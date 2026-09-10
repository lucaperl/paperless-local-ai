from __future__ import annotations

import re
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
    assert "__RAG_CONFIG_DEFAULT_JSON__" not in html
    assert "__RAG_PROMPT_PLACEHOLDERS_JSON__" not in html
    assert "__RAG_QUERY_PLACEHOLDERS_JSON__" not in html
    assert "__RAG_DOCUMENT_PLACEHOLDERS_JSON__" not in html
    assert "__RAG_SOURCE_PLACEHOLDERS_JSON__" not in html
    assert "__RAG_ANSWER_PLACEHOLDERS_JSON__" not in html
    assert 'path === "/api/control/rag/bootstrap"' in html
    assert 'path === "/api/control/rag/config"' in html
    assert 'path === "/api/control/rag/index/sync"' in html
    assert 'path === "/api/control/rag/index/rebuild"' in html
    assert 'path === "/api/control/rag/index/pause"' in html


def test_demo_mock_has_no_network_client():
    source = (ROOT / "demo" / "mock-api.js").read_text(encoding="utf-8")
    assert "fetch(" not in source
    assert "XMLHttpRequest" not in source
    assert "WebSocket(" not in source


def test_demo_rag_state_uses_only_synthetic_fixtures():
    source = (ROOT / "demo" / "mock-api.js").read_text(encoding="utf-8")

    # RAG configuration comes from public project defaults at demo build time.
    assert "const RAG_DEFAULT = __RAG_CONFIG_DEFAULT_JSON__;" in source

    # Demo index state is derived exclusively from the existing synthetic
    # DOCUMENTS fixture, never from real archive counts or copied runtime state.
    assert "const documentCount = Object.keys(DOCUMENTS).length;" in source
    assert "indexed_documents: documentCount" in source
    assert "indexed_chunks: documentCount * 3" in source
    assert "demo: true" in source
    assert "last_sync: stamp" in source
    assert "last_build: stamp" in source

    # Never copy archive-specific counts into the public demo.
    assert re.search(r"indexed_(?:documents|chunks)\\s*:\\s*\\d+", source) is None

    # Never embed a private LAN address from a real installation.
    private_ipv4 = re.compile(
        r"\\b(?:"
        r"10(?:\\.\\d{1,3}){3}|"
        r"192\\.168(?:\\.\\d{1,3}){2}|"
        r"172\\.(?:1[6-9]|2\\d|3[01])(?:\\.\\d{1,3}){2}"
        r")\\b"
    )
    assert private_ipv4.search(source) is None

    # All Control Center RAG admin calls are handled by the browser-only mock.
    for endpoint in (
        "/api/control/rag/bootstrap",
        "/api/control/rag/config",
        "/api/control/rag/index/sync",
        "/api/control/rag/index/rebuild",
        "/api/control/rag/index/pause",
    ):
        assert endpoint in source
