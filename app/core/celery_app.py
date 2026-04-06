from __future__ import annotations

import os

from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "pdf_converter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
    include=["app.workers.tasks"],
)

# Use "solo" pool in dev/test (no subprocess overhead), "prefork" in production.
_worker_pool = "solo" if os.getenv("ENVIRONMENT", "development") != "production" else "prefork"

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_track_started=True,
    task_ignore_result=False,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    worker_pool=_worker_pool,
    # Keep results for 24 h then expire to avoid Redis bloat
    result_expires=86400,
    # Dead-letter: tasks that exhaust retries land in a dedicated queue
    task_routes={
        "preview_transform_job": {"queue": "preview"},
    },
)
