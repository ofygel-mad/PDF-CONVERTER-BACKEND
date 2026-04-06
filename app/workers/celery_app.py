from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "pdf_converter",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    task_track_started=True,
)


@celery_app.task(name="app.workers.ping")
def ping() -> str:
    return "pong"
