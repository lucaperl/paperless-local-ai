from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_static_control_center_demo_builds(tmp_path):
    output = tmp_path / "demo"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_demo.py"),
            "--output",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    html = (output / "index.html").read_text(encoding="utf-8")

    assert "paperless-local-ai Control Center" in html
    assert "Demo mode" in html
    assert "4711 · History match" in html
    assert "4712 · LLM fallback" in html
    assert "4713 · conservative" in html
    assert "window.PLAI_DEMO.api" in html
    assert "connect-src 'none'" in html
    assert "fetch(path" not in html
    assert "__PROMPT_CONFIG_DEFAULT_JSON__" not in html
    assert "__APP_CONFIG_DEFAULT_JSON__" not in html
    assert "__TAGGING_DOCS_URL__" not in html
    assert "__PAPERLESS_SETUP_DOCS_URL__" not in html
    assert "__APP_VERSION__" not in html


def test_demo_mock_has_no_network_client():
    source = (ROOT / "demo" / "mock-api.js").read_text(encoding="utf-8")
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
    assert "WebSocket(" not in source
