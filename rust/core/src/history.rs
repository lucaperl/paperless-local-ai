use crate::ai_lock;
use crate::app_config::AppConfig;
use crate::error::{Error, Result};
use crate::paperless::{PaperlessClient, PaperlessDocument, Taxonomy};
use crate::prompt::{PromptConfig, TaggingContext, TaggingMode};
use serde_json::Value;
use std::collections::{BTreeMap, HashMap};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Stdio;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader};
use tokio::process::{Child, ChildStdin, ChildStdout, Command};
use tokio::sync::{Mutex, watch};
use tokio::time::timeout;

#[cfg(unix)]
use std::os::unix::fs::PermissionsExt;
#[cfg(unix)]
use tokio::io::AsyncReadExt;
#[cfg(unix)]
use tokio::net::{UnixListener, UnixStream};

pub const HISTORY_CACHE_FILE: &str = "/data/history-cache/index.pkl";
pub const HISTORY_META_FILE: &str = "/data/history-cache/index-meta.json";
pub const HISTORY_BROKER_SOCKET: &str = "/coordination/history-broker.sock";
pub const HISTORY_PROTOCOL_MAX_BYTES: usize = 32 * 1024 * 1024;
pub const HISTORY_CACHE_FORMAT_VERSION: u64 = 1;
pub const HISTORY_ALGORITHM_VERSION: &str = "tfidf-word12-char35-nearest-neighbors-cosine-v1";

pub const FAST_SIMILARITY: f64 = 0.60;
pub const FAMILY_SIMILARITY: f64 = 0.50;
pub const EXAMPLE_MIN_SIMILARITY: f64 = 0.08;
pub const TOP_VOTE_NEIGHBORS: u64 = 5;
pub const QUERY_NEIGHBORS: u64 = 30;
pub const MIN_SUPPORT: u64 = 2;
pub const MIN_WINNER_SHARE: f64 = 0.50;
pub const MAX_EXAMPLES: u64 = 5;
pub const MAX_EXAMPLES_PER_TAG_SET: u64 = 2;
pub const MAX_DIAGNOSTIC_DOCS: u64 = 2000;

struct Engine {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
    last_use: Instant,
}

#[derive(Default)]
struct HistoryInner {
    engine: Option<Engine>,
}

pub struct HistoryManager {
    inner: Mutex<HistoryInner>,
    #[cfg_attr(not(unix), allow(dead_code))]
    socket_path: PathBuf,
    engine_script: PathBuf,
    python: String,
    idle: Duration,
    engine_timeout: Duration,
    shutdown_timeout: Duration,
    ai_lock_path: PathBuf,
    protocol_max_bytes: usize,
}

