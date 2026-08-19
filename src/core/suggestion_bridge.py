#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app_config import load_config as load_app_config
from review_store import (
    REVIEW_DIR,
    prompt_content_signature,
    load_review_records,
    match_review_record,
    records_for_content,
)

HOST = os.getenv("SUGGESTION_BRIDGE_HOST", "0.0.0.0")
PORT = int(os.getenv("SUGGESTION_BRIDGE_PORT", "8081"))
MODEL_NAME = "paperless-correspondent-bridge"
PAPERLESS_TOKEN = os.getenv("PAPERLESS_TOKEN", "")
MAX_BODY_BYTES = 2 * 1024 * 1024
TAXONOMY_CACHE_SECONDS = 60

CLASSIFICATION_MARKER = "You are a document classification assistant."
FILENAME_MARKER = "Filename:"
CONTENT_MARKER = "Content (untrusted user data"
LOCALIZATION_MARKER = "You are localizing document classification suggestions for display in Paperless-ngx."
_taxonomy_cache = None


def log(message: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}", flush=True)


def empty_classification():
    return {"title": "", "tags": [], "correspondents": [], "document_types": [], "storage_paths": [], "dates": []}


def extract_user_prompt(payload):
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if isinstance(item, dict) and item.get("role") == "user" and isinstance(item.get("content"), str):
            return item["content"]
    return ""


def extract_document_identity(prompt: str):
    if CLASSIFICATION_MARKER not in prompt:
        return None
    filename_pos = prompt.find(FILENAME_MARKER)
    content_pos = prompt.find(CONTENT_MARKER)
    if filename_pos < 0 or content_pos < 0 or content_pos <= filename_pos:
        return None
    filename = prompt[filename_pos + len(FILENAME_MARKER):content_pos].strip()
    content_colon = prompt.find(":", content_pos)
    if content_colon < 0:
        return None
    return filename, prompt[content_colon + 1:].strip()



def resolve_ambiguous_content_match(content: str):
    """
    Resolve a legacy v2/v3 96-word content collision against live Paperless
    content using the stronger signature of the exact no-RAG prompt input.

    Paperless 3.0.5 does not expose its internal Document.filename through the
    normal document serializer, so filename-based disambiguation would compare
    different concepts. This path is exact-only and fail-closed.
    """
    records = records_for_content(
        content,
        load_review_records(),
    )

    if len(records) <= 1:
        return (
            records[0] if records else None,
            "content_signature" if records else "no review record",
        )

    target_signature = prompt_content_signature(
        content
    )

    live_matches = []

    for record in records:
        document_id = int(
            record["document_id"]
        )

        try:
            document = paperless_json(
                f"/api/documents/{document_id}/"
            )
        except Exception as exc:
            log(
                f"[WARN] Content resolution ID {document_id}: "
                f"{type(exc).__name__}: {exc}"
            )
            continue

        if prompt_content_signature(
            document.get("content")
        ) == target_signature:
            live_matches.append(
                record
            )

    if len(live_matches) == 1:
        return (
            live_matches[0],
            "content_signature + live prompt_content_signature",
        )

    if len(live_matches) > 1:
        return (
            None,
            "content+prompt ambiguous "
            f"({len(live_matches)})",
        )

    return (
        None,
        f"content_signature ambiguous ({len(records)}); "
        "no unique exact prompt-content match",
    )

def paperless_json(path: str, params=None):
    if not PAPERLESS_TOKEN:
        raise RuntimeError("PAPERLESS_TOKEN is missing from suggestion-bridge")
    paperless_url = load_app_config()["connections"]["paperless_url"]
    url = f"{paperless_url}{path}"
    if params:
        url += "?" + urlencode(params, doseq=True)
    req = Request(url, headers={"Authorization": f"Token {PAPERLESS_TOKEN}", "Accept": "application/json"}, method="GET")
    try:
        with urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Paperless API {path} -> HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"Paperless API {path} is not reachable: {exc}") from exc


def _all_objects(path):
    data = paperless_json(path, {"page_size": 1000})
    if isinstance(data, dict) and isinstance(data.get("results"), list):
        return data["results"]
    if isinstance(data, list):
        return data
    raise RuntimeError(f"Unexpected Paperless list response for {path}")


def taxonomy_maps(force=False):
    global _taxonomy_cache
    now = time.monotonic()
    if not force and _taxonomy_cache is not None and now - _taxonomy_cache[0] < TAXONOMY_CACHE_SECONDS:
        return _taxonomy_cache[1]
    paths = {
        "correspondents": "/api/correspondents/",
        "tags": "/api/tags/",
        "document_types": "/api/document_types/",
        "storage_paths": "/api/storage_paths/",
    }
    maps = {}
    for key, path in paths.items():
        maps[key] = {int(x["id"]): str(x["name"]) for x in _all_objects(path) if x.get("id") is not None and x.get("name") is not None}
    _taxonomy_cache = (now, maps)
    return maps


def names_for_ids(kind, ids):
    mapping = taxonomy_maps()[kind]
    missing = []
    names = []
    for raw in ids:
        try:
            item_id = int(raw)
        except (TypeError, ValueError):
            continue
        if item_id in mapping:
            names.append(mapping[item_id])
        else:
            missing.append(item_id)
    if missing:
        mapping = taxonomy_maps(force=True)[kind]
        names = []
        for raw in ids:
            try:
                item_id = int(raw)
            except (TypeError, ValueError):
                continue
            if item_id in mapping:
                names.append(mapping[item_id])
    return names


