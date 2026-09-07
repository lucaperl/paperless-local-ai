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
    // Compare fixed-size digests so the comparison does not reveal a useful prefix.
    Sha256::digest(value.as_bytes()) == Sha256::digest(expected.as_bytes())
}

fn require_auth(headers: &HeaderMap) -> Option<Response> {
    if relay_authorized(headers) {
        None
    } else {
        Some(error_response(StatusCode::UNAUTHORIZED, "unauthorized"))
    }
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
            "last_error": null
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

async fn spawn_chat(state: Arc<CoreState>, job_id: String, body: Bytes) -> Result<()> {
    fs::create_dir_all(RAG_JOB_DIR)?;
    let request_path = PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.request.json"));
    atomic_write(&request_path, &body)?;
    let _ = fs::remove_file(PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.stop")));

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
        let job_path = PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.json"));
        let failure = match result {
            Ok(status) if !status.success() => Some(format!("RAG helper exited with {status}")),
            Ok(_) => None,
            Err(error) => Some(format!("RAG helper wait failed: {error}")),
        };
        if let Some(error) = failure {
            eprintln!("[RAG] chat job {job_id}: {error}");
            if !job_path.exists() {
                let payload = serde_json::json!({
                    "job_id": &job_id,
                    "status": "error",
                    "phase": "error",
                    "answer": "",
                    "sources": [],
                    "error": &error,
                });
                if let Ok(bytes) = serde_json::to_vec_pretty(&payload) {
                    let _ = atomic_write(&job_path, &bytes);
                }
            }
        } else if !job_path.exists() {
            let payload = serde_json::json!({
                "job_id": &job_id,
                "status": "error",
                "phase": "error",
                "answer": "",
                "sources": [],
                "error": "RAG helper exited without creating job state",
            });
            if let Ok(bytes) = serde_json::to_vec_pretty(&payload) {
                let _ = atomic_write(&job_path, &bytes);
            }
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
    json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config": rag_config(),
            "state": rag_state(),
        }),
    )
}

pub async fn status(State(_state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
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

pub async fn chat_start(
    State(state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    if body.is_empty() || body.len() > MAX_CHAT_BODY_BYTES {
        return error_response(StatusCode::BAD_REQUEST, "invalid chat request size");
    }
    if serde_json::from_slice::<Value>(&body).is_err() {
        return error_response(StatusCode::BAD_REQUEST, "chat request must be valid JSON");
    }
    let job_id = new_job_id();
    match spawn_chat(state, job_id.clone(), body).await {
        Ok(()) => json_response(StatusCode::ACCEPTED, serde_json::json!({"job_id": job_id})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
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
    let payload: Value = match serde_json::from_slice(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(job_id) = value_job_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid job_id is required");
    };
    let path = PathBuf::from(RAG_JOB_DIR).join(format!("{job_id}.json"));
    if !path.exists() {
        return error_response(StatusCode::NOT_FOUND, "chat job not found");
    }
    json_response(StatusCode::OK, read_json_or(path, serde_json::json!({})))
}

pub async fn chat_stop(
    State(_state): State<Arc<CoreState>>,
    headers: HeaderMap,
    body: Bytes,
) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
    }
    let payload: Value = match serde_json::from_slice(&body) {
        Ok(value) => value,
        Err(error) => return error_response(StatusCode::BAD_REQUEST, error),
    };
    let Some(job_id) = value_job_id(&payload) else {
        return error_response(StatusCode::BAD_REQUEST, "valid job_id is required");
    };
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
    match spawn_index_job(state, "rebuild").await {
        Ok(()) => json_response(StatusCode::ACCEPTED, serde_json::json!({"started": true})),
        Err(error) => error_response(StatusCode::INTERNAL_SERVER_ERROR, error),
    }
}

pub async fn index_sync(State(state): State<Arc<CoreState>>, headers: HeaderMap) -> Response {
    if let Some(response) = require_auth(&headers) {
        return response;
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
    // Do not create the expensive first index automatically. Once an active
    // index exists, run lightweight incremental checks on the configured cadence.
    loop {
        let wait = Duration::from_secs(sync_interval_seconds());
        tokio::select! {
            _ = tokio::time::sleep(wait) => {}
            changed = shutdown.changed() => {
                if changed.is_err() || *shutdown.borrow() {
                    return Ok(());
                }
                continue;
            }
        }
        if *shutdown.borrow() {
            return Ok(());
        }
        if !Path::new(RAG_DB_FILE).exists() || Path::new(RAG_PAUSE_FILE).exists() {
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
    use super::valid_job_id;

    #[test]
    fn job_ids_are_path_safe() {
        assert!(valid_job_id("abc-123_DEF"));
        assert!(!valid_job_id("../../escape"));
        assert!(!valid_job_id("contains space"));
        assert!(!valid_job_id(""));
    }
}
