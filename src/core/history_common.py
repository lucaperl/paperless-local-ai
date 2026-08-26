from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import socket
from pathlib import Path
from typing import Any

from app_config import (
    HISTORY_MATCH_SIMILARITY_DEFAULT,
    HISTORY_MIN_SUPPORT_DEFAULT,
    HISTORY_MIN_WINNER_SHARE_DEFAULT,
)


HISTORY_CACHE_DIR = Path(os.getenv("PLAI_HISTORY_CACHE_DIR", "/data/history-cache"))
HISTORY_CACHE_FILE = HISTORY_CACHE_DIR / "index.pkl"
HISTORY_META_FILE = HISTORY_CACHE_DIR / "index-meta.json"
HISTORY_CACHE_LOCK_FILE = HISTORY_CACHE_DIR / "cache.lock"
HISTORY_BROKER_SOCKET = Path(
    os.getenv("PLAI_HISTORY_BROKER_SOCKET", "/coordination/history-broker.sock")
)
HISTORY_BROKER_TIMEOUT_SECONDS = float(
    os.getenv("PLAI_HISTORY_BROKER_TIMEOUT_SECONDS", "2800")
)
HISTORY_PROTOCOL_MAX_BYTES = int(
    os.getenv("PLAI_HISTORY_PROTOCOL_MAX_BYTES", str(32 * 1024 * 1024))
)
HISTORY_CACHE_FORMAT_VERSION = 1
HISTORY_ALGORITHM_VERSION = "tfidf-word12-char35-nearest-neighbors-cosine-labelset-v2"
HISTORY_APP_VERSION = os.getenv("APP_VERSION", "dev").strip() or "dev"

FAST_SIMILARITY = HISTORY_MATCH_SIMILARITY_DEFAULT
FAMILY_SIMILARITY = 0.50
EXAMPLE_MIN_SIMILARITY = 0.08
TOP_VOTE_NEIGHBORS = 5
QUERY_NEIGHBORS = 30
MIN_SUPPORT = HISTORY_MIN_SUPPORT_DEFAULT
MIN_WINNER_SHARE = HISTORY_MIN_WINNER_SHARE_DEFAULT
MAX_EXAMPLES = 5
MAX_EXAMPLES_PER_TAG_SET = 2
MAX_DIAGNOSTIC_DOCS = 2000

def history_matching_settings(
    app_cfg: dict[str, Any] | None = None,
    max_tags: int = 2,
) -> dict[str, Any]:
    history = app_cfg.get("history", {}) if isinstance(app_cfg, dict) else {}
    return {
        "match_similarity": float(history.get("match_similarity", FAST_SIMILARITY)),
        "min_support": int(history.get("min_support", MIN_SUPPORT)),
        "min_winner_share": float(history.get("min_winner_share", MIN_WINNER_SHARE)),
        "max_tags": int(max_tags),
    }


