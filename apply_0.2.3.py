#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE_VERSION = "0.2.2"
TARGET_VERSION = "0.2.3"
RELEASE_DATE = "2026-08-22"

EXPECTED_RUNTIME_SHA256 = {
    "src/common/app_config.py": "19efa5410135817dcaed29d1a9ffcc29fc7212a29c19e6d5b723368d51e1cb6f",
    "src/core/prompt_ui.py": "3802b568f160dc1f4905c080961c57f9d1ef66c0838b4f399910ce55a0371917",
    "src/ocr/ocrmypdf_plai.py": "d8209fa302430651934f9c335cdf027a40aa5e5da61b807bb805a2be2a5c47d0",
    "src/ocr/service.py": "2ef54a920af337108ca9370ceb87ecd70af635f8983c3570fff3d496313af33b",
}

CHANGED_FILES = [
    "VERSION",
    "CHANGELOG.md",
    "README.md",
    "SOURCE-MANIFEST.json",
    "OVERLAY-SHA256.txt",
    "src/common/app_config.py",
    "src/common/ocr_recovery_state.py",
    "src/core/prompt_ui.py",
    "src/ocr/ocrmypdf_plai.py",
    "src/ocr/service.py",
    "tests/test_app_config.py",
    "tests/test_ocr_plugin.py",
    "tests/test_ocr_service.py",
    "tests/test_ocr_recovery_state.py",
    "tests/test_public_contracts.py",
    "docs/configuration.md",
    "docs/troubleshooting.md",
    "docs/architecture.md",
]


def normalized_bytes(path: Path) -> bytes:
    data = path.read_bytes()
    if b"\x00" not in data:
        data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return data


def sha256(path: Path) -> str:
    return hashlib.sha256(normalized_bytes(path)).hexdigest()


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


def replace_regex_once(text: str, pattern: str, repl: str, label: str) -> str:
    out, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE | re.DOTALL)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one regex match, found {count}")
    return out


