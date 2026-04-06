from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select

from app.core.database import db_session
from app.core.paths import JOB_UPLOADS_DIR
from app.models.persistence import JobRecord
from app.schemas.statement import JobSummary


def create_preview_job(filename: str, content: bytes) -> JobSummary:
    job_id = uuid.uuid4().hex
    upload_path = JOB_UPLOADS_DIR / f"{job_id}-{Path(filename).name}"
    upload_path.write_bytes(content)
    now = datetime.now(UTC)
    with db_session() as session:
        session.add(
            JobRecord(
                job_id=job_id,
                job_type="preview_transform",
                status="queued",
                source_filename=filename,
                created_at=now,
                updated_at=now,
                payload={"upload_path": str(upload_path)},
                result_payload=None,
            )
        )
    return get_job(job_id)


def mark_job_running(job_id: str) -> JobSummary:
    return _update_job(job_id, status="running")


def mark_job_failed(job_id: str, error_message: str) -> JobSummary:
    return _update_job(job_id, status="failed", error_message=error_message)


def mark_job_completed(
    job_id: str,
    *,
    session_id: str | None = None,
    review_id: str | None = None,
    result_payload: dict | None = None,
) -> JobSummary:
    return _update_job(
        job_id,
        status="completed",
        session_id=session_id,
        review_id=review_id,
        result_payload=result_payload,
        error_message=None,
    )


def get_job(job_id: str) -> JobSummary:
    with db_session() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            raise FileNotFoundError("Job was not found.")
        return _record_to_schema(record)


def list_jobs(limit: int = 20) -> list[JobSummary]:
    with db_session() as session:
        rows = session.scalars(select(JobRecord).order_by(desc(JobRecord.created_at)).limit(limit)).all()
        return [_record_to_schema(row) for row in rows]


def load_job_file(job_id: str) -> tuple[str, bytes]:
    job = get_job(job_id)
    upload_path = Path((job.payload or {}).get("upload_path", ""))
    if not upload_path.exists():
        raise FileNotFoundError("Uploaded job file was not found.")
    return job.source_filename or upload_path.name, upload_path.read_bytes()


def _update_job(
    job_id: str,
    *,
    status: str,
    session_id: str | None = None,
    review_id: str | None = None,
    result_payload: dict | None = None,
    error_message: str | None = None,
) -> JobSummary:
    with db_session() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            raise FileNotFoundError("Job was not found.")
        record.status = status
        record.session_id = session_id if session_id is not None else record.session_id
        record.review_id = review_id if review_id is not None else record.review_id
        record.error_message = error_message
        record.result_payload = result_payload if result_payload is not None else record.result_payload
        record.updated_at = datetime.now(UTC)
        return _record_to_schema(record)


def _record_to_schema(record: JobRecord) -> JobSummary:
    return JobSummary(
        job_id=record.job_id,
        job_type=record.job_type,
        status=record.status,
        source_filename=record.source_filename,
        session_id=record.session_id,
        review_id=record.review_id,
        error_message=record.error_message,
        created_at=record.created_at if record.created_at.tzinfo else record.created_at.replace(tzinfo=UTC),
        updated_at=record.updated_at if record.updated_at.tzinfo else record.updated_at.replace(tzinfo=UTC),
        payload=record.payload or {},
        result_payload=record.result_payload,
    )
