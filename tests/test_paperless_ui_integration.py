from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace


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


def _injection(tmp_path, monkeypatch):
    state = tmp_path / "paperless-local-ai-ui.json"
    monkeypatch.setenv("PLAI_PAPERLESS_UI_STATE_FILE", str(state))
    sys.modules.pop("paperless_local_ai_ui.injection", None)
    module = importlib.import_module("paperless_local_ai_ui.injection")
    module.STATE_FILE = state
    return module, state


def test_disabled_is_noop(tmp_path, monkeypatch):
    module, state = _injection(tmp_path, monkeypatch)
    state.write_text(json.dumps({"enabled": False, "control_center_url": "https://plai.example/"}))
    response = Response()
    original = response.content
    assert module.inject_response(response).content == original


def test_enabled_injects_external_chat_asset(tmp_path, monkeypatch):
    module, state = _injection(tmp_path, monkeypatch)
    state.write_text(json.dumps({"enabled": True, "control_center_url": "https://plai.example/"}))
    response = Response()
    module.inject_response(response)
    text = response.content.decode()
    assert "data-paperless-local-ai-ui" in text
    assert 'src="/_plai/assets/chat.js"' in text
    assert "documents.views" not in Path(module.__file__).read_text(encoding="utf-8")
    assert response.headers["Content-Length"] == str(len(response.content))


def test_subpath_asset_url_uses_request_prefix(tmp_path, monkeypatch):
    module, state = _injection(tmp_path, monkeypatch)
    state.write_text(json.dumps({"enabled": True, "control_center_url": "https://plai.example/"}))
    response = Response()
    request = SimpleNamespace(path="/paperless/documents/1/details", path_info="/documents/1/details", META={})
    module.inject_response(response, request)
    assert 'src="/paperless/_plai/assets/chat.js"' in response.content.decode()


def test_compressed_html_fails_open(tmp_path, monkeypatch):
    module, state = _injection(tmp_path, monkeypatch)
    state.write_text(json.dumps({"enabled": True, "control_center_url": "https://plai.example/"}))
    response = Response()
    response.headers["Content-Encoding"] = "gzip"
    original = response.content
    assert module.inject_response(response).content == original


def test_invalid_url_fails_closed(tmp_path, monkeypatch):
    module, state = _injection(tmp_path, monkeypatch)
    state.write_text(json.dumps({"enabled": True, "control_center_url": "javascript:alert(1)"}))
    response = Response()
    original = response.content
    assert module.inject_response(response).content == original


def test_middleware_is_fail_open_and_marks_normal_responses(monkeypatch):
    injection = importlib.import_module("paperless_local_ai_ui.injection")
    relay = ModuleType("paperless_local_ai_ui.relay")
    relay.handle = lambda _request: None
    monkeypatch.setitem(sys.modules, "paperless_local_ai_ui.relay", relay)
    sys.modules.pop("paperless_local_ai_ui.middleware", None)
    module = importlib.import_module("paperless_local_ai_ui.middleware")
    monkeypatch.setattr(injection, "inject_response", lambda response, _request=None: response)

    response = Response(content=b"")
    middleware = module.PaperlessLocalAiUiMiddleware(lambda _request: response)
    result = middleware(SimpleNamespace(path_info="/documents/"))
    assert result is response
    assert result.headers["X-Paperless-Local-AI-UI"] == "ready"


def test_runtime_assets_do_not_embed_a_control_center_origin():
    script = (ROOT / "src/ocr/paperless_local_ai_ui/assets/chat.js").read_text(encoding="utf-8")
    assert "192.168." not in script
    assert "http://" not in script
    assert "https://" not in script
    assert "_plai/" in script
    assert "#chatDropdown" not in script  # selector uses getElementById, avoiding CSS coupling
    assert 'getElementById("chatDropdown")' in script
    assert "sessionStorage" not in script
    assert "conversations/create" in script
    assert "aria-expanded" in script
