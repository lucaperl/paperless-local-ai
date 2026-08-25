use crate::ai_lock;
use crate::app_config::{AppConfig, config_hash_value as app_config_hash_value};
use crate::correspondent::{CorrespondentResolution, resolve_correspondent};
use crate::error::Error;
use crate::history;
use crate::ollama::performance_from_raw;
use crate::prompt::{
    PLACEHOLDERS, PromptConfig, TaggingContext, prompt_hashes, prompt_preset,
    prune_parent_tag_names, render_prompts, validate_result,
};
use crate::state::CoreState;
use axum::body::Bytes;
use axum::extract::{DefaultBodyLimit, State};
use axum::http::{HeaderMap, HeaderValue, StatusCode};
use axum::response::{Html, IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Json, Router};
use serde_json::Value;
use std::sync::Arc;
use std::time::Duration;

const MAX_BODY_BYTES: usize = 2_000_000;

#[derive(Debug)]
struct ApiError {
    status: StatusCode,
    message: String,
}

impl ApiError {
    fn bad(error: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::BAD_REQUEST,
            message: error.to_string(),
        }
    }

    fn internal(error: impl std::fmt::Display) -> Self {
        Self {
            status: StatusCode::INTERNAL_SERVER_ERROR,
            message: error.to_string(),
        }
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        json_response(self.status, serde_json::json!({"error": self.message}))
    }
}

type ApiResult = std::result::Result<Response, ApiError>;

pub fn router(state: Arc<CoreState>) -> Router {
    Router::new()
        .route("/", get(root))
        .route("/api/app/state", get(app_state))
        .route("/api/app/history", get(app_history))
        .route("/api/app/ocr/recovery", get(ocr_recovery_state))
        .route("/api/app/ocr/health", get(ocr_health))
        .route("/api/app/ocr/retry-now", post(ocr_retry_now))
        .route("/api/app/ocr/failures/dismiss", post(ocr_dismiss))
        .route("/api/app/validate", post(app_validate))
        .route("/api/app/save", post(app_save))
        .route("/api/app/history/restore", post(app_restore))
        .route("/api/app/connections/test", post(connection_test))
        .route("/api/state", get(prompt_state))
        .route("/api/health", get(health))
        .route("/api/history", get(prompt_history))
        .route("/api/tagging/state", get(tagging_state_get))
        .route("/api/tagging/refresh", post(tagging_refresh))
        .route("/api/config/validate", post(prompt_validate))
        .route("/api/config/save", post(prompt_save))
        .route("/api/history/restore", post(prompt_restore))
        .route("/api/preview", post(preview))
        .route("/api/test", post(test_model))
        .fallback(not_found)
        .layer(DefaultBodyLimit::max(MAX_BODY_BYTES))
        .with_state(state)
}

fn json_response(status: StatusCode, value: Value) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert("cache-control", HeaderValue::from_static("no-store"));
    (status, headers, Json(value)).into_response()
}

fn parse_body(body: &Bytes) -> std::result::Result<Value, ApiError> {
    if body.is_empty() {
        return Ok(serde_json::json!({}));
    }
    serde_json::from_slice(body).map_err(ApiError::bad)
}

async fn not_found() -> Response {
    json_response(
        StatusCode::NOT_FOUND,
        serde_json::json!({"error": "Not found"}),
    )
}

async fn root(State(state): State<Arc<CoreState>>) -> Response {
    let mut headers = HeaderMap::new();
    headers.insert("cache-control", HeaderValue::from_static("no-store"));
    (headers, Html(state.control_html.to_string())).into_response()
}

async fn app_state(State(state): State<Arc<CoreState>>) -> ApiResult {
    let config = state.app_config.ensure().map_err(ApiError::internal)?;
    let value = serde_json::to_value(&config).map_err(ApiError::internal)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "config": config,
            "config_sha256": app_config_hash_value(&value),
            "history": state.app_config.list_history().map_err(ApiError::internal)?,
            "token_configured": !state.token.is_empty(),
        }),
    ))
}

async fn app_history(State(state): State<Arc<CoreState>>) -> ApiResult {
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "items": state.app_config.list_history().map_err(ApiError::internal)?,
        }),
    ))
}

async fn ocr_recovery_state(State(state): State<Arc<CoreState>>) -> ApiResult {
    Ok(json_response(
        StatusCode::OK,
        state
            .ocr_recovery
            .recovery_state_for_ui()
            .await
            .map_err(ApiError::internal)?,
    ))
}