def classic_classification(document_id: int):
    document = paperless_json(f"/api/documents/{document_id}/")
    suggestions = paperless_json(f"/api/documents/{document_id}/suggestions/")
    return {
        "title": "",
        "correspondents": names_for_ids("correspondents", list(suggestions.get("correspondents", []))),
        "tags": names_for_ids("tags", list(suggestions.get("tags", []))),
        "document_types": names_for_ids("document_types", list(suggestions.get("document_types", []))),
        "storage_paths": names_for_ids("storage_paths", list(suggestions.get("storage_paths", []))),
        "dates": list(suggestions.get("dates", [])),
    }, document


def classification_for_prompt(prompt: str):
    if LOCALIZATION_MARKER in prompt:
        return empty_classification(), {"kind": "localization", "matched_document_id": None, "match": "not required"}
    identity = extract_document_identity(prompt)
    if identity is None:
        return empty_classification(), {"kind": "unsupported", "matched_document_id": None, "match": "not a Paperless classification prompt"}
    filename, content = identity
    record, reason = match_review_record(filename, content)
    if record is None and reason.startswith("content_signature ambiguous"):
        record, reason = resolve_ambiguous_content_match(
            content,
        )
    if record is None:
        return empty_classification(), {"kind": "classification", "matched_document_id": None, "match": reason}
    document_id = int(record["document_id"])
    result, document = classic_classification(document_id)
    candidate = record.get("correspondent_suggestion")
    candidate = " ".join(candidate.split()).strip() if isinstance(candidate, str) else ""
    if candidate and document.get("correspondent") is None:
        existing = {name.casefold() for name in result["correspondents"]}
        if candidate.casefold() not in existing:
            result["correspondents"].append(candidate)
    return result, {"kind": "classification", "matched_document_id": document_id, "match": reason, "candidate": candidate or None}


def ollama_chat_response(content: str, model: str):
    return {
        "model": model,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "message": {"role": "assistant", "content": content},
        "done": True, "done_reason": "stop", "total_duration": 1, "load_duration": 0,
        "prompt_eval_count": 0, "prompt_eval_duration": 0, "eval_count": 0, "eval_duration": 0,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "paperless-suggestion-bridge/2.0"
    def log_message(self, fmt, *args):
        log(f"[HTTP] {self.address_string()} {fmt % args}")
    def _json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)
    def _read_json(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise ValueError("Invalid Content-Length header") from exc
        if length < 0 or length > MAX_BODY_BYTES:
            raise ValueError("Request body is too large")
        body = self.rfile.read(length)
        if not body:
            return {}
        payload = json.loads(body.decode("utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("JSON body must be an object")
        return payload
    def do_GET(self):
        if self.path == "/health":
            count = len(list(REVIEW_DIR.glob("*.json"))) if REVIEW_DIR.exists() else 0
            paperless_ok = False
            if PAPERLESS_TOKEN:
                try:
                    paperless_json("/api/documents/", {"page_size": 1}); paperless_ok = True
                except Exception:
                    pass
            self._json(HTTPStatus.OK, {"ok": True, "service": "paperless-suggestion-bridge", "version": 2, "model": MODEL_NAME, "review_records": count, "paperless_api": paperless_ok}); return
        if self.path == "/api/version":
            self._json(HTTPStatus.OK, {"version": "paperless-suggestion-bridge-2"}); return
        if self.path == "/api/tags":
            self._json(HTTPStatus.OK, {"models": [{"name": MODEL_NAME, "model": MODEL_NAME, "modified_at": "2026-08-18T00:00:00Z", "size": 0, "digest": "sha256:paperless-suggestion-bridge-v2", "details": {"parent_model": "", "format": "bridge", "family": "bridge", "families": ["bridge"], "parameter_size": "0", "quantization_level": "none"}}]}); return
        self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
    def do_POST(self):
        try:
            payload = self._read_json()
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)}); return
        if self.path == "/api/show":
            self._json(HTTPStatus.OK, {"modelfile": "", "parameters": "", "template": "", "details": {"parent_model": "", "format": "bridge", "family": "bridge", "families": ["bridge"], "parameter_size": "0", "quantization_level": "none"}, "model_info": {}, "capabilities": ["completion"]}); return
        if self.path != "/api/chat":
            self._json(HTTPStatus.NOT_FOUND, {"error": "not found"}); return
        if payload.get("stream") is True:
            self._json(HTTPStatus.BAD_REQUEST, {"error": "Bridge supports only stream=false"}); return
        try:
            result, meta = classification_for_prompt(extract_user_prompt(payload))
        except Exception as exc:
            log(f"[ERROR] Classification: {type(exc).__name__}: {exc}")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": f"suggestion bridge failed: {type(exc).__name__}"}); return
        model = str(payload.get("model") or MODEL_NAME)
        content = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        log(f"[CHAT] kind={meta['kind']} document_id={meta['matched_document_id']} match={meta['match']}")
        self._json(HTTPStatus.OK, ollama_chat_response(content, model))


def main():
    if not PAPERLESS_TOKEN:
        raise RuntimeError("PAPERLESS_TOKEN is missing; paperless.env must be loaded")
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    paperless_url = load_app_config()["connections"]["paperless_url"]
    log(f"[BOOT] Paperless Suggestion Bridge v2 at {HOST}:{PORT}, reviews={REVIEW_DIR}, paperless={paperless_url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
