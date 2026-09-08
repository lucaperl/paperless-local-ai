from __future__ import annotations

import json
import logging
import mimetypes
import os
from pathlib import Path
from urllib import error, request

from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_protect

from .injection import integration_state


LOG = logging.getLogger("paperless_local_ai_ui")
SECRET_FILE = Path(
    os.getenv(
        "PLAI_PAPERLESS_UI_RELAY_SECRET_FILE",
        "/opt/paperless-local-ai/paperless-local-ai-relay.secret",
    )
)
ASSET_DIR = Path(__file__).resolve().parent / "assets"
MAX_REQUEST_BYTES = 256_000
MAX_RESPONSE_BYTES = 2_000_000

GET_ROUTES = {
    "bootstrap": "/api/rag/bootstrap",
    "status": "/api/rag/status",
    "models": "/api/rag/models",
}
POST_ROUTES = {
    "conversations": "/api/rag/conversations",
    "conversations/create": "/api/rag/conversations/create",
    "conversations/get": "/api/rag/conversations/get",
    "conversations/rename": "/api/rag/conversations/rename",
    "conversations/delete": "/api/rag/conversations/delete",
    "config": "/api/rag/config",
    "chat/start": "/api/rag/chat/start",
    "chat/status": "/api/rag/chat/status",
    "chat/stop": "/api/rag/chat/stop",
    "index/sync": "/api/rag/index/sync",
    "index/rebuild": "/api/rag/index/rebuild",
    "index/pause": "/api/rag/index/pause",
}


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = request.build_opener(_NoRedirect)


def _json_error(status: int, message: str):
    return JsonResponse({"error": message}, status=status)


def _authorized_user(req) -> bool:
    user = getattr(req, "user", None)
    return bool(user and user.is_authenticated and user.is_superuser)


def _secret() -> str | None:
    try:
        value = SECRET_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return value if len(value) >= 32 else None


def _asset(name: str):
    if name not in {"chat.js", "chat.css"}:
        return _json_error(404, "not found")
    path = ASSET_DIR / name
    if not path.is_file():
        return _json_error(503, "paperless-local-ai asset unavailable")
    content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    response = FileResponse(path.open("rb"), content_type=content_type)
    response["Cache-Control"] = "no-cache"
    return response


def _proxy(req, upstream_path: str, *, merge_bootstrap: bool = False):
    state = integration_state()
    secret = _secret()
    if state is None or secret is None:
        return _json_error(503, "paperless-local-ai integration is not ready")
    user = getattr(req, "user", None)
    user_id = getattr(user, "id", None)
    if not isinstance(user_id, int) or user_id <= 0:
        return _json_error(403, "paperless-local-ai could not resolve the Paperless user")
    body = b""
    if req.method == "POST":
        body = req.body
        if len(body) > MAX_REQUEST_BYTES:
            return _json_error(413, "request too large")
    upstream = state["control_center_url"] + upstream_path
    headers = {
        "Authorization": f"Bearer {secret}",
        "Accept": "application/json",
        "X-Paperless-User-Id": str(user_id),
    }
    username = getattr(user, "username", "")
    if username:
        headers["X-Paperless-Username"] = str(username)[:150]
    if body:
        headers["Content-Type"] = "application/json"
    upstream_request = request.Request(
        upstream,
        data=body if req.method == "POST" else None,
        headers=headers,
        method=req.method,
    )
    try:
        with _OPENER.open(upstream_request, timeout=60) as response:
            raw = response.read(MAX_RESPONSE_BYTES + 1)
            status = response.status
    except error.HTTPError as exc:
        raw = exc.read(MAX_RESPONSE_BYTES + 1)
        status = exc.code
    except (error.URLError, TimeoutError, OSError) as exc:
        LOG.warning("paperless-local-ai relay failed: %s", exc)
        return _json_error(502, "paperless-local-ai is unavailable")
    if len(raw) > MAX_RESPONSE_BYTES:
        return _json_error(502, "paperless-local-ai response too large")
    try:
        payload = json.loads(raw or b"{}")
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _json_error(502, "paperless-local-ai returned invalid JSON")
    if merge_bootstrap and isinstance(payload, dict):
        payload["control_center_url"] = state["control_center_url"]
    response = JsonResponse(payload, safe=isinstance(payload, dict), status=status)
    response["Cache-Control"] = "no-store"
    return response


@csrf_protect
def _post(req, route: str):
    upstream = POST_ROUTES.get(route)
    if upstream is None:
        return _json_error(404, "not found")
    return _proxy(req, upstream)


def handle(req):
    path = str(getattr(req, "path_info", ""))
    prefix = "/_plai/"
    if not path.startswith(prefix):
        return None
    route = path[len(prefix) :].strip("/")

    if route.startswith("assets/"):
        return _asset(route.split("/", 1)[1])

    if not _authorized_user(req):
        return _json_error(403, "paperless-local-ai RAG chat requires a Paperless superuser")

    if req.method == "GET":
        upstream = GET_ROUTES.get(route)
        if upstream is None:
            return _json_error(404, "not found")
        return _proxy(req, upstream, merge_bootstrap=route == "bootstrap")
    if req.method == "POST":
        return _post(req, route)
    return _json_error(405, "method not allowed")
