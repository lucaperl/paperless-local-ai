use crate::ai_lock;
use crate::app_config::{AppConfig, atomic_write_json, utc_now_iso};
use crate::control::finalize_model_result;
use crate::error::{Error, Result};
use crate::history::{self, history_error_context};
use crate::ollama::performance_from_raw;
use crate::paperless::{PaperlessDocument, Taxonomy, expand_tag_ids_with_ancestors};
use crate::prompt::{PromptConfig, TaggingContext, TaggingMode, prompt_hashes, render_prompts};
use crate::state::{CORE_CONTAINER_RECYCLE_IDLE_SECONDS, CoreState};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::{BTreeSet, HashMap};
use std::fs;
use std::path::PathBuf;
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::watch;

const RESULTS_DIR: &str = "/data/results";

fn log(message: impl AsRef<str>) {
    println!("{} {}", utc_now_iso().replace('T', " "), message.as_ref());
}

fn content_sha256(document: &PaperlessDocument) -> String {
    format!(
        "{:x}",
        Sha256::digest(document.content.as_deref().unwrap_or_default().as_bytes())
    )
}

async fn update_tags(
    state: &CoreState,
    doc_id: i64,
    add: impl IntoIterator<Item = i64>,
    remove: impl IntoIterator<Item = i64>,
) -> Result<()> {
    let document = state.paperless.document(doc_id).await?;
    let mut tags = document.tags.into_iter().collect::<BTreeSet<_>>();
    for tag in remove {
        tags.remove(&tag);
    }
    tags.extend(add);
    state
        .paperless
        .patch_document(doc_id, &serde_json::json!({"tags": tags}))
        .await?;
    Ok(())
}

async fn mark_success(
    state: &CoreState,
    doc_id: i64,
    queue_tag: i64,
    error_tag: i64,
) -> Result<()> {
    update_tags(state, doc_id, [], [queue_tag, error_tag]).await
}

async fn mark_error(
    state: &CoreState,
    doc_id: i64,
    queue_tag: i64,
    error_tag: i64,
    error: &Error,
    error_name: &str,
) {
    log(format!("[FAILED] ID {doc_id}: {error}"));
    match update_tags(state, doc_id, [error_tag], [queue_tag]).await {
        Ok(()) => log(format!("[FAILED] ID {doc_id}: marked with {error_name:?}")),
        Err(tag_error) => log(format!("[WARN] Could not set error status: {tag_error}")),
    }
}

async fn inbox_document_ids(
    state: &CoreState,
    taxonomy: &Taxonomy,
    review_tag_name: &str,
) -> Result<BTreeSet<i64>> {
    let inbox_tag = taxonomy
        .tag_by_name
        .get(review_tag_name)
        .copied()
        .ok_or_else(|| Error::Invalid(format!("Tag {review_tag_name:?} not found")))?;
    let mut ids = BTreeSet::new();
    let mut page = 1u64;
    loop {
        let query = vec![
            ("tags__id__all".into(), inbox_tag.to_string()),
            ("ordering".into(), "id".into()),
            ("page_size".into(), "100".into()),
            ("page".into(), page.to_string()),
            ("fields".into(), "id".into()),
        ];
        let data = state
            .paperless
            .request_json(reqwest::Method::GET, "/api/documents/", Some(&query), None)
            .await?;
        if let Some(results) = data.get("results").and_then(Value::as_array) {
            for item in results {
                if let Some(id) = value_i64(item.get("id")) {
                    ids.insert(id);
                }
            }
        }
        if data.get("next").is_none_or(Value::is_null) {
            break;
        }
        page += 1;
    }
    Ok(ids)
}