impl HistoryManager {
    pub fn from_env() -> Self {
        Self {
            inner: Mutex::new(HistoryInner::default()),
            socket_path: std::env::var_os("PLAI_HISTORY_BROKER_SOCKET")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from(HISTORY_BROKER_SOCKET)),
            engine_script: std::env::var_os("PLAI_HISTORY_ENGINE_SCRIPT")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("/app/history_engine.py")),
            python: std::env::var("PLAI_HISTORY_PYTHON").unwrap_or_else(|_| "python".into()),
            idle: Duration::from_secs_f64(
                env_f64("PLAI_HISTORY_ENGINE_IDLE_SECONDS", 30.0).max(0.0),
            ),
            engine_timeout: Duration::from_secs_f64(
                env_f64("PLAI_HISTORY_ENGINE_TIMEOUT_SECONDS", 900.0).max(1.0),
            ),
            shutdown_timeout: Duration::from_secs_f64(
                env_f64("PLAI_HISTORY_ENGINE_SHUTDOWN_TIMEOUT_SECONDS", 5.0).max(0.5),
            ),
            ai_lock_path: ai_lock::configured_ai_lock_path(),
            protocol_max_bytes: std::env::var("PLAI_HISTORY_PROTOCOL_MAX_BYTES")
                .ok()
                .and_then(|value| value.parse().ok())
                .unwrap_or(HISTORY_PROTOCOL_MAX_BYTES),
        }
    }

    async fn start_engine_locked(&self, inner: &mut HistoryInner) -> Result<()> {
        if let Some(engine) = inner.engine.as_mut() {
            if engine.child.try_wait()?.is_none() {
                return Ok(());
            }
            inner.engine = None;
        }

        let mut command = Command::new(&self.python);
        command
            .arg(&self.engine_script)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::inherit())
            .kill_on_drop(true)
            .env("OMP_NUM_THREADS", "1")
            .env("OPENBLAS_NUM_THREADS", "1")
            .env("MKL_NUM_THREADS", "1")
            .env("BLIS_NUM_THREADS", "1")
            .env("PYTHONUNBUFFERED", "1");

        let mut child = command.spawn()?;
        let stdin = child
            .stdin
            .take()
            .ok_or_else(|| Error::Invalid("History engine stdin could not be created".into()))?;
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| Error::Invalid("History engine stdout could not be created".into()))?;
        let pid = child.id();
        inner.engine = Some(Engine {
            child,
            stdin,
            stdout: BufReader::new(stdout),
            last_use: Instant::now(),
        });
        println!("[HISTORY-BROKER] started engine pid={pid:?}");
        Ok(())
    }

    async fn engine_request_locked(
        &self,
        inner: &mut HistoryInner,
        payload: &Value,
    ) -> Result<Value> {
        self.start_engine_locked(inner).await?;
        let engine = inner
            .engine
            .as_mut()
            .ok_or_else(|| Error::Invalid("History engine was not retained after start".into()))?;
        let mut encoded = serde_json::to_vec(payload)?;
        encoded.push(b'\n');
        if encoded.len() > self.protocol_max_bytes {
            return Err(Error::Invalid(
                "History engine request exceeded the protocol limit".into(),
            ));
        }
        engine.stdin.write_all(&encoded).await?;
        engine.stdin.flush().await?;

        let mut line = String::new();
        let bytes = timeout(self.engine_timeout, engine.stdout.read_line(&mut line))
            .await
            .map_err(|_| {
                Error::Invalid(format!(
                    "History engine did not respond within {} seconds",
                    self.engine_timeout.as_secs_f64()
                ))
            })??;
        if bytes == 0 {
            return Err(Error::Invalid(format!(
                "History engine exited with code {:?}",
                engine.child.try_wait()?.and_then(|status| status.code())
            )));
        }
        if line.len() > self.protocol_max_bytes {
            return Err(Error::Invalid(
                "History engine response exceeded the protocol limit".into(),
            ));
        }
        let response: Value = serde_json::from_str(line.trim_end())?;
        if !response.is_object() {
            return Err(Error::Invalid(
                "History engine returned a non-object response".into(),
            ));
        }
        engine.last_use = Instant::now();
        Ok(response)
    }

    async fn stop_engine_locked(&self, inner: &mut HistoryInner) {
        let Some(mut engine) = inner.engine.take() else {
            return;
        };
        let pid = engine.child.id();

        if engine.child.try_wait().ok().flatten().is_none() {
            let graceful = async {
                engine.stdin.write_all(b"{\"op\":\"shutdown\"}\n").await?;
                engine.stdin.flush().await?;
                let mut line = String::new();
                let bytes = engine.stdout.read_line(&mut line).await?;
                if bytes == 0 {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::UnexpectedEof,
                        "History engine closed stdout during shutdown",
                    ));
                }
                let _ = engine.child.wait().await?;
                Ok::<(), std::io::Error>(())
            };

            if !matches!(timeout(self.shutdown_timeout, graceful).await, Ok(Ok(()))) {
                let _ = engine.child.start_kill();
                let _ = timeout(Duration::from_secs(2), engine.child.wait()).await;
            }
        }
        println!("[HISTORY-BROKER] stopped engine pid={pid:?}");
    }

    async fn request_engine(&self, payload: &Value) -> Result<Value> {
        for attempt in 0..2 {
            let mut inner = self.inner.lock().await;
            match self.engine_request_locked(&mut inner, payload).await {
                Ok(response) => return Ok(response),
                Err(error) => {
                    self.stop_engine_locked(&mut inner).await;
                    if attempt == 1 {
                        return Err(error);
                    }
                }
            }
        }
        unreachable!()
    }

    pub async fn request(&self, mut payload: Value) -> Result<Value> {
        let shutdown_after = payload
            .as_object_mut()
            .and_then(|object| object.remove("shutdown_after"))
            .and_then(|value| value.as_bool())
            .unwrap_or(false);

        if payload.get("op").and_then(Value::as_str) == Some("release") {
            self.release().await;
            return Ok(serde_json::json!({"released": true}));
        }

        let _guard = ai_lock::acquire(&self.ai_lock_path).await?;
        let response = self.request_engine(&payload).await?;
        if shutdown_after {
            self.release().await;
        }

        if response.get("ok").and_then(Value::as_bool) != Some(true) {
            return Err(Error::Invalid(
                response
                    .get("error")
                    .and_then(Value::as_str)
                    .unwrap_or("History engine request failed")
                    .to_owned(),
            ));
        }
        response
            .get("result")
            .filter(|value| value.is_object())
            .cloned()
            .ok_or_else(|| Error::Invalid("History engine returned an invalid result".into()))
    }

    pub async fn release(&self) {
        let mut inner = self.inner.lock().await;
        self.stop_engine_locked(&mut inner).await;
    }

    pub async fn shutdown(&self) {
        self.release().await;
        #[cfg(unix)]
        {
            let _ = fs::remove_file(&self.socket_path);
        }
    }

    pub async fn idle_reaper(self: Arc<Self>, mut shutdown: watch::Receiver<bool>) -> Result<()> {
        loop {
            tokio::select! {
                _ = tokio::time::sleep(Duration::from_secs(1)) => {}
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow() {
                        break;
                    }
                }
            }
            let mut inner = self.inner.lock().await;
            let should_stop = inner.engine.as_ref().is_some_and(|engine| {
                self.idle.is_zero() || engine.last_use.elapsed() >= self.idle
            });
            if should_stop {
                self.stop_engine_locked(&mut inner).await;
            }
        }
        Ok(())
    }

    #[cfg(unix)]
    pub async fn serve_unix_socket(
        self: Arc<Self>,
        mut shutdown: watch::Receiver<bool>,
    ) -> Result<()> {
        if let Some(parent) = self.socket_path.parent() {
            fs::create_dir_all(parent)?;
        }
        match fs::remove_file(&self.socket_path) {
            Ok(()) => {}
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
            Err(error) => return Err(error.into()),
        }
        let listener = UnixListener::bind(&self.socket_path)?;
        let _ = fs::set_permissions(&self.socket_path, fs::Permissions::from_mode(0o600));
        println!("[HISTORY-BROKER] ready on {}", self.socket_path.display());

        loop {
            tokio::select! {
                accepted = listener.accept() => {
                    let (stream, _) = accepted?;
                    match timeout(self.engine_timeout + Duration::from_secs(5), self.handle_socket(stream)).await {
                        Ok(Ok(())) => {}
                        Ok(Err(error)) => eprintln!("[HISTORY-BROKER] request failed: {error}"),
                        Err(_) => eprintln!("[HISTORY-BROKER] request timed out"),
                    }
                }
                changed = shutdown.changed() => {
                    if changed.is_err() || *shutdown.borrow() {
                        break;
                    }
                }
            }
        }
        let _ = fs::remove_file(&self.socket_path);
        Ok(())
    }

    #[cfg(unix)]
    async fn handle_socket(&self, mut stream: UnixStream) -> Result<()> {
        let mut buffer = Vec::new();
        loop {
            if buffer.len() > self.protocol_max_bytes {
                return Err(Error::Invalid(
                    "History broker request exceeded the protocol limit".into(),
                ));
            }
            let remaining = self.protocol_max_bytes.saturating_sub(buffer.len()) + 1;
            let mut chunk = vec![0u8; remaining.min(65_536)];
            let bytes = stream.read(&mut chunk).await?;
            if bytes == 0 {
                break;
            }
            buffer.extend_from_slice(&chunk[..bytes]);
            if let Some(newline) = buffer.iter().position(|byte| *byte == b'\n') {
                buffer.truncate(newline);
                break;
            }
        }
        if buffer.is_empty() {
            return Err(Error::Invalid(
                "History broker received an empty request".into(),
            ));
        }
        let request: Value = serde_json::from_slice(&buffer)?;
        if !request.is_object() {
            return Err(Error::Invalid(
                "History broker request must be a JSON object".into(),
            ));
        }
        let response = match self.request(request).await {
            Ok(result) => serde_json::json!({"ok": true, "result": result}),
            Err(error) => serde_json::json!({"ok": false, "error": error.to_string()}),
        };
        let mut encoded = serde_json::to_vec(&response)?;
        encoded.push(b'\n');
        if encoded.len() > self.protocol_max_bytes {
            return Err(Error::Invalid(
                "History broker response exceeded the protocol limit".into(),
            ));
        }
        stream.write_all(&encoded).await?;
        Ok(())
    }
}

