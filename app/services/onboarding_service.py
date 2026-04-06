from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import desc, select

from app.core.database import db_session
from app.models.persistence import OnboardingProjectRecord, OnboardingSampleRecord
from app.schemas.statement import (
    AddOnboardingSampleRequest,
    CreateOnboardingProjectRequest,
    OnboardingProject,
    OnboardingSample,
)


def create_onboarding_project(request: CreateOnboardingProjectRequest) -> OnboardingProject:
    project = OnboardingProject(
        project_id=uuid.uuid4().hex,
        name=request.name,
        bank_name=request.bank_name,
        notes=request.notes,
        status="draft",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        samples=[],
    )
    with db_session() as session:
        session.add(
            OnboardingProjectRecord(
                project_id=project.project_id,
                name=project.name,
                bank_name=project.bank_name,
                status=project.status,
                notes=project.notes,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
        )
    return project


def list_onboarding_projects() -> list[OnboardingProject]:
    with db_session() as session:
        rows = session.scalars(
            select(OnboardingProjectRecord).order_by(desc(OnboardingProjectRecord.updated_at))
        ).all()
        return [_project_from_record(row) for row in rows]


def add_onboarding_sample(project_id: str, request: AddOnboardingSampleRequest) -> OnboardingSample:
    with db_session() as session:
        project = session.get(OnboardingProjectRecord, project_id)
        if project is None:
            raise FileNotFoundError("Onboarding project was not found.")
        sample = OnboardingSample(
            sample_id=uuid.uuid4().hex,
            project_id=project_id,
            source_filename=request.source_filename,
            review_id=request.review_id,
            session_id=request.session_id,
            status=request.status,
            payload=request.payload,
            created_at=datetime.now(UTC),
        )
        session.add(
            OnboardingSampleRecord(
                sample_id=sample.sample_id,
                project_id=project_id,
                source_filename=sample.source_filename,
                review_id=sample.review_id,
                session_id=sample.session_id,
                status=sample.status,
                payload=sample.payload,
                created_at=sample.created_at,
            )
        )
        project.updated_at = datetime.now(UTC)
        if request.review_id and request.session_id:
            project.status = "validated"
        elif request.review_id:
            project.status = "mapping"
        else:
            project.status = "collecting_samples"
        return sample


def get_onboarding_project(project_id: str) -> OnboardingProject:
    with db_session() as session:
        record = session.get(OnboardingProjectRecord, project_id)
        if record is None:
            raise FileNotFoundError("Onboarding project was not found.")
        return _project_from_record(record)


def _project_from_record(record: OnboardingProjectRecord) -> OnboardingProject:
    samples = sorted(record.samples, key=lambda item: item.created_at, reverse=True)
    return OnboardingProject(
        project_id=record.project_id,
        name=record.name,
        bank_name=record.bank_name,
        status=record.status,
        notes=record.notes,
        created_at=record.created_at if record.created_at.tzinfo else record.created_at.replace(tzinfo=UTC),
        updated_at=record.updated_at if record.updated_at.tzinfo else record.updated_at.replace(tzinfo=UTC),
        samples=[
            OnboardingSample(
                sample_id=sample.sample_id,
                project_id=sample.project_id,
                source_filename=sample.source_filename,
                review_id=sample.review_id,
                session_id=sample.session_id,
                status=sample.status,
                payload=sample.payload,
                created_at=sample.created_at if sample.created_at.tzinfo else sample.created_at.replace(tzinfo=UTC),
            )
            for sample in samples
        ],
    )
