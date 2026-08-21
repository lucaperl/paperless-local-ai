import time

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
