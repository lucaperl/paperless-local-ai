import json
import time
from datetime import datetime
from pathlib import Path

from app_config import (
    blocking_tag_names,
    ensure_config as ensure_app_config,
    load_config as load_app_config,
)

from prompt_runtime import (
    PaperlessClient,
    ai_resource_lock,
    call_ollama,
    ensure_config,
    load_config,
    performance_from_raw,
    prompt_hashes,
    render_prompts,
    validate_result,
)

from correspondent_runtime import (
    call_ollama as call_correspondent_ollama,
    load_config as load_correspondent_config,
    performance_from_raw as correspondent_performance_from_raw,
    prompt_hashes as correspondent_prompt_hashes,
    render_prompts as render_correspondent_prompts,
    validate_result as validate_correspondent_result,
)
from review_store import REVIEW_DIR, write_review_record


RESULTS = Path("/data/results")
RESULTS.mkdir(parents=True, exist_ok=True)

client = PaperlessClient()


def log(msg):
    print(time.strftime("%Y-%m-%d %H:%M:%S"), msg, flush=True)


def current_document(doc_id):
    return client.document(doc_id)


def update_tags(doc_id, add=None, remove=None):
    add = set(add or [])
    remove = set(remove or [])
    doc = current_document(doc_id)
    tags = set(doc.get("tags", []))
    tags -= remove
    tags |= add
    client.request(
        "PATCH",
        f"/api/documents/{doc_id}/",
        json={"tags": sorted(tags)},
    )


def resolve_named_id(path, name):
    if not name:
        return None
    for obj in client.all_objects(path):
        if obj.get("name") == name:
            return obj["id"]
    raise RuntimeError(f"Value {name!r} no longer exists in {path}")


def apply_metadata_and_finish(doc_id, result, tax, queue_tag, error_tag):
    fresh = current_document(doc_id)
    current_tag_ids = set(fresh.get("tags", []))
    managed_content_tag_ids = {
        tax["tag_by_name"][name]
        for name in tax["content_tags"]
        if name in tax["tag_by_name"]
    }
    final_tag_ids = current_tag_ids - managed_content_tag_ids
    for name in result["tags"]:
        final_tag_ids.add(tax["tag_by_name"][name])
    final_tag_ids.discard(queue_tag)
    final_tag_ids.discard(error_tag)

    payload = {
        "title": result["title"].strip(),
        "document_type": resolve_named_id(
            "/api/document_types/",
            result["document_type"],
        ),
        "correspondent": resolve_named_id(
            "/api/correspondents/",
            result["correspondent"],
        ),
        "tags": sorted(final_tag_ids),
    }
    if result.get("created"):
        payload["created"] = result["created"]

    client.request(
        "PATCH",
        f"/api/documents/{doc_id}/",
        json=payload,
    )


def mark_success(doc_id, queue_tag, error_tag):
    update_tags(doc_id, remove={queue_tag, error_tag})


def mark_error(doc_id, queue_tag, error_tag, error, error_name):
    log(f"[FAILED] ID {doc_id}: {type(error).__name__}: {error}")
    try:
        update_tags(
            doc_id,
            add={error_tag},
            remove={queue_tag},
        )
        log(f"[FAILED] ID {doc_id}: marked with '{error_name}'")
    except Exception as tag_error:
        log(f"[WARN] Could not set error status: {tag_error}")


def run_correspondent_fallback(fresh, tax, main_result):
    fallback = {"enabled": False, "status": "not_needed", "suggestion": {"correspondent": ""}, "validation_errors": []}
    if main_result.get("correspondent"):
        return "", fallback
    try:
        config = load_correspondent_config()
    except Exception as exc:
        fallback.update({"status": "config_error", "error": f"{type(exc).__name__}: {exc}"})
        return "", fallback
    fallback["enabled"] = bool(config["enabled"])
    fallback["config_version"] = config["version"]
    fallback["config_updated_at"] = config.get("updated_at")
    fallback["prompt"] = correspondent_prompt_hashes(config)
    if not config["enabled"]:
        fallback["status"] = "disabled"
        return "", fallback
    try:
        rendered = render_correspondent_prompts(fresh, tax, config)
        result, raw, wall_duration, _payload = call_correspondent_ollama(rendered, config)
        errors = validate_correspondent_result(result)
        fallback.update({
            "status": "invalid" if errors else "ok",
            "content_chars_used": rendered["content_chars_used"],
            "content_truncated": rendered["content_truncated"],
            "settings": {
                "model": config["model"], "num_ctx": config["num_ctx"], "num_predict": config["num_predict"],
                "temperature": config["temperature"], "think": config["think"], "keep_alive": config["keep_alive"],
                "content_char_limit": config["content_char_limit"], "content_head_ratio": config["content_head_ratio"],
            },
            "suggestion": result, "validation_errors": errors,
            "performance": correspondent_performance_from_raw(raw, wall_duration),
        })
        if errors:
            return "", fallback
        candidate = result.get("correspondent", "")
        if not candidate:
            fallback["status"] = "empty"
            return "", fallback
        fallback["status"] = "candidate"
        return candidate, fallback
    except Exception as exc:
        fallback.update({"status": "error", "error": f"{type(exc).__name__}: {exc}"})
        return "", fallback



