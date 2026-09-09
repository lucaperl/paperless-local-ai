use crate::error::{Error, Result};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

const CHAT_DIR: &str = "/data/chat";
const HISTORY_LOCK: &str = "/data/chat/history.lock";

struct HistoryGuard {
    file: File,
}

impl Drop for HistoryGuard {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

fn lock_history() -> Result<HistoryGuard> {
    fs::create_dir_all(CHAT_DIR)?;
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(HISTORY_LOCK)?;
    file.lock()?;
    Ok(HistoryGuard { file })
}

fn now_ms() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
        .try_into()
        .unwrap_or(u64::MAX)
}

fn valid_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 80
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_'))
}

fn new_id(user_id: i64) -> String {
    let seed = format!("{}:{}:{}", user_id, std::process::id(), now_ms());
    let digest = Sha256::digest(seed.as_bytes());
    digest[..16]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}

fn user_dir(user_id: i64) -> PathBuf {
    PathBuf::from(CHAT_DIR)
        .join("conversations")
        .join(user_id.to_string())
}

fn conversation_path(user_id: i64, conversation_id: &str) -> Result<PathBuf> {
    if !valid_id(conversation_id) {
        return Err(Error::Invalid("invalid conversation id".into()));
    }
    Ok(user_dir(user_id).join(format!("{conversation_id}.json")))
}

fn atomic_write(path: &Path, value: &Value) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let nonce = now_ms();
    let tmp = path.with_extension(format!("tmp-{}-{nonce}", std::process::id()));
    let mut bytes = serde_json::to_vec_pretty(value)?;
    bytes.push(b'\n');
    {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&tmp)?;
        file.write_all(&bytes)?;
        file.sync_all()?;
    }
    fs::rename(tmp, path)?;
    Ok(())
}

fn load(path: &Path) -> Result<Value> {
    let raw = fs::read(path)?;
    let value: Value = serde_json::from_slice(&raw)?;
    if !value.is_object() {
        return Err(Error::Invalid(
            "conversation file is not a JSON object".into(),
        ));
    }
    Ok(value)
}

fn title_from_question(question: &str) -> String {
    let compact = question.split_whitespace().collect::<Vec<_>>().join(" ");
    let mut title = compact.chars().take(64).collect::<String>();
    if compact.chars().count() > 64 {
        title.push('…');
    }
    if title.is_empty() {
        "New chat".into()
    } else {
        title
    }
}

fn touch(value: &mut Value) {
    value["updated_at_ms"] = Value::from(now_ms());
}

pub fn create(user_id: i64, scope: Value, settings: Value) -> Result<Value> {
    let _guard = lock_history()?;
    let conversation_id = new_id(user_id);
    let now = now_ms();
    let value = json!({
        "id": conversation_id,
        "user_id": user_id,
        "title": "New chat",
        "created_at_ms": now,
        "updated_at_ms": now,
        "scope": scope,
        "settings": settings,
        "messages": [],
        "active_job_id": null
    });
    let path = conversation_path(user_id, value["id"].as_str().unwrap_or_default())?;
    atomic_write(&path, &value)?;
    Ok(value)
}

pub fn list(user_id: i64) -> Result<Value> {
    let _guard = lock_history()?;
    let dir = user_dir(user_id);
    if !dir.exists() {
        return Ok(json!({"conversations": []}));
    }
    let mut items = Vec::new();
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let Ok(value) = load(&path) else {
            continue;
        };
        items.push(json!({
            "id": value.get("id"),
            "title": value.get("title"),
            "created_at_ms": value.get("created_at_ms"),
            "updated_at_ms": value.get("updated_at_ms"),
            "scope": value.get("scope"),
            "active_job_id": value.get("active_job_id")
        }));
    }
    items.sort_by_key(|item| std::cmp::Reverse(item["updated_at_ms"].as_u64().unwrap_or(0)));
    Ok(json!({"conversations": items}))
}

pub fn get(user_id: i64, conversation_id: &str) -> Result<Value> {
    let _guard = lock_history()?;
    load(&conversation_path(user_id, conversation_id)?)
}

pub fn rename(user_id: i64, conversation_id: &str, title: &str) -> Result<Value> {
    let title = title.trim();
    if title.is_empty() || title.chars().count() > 120 {
        return Err(Error::Invalid(
            "title must contain 1 to 120 characters".into(),
        ));
    }
    let _guard = lock_history()?;
    let path = conversation_path(user_id, conversation_id)?;
    let mut value = load(&path)?;
    value["title"] = Value::String(title.to_owned());
    touch(&mut value);
    atomic_write(&path, &value)?;
    Ok(value)
}

