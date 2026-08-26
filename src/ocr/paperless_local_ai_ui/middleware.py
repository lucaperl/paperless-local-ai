from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any


LOG = logging.getLogger("paperless_local_ai_ui")
READY_HEADER = "X-Paperless-Local-AI-UI"


class PaperlessLocalAiUiMiddleware:
    # Attach the Paperless UI hook and expose functional readiness.

    def __init__(self, get_response: Callable[[Any], Any]) -> None:
        self.get_response = get_response
        self.ready = False
        try:
            from documents.views import IndexView

            from .injection import patch_index_view

            patch_index_view(IndexView)
            self.ready = True
        except Exception:
            LOG.exception(
                "paperless-local-ai UI integration could not attach; "
                "Paperless will continue without the shortcut"
            )

    def __call__(self, request: Any) -> Any:
        response = self.get_response(request)
        if self.ready:
            # The marker is intentionally independent of shortcut enabled state.
            # Being outermost also makes it visible on login redirects, allowing
            # an unauthenticated Control Center readiness probe to verify that
            # Paperless actually loaded and attached the integration.
            response[READY_HEADER] = "ready"
        return response
