from __future__ import annotations

from django.apps import AppConfig
from django.conf import settings


_MIDDLEWARE = "paperless_local_ai_ui.middleware.PaperlessLocalAiUiMiddleware"
_AUTH_MIDDLEWARE = "django.contrib.auth.middleware.AuthenticationMiddleware"


class PaperlessLocalAiUiConfig(AppConfig):
    name = "paperless_local_ai_ui"
    verbose_name = "paperless-local-ai UI integration"

    def ready(self) -> None:
        # Keep the integration behind AuthenticationMiddleware so relay requests
        # receive request.user, while remaining inside Paperless' optional outer
        # compression middleware so HTML injection happens before compression.
        middleware = list(settings.MIDDLEWARE)
        if _MIDDLEWARE in middleware:
            return
        try:
            index = middleware.index(_AUTH_MIDDLEWARE) + 1
        except ValueError:
            index = len(middleware)
        middleware.insert(index, _MIDDLEWARE)
        settings.MIDDLEWARE = middleware