def read_text(path: Path) -> str:
    return normalized_bytes(path).decode("utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def verify_base(repo: Path) -> None:
    version = read_text(repo / "VERSION").strip()
    if version != BASE_VERSION:
        raise RuntimeError(f"Expected VERSION {BASE_VERSION}, found {version!r}")

    manifest = json.loads(read_text(repo / "SOURCE-MANIFEST.json"))
    if manifest.get("version") != BASE_VERSION:
        raise RuntimeError(
            f"SOURCE-MANIFEST version is {manifest.get('version')!r}, expected {BASE_VERSION!r}"
        )

    for rel, expected in EXPECTED_RUNTIME_SHA256.items():
        path = repo / rel
        actual = sha256(path)
        manifest_expected = manifest.get("source_files", {}).get(rel)
        if actual != expected or manifest_expected != expected:
            raise RuntimeError(
                f"Unexpected base file: {rel}\n"
                f"  expected: {expected}\n"
                f"  actual:   {actual}\n"
                f"  manifest: {manifest_expected}\n"
                "No files were changed. Update your checkout to the released 0.2.2 main branch first."
            )

    new_file = repo / "src/common/ocr_recovery_state.py"
    if new_file.exists():
        raise RuntimeError(f"Refusing to overwrite unexpected existing file: {new_file}")


def patch_app_config(repo: Path) -> None:
    path = repo / "src/common/app_config.py"
    text = read_text(path)

    text = replace_once(
        text,
        'OCR_MAX_SIDE_PIXELS_MAX = 4000\n',
        'OCR_MAX_SIDE_PIXELS_MAX = 4000\n'
        'OCR_RETRY_DELAYS_DEFAULT = (15, 60, 300, 600)\n'
        'OCR_RETRY_DELAYS_MAX_COUNT = 10\n'
        'OCR_RETRY_DELAY_MAX_SECONDS = 86400\n',
        f"{path}: retry constants",
    )

    text = replace_once(
        text,
        '        "max_side_pixels": OCR_MAX_SIDE_PIXELS_DEFAULT,\n        "device": "cpu",\n',
        '        "max_side_pixels": OCR_MAX_SIDE_PIXELS_DEFAULT,\n'
        '        "retry_delays_seconds": list(OCR_RETRY_DELAYS_DEFAULT),\n'
        '        "device": "cpu",\n',
        f"{path}: default retry schedule",
    )

    text = replace_once(
        text,
        'def validate_config(raw):\n',
        '''def _retry_delays(value):
    if not isinstance(value, list):
        raise ConfigError("ocr.retry_delays_seconds must be a list of integer seconds")
    if len(value) > OCR_RETRY_DELAYS_MAX_COUNT:
        raise ConfigError(
            f"ocr.retry_delays_seconds may contain at most {OCR_RETRY_DELAYS_MAX_COUNT} values"
        )
    return [
        _positive_int(
            delay,
            f"ocr.retry_delays_seconds[{index}]",
            1,
            OCR_RETRY_DELAY_MAX_SECONDS,
        )
        for index, delay in enumerate(value)
    ]


def validate_config(raw):
''',
        f"{path}: retry validator",
    )

    text = replace_once(
        text,
        '    ocr["max_side_pixels"] = _positive_int(\n'
        '        ocr["max_side_pixels"],\n'
        '        "ocr.max_side_pixels",\n'
        '        OCR_MAX_SIDE_PIXELS_MIN,\n'
        '        OCR_MAX_SIDE_PIXELS_MAX,\n'
        '    )\n\n'
        '    ocr["model_profile"] = ocr["model_profile"].lower()\n',
        '    ocr["max_side_pixels"] = _positive_int(\n'
        '        ocr["max_side_pixels"],\n'
        '        "ocr.max_side_pixels",\n'
        '        OCR_MAX_SIDE_PIXELS_MIN,\n'
        '        OCR_MAX_SIDE_PIXELS_MAX,\n'
        '    )\n'
        '    ocr["retry_delays_seconds"] = _retry_delays(ocr["retry_delays_seconds"])\n\n'
        '    ocr["model_profile"] = ocr["model_profile"].lower()\n',
        f"{path}: validate retry schedule",
    )

    write_text(path, text)


def add_recovery_state_module(repo: Path) -> None:
    path = repo / "src/common/ocr_recovery_state.py"
    write_text(
        path,
        '''from __future__ import annotations

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
        json.dumps(data, ensure_ascii=False, indent=2) + "\\n",
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
''',
    )


def patch_service(repo: Path) -> None:
    path = repo / "src/ocr/service.py"
    text = read_text(path)

    text = replace_once(
        text,
        'from typing import Any\n\nfrom app_config import OCR_MAX_SIDE_PIXELS_DEFAULT, load_config as load_app_config\n',
        'from typing import Any\nfrom urllib.parse import unquote\n\n'
        'from app_config import OCR_MAX_SIDE_PIXELS_DEFAULT, load_config as load_app_config\n'
        'from ocr_recovery_state import (\n'
        '    consume_retry_now,\n'
        '    iso_after_seconds,\n'
        '    record_failure,\n'
        '    read_recovery_state,\n'
        '    recovery_control_state,\n'
        '    set_idle_state,\n'
        '    utc_now_iso,\n'
        '    write_recovery_state,\n'
        ')\n',
        f"{path}: recovery imports",
    )

    text = replace_once(
        text,
        'PP_OCRV6_MEDIUM_DET, PP_OCRV6_MEDIUM_REC = PP_OCRV6_MODEL_PROFILES["medium"]\n\n\n',
        '''PP_OCRV6_MEDIUM_DET, PP_OCRV6_MEDIUM_REC = PP_OCRV6_MODEL_PROFILES["medium"]


class RetryableOCRError(RuntimeError):
    """An OCR failure that may succeed after the system has recovered."""


_TRANSIENT_ERROR_MARKERS = (
    "out of memory",
    "memoryerror",
    "cannot allocate memory",
    "failed to allocate",
    "std::bad_alloc",
    "bad allocation",
)


def _is_transient_ocr_error_text(value: str) -> bool:
    text = str(value or "").casefold()
    return any(marker in text for marker in _TRANSIENT_ERROR_MARKERS)


''',
        f"{path}: retryable error class",
    )

    # Wrap child startup so deterministic Paddle init errors can be distinguished from memory failures.
    old_start = '''def _engine_process(conn: Any, ocr_config: dict[str, Any]) -> None:
    # Import Paddle only in the short-lived inference process. When this process
    # exits after the warm-session timeout, all Paddle allocations are returned
    # to the OS before Ollama is allowed to acquire the shared AI lock.
    from paddleocr import PaddleOCR

    language = ocr_config["language"]
    version = ocr_config["version"]
    model_profile = ocr_config.get("model_profile", "medium")
    max_side_pixels = int(ocr_config.get("max_side_pixels", OCR_MAX_SIDE_PIXELS_DEFAULT))
    device = ocr_config["device"]
    started = time.monotonic()
    cpu_threads = _effective_cpu_threads()
    enable_hpi = _env_bool("OCR_ENABLE_HPI", False)
    model_kwargs = {
        "device": device,
        "use_doc_orientation_classify": False,
        "use_doc_unwarping": False,
        "use_textline_orientation": False,
        "enable_hpi": enable_hpi,
        "enable_mkldnn": True,
        "cpu_threads": cpu_threads,
    }
    detection_model = None
    recognition_model = None
    effective_model_profile = "upstream-default"

    if version == "PP-OCRv6":
        # Keep detection and recognition on the same explicit PP-OCRv6 tier.
        detection_model, recognition_model = _ppocrv6_model_names(model_profile)
        effective_model_profile = model_profile
        model_kwargs.update(
            text_detection_model_name=detection_model,
            text_recognition_model_name=recognition_model,
        )
    else:
        model_kwargs.update(lang=language, ocr_version=version)
    model = PaddleOCR(**model_kwargs)
    conn.send(
        {
            "type": "ready",
            "load_seconds": round(time.monotonic() - started, 3),
            "language": language,
            "ocr_version": version,
            "model_profile": effective_model_profile,
            "max_side_pixels": max_side_pixels,
            "device": device,
            "cpu_threads": cpu_threads,
            "enable_mkldnn": True,
            "enable_hpi": enable_hpi,
            "text_detection_model": detection_model,
            "text_recognition_model": recognition_model,
        }
    )

    while True:
'''
    new_start = '''def _engine_process(conn: Any, ocr_config: dict[str, Any]) -> None:
    # Import Paddle only in the short-lived inference process. When this process
    # exits after the warm-session timeout, all Paddle allocations are returned
    # to the OS before Ollama is allowed to acquire the shared AI lock.
    try:
        from paddleocr import PaddleOCR

        language = ocr_config["language"]
        version = ocr_config["version"]
        model_profile = ocr_config.get("model_profile", "medium")
        max_side_pixels = int(ocr_config.get("max_side_pixels", OCR_MAX_SIDE_PIXELS_DEFAULT))
        device = ocr_config["device"]
        started = time.monotonic()
        cpu_threads = _effective_cpu_threads()
        enable_hpi = _env_bool("OCR_ENABLE_HPI", False)
        model_kwargs = {
            "device": device,
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_textline_orientation": False,
            "enable_hpi": enable_hpi,
            "enable_mkldnn": True,
            "cpu_threads": cpu_threads,
        }
        detection_model = None
        recognition_model = None
        effective_model_profile = "upstream-default"

        if version == "PP-OCRv6":
            # Keep detection and recognition on the same explicit PP-OCRv6 tier.
            detection_model, recognition_model = _ppocrv6_model_names(model_profile)
            effective_model_profile = model_profile
            model_kwargs.update(
                text_detection_model_name=detection_model,
                text_recognition_model_name=recognition_model,
            )
        else:
            model_kwargs.update(lang=language, ocr_version=version)
        model = PaddleOCR(**model_kwargs)
        conn.send(
            {
                "type": "ready",
                "load_seconds": round(time.monotonic() - started, 3),
                "language": language,
                "ocr_version": version,
                "model_profile": effective_model_profile,
                "max_side_pixels": max_side_pixels,
                "device": device,
                "cpu_threads": cpu_threads,
                "enable_mkldnn": True,
                "enable_hpi": enable_hpi,
                "text_detection_model": detection_model,
                "text_recognition_model": recognition_model,
            }
        )
    except Exception as exc:
        try:
            conn.send(
                {
                    "type": "startup_error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "retryable": _is_transient_ocr_error_text(f"{type(exc).__name__}: {exc}"),
                }
            )
        finally:
            return

    while True:
'''
    text = replace_once(text, old_start, new_start, f"{path}: child startup protocol")

    text = replace_once(
        text,
        '                    "error": f"{type(exc).__name__}: {exc}",\n                }\n            )\n\n\nclass PaddleSession:',
        '                    "error": f"{type(exc).__name__}: {exc}",\n'
        '                    "retryable": _is_transient_ocr_error_text(\n'
        '                        f"{type(exc).__name__}: {exc}"\n'
        '                    ),\n'
        '                }\n'
        '            )\n\n\nclass PaddleSession:',
        f"{path}: child inference error retryability",
    )

    old_start_method = '''        try:
            if not parent_conn.poll(180):
                raise RuntimeError("Timed out waiting for PaddleOCR model initialization")
            ready = parent_conn.recv()
            if ready.get("type") != "ready":
                raise RuntimeError(f"Unexpected Paddle worker startup response: {ready!r}")
        except Exception:
            process.terminate()
            process.join(timeout=10)
            parent_conn.close()
            self._release_global_lock()
            raise
'''
    new_start_method = '''        try:
            if not parent_conn.poll(180):
                raise RetryableOCRError("Timed out waiting for PaddleOCR model initialization")
            try:
                ready = parent_conn.recv()
            except (EOFError, OSError, ValueError) as exc:
                raise RetryableOCRError(
                    f"Paddle worker startup IPC failed ({type(exc).__name__}, exitcode={process.exitcode})"
                ) from exc
            if ready.get("type") == "startup_error":
                message = str(ready.get("error") or "Paddle worker startup failed")
                if ready.get("retryable") or _is_transient_ocr_error_text(message):
                    raise RetryableOCRError(message)
                raise RuntimeError(message)
            if ready.get("type") != "ready":
                raise RuntimeError(f"Unexpected Paddle worker startup response: {ready!r}")
        except Exception:
            if process.is_alive():
                process.terminate()
            process.join(timeout=10)
            parent_conn.close()
            self._release_global_lock()
            raise
'''
    text = replace_once(text, old_start_method, new_start_method, f"{path}: startup retryability")

    text = replace_once(
        text,
        '        self._stop(reason)\n        raise RuntimeError(reason) from exc\n',
        '        self._stop(reason)\n        raise RetryableOCRError(reason) from exc\n',
        f"{path}: IPC retryable error",
    )

    text = replace_once(
        text,
        '                    raise RuntimeError(\n'
        '                        f"Paddle worker exited unexpectedly with code {exitcode}"\n'
        '                    )\n',
        '                    raise RetryableOCRError(\n'
        '                        f"Paddle worker exited unexpectedly with code {exitcode}"\n'
        '                    )\n',
        f"{path}: dead child retryability",
    )

    text = replace_once(
        text,
        '            if response.get("type") == "error":\n'
        '                raise RuntimeError(response.get("error", "Paddle OCR failed"))\n',
        '            if response.get("type") == "error":\n'
        '                error = str(response.get("error", "Paddle OCR failed"))\n'
        '                if response.get("retryable") or _is_transient_ocr_error_text(error):\n'
        '                    self._stop(f"retryable Paddle error: {error}")\n'
        '                    raise RetryableOCRError(error)\n'
        '                raise RuntimeError(error)\n',
        f"{path}: Paddle response retryability",
    )

    text = replace_once(
        text,
        '    def _json(self, status: int, payload: dict[str, Any]) -> None:\n'
        '        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")\n'
        '        self.send_response(status)\n'
        '        self.send_header("Content-Type", "application/json; charset=utf-8")\n'
        '        self.send_header("Content-Length", str(len(body)))\n'
        '        self.end_headers()\n'
        '        self.wfile.write(body)\n',
        '    def _json(\n'
        '        self,\n'
        '        status: int,\n'
        '        payload: dict[str, Any],\n'
        '        headers: dict[str, str] | None = None,\n'
        '    ) -> None:\n'
        '        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")\n'
        '        self.send_response(status)\n'
        '        self.send_header("Content-Type", "application/json; charset=utf-8")\n'
        '        self.send_header("Content-Length", str(len(body)))\n'
        '        for key, value in (headers or {}).items():\n'
        '            self.send_header(key, value)\n'
        '        self.end_headers()\n'
        '        self.wfile.write(body)\n',
        f"{path}: response headers",
    )

    text = replace_once(
        text,
        '                "max_side_pixels": int(cfg.get("max_side_pixels", OCR_MAX_SIDE_PIXELS_DEFAULT)),\n'
        '                "device": cfg["device"],\n',
        '                "max_side_pixels": int(cfg.get("max_side_pixels", OCR_MAX_SIDE_PIXELS_DEFAULT)),\n'
        '                "retry_delays_seconds": list(cfg.get("retry_delays_seconds", [])),\n'
        '                "recovery": recovery_control_state(),\n'
        '                "device": cfg["device"],\n',
        f"{path}: health recovery state",
    )

    old_request = '''            payload = _session().ocr(temp_path)
            self._json(200, payload)
        except Exception as exc:
            LOG.exception("OCR request failed")
            self._json(500, {"error": "ocr_failed", "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
'''
    new_request = '''            configured_retry_delays = [int(x) for x in cfg.get("retry_delays_seconds", [])]
            request_id = str(self.headers.get("X-PLAI-Request-ID", "") or uuid.uuid4().hex).strip()
            try:
                attempt = max(1, int(self.headers.get("X-PLAI-Attempt", "1")))
            except ValueError:
                attempt = 1
            try:
                page_number = int(self.headers.get("X-PLAI-Page-Number", "0")) or None
            except ValueError:
                page_number = None
            source = unquote(self.headers.get("X-PLAI-Source", "")).strip()[:300] or "OCR page"

            previous = read_recovery_state()
            previous_delays = previous.get("retry_delays_seconds")
            if (
                attempt > 1
                and previous.get("request_id") == request_id
                and isinstance(previous_delays, list)
            ):
                retry_delays = [int(x) for x in previous_delays]
            else:
                retry_delays = configured_retry_delays
            max_attempts = 1 + len(retry_delays)
            if attempt > max_attempts:
                self._json(
                    400,
                    {
                        "error": "invalid_retry_attempt",
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                    },
                )
                return

            consume_retry_now(request_id)
            write_recovery_state(
                {
                    "status": "running",
                    "request_id": request_id,
                    "source": source,
                    "page_number": page_number,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                    "retry_delays_seconds": retry_delays,
                }
            )

            try:
                payload = _session().ocr(temp_path)
            except RetryableOCRError as exc:
                detail = f"{type(exc).__name__}: {exc}"
                if attempt <= len(retry_delays):
                    delay = retry_delays[attempt - 1]
                    write_recovery_state(
                        {
                            "status": "waiting",
                            "request_id": request_id,
                            "source": source,
                            "page_number": page_number,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "retry_delays_seconds": retry_delays,
                            "last_error": detail,
                            "retry_after_seconds": delay,
                            "next_retry_at": iso_after_seconds(delay),
                        }
                    )
                    LOG.warning(
                        "Transient OCR failure for %s page %s on attempt %d/%d; retry in %ds: %s",
                        source,
                        page_number,
                        attempt,
                        max_attempts,
                        delay,
                        detail,
                    )
                    self._json(
                        503,
                        {
                            "error": "ocr_retryable",
                            "detail": detail,
                            "request_id": request_id,
                            "attempt": attempt,
                            "max_attempts": max_attempts,
                            "retry_after_seconds": delay,
                        },
                        {"Retry-After": str(delay)},
                    )
                    return

                failure = record_failure(
                    request_id=request_id,
                    source=source,
                    page_number=page_number,
                    attempts=attempt,
                    max_attempts=max_attempts,
                    error=detail,
                    retryable=True,
                    retry_delays_seconds=retry_delays,
                )
                write_recovery_state(
                    {
                        "status": "failed",
                        "request_id": request_id,
                        "source": source,
                        "page_number": page_number,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retry_delays_seconds": retry_delays,
                        "last_error": detail,
                        "failure_id": failure["id"],
                    }
                )
                LOG.error("OCR retries exhausted for %s page %s: %s", source, page_number, detail)
                self._json(
                    500,
                    {
                        "error": "ocr_retries_exhausted",
                        "detail": detail,
                        "attempts": attempt,
                        "max_attempts": max_attempts,
                    },
                )
                return
            except Exception as exc:
                detail = f"{type(exc).__name__}: {exc}"
                failure = record_failure(
                    request_id=request_id,
                    source=source,
                    page_number=page_number,
                    attempts=attempt,
                    max_attempts=max_attempts,
                    error=detail,
                    retryable=False,
                    retry_delays_seconds=retry_delays,
                )
                write_recovery_state(
                    {
                        "status": "failed",
                        "request_id": request_id,
                        "source": source,
                        "page_number": page_number,
                        "attempt": attempt,
                        "max_attempts": max_attempts,
                        "retry_delays_seconds": retry_delays,
                        "last_error": detail,
                        "failure_id": failure["id"],
                    }
                )
                LOG.exception("Non-retryable OCR request failed")
                self._json(500, {"error": "ocr_failed", "detail": detail})
                return

            set_idle_state()
            self._json(200, payload)
        except Exception as exc:
            LOG.exception("OCR request failed before inference")
            self._json(500, {"error": "ocr_failed", "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)
'''
    text = replace_once(text, old_request, new_request, f"{path}: request retry protocol")

    text = replace_once(
        text,
        '    sync_integration_plugin()\n    SESSION = PaddleSession()\n',
        '    sync_integration_plugin()\n    set_idle_state()\n    SESSION = PaddleSession()\n',
        f"{path}: initialize recovery state",
    )

    write_text(path, text)


def patch_plugin(repo: Path) -> None:
    path = repo / "src/ocr/ocrmypdf_plai.py"
    text = read_text(path)

    text = replace_once(
        text,
        'import logging\nimport os\nfrom pathlib import Path\nfrom typing import Any\nfrom urllib.parse import urlparse\n',
        'import logging\nimport os\nimport time\nimport uuid\nfrom pathlib import Path\nfrom typing import Any\nfrom urllib.parse import quote, urlparse\n',
        f"{path}: retry imports",
    )

    text = replace_once(
        text,
        'CONFIG_LOOKUP_TIMEOUT_SECONDS = 1.5\n',
        'CONFIG_LOOKUP_TIMEOUT_SECONDS = 1.5\n'
        'DEFAULT_RETRY_DELAYS_SECONDS = [15, 60, 300, 600]\n'
        'RETRY_STATUS_POLL_SECONDS = 2.0\n'
        'MAX_TOTAL_ATTEMPTS = 11\n',
        f"{path}: retry constants",
    )

    old_health = '''def _configured_max_side_pixels() -> int:
    conn = None
    try:
        scheme, host, port, path = _endpoint_parts("/health")
        connection_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = connection_cls(host, port, timeout=CONFIG_LOOKUP_TIMEOUT_SECONDS)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if 200 <= response.status < 300:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                return _validated_max_side_pixels(payload.get("max_side_pixels"))
        LOG.warning("OCR service config lookup returned HTTP %s; using %d px fallback", response.status, PADDLE_DEFAULT_MAX_SIDE_PIXELS)
    except Exception as exc:
        LOG.warning("OCR service config lookup failed (%s: %s); using %d px fallback", type(exc).__name__, exc, PADDLE_DEFAULT_MAX_SIDE_PIXELS)
    finally:
        if conn is not None:
            conn.close()
    return PADDLE_DEFAULT_MAX_SIDE_PIXELS
'''
    new_health = '''def _service_health(*, log_errors: bool = True) -> dict[str, Any] | None:
    conn = None
    try:
        scheme, host, port, path = _endpoint_parts("/health")
        connection_cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = connection_cls(host, port, timeout=CONFIG_LOOKUP_TIMEOUT_SECONDS)
        conn.request("GET", path)
        response = conn.getresponse()
        body = response.read()
        if 200 <= response.status < 300:
            payload = json.loads(body.decode("utf-8"))
            return payload if isinstance(payload, dict) else None
        if log_errors:
            LOG.warning("OCR service health lookup returned HTTP %s", response.status)
    except Exception as exc:
        if log_errors:
            LOG.warning("OCR service health lookup failed (%s: %s)", type(exc).__name__, exc)
    finally:
        if conn is not None:
            conn.close()
    return None


def _configured_max_side_pixels() -> int:
    payload = _service_health()
    if payload is not None:
        return _validated_max_side_pixels(payload.get("max_side_pixels"))
    LOG.warning("Using %d px OCR raster fallback", PADDLE_DEFAULT_MAX_SIDE_PIXELS)
    return PADDLE_DEFAULT_MAX_SIDE_PIXELS


def _validated_retry_delays(value: Any) -> list[int]:
    if not isinstance(value, list):
        return list(DEFAULT_RETRY_DELAYS_SECONDS)
    out: list[int] = []
    for item in value[:10]:
        if isinstance(item, bool):
            return list(DEFAULT_RETRY_DELAYS_SECONDS)
        try:
            delay = int(item)
        except (TypeError, ValueError):
            return list(DEFAULT_RETRY_DELAYS_SECONDS)
        if not 1 <= delay <= 86400:
            return list(DEFAULT_RETRY_DELAYS_SECONDS)
        out.append(delay)
    return out


def _configured_retry_delays() -> list[int]:
    payload = _service_health()
    if payload is not None and "retry_delays_seconds" in payload:
        return _validated_retry_delays(payload.get("retry_delays_seconds"))
    LOG.warning(
        "OCR retry configuration unavailable; using fallback schedule %s",
        DEFAULT_RETRY_DELAYS_SECONDS,
    )
    return list(DEFAULT_RETRY_DELAYS_SECONDS)
'''
    text = replace_once(text, old_health, new_health, f"{path}: shared health/config lookup")

    old_remote = '''def _remote_ocr(input_file: Path, options: Any) -> dict[str, Any]:
    scheme, host, port, path = _endpoint_parts()
    timeout = float(os.environ.get("PLAI_OCR_TIMEOUT_SECONDS", "1800"))
    connection_cls = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    conn = connection_cls(host, port, timeout=timeout)
    languages = _requested_languages(options)
    size = input_file.stat().st_size

    try:
        conn.putrequest("POST", path)
        conn.putheader("Authorization", f"Bearer {_token()}")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.putheader("X-PLAI-Filename", input_file.name)
        if languages:
            conn.putheader("X-PLAI-Language", ",".join(languages))
        conn.endheaders()

        with input_file.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)

        response = conn.getresponse()
        body = response.read()
        if response.status < 200 or response.status >= 300:
            detail = body.decode("utf-8", errors="replace")
            raise RuntimeError(
                f"paperless-local-ai OCR HTTP {response.status}: {detail}"
            )
        payload = json.loads(body.decode("utf-8"))
    except OSError as exc:
        raise RuntimeError(f"paperless-local-ai OCR unavailable: {exc}") from exc
    finally:
        conn.close()

    if not isinstance(payload, dict):
        raise RuntimeError("paperless-local-ai OCR returned a non-object response")
    return payload
'''
    new_remote = '''class RetryableRemoteOCRError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        retry_after_seconds: int | None = None,
        service_authorized_retry: bool = False,
    ) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds
        self.service_authorized_retry = service_authorized_retry


def _source_name(options: Any, input_file: Path) -> str:
    for attr in ("input_file", "input_file_or_options"):
        raw = getattr(options, attr, None) if options is not None else None
        if raw:
            try:
                return Path(str(raw)).name[:300]
            except Exception:
                pass
    return input_file.name[:300]


def _remote_ocr_once(
    input_file: Path,
    options: Any,
    *,
    request_id: str,
    attempt: int,
    page_number: int,
    source: str,
) -> dict[str, Any]:
    scheme, host, port, path = _endpoint_parts()
    timeout = float(os.environ.get("PLAI_OCR_TIMEOUT_SECONDS", "1800"))
    connection_cls = (
        http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
    )
    conn = connection_cls(host, port, timeout=timeout)
    languages = _requested_languages(options)
    size = input_file.stat().st_size

    try:
        conn.putrequest("POST", path)
        conn.putheader("Authorization", f"Bearer {_token()}")
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Content-Length", str(size))
        conn.putheader("X-PLAI-Filename", input_file.name)
        conn.putheader("X-PLAI-Request-ID", request_id)
        conn.putheader("X-PLAI-Attempt", str(attempt))
        conn.putheader("X-PLAI-Source", quote(source, safe=""))
        conn.putheader("X-PLAI-Page-Number", str(page_number + 1))
        if languages:
            conn.putheader("X-PLAI-Language", ",".join(languages))
        conn.endheaders()

        with input_file.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                conn.send(chunk)

        response = conn.getresponse()
        body = response.read()
        detail = body.decode("utf-8", errors="replace")
        if response.status in {502, 503, 504}:
            parsed = {}
            try:
                candidate = json.loads(detail)
                if isinstance(candidate, dict):
                    parsed = candidate
            except Exception:
                pass
            service_authorized = (
                response.status == 503
                and parsed.get("error") == "ocr_retryable"
                and parsed.get("request_id") == request_id
            )
            retry_after = None
            if service_authorized:
                try:
                    retry_after = int(parsed.get("retry_after_seconds"))
                except (TypeError, ValueError):
                    try:
                        retry_after = int(response.getheader("Retry-After") or "")
                    except (TypeError, ValueError):
                        retry_after = None
            raise RetryableRemoteOCRError(
                f"paperless-local-ai OCR HTTP {response.status}: {detail}",
                retry_after_seconds=retry_after,
                service_authorized_retry=service_authorized,
            )
        if response.status < 200 or response.status >= 300:
            raise RuntimeError(f"paperless-local-ai OCR HTTP {response.status}: {detail}")
        payload = json.loads(detail)
    except RetryableRemoteOCRError:
        raise
    except (OSError, http.client.HTTPException) as exc:
        raise RetryableRemoteOCRError(
            f"paperless-local-ai OCR temporarily unavailable: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        conn.close()

    if not isinstance(payload, dict):
        raise RuntimeError("paperless-local-ai OCR returned a non-object response")
    return payload


def _wait_for_retry(delay_seconds: int, request_id: str) -> None:
    delay_seconds = max(1, int(delay_seconds))
    deadline = time.monotonic() + delay_seconds
    LOG.warning("Waiting %ds before the next OCR attempt", delay_seconds)
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        payload = _service_health(log_errors=False)
        recovery = payload.get("recovery", {}) if isinstance(payload, dict) else {}
        if (
            isinstance(recovery, dict)
            and recovery.get("request_id") == request_id
            and recovery.get("retry_now_requested") is True
        ):
            LOG.warning("OCR retry wait skipped by Control Center Retry now")
            return
        time.sleep(min(RETRY_STATUS_POLL_SECONDS, remaining))


def _remote_ocr(
    input_file: Path,
    options: Any,
    page_number: int = 0,
) -> dict[str, Any]:
    configured_delays = _configured_retry_delays()
    request_id = uuid.uuid4().hex
    source = _source_name(options, input_file)
    attempt = 1

    while True:
        try:
            return _remote_ocr_once(
                input_file,
                options,
                request_id=request_id,
                attempt=attempt,
                page_number=page_number,
                source=source,
            )
        except RetryableRemoteOCRError as exc:
            # A 503 is the OCR service explicitly authorizing the next retry and
            # supplying its current configured delay. Connection-level failures
            # have no service response, so use the schedule fetched at start.
            if exc.service_authorized_retry:
                if attempt >= MAX_TOTAL_ATTEMPTS:
                    raise RuntimeError(
                        f"OCR retry safety limit reached after {attempt} attempt(s): {exc}"
                    ) from exc
                delay = exc.retry_after_seconds
                if delay is None:
                    index = attempt - 1
                    if index >= len(configured_delays):
                        raise RuntimeError(f"OCR retry schedule exhausted: {exc}") from exc
                    delay = configured_delays[index]
            else:
                index = attempt - 1
                if index >= len(configured_delays):
                    raise RuntimeError(
                        f"OCR unavailable after {attempt} attempt(s): {exc}"
                    ) from exc
                delay = configured_delays[index]

            LOG.warning(
                "Transient OCR failure on attempt %d; next attempt in %ds: %s",
                attempt,
                delay,
                exc,
            )
            _wait_for_retry(delay, request_id)
            attempt += 1
'''
    text = replace_once(text, old_remote, new_remote, f"{path}: retry loop")

    text = replace_once(
        text,
        '        return _build_ocr_tree(_remote_ocr(input_file, options), page_number)\n',
        '        return _build_ocr_tree(\n'
        '            _remote_ocr(input_file, options, page_number),\n'
        '            page_number,\n'
        '        )\n',
        f"{path}: pass page to retry protocol",
    )

    write_text(path, text)


def patch_ui(repo: Path) -> None:
    path = repo / "src/core/prompt_ui.py"
    text = read_text(path)

    text = replace_once(
        text,
        'from correspondent_runtime import (\n',
        'from ocr_recovery_state import (\n'
        '    dismiss_failure as dismiss_ocr_failure,\n'
        '    recovery_state_for_ui,\n'
        '    request_retry_now as request_ocr_retry_now,\n'
        ')\n\n'
        'from correspondent_runtime import (\n',
        f"{path}: recovery imports",
    )

    text = replace_once(
        text,
        '.status-box{padding:9px 11px;border-radius:8px;background:#111b28;border:1px solid var(--line);color:var(--muted);white-space:pre-wrap}.status-box.good{color:var(--green)}\n',
        '.status-box{padding:9px 11px;border-radius:8px;background:#111b28;border:1px solid var(--line);color:var(--muted);white-space:pre-wrap}.status-box.good{color:var(--green)}\n'
        '.pill.warn{color:var(--orange);border-color:#6a5127;background:#261d0f}.pill.bad{color:var(--red);border-color:#653638;background:#2b1517}\n'
        '.ocr-recovery-head{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap}.ocr-recovery-actions{display:flex;align-items:center;gap:9px}.failure-item{padding:11px 0;border-bottom:1px solid var(--line)}.failure-item:last-child{border-bottom:0}.failure-head{display:flex;align-items:center;justify-content:space-between;gap:10px}.failure-error{margin-top:5px;color:var(--muted);font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}\n',
        f"{path}: recovery styles",
    )

    text = replace_once(
        text,
        '<details class="section-help"><summary>OCR behavior</summary><div class="help-body">These values control selective PaddleOCR processing. Medium is the default PP-OCRv6 profile; Small and Tiny trade some recognition quality for lower inference cost. The maximum OCR image side limits the temporary raster sent to PaddleOCR and is the main memory-safety control for unusually high-resolution scans. Changes are picked up for the next OCR session, so no container restart is required. The original PDF is never modified.</div></details>',
        '<details class="section-help"><summary>OCR behavior</summary><div class="help-body">These values control selective PaddleOCR processing. Medium is the default PP-OCRv6 profile; Small and Tiny trade some recognition quality for lower inference cost. The maximum OCR image side limits the temporary raster sent to PaddleOCR and is the main memory-safety control for unusually high-resolution scans. Automatic retries handle short-lived worker, memory or service failures with a bounded backoff schedule; deterministic configuration/input errors still fail immediately. Changes are picked up for the next OCR session, so no container restart is required. The original PDF is never modified.</div></details>',
        f"{path}: OCR help",
    )

    text = replace_once(
        text,
        '            <div class="field"><label>Device <button type="button" class="info-btn" data-tip="PaddleOCR device. The tested low-power setup uses cpu.">i</button></label><input id="appOcrDevice"></div>\n'
        '          </div></div>\n'
        '        </div>\n\n'
        '        <div class="tab-page" id="app-runtime">',
        '            <div class="field"><label>Device <button type="button" class="info-btn" data-tip="PaddleOCR device. The tested low-power setup uses cpu.">i</button></label><input id="appOcrDevice"></div>\n'
        '            <div class="field" style="grid-column:1/-1"><label>Automatic retry delays in seconds <span class="mini">(retry_delays_seconds)</span> <button type="button" class="info-btn" data-tip="Comma-separated waits before each retry after a transient OCR failure. Each value adds one retry. Leave empty to disable automatic retries. Deterministic input or configuration errors are not retried.">i</button></label><input id="appOcrRetryDelays" class="mono" placeholder="15, 60, 300, 600"><div class="field-help">Default: <strong>15, 60, 300, 600</strong> = retry after 15 seconds, 1 minute, 5 minutes and 10 minutes. Keep the total backoff below Paperless&#39; worker timeout (1800 seconds by default) unless you raise <code>PAPERLESS_WORKER_TIMEOUT</code>. Up to 10 retries; each delay may be 1–86400 seconds.</div></div>\n'
        '          </div></div>\n'
        '          <div class="card panel" style="margin-top:14px">\n'
        '            <div class="ocr-recovery-head"><div><h3 style="margin:0">OCR recovery</h3><p class="mini" style="margin:4px 0 0">Live state for automatic recovery. Successful transient retries need no action.</p></div><div class="ocr-recovery-actions"><span id="ocrRecoveryPill" class="pill">Loading…</span><button id="ocrRetryNowBtn" class="btn" style="display:none">Retry now</button></div></div>\n'
        '            <div id="ocrRecoverySummary" class="status-box" style="margin-top:12px">Loading OCR recovery state…</div>\n'
        '            <details id="ocrFailureDetails" class="section-help" style="margin:12px 0 0"><summary>Recent final failures (<span id="ocrFailureCount">0</span>)</summary><div class="help-body"><div class="mini" style="margin-bottom:8px">Final failures are also visible in Paperless File Tasks. After automatic retries are exhausted, fix the cause and submit the source again in Paperless; paperless-local-ai does not silently requeue failed imports.</div><div id="ocrFailureList"><span class="mini">No final OCR failures recorded.</span></div></div></details>\n'
        '          </div>\n'
        '        </div>\n\n'
        '        <div class="tab-page" id="app-runtime">',
        f"{path}: retry field and recovery card",
    )

    text = replace_once(
        text,
        'function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$(\'appPaperlessUrl\').value.trim(),ollama_url:$(\'appOllamaUrl\').value.trim()},workflow:{llm_queue_tag:$(\'appLlmQueueTag\').value.trim(),llm_error_tag:$(\'appLlmErrorTag\').value.trim(),review_tag:$(\'appReviewTag\').value.trim(),extra_excluded_tags:$(\'appExtraExcludedTags\').value.split(\',\').map(x=>x.trim()).filter(Boolean)},ocr:{language:$(\'appOcrLanguage\').value.trim(),version:$(\'appOcrVersion\').value.trim(),model_profile:$(\'appOcrModelProfile\').value,max_side_pixels:Number($(\'appOcrMaxSidePixels\').value),device:$(\'appOcrDevice\').value.trim()},runtime:{poll_interval_seconds:Number($(\'appPollInterval\').value),review_prune_interval_seconds:Number($(\'appReviewPruneInterval\').value),dry_run:$(\'appDryRun\').value===\'true\'}}}\n',
        'function parseRetryDelays(value){const raw=value.trim();if(!raw)return[];const parts=raw.split(\',\').map(x=>x.trim());if(parts.some(x=>!/^\\d+$/.test(x)))throw new Error(\'OCR retry delays must be comma-separated whole seconds, for example: 15, 60, 300, 600\');return parts.map(Number)}\n'
        'function appDraft(){return {version:currentAppConfig?.version||1,updated_at:currentAppConfig?.updated_at||null,connections:{paperless_url:$(\'appPaperlessUrl\').value.trim(),ollama_url:$(\'appOllamaUrl\').value.trim()},workflow:{llm_queue_tag:$(\'appLlmQueueTag\').value.trim(),llm_error_tag:$(\'appLlmErrorTag\').value.trim(),review_tag:$(\'appReviewTag\').value.trim(),extra_excluded_tags:$(\'appExtraExcludedTags\').value.split(\',\').map(x=>x.trim()).filter(Boolean)},ocr:{language:$(\'appOcrLanguage\').value.trim(),version:$(\'appOcrVersion\').value.trim(),model_profile:$(\'appOcrModelProfile\').value,max_side_pixels:Number($(\'appOcrMaxSidePixels\').value),retry_delays_seconds:parseRetryDelays($(\'appOcrRetryDelays\').value),device:$(\'appOcrDevice\').value.trim()},runtime:{poll_interval_seconds:Number($(\'appPollInterval\').value),review_prune_interval_seconds:Number($(\'appReviewPruneInterval\').value),dry_run:$(\'appDryRun\').value===\'true\'}}}\n',
        f"{path}: app draft retries",
    )

    text = replace_once(
        text,
        "$('appOcrModelProfile').value=c.ocr.model_profile||'medium';$('appOcrMaxSidePixels').value=c.ocr.max_side_pixels||3000;$('appOcrDevice').value=c.ocr.device;",
        "$('appOcrModelProfile').value=c.ocr.model_profile||'medium';$('appOcrMaxSidePixels').value=c.ocr.max_side_pixels||3000;$('appOcrRetryDelays').value=(c.ocr.retry_delays_seconds||[]).join(', ');$('appOcrDevice').value=c.ocr.device;",
        f"{path}: app fill retries",
    )

    text = replace_once(
        text,
        'function renderAppHistory(items){renderHistory(items,\'appHistoryList\',\'restoreAppHistory\')}\nfunction renderCorrHistory(items){renderHistory(items,\'corrHistoryList\',\'restoreCorrHistory\')}\n\n',
        '''function renderAppHistory(items){renderHistory(items,'appHistoryList','restoreAppHistory')}
function renderCorrHistory(items){renderHistory(items,'corrHistoryList','restoreCorrHistory')}
function escapeHtml(value){return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]))}
function humanDelay(seconds){seconds=Math.max(0,Math.round(Number(seconds)||0));if(seconds<60)return`${seconds}s`;if(seconds<3600)return`${Math.floor(seconds/60)}m ${seconds%60}s`;return`${Math.floor(seconds/3600)}h ${Math.floor((seconds%3600)/60)}m`}
function renderOcrRecovery(payload){
  const state=payload?.state||{status:'idle'};const failures=payload?.failures||[];const pill=$('ocrRecoveryPill');const retry=$('ocrRetryNowBtn');const summary=$('ocrRecoverySummary');
  const displayStatus=state.status==='idle'&&failures.length?'failed':state.status;const labels={idle:'Ready',running:'OCR running',waiting:'Waiting to retry',failed:'Needs attention'};pill.textContent=labels[displayStatus]||displayStatus||'Ready';pill.className='pill '+(displayStatus==='idle'?'good':displayStatus==='failed'?'bad':displayStatus==='waiting'?'warn':'');
  retry.style.display=state.status==='waiting'?'inline-block':'none';retry.dataset.requestId=state.request_id||'';retry.disabled=!!state.retry_now_requested;retry.textContent=state.retry_now_requested?'Retry requested':'Retry now';
  if(state.status==='waiting'){
    const next=state.next_retry_at?Math.max(0,(new Date(state.next_retry_at).getTime()-Date.now())/1000):state.retry_after_seconds;
    summary.textContent=`${state.source||'OCR page'}${state.page_number?' · page '+state.page_number:''} · attempt ${state.attempt||'?'} / ${state.max_attempts||'?'} failed. ${state.retry_now_requested?'Immediate retry requested.':'Next retry in '+humanDelay(next)+'.'}\n${state.last_error||''}`;
  }else if(state.status==='running'){
    summary.textContent=`${state.source||'OCR page'}${state.page_number?' · page '+state.page_number:''} · attempt ${state.attempt||1} / ${state.max_attempts||1} is running.`;
  }else if(state.status==='failed'){
    summary.textContent=`Automatic OCR recovery stopped after a final failure.${state.source?'\\n'+state.source+(state.page_number?' · page '+state.page_number:''):''}${state.last_error?'\\n'+state.last_error:''}`;
  }else if(failures.length){
    summary.textContent=`OCR is currently idle. ${failures.length} final failure${failures.length===1?' needs':'s need'} review below.`;
  }else{
    summary.textContent='No OCR recovery action is needed. Transient failures are retried automatically according to the configured schedule.';
  }
  $('ocrFailureCount').textContent=String(failures.length);
  $('ocrFailureList').innerHTML=failures.length?failures.map(f=>`<div class="failure-item"><div class="failure-head"><div><strong>${escapeHtml(f.source||'OCR page')}</strong>${f.page_number?` <span class="mini">· page ${f.page_number}</span>`:''}<div class="mini">${escapeHtml(f.failed_at||'')} · ${f.attempts||1}/${f.max_attempts||1} attempt(s)</div></div><button class="btn" onclick="dismissOcrFailure('${escapeHtml(f.id)}')">Dismiss</button></div><div class="failure-error">${escapeHtml(f.error||'Unknown OCR error')}</div></div>`).join(''):'<span class="mini">No final OCR failures recorded.</span>';
}
async function refreshOcrRecovery(){try{renderOcrRecovery(await api('/api/app/ocr/recovery'))}catch(e){$('ocrRecoveryPill').textContent='Unavailable';$('ocrRecoverySummary').textContent=e.message}}
window.dismissOcrFailure=async id=>{try{await api('/api/app/ocr/failures/dismiss',{method:'POST',body:JSON.stringify({failure_id:id})});await refreshOcrRecovery()}catch(e){alert(e.message)}};

''',
        f"{path}: recovery JS helpers",
    )

    text = replace_once(
        text,
        "$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Testing connections…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'ERROR'}${r.paperless.detail?' · '+r.paperless.detail:''}\\nOllama: ${r.ollama.ok?'OK':'ERROR'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok);applyConnectionResult(r)}catch(e){setStatus('appConnectionStatus',e.message,false)}};\n",
        "$('appConnectionTestBtn').onclick=async()=>{setStatus('appConnectionStatus','Testing connections…');try{const r=await api('/api/app/connections/test',{method:'POST',body:JSON.stringify({config:appDraft()})});setStatus('appConnectionStatus',`Paperless: ${r.paperless.ok?'OK':'ERROR'}${r.paperless.detail?' · '+r.paperless.detail:''}\\nOllama: ${r.ollama.ok?'OK':'ERROR'}${r.ollama.detail?' · '+r.ollama.detail:''}`,r.paperless.ok&&r.ollama.ok);applyConnectionResult(r)}catch(e){setStatus('appConnectionStatus',e.message,false)}};\n"
        "$('ocrRetryNowBtn').onclick=async()=>{const id=$('ocrRetryNowBtn').dataset.requestId;if(!id)return;try{await api('/api/app/ocr/retry-now',{method:'POST',body:JSON.stringify({request_id:id})});await refreshOcrRecovery()}catch(e){alert(e.message)}};\n",
        f"{path}: Retry now action",
    )

    text = replace_once(
        text,
        'init();loadCorrespondent();loadApp();\n',
        'init();loadCorrespondent();loadApp();refreshOcrRecovery();setInterval(refreshOcrRecovery,5000);\n',
        f"{path}: recovery polling",
    )

    text = replace_once(
        text,
        '        if self.command == "GET" and path == "/api/app/history":\n'
        '            return response(self, HTTPStatus.OK, {"items": list_app_history()})\n\n',
        '        if self.command == "GET" and path == "/api/app/history":\n'
        '            return response(self, HTTPStatus.OK, {"items": list_app_history()})\n\n'
        '        if self.command == "GET" and path == "/api/app/ocr/recovery":\n'
        '            return response(self, HTTPStatus.OK, recovery_state_for_ui())\n\n'
        '        if self.command == "POST" and path == "/api/app/ocr/retry-now":\n'
        '            payload = body_json(self)\n'
        '            trigger = request_ocr_retry_now(payload.get("request_id", ""))\n'
        '            return response(self, HTTPStatus.OK, {"ok": True, "trigger": trigger})\n\n'
        '        if self.command == "POST" and path == "/api/app/ocr/failures/dismiss":\n'
        '            payload = body_json(self)\n'
        '            removed = dismiss_ocr_failure(payload.get("failure_id", ""))\n'
        '            return response(self, HTTPStatus.OK, {"ok": True, "removed": removed})\n\n',
        f"{path}: recovery API routes",
    )

    write_text(path, text)


def patch_tests(repo: Path) -> None:
    path = repo / "tests/test_app_config.py"
    text = read_text(path)
    text = replace_once(
        text,
        '    OCR_MODEL_PROFILES,\n',
        '    OCR_MODEL_PROFILES,\n'
        '    OCR_RETRY_DELAYS_DEFAULT,\n'
        '    OCR_RETRY_DELAYS_MAX_COUNT,\n'
        '    OCR_RETRY_DELAY_MAX_SECONDS,\n',
        f"{path}: retry constants imports",
    )
    text = replace_once(
        text,
        '    assert OCR_MODEL_PROFILES == ("medium", "small", "tiny")\n',
        '    assert OCR_MODEL_PROFILES == ("medium", "small", "tiny")\n'
        '    assert cfg["ocr"]["retry_delays_seconds"] == [15, 60, 300, 600]\n'
        '    assert OCR_RETRY_DELAYS_DEFAULT == (15, 60, 300, 600)\n'
        '    assert OCR_RETRY_DELAYS_MAX_COUNT == 10\n'
        '    assert OCR_RETRY_DELAY_MAX_SECONDS == 86400\n',
        f"{path}: retry defaults asserts",
    )
    text += '''\n\ndef test_existing_config_without_retry_delays_gets_default_schedule():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {
            "language": "de",
            "version": "PP-OCRv6",
            "model_profile": "medium",
            "max_side_pixels": 3000,
            "device": "cpu",
        },
    }
    validated = validate_config(raw)
    assert validated["ocr"]["retry_delays_seconds"] == [15, 60, 300, 600]


def test_empty_retry_schedule_disables_automatic_retries():
    raw = {
        **DEFAULT_CONFIG,
        "ocr": {**DEFAULT_CONFIG["ocr"], "retry_delays_seconds": []},
    }
    assert validate_config(raw)["ocr"]["retry_delays_seconds"] == []


def test_retry_schedule_validation_is_bounded():
    invalid = ([0], [86401], [1] * 11, "15,60")
    for value in invalid:
        raw = {
            **DEFAULT_CONFIG,
            "ocr": {**DEFAULT_CONFIG["ocr"], "retry_delays_seconds": value},
        }
        try:
            validate_config(raw)
        except ValueError as exc:
            assert "retry_delays_seconds" in str(exc)
        else:
            raise AssertionError(f"retry_delays_seconds={value!r} must be rejected")
'''
    write_text(path, text)

    path = repo / "tests/test_ocr_plugin.py"
    text = read_text(path)
    text += '''\n\ndef test_retry_delay_validation_preserves_empty_schedule():
    assert plugin._validated_retry_delays([]) == []
    assert plugin._validated_retry_delays([15, 60, 300, 600]) == [15, 60, 300, 600]
    assert plugin._validated_retry_delays([0]) == plugin.DEFAULT_RETRY_DELAYS_SECONDS


def test_remote_ocr_retries_service_authorized_failure(monkeypatch, tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    calls = []
    waits = []

    monkeypatch.setattr(plugin, "_configured_retry_delays", lambda: [15, 60])
    monkeypatch.setattr(plugin, "_source_name", lambda options, input_file: "scan.pdf")
    monkeypatch.setattr(plugin, "_wait_for_retry", lambda delay, request_id: waits.append(delay))

    def fake_once(*args, **kwargs):
        calls.append(kwargs["attempt"])
        if len(calls) == 1:
            raise plugin.RetryableRemoteOCRError(
                "temporary",
                retry_after_seconds=15,
                service_authorized_retry=True,
            )
        return {"ok": True}

    monkeypatch.setattr(plugin, "_remote_ocr_once", fake_once)
    assert plugin._remote_ocr(image, None, 0) == {"ok": True}
    assert calls == [1, 2]
    assert waits == [15]


def test_remote_ocr_does_not_retry_final_http_error(monkeypatch, tmp_path):
    image = tmp_path / "page.png"
    image.write_bytes(b"fake")
    monkeypatch.setattr(plugin, "_configured_retry_delays", lambda: [15, 60])
    monkeypatch.setattr(plugin, "_source_name", lambda options, input_file: "scan.pdf")

    def fail_once(*args, **kwargs):
        raise RuntimeError("paperless-local-ai OCR HTTP 500: deterministic")

    monkeypatch.setattr(plugin, "_remote_ocr_once", fail_once)
    try:
        plugin._remote_ocr(image, None, 0)
    except RuntimeError as exc:
        assert "deterministic" in str(exc)
    else:
        raise AssertionError("final HTTP errors must fail immediately")
'''
    write_text(path, text)

    path = repo / "tests/test_ocr_service.py"
    text = read_text(path)
    text = replace_once(
        text,
        'from service import _poly, _result_get, _seq\n',
        'import service as ocr_service\nfrom service import _poly, _result_get, _seq\n',
        f"{path}: service module import",
    )
    text += '''\n\ndef test_transient_ocr_error_classifier_is_narrow():
    assert ocr_service._is_transient_ocr_error_text("MemoryError: allocation failed")
    assert ocr_service._is_transient_ocr_error_text("std::bad_alloc")
    assert not ocr_service._is_transient_ocr_error_text("ValueError: invalid image")
    assert not ocr_service._is_transient_ocr_error_text("language mismatch")


def test_retryable_ocr_error_is_distinct():
    exc = ocr_service.RetryableOCRError("worker exited")
    assert isinstance(exc, RuntimeError)
'''
    write_text(path, text)

    write_text(
        repo / "tests/test_ocr_recovery_state.py",
        '''import ocr_recovery_state as state


def _point_state_at(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "COORDINATION_DIR", tmp_path)
    monkeypatch.setattr(state, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(state, "FAILURES_FILE", tmp_path / "failures.json")
    monkeypatch.setattr(state, "RETRY_NOW_FILE", tmp_path / "retry.json")
    monkeypatch.setattr(state, "LOCK_FILE", tmp_path / "state.lock")


def test_retry_now_only_targets_current_waiting_request(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    state.write_recovery_state({"status": "waiting", "request_id": "abc"})
    state.request_retry_now("abc")
    assert state.retry_now_requested("abc") is True
    assert state.retry_now_requested("other") is False
    assert state.consume_retry_now("abc") is True
    assert state.retry_now_requested("abc") is False


def test_retry_now_rejects_non_waiting_state(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    state.set_idle_state()
    try:
        state.request_retry_now("abc")
    except ValueError as exc:
        assert "No OCR retry" in str(exc)
    else:
        raise AssertionError("Retry now must require a waiting request")


def test_health_control_state_omits_document_details(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    state.write_recovery_state(
        {
            "status": "waiting",
            "request_id": "abc",
            "source": "private-document.pdf",
            "page_number": 2,
            "last_error": "private detail",
        }
    )
    control = state.recovery_control_state()
    assert control["status"] == "waiting"
    assert control["request_id"] == "abc"
    assert "source" not in control
    assert "page_number" not in control
    assert "last_error" not in control


def test_failure_history_is_bounded_and_dismissible(tmp_path, monkeypatch):
    _point_state_at(tmp_path, monkeypatch)
    monkeypatch.setattr(state, "MAX_FAILURES", 3)
    ids = []
    for index in range(5):
        item = state.record_failure(
            request_id=f"r{index}",
            source="scan.pdf",
            page_number=1,
            attempts=5,
            max_attempts=5,
            error="boom",
            retryable=True,
            retry_delays_seconds=[15, 60, 300, 600],
        )
        ids.append(item["id"])
    assert len(state.list_failures()) == 3
    newest = state.list_failures()[0]["id"]
    assert state.dismiss_failure(newest) is True
    assert len(state.list_failures()) == 2
''',
    )

    path = repo / "tests/test_public_contracts.py"
    text = read_text(path)
    text = replace_once(
        text,
        '        "PP-OCRv6 Tiny — Fastest · Lower accuracy",\n',
        '        "PP-OCRv6 Tiny — Fastest · Lower accuracy",\n'
        '        "Automatic retry delays in seconds",\n'
        '        "OCR recovery",\n'
        '        "Retry now",\n'
        '        "Recent final failures",\n'
        '        "appOcrRetryDelays",\n',
        f"{path}: recovery UI contract",
    )
    write_text(path, text)


def patch_docs(repo: Path) -> None:
    path = repo / "README.md"
    text = read_text(path)
    text = replace_once(
        text,
        '- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles selectable when lower inference cost matters.\n',
        '- **Improved scan OCR with PaddleOCR** — PP-OCRv6 Medium is the quality-focused default, with Small and Tiny profiles selectable when lower inference cost matters; bounded automatic retries recover from transient OCR worker/service failures.\n',
        f"{path}: highlight retries",
    )
    text = replace_once(
        text,
        '- OCR language/version/model profile, temporary OCR raster limit and device;\n',
        '- OCR language/version/model profile, temporary OCR raster limit, automatic retry schedule and recovery status;\n',
        f"{path}: Control Center retries",
    )
    write_text(path, text)

    path = repo / "docs/configuration.md"
    text = read_text(path)
    text = replace_once(
        text,
        '- maximum OCR image side in pixels;\n- device.\n',
        '- maximum OCR image side in pixels;\n- automatic retry delays;\n- device.\n',
        f"{path}: OCR settings list",
    )
    marker = 'Existing saved configurations without `ocr.max_side_pixels` automatically use `3000`, so the setting does not require a deployment migration.\n\n'
    addition = '''Existing saved configurations without `ocr.max_side_pixels` automatically use `3000`, so the setting does not require a deployment migration.

`ocr.retry_delays_seconds` controls bounded automatic recovery for transient OCR failures. The default is **`[15, 60, 300, 600]`**, meaning one initial attempt followed by retries after 15 seconds, 1 minute, 5 minutes and 10 minutes. In the Control Center this is edited as a comma-separated list (`15, 60, 300, 600`). Each value adds one retry; an empty field disables automatic retries. Up to 10 delays are accepted, each from 1 to 86400 seconds. Paperless defaults `PAPERLESS_WORKER_TIMEOUT` to 1800 seconds, so the shipped schedule deliberately leaves headroom for the OCR attempts themselves. If you configure substantially longer backoffs, increase the Paperless worker timeout as well.

Retries are intentionally limited to failures that can plausibly recover later, such as an unexpectedly terminated Paddle worker, IPC loss, memory-allocation failure or temporary OCR-service/network unavailability. Authentication, language/configuration, malformed-input and other deterministic errors fail immediately. A long Paddle page timeout remains a final error rather than starting another potentially 30-minute attempt.

During retry backoff the failed Paddle subprocess is torn down and the shared `ai.lock` is released. The OCRmyPDF bridge keeps the Paperless consume task alive and starts the next attempt after the configured delay. The Control Center's **OCR recovery** card shows the current state and can skip an active wait with **Retry now**. The retry count remains bounded; `Retry now` does not add another attempt.

Existing saved configurations without `ocr.retry_delays_seconds` automatically receive the default schedule.

'''
    text = replace_once(text, marker, addition, f"{path}: retry configuration docs")
    write_text(path, text)

    path = repo / "docs/troubleshooting.md"
    text = read_text(path)
    marker = '## App settings seem ignored\n'
    section = '''## OCR retries and final failures

Transient OCR failures are retried inside the Paperless/OCRmyPDF import while the consume task is still active. The default waits are 15 seconds, 1 minute, 5 minutes and 10 minutes. Change or disable the schedule under **App Settings → OCR**. The default schedule is kept below Paperless' 1800-second worker timeout with room for the OCR attempts; longer custom schedules may require a higher `PAPERLESS_WORKER_TIMEOUT`.

The **OCR recovery** card shows four normal states:

- **Ready** — no recovery action is needed;
- **OCR running** — an OCR attempt is active;
- **Waiting to retry** — a transient failure was detected and another bounded attempt is scheduled; **Retry now** skips only the remaining wait;
- **Needs attention** — the configured retries were exhausted or the failure was classified as deterministic.

Only transient failures are retried. Authentication/configuration errors, OCR language mismatches, malformed input and deterministic Paddle errors fail immediately.

Final failures remain visible in Paperless File Tasks and are also kept in the Control Center's bounded **Recent final failures** history. Paperless-ngx 3.0.5 does not expose a supported generic retry operation for an already failed initial consume task, so the Control Center deliberately does not pretend it can safely requeue that completed failure. Fix the cause, then submit the source again through Paperless. **Dismiss** only removes the Control Center history entry.

If repeated failures are memory-related, lower **Maximum OCR image side** before increasing the OCR container memory limit.

'''
    if marker not in text:
        raise RuntimeError(f"{path}: troubleshooting insertion marker missing")
    text = text.replace(marker, section + marker, 1)
    write_text(path, text)

    path = repo / "docs/architecture.md"
    text = read_text(path)
    text = replace_once(
        text,
        '5. only after cleanup is complete is `ai.lock` released.\n\n`/health.session_active` follows ownership of the global AI slot, not merely process liveness. A reported idle state therefore means the OCR service has actually released the shared lock.\n',
        '5. only after cleanup is complete is `ai.lock` released.\n\n'
        'Transient worker/service failures use a bounded retry protocol between the OCRmyPDF bridge and `ocr-service`. One HTTP request represents one Paddle attempt. If the worker dies or another retryable condition occurs, `ocr-service` tears down the failed session, releases `ai.lock`, records recovery state and returns HTTP 503 with the configured next delay. The OCRmyPDF bridge waits and submits the same page again with a stable recovery request ID. This avoids keeping a single service connection open across long backoff periods. Deterministic failures return a final error immediately.\n\n'
        '`/health.session_active` follows ownership of the global AI slot, not merely process liveness. A reported idle state therefore means the OCR service has actually released the shared lock. `/health` also exposes the current retry schedule plus only the minimal retry-control state needed by the bridge. Document source names, page details and errors remain on the shared coordination volume for the Control Center and are not exposed through the unauthenticated health endpoint.\n',
        f"{path}: retry protocol architecture",
    )
    text = replace_once(
        text,
        'coordination/  shared ai.lock\n',
        'coordination/  shared ai.lock + bounded OCR recovery state/history\n',
        f"{path}: coordination state",
    )
    write_text(path, text)


def patch_changelog_and_version(repo: Path) -> None:
    write_text(repo / "VERSION", TARGET_VERSION + "\n")
    path = repo / "CHANGELOG.md"
    text = read_text(path)
    entry = f'''## {TARGET_VERSION} - {RELEASE_DATE}

### Automatic OCR recovery

- add bounded automatic retries for transient OCR failures with the default backoff **15 s → 1 min → 5 min → 10 min** after the initial attempt;
- expose the retry schedule under **Control Center → App Settings → OCR** as a simple comma-separated list; each value adds one retry, an empty list disables retries, and existing 0.2.2 configurations receive the default schedule automatically;
- keep deterministic authentication, language/configuration, malformed-input and ordinary Paddle errors fail-fast instead of repeatedly retrying failures that are unlikely to recover;
- tear down a failed Paddle subprocess and release the shared `ai.lock` before every delayed retry so Ollama and other work are not blocked during backoff;
- use a stateless 503/`Retry-After` protocol between the OCR service and OCRmyPDF bridge so long backoff periods do not keep one service-side HTTP request open;
- recover from temporary OCR-service/network unavailability in the bridge with the same bounded schedule;
- add a compact **OCR recovery** card to the Control Center with live Running/Waiting/Needs-attention state, **Retry now** while a retry is waiting, and bounded recent final-failure history with Dismiss;
- keep final failures visible instead of silently requeueing forever; Paperless-ngx 3.0.5 has no supported generic retry action for an already failed initial consume task, so final recovery remains an explicit user action after the underlying cause is fixed.

### Deployment

- image-only update from 0.2.2; no port, mount, secret or container resource-limit changes are required.

'''
    text = replace_once(text, "## Unreleased\n\n", "## Unreleased\n\n" + entry, f"{path}: changelog")
    write_text(path, text)


def regenerate_manifests(repo: Path) -> None:
    manifest_path = repo / "SOURCE-MANIFEST.json"
    manifest = json.loads(read_text(manifest_path))
    manifest["version"] = TARGET_VERSION
    manifest["created"] = RELEASE_DATE
    source_files = manifest.setdefault("source_files", {})
    source_files["src/common/ocr_recovery_state.py"] = ""
    for rel in list(source_files):
        source_files[rel] = sha256(repo / rel)
    write_text(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")

    lines = [
        f"paperless-local-ai {TARGET_VERSION} update",
        "Generated after applying bounded OCR recovery.",
        "",
    ]
    for rel in CHANGED_FILES:
        if rel == "OVERLAY-SHA256.txt":
            continue
        path = repo / rel
        if path.exists():
            lines.append(f"{sha256(path)}  {rel}")
    write_text(repo / "OVERLAY-SHA256.txt", "\n".join(lines) + "\n")


def run_checks(repo: Path) -> None:
    print("\nRunning Python compile checks...")
    subprocess.run(
        [sys.executable, "-m", "compileall", "-q", "src", "tests", "scripts"],
        cwd=repo,
        check=True,
    )
    print("compileall: PASS")

    if (repo / ".git").exists():
        subprocess.run(["git", "diff", "--check"], cwd=repo, check=True)
        print("git diff --check: PASS")

    if os.name == "nt":
        print("pytest: skipped locally on Windows (the project uses Linux-only fcntl).")
        print("        GitHub Actions on Ubuntu is the authoritative full test run after push.")
        return

    try:
        import pytest  # noqa: F401
    except ImportError:
        print("pytest: not installed; skipped. GitHub Actions will run the full suite.")
        return

    subprocess.run([sys.executable, "-m", "pytest", "-q"], cwd=repo, check=True)
    print("pytest: PASS")


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply paperless-local-ai 0.2.3 bounded OCR recovery")
    parser.add_argument("repo", nargs="?", default=".", help="Repository root (default: current directory)")
    parser.add_argument("--no-checks", action="store_true", help="Skip compile/diff/pytest checks")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    required = ["VERSION", "SOURCE-MANIFEST.json", "src/common/app_config.py"]
    missing = [rel for rel in required if not (repo / rel).exists()]
    if missing:
        raise RuntimeError("This does not look like paperless-local-ai. Missing: " + ", ".join(missing))

    print(f"Repository: {repo}")
    print("Verifying exact released 0.2.2 runtime base...")
    verify_base(repo)
    print("Base verification: PASS")

    patch_app_config(repo)
    add_recovery_state_module(repo)
    patch_service(repo)
    patch_plugin(repo)
    patch_ui(repo)
    patch_tests(repo)
    patch_docs(repo)
    patch_changelog_and_version(repo)
    regenerate_manifests(repo)

    print("\nUpdated:")
    for rel in CHANGED_FILES:
        if (repo / rel).exists():
            print(f"  {rel}")

    if not args.no_checks:
        run_checks(repo)

    print("\n0.2.3 bounded OCR recovery applied successfully.")
    print("Review the diff in GitHub Desktop before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
