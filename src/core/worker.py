from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from app_config import ensure_config as ensure_app_config, load_config as load_app_config
from correspondent_resolver import resolve_correspondent
from history_runtime import HistoryIndex
from prompt_runtime import (
    PaperlessClient,
    ai_resource_lock,
    call_ollama,
    ensure_config,
    load_config,
    performance_from_raw,
    prompt_hashes,
    prune_parent_tag_names,
    render_prompts,
    unload_ollama_model,
    validate_result,
)
from review_store import REVIEW_DIR, write_review_record


RESULTS = Path("/data/results")
RESULTS.mkdir(parents=True, exist_ok=True)

client = PaperlessClient()
history_index = HistoryIndex()


def log(msg: str) -> None:
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def current_document(doc_id: int) -> dict[str, Any]:
    return client.document(doc_id)


def update_tags(doc_id: int, add=None, remove=None) -> None:
    add = set(add or [])
    remove = set(remove or [])
    doc = current_document(doc_id)
    tags = set(doc.get("tags", []))
    tags -= remove
    tags |= add
    client.request("PATCH", f"/api/documents/{doc_id}/", json={"tags": sorted(tags)})


def resolve_named_id(path: str, name: str):
    if not name:
        return None
    for obj in client.all_objects(path):
        if obj.get("name") == name:
            return obj["id"]
    raise RuntimeError(f"Value {name!r} no longer exists in {path}")


def apply_metadata_and_finish(
    doc_id: int,
    result: dict[str, Any],
    tax: dict[str, Any],
    queue_tag: int,
    error_tag: int,
) -> None:
    fresh = current_document(doc_id)
    current_tag_ids = set(fresh.get("tags", []))
    managed_content_tag_ids = set(tax.get("content_tag_ids", []))
    final_tag_ids = current_tag_ids - managed_content_tag_ids
    for name in result["tags"]:
        final_tag_ids.add(tax["tag_by_name"][name])
    final_tag_ids.discard(queue_tag)
    final_tag_ids.discard(error_tag)

    payload = {
        "title": result["title"].strip(),
        "document_type": resolve_named_id("/api/document_types/", result["document_type"]),
        "correspondent": resolve_named_id("/api/correspondents/", result["correspondent"]),
        "tags": sorted(final_tag_ids),
    }
    if result.get("created"):
        payload["created"] = result["created"]
    client.request("PATCH", f"/api/documents/{doc_id}/", json=payload)


def mark_success(doc_id: int, queue_tag: int, error_tag: int) -> None:
    update_tags(doc_id, remove={queue_tag, error_tag})


def mark_error(doc_id: int, queue_tag: int, error_tag: int, error: Exception, error_name: str) -> None:
    log(f"[FAILED] ID {doc_id}: {type(error).__name__}: {error}")
    try:
        update_tags(doc_id, add={error_tag}, remove={queue_tag})
        log(f"[FAILED] ID {doc_id}: marked with '{error_name}'")
    except Exception as tag_error:
        log(f"[WARN] Could not set error status: {tag_error}")


def _inbox_document_ids(tax: dict[str, Any], review_tag_name: str) -> set[int]:
    inbox_tag = tax["tag_by_name"].get(review_tag_name)
    if inbox_tag is None:
        raise RuntimeError(f"Tag {review_tag_name!r} not found")
    ids: set[int] = set()
    page = 1
    while True:
        data = client.request(
            "GET",
            "/api/documents/",
            params={
                "tags__id__all": inbox_tag,
                "ordering": "id",
                "page_size": 100,
                "page": page,
                "fields": "id",
            },
        ).json()
        for item in data.get("results", []):
            ids.add(int(item["id"]))
        if not data.get("next"):
            break
        page += 1
    return ids


def prune_review_records(tax: dict[str, Any], review_tag_name: str) -> list[int]:
    inbox_ids = _inbox_document_ids(tax, review_tag_name)
    removed = []
    if REVIEW_DIR.exists():
        for path in REVIEW_DIR.glob("*.json"):
            try:
                doc_id = int(path.stem)
            except ValueError:
                continue
            if doc_id in inbox_ids:
                continue
            path.unlink(missing_ok=True)
            removed.append(doc_id)
    if removed:
        log(
            "[REVIEW-PRUNE] "
            + f"{len(removed)} completed/orphaned record(s) removed: "
            + ",".join(str(x) for x in sorted(removed))
        )
    return removed