fn env_f64(name: &str, default: f64) -> f64 {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse().ok())
        .unwrap_or(default)
}

pub fn llm_only_context() -> TaggingContext {
    TaggingContext {
        mode: "llm_only".into(),
        route: "llm_only".into(),
        llm_decides: true,
        tag: None,
        examples: vec![],
        extra: BTreeMap::new(),
    }
}

pub fn history_error_context(error: impl Into<String>) -> TaggingContext {
    let mut extra = BTreeMap::new();
    extra.insert("reason".into(), Value::String("history_error".into()));
    extra.insert("history_error".into(), Value::String(error.into()));
    TaggingContext {
        mode: "history_assisted".into(),
        route: "llm_fallback".into(),
        llm_decides: true,
        tag: None,
        examples: vec![],
        extra,
    }
}

pub async fn history_contexts_for_documents(
    manager: &HistoryManager,
    config: &PromptConfig,
    documents: &[PaperlessDocument],
    shutdown_after: bool,
) -> HashMap<i64, TaggingContext> {
    if config.tagging_mode == TaggingMode::LlmOnly {
        if shutdown_after {
            manager.release().await;
        }
        return documents
            .iter()
            .map(|document| (document.id, llm_only_context()))
            .collect();
    }
    if documents.is_empty() {
        return HashMap::new();
    }

    let payload = serde_json::json!({
        "op": "route_batch",
        "documents": documents.iter().map(|document| serde_json::json!({
            "id": document.id,
            "content": document.content.as_deref().unwrap_or_default(),
        })).collect::<Vec<_>>(),
        "shutdown_after": shutdown_after,
    });

    let result = async {
        let result = manager.request(payload).await?;
        let routes = result
            .get("routes")
            .and_then(Value::as_array)
            .ok_or_else(|| Error::Invalid("History broker returned no routes".into()))?;
        let mut by_id = HashMap::new();
        for item in routes {
            let id = item
                .get("id")
                .and_then(Value::as_i64)
                .ok_or_else(|| Error::Invalid("History broker returned an invalid route".into()))?;
            let tagging = item
                .get("tagging")
                .ok_or_else(|| Error::Invalid("History broker returned an invalid route".into()))?;
            let tagging: TaggingContext = serde_json::from_value(tagging.clone())?;
            by_id.insert(id, tagging);
        }
        let missing = documents
            .iter()
            .filter(|document| !by_id.contains_key(&document.id))
            .map(|document| document.id)
            .collect::<Vec<_>>();
        if !missing.is_empty() {
            return Err(Error::Invalid(format!(
                "History broker omitted route(s): {}",
                missing
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>()
                    .join(", ")
            )));
        }
        Ok::<_, Error>(by_id)
    }
    .await;

    match result {
        Ok(routes) => routes,
        Err(error) => documents
            .iter()
            .map(|document| (document.id, history_error_context(error.to_string())))
            .collect(),
    }
}

