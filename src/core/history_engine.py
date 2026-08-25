from __future__ import annotations

import fcntl
import hashlib
import json
import os
import pickle
import sys
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sklearn.exceptions import InconsistentVersionWarning

from app_config import load_config as load_app_config
from memory_reclaim import page_out_self_file_mappings
from history_common import (
    HISTORY_CACHE_DIR,
    HISTORY_CACHE_FILE,
    HISTORY_CACHE_LOCK_FILE,
    HISTORY_META_FILE,
    HISTORY_APP_VERSION,
    HISTORY_CACHE_FORMAT_VERSION,
    history_algorithm_signature,
    history_excluded_tag_names,
    history_library_versions,
    history_source_state,
)
from history_runtime import HistoryIndex
from prompt_runtime import PaperlessClient


_ACTIVE_INDEX: HistoryIndex | None = None
_ACTIVE_STATUS: dict[str, Any] | None = None
_ACTIVE_SOURCE: dict[str, Any] | None = None
_ACTIVE_PAPERLESS_URL: str | None = None


def log(message: str) -> None:
    print(f"[HISTORY-ENGINE] {message}", file=sys.stderr, flush=True)


def _library_versions() -> dict[str, str]:
    return history_library_versions()


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.chmod(0o700)
    except OSError:
        pass
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            tmp.chmod(0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write_bytes(path, encoded)


@contextmanager
def _cache_lock():
    HISTORY_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        HISTORY_CACHE_DIR.chmod(0o700)
    except OSError:
        pass
    with HISTORY_CACHE_LOCK_FILE.open("a+") as lock_file:
        try:
            HISTORY_CACHE_LOCK_FILE.chmod(0o600)
        except OSError:
            pass
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _expected_metadata(
    source: dict[str, Any],
    paperless_url: str,
) -> dict[str, Any]:
    return {
        "format_version": HISTORY_CACHE_FORMAT_VERSION,
        "app_version": HISTORY_APP_VERSION,
        "algorithm": history_algorithm_signature(),
        "paperless_url": paperless_url,
        "source": source,
        "libraries": _library_versions(),
    }


def _cache_matches(
    metadata: dict[str, Any] | None,
    source: dict[str, Any],
    paperless_url: str,
) -> bool:
    if not metadata:
        return False
    expected = _expected_metadata(source, paperless_url)
    return all(metadata.get(key) == value for key, value in expected.items()) and isinstance(
        metadata.get("cache_sha256"), str
    )


def _load_cached_index(
    source: dict[str, Any],
    paperless_url: str,
) -> tuple[HistoryIndex, dict[str, Any]] | None:
    metadata = _read_json(HISTORY_META_FILE)
    if not _cache_matches(metadata, source, paperless_url):
        return None
    status = metadata.get("status")
    if not isinstance(status, dict) or not HISTORY_CACHE_FILE.exists():
        return None

    try:
        data = HISTORY_CACHE_FILE.read_bytes()
    except OSError:
        return None
    if hashlib.sha256(data).hexdigest() != metadata.get("cache_sha256"):
        return None

    # This cache is internal application state under /data/history-cache and is
    # never accepted from uploads or network input. Pickle is only safe here
    # because the application exclusively creates and owns the artifact.
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", InconsistentVersionWarning)
            payload = pickle.loads(data)
    except Exception:
        return None

    index = HistoryIndex()
    index.load_cache_payload(payload, status=status, source_signature=source)
    return index, status


def _build_and_store_index(
    client: PaperlessClient,
    tax: dict[str, Any],
    excluded_tag_names: list[str],
    source: dict[str, Any],
    paperless_url: str,
) -> tuple[HistoryIndex, dict[str, Any]]:
    index = HistoryIndex()
    status = index.refresh(client, tax, excluded_tag_names, force=True)
    if status.get("status") == "Error":
        raise RuntimeError(status.get("last_error") or "History rebuild failed")

    payload = index.cache_payload()
    data = pickle.dumps(payload, protocol=5)
    persisted_status = dict(status)
    persisted_status["stale"] = False
    persisted_status["cache_state"] = "ready"
    metadata = {
        **_expected_metadata(source, paperless_url),
        "cache_sha256": hashlib.sha256(data).hexdigest(),
        "status": persisted_status,
    }

    # Metadata is the commit marker. If the process dies before the final
    # replace, the previous metadata will not validate against the new cache.
    _atomic_write_bytes(HISTORY_CACHE_FILE, data)
    _atomic_write_json(HISTORY_META_FILE, metadata)
    return index, persisted_status


def ensure_index(*, force: bool = False) -> tuple[HistoryIndex, dict[str, Any]]:
    global _ACTIVE_INDEX, _ACTIVE_STATUS, _ACTIVE_SOURCE, _ACTIVE_PAPERLESS_URL

    client = PaperlessClient()
    app_cfg = load_app_config()
    paperless_url = app_cfg["connections"]["paperless_url"]
    excluded = history_excluded_tag_names(app_cfg)
    tax = client.taxonomy()
    source = history_source_state(client, tax, excluded)

    if (
        not force
        and _ACTIVE_INDEX is not None
        and _ACTIVE_STATUS is not None
        and _ACTIVE_SOURCE == source
        and _ACTIVE_PAPERLESS_URL == paperless_url
    ):
        return _ACTIVE_INDEX, _ACTIVE_STATUS

    if not force:
        cached = _load_cached_index(source, paperless_url)
        if cached is not None:
            _ACTIVE_INDEX, _ACTIVE_STATUS = cached
            _ACTIVE_SOURCE = source
            _ACTIVE_PAPERLESS_URL = paperless_url
            return cached

    with _cache_lock():
        # Re-read source state after waiting for the cache lock so a concurrent
        # Paperless change cannot make an older signature look current here.
        tax = client.taxonomy()
        source = history_source_state(client, tax, excluded)
        if not force:
            cached = _load_cached_index(source, paperless_url)
            if cached is not None:
                _ACTIVE_INDEX, _ACTIVE_STATUS = cached
                _ACTIVE_SOURCE = source
                _ACTIVE_PAPERLESS_URL = paperless_url
                return cached
        log(f"rebuilding history cache for {source['reviewed_documents']} reviewed document(s)")
        built = _build_and_store_index(client, tax, excluded, source, paperless_url)
        _ACTIVE_INDEX, _ACTIVE_STATUS = built
        _ACTIVE_SOURCE = source
        _ACTIVE_PAPERLESS_URL = paperless_url
        return built


def _history_context(route: dict[str, Any]) -> dict[str, Any]:
    result = dict(route)
    result["mode"] = "history_assisted"
    result["llm_decides"] = result.get("route") != "history_match"
    return result


def _handle(request: dict[str, Any]) -> dict[str, Any]:
    op = request.get("op")
    if op == "ping":
        return {"pid": os.getpid()}
    if op == "refresh":
        _index, status = ensure_index(force=True)
        return {"history": status}
    if op == "route_batch":
        documents = request.get("documents")
        if not isinstance(documents, list):
            raise ValueError("route_batch requires a documents list")
        index, status = ensure_index(force=False)
        routes = []
        for document in documents:
            if not isinstance(document, dict) or "id" not in document:
                raise ValueError("Each history document must contain an id")
            doc_id = int(document["id"])
            route = index.route(
                str(document.get("content") or ""),
                exclude_id=doc_id,
            )
            routes.append({"id": doc_id, "tagging": _history_context(route)})
        return {"routes": routes, "history": status}
    if op == "shutdown":
        return {"shutdown": True}
    raise ValueError(f"Unsupported history engine operation: {op!r}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        shutdown = False
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("History engine request must be a JSON object")
            result = _handle(request)
            shutdown = request.get("op") == "shutdown"
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        if shutdown:
            return


def _reclaim_before_process_exit() -> None:
    try:
        stats = page_out_self_file_mappings()
        message = (
            "[HISTORY-ENGINE] final file-mapping reclaim: "
            f"accepted={stats['accepted_bytes'] / 1048576:.1f} MiB "
            f"attempted={stats['attempted_bytes'] / 1048576:.1f} MiB "
            f"failed_mappings={stats['failed_mappings']}\\n"
        )
        try:
            os.write(2, message.encode("utf-8", errors="replace"))
        except OSError:
            pass
    except BaseException as exc:
        try:
            os.write(
                2,
                (
                    "[HISTORY-ENGINE] final file-mapping reclaim skipped: "
                    f"{type(exc).__name__}: {exc}\\n"
                ).encode("utf-8", errors="replace"),
            )
        except OSError:
            pass


if __name__ == "__main__":
    main()
    _reclaim_before_process_exit()
    os._exit(0)
