from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from urllib.parse import urlparse


LOG = logging.getLogger("paperless_local_ai_ui")
STATE_FILE = Path(
    os.getenv(
        "PLAI_PAPERLESS_UI_STATE_FILE",
        "/opt/paperless-local-ai/paperless-local-ai-ui.json",
    )
)
MARKER = b"data-paperless-local-ai-ui"


def integration_state() -> dict | None:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None
    value = raw.get("control_center_url")
    if not isinstance(value, str):
        return None
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return {"enabled": True, "control_center_url": value}


def _asset_tags(request=None) -> bytes:
    prefix = ""
    if request is not None:
        path = str(getattr(request, "path", "") or "")
        path_info = str(getattr(request, "path_info", "") or "")
        if path_info and path.endswith(path_info):
            prefix = path[: -len(path_info)]
        elif isinstance(getattr(request, "META", None), dict):
            prefix = str(request.META.get("SCRIPT_NAME", "") or "")
    prefix = "/" + prefix.strip("/") if prefix.strip("/") else ""
    asset_base = f"{prefix}/_plai/assets"
    return (
        f'<script src="{asset_base}/chat.js" defer data-paperless-local-ai-ui></script>'
    ).encode("utf-8")


def inject_response(response, request=None):
    try:
        if getattr(response, "streaming", False):
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response
        if response.get("Content-Encoding", ""):
            # The middleware is normally inside Paperless' compression layer.
            # Fail open if a future stack returns already-compressed HTML here.
            return response
        if integration_state() is None:
            return response

        content = response.content
        if MARKER in content or b"</body>" not in content:
            return response
        response.content = content.replace(
            b"</body>",
            b"\n" + _asset_tags(request) + b"\n</body>",
            1,
        )
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
    except Exception:
        LOG.exception(
            "paperless-local-ai UI injection failed; leaving Paperless response unchanged"
        )
    return response