pub async fn history_context_for_document(
    manager: &HistoryManager,
    config: &PromptConfig,
    document: &PaperlessDocument,
    shutdown_after: bool,
) -> TaggingContext {
    let mut contexts = history_contexts_for_documents(
        manager,
        config,
        std::slice::from_ref(document),
        shutdown_after,
    )
    .await;
    contexts
        .remove(&document.id)
        .unwrap_or_else(|| history_error_context("No history route was prepared for this document"))
}

pub async fn refresh_history(manager: &HistoryManager, shutdown_after: bool) -> Result<Value> {
    let result = manager
        .request(serde_json::json!({
            "op": "refresh",
            "shutdown_after": shutdown_after,
        }))
        .await?;
    result
        .get("history")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or_else(|| Error::Invalid("History broker returned no history status".into()))
}

pub async fn cached_history_state(
    client: &PaperlessClient,
    tax: &Taxonomy,
    app: &AppConfig,
    app_version: &str,
) -> Result<Value> {
    let metadata = read_json(Path::new(HISTORY_META_FILE));
    let source = history_source_state(client, tax, app).await?;
    let mut status = empty_history_status();
    let mut cache_state = "missing";
    let mut stale = true;

    if let Some(metadata) = metadata
        && Path::new(HISTORY_CACHE_FILE).exists()
    {
        if let Some(cached) = metadata.get("status").filter(|value| value.is_object()) {
            status = cached.clone();
        }
        let libraries_match = current_history_library_versions()
            .is_some_and(|libraries| metadata.get("libraries") == Some(&libraries));
        let metadata_matches = metadata.get("format_version").and_then(Value::as_u64)
            == Some(HISTORY_CACHE_FORMAT_VERSION)
            && metadata.get("app_version").and_then(Value::as_str) == Some(app_version)
            && metadata.get("algorithm") == Some(&history_algorithm_signature())
            && metadata.get("paperless_url").and_then(Value::as_str)
                == Some(app.connections.paperless_url.as_str())
            && metadata.get("source") == Some(&source)
            && libraries_match
            && metadata.get("cache_sha256").is_some_and(Value::is_string);
        if metadata_matches {
            cache_state = "ready";
            stale = false;
        } else {
            cache_state = "stale";
        }
    }

    let object = status
        .as_object_mut()
        .ok_or_else(|| Error::Invalid("History status is not a JSON object".into()))?;
    object.insert("stale".into(), Value::Bool(stale));
    object.insert("cache_state".into(), Value::String(cache_state.into()));
    object.insert(
        "source".into(),
        serde_json::json!({
            "reviewed_documents": source.get("reviewed_documents"),
            "latest_modified": source.get("latest_modified"),
        }),
    );
    Ok(status)
}

