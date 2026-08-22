import ocr_recovery_state as state


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