def write_review_record_safe(
    doc_id: int,
    correspondent_resolution: dict[str, Any],
) -> None:
    try:
        fresh = current_document(doc_id)
        candidate = correspondent_resolution.get("suggestion", "")
        record = write_review_record(
            fresh,
            correspondent_suggestion=candidate,
            correspondent_meta={
                "status": correspondent_resolution.get("status"),
                "extracted": correspondent_resolution.get("extracted"),
                "matched_existing": correspondent_resolution.get("resolved") or None,
                "match_score": correspondent_resolution.get("match_score"),
                "runner_up_score": correspondent_resolution.get("runner_up_score"),
            },
        )
        log(
            f"[REVIEW] ID {doc_id}: wrote record v{record['version']}"
            + (f", correspondent suggestion={candidate!r}" if candidate else ", no new correspondent suggestion")
        )
    except Exception as exc:
        log(f"[REVIEW-WARN] ID {doc_id}: {type(exc).__name__}: {exc}")


def process(doc: dict[str, Any], tax: dict[str, Any], app_cfg: dict[str, Any]) -> None:
    doc_id = int(doc["id"])
    fresh = current_document(doc_id)
    workflow = app_cfg["workflow"]
    runtime = app_cfg["runtime"]
    queue_name = workflow["llm_queue_tag"]
    error_name = workflow["llm_error_tag"]
    review_name = workflow["review_tag"]
    queue_tag = tax["tag_by_name"][queue_name]
    error_tag = tax["tag_by_name"][error_name]

    config = load_config()
    tagging = history_index.tagging_context(
        client,
        tax,
        config,
        [review_name, queue_name, error_name],
        fresh,
    )
    rendered = render_prompts(fresh, tax, config, tagging=tagging)

    route = tagging.get("route", "llm_only")
    log(
        f"[JOB] ID {doc_id}: {rendered['content_chars_used']} characters"
        + (" (truncated)" if rendered["content_truncated"] else "")
        + f", PromptConfig v{config['version']}, tagging={route}"
    )

    result, raw, wall_duration, _payload = call_ollama(rendered, config)
    validation_errors = validate_result(
        result,
        tax,
        config,
        tags_enabled=rendered["tags_enabled"],
    )

    correspondent_resolution = {
        "extracted": "",
        "status": "skipped_main_invalid",
        "resolved": "",
        "suggestion": "",
        "match_score": None,
        "runner_up_score": None,
    }

    if not validation_errors:
        correspondent_resolution = resolve_correspondent(
            result.get("correspondent", ""),
            tax["correspondents"],
        )
        result["correspondent"] = correspondent_resolution["resolved"]
        if route == "history_match":
            result["tags"] = [tagging["tag"]]
        else:
            result["tags"] = prune_parent_tag_names(result.get("tags", []), tax)

    hashes = prompt_hashes(config)
    report = {
        "document_id": doc_id,
        "generated_at": datetime.now().astimezone().isoformat(),
        "model": config["model"],
        "dry_run": runtime["dry_run"],
        "content_chars_used": rendered["content_chars_used"],
        "content_truncated": rendered["content_truncated"],
        "prompt": {
            "config_version": config["version"],
            "config_updated_at": config.get("updated_at"),
            **hashes,
        },
        "settings": {
            "num_ctx": config["num_ctx"],
            "num_predict": config["num_predict"],
            "temperature": config["temperature"],
            "think": config["think"],
            "keep_alive": config["keep_alive"],
            "content_char_limit": config["content_char_limit"],
            "content_head_ratio": config["content_head_ratio"],
            "max_tags": config["max_tags"],
            "tagging_mode": config["tagging_mode"],
        },
        "tagging": tagging,
        "suggestion": result,
        "validation_errors": validation_errors,
        "correspondent_resolution": correspondent_resolution,
        "performance": performance_from_raw(raw, wall_duration),
    }
    result_file = RESULTS / f"{doc_id}.json"
    result_file.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    if validation_errors:
        raise RuntimeError("LLM response is invalid: " + "; ".join(validation_errors))

    perf = report["performance"]
    log(f"[SUGGEST] ID {doc_id}: " + json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    log(
        f"[PERF] ID {doc_id}: {perf['wall_seconds']:.1f}s total, "
        f"{perf['prompt_tokens']} Prompt-Tokens, {perf['output_tokens']} Output-Tokens"
    )
    log(
        f"[TAGS] ID {doc_id}: "
        + json.dumps(
            {
                "mode": config["tagging_mode"],
                "route": route,
                "tags": result["tags"],
                "similarity": tagging.get("similarity"),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    if correspondent_resolution["status"] != "empty":
        log(
            f"[CORR] ID {doc_id}: "
            + json.dumps(correspondent_resolution, ensure_ascii=False, separators=(",", ":"))
        )

    if runtime["dry_run"]:
        log(f"[DRY-RUN] ID {doc_id}: no document metadata changed")
        log(f"[DRY-RUN] ID {doc_id}: no persistent review record written")
        mark_success(doc_id, queue_tag, error_tag)
    else:
        apply_metadata_and_finish(doc_id, result, tax, queue_tag, error_tag)
        log(f"[APPLY] ID {doc_id}: metadata saved to Paperless")
        write_review_record_safe(doc_id, correspondent_resolution)


def main() -> None:
    app_cfg = ensure_app_config()
    config = ensure_config()
    log("[BOOT] Paperless local metadata worker")
    log(f"[BOOT] AppConfig: /config/app-config.json (v{app_cfg['version']})")
    log(f"[BOOT] PromptConfig: /config/prompt-config.json (v{config['version']})")
    log(f"[BOOT] Model: {config['model']}")
    log(f"[BOOT] Context: {config['num_ctx']}")
    log(f"[BOOT] Tagging: {config['tagging_mode']}")
    log("[BOOT] Prompt and app settings are reloaded continuously")

    last_review_prune = 0.0
    while True:
        poll_interval = 10
        try:
            app_cfg = load_app_config()
            workflow = app_cfg["workflow"]
            runtime = app_cfg["runtime"]
            poll_interval = runtime["poll_interval_seconds"]
            queue_name = workflow["llm_queue_tag"]
            error_name = workflow["llm_error_tag"]
            review_name = workflow["review_tag"]

            tax = client.taxonomy()
            if queue_name not in tax["tag_by_name"]:
                raise RuntimeError(f'Tag "{queue_name}" not found')
            if error_name not in tax["tag_by_name"]:
                raise RuntimeError(f'Tag "{error_name}" not found')
            if review_name not in tax["tag_by_name"]:
                raise RuntimeError(f'Tag "{review_name}" not found')

            now = time.monotonic()
            if now - last_review_prune >= runtime["review_prune_interval_seconds"]:
                prune_review_records(tax, review_name)
                last_review_prune = now

            queue_tag = tax["tag_by_name"][queue_name]
            error_tag = tax["tag_by_name"][error_name]
            docs = client.request(
                "GET",
                "/api/documents/",
                params={
                    "tags__id__all": queue_tag,
                    "ordering": "added",
                    "page_size": 20,
                },
            ).json()["results"]

            for doc in docs:
                try:
                    with ai_resource_lock("LLM", doc["id"]):
                        config = load_config()
                        try:
                            process(doc, tax, app_cfg)
                        finally:
                            try:
                                unload_ollama_model(config["model"])
                                log(f"[UNLOAD] Ollama model released: {config['model']}")
                            except Exception as exc:
                                log(f"[UNLOAD-WARN] {config['model']}: {type(exc).__name__}: {exc}")
                except Exception as exc:
                    mark_error(doc["id"], queue_tag, error_tag, exc, error_name)
        except Exception as exc:
            log(f"[ERROR] Worker/Polling: {type(exc).__name__}: {exc}")
        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