async fn ocr_health(State(state): State<Arc<CoreState>>) -> ApiResult {
    let recovery = state
        .ocr_recovery
        .recovery_state_for_ui()
        .await
        .map_err(ApiError::internal)?;
    let base = std::env::var("OCR_SERVICE_INTERNAL_URL")
        .unwrap_or_else(|_| "http://ocr-service:8082".into())
        .trim_end_matches('/')
        .to_owned();
    let mut result = serde_json::json!({
        "ok": false,
        "health": null,
        "recovery": recovery,
    });
    match state
        .http
        .inner()
        .get(format!("{base}/health"))
        .timeout(Duration::from_secs(5))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
    {
        Ok(response) => match response.json::<Value>().await {
            Ok(health) => {
                result["ok"] =
                    Value::Bool(health.get("ok").and_then(Value::as_bool).unwrap_or(true));
                result["health"] = health;
            }
            Err(error) => result["error"] = Value::String(format!("reqwest::Error: {error}")),
        },
        Err(error) => result["error"] = Value::String(format!("reqwest::Error: {error}")),
    }
    Ok(json_response(StatusCode::OK, result))
}

async fn ocr_retry_now(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let trigger = state
        .ocr_recovery
        .request_retry_now(
            payload
                .get("request_id")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .await
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({"ok": true, "trigger": trigger}),
    ))
}

async fn ocr_dismiss(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let removed = state
        .ocr_recovery
        .dismiss_failure(
            payload
                .get("failure_id")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .await
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({"ok": true, "removed": removed}),
    ))
}

async fn app_validate(body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = AppConfig::from_value(payload.get("config").unwrap_or(&Value::Null))
        .map_err(ApiError::bad)?;
    let value = serde_json::to_value(&config).map_err(ApiError::internal)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config_sha256": app_config_hash_value(&value),
        }),
    ))
}

async fn app_save(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = state
        .app_config
        .save(payload.get("config").unwrap_or(&Value::Null), "prompt-ui")
        .map_err(ApiError::bad)?;
    let value = serde_json::to_value(&config).map_err(ApiError::internal)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config": config,
            "config_sha256": app_config_hash_value(&value),
            "history": state.app_config.list_history().map_err(ApiError::internal)?,
            "token_configured": !state.token.is_empty(),
        }),
    ))
}

async fn app_restore(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = state
        .app_config
        .restore(
            payload
                .get("file")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config": config,
            "history": state.app_config.list_history().map_err(ApiError::internal)?,
            "token_configured": !state.token.is_empty(),
        }),
    ))
}

async fn connection_test(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = AppConfig::from_value(payload.get("config").unwrap_or(&Value::Null))
        .map_err(ApiError::bad)?;

    let paperless = if state.token.is_empty() {
        serde_json::json!({"ok": false, "detail": "PAPERLESS_TOKEN is missing"})
    } else {
        match state
            .http
            .inner()
            .get(format!(
                "{}/api/documents/",
                config.connections.paperless_url
            ))
            .query(&[("page_size", 1)])
            .header("Authorization", format!("Token {}", state.token))
            .header("Accept", "application/json")
            .timeout(Duration::from_secs(20))
            .send()
            .await
            .and_then(reqwest::Response::error_for_status)
        {
            Ok(response) => serde_json::json!({
                "ok": true,
                "detail": format!("HTTP {}", response.status().as_u16()),
            }),
            Err(error) => serde_json::json!({
                "ok": false,
                "detail": format!("reqwest::Error: {error}"),
            }),
        }
    };

    let ollama = match state
        .http
        .inner()
        .get(format!("{}/api/tags", config.connections.ollama_url))
        .timeout(Duration::from_secs(20))
        .send()
        .await
        .and_then(reqwest::Response::error_for_status)
    {
        Ok(response) => match response.json::<Value>().await {
            Ok(value) => serde_json::json!({
                "ok": true,
                "detail": format!(
                    "{} model(s) found",
                    value.get("models").and_then(Value::as_array).map(Vec::len).unwrap_or(0)
                ),
            }),
            Err(error) => serde_json::json!({
                "ok": false,
                "detail": format!("reqwest::Error: {error}"),
            }),
        },
        Err(error) => serde_json::json!({
            "ok": false,
            "detail": format!("reqwest::Error: {error}"),
        }),
    };

    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({"paperless": paperless, "ollama": ollama}),
    ))
}

async fn prompt_state(State(state): State<Arc<CoreState>>) -> ApiResult {
    let config = state.prompt_config.ensure().map_err(ApiError::internal)?;
    let connections = state
        .app_config
        .ensure()
        .map_err(ApiError::internal)?
        .connections;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "config": config,
            "placeholders": placeholders_value(),
            "presets": presets_value(),
            "hashes": prompt_hashes(&config),
            "connections": connections,
        }),
    ))
}

async fn health(State(state): State<Arc<CoreState>>) -> ApiResult {
    let config = state.prompt_config.load().map_err(ApiError::internal)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config_version": config.version,
            "model": config.model,
            "tagging_mode": config.tagging_mode,
        }),
    ))
}

