from __future__ import annotations

import structlog

from app.core.celery_app import celery_app
from app.services.job_service import (
    load_job_file,
    mark_job_completed,
    mark_job_failed,
    mark_job_running,
)
from app.services.workflow_service import process_preview_workflow

log = structlog.get_logger(__name__)

# Transient infrastructure errors worth retrying
_RETRYABLE = (
    ConnectionError,
    TimeoutError,
    OSError,
)


@celery_app.task(
    name="preview_transform_job",
    bind=True,
    max_retries=3,
    default_retry_delay=4,
    acks_late=True,
)
def preview_transform_job(self, job_id: str) -> dict:
    mark_job_running(job_id)
    try:
        filename, content = load_job_file(job_id)
        result = process_preview_workflow(filename, content)
        mark_job_completed(
            job_id,
            session_id=result.get("session_id"),
            review_id=result.get("review_id"),
            result_payload=result,
        )
        return result
    except _RETRYABLE as exc:
        log.warning("preview_transform_job.transient_error", job_id=job_id, error=str(exc))
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)
    except Exception as exc:
        log.error("preview_transform_job.failed", job_id=job_id, error=str(exc))
        mark_job_failed(job_id, str(exc))
        raise