def history_algorithm_signature(
    matching: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Cache-relevant algorithm parameters that must invalidate derived status/index state."""
    matching = matching or history_matching_settings()
    return {
        "version": HISTORY_ALGORITHM_VERSION,
        "decision_unit": "complete_leaf_tag_set",
        "word_ngram_range": [1, 2],
        "char_analyzer": "char_wb",
        "char_ngram_range": [3, 5],
        "dtype": "float32",
        "norm": "l2",
        "retrieval_estimator": "NearestNeighbors",
        "retrieval_metric": "cosine",
        "retrieval_algorithm": "brute",
        "match_similarity": matching["match_similarity"],
        "family_similarity": FAMILY_SIMILARITY,
        "example_min_similarity": EXAMPLE_MIN_SIMILARITY,
        "top_vote_neighbors": TOP_VOTE_NEIGHBORS,
        "query_neighbors": QUERY_NEIGHBORS,
        "min_support": matching["min_support"],
        "min_winner_share": matching["min_winner_share"],
        "max_tags": matching["max_tags"],
        "max_examples": MAX_EXAMPLES,
        "max_examples_per_tag_set": MAX_EXAMPLES_PER_TAG_SET,
        "max_diagnostic_docs": MAX_DIAGNOSTIC_DOCS,
    }


def history_library_versions() -> dict[str, str]:
    """Return exact runtime versions without importing the scientific stack."""
    return {
        "python": platform.python_version(),
        "numpy": importlib.metadata.version("numpy"),
        "scipy": importlib.metadata.version("scipy"),
        "scikit_learn": importlib.metadata.version("scikit-learn"),
    }


def _leaf_names_from_ids(
    tag_ids: list[int] | tuple[int, ...],
    tax: dict[str, Any],
) -> list[str]:
    content_ids = set(tax.get("content_tag_ids", []))
    parent_by_id = tax.get("parent_by_id", {})
    name_by_id = tax.get("tag_by_id", {})
    selected = {int(tag_id) for tag_id in tag_ids if int(tag_id) in content_ids}
    parents_to_remove: set[int] = set()

    for tag_id in selected:
        parent = parent_by_id.get(tag_id)
        while parent:
            if parent in selected:
                parents_to_remove.add(parent)
            parent = parent_by_id.get(parent)

    return sorted(
        name_by_id[tag_id]
        for tag_id in selected - parents_to_remove
        if tag_id in name_by_id
    )


def _taxonomy_signature(tax: dict[str, Any]) -> list[list[Any]]:
    return [
        [
            int(item["id"]),
            str(item["name"]),
            int(item["parent"]) if item.get("parent") else None,
        ]
        for item in sorted(
            tax.get("tags", []),
            key=lambda item: (int(item["id"]), str(item["name"])),
        )
    ]


def _excluded_tag_ids(
    tax: dict[str, Any],
    excluded_tag_names: str | list[str] | tuple[str, ...],
) -> list[int]:
    if isinstance(excluded_tag_names, str):
        excluded_tag_names = [excluded_tag_names]
    ids = []
    missing = []
    for name in excluded_tag_names:
        tag_id = tax.get("tag_by_name", {}).get(name)
        if tag_id is None:
            missing.append(name)
        else:
            ids.append(int(tag_id))
    if missing:
        raise RuntimeError(
            "History exclusion tag(s) not found in Paperless: "
            + ", ".join(repr(x) for x in missing)
        )
    return sorted(set(ids))


def history_excluded_tag_names(app_cfg: dict[str, Any]) -> list[str]:
    workflow = app_cfg["workflow"]
    return [
        workflow["review_tag"],
        workflow["llm_queue_tag"],
        workflow["llm_error_tag"],
    ]


def history_source_state(
    client,
    tax: dict[str, Any],
    excluded_tag_names: str | list[str] | tuple[str, ...],
) -> dict[str, Any]:
    excluded_tag_ids = _excluded_tag_ids(tax, excluded_tag_names)
    data = client.request(
        "GET",
        "/api/documents/",
        params={
            "tags__id__none": ",".join(str(x) for x in excluded_tag_ids),
            "ordering": "-modified",
            "page_size": 1,
            "fields": "id,modified",
        },
    ).json()
    results = data.get("results", []) if isinstance(data, dict) else []
    modified = results[0].get("modified") if results else None
    return {
        "reviewed_documents": int(data.get("count", len(results))),
        "latest_modified": modified,
        "taxonomy": _taxonomy_signature(tax),
        "excluded_tag_ids": excluded_tag_ids,
    }


def fetch_reviewed_documents(
    client,
    tax: dict[str, Any],
    excluded_tag_names: str | list[str] | tuple[str, ...],
) -> list[dict[str, Any]]:
    excluded_tag_ids = _excluded_tag_ids(tax, excluded_tag_names)
    entries: list[dict[str, Any]] = []
    page = 1
    while True:
        data = client.request(
            "GET",
            "/api/documents/",
            params={
                "tags__id__none": ",".join(str(x) for x in excluded_tag_ids),
                "ordering": "id",
                "page_size": 100,
                "page": page,
                "fields": "id,title,content,tags,modified",
            },
        ).json()
        for doc in data.get("results", []):
            content = (doc.get("content") or "").strip()
            if not content:
                continue
            entries.append(
                {
                    "id": int(doc["id"]),
                    "title": doc.get("title") or f"Document {doc['id']}",
                    "content": content,
                    "tags": _leaf_names_from_ids(doc.get("tags", []), tax),
                    "modified": doc.get("modified"),
                }
            )
        if not data.get("next"):
            break
        page += 1
    return entries


def empty_history_status(
    matching: dict[str, Any] | None = None,
) -> dict[str, Any]:
    matching = matching or history_matching_settings()
    return {
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
        "last_updated": None,
        "last_error": None,
        "thresholds": {
            "history_match_similarity": matching["match_similarity"],
            "support": matching["min_support"],
            "winner_share": matching["min_winner_share"],
            "max_tags": matching["max_tags"],
            "inconsistency_similarity": FAMILY_SIMILARITY,
        },
    }


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def cached_history_state(
    client,
    tax: dict[str, Any],
    excluded_tag_names: str | list[str] | tuple[str, ...],
    *,
    paperless_url: str,
    matching: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return lightweight cache/source health without reading or unpickling the cache blob."""
    metadata = _read_json(HISTORY_META_FILE)
    source = history_source_state(client, tax, excluded_tag_names)

    matching = matching or history_matching_settings()
    status = empty_history_status(matching)
    cache_state = "missing"
    stale = True
    if metadata and HISTORY_CACHE_FILE.exists():
        cached_status = metadata.get("status")
        if isinstance(cached_status, dict):
            status = dict(cached_status)
        expected = {
            "format_version": HISTORY_CACHE_FORMAT_VERSION,
            "app_version": HISTORY_APP_VERSION,
            "algorithm": history_algorithm_signature(matching),
            "paperless_url": paperless_url,
            "source": source,
            "libraries": history_library_versions(),
        }
        metadata_matches = all(metadata.get(key) == value for key, value in expected.items())
        digest = metadata.get("cache_sha256")
        if metadata_matches and isinstance(digest, str):
            # Integrity is verified inside the disposable scientific helper
            # immediately before unpickling. The persistent UI process avoids
            # reading the multi-MiB cache blob so that cache inspection itself
            # cannot inflate long-lived RSS.
            cache_state = "ready"
            stale = False
        else:
            cache_state = "stale"

    result = dict(status)
    result["stale"] = stale
    result["cache_state"] = cache_state
    result["source"] = {
        "reviewed_documents": source["reviewed_documents"],
        "latest_modified": source["latest_modified"],
    }
    return result


def _recv_json_line(sock: socket.socket, max_bytes: int) -> dict[str, Any]:
    chunks = bytearray()
    while True:
        chunk = sock.recv(min(65536, max_bytes - len(chunks) + 1))
        if not chunk:
            break
        chunks.extend(chunk)
        newline = chunks.find(b"\n")
        if newline >= 0:
            chunks = chunks[:newline]
            break
        if len(chunks) > max_bytes:
            raise RuntimeError("History broker response exceeded the protocol limit")
    if not chunks:
        raise RuntimeError("History broker closed the connection without a response")
    try:
        payload = json.loads(chunks.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"History broker returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("History broker returned a non-object response")
    return payload


def history_broker_request(
    payload: dict[str, Any],
    *,
    timeout: float | None = None,
    socket_path: Path | None = None,
) -> dict[str, Any]:
    path = socket_path or HISTORY_BROKER_SOCKET
    timeout = HISTORY_BROKER_TIMEOUT_SECONDS if timeout is None else timeout
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > HISTORY_PROTOCOL_MAX_BYTES:
        raise RuntimeError("History broker request exceeded the protocol limit")

    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(timeout)
        try:
            sock.connect(str(path))
        except OSError as exc:
            raise RuntimeError(f"History broker is unavailable: {exc}") from exc
        sock.sendall(encoded)
        response = _recv_json_line(sock, HISTORY_PROTOCOL_MAX_BYTES)

    if not response.get("ok"):
        raise RuntimeError(str(response.get("error") or "History broker request failed"))
    result = response.get("result")
    if not isinstance(result, dict):
        raise RuntimeError("History broker returned an invalid result")
    return result
