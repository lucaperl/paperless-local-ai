use crate::chat_history;
use crate::error::{Error, Result};
use crate::state::CoreState;
use axum::Json;
use axum::body::Bytes;
use axum::extract::State;
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{IntoResponse, Response};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::time::{Duration, SystemTime, UNIX_EPOCH};
use tokio::process::Command;
use tokio::sync::watch;

const RAG_DIR: &str = "/data/rag";
const RAG_STATE_FILE: &str = "/data/rag/state.json";
const RAG_CONFIG_FILE: &str = "/config/rag-config.json";
const RAG_DB_FILE: &str = "/data/rag/rag.db";
const RAG_BUILD_DB_FILE: &str = "/data/rag/rag.db.build";
const RAG_JOB_DIR: &str = "/data/rag/jobs";
const RAG_PAUSE_FILE: &str = "/data/rag/pause";
const RELAY_SECRET_FILE: &str = "/integration/paperless-local-ai-relay.secret";
const RAG_ENGINE: &str = "/app/rag_engine.py";
const MAX_CHAT_BODY_BYTES: usize = 256_000;
const DEFAULT_SYNC_SECONDS: u64 = 900;

static ACTIVE_RAG_JOBS: AtomicUsize = AtomicUsize::new(0);

const DEFAULT_RAG_CONFIG: &str = r#"{
  "version": 1,
  "embedding_model": "qwen3-embedding:4b-q4_K_M",
  "chunk_target_chars": 4000,
  "chunk_overlap_chars": 800,
  "embedding_batch_size": 16,
  "embedding_slice_chunks": 64,
  "sync_interval_seconds": 900,
  "chat_defaults": {
    "model": "qwen3.5:4b",
    "think": "off",
    "num_ctx": 8192,
    "top_k": 5,
    "temperature": 0.1,
    "num_predict": 512
  }
}"#;

fn json_response(status: StatusCode, value: Value) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert("cache-control", HeaderValue::from_static("no-store"));
    (status, headers, Json(value)).into_response()
}

fn error_response(status: StatusCode, message: impl std::fmt::Display) -> Response {
    json_response(status, serde_json::json!({"error": message.to_string()}))
}

fn relay_secret() -> Result<String> {
    let value = fs::read_to_string(RELAY_SECRET_FILE)
        .map_err(|error| Error::Config(format!("RAG relay secret is unavailable: {error}")))?;
    let value = value.trim().to_owned();
    if value.len() < 32 {
        return Err(Error::Config("RAG relay secret is invalid".into()));
    }
    Ok(value)
}

fn relay_authorized(headers: &HeaderMap) -> bool {
    let Ok(secret) = relay_secret() else {
        return false;
    };
    let Some(value) = headers
        .get("authorization")
        .and_then(|value| value.to_str().ok())
    else {
        return false;
    };
    let expected = format!("Bearer {secret}");
    Sha256::digest(value.as_bytes()) == Sha256::digest(expected.as_bytes())
}

fn require_auth(headers: &HeaderMap) -> Option<Response> {
    if relay_authorized(headers) {
        None
    } else {
        Some(error_response(StatusCode::UNAUTHORIZED, "unauthorized"))
    }
}

fn relay_user_id(headers: &HeaderMap) -> Option<i64> {
    headers
        .get("x-paperless-user-id")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<i64>().ok())
        .filter(|value| *value > 0)
}

fn read_json_or(path: impl AsRef<Path>, fallback: Value) -> Value {
    fs::read_to_string(path)
        .ok()
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or(fallback)
}

fn rag_config() -> Value {
    read_json_or(
        RAG_CONFIG_FILE,
        serde_json::from_str(DEFAULT_RAG_CONFIG).expect("default RAG config is valid JSON"),
    )
}