async fn prompt_history(State(state): State<Arc<CoreState>>) -> ApiResult {
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "items": state.prompt_config.list_history().map_err(ApiError::internal)?,
        }),
    ))
}

async fn tagging_state_impl(state: &CoreState, force: bool) -> std::result::Result<Value, Error> {
    let config = state.prompt_config.load()?;
    let app = state.app_config.load()?;
    let taxonomy = state.paperless.taxonomy().await?;
    let history = if force {
        history::refresh_history(&state.history, false).await?
    } else {
        history::cached_history_state(&state.paperless, &taxonomy, &app, &state.app_version).await?
    };
    Ok(serde_json::json!({
        "tagging_mode": config.tagging_mode,
        "tags": taxonomy.tags,
        "tag_guidance": config.tag_guidance,
        "history": history,
    }))
}

async fn tagging_state_get(State(state): State<Arc<CoreState>>) -> ApiResult {
    Ok(json_response(
        StatusCode::OK,
        tagging_state_impl(&state, false)
            .await
            .map_err(ApiError::internal)?,
    ))
}

async fn tagging_refresh(State(state): State<Arc<CoreState>>) -> ApiResult {
    Ok(json_response(
        StatusCode::OK,
        tagging_state_impl(&state, true)
            .await
            .map_err(ApiError::internal)?,
    ))
}

async fn prompt_validate(body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = PromptConfig::from_value(payload.get("config").unwrap_or(&Value::Null))
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config_sha256": prompt_hashes(&config)["config_sha256"],
        }),
    ))
}

async fn prompt_save(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = state
        .prompt_config
        .save(payload.get("config").unwrap_or(&Value::Null), "prompt-ui")
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({
            "ok": true,
            "config": config,
            "hashes": prompt_hashes(&config),
        }),
    ))
}

async fn prompt_restore(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    let payload = parse_body(&body)?;
    let config = state
        .prompt_config
        .restore(
            payload
                .get("file")
                .and_then(Value::as_str)
                .unwrap_or_default(),
        )
        .map_err(ApiError::bad)?;
    Ok(json_response(
        StatusCode::OK,
        serde_json::json!({"ok": true, "config": config}),
    ))
}

async fn preview(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    preview_or_test(&state, parse_body(&body)?, false).await
}

async fn test_model(State(state): State<Arc<CoreState>>, body: Bytes) -> ApiResult {
    preview_or_test(&state, parse_body(&body)?, true).await
}

async fn preview_or_test(state: &CoreState, payload: Value, run_model: bool) -> ApiResult {
    let document_id = payload
        .get("document_id")
        .and_then(value_i64)
        .ok_or_else(|| ApiError::bad("document_id is required"))?;
    let config = match payload.get("config") {
        Some(config) => PromptConfig::from_value(config).map_err(ApiError::bad)?,
        None => state.prompt_config.load().map_err(ApiError::internal)?,
    };
    let taxonomy = state
        .paperless
        .taxonomy()
        .await
        .map_err(ApiError::internal)?;
    let document = state
        .paperless
        .document(document_id)
        .await
        .map_err(ApiError::internal)?;
    let tagging =
        history::history_context_for_document(&state.history, &config, &document, run_model).await;
    let rendered = render_prompts(&document, &taxonomy, &config, Some(tagging.clone()))
        .map_err(ApiError::bad)?;
    let hashes = prompt_hashes(&config);
    let mut base = serde_json::json!({
        "document": {
            "id": document.id,
            "title": document.title.as_deref(),
            "created": document.created.as_deref(),
        },
        "rendered": {
            "system_prompt": &rendered.system_prompt,
            "user_prompt": &rendered.user_prompt,
            "schema": &rendered.schema,
        },
        "taxonomy": {
            "tags": &taxonomy.tags,
            "document_types": &taxonomy.document_types,
            "existing_correspondents": &taxonomy.correspondents,
        },
        "tagging": &tagging,
        "meta": {
            "config_version": config.version,
            "draft_config_sha256": hashes["config_sha256"],
            "model": &config.model,
            "tagging_mode": config.tagging_mode,
            "num_ctx": config.num_ctx,
            "num_predict": config.num_predict,
            "temperature": config.temperature,
            "think": config.think,
            "keep_alive": &config.keep_alive,
            "content_chars_used": rendered.content_chars_used,
            "content_truncated": rendered.content_truncated,
        },
    });
    if !run_model {
        return Ok(json_response(StatusCode::OK, base));
    }

    let _guard = ai_lock::acquire(ai_lock::configured_ai_lock_path())
        .await
        .map_err(ApiError::internal)?;
    let call = state
        .ollama
        .call(&rendered, &config, None)
        .await
        .map_err(ApiError::internal)?;
    drop(_guard);

    let (result, errors, resolution) = finalize_model_result(
        call.result,
        &taxonomy,
        &config,
        &tagging,
        rendered.tags_enabled,
    );
    base["suggestion"] = result;
    base["validation_errors"] = serde_json::json!(errors);
    base["correspondent_resolution"] = serde_json::json!(resolution);
    base["performance"] = serde_json::json!(performance_from_raw(&call.raw, call.wall_duration));
    Ok(json_response(StatusCode::OK, base))
}

