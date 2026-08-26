from __future__ import annotations

import logging

from django.apps import AppConfig
from django.core.signals import request_started


LOG = logging.getLogger("paperless_local_ai_ui")
_ATTACH_UID = "paperless_local_ai_ui.attach_index_view"


def _attach_to_index_view(**_kwargs) -> None:
    # Delay importing Paperless views until an actual HTTP request arrives.
    # Celery/background processes load the tiny Django app but never pull in
    # the web view solely for this optional integration.
    request_started.disconnect(_attach_to_index_view, dispatch_uid=_ATTACH_UID)
    try:
        from documents.views import IndexView

        from .injection import patch_index_view

        patch_index_view(IndexView)
    except Exception:
        LOG.exception(
            "paperless-local-ai UI integration could not attach; "
            "Paperless will continue without the shortcut"
        )


class PaperlessLocalAiUiConfig(AppConfig):
    name = "paperless_local_ai_ui"
    verbose_name = "paperless-local-ai UI integration"

    def ready(self) -> None:
        request_started.connect(
            _attach_to_index_view,
            weak=False,
            dispatch_uid=_ATTACH_UID,
        )