fn rag_state() -> Value {
    let mut state = read_json_or(
        RAG_STATE_FILE,
        serde_json::json!({
            "version": 1,
            "running": false,
            "paused": Path::new(RAG_PAUSE_FILE).exists(),
            "operation": null,
            "phase": if Path::new(RAG_DB_FILE).exists() { "idle" } else { "not_built" },
            "current": 0,
            "total": 0,
            "indexed_documents": 0,
            "indexed_chunks": 0,
            "last_sync": null,
            "last_build": null,
            "last_error": null,
            "rebuild_required": false
        }),
    );
    if let Some(object) = state.as_object_mut() {
        object.insert(
            "index_exists".into(),
            Value::Bool(Path::new(RAG_DB_FILE).exists()),
        );
        object.insert(
            "paused".into(),
            Value::Bool(Path::new(RAG_PAUSE_FILE).exists()),
        );
    }
    state
}

pub fn reconcile_startup_state() -> Result<()> {
    let state_path = Path::new(RAG_STATE_FILE);
    if !state_path.exists() {
        return Ok(());
    }

    let mut state = read_json_or(state_path, serde_json::json!({}));
    let Some(object) = state.as_object_mut() else {
        return Ok(());
    };

    let running = object
        .get("running")
        .and_then(Value::as_bool)
        .unwrap_or(false);
    let operation = object
        .get("operation")
        .and_then(Value::as_str)
        .map(str::to_owned);
    let phase = object
        .get("phase")
        .and_then(Value::as_str)
        .map(str::to_owned);

    let interrupted_rebuild = operation.as_deref() == Some("rebuild")
        && Path::new(RAG_BUILD_DB_FILE).exists()
        && (running || phase.as_deref() == Some("paused"));

    if interrupted_rebuild {
        atomic_write(Path::new(RAG_PAUSE_FILE), b"paused\n")?;
        object.insert("running".into(), Value::Bool(false));
        object.insert("paused".into(), Value::Bool(true));
        object.insert("phase".into(), Value::String("paused".into()));
        atomic_write(state_path, &serde_json::to_vec_pretty(&state)?)?;
        println!(
            "[RAG] interrupted rebuild staging index found; keeping it paused for explicit Resume"
        );
        return Ok(());
    }

    if running {
        object.insert("running".into(), Value::Bool(false));
        object.insert("operation".into(), Value::Null);
        object.insert(
            "phase".into(),
            Value::String(
                if Path::new(RAG_DB_FILE).exists() {
                    "idle"
                } else {
                    "not_built"
                }
                .into(),
            ),
        );
        object.insert(
            "paused".into(),
            Value::Bool(Path::new(RAG_PAUSE_FILE).exists()),
        );
        atomic_write(state_path, &serde_json::to_vec_pretty(&state)?)?;
        println!("[RAG] cleared stale running index state after core restart");
    }

    Ok(())
}

fn valid_job_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn value_job_id(payload: &Value) -> Option<&str> {
    payload
        .get("job_id")
        .and_then(Value::as_str)
        .filter(|value| valid_job_id(value))
}

fn value_conversation_id(payload: &Value) -> Option<&str> {
    payload
        .get("conversation_id")
        .and_then(Value::as_str)
        .filter(|value| valid_job_id(value))
}

fn new_job_id() -> String {
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let pid = std::process::id();
    let digest = Sha256::digest(format!("{pid}:{nanos}").as_bytes());
    digest[..16]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn atomic_write(path: &Path, bytes: &[u8]) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let nonce = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_nanos();
    let tmp = path.with_extension(format!("tmp-{}-{nonce}", std::process::id()));
    {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&tmp)?;
        file.write_all(bytes)?;
        file.sync_all()?;
    }
    fs::rename(tmp, path)?;
    Ok(())
}

fn body_json(body: &Bytes) -> serde_json::Result<Value> {
    serde_json::from_slice(body)
}

fn job_path(job_id: &str) -> PathBuf {
    PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.json"))
}

fn job_belongs_to_user(job: &Value, user_id: i64) -> bool {
    job.get("user_id").and_then(Value::as_i64) == Some(user_id)
}

