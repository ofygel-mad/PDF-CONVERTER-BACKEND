from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.core.database import db_session
from app.models.persistence import TransformationTemplateRecord
from app.schemas.statement import CreateTemplateRequest, TransformationTemplate, UpdateTemplateRequest


def list_templates(parser_key: str | None = None) -> list[TransformationTemplate]:
    with db_session() as session:
        query = select(TransformationTemplateRecord)
        if parser_key is not None:
            query = query.where(TransformationTemplateRecord.parser_key == parser_key)
        rows = session.scalars(query.order_by(TransformationTemplateRecord.updated_at.desc())).all()
        return [TransformationTemplate.model_validate(item.payload) for item in rows]


def create_template(request: CreateTemplateRequest) -> TransformationTemplate:
    with db_session() as session:
        if request.is_default:
            _clear_default_for_parser(session, request.parser_key)

        template = TransformationTemplate(
            template_id=uuid.uuid4().hex,
            parser_key=request.parser_key,
            name=request.name,
            description=request.description,
            base_variant_key=request.base_variant_key,
            columns=request.columns,
            is_default=request.is_default,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        session.add(
            TransformationTemplateRecord(
                template_id=template.template_id,
                parser_key=template.parser_key,
                name=template.name,
                is_default=template.is_default,
                updated_at=template.updated_at,
                payload=template.model_dump(mode="json"),
            )
        )
        return template


def update_template(template_id: str, request: UpdateTemplateRequest) -> TransformationTemplate:
    with db_session() as session:
        record = session.get(TransformationTemplateRecord, template_id)
        if record is None:
            raise FileNotFoundError("Шаблон не найден.")

        template = TransformationTemplate.model_validate(record.payload)
        if request.is_default:
            _clear_default_for_parser(session, template.parser_key)

        template.name = request.name or template.name
        template.description = request.description if request.description is not None else template.description
        template.columns = request.columns or template.columns
        if request.is_default is not None:
            template.is_default = request.is_default
        template.updated_at = datetime.now(UTC)

        record.name = template.name
        record.is_default = template.is_default
        record.updated_at = template.updated_at
        record.payload = template.model_dump(mode="json")
        return template


def get_template(template_id: str) -> TransformationTemplate | None:
    with db_session() as session:
        record = session.get(TransformationTemplateRecord, template_id)
        return TransformationTemplate.model_validate(record.payload) if record else None


def get_default_template(parser_key: str) -> TransformationTemplate | None:
    templates = list_templates(parser_key)
    return next((template for template in templates if template.is_default), None)


def _clear_default_for_parser(session, parser_key: str) -> None:
    rows = session.scalars(
        select(TransformationTemplateRecord).where(TransformationTemplateRecord.parser_key == parser_key)
    ).all()
    for row in rows:
        template = TransformationTemplate.model_validate(row.payload)
        template.is_default = False
        template.updated_at = datetime.now(UTC)
        row.is_default = False
        row.updated_at = template.updated_at
        row.payload = template.model_dump(mode="json")
