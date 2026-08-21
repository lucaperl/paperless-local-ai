from __future__ import annotations

import fcntl
import hmac
import json
import logging
import math
import multiprocessing as mp
import os
import shutil
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from app_config import load_config as load_app_config


LOG = logging.getLogger("plai.ocr_service")
logging.basicConfig(
    level=os.getenv("PLAI_OCR_LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)

HOST = os.getenv("OCR_SERVICE_HOST", "0.0.0.0")
PORT = int(os.getenv("OCR_SERVICE_PORT", "8082"))
TOKEN = os.getenv("OCR_SERVICE_TOKEN", "")
MAX_REQUEST_BYTES = int(os.getenv("OCR_MAX_REQUEST_BYTES", str(100 * 1024 * 1024)))
AI_LOCK_FILE = Path("/coordination/ai.lock")
INTEGRATION_SOURCE = Path(os.getenv("OCR_PLUGIN_SOURCE", "/app/ocrmypdf_plai.py"))
INTEGRATION_TARGET = Path("/integration/ocrmypdf_plai.py")
SESSION_IDLE_SECONDS = float(os.getenv("OCR_SESSION_IDLE_SECONDS", "5"))
PAGE_TIMEOUT_SECONDS = float(os.getenv("OCR_PAGE_TIMEOUT_SECONDS", "1800"))
TMP_DIR = Path(os.getenv("OCR_TMP_DIR", "/dev/shm/paperless-local-ai-ocr"))
PP_OCRV6_MEDIUM_DET = "PP-OCRv6_medium_det"
PP_OCRV6_MEDIUM_REC = "PP-OCRv6_medium_rec"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


_LANGUAGE_ALIASES = {
    "de": "de", "deu": "de", "ger": "de",
    "en": "en", "eng": "en",
    "it": "it", "ita": "it",
    "fr": "fr", "fra": "fr", "fre": "fr",
    "es": "es", "spa": "es",
    "pt": "pt", "por": "pt",
    "nl": "nl", "nld": "nl", "dut": "nl",
}


def _normalize_language(value: str) -> str:
    code = value.strip().lower().replace("_", "-").split("-", 1)[0]
    return _LANGUAGE_ALIASES.get(code, code)


def _language_header_matches(requested: str, configured: str) -> bool:
    if not requested.strip():
        return True
    wanted = {_normalize_language(item) for item in requested.split(",") if item.strip()}
    return _normalize_language(configured) in wanted


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "tolist"):
        return _jsonable(value.tolist())
    return str(value)


def _result_get(result: Any, key: str, default: Any = None) -> Any:
    if hasattr(result, "get"):
        try:
            return result.get(key, default)
        except TypeError:
            pass
    try:
        return result[key]
    except Exception:
        return default


def _seq(value: Any) -> list[Any]:
    if value is None:
        return []
    raw = _jsonable(value)
    return raw if isinstance(raw, list) else []


def _poly(value: Any) -> list[list[float]]:
    raw = _jsonable(value)
    if not isinstance(raw, list):
        return []
    if len(raw) == 4 and all(isinstance(item, (int, float)) for item in raw):
        x0, y0, x1, y1 = (float(item) for item in raw)
        return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]

    out: list[list[float]] = []
    for point in raw:
        if not isinstance(point, list) or len(point) < 2:
            continue
        try:
            out.append([float(point[0]), float(point[1])])
        except (TypeError, ValueError):
            continue
    return out