async fn spawn_chat(
    state: Arc<CoreState>,
    job_id: String,
    user_id: i64,
    conversation_id: String,
    body: Bytes,
) -> Result<()> {
    fs::create_dir_all(RAG_JOB_DIR)?;
    let request_path = PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.request.json"));
    atomic_write(&request_path, &body)?;
    let _ = fs::remove_file(PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.stop")));
    let queued = serde_json::json!({
        "job_id": &job_id,
        "user_id": user_id,
        "conversation_id": &conversation_id,
        "status": "running",
        "phase": "waiting",
        "answer": "",
        "sources": [],
        "metrics": {},
        "error": null
    });
    atomic_write(&job_path(&job_id), &serde_json::to_vec_pretty(&queued)?)?;

    let mut child = Command::new("python")
        .arg(RAG_ENGINE)
        .arg("chat")
        .arg("--job-id")
        .arg(&job_id)
        .arg("--request")
        .arg(&request_path)
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()?;

    ACTIVE_RAG_JOBS.fetch_add(1, Ordering::SeqCst);
    state.recycle.cancel();
    tokio::spawn(async move {
        let result = child.wait().await;
        let _ = fs::remove_file(&request_path);
        let path = job_path(&job_id);
        let failure = match result {
            Ok(status) if !status.success() => Some(format!("RAG helper exited with {status}")),
            Ok(_) => None,
            Err(error) => Some(format!("RAG helper wait failed: {error}")),
        };
        if let Some(error) = failure.as_ref() {
            eprintln!("[RAG] chat job {job_id}: {error}");
            if !path.exists() {
                let payload = serde_json::json!({
                    "job_id": &job_id,
                    "user_id": user_id,
                    "conversation_id": &conversation_id,
                    "status": "error",
                    "phase": "error",
                    "answer": "",
                    "sources": [],
                    "metrics": {},
                    "error": &error,
                });
                if let Ok(bytes) = serde_json::to_vec_pretty(&payload) {
                    let _ = atomic_write(&path, &bytes);
                }
            }
        }
        let mut job = read_json_or(&path, serde_json::json!({}));
        if !job.is_object() {
            job = serde_json::json!({});
        }
        let terminal = matches!(
            job.get("status").and_then(Value::as_str),
            Some("done" | "error" | "stopped")
        );
        if !terminal {
            let error =
                failure.unwrap_or_else(|| "RAG helper exited without a terminal job state".into());
            job = serde_json::json!({
                "job_id": &job_id,
                "user_id": user_id,
                "conversation_id": &conversation_id,
                "status": "error",
                "phase": "error",
                "answer": job.get("answer").and_then(Value::as_str).unwrap_or_default(),
                "sources": job.get("sources").cloned().unwrap_or_else(|| serde_json::json!([])),
                "metrics": job.get("metrics").cloned().unwrap_or_else(|| serde_json::json!({})),
                "error": error
            });
            if let Ok(bytes) = serde_json::to_vec_pretty(&job) {
                let _ = atomic_write(&path, &bytes);
            }
        }
        if let Err(error) = chat_history::finish_turn(user_id, &conversation_id, &job_id, &job) {
            eprintln!("[RAG] chat history finalize failed for {job_id}: {error}");
        }
        if ACTIVE_RAG_JOBS.fetch_sub(1, Ordering::SeqCst) == 1 {
            state.recycle.schedule();
        }
    });
    Ok(())
}

async fn spawn_index_job(state: Arc<CoreState>, operation: &'static str) -> Result<()> {
    fs::create_dir_all(RAG_DIR)?;
    if operation == "rebuild" {
        let _ = fs::remove_file(RAG_PAUSE_FILE);
    }
    let mut child = Command::new("python")
        .arg(RAG_ENGINE)
        .arg(operation)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .kill_on_drop(true)
        .spawn()?;
    ACTIVE_RAG_JOBS.fetch_add(1, Ordering::SeqCst);
    state.recycle.cancel();
    tokio::spawn(async move {
        if let Err(error) = child.wait().await {
            eprintln!("[RAG] {operation} wait failed: {error}");
        }
        if ACTIVE_RAG_JOBS.fetch_sub(1, Ordering::SeqCst) == 1 {
            state.recycle.schedule();
        }
    });
    Ok(())
}

pub async fn bootstrap(State(_state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "user_id": user_id,
            "config": rag_config(),
            "state": rag_state(),
        }),
    )
}

