from __future__ import annotations

import fcntl
import json
import os
import select
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from history_common import (
    HISTORY_BROKER_SOCKET,
    HISTORY_PROTOCOL_MAX_BYTES,
)


HISTORY_ENGINE_IDLE_SECONDS = float(os.getenv("PLAI_HISTORY_ENGINE_IDLE_SECONDS", "30"))
HISTORY_ENGINE_TIMEOUT_SECONDS = float(os.getenv("PLAI_HISTORY_ENGINE_TIMEOUT_SECONDS", "900"))
HISTORY_ENGINE_SHUTDOWN_TIMEOUT_SECONDS = float(
    os.getenv("PLAI_HISTORY_ENGINE_SHUTDOWN_TIMEOUT_SECONDS", "5")
)
AI_LOCK_FILE = Path(os.getenv("PLAI_AI_LOCK_FILE", "/coordination/ai.lock"))


def log(message: str) -> None:
    print(f"[HISTORY-BROKER] {message}", flush=True)


def _recv_json_line(conn: socket.socket, max_bytes: int) -> dict[str, Any]:
    chunks = bytearray()
    while True:
        chunk = conn.recv(min(65536, max_bytes - len(chunks) + 1))
        if not chunk:
            break
        chunks.extend(chunk)
        newline = chunks.find(b"\n")
        if newline >= 0:
            chunks = chunks[:newline]
            break
        if len(chunks) > max_bytes:
            raise RuntimeError("History broker request exceeded the protocol limit")
    if not chunks:
        raise RuntimeError("History broker received an empty request")
    payload = json.loads(chunks.decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("History broker request must be a JSON object")
    return payload


def _send_json_line(conn: socket.socket, payload: dict[str, Any]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
    if len(encoded) > HISTORY_PROTOCOL_MAX_BYTES:
        raise RuntimeError("History broker response exceeded the protocol limit")
    conn.sendall(encoded)


class HistoryBroker:
    """Lightweight broker that owns the on-demand scientific history process."""

    def __init__(
        self,
        *,
        socket_path: Path | None = None,
        engine_script: Path | None = None,
        idle_seconds: float = HISTORY_ENGINE_IDLE_SECONDS,
        engine_timeout_seconds: float = HISTORY_ENGINE_TIMEOUT_SECONDS,
        shutdown_timeout_seconds: float = HISTORY_ENGINE_SHUTDOWN_TIMEOUT_SECONDS,
        ai_lock_path: Path | None = None,
    ) -> None:
        self.socket_path = socket_path or HISTORY_BROKER_SOCKET
        self.engine_script = engine_script or Path(__file__).with_name("history_engine.py")
        self.idle_seconds = max(0.0, float(idle_seconds))
        self.engine_timeout_seconds = max(1.0, float(engine_timeout_seconds))
        self.shutdown_timeout_seconds = max(0.5, float(shutdown_timeout_seconds))
        self.ai_lock_path = ai_lock_path or AI_LOCK_FILE
        self._server: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._engine: subprocess.Popen[str] | None = None
        self._last_engine_use = 0.0
        self._engine_lock = threading.RLock()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)
        self.socket_path.unlink(missing_ok=True)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        server.bind(str(self.socket_path))
        try:
            self.socket_path.chmod(0o600)
        except OSError:
            pass
        server.listen(8)
        server.settimeout(1.0)
        self._server = server
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._serve,
            name="paperless-local-ai-history-broker",
            daemon=True,
        )
        self._thread.start()
        log(f"ready on {self.socket_path}")

    def stop(self) -> None:
        self._stop_event.set()
        server = self._server
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2.0)
        with self._engine_lock:
            self._stop_engine_locked()
        self.socket_path.unlink(missing_ok=True)

    def _engine_env(self) -> dict[str, str]:
        env = os.environ.copy()
        # The measured TF-IDF workload does not benefit from native fan-out on
        # modest CPUs. One thread avoids oversubscription and extra thread stacks.
        for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "BLIS_NUM_THREADS"):
            env[name] = "1"
        env["PYTHONUNBUFFERED"] = "1"
        return env

    def _start_engine_locked(self) -> subprocess.Popen[str]:
        process = self._engine
        if process is not None and process.poll() is None:
            return process
        if process is not None:
            self._reap_engine_locked()
        process = subprocess.Popen(
            [sys.executable, str(self.engine_script)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            bufsize=1,
            close_fds=True,
            env=self._engine_env(),
        )
        if process.stdin is None or process.stdout is None:
            process.kill()
            process.wait(timeout=2)
            raise RuntimeError("History engine pipes could not be created")
        self._engine = process
        self._last_engine_use = time.monotonic()
        log(f"started engine pid={process.pid}")
        return process

    def _reap_engine_locked(self) -> None:
        process = self._engine
        if process is None:
            return
        try:
            process.wait(timeout=0)
        except subprocess.TimeoutExpired:
            return
        finally:
            if process.poll() is not None:
                self._engine = None

    def _read_engine_response_locked(
        self,
        process: subprocess.Popen[str],
        *,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        assert process.stdout is not None
        ready, _, _ = select.select(
            [process.stdout.fileno()],
            [],
            [],
            self.engine_timeout_seconds if timeout is None else timeout,
        )
        if not ready:
            effective_timeout = self.engine_timeout_seconds if timeout is None else timeout
            raise TimeoutError(
                f"History engine did not respond within {effective_timeout:g} seconds"
            )
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(f"History engine exited with code {process.poll()}")
        payload = json.loads(line)
        if not isinstance(payload, dict):
            raise RuntimeError("History engine returned a non-object response")
        return payload

    def _engine_request_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
        process = self._start_engine_locked()
        assert process.stdin is not None
        process.stdin.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
        process.stdin.flush()
        response = self._read_engine_response_locked(process)
        self._last_engine_use = time.monotonic()
        return response

    def _stop_engine_locked(self) -> None:
        process = self._engine
        if process is None:
            return
        if process.poll() is not None:
            self._reap_engine_locked()
            return
        try:
            assert process.stdin is not None
            process.stdin.write('{"op":"shutdown"}\n')
            process.stdin.flush()
            self._read_engine_response_locked(
                process, timeout=self.shutdown_timeout_seconds
            )
            process.wait(timeout=self.shutdown_timeout_seconds)
        except Exception:
            # The helper owns no parent-process locks or shared Python objects;
            # terminate is only the recovery path if graceful shutdown failed.
            process.terminate()
            try:
                process.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2.0)
        finally:
            log(f"stopped engine pid={process.pid}")
            self._engine = None

    def _request_engine(self, payload: dict[str, Any]) -> dict[str, Any]:
        # Retry once if a warm helper died between requests.
        for attempt in range(2):
            with self._engine_lock:
                try:
                    return self._engine_request_locked(payload)
                except Exception:
                    self._stop_engine_locked()
                    if attempt:
                        raise
        raise RuntimeError("History engine request failed")

    def _maybe_idle_stop(self) -> None:
        with self._engine_lock:
            process = self._engine
            if process is None:
                return
            if process.poll() is not None:
                self._reap_engine_locked()
                return
            if self.idle_seconds <= 0 or time.monotonic() - self._last_engine_use >= self.idle_seconds:
                self._stop_engine_locked()

    @contextmanager
    def _ai_resource_lock(self):
        self.ai_lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.ai_lock_path.open("a+") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _handle_connection(self, conn: socket.socket) -> None:
        try:
            conn.settimeout(self.engine_timeout_seconds + 5.0)
            request = _recv_json_line(conn, HISTORY_PROTOCOL_MAX_BYTES)
            shutdown_after = bool(request.pop("shutdown_after", False))
            if request.get("op") == "release":
                with self._engine_lock:
                    self._stop_engine_locked()
                _send_json_line(conn, {"ok": True, "result": {"released": True}})
                return
            # The broker owns serialization for the scientific helper. This
            # keeps all callers safe against overlap with OCR/Ollama without
            # relying on every client to remember the shared AI lock.
            with self._ai_resource_lock():
                response = self._request_engine(request)
                if shutdown_after:
                    with self._engine_lock:
                        self._stop_engine_locked()
            _send_json_line(conn, response)
        except Exception as exc:
            try:
                _send_json_line(conn, {"ok": False, "error": f"{type(exc).__name__}: {exc}"})
            except Exception:
                pass

    def _serve(self) -> None:
        assert self._server is not None
        server = self._server
        try:
            while not self._stop_event.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    self._maybe_idle_stop()
                    continue
                except OSError:
                    if self._stop_event.is_set():
                        break
                    raise
                with conn:
                    self._handle_connection(conn)
                self._maybe_idle_stop()
        finally:
            with self._engine_lock:
                self._stop_engine_locked()
            try:
                server.close()
            except OSError:
                pass
            self.socket_path.unlink(missing_ok=True)