pub fn delete(user_id: i64, conversation_id: &str) -> Result<()> {
    let _guard = lock_history()?;
    let path = conversation_path(user_id, conversation_id)?;
    let value = load(&path)?;
    if value
        .get("active_job_id")
        .is_some_and(|item| !item.is_null())
    {
        return Err(Error::Invalid(
            "cannot delete a chat while a turn is active".into(),
        ));
    }
    fs::remove_file(path)?;
    Ok(())
}

pub fn begin_turn(
    user_id: i64,
    conversation_id: &str,
    job_id: &str,
    question: &str,
    scope: Value,
    settings: Value,
) -> Result<Value> {
    let question = question.trim();
    if question.is_empty() {
        return Err(Error::Invalid("question must not be empty".into()));
    }
    let _guard = lock_history()?;
    let path = conversation_path(user_id, conversation_id)?;
    let mut value = load(&path)?;
    if value
        .get("active_job_id")
        .is_some_and(|item| !item.is_null())
    {
        return Err(Error::Invalid(
            "this chat already has an active turn".into(),
        ));
    }
    let history = value
        .get("messages")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter(|item| {
            matches!(
                item.get("role").and_then(Value::as_str),
                Some("user" | "assistant")
            ) && !item
                .get("pending")
                .and_then(Value::as_bool)
                .unwrap_or(false)
                && item
                    .get("content")
                    .and_then(Value::as_str)
                    .is_some_and(|text| !text.is_empty())
        })
        .map(|item| json!({"role": item["role"], "content": item["content"]}))
        .collect::<Vec<_>>();

    if value.get("title").and_then(Value::as_str) == Some("New chat") {
        value["title"] = Value::String(title_from_question(question));
    }
    value["scope"] = scope;
    value["settings"] = settings;
    value["active_job_id"] = Value::String(job_id.to_owned());
    let messages = value
        .get_mut("messages")
        .and_then(Value::as_array_mut)
        .ok_or_else(|| Error::Invalid("conversation messages are invalid".into()))?;
    messages.push(json!({
        "role": "user",
        "content": question,
        "created_at_ms": now_ms()
    }));
    messages.push(json!({
        "role": "assistant",
        "content": "",
        "pending": true,
        "job_id": job_id,
        "thinking": "",
        "sources": [],
        "metrics": {},
        "created_at_ms": now_ms()
    }));
    touch(&mut value);
    atomic_write(&path, &value)?;
    Ok(Value::Array(history))
}

pub fn finish_turn(
    user_id: i64,
    conversation_id: &str,
    job_id: &str,
    job: &Value,
) -> Result<Value> {
    let _guard = lock_history()?;
    let path = conversation_path(user_id, conversation_id)?;
    let mut value = load(&path)?;
    if let Some(messages) = value.get_mut("messages").and_then(Value::as_array_mut)
        && let Some(message) = messages.iter_mut().rev().find(|item| {
            item.get("role").and_then(Value::as_str) == Some("assistant")
                && item.get("job_id").and_then(Value::as_str) == Some(job_id)
        })
    {
        message["pending"] = Value::Bool(false);
        message["content"] = Value::String(
            job.get("answer")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
        );
        message["thinking"] = Value::String(
            job.get("thinking")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .to_owned(),
        );
        message["sources"] = job.get("sources").cloned().unwrap_or_else(|| json!([]));
        message["metrics"] = job.get("metrics").cloned().unwrap_or_else(|| json!({}));
        message["status"] = job
            .get("status")
            .cloned()
            .unwrap_or_else(|| Value::String("error".into()));
        if job.get("status").and_then(Value::as_str) == Some("error") {
            let error = job
                .get("error")
                .and_then(Value::as_str)
                .unwrap_or("Unknown RAG error");
            message["content"] = Value::String(format!("Error: {error}"));
        } else if job.get("status").and_then(Value::as_str) == Some("stopped")
            && message
                .get("content")
                .and_then(Value::as_str)
                .unwrap_or_default()
                .is_empty()
        {
            message["content"] = Value::String("Stopped.".into());
        }
    }
    if value.get("active_job_id").and_then(Value::as_str) == Some(job_id) {
        value["active_job_id"] = Value::Null;
    }
    touch(&mut value);
    atomic_write(&path, &value)?;
    Ok(value)
}

#[cfg(test)]
mod tests {
    use super::title_from_question;

    #[test]
    fn deterministic_title_is_bounded_without_an_llm_call() {
        let title = title_from_question(&"word ".repeat(40));
        assert!(title.chars().count() <= 65);
        assert!(title.ends_with('…'));
    }
}