pub async fn status(State(_state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    json_response(
        StatusCode::OK,
        serde_json::json!({"config": rag_config(), "state": rag_state()}),
    )
}

pub async fn models(State(state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    let base = match state.app_config.load() {
        Ok(config) => config.connections.ollama_url,
        Err(error) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    };
    let response = state
        .http
        .inner()
        .get(format!("{base}/api/tags"))
        .timeout(Duration::from_secs(15))
        .send()
        .await;
    match response {
        Ok(response) => match response.error_for_status() {
            Ok(response) => match response.json::<Value>().await {
                Ok(value) => {
                    let names = value
                        .get("models")
                        .and_then(Value::as_array)
                        .into_iter()
                        .flatten()
                        .filter_map(|item| item.get("name").and_then(Value::as_str))
                        .map(str::to_owned)
                        .collect::<Vec<_>>();
                    json_response(StatusCode::OK, serde_json::json!({"models": names}))
                }
                Err(error) => error_response(StatusCode::BAD_GATEWAY, error),
            },
            Err(error) => error_response(StatusCode::BAD_GATEWAY, error),
        },
        Err(error) => error_response(StatusCode::BAD_GATEWAY, error),
    }
}

pub async fn conversations_list(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    match chat_history::list(user_id) {
        Ok(value) => json_response(StatusCode::OK, value),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

pub async fn conversations_create(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    match chat_history::create(
        user_id,
        payload
            .get("scope")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({"type":"all"})),
        payload
            .get("settings")
            .cloned()
            .unwrap_or_else(|| serde_json::json!({})),
    ) {
        Ok(value) => json_response(StatusCode::CREATED, value),
        Err(error) => error_response(StatusCode::BAD_REQUEST, error),
    }
}

pub async fn conversations_get(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(conversation_id) = value_conversation_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid conversation_id is required");
    };
    match chat_history::get(user_id, conversation_id) {
        Ok(value) => json_response(StatusCode::OK, value),
        Err(Error::Io(error)) if error.kind() == std::io::ErrorKind::NotFound => {
            error_response(StatusCode::NOT_FOUND, "chat not found")
        }
        Err(error) => error_response(StatusCode::BAD_REQUEST, error),
    }
}

pub async fn conversations_rename(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(conversation_id) = value_conversation_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid conversation_id is required");
    };
    let title = payload
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or_default();
    match chat_history::rename(user_id, conversation_id, title) {
        Ok(value) => json_response(StatusCode::OK, value),
        Err(error) => error_response(StatusCode::BAD_REQUEST, error),
    }
}

pub async fn conversations_delete(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(conversation_id) = value_conversation_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid conversation_id is required");
    };
    match chat_history::delete(user_id, conversation_id) {
        Ok(()) => json_response(StatusCode::OK, serde_json::json!({"deleted": true})),
        Err(error) => error_response(StatusCode::BAD_REQUEST, error),
    }
}

fn merged_config_u64(payload: &Value, current: &Value, key: &str) -> std::result::Result<u64, String> {
    match payload.get(key) {
        Some(value) => value
            .as_u64()
            .ok_or_else(|| format!("{key} must be a non-negative integer")),
        None => current
            .get(key)
            .and_then(Value::as_u64)
            .ok_or_else(|| format!("{key} is missing from the current config")),
    }
}