async fn prune_review_records(
    state: &CoreState,
    taxonomy: &Taxonomy,
    review_tag_name: &str,
) -> Result<Vec<i64>> {
    let inbox_ids = inbox_document_ids(state, taxonomy, review_tag_name).await?;
    let mut removed = Vec::new();
    let dir = state.review.dir();
    if !dir.exists() {
        return Ok(removed);
    }
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let path = entry.path();
        if path.extension().and_then(|value| value.to_str()) != Some("json") {
            continue;
        }
        let Some(doc_id) = path
            .file_stem()
            .and_then(|value| value.to_str())
            .and_then(|value| value.parse::<i64>().ok())
        else {
            continue;
        };
        if !inbox_ids.contains(&doc_id) {
            state.review.remove(doc_id)?;
            removed.push(doc_id);
        }
    }
    removed.sort_unstable();
    if !removed.is_empty() {
        log(format!(
            "[REVIEW-PRUNE] {} completed/orphaned record(s) removed: {}",
            removed.len(),
            removed
                .iter()
                .map(i64::to_string)
                .collect::<Vec<_>>()
                .join(",")
        ));
    }
    Ok(removed)
}

async fn write_review_record_safe(
    state: &CoreState,
    doc_id: i64,
    resolution: &crate::correspondent::CorrespondentResolution,
) {
    let result = async {
        let fresh = state.paperless.document(doc_id).await?;
        let candidate = &resolution.suggestion;
        let record = state.review.write(
            &fresh,
            candidate,
            serde_json::json!({
                "status": resolution.status,
                "extracted": resolution.extracted,
                "matched_existing": if resolution.resolved.is_empty() {
                    Value::Null
                } else {
                    Value::String(resolution.resolved.clone())
                },
                "match_score": resolution.match_score,
                "runner_up_score": resolution.runner_up_score,
            }),
        )?;
        Ok::<_, Error>((record.version, candidate.clone()))
    }
    .await;

    match result {
        Ok((version, candidate)) => log(format!(
            "[REVIEW] ID {doc_id}: wrote record v{version}{}",
            if candidate.is_empty() {
                ", no new correspondent suggestion".into()
            } else {
                format!(", correspondent suggestion={candidate:?}")
            }
        )),
        Err(error) => log(format!("[REVIEW-WARN] ID {doc_id}: {error}")),
    }
}

async fn apply_metadata_and_finish(
    state: &CoreState,
    doc_id: i64,
    result: &Value,
    taxonomy: &Taxonomy,
    queue_tag: i64,
    error_tag: i64,
) -> Result<()> {
    let fresh = state.paperless.document(doc_id).await?;
    let managed = taxonomy
        .content_tag_ids
        .iter()
        .copied()
        .collect::<BTreeSet<_>>();
    let mut final_tags = fresh
        .tags
        .into_iter()
        .filter(|tag| !managed.contains(tag))
        .collect::<BTreeSet<_>>();
    let mut selected_content_tags = Vec::new();
    for name in result
        .get("tags")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
    {
        selected_content_tags.push(
            *taxonomy
                .tag_by_name
                .get(name)
                .ok_or_else(|| Error::Invalid(format!("Unknown final tag {name:?}")))?,
        );
    }
    final_tags.extend(expand_tag_ids_with_ancestors(
        selected_content_tags,
        taxonomy,
    ));
    final_tags.remove(&queue_tag);
    final_tags.remove(&error_tag);

    let title = result
        .get("title")
        .and_then(Value::as_str)
        .unwrap_or_default()
        .trim();
    let document_type = result
        .get("document_type")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let correspondent = result
        .get("correspondent")
        .and_then(Value::as_str)
        .unwrap_or_default();
    let mut payload = serde_json::json!({
        "title": title,
        "document_type": state.paperless.resolve_named_id("/api/document_types/", document_type).await?,
        "correspondent": state.paperless.resolve_named_id("/api/correspondents/", correspondent).await?,
        "tags": final_tags,
    });
    if let Some(created) = result
        .get("created")
        .and_then(Value::as_str)
        .filter(|value| !value.is_empty())
    {
        payload["created"] = Value::String(created.to_owned());
    }
    state.paperless.patch_document(doc_id, &payload).await?;
    Ok(())
}

