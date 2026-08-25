use crate::app_config::AppConfigStore;
use crate::error::{Error, Result};
use crate::http::HttpClient;
use crate::prompt::{KeepAlive, PromptConfig, RenderedPrompts, normalize_result};
use serde::Serialize;
use serde_json::Value;
use std::collections::BTreeMap;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[derive(Debug, Clone)]
pub struct OllamaClient {
    http: HttpClient,
    config_store: Arc<AppConfigStore>,
}

#[derive(Debug, Clone)]
pub struct OllamaCall {
    pub result: Value,
    pub raw: Value,
    pub wall_duration: Duration,
    pub payload: Value,
}

#[derive(Debug, Serialize)]
struct ChatMessage<'a> {
    role: &'static str,
    content: &'a str,
}

impl OllamaClient {
    pub fn new(http: HttpClient, config_store: Arc<AppConfigStore>) -> Self {
        Self { http, config_store }
    }

    pub fn build_payload(
        rendered: &RenderedPrompts,
        config: &PromptConfig,
        keep_alive_override: Option<KeepAlive>,
    ) -> Result<Value> {
        Ok(serde_json::json!({
            "model": config.model,
            "messages": [
                ChatMessage { role: "system", content: &rendered.system_prompt },
                ChatMessage { role: "user", content: &rendered.user_prompt },
            ],
            "format": rendered.schema,
            "stream": false,
            "think": config.think,
            "keep_alive": keep_alive_override.unwrap_or_else(|| config.keep_alive.clone()),
            "options": {
                "num_ctx": config.num_ctx,
                "temperature": config.temperature,
                "num_predict": config.num_predict,
            },
        }))
    }

    pub async fn call(
        &self,
        rendered: &RenderedPrompts,
        config: &PromptConfig,
        keep_alive_override: Option<KeepAlive>,
    ) -> Result<OllamaCall> {
        let payload = Self::build_payload(rendered, config, keep_alive_override)?;
        let base = self.config_store.load()?.connections.ollama_url;
        let started = Instant::now();
        let response = self
            .http
            .inner()
            .post(format!("{base}/api/chat"))
            .json(&payload)
            .timeout(Duration::from_secs(config.ollama_timeout_seconds))
            .send()
            .await?
            .error_for_status()?;
        let raw: Value = response.json().await?;
        let wall_duration = started.elapsed();
        let text = raw
            .get("message")
            .and_then(|v| v.get("content"))
            .and_then(Value::as_str)
            .filter(|text| !text.is_empty())
            .ok_or_else(|| Error::Invalid("Ollama did not return a normal response text".into()))?;
        let result = normalize_result(serde_json::from_str(text)?);
        Ok(OllamaCall {
            result,
            raw,
            wall_duration,
            payload,
        })
    }

    pub async fn unload_model(&self, model: &str) -> Result<()> {
        let base = self.config_store.load()?.connections.ollama_url;
        self.http
            .inner()
            .post(format!("{base}/api/generate"))
            .json(&serde_json::json!({"model": model, "keep_alive": 0, "stream": false}))
            .timeout(Duration::from_secs(30))
            .send()
            .await?
            .error_for_status()?;
        Ok(())
    }
}

pub fn performance_from_raw(raw: &Value, wall_duration: Duration) -> BTreeMap<String, Value> {
    BTreeMap::from([
        (
            "wall_seconds".into(),
            rounded_seconds(wall_duration.as_secs_f64()),
        ),
        (
            "total_seconds".into(),
            rounded_seconds(nanos(raw, "total_duration")),
        ),
        (
            "load_seconds".into(),
            rounded_seconds(nanos(raw, "load_duration")),
        ),
        (
            "prompt_tokens".into(),
            raw.get("prompt_eval_count")
                .cloned()
                .unwrap_or(Value::from(0)),
        ),
        (
            "prompt_seconds".into(),
            rounded_seconds(nanos(raw, "prompt_eval_duration")),
        ),
        (
            "output_tokens".into(),
            raw.get("eval_count").cloned().unwrap_or(Value::from(0)),
        ),
        (
            "generation_seconds".into(),
            rounded_seconds(nanos(raw, "eval_duration")),
        ),
    ])
}

fn nanos(raw: &Value, key: &str) -> f64 {
    raw.get(key).and_then(Value::as_f64).unwrap_or(0.0) / 1_000_000_000.0
}

fn rounded_seconds(value: f64) -> Value {
    let value = format!("{value:.3}").parse::<f64>().unwrap_or(value);
    Value::from(value)
}
