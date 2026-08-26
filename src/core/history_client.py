from __future__ import annotations

from typing import Any

from history_common import history_broker_request


def llm_only_context() -> dict[str, Any]:
    return {
        "mode": "llm_only",
        "route": "llm_only",
        "llm_decides": True,
        "examples": [],
    }


def history_error_context(error: str) -> dict[str, Any]:
    return {
        "mode": "history_assisted",
        "route": "llm_fallback",
        "llm_decides": True,
        "reason": "history_error",
        "history_error": error,
        "examples": [],
    }


def release_history_engine() -> None:
    try:
        history_broker_request({"op": "release"})
    except Exception:
        # Releasing a warm helper is a best-effort memory optimization. If the
        # broker is unavailable there is no safe helper process to retain.
        pass


def history_contexts_for_documents(
    config: dict[str, Any],
    documents: list[dict[str, Any]],
    *,
    shutdown_after: bool,
) -> dict[int, dict[str, Any]]:
    if config.get("tagging_mode", "history_assisted") == "llm_only":
        if shutdown_after:
            release_history_engine()
        return {int(doc["id"]): llm_only_context() for doc in documents}
    if not documents:
        return {}

    payload = {
        "op": "route_batch",
        "documents": [
            {
                "id": int(document["id"]),
                "content": str(document.get("content") or ""),
            }
            for document in documents
        ],
        "max_tags": int(config.get("max_tags", 2)),
        "shutdown_after": shutdown_after,
    }
    try:
        result = history_broker_request(payload)
        routes = result.get("routes")
        if not isinstance(routes, list):
            raise RuntimeError("History broker returned no routes")
        by_id: dict[int, dict[str, Any]] = {}
        for item in routes:
            if not isinstance(item, dict) or not isinstance(item.get("tagging"), dict):
                raise RuntimeError("History broker returned an invalid route")
            by_id[int(item["id"])] = item["tagging"]
        missing = [int(doc["id"]) for doc in documents if int(doc["id"]) not in by_id]
        if missing:
            raise RuntimeError("History broker omitted route(s): " + ", ".join(map(str, missing)))
        return by_id
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        return {int(doc["id"]): history_error_context(error) for doc in documents}


def history_context_for_document(
    config: dict[str, Any],
    document: dict[str, Any],
    *,
    shutdown_after: bool = False,
) -> dict[str, Any]:
    return history_contexts_for_documents(
        config,
        [document],
        shutdown_after=shutdown_after,
    )[int(document["id"])]


def refresh_history(
    *, max_tags: int = 2, shutdown_after: bool = False
) -> dict[str, Any]:
    result = history_broker_request(
        {
            "op": "refresh",
            "max_tags": int(max_tags),
            "shutdown_after": shutdown_after,
        }
    )
    history = result.get("history")
    if not isinstance(history, dict):
        raise RuntimeError("History broker returned no history status")
    return history