def normalize_correspondent_name(name):
    return " ".join(
        str(name or "").split()
    ).strip().casefold()


def route_correspondent_candidate(candidate, tax, main_result, fallback):
    """
    An exact normalized match against an existing Paperless correspondent is
    safe to apply automatically. Only genuinely new names remain pending for
    human review in Paperless.
    """
    candidate = " ".join(
        str(candidate or "").split()
    ).strip()

    if not candidate:
        return ""

    existing_by_normalized = {
        normalize_correspondent_name(name): name
        for name in tax.get(
            "correspondents",
            [],
        )
        if str(name).strip()
    }

    canonical = existing_by_normalized.get(
        normalize_correspondent_name(
            candidate
        )
    )

    if canonical:
        main_result["correspondent"] = canonical
        fallback["candidate_kind"] = "existing"
        fallback["matched_existing"] = canonical
        log(
            f"[CORR] exact existing correspondent match: "
            f"{canonical!r} -> applied automatically"
        )
        return ""

    fallback["candidate_kind"] = "new"
    fallback["matched_existing"] = None

    return candidate


def _inbox_document_ids(tax, review_tag_name):
    inbox_tag = tax["tag_by_name"].get(
        review_tag_name
    )

    if inbox_tag is None:
        raise RuntimeError(
            f'Tag {review_tag_name!r} not found'
        )

    ids = set()
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
            },
        ).json()

        for item in data.get(
            "results",
            [],
        ):
            ids.add(
                int(item["id"])
            )

        if not data.get("next"):
            break

        page += 1

    return ids


def prune_review_records(tax, review_tag_name):
    """
    Keep the persistent bridge index limited to documents that are still in
    the configured human review tag. A complete successful API listing is obtained
    before anything is deleted.
    """
    inbox_ids = _inbox_document_ids(
        tax,
        review_tag_name,
    )

    removed = []

    if REVIEW_DIR.exists():
        for path in REVIEW_DIR.glob(
            "*.json"
        ):
            try:
                doc_id = int(
                    path.stem
                )
            except ValueError:
                continue

            if doc_id in inbox_ids:
                continue

            path.unlink(
                missing_ok=True
            )
            removed.append(
                doc_id
            )

    if removed:
        log(
            "[REVIEW-PRUNE] "
            + f"{len(removed)} completed/orphaned record(s) removed: "
            + ",".join(
                str(x)
                for x in sorted(
                    removed
                )
            )
        )

    return removed

def write_review_record_safe(doc_id, candidate, fallback):
    try:
        fresh = current_document(doc_id)
        record = write_review_record(
            fresh,
            correspondent_suggestion=candidate,
            correspondent_meta={
                "status": fallback.get("status"),
                "candidate_kind": fallback.get("candidate_kind"),
                "matched_existing": fallback.get("matched_existing"),
                "config_version": fallback.get("config_version"),
                "prompt": fallback.get("prompt", {}),
            },
        )
        log(f"[REVIEW] ID {doc_id}: wrote record v{record['version']}" + (f", correspondent suggestion={candidate!r}" if candidate else ", no additional correspondent suggestion"))
    except Exception as exc:
        log(f"[REVIEW-WARN] ID {doc_id}: {type(exc).__name__}: {exc}")


