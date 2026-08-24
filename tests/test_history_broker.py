from __future__ import annotations

import socket
import textwrap
import time
from pathlib import Path

import pytest

from history_broker import HistoryBroker
from history_common import history_broker_request


pytestmark = pytest.mark.skipif(
    not hasattr(socket, "AF_UNIX"),
    reason="History broker requires Unix-domain sockets",
)


def test_broker_reuses_warm_engine_and_shutdown_after_releases_it(tmp_path: Path):
    engine = tmp_path / "fake_history_engine.py"
    engine.write_text(
        textwrap.dedent(
            """
            import json
            import os
            import sys

            for line in sys.stdin:
                request = json.loads(line)
                if request.get("op") == "shutdown":
                    print(json.dumps({"ok": True, "result": {"shutdown": True}}), flush=True)
                    break
                print(
                    json.dumps(
                        {"ok": True, "result": {"pid": os.getpid(), "op": request.get("op")}}
                    ),
                    flush=True,
                )
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    socket_path = tmp_path / "history.sock"
    broker = HistoryBroker(
        socket_path=socket_path,
        engine_script=engine,
        idle_seconds=60,
        engine_timeout_seconds=5,
        shutdown_timeout_seconds=1,
        ai_lock_path=tmp_path / "ai.lock",
    )
    broker.start()
    try:
        first = history_broker_request({"op": "ping"}, socket_path=socket_path, timeout=5)
        second = history_broker_request({"op": "ping"}, socket_path=socket_path, timeout=5)
        assert first["pid"] == second["pid"]

        final_warm = history_broker_request(
            {"op": "ping", "shutdown_after": True},
            socket_path=socket_path,
            timeout=5,
        )
        assert final_warm["pid"] == first["pid"]

        replacement = history_broker_request({"op": "ping"}, socket_path=socket_path, timeout=5)
        assert replacement["pid"] != first["pid"]

        history_broker_request({"op": "release"}, socket_path=socket_path, timeout=5)
        with broker._engine_lock:
            assert broker._engine is None
    finally:
        broker.stop()


def test_broker_stops_engine_after_idle_timeout(tmp_path: Path):
    engine = tmp_path / "fake_history_engine.py"
    engine.write_text(
        "import json, os, sys\n"
        "for line in sys.stdin:\n"
        "    request=json.loads(line)\n"
        "    if request.get('op') == 'shutdown':\n"
        "        print(json.dumps({'ok':True,'result':{'shutdown':True}}), flush=True); break\n"
        "    print(json.dumps({'ok':True,'result':{'pid':os.getpid()}}), flush=True)\n",
        encoding="utf-8",
    )

    socket_path = tmp_path / "history.sock"
    broker = HistoryBroker(
        socket_path=socket_path,
        engine_script=engine,
        idle_seconds=0.2,
        engine_timeout_seconds=5,
        shutdown_timeout_seconds=1,
        ai_lock_path=tmp_path / "ai.lock",
    )
    broker.start()
    try:
        first = history_broker_request({"op": "ping"}, socket_path=socket_path, timeout=5)
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            with broker._engine_lock:
                if broker._engine is None:
                    break
            time.sleep(0.05)
        with broker._engine_lock:
            assert broker._engine is None

        second = history_broker_request({"op": "ping"}, socket_path=socket_path, timeout=5)
        assert second["pid"] != first["pid"]
    finally:
        broker.stop()
