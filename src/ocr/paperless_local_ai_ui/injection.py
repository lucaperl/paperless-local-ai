from __future__ import annotations

import json
import logging
import os
from functools import wraps
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


def _control_center_url() -> str | None:
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None

    if not isinstance(raw, dict) or raw.get("enabled") is not True:
        return None
    value = raw.get("control_center_url")
    if not isinstance(value, str):
        return None
    value = value.strip()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _script(control_center_url: str) -> bytes:
    # This JSON literal is embedded in an inline <script>. Escape HTML-significant
    # characters so even a manually edited URL containing </script> cannot break
    # out of the script element.
    target = (
        json.dumps(control_center_url, ensure_ascii=False)
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
    )
    return f'''<script data-paperless-local-ai-ui>
(() => {{
  const id = "paperless-local-ai-settings-link";
  const target = {target};
  const base = new URL(
    document.querySelector("base")?.getAttribute("href") || "/",
    window.location.origin
  ).pathname.replace(/\\/+$/, "");

  const relativePath = () => {{
    let path = window.location.pathname;
    if (base && path.startsWith(base)) path = path.slice(base.length);
    return path.replace(/^\\/+|\\/+$/g, "");
  }};

  const sync = () => {{
    const existing = document.getElementById(id);
    const path = relativePath();
    if (!(path === "settings" || path.startsWith("settings/"))) {{
      existing?.remove();
      return;
    }}

    const admin = [...document.querySelectorAll("a[href]")].find((link) => {{
      const href = link.getAttribute("href") || "";
      return href === "admin/" || href.endsWith("/admin/");
    }});
    if (!admin) {{
      existing?.remove();
      return;
    }}
    if (existing) return;

    const link = document.createElement("a");
    link.id = id;
    link.className = "btn btn-sm btn-outline-primary me-1";
    link.href = target;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = "Open paperless-local-ai";
    link.append(document.createTextNode("paperless-local-ai"));

    const arrow = document.createElement("span");
    arrow.className = "ms-2";
    arrow.setAttribute("aria-hidden", "true");
    arrow.textContent = "↗";
    link.append(arrow);
    admin.parentNode?.insertBefore(link, admin);
  }};

  new MutationObserver(sync).observe(document.documentElement, {{
    childList: true,
    subtree: true,
  }});
  window.addEventListener("popstate", sync);
  sync();
}})();
</script>'''.encode("utf-8")


def inject_response(response):
    try:
        if getattr(response, "streaming", False):
            return response
        if "text/html" not in response.get("Content-Type", ""):
            return response

        control_center_url = _control_center_url()
        if control_center_url is None:
            return response

        content = response.content
        if MARKER in content or b"</body>" not in content:
            return response
        response.content = content.replace(
            b"</body>",
            b"\n" + _script(control_center_url) + b"\n</body>",
            1,
        )
        if response.has_header("Content-Length"):
            response["Content-Length"] = str(len(response.content))
    except Exception:
        LOG.exception(
            "paperless-local-ai UI injection failed; leaving Paperless response unchanged"
        )
    return response


def patch_index_view(index_view) -> None:
    if getattr(index_view, "_paperless_local_ai_ui_patched", False):
        return

    original = index_view.render_to_response

    @wraps(original)
    def render_to_response(self, context, **response_kwargs):
        response = original(self, context, **response_kwargs)
        callback = getattr(response, "add_post_render_callback", None)
        if callback is not None:
            callback(inject_response)
        return response

    index_view.render_to_response = render_to_response
    index_view._paperless_local_ai_ui_patched = True
