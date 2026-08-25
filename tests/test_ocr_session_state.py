import fcntl
import threading
import time

import pytest

import service
from service import PaddleSession


def test_session_active_follows_global_lock_not_worker_liveness():
    session = PaddleSession.__new__(PaddleSession)

    # Exact alpha.4 teardown window:
    # worker state is already inactive, but ai.lock is still owned.
    session._process = None
    session._lock_file = object()
    session._started_at = time.monotonic() - 1.0

    assert session.active is False
    assert session.session_active is True
    assert session.age_seconds is not None

    session._lock_file = None

    assert session.session_active is False
    assert session.age_seconds is None


class _WorkerKilledDuringReceive:
    def __init__(self):
        self.alive = True
        self.exitcode = -9
        self.join_calls = 0
        self.terminate_calls = 0

    def is_alive(self):
        return self.alive

    def join(self, timeout=None):
        self.join_calls += 1

    def terminate(self):
        self.terminate_calls += 1
        self.alive = False


class _EOFConnection:
    def __init__(self, process):
        self.process = process
        self.closed = False
        self.sent = []

    def send(self, payload):
        self.sent.append(payload)

    def poll(self, timeout=None):
        return True

    def recv(self):
        self.process.alive = False
        raise EOFError

    def close(self):
        self.closed = True


def test_worker_eof_tears_down_session_and_releases_ai_lock(tmp_path):
    lock_path = tmp_path / "ai.lock"
    lock_file = lock_path.open("a+")
    fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    process = _WorkerKilledDuringReceive()
    conn = _EOFConnection(process)
    config = {
        "language": "de",
        "version": "PP-OCRv6",
        "model_profile": "medium",
        "device": "cpu",
    }

    session = PaddleSession.__new__(PaddleSession)
    session._mutex = threading.RLock()
    session._process = process
    session._conn = conn
    session._lock_file = lock_file
    session._last_used = time.monotonic()
    session._started_at = time.monotonic()
    session._config = config
    session._current_ocr_config = lambda: dict(config)
    session._recycle_event = threading.Event()

    with pytest.raises(RuntimeError, match="Paddle worker IPC receive failed"):
        session.ocr(tmp_path / "page.png")

    assert session._process is None
    assert session._conn is None
    assert session._lock_file is None
    assert session.session_active is False
    assert session.age_seconds is None
    assert conn.closed is True
    assert process.join_calls == 1
    assert process.terminate_calls == 0

    # A separate descriptor must be able to take the same lock immediately.
    with lock_path.open("a+") as probe:
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        fcntl.flock(probe.fileno(), fcntl.LOCK_UN)


class _AliveWorker:
    def is_alive(self):
        return True


class _OneHousekeepingTick:
    def __init__(self):
        self.calls = 0

    def wait(self, timeout):
        self.calls += 1
        return self.calls > 1


def test_idle_worker_stop_requests_container_recycle():
    session = PaddleSession.__new__(PaddleSession)
    session._mutex = threading.RLock()
    session._process = _AliveWorker()
    session._lock_file = object()
    session._last_used = time.monotonic() - service.SESSION_IDLE_SECONDS - 1.0
    session._recycle_event = threading.Event()
    session._stop_event = _OneHousekeepingTick()

    stopped = []
    session._stop = lambda reason: stopped.append(reason)

    session._housekeeping_loop()

    assert stopped == [f"idle for {service.SESSION_IDLE_SECONDS:.0f}s"]
    assert session._recycle_event.is_set()