def _line_words(result: Any, line_index: int) -> list[dict[str, Any]]:
    words_all = _seq(_result_get(result, "text_word", []))
    boxes_value = _result_get(result, "text_word_boxes", None)
    if boxes_value is None:
        boxes_value = _result_get(result, "text_word_region", None)
    boxes_all = _seq(boxes_value)
    if line_index >= len(words_all) or line_index >= len(boxes_all):
        return []

    tokens = _seq(words_all[line_index])
    boxes = _seq(boxes_all[line_index])
    out: list[dict[str, Any]] = []
    current_text: list[str] = []
    current_polys: list[list[list[float]]] = []

    def flush_word() -> None:
        if not current_text or not current_polys:
            current_text.clear()
            current_polys.clear()
            return
        points = [point for poly in current_polys for point in poly]
        xs = [point[0] for point in points]
        ys = [point[1] for point in points]
        if xs and ys:
            x0, x1 = min(xs), max(xs)
            y0, y1 = min(ys), max(ys)
            out.append(
                {
                    "text": "".join(current_text),
                    "poly": [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                }
            )
        current_text.clear()
        current_polys.clear()

    for token, box in zip(tokens, boxes):
        text = str(token)
        if not text:
            continue
        if text.isspace():
            flush_word()
            continue
        poly = _poly(box)
        if len(poly) < 4:
            continue
        current_text.append(text)
        current_polys.append(poly)

    flush_word()

    # Paddle exposes line text and word-token geometry separately. Prefer the
    # canonical recognized line text whenever it has the same word count; this
    # prevents compatibility glyphs/ligatures in token metadata from corrupting
    # otherwise-correct searchable text while preserving Paddle's word boxes.
    line_texts = _seq(_result_get(result, "rec_texts", []))
    if line_index < len(line_texts):
        canonical_words = str(line_texts[line_index]).split()
        if len(canonical_words) == len(out):
            for item, canonical in zip(out, canonical_words):
                item["text"] = canonical

    return out


def _effective_cpu_threads() -> int:
    """Return a conservative thread count that respects container CPU quota."""
    override = os.getenv("OCR_CPU_THREADS")
    if override:
        value = int(override)
        if value < 1:
            raise ValueError("OCR_CPU_THREADS must be >= 1")
        return value

    affinity = None
    try:
        affinity = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass

    quota_cpus = None
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().strip().split()
        if quota != "max":
            quota_cpus = max(1, math.ceil(int(quota) / int(period)))
    except (OSError, ValueError, ZeroDivisionError):
        pass

    candidates = [x for x in (affinity, quota_cpus, os.cpu_count()) if x]
    return max(1, min(candidates)) if candidates else 1


def _run_paddle(image_path: Path, model: Any) -> dict[str, Any]:
    from PIL import Image

    with Image.open(image_path) as image:
        width, height = image.size
        dpi = image.info.get("dpi", (300, 300))

    started = time.monotonic()
    result = list(model.predict(str(image_path), return_word_box=True))
    inference_seconds = time.monotonic() - started

    if not result:
        return {
            "width": width,
            "height": height,
            "dpi": _jsonable(dpi),
            "lines": [],
            "text": "",
            "performance": {"inference_seconds": round(inference_seconds, 3)},
        }

    page = result[0]
    texts = _seq(_result_get(page, "rec_texts", []))
    scores = _seq(_result_get(page, "rec_scores", []))
    polys = _seq(_result_get(page, "rec_polys", []))

    lines: list[dict[str, Any]] = []
    plain_lines: list[str] = []
    for index, (text_raw, score_raw, poly_raw) in enumerate(zip(texts, scores, polys)):
        text = str(text_raw).strip()
        if not text:
            continue
        try:
            score = float(score_raw)
        except (TypeError, ValueError):
            score = 0.0
        poly = _poly(poly_raw)
        if len(poly) < 4:
            continue
        lines.append(
            {
                "text": text,
                "score": score,
                "poly": poly,
                "words": _line_words(page, index),
            }
        )
        plain_lines.append(text)

    return {
        "width": width,
        "height": height,
        "dpi": _jsonable(dpi),
        "lines": lines,
        "text": "\n".join(plain_lines),
        "performance": {"inference_seconds": round(inference_seconds, 3)},
    }


def _engine_process(conn: Any, ocr_config: dict[str, str]) -> None:
    # Import Paddle only in the short-lived inference process. When this process
    # exits after the warm-session timeout, all Paddle allocations are returned
    # to the OS before Ollama is allowed to acquire the shared AI lock.
    from paddleocr import PaddleOCR

    language = ocr_config["language"]
    version = ocr_config["version"]
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
    if version == "PP-OCRv6":
        # Pin the exact quality tier instead of relying on PaddleOCR defaults.
        model_kwargs.update(
            text_detection_model_name=PP_OCRV6_MEDIUM_DET,
            text_recognition_model_name=PP_OCRV6_MEDIUM_REC,
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
            "device": device,
            "cpu_threads": cpu_threads,
            "enable_mkldnn": True,
            "enable_hpi": enable_hpi,
            "text_detection_model": PP_OCRV6_MEDIUM_DET if version == "PP-OCRv6" else None,
            "text_recognition_model": PP_OCRV6_MEDIUM_REC if version == "PP-OCRv6" else None,
        }
    )

    while True:
        request = conn.recv()
        if request.get("cmd") == "shutdown":
            return
        request_id = request["request_id"]
        image_path = Path(request["image_path"])
        try:
            payload = _run_paddle(image_path, model)
            payload.update(
                {
                    "language": language,
                    "ocr_version": version,
                    "device": device,
                }
            )
            conn.send({"type": "result", "request_id": request_id, "payload": payload})
        except Exception as exc:
            conn.send(
                {
                    "type": "error",
                    "request_id": request_id,
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )


class PaddleSession:
    def __init__(self) -> None:
        self._mutex = threading.RLock()
        self._ctx = mp.get_context("spawn")
        self._process: mp.Process | None = None
        self._conn: Any | None = None
        self._lock_file: Any | None = None
        self._last_used = 0.0
        self._started_at = 0.0
        self._config: dict[str, str] | None = None
        self._stop_event = threading.Event()
        self._housekeeper = threading.Thread(target=self._housekeeping_loop, daemon=True)
        self._housekeeper.start()

    @property
    def active(self) -> bool:
        # Internal worker-process liveness.
        return self._process is not None and self._process.is_alive()

    @property
    def session_active(self) -> bool:
        # External session state follows ownership of the global AI slot.
        # During _stop(), the worker may already be gone while ai.lock is
        # still held for process join/cleanup.
        return self._lock_file is not None

    @property
    def age_seconds(self) -> float | None:
        if not self.session_active or self._started_at <= 0:
            return None
        return round(time.monotonic() - self._started_at, 1)

    def _acquire_global_lock(self) -> float:
        AI_LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
        lock_file = AI_LOCK_FILE.open("a+")
        wait_started = time.monotonic()
        LOG.info("Waiting for global AI lock")
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        wait_seconds = time.monotonic() - wait_started
        LOG.info("Global AI lock acquired after %.2fs", wait_seconds)
        self._lock_file = lock_file
        return wait_seconds

    def _release_global_lock(self) -> None:
        if self._lock_file is None:
            return
        try:
            fcntl.flock(self._lock_file.fileno(), fcntl.LOCK_UN)
        finally:
            self._lock_file.close()
            self._lock_file = None
        LOG.info("Global AI lock released")

    def _current_ocr_config(self) -> dict[str, str]:
        ocr = load_app_config()["ocr"]
        return {
            "language": str(ocr["language"]),
            "version": str(ocr["version"]),
            "device": str(ocr["device"]),
        }

    def _start(self) -> float:
        lock_wait = self._acquire_global_lock()
        parent_conn, child_conn = self._ctx.Pipe()
        config = self._current_ocr_config()
        process = self._ctx.Process(target=_engine_process, args=(child_conn, config), daemon=True)
        process.start()
        child_conn.close()
        try:
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

        self._process = process
        self._conn = parent_conn
        self._config = config
        self._started_at = time.monotonic()
        self._last_used = self._started_at
        LOG.info(
            "PaddleOCR session ready in %.2fs: language=%s version=%s device=%s cpu_threads=%s",
            float(ready.get("load_seconds", 0.0)),
            config["language"],
            config["version"],
            config["device"],
            ready.get("cpu_threads"),
        )
        return lock_wait

    def _stop(self, reason: str) -> None:
        process = self._process
        conn = self._conn
        self._process = None
        self._conn = None
        self._config = None
        try:
            if process is not None:
                if process.is_alive():
                    try:
                        if conn is not None:
                            conn.send({"cmd": "shutdown"})
                    except Exception:
                        pass
                process.join(timeout=8)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=5)
        finally:
            if conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass
            self._release_global_lock()
            self._started_at = 0.0
            self._last_used = 0.0
        LOG.info("PaddleOCR session stopped (%s)", reason)

    def _raise_worker_ipc_failure(self, action: str, exc: BaseException) -> None:
        process = self._process
        exitcode = process.exitcode if process is not None else None
        reason = (
            f"Paddle worker IPC {action} failed "
            f"({type(exc).__name__}, exitcode={exitcode})"
        )
        self._stop(reason)
        raise RuntimeError(reason) from exc

    def ocr(self, image_path: Path) -> dict[str, Any]:
        with self._mutex:
            config = self._current_ocr_config()
            lock_wait = 0.0
            started_new_session = False

            # A worker may have been killed outside Python (for example by the
            # kernel OOM killer). Never carry a dead process together with the
            # global AI lock into the next request.
            if self.session_active and not self.active:
                self._stop("stale Paddle worker session")
            if self.active and config != self._config:
                self._stop("OCR configuration changed")
            if not self.active:
                lock_wait = self._start()
                started_new_session = True

            assert self._conn is not None
            assert self._process is not None
            request_id = uuid.uuid4().hex
            try:
                self._conn.send(
                    {
                        "cmd": "ocr",
                        "request_id": request_id,
                        "image_path": str(image_path),
                    }
                )
            except (EOFError, OSError, ValueError) as exc:
                self._raise_worker_ipc_failure("send", exc)

            deadline = time.monotonic() + PAGE_TIMEOUT_SECONDS
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self._stop(f"OCR page timeout after {PAGE_TIMEOUT_SECONDS:.0f}s")
                    raise TimeoutError(
                        f"Paddle OCR page exceeded {PAGE_TIMEOUT_SECONDS:.0f}s"
                    )

                try:
                    has_response = self._conn.poll(min(1.0, remaining))
                except (EOFError, OSError, ValueError) as exc:
                    self._raise_worker_ipc_failure("poll", exc)

                if has_response:
                    try:
                        response = self._conn.recv()
                    except (EOFError, OSError, ValueError) as exc:
                        self._raise_worker_ipc_failure("receive", exc)
                    break

                if not self._process.is_alive():
                    exitcode = self._process.exitcode
                    self._stop(f"Paddle worker exited unexpectedly ({exitcode})")
                    raise RuntimeError(
                        f"Paddle worker exited unexpectedly with code {exitcode}"
                    )

            self._last_used = time.monotonic()
            if response.get("request_id") != request_id:
                self._stop("IPC protocol error")
                raise RuntimeError("Paddle worker returned mismatched request ID")
            if response.get("type") == "error":
                raise RuntimeError(response.get("error", "Paddle OCR failed"))
            if response.get("type") != "result":
                raise RuntimeError(f"Unexpected Paddle worker response: {response!r}")

            payload = response["payload"]
            payload.setdefault("performance", {})["lock_wait_seconds"] = round(lock_wait, 3)
            payload["performance"]["warm_session"] = not started_new_session
            return payload

    def _housekeeping_loop(self) -> None:
        while not self._stop_event.wait(1.0):
            with self._mutex:
                if self.session_active and not self.active:
                    self._stop("Paddle worker no longer alive")
                elif self.active and time.monotonic() - self._last_used >= SESSION_IDLE_SECONDS:
                    self._stop(f"idle for {SESSION_IDLE_SECONDS:.0f}s")

    def close(self) -> None:
        self._stop_event.set()
        with self._mutex:
            if (
                self._process is not None
                or self._conn is not None
                or self._lock_file is not None
            ):
                self._stop("service shutdown")


