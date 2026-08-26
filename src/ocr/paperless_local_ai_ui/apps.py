from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings


_MIDDLEWARE = "paperless_local_ai_ui.middleware.PaperlessLocalAiUiMiddleware"


class PaperlessLocalAiUiConfig(AppConfig):
    name = "paperless_local_ai_ui"
    verbose_name = "paperless-local-ai UI integration"

    def ready(self) -> None:
        # Register the integration as the outermost Django middleware. The
        # middleware itself is only instantiated by the web handler, so Celery
        # and other background processes do not import Paperless web views.
        if _MIDDLEWARE not in settings.MIDDLEWARE:
            settings.MIDDLEWARE = [_MIDDLEWARE, *settings.MIDDLEWARE]
