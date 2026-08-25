use crate::ai_lock;
use crate::app_config::{atomic_write_json, utc_now_iso};
use crate::error::{Error, Result};
use serde_json::Value;
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Clone)]
pub struct OcrRecoveryStore {
    coordination_dir: PathBuf,
}

impl Default for OcrRecoveryStore {
    fn default() -> Self {
        Self {
            coordination_dir: std::env::var_os("PLAI_COORDINATION_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| PathBuf::from("/coordination")),
        }
    }
}

impl OcrRecoveryStore {
    #[cfg(test)]
    pub fn new(coordination_dir: PathBuf) -> Self {
        Self { coordination_dir }
    }

    fn state_file(&self) -> PathBuf {
        self.coordination_dir.join("ocr-recovery-state.json")
    }

    fn failures_file(&self) -> PathBuf {
        self.coordination_dir.join("ocr-recovery-failures.json")
    }

    fn retry_now_file(&self) -> PathBuf {
        self.coordination_dir.join("ocr-retry-now.json")
    }

    fn lock_file(&self) -> PathBuf {
        self.coordination_dir.join("ocr-recovery.lock")
    }

    pub async fn recovery_state_for_ui(&self) -> Result<Value> {
        let _guard = ai_lock::acquire(self.lock_file()).await?;
        let mut state = default_state();
        if let Some(raw) =
            read_json(&self.state_file()).and_then(|value| value.as_object().cloned())
            && let Some(object) = state.as_object_mut()
        {
            object.extend(raw);
        }
        let request_id = state
            .get("request_id")
            .and_then(Value::as_str)
            .map(str::to_owned);
        let retry_now_requested = request_id.as_deref().is_some_and(|request_id| {
            read_json(&self.retry_now_file())
                .and_then(|trigger| {
                    trigger
                        .get("request_id")
                        .and_then(Value::as_str)
                        .map(|value| value == request_id)
                })
                .unwrap_or(false)
        });
        state["retry_now_requested"] = Value::Bool(retry_now_requested);
        let failures = read_json(&self.failures_file())
            .filter(Value::is_array)
            .unwrap_or_else(|| Value::Array(vec![]));
        Ok(serde_json::json!({"state": state, "failures": failures}))
    }

    pub async fn request_retry_now(&self, request_id: &str) -> Result<Value> {
        let request_id = request_id.trim();
        if request_id.is_empty() {
            return Err(Error::Invalid("request_id is required".into()));
        }
        let _guard = ai_lock::acquire(self.lock_file()).await?;
        let state = read_json(&self.state_file()).unwrap_or_else(|| serde_json::json!({}));
        if state.get("status").and_then(Value::as_str) != Some("waiting") {
            return Err(Error::Invalid("No OCR retry is currently waiting".into()));
        }
        if state.get("request_id").and_then(Value::as_str) != Some(request_id) {
            return Err(Error::Invalid(
                "The waiting OCR request changed; refresh and try again".into(),
            ));
        }
        let trigger = serde_json::json!({
            "request_id": request_id,
            "requested_at": utc_now_iso(),
        });
        atomic_write_json(&self.retry_now_file(), &trigger)?;
        Ok(trigger)
    }

    pub async fn dismiss_failure(&self, failure_id: &str) -> Result<bool> {
        let failure_id = failure_id.trim();
        if failure_id.is_empty() {
            return Ok(false);
        }
        let _guard = ai_lock::acquire(self.lock_file()).await?;
        let mut items = read_json(&self.failures_file())
            .and_then(|value| value.as_array().cloned())
            .unwrap_or_default();
        let before = items.len();
        items.retain(|item| item.get("id").and_then(Value::as_str) != Some(failure_id));
        let removed = items.len() != before;
        if removed {
            atomic_write_json(&self.failures_file(), &items)?;
            let state = read_json(&self.state_file()).unwrap_or_else(|| serde_json::json!({}));
            if state.get("failure_id").and_then(Value::as_str) == Some(failure_id) {
                atomic_write_json(&self.state_file(), &default_state())?;
            }
        }
        Ok(removed)
    }
}

fn default_state() -> Value {
    serde_json::json!({
        "status": "idle",
        "request_id": null,
        "source": null,
        "page_number": null,
        "attempt": null,
        "max_attempts": null,
        "retry_delays_seconds": null,
        "last_error": null,
        "retry_after_seconds": null,
        "next_retry_at": null,
        "failure_id": null,
        "updated_at": utc_now_iso(),
    })
}

fn read_json(path: &Path) -> Option<Value> {
    serde_json::from_str(&fs::read_to_string(path).ok()?).ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_state_matches_public_shape() {
        let state = default_state();
        assert_eq!(state["status"], "idle");
        assert!(state["request_id"].is_null());
        assert!(state["failure_id"].is_null());
    }

    #[test]
    fn configured_paths_stay_inside_coordination_dir() {
        let store = OcrRecoveryStore::new(PathBuf::from("/tmp/plai-test"));
        assert_eq!(
            store.state_file(),
            PathBuf::from("/tmp/plai-test/ocr-recovery-state.json")
        );
        assert_eq!(
            store.lock_file(),
            PathBuf::from("/tmp/plai-test/ocr-recovery.lock")
        );
    }
}
