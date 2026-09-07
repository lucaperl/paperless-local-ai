from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


LOG = logging.getLogger("paperless_local_ai_ui")
READY_HEADER = "X-Paperless-Local-AI-UI"


class PaperlessLocalAiUiMiddleware:
    """Fail-open Paperless HTML injection plus authenticated same-origin relay."""

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response
        self.ready = False
        try:
            from .injection import inject_response
            from .relay import handle

            self._inject_response = inject_response
            self._relay = handle
            self.ready = True
        except Exception:
            LOG.exception(
                "paperless-local-ai UI integration could not initialize; "
                "Paperless will continue without the integration"
            )

    def __call__(self, request: Any) -> Any:
        if self.ready and str(getattr(request, "path_info", "")).startswith("/_plai/"):
            try:
                response = self._relay(request)
                if response is not None:
                    response[READY_HEADER] = "ready"
                    return response
            except Exception:
                LOG.exception("paperless-local-ai relay failed")

        response = self.get_response(request)
        if self.ready:
            response = self._inject_response(response, request)
            # The marker is independent of enabled state so the existing Control
            # Center readiness probe can verify that Paperless loaded the app.
            response[READY_HEADER] = "ready"
        return response