async fn history_source_state(
    client: &PaperlessClient,
    tax: &Taxonomy,
    app: &AppConfig,
) -> Result<Value> {
    let names = [
        app.workflow.review_tag.as_str(),
        app.workflow.llm_queue_tag.as_str(),
        app.workflow.llm_error_tag.as_str(),
    ];
    let mut excluded_ids = Vec::new();
    let mut missing = Vec::new();
    for name in names {
        match tax.tag_by_name.get(name) {
            Some(id) => excluded_ids.push(*id),
            None => missing.push(name),
        }
    }
    if !missing.is_empty() {
        return Err(Error::Invalid(format!(
            "History exclusion tag(s) not found in Paperless: {}",
            missing
                .iter()
                .map(|name| format!("{name:?}"))
                .collect::<Vec<_>>()
                .join(", ")
        )));
    }
    excluded_ids.sort_unstable();
    excluded_ids.dedup();

    let query = vec![
        (
            "tags__id__none".into(),
            excluded_ids
                .iter()
                .map(ToString::to_string)
                .collect::<Vec<_>>()
                .join(","),
        ),
        ("ordering".into(), "-modified".into()),
        ("page_size".into(), "1".into()),
        ("fields".into(), "id,modified".into()),
    ];
    let data = client
        .request_json(reqwest::Method::GET, "/api/documents/", Some(&query), None)
        .await?;
    let results = data
        .get("results")
        .and_then(Value::as_array)
        .cloned()
        .unwrap_or_default();
    let modified = results
        .first()
        .and_then(|item| item.get("modified"))
        .cloned()
        .unwrap_or(Value::Null);

    Ok(serde_json::json!({
        "reviewed_documents": data.get("count").and_then(Value::as_u64).unwrap_or(results.len() as u64),
        "latest_modified": modified,
        "taxonomy": taxonomy_signature(tax),
        "excluded_tag_ids": excluded_ids,
    }))
}

fn taxonomy_signature(tax: &Taxonomy) -> Value {
    let mut rows = tax
        .tags
        .iter()
        .map(|tag| (tag.id, tag.name.clone(), tag.parent))
        .collect::<Vec<_>>();
    rows.sort_by(|left, right| (left.0, &left.1).cmp(&(right.0, &right.1)));
    Value::Array(
        rows.into_iter()
            .map(|(id, name, parent)| serde_json::json!([id, name, parent]))
            .collect(),
    )
}

