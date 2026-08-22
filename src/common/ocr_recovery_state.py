from __future__ import annotations

import fcntl
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


COORDINATION_DIR = Path(os.getenv("PLAI_COORDINATION_DIR", "/coordination"))
STATE_FILE = COORDINATION_DIR / "ocr-recovery-state.json"
FAILURES_FILE = COORDINATION_DIR / "ocr-recovery-failures.json"
RETRY_NOW_FILE = COORDINATION_DIR / "ocr-retry-now.json"
LOCK_FILE = COORDINATION_DIR / "ocr-recovery.lock"
MAX_FAILURES = 25


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iso_after_seconds(seconds: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).isoformat()


def _default_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "request_id": None,
        "source": None,
        "page_number": None,
        "attempt": None,
        "max_attempts": None,
        "retry_delays_seconds": None,
        "last_error": None,
        "retry_after_seconds": None,
        "next_retry_at": None,
        "failure_id": None,
        "updated_at": utc_now_iso(),
    }


@contextmanager
def _lock():
    COORDINATION_DIR.mkdir(parents=True, exist_ok=True)
    with LOCK_FILE.open("a+") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json_unlocked(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


def _atomic_write_unlocked(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(tmp, path)


def read_recovery_state() -> dict[str, Any]:
    with _lock():
        raw = _read_json_unlocked(STATE_FILE, {})
    state = _default_state()
    if isinstance(raw, dict):
        state.update(raw)
    return state


def write_recovery_state(values: dict[str, Any]) -> dict[str, Any]:
    state = _default_state()
    state.update(values)
    state["updated_at"] = utc_now_iso()
    with _lock():
        _atomic_write_unlocked(STATE_FILE, state)
    return state


def set_idle_state() -> dict[str, Any]:
    with _lock():
        RETRY_NOW_FILE.unlink(missing_ok=True)
        state = _default_state()
        _atomic_write_unlocked(STATE_FILE, state)
    return state


def list_failures() -> list[dict[str, Any]]:
    with _lock():
        raw = _read_json_unlocked(FAILURES_FILE, [])
    return raw if isinstance(raw, list) else []


def record_failure(
    *,
    request_id: str,
    source: str,
    page_number: int | None,
    attempts: int,
    max_attempts: int,
    error: str,
    retryable: bool,
    retry_delays_seconds: list[int],
) -> dict[str, Any]:
    record = {
        "id": uuid.uuid4().hex,
        "failed_at": utc_now_iso(),
        "request_id": request_id,
        "source": source,
        "page_number": page_number,
        "attempts": attempts,
        "max_attempts": max_attempts,
        "error": error,
        "retryable": retryable,
        "retry_delays_seconds": list(retry_delays_seconds),
    }
    with _lock():
        items = _read_json_unlocked(FAILURES_FILE, [])
        if not isinstance(items, list):
            items = []
        items.insert(0, record)
        _atomic_write_unlocked(FAILURES_FILE, items[:MAX_FAILURES])
    return record


def dismiss_failure(failure_id: str) -> bool:
    failure_id = str(failure_id or "").strip()
    if not failure_id:
        return False
    removed = False
    with _lock():
        items = _read_json_unlocked(FAILURES_FILE, [])
        if not isinstance(items, list):
            items = []
        kept = []
        for item in items:
            if isinstance(item, dict) and item.get("id") == failure_id:
                removed = True
                continue
            kept.append(item)
        if removed:
            _atomic_write_unlocked(FAILURES_FILE, kept)
            state = _read_json_unlocked(STATE_FILE, {})
            if isinstance(state, dict) and state.get("failure_id") == failure_id:
                idle = _default_state()
                _atomic_write_unlocked(STATE_FILE, idle)
    return removed


def request_retry_now(request_id: str) -> dict[str, Any]:
    request_id = str(request_id or "").strip()
    if not request_id:
        raise ValueError("request_id is required")
    with _lock():
        state = _read_json_unlocked(STATE_FILE, {})
        if not isinstance(state, dict) or state.get("status") != "waiting":
            raise ValueError("No OCR retry is currently waiting")
        if state.get("request_id") != request_id:
            raise ValueError("The waiting OCR request changed; refresh and try again")
        trigger = {"request_id": request_id, "requested_at": utc_now_iso()}
        _atomic_write_unlocked(RETRY_NOW_FILE, trigger)
        return trigger


def retry_now_requested(request_id: str) -> bool:
    with _lock():
        trigger = _read_json_unlocked(RETRY_NOW_FILE, {})
    return isinstance(trigger, dict) and trigger.get("request_id") == request_id


def consume_retry_now(request_id: str) -> bool:
    with _lock():
        trigger = _read_json_unlocked(RETRY_NOW_FILE, {})
        if isinstance(trigger, dict) and trigger.get("request_id") == request_id:
            RETRY_NOW_FILE.unlink(missing_ok=True)
            return True
    return False


def recovery_control_state() -> dict[str, Any]:
    """Minimal non-sensitive recovery state suitable for the public health endpoint."""
    state = read_recovery_state()
    request_id = state.get("request_id")
    return {
        "status": state.get("status", "idle"),
        "request_id": request_id,
        "retry_now_requested": bool(
            request_id and retry_now_requested(str(request_id))
        ),
    }


def recovery_state_for_ui() -> dict[str, Any]:
    state = read_recovery_state()
    state["retry_now_requested"] = bool(
        state.get("request_id") and retry_now_requested(str(state["request_id"]))
    )
    return {"state": state, "failures": list_failures()}