SESSION: PaddleSession | None = None


def _session() -> PaddleSession:
    if SESSION is None:
        raise RuntimeError("OCR service session is not initialized")
    return SESSION


def sync_integration_plugin() -> None:
    INTEGRATION_TARGET.parent.mkdir(parents=True, exist_ok=True)
    if INTEGRATION_SOURCE.exists() and INTEGRATION_SOURCE.resolve() != INTEGRATION_TARGET.resolve():
        tmp = INTEGRATION_TARGET.with_suffix(".py.tmp")
        shutil.copyfile(INTEGRATION_SOURCE, tmp)
        os.replace(tmp, INTEGRATION_TARGET)
    elif not INTEGRATION_TARGET.exists():
        raise RuntimeError(
            f"OCRmyPDF plugin missing: source={INTEGRATION_SOURCE} target={INTEGRATION_TARGET}"
        )
    INTEGRATION_TARGET.chmod(0o644)
    LOG.info("OCRmyPDF bridge ready at %s", INTEGRATION_TARGET)


class Handler(BaseHTTPRequestHandler):
    server_version = "paperless-local-ai-ocr/0.2"

    def log_message(self, fmt: str, *args: Any) -> None:
        LOG.info("%s - %s", self.address_string(), fmt % args)

    def _json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return bool(TOKEN) and hmac.compare_digest(
            self.headers.get("Authorization", ""),
            f"Bearer {TOKEN}",
        )

    def do_GET(self) -> None:  # noqa: N802
        if self.path != "/health":
            self._json(404, {"error": "not_found"})
            return
        cfg = load_app_config()["ocr"]
        self._json(
            200,
            {
                "ok": True,
                "language": cfg["language"],
                "ocr_version": cfg["version"],
                "device": cfg["device"],
                "session_active": _session().session_active,
                "session_age_seconds": _session().age_seconds,
                "session_idle_seconds": SESSION_IDLE_SECONDS,
                "page_timeout_seconds": PAGE_TIMEOUT_SECONDS,
                "tmp_dir": str(TMP_DIR),
                "model_profile": "medium" if cfg["version"] == "PP-OCRv6" else "upstream-default",
                "text_detection_model": PP_OCRV6_MEDIUM_DET if cfg["version"] == "PP-OCRv6" else None,
                "text_recognition_model": PP_OCRV6_MEDIUM_REC if cfg["version"] == "PP-OCRv6" else None,
                "enable_hpi": _env_bool("OCR_ENABLE_HPI", False),
            },
        )

    def do_POST(self) -> None:  # noqa: N802
        if self.path != "/v1/ocr":
            self._json(404, {"error": "not_found"})
            return
        if not self._authorized():
            self._json(401, {"error": "unauthorized"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_REQUEST_BYTES:
            self._json(413, {"error": "invalid_content_length"})
            return

        cfg = load_app_config()["ocr"]
        requested_language = self.headers.get("X-PLAI-Language", "")
        if not _language_header_matches(requested_language, str(cfg["language"])):
            self._json(
                400,
                {
                    "error": "ocr_language_mismatch",
                    "configured_language": cfg["language"],
                },
            )
            return

        suffix = Path(self.headers.get("X-PLAI-Filename", "page.png")).suffix.lower()
        if suffix not in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp"}:
            suffix = ".png"

        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=TMP_DIR, suffix=suffix, delete=False) as tmp:
                remaining = length
                while remaining:
                    chunk = self.rfile.read(min(1024 * 1024, remaining))
                    if not chunk:
                        raise RuntimeError("OCR request body ended before Content-Length")
                    tmp.write(chunk)
                    remaining -= len(chunk)
                temp_path = Path(tmp.name)
            payload = _session().ocr(temp_path)
            self._json(200, payload)
        except Exception as exc:
            LOG.exception("OCR request failed")
            self._json(500, {"error": "ocr_failed", "detail": f"{type(exc).__name__}: {exc}"})
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def main() -> None:
    global SESSION
    if not TOKEN:
        raise RuntimeError("OCR_SERVICE_TOKEN must be set")
    TMP_DIR.mkdir(parents=True, exist_ok=True)
    sync_integration_plugin()
    SESSION = PaddleSession()
    LOG.info("Starting PaddleOCR service on %s:%d", HOST, PORT)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        if SESSION is not None:
            SESSION.close()


if __name__ == "__main__":
    main()
