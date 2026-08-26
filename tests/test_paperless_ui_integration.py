from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src" / "ocr"))


class Response:
    streaming = False

    def __init__(
        self,
        content=b"<html><body><pngx-root></pngx-root></body></html>",
        content_type="text/html; charset=utf-8",
    ):
        self.content = content
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(content)),
        }

    def get(self, key, default=None):
        return self.headers.get(key, default)

    def has_header(self, key):
        return key in self.headers

    def __setitem__(self, key, value):
        self.headers[key] = value


def _module(tmp_path, monkeypatch):
    state = tmp_path / "paperless-local-ai-ui.json"
    monkeypatch.setenv("PLAI_PAPERLESS_UI_STATE_FILE", str(state))
    sys.modules.pop("paperless_local_ai_ui.injection", None)
    module = importlib.import_module("paperless_local_ai_ui.injection")
    module.STATE_FILE = state
    return module, state


def test_disabled_is_noop(tmp_path, monkeypatch):
    module, state = _module(tmp_path, monkeypatch)
    state.write_text(
        json.dumps({"enabled": False, "control_center_url": "https://plai.example/"})
    )
    response = Response()
    original = response.content
    assert module.inject_response(response).content == original


def test_enabled_injects_settings_link_script(tmp_path, monkeypatch):
    module, state = _module(tmp_path, monkeypatch)
    state.write_text(
        json.dumps({"enabled": True, "control_center_url": "https://plai.example/"})
    )
    response = Response()
    module.inject_response(response)
    text = response.content.decode()
    assert "data-paperless-local-ai-ui" in text
    assert "paperless-local-ai-settings-link" in text
    assert 'document.createTextNode("paperless-local-ai")' in text
    assert "https://plai.example/" in text
    assert 'href === "admin/"' in text
    assert response.headers["Content-Length"] == str(len(response.content))


def test_invalid_url_fails_closed(tmp_path, monkeypatch):
    module, state = _module(tmp_path, monkeypatch)
    state.write_text(
        json.dumps({"enabled": True, "control_center_url": "javascript:alert(1)"})
    )
    response = Response()
    original = response.content
    assert module.inject_response(response).content == original


def test_embedded_url_cannot_break_out_of_script(tmp_path, monkeypatch):
    module, state = _module(tmp_path, monkeypatch)
    state.write_text(
        json.dumps(
            {
                "enabled": True,
                "control_center_url": "https://plai.example/</script><script>alert(1)</script>",
            }
        )
    )
    response = Response()
    module.inject_response(response)
    text = response.content.decode()
    assert "</script><script>alert(1)</script>" not in text
    assert "\\u003c/script\\u003e" in text



def _middleware_module(monkeypatch, *, attach_error: bool = False):
    injection = importlib.import_module("paperless_local_ai_ui.injection")

    documents = ModuleType("documents")
    documents.__path__ = []
    views = ModuleType("documents.views")

    class IndexView:
        pass

    views.IndexView = IndexView
    documents.views = views
    monkeypatch.setitem(sys.modules, "documents", documents)
    monkeypatch.setitem(sys.modules, "documents.views", views)

    attached = []

    if attach_error:
        def fail(_index_view):
            raise RuntimeError("attach failed")

        monkeypatch.setattr(injection, "patch_index_view", fail)
    else:
        monkeypatch.setattr(injection, "patch_index_view", attached.append)

    sys.modules.pop("paperless_local_ai_ui.middleware", None)
    module = importlib.import_module("paperless_local_ai_ui.middleware")
    return module, attached, IndexView


def test_middleware_marks_responses_after_successful_attach(monkeypatch):
    module, attached, index_view = _middleware_module(monkeypatch)
    response = Response(content=b"")

    middleware = module.PaperlessLocalAiUiMiddleware(lambda _request: response)
    result = middleware(None)

    assert attached == [index_view]
    assert result is response
    assert result.headers["X-Paperless-Local-AI-UI"] == "ready"


def test_middleware_does_not_claim_ready_when_attach_fails(monkeypatch):
    module, _attached, _index_view = _middleware_module(
        monkeypatch,
        attach_error=True,
    )
    response = Response(content=b"")

    middleware = module.PaperlessLocalAiUiMiddleware(lambda _request: response)
    result = middleware(None)

    assert result is response
    assert "X-Paperless-Local-AI-UI" not in result.headers