fn merge_index_config(payload: &Value, current: &Value) -> std::result::Result<Value, String> {
    let model = match payload.get("embedding_model") {
        Some(value) => value
            .as_str()
            .ok_or_else(|| "embedding_model must be a string".to_owned())?,
        None => current
            .get("embedding_model")
            .and_then(Value::as_str)
            .ok_or_else(|| "embedding_model is missing from the current config".to_owned())?,
    }
    .trim()
    .to_owned();

    if model.is_empty() || model.len() > 200 {
        return Err("embedding_model must contain 1 to 200 characters".into());
    }

    let chunk_target = merged_config_u64(payload, current, "chunk_target_chars")?;
    let chunk_overlap = merged_config_u64(payload, current, "chunk_overlap_chars")?;
    let batch = merged_config_u64(payload, current, "embedding_batch_size")?;
    let slice = merged_config_u64(payload, current, "embedding_slice_chunks")?;
    let sync_interval = merged_config_u64(payload, current, "sync_interval_seconds")?;

    if !(1000..=20_000).contains(&chunk_target) {
        return Err("chunk_target_chars must be between 1000 and 20000".into());
    }
    if chunk_overlap >= chunk_target {
        return Err("chunk_overlap_chars must be smaller than chunk_target_chars".into());
    }
    if !(1..=64).contains(&batch) {
        return Err("embedding_batch_size must be between 1 and 64".into());
    }
    if slice < batch || slice > 256 {
        return Err("embedding_slice_chunks must be between embedding_batch_size and 256".into());
    }
    if !(60..=86_400).contains(&sync_interval) {
        return Err("sync_interval_seconds must be between 60 and 86400".into());
    }

    let mut next = current.clone();
    next["embedding_model"] = Value::String(model);
    next["chunk_target_chars"] = Value::from(chunk_target);
    next["chunk_overlap_chars"] = Value::from(chunk_overlap);
    next["embedding_batch_size"] = Value::from(batch);
    next["embedding_slice_chunks"] = Value::from(slice);
    next["sync_interval_seconds"] = Value::from(sync_interval);
    Ok(next)
}

fn rebuild_required_for_config(config: &Value, state: &Value) -> bool {
    let Some(active) = state.get("active_signature") else {
        return state
            .get("rebuild_required")
            .and_then(Value::as_bool)
            .unwrap_or(false);
    };

    active.get("embedding_model").and_then(Value::as_str)
        != config.get("embedding_model").and_then(Value::as_str)
        || active.get("chunk_target_chars").and_then(Value::as_u64)
            != config.get("chunk_target_chars").and_then(Value::as_u64)
        || active.get("chunk_overlap_chars").and_then(Value::as_u64)
            != config.get("chunk_overlap_chars").and_then(Value::as_u64)
}

pub async fn config_save(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    if rag_state()
        .get("running")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return error_response(
            StatusCode::CONFLICT,
            "cannot change index settings while an index job is running",
        );
    }
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let current = rag_config();
    let config = match merge_index_config(&payload, &current) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };

    let mut bytes = match serde_json::to_vec_pretty(&config) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    };
    bytes.push(b'\n');
    if let Err(error) = atomic_write(Path::new(RAG_CONFIG_FILE), &bytes) {
        return error_response(StatusCode::INTERNAL_SERVER_ERROR, error);
    }

    if Path::new(RAG_DB_FILE).exists() {
        let mut state = rag_state();
        state["rebuild_required"] = Value::Bool(rebuild_required_for_config(&config, &state));
        if let Ok(mut data) = serde_json::to_vec_pretty(&state) {
            data.push(b'\n');
            let _ = atomic_write(Path::new(RAG_STATE_FILE), &data);
        }
    }

    json_response(
        StatusCode::OK,
        serde_json::json!({"config": config, "state": rag_state()}),
    )
}