def process(doc, tax, app_cfg):
    doc_id = doc["id"]
    fresh = current_document(doc_id)
    tag_ids = set(fresh.get("tags", []))

    workflow = app_cfg["workflow"]
    runtime = app_cfg["runtime"]
    queue_name = workflow["llm_queue_tag"]
    error_name = workflow["llm_error_tag"]
    blocking_names = blocking_tag_names(app_cfg)

    queue_tag = tax["tag_by_name"][queue_name]
    error_tag = tax["tag_by_name"][error_name]

    blocking_ids = {
        tax["tag_by_name"][name]
        for name in blocking_names
        if name in tax["tag_by_name"]
    }
    active_blockers = tag_ids & blocking_ids
    if active_blockers:
        names = [
            name
            for name in blocking_names
            if tax["tag_by_name"].get(name) in active_blockers
        ]
        log(f"[WAIT] ID {doc_id}: blocked by {', '.join(sorted(names))}")
        return

    config = load_config()
    rendered = render_prompts(fresh, tax, config)

    log(
        f"[JOB] ID {doc_id}: {rendered['content_chars_used']} characters"
        + (" (truncated)" if rendered["content_truncated"] else "")
        + f", PromptConfig v{config['version']}"
    )

    result, raw, wall_duration, _payload = call_ollama(rendered, config)
    validation_errors = validate_result(result, tax, config)

    correspondent_candidate = ""
    correspondent_fallback = {"enabled": False, "status": "skipped_main_invalid", "suggestion": {"correspondent": ""}, "validation_errors": []}
    if not validation_errors:
        correspondent_candidate, correspondent_fallback = run_correspondent_fallback(
            fresh,
            tax,
            result,
        )
        correspondent_candidate = route_correspondent_candidate(
            correspondent_candidate,
            tax,
            result,
            correspondent_fallback,
        )

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
        },
        "suggestion": result,
        "validation_errors": validation_errors,
        "correspondent_fallback": correspondent_fallback,
        "performance": performance_from_raw(raw, wall_duration),
    }

    result_file = RESULTS / f"{doc_id}.json"
    result_file.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if validation_errors:
        raise RuntimeError(
            "LLM response is invalid: " + "; ".join(validation_errors)
        )

    perf = report["performance"]
    log(
        f"[SUGGEST] ID {doc_id}: "
        + json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    )
    log(
        f"[PERF] ID {doc_id}: {perf['wall_seconds']:.1f}s total, "
        f"{perf['prompt_tokens']} Prompt-Tokens, "
        f"{perf['output_tokens']} Output-Tokens"
    )
    if correspondent_fallback.get("status") not in {"not_needed", "disabled"}:
        log(f"[CORR] ID {doc_id}: " + json.dumps({"status": correspondent_fallback.get("status"), "suggestion": correspondent_fallback.get("suggestion"), "validation_errors": correspondent_fallback.get("validation_errors")}, ensure_ascii=False, separators=(",", ":")))

    if runtime["dry_run"]:
        log(f"[DRY-RUN] ID {doc_id}: no document metadata changed")
        log(f"[DRY-RUN] ID {doc_id}: no persistent review record written")
        mark_success(doc_id, queue_tag, error_tag)
    else:
        apply_metadata_and_finish(
            doc_id,
            result,
            tax,
            queue_tag,
            error_tag,
        )
        log(f"[APPLY] ID {doc_id}: metadata saved to Paperless")
        write_review_record_safe(
            doc_id,
            correspondent_candidate,
            correspondent_fallback,
        )


def main():
    app_cfg = ensure_app_config()
    config = ensure_config()
    log("[BOOT] Paperless LLM Metadata Worker")
    log(f"[BOOT] AppConfig: /config/app-config.json (v{app_cfg['version']})")
    log(f"[BOOT] PromptConfig: /config/prompt-config.json (v{config['version']})")
    log(f"[BOOT] Model: {config['model']}")
    log(f"[BOOT] Context: {config['num_ctx']}")
    log("[BOOT] Prompt and app settings are reloaded continuously")
    try:
        corr_cfg = load_correspondent_config()
        log(
            "[BOOT] Correspondent fallback: "
            + ("ENABLED" if corr_cfg["enabled"] else "disabled")
            + f" (Config v{corr_cfg['version']})"
        )
    except Exception as exc:
        log(f"[BOOT-WARN] Correspondent config is not readable: {type(exc).__name__}: {exc}")

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
                        process(doc, tax, app_cfg)
                except Exception as e:
                    mark_error(doc["id"], queue_tag, error_tag, e, error_name)
        except Exception as e:
            log(f"[ERROR] Worker/Polling: {type(e).__name__}: {e}")

        time.sleep(poll_interval)


if __name__ == "__main__":
    main()
