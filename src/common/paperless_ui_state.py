from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse


STATE_FILE = Path(
    os.getenv("PLAI_PAPERLESS_UI_STATE_FILE", "/integration/paperless-local-ai-ui.json")
)
INTEGRATION_PACKAGE = Path("/integration/paperless_local_ai_ui/apps.py")


def _validate_url(value: str) -> str:
    value = str(value or "").strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("control_center_url must be a complete http(s) URL")
    return value


def projection(config: dict) -> dict:
    section = config.get("paperless_ui", {})
    enabled = section.get("enabled") is True
    url = str(section.get("control_center_url") or "").strip()
    if url:
        url = _validate_url(url)
    if enabled and not url:
        raise ValueError("paperless_ui.control_center_url is required when enabled")
    return {"enabled": enabled, "control_center_url": url}


def sync_projection(config: dict) -> dict:
    state = projection(config)
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_name(STATE_FILE.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, STATE_FILE)
    return state


def integration_package_ready() -> bool:
    return INTEGRATION_PACKAGE.is_file()