pub async fn chat_start(
    State(state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    if body.is_empty() || body.len() > MAX_CHAT_BODY_BYTES {
        return error_response(StatusCode::BAD_REQUEST, "invalid chat request size");
    }
    let mut payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(conversation_id) = value_conversation_id(&payload).map(str::to_owned) else {
        return error_response(StatusCode::BAD_REQUEST, "valid conversation_id is required");
    };
    let question = payload
        .get("question")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim()
        .to_owned();
    if question.is_empty() {
        return error_response(StatusCode::BAD_REQUEST, "question must not be empty");
    }
    let scope = serde_json::json!({
        "type": payload.get("scope").and_then(Value::as_str).unwrap_or("all"),
        "id": payload.get("scope_id"),
        "label": payload.get("scope_label"),
        "document_id": payload.get("document_id")
    });
    let settings = payload
        .get("settings")
        .cloned()
        .unwrap_or_else(|| serde_json::json!({}));
    let job_id = new_job_id();
    let history = match chat_history::begin_turn(
        user_id,
        &conversation_id,
        &job_id,
        &question,
        scope,
        settings,
    ) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::CONFLICT, error),
    };
    payload["history"] = history;
    payload["_plai_user_id"] = Value::from(user_id);
    payload["_plai_conversation_id"] = Value::String(conversation_id.clone());
    let encoded = match serde_json::to_vec(&payload) {
        Ok(value) => Bytes::from(value),
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    match spawn_chat(
        state,
        job_id.clone(),
        user_id,
        conversation_id.clone(),
        encoded,
    )
    .await
    {
        Ok(()) => json_response(
            StatusCode::ACCEPTED,
            serde_json::json!({
                "job_id": job_id,
                "conversation_id": conversation_id
            }),
        ),
        Err(error) => {
            let job = serde_json::json!({"status":"error","answer":"","sources":[],"metrics":{},"error":error.to_string()});
            let _ = chat_history::finish_turn(user_id, &conversation_id, &job_id, &job);
            error_response(StatusCode::INTERNAL_SERVER_ERROR, error)
        }
    }
}

pub async fn chat_status(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(job_id) = value_job_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid job_id is required");
    };
    let path = job_path(job_id);
    if !path.exists() {
        return error_response(StatusCode::NOT_FOUND, "chat job not found");
    }
    let job = read_json_or(path, serde_json::json!({}));
    if !job_belongs_to_user(&job, user_id) {
        return error_response(StatusCode::NOT_FOUND, "chat job not found");
    }
    json_response(StatusCode::OK, job)
}

