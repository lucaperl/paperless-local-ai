from pathlib import Path

import core_service
import prompt_ui
import suggestion_bridge


ROOT = Path(__file__).resolve().parents[1]


def test_unified_core_can_bind_both_existing_http_handlers(monkeypatch):
    monkeypatch.setattr(prompt_ui, "HOST", "127.0.0.1")
    monkeypatch.setattr(prompt_ui, "PORT", 0)
    monkeypatch.setattr(suggestion_bridge, "HOST", "127.0.0.1")
    monkeypatch.setattr(suggestion_bridge, "PORT", 0)

    servers = core_service.build_servers()
    try:
        assert [name for name, _server in servers] == [
            "control-center",
            "suggestion-bridge",
        ]
        assert servers[0][1].RequestHandlerClass is prompt_ui.Handler
        assert (
            servers[1][1].RequestHandlerClass
            is suggestion_bridge.Handler
        )
    finally:
        for _name, server in servers:
            server.server_close()


def test_published_compose_uses_two_persistent_services():
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert "\n  core-service:\n" in compose
    assert "\n  ocr-service:\n" in compose

    assert "\n  metadata-worker:\n" not in compose
    assert "\n  prompt-ui:\n" not in compose
    assert "\n  suggestion-bridge:\n" not in compose

    assert ":8080" in compose
    assert ":8081" in compose
    assert ":8082" in compose


def test_core_image_defaults_to_unified_supervisor():
    dockerfile = (
        ROOT / "docker/core.Dockerfile"
    ).read_text(encoding="utf-8")

    assert 'CMD ["python", "/app/core_service.py"]' in dockerfile