async fn process(
    state: &CoreState,
    fresh: &PaperlessDocument,
    taxonomy: &Taxonomy,
    app_config: &AppConfig,
    config: &PromptConfig,
    mut tagging: TaggingContext,
) -> Result<()> {
    let doc_id = fresh.id;
    let queue_name = &app_config.workflow.llm_queue_tag;
    let error_name = &app_config.workflow.llm_error_tag;
    let queue_tag = taxonomy
        .tag_by_name
        .get(queue_name)
        .copied()
        .ok_or_else(|| Error::Invalid(format!("Tag {queue_name:?} not found")))?;
    let error_tag = taxonomy
        .tag_by_name
        .get(error_name)
        .copied()
        .ok_or_else(|| Error::Invalid(format!("Tag {error_name:?} not found")))?;

    if config.tagging_mode == TaggingMode::LlmOnly {
        tagging = history::llm_only_context();
    } else if tagging.mode != "history_assisted" {
        tagging = history_error_context("Tagging mode changed after history batch routing");
    }

    let rendered = render_prompts(fresh, taxonomy, config, Some(tagging.clone()))?;
    log(format!(
        "[JOB] ID {doc_id}: {} characters{}, PromptConfig v{}, tagging={}",
        rendered.content_chars_used,
        if rendered.content_truncated {
            " (truncated)"
        } else {
            ""
        },
        config.version,
        tagging.route
    ));

    let call = state.ollama.call(&rendered, config, None).await?;
    let (result, validation_errors, resolution) = finalize_model_result(
        call.result,
        taxonomy,
        config,
        &tagging,
        rendered.tags_enabled,
    );
    let hashes = prompt_hashes(config);
    let performance = performance_from_raw(&call.raw, call.wall_duration);
    let report = serde_json::json!({
        "document_id": doc_id,
        "generated_at": utc_now_iso(),
        "model": config.model,
        "dry_run": app_config.runtime.dry_run,
        "content_chars_used": rendered.content_chars_used,
        "content_truncated": rendered.content_truncated,
        "prompt": {
            "config_version": config.version,
            "config_updated_at": config.updated_at,
            "system_sha256": hashes["system_sha256"],
            "classification_sha256": hashes["classification_sha256"],
            "tagging_sha256": hashes["tagging_sha256"],
            "config_sha256": hashes["config_sha256"],
        },
        "settings": {
            "num_ctx": config.num_ctx,
            "num_predict": config.num_predict,
            "temperature": config.temperature,
            "think": config.think,
            "keep_alive": config.keep_alive,
            "content_char_limit": config.content_char_limit,
            "content_head_ratio": config.content_head_ratio,
            "max_tags": config.max_tags,
            "tagging_mode": config.tagging_mode,
        },
        "tagging": tagging,
        "suggestion": result,
        "validation_errors": validation_errors,
        "correspondent_resolution": resolution,
        "performance": performance,
    });
    let result_path = PathBuf::from(RESULTS_DIR).join(format!("{doc_id}.json"));
    atomic_write_json(&result_path, &report)?;

    let errors = report["validation_errors"]
        .as_array()
        .into_iter()
        .flatten()
        .filter_map(Value::as_str)
        .collect::<Vec<_>>();
    if !errors.is_empty() {
        return Err(Error::Invalid(format!(
            "LLM response is invalid: {}",
            errors.join("; ")
        )));
    }

    log(format!(
        "[SUGGEST] ID {doc_id}: {}",
        serde_json::to_string(&report["suggestion"])?
    ));
    let perf = &report["performance"];
    log(format!(
        "[PERF] ID {doc_id}: {:.1}s total, {} Prompt-Tokens, {} Output-Tokens",
        perf.get("wall_seconds")
            .and_then(Value::as_f64)
            .unwrap_or(0.0),
        perf.get("prompt_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0),
        perf.get("output_tokens")
            .and_then(Value::as_u64)
            .unwrap_or(0)
    ));
    log(format!(
        "[TAGS] ID {doc_id}: {}",
        serde_json::to_string(&serde_json::json!({
            "mode": config.tagging_mode,
            "route": report["tagging"]["route"],
            "tags": report["suggestion"]["tags"],
            "similarity": report["tagging"].get("similarity"),
        }))?
    ));
    if report["correspondent_resolution"]["status"].as_str() != Some("empty") {
        log(format!(
            "[CORR] ID {doc_id}: {}",
            serde_json::to_string(&report["correspondent_resolution"])?
        ));
    }

    if app_config.runtime.dry_run {
        log(format!(
            "[DRY-RUN] ID {doc_id}: no document metadata changed"
        ));
        log(format!(
            "[DRY-RUN] ID {doc_id}: no persistent review record written"
        ));
        mark_success(state, doc_id, queue_tag, error_tag).await?;
    } else {
        apply_metadata_and_finish(
            state,
            doc_id,
            &report["suggestion"],
            taxonomy,
            queue_tag,
            error_tag,
        )
        .await?;
        log(format!("[APPLY] ID {doc_id}: metadata saved to Paperless"));
        write_review_record_safe(state, doc_id, &resolution).await;
    }
    Ok(())
}

async fn wait_poll_interval(seconds: u32, shutdown: &mut watch::Receiver<bool>) -> bool {
    match tokio::time::timeout(Duration::from_secs(u64::from(seconds)), shutdown.changed()).await {
        Ok(Ok(())) => *shutdown.borrow(),
        Ok(Err(_)) => true,
        Err(_) => false,
    }
}

pub async fn run(state: Arc<CoreState>, mut shutdown: watch::Receiver<bool>) -> Result<()> {
    fs::create_dir_all(RESULTS_DIR)?;
    let app_config = state.app_config.ensure()?;
    let config = state.prompt_config.ensure()?;
    log("[BOOT] Paperless local metadata worker");
    log(format!(
        "[BOOT] AppConfig: /config/app-config.json (v{})",
        app_config.version
    ));
    log(format!(
        "[BOOT] PromptConfig: /config/prompt-config.json (v{})",
        config.version
    ));
    log(format!("[BOOT] Model: {}", config.model));
    log(format!("[BOOT] Context: {}", config.num_ctx));
    log(format!("[BOOT] Tagging: {:?}", config.tagging_mode));
    log("[BOOT] History engine is loaded on demand and released after use");
    log("[BOOT] Prompt and app settings are reloaded continuously");

    let mut last_review_prune: Option<Instant> = None;
    while !*shutdown.borrow() {
        let mut poll_interval = 10u32;
        let cycle = async {
            let app_config = state.app_config.load()?;
            poll_interval = app_config.runtime.poll_interval_seconds;
            let queue_name = &app_config.workflow.llm_queue_tag;
            let error_name = &app_config.workflow.llm_error_tag;
            let review_name = &app_config.workflow.review_tag;
            let taxonomy = state.paperless.taxonomy().await?;

            for name in [queue_name, error_name, review_name] {
                if !taxonomy.tag_by_name.contains_key(name) {
                    return Err(Error::Invalid(format!("Tag {name:?} not found")));
                }
            }

            if last_review_prune.is_none_or(|last| {
                last.elapsed()
                    >= Duration::from_secs(u64::from(app_config.runtime.review_prune_interval_seconds))
            }) {
                prune_review_records(&state, &taxonomy, review_name).await?;
                last_review_prune = Some(Instant::now());
            }

            let queue_tag = taxonomy.tag_by_name[queue_name];
            let error_tag = taxonomy.tag_by_name[error_name];
            let query = vec![
                ("tags__id__all".into(), queue_tag.to_string()),
                ("ordering".into(), "added".into()),
                ("page_size".into(), "20".into()),
            ];
            let data = state
                .paperless
                .request_json(reqwest::Method::GET, "/api/documents/", Some(&query), None)
                .await?;
            let docs = data
                .get("results")
                .and_then(Value::as_array)
                .cloned()
                .unwrap_or_default();

            let had_queue_items = !docs.is_empty();
            if had_queue_items {
                state.recycle.cancel();
                log("[RECYCLE] Metadata work started; pending core recycle cancelled");
            }

            let mut routing_docs = Vec::new();
            let mut routed_hashes = HashMap::new();
            for item in docs {
                let Some(doc_id) = value_i64(item.get("id")) else {
                    continue;
                };
                match state.paperless.document(doc_id).await {
                    Ok(snapshot) => {
                        routed_hashes.insert(doc_id, content_sha256(&snapshot));
                        routing_docs.push(snapshot);
                    }
                    Err(error) => {
                        mark_error(&state, doc_id, queue_tag, error_tag, &error, error_name).await;
                    }
                }
            }

            let routed_ids = routing_docs.iter().map(|document| document.id).collect::<Vec<_>>();
            let routing_config = state.prompt_config.load()?;
            let mut tagging_by_id = history::history_contexts_for_documents(
                &state.history,
                &routing_config,
                &routing_docs,
                true,
            )
            .await;
            drop(routing_docs);

            for doc_id in routed_ids {
                let job = async {
                    let _ai_guard = ai_lock::acquire(ai_lock::configured_ai_lock_path()).await?;
                    let fresh = state.paperless.document(doc_id).await?;
                    let config = state.prompt_config.load()?;
                    let mut tagging = tagging_by_id.remove(&doc_id).unwrap_or_else(|| {
                        history_error_context("No history route was prepared for this document")
                    });
                    if config.tagging_mode == TaggingMode::HistoryAssisted
                        && routed_hashes
                            .get(&doc_id)
                            .is_some_and(|hash| hash != &content_sha256(&fresh))
                    {
                        tagging = history_error_context(
                            "Document content changed after History batch routing",
                        );
                        log(format!(
                            "[HISTORY] ID {doc_id}: content changed after batch routing; using LLM fallback"
                        ));
                    }
                    let result = process(&state, &fresh, &taxonomy, &app_config, &config, tagging).await;
                    match state.ollama.unload_model(&config.model).await {
                        Ok(()) => log(format!("[UNLOAD] Ollama model released: {}", config.model)),
                        Err(error) => log(format!(
                            "[UNLOAD-WARN] {}: {error}",
                            config.model
                        )),
                    }
                    result
                }
                .await;
                if let Err(error) = job {
                    mark_error(&state, doc_id, queue_tag, error_tag, &error, error_name).await;
                }
            }

            if had_queue_items {
                state.recycle.schedule();
                log(format!(
                    "[RECYCLE] Metadata batch completed; core recycle scheduled after {}s idle",
                    CORE_CONTAINER_RECYCLE_IDLE_SECONDS
                ));
            }
            Ok::<(), Error>(())
        }
        .await;

        if let Err(error) = cycle {
            log(format!("[ERROR] Worker/Polling: {error}"));
        }
        if wait_poll_interval(poll_interval, &mut shutdown).await {
            break;
        }
    }
    Ok(())
}

fn value_i64(value: Option<&Value>) -> Option<i64> {
    let value = value?;
    value
        .as_i64()
        .or_else(|| value.as_u64().and_then(|number| i64::try_from(number).ok()))
        .or_else(|| value.as_str()?.parse().ok())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn content_hash_tracks_freshness_input() {
        let mut document = PaperlessDocument {
            id: 1,
            title: None,
            created: None,
            content: Some("alpha".into()),
            tags: vec![],
        };
        let first = content_sha256(&document);
        document.content = Some("beta".into());
        assert_ne!(first, content_sha256(&document));
    }
}