pub async fn chat_stop(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let Some(user_id) = relay_user_id(&headers) else {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    };
    let payload = match body_json(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(job_id) = value_job_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid job_id is required");
    };
    let job = read_json_or(job_path(job_id), serde_json::json!({}));
    if !job_belongs_to_user(&job, user_id) {
        return error_response(StatusCode::NOT_FOUND, "chat job not found");
    }
    let path = PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.stop"));
    match atomic_write(&path, b"stop\n") {
        Ok(()) => json_response(StatusCode::OK, serde_json::json!({"stopping": true})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

pub async fn index_rebuild(State(state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    match spawn_index_job(state, "rebuild").await {
        Ok(()) => json_response(StatusCode::ACCEPTED, serde_json::json!({"started": true})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

pub async fn index_sync(State(state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    if rag_state()
        .get("rebuild_required")
        .and_then(Value::as_bool)
        .unwrap_or(false)
    {
        return error_response(
            StatusCode::CONFLICT,
            "index settings changed; rebuild required before sync",
        );
    }
    match spawn_index_job(state, "sync").await {
        Ok(()) => json_response(StatusCode::ACCEPTED, serde_json::json!({"started": true})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

pub async fn index_pause(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if relay_user_id(&headers).is_none() {
        return error_response(
            StatusCode::UNAUTHORIZED,
            "Paperless user identity is missing",
        );
    }
    let payload: Value = serde_json::from_slice(&body).unwrap_or_else(|_| serde_json::json!({}));
    let paused = payload
        .get("paused")
        .and_then(Value::as_bool)
        .unwrap_or(true);
    let result = if paused {
        atomic_write(Path::new(RAG_PAUSE_FILE), b"paused\n")
    } else {
        match fs::remove_file(RAG_PAUSE_FILE) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error.into()),
        }
    };
    match result {
        Ok(()) => json_response(StatusCode::OK, serde_json::json!({"paused": paused})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

fn sync_interval_seconds() -> u64 {
    rag_config()
        .get("sync_interval_seconds")
        .and_then(Value::as_u64)
        .unwrap_or(DEFAULT_SYNC_SECONDS)
        .clamp(60, 86_400)
}

pub async fn sync_loop(state: Arc<CoreState>, mut shutdown: watch::Receiver<bool>) -> Result<()> {
    loop {
        let wait = Duration::from_secs(sync_interval_seconds());
        tokio::select! {
            _ = tokio::time::sleep(wait) => {}
            changed = shutdown.changed() => {
                if changed.is_err() || *shutdown.borrow() { return Ok(()); }
                continue;
            }
        }
        if *shutdown.borrow() {
            return Ok(());
        }
        let current = rag_state();
        if !Path::new(RAG_DB_FILE).exists()
            || Path::new(RAG_PAUSE_FILE).exists()
            || current
                .get("rebuild_required")
                .and_then(Value::as_bool)
                .unwrap_or(false)
        {
            continue;
        }

        let was_scheduled = state.recycle.is_scheduled();
        if was_scheduled {
            state.recycle.cancel();
        }
        let mut child = match Command::new("python")
            .arg(RAG_ENGINE)
            .arg("sync")
            .arg("--quiet")
            .stdin(Stdio::null())
            .stdout(Stdio::null())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .spawn()
        {
            Ok(child) => child,
            Err(error) => {
                eprintln!("[RAG] automatic sync could not start: {error}");
                if was_scheduled && ACTIVE_RAG_JOBS.load(Ordering::SeqCst) == 0 {
                    state.recycle.schedule();
                }
                continue;
            }
        };
        ACTIVE_RAG_JOBS.fetch_add(1, Ordering::SeqCst);
        state.recycle.cancel();
        if let Err(error) = child.wait().await {
            eprintln!("[RAG] automatic sync wait failed: {error}");
        }
        let remaining = ACTIVE_RAG_JOBS.fetch_sub(1, Ordering::SeqCst) - 1;
        if was_scheduled && remaining == 0 {
            state.recycle.schedule();
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{merge_index_config, valid_job_id};
    use serde_json::json;

    #[test]
    fn job_ids_are_path_safe() {
        assert!(valid_job_id("abc-123_DEF"));
        assert!(!valid_job_id("../../escape"));
        assert!(!valid_job_id("contains space"));
        assert!(!valid_job_id(""));
    }

    #[test]
    fn index_config_accepts_complete_valid_settings() {
        let current = json!({
            "embedding_model": "old",
            "chunk_target_chars": 4000,
            "chunk_overlap_chars": 800,
            "embedding_batch_size": 16,
            "embedding_slice_chunks": 64,
            "sync_interval_seconds": 900
        });
        let payload = json!({
            "embedding_model": "qwen3-embedding:4b-q4_K_M",
            "chunk_target_chars": 4000,
            "chunk_overlap_chars": 800,
            "embedding_batch_size": 1,
            "embedding_slice_chunks": 16,
            "sync_interval_seconds": 900
        });
        let merged = merge_index_config(&payload, &current).expect("valid index config");
        assert_eq!(merged["embedding_batch_size"], 1);
        assert_eq!(merged["embedding_slice_chunks"], 16);
    }

    #[test]
    fn index_config_rejects_invalid_relationships() {
        let current = json!({
            "embedding_model": "model",
            "chunk_target_chars": 4000,
            "chunk_overlap_chars": 800,
            "embedding_batch_size": 16,
            "embedding_slice_chunks": 64,
            "sync_interval_seconds": 900
        });
        assert!(merge_index_config(&json!({"chunk_overlap_chars": 4000}), &current).is_err());
        assert!(merge_index_config(
            &json!({"embedding_batch_size": 32, "embedding_slice_chunks": 16}),
            &current
        )
        .is_err());
    }
}