pub fn finalize_model_result(
    mut result: Value,
    taxonomy: &crate::paperless::Taxonomy,
    config: &PromptConfig,
    tagging: &TaggingContext,
    tags_enabled: bool,
) -> (Value, Vec<String>, CorrespondentResolution) {
    let errors = validate_result(&result, taxonomy, config, tags_enabled);
    let mut resolution = CorrespondentResolution {
        extracted: String::new(),
        status: "skipped_main_invalid".into(),
        resolved: String::new(),
        suggestion: String::new(),
        match_score: None,
        runner_up_score: None,
    };
    if errors.is_empty() {
        resolution = resolve_correspondent(
            result
                .get("correspondent")
                .and_then(Value::as_str)
                .unwrap_or_default(),
            &taxonomy.correspondents,
        );
        result["correspondent"] = Value::String(resolution.resolved.clone());
        if tagging.route == "history_match" {
            result["tags"] = serde_json::json!([tagging.tag.clone().unwrap_or_default()]);
        } else {
            let names = result
                .get("tags")
                .and_then(Value::as_array)
                .into_iter()
                .flatten()
                .filter_map(Value::as_str)
                .map(str::to_owned)
                .collect::<Vec<_>>();
            result["tags"] = serde_json::json!(prune_parent_tag_names(&names, taxonomy));
        }
    }
    (result, errors, resolution)
}

fn placeholders_value() -> Value {
    Value::Object(
        PLACEHOLDERS
            .iter()
            .map(|(name, description)| {
                ((*name).to_owned(), Value::String((*description).to_owned()))
            })
            .collect(),
    )
}

fn presets_value() -> Value {
    let mut object = serde_json::Map::new();
    for language in ["en", "de"] {
        if let Some((label, system, classification, tagging)) = prompt_preset(language) {
            object.insert(
                language.into(),
                serde_json::json!({
                    "label": label,
                    "system_prompt": system,
                    "classification_template": classification,
                    "tagging_prompt": tagging,
                }),
            );
        }
    }
    Value::Object(object)
}

fn value_i64(value: &Value) -> Option<i64> {
    value
        .as_i64()
        .or_else(|| value.as_u64().and_then(|number| i64::try_from(number).ok()))
        .or_else(|| value.as_str()?.parse().ok())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::paperless::{TagInfo, Taxonomy};
    use crate::prompt::{PromptConfig, TaggingMode};
    use std::collections::BTreeMap;

    fn taxonomy() -> Taxonomy {
        Taxonomy {
            document_types: vec!["Invoice".into()],
            correspondents: vec!["Example GmbH".into()],
            content_tags: vec!["Bank".into(), "Finance".into()],
            content_tag_ids: vec![1, 2],
            tag_by_name: BTreeMap::from([("Finance".into(), 1), ("Bank".into(), 2)]),
            tag_by_id: BTreeMap::from([(1, "Finance".into()), (2, "Bank".into())]),
            parent_by_id: BTreeMap::from([(1, None), (2, Some(1))]),
            tags: vec![
                TagInfo {
                    id: 2,
                    name: "Bank".into(),
                    parent: Some(1),
                },
                TagInfo {
                    id: 1,
                    name: "Finance".into(),
                    parent: None,
                },
            ],
        }
    }

    #[test]
    fn fast_path_inserts_history_tag_after_validation() {
        let config = PromptConfig {
            tagging_mode: TaggingMode::HistoryAssisted,
            ..PromptConfig::default()
        };
        let tagging = TaggingContext {
            mode: "history_assisted".into(),
            route: "history_match".into(),
            llm_decides: false,
            tag: Some("Finance".into()),
            examples: vec![],
            extra: Default::default(),
        };
        let result = serde_json::json!({
            "title": "Invoice March 2026",
            "document_type": "Invoice",
            "correspondent": "Example GmbH",
            "created": "2026-03-31",
        });
        let (result, errors, _) =
            finalize_model_result(result, &taxonomy(), &config, &tagging, false);
        assert!(errors.is_empty());
        assert_eq!(result["tags"], serde_json::json!(["Finance"]));
    }

    #[test]
    fn presets_and_placeholders_keep_ui_contract() {
        assert!(presets_value()["en"]["system_prompt"].is_string());
        assert!(placeholders_value()["DOCUMENT_TEXT"].is_string());
    }
}