pub fn history_algorithm_signature() -> Value {
    serde_json::json!({
        "version": HISTORY_ALGORITHM_VERSION,
        "word_ngram_range": [1, 2],
        "char_analyzer": "char_wb",
        "char_ngram_range": [3, 5],
        "dtype": "float32",
        "norm": "l2",
        "retrieval_estimator": "NearestNeighbors",
        "retrieval_metric": "cosine",
        "retrieval_algorithm": "brute",
        "fast_similarity": FAST_SIMILARITY,
        "family_similarity": FAMILY_SIMILARITY,
        "example_min_similarity": EXAMPLE_MIN_SIMILARITY,
        "top_vote_neighbors": TOP_VOTE_NEIGHBORS,
        "query_neighbors": QUERY_NEIGHBORS,
        "min_support": MIN_SUPPORT,
        "min_winner_share": MIN_WINNER_SHARE,
        "max_examples": MAX_EXAMPLES,
        "max_examples_per_tag_set": MAX_EXAMPLES_PER_TAG_SET,
        "max_diagnostic_docs": MAX_DIAGNOSTIC_DOCS,
    })
}

pub fn empty_history_status() -> Value {
    serde_json::json!({
        "status": "Not built",
        "reviewed_documents": 0,
        "tags_represented": 0,
        "eligible_tags": 0,
        "estimated_reuse_count": 0,
        "estimated_reuse_percent": 0.0,
        "estimated_reuse_sample_size": 0,
        "retrospective_routed_count": 0,
        "retrospective_agreement_count": 0,
        "potential_inconsistencies": [],
        "potential_inconsistency_count": 0,
        "per_tag": [],
        "last_updated": null,
        "last_error": null,
        "thresholds": {
            "history_match_similarity": FAST_SIMILARITY,
            "support": MIN_SUPPORT,
            "winner_share": MIN_WINNER_SHARE,
            "inconsistency_similarity": FAMILY_SIMILARITY,
        },
    })
}

fn read_json(path: &Path) -> Option<Value> {
    serde_json::from_str(&fs::read_to_string(path).ok()?).ok()
}

fn current_history_library_versions() -> Option<Value> {
    let python = std::env::var("PYTHON_VERSION").ok()?;
    let mut parts = python.split('.');
    let major = parts.next()?;
    let minor = parts.next()?;
    let site_packages = std::env::var_os("PLAI_PYTHON_SITE_PACKAGES")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            PathBuf::from(format!(
                "/usr/local/lib/python{major}.{minor}/site-packages"
            ))
        });
    let mut versions = BTreeMap::new();
    for entry in fs::read_dir(site_packages)
        .ok()?
        .filter_map(std::result::Result::ok)
    {
        let path = entry.path();
        if !path
            .file_name()
            .and_then(|name| name.to_str())
            .is_some_and(|name| name.ends_with(".dist-info"))
        {
            continue;
        }
        let Ok(metadata) = fs::read_to_string(path.join("METADATA")) else {
            continue;
        };
        let mut name = None;
        let mut version = None;
        for line in metadata.lines() {
            if name.is_none() {
                name = line.strip_prefix("Name: ").map(str::to_owned);
            }
            if version.is_none() {
                version = line.strip_prefix("Version: ").map(str::to_owned);
            }
            if name.is_some() && version.is_some() {
                break;
            }
        }
        let Some(name) = name else { continue };
        let Some(version) = version else { continue };
        match name.to_ascii_lowercase().replace('-', "_").as_str() {
            "numpy" => {
                versions.insert("numpy", version);
            }
            "scipy" => {
                versions.insert("scipy", version);
            }
            "scikit_learn" => {
                versions.insert("scikit_learn", version);
            }
            _ => {}
        }
    }
    if !["numpy", "scipy", "scikit_learn"]
        .iter()
        .all(|name| versions.contains_key(*name))
    {
        return None;
    }
    Some(serde_json::json!({
        "python": python,
        "numpy": versions["numpy"],
        "scipy": versions["scipy"],
        "scikit_learn": versions["scikit_learn"],
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn contexts_keep_public_route_names() {
        let direct = llm_only_context();
        assert_eq!(direct.mode, "llm_only");
        assert_eq!(direct.route, "llm_only");
        assert!(direct.llm_decides);

        let fallback = history_error_context("test");
        assert_eq!(fallback.mode, "history_assisted");
        assert_eq!(fallback.route, "llm_fallback");
        assert!(fallback.llm_decides);
        assert_eq!(fallback.extra["reason"], "history_error");
    }

    #[test]
    fn algorithm_signature_keeps_released_thresholds() {
        let signature = history_algorithm_signature();
        assert_eq!(signature["fast_similarity"], 0.60);
        assert_eq!(signature["min_support"], 2);
        assert_eq!(signature["min_winner_share"], 0.50);
        assert_eq!(signature["max_examples"], 5);
    }
}
