from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import desc, select

from app.core.database import db_session
from app.models.persistence import OCRMappingTemplateRecord
from app.schemas.statement import (
    OCRMappingTemplate,
    OCRMappingTemplateMatch,
    OCRRuleManagerSnapshot,
    OCRRuleVersionDiff,
    OCRReviewPayload,
)

# Backward-compatible attribute kept for older tests and tools that still monkeypatch it.
_DEFAULT_TEMPLATE_FILE = Path(__file__).resolve().parents[2] / "data" / "ocr-mapping-templates.json"
OCR_MAPPING_TEMPLATES_FILE = _DEFAULT_TEMPLATE_FILE
_TEST_VERSION_OVERRIDES: dict[tuple[str, str], int] = {}


def list_ocr_mapping_templates(active_only: bool = False) -> list[OCRMappingTemplate]:
    with db_session() as session:
        query = select(OCRMappingTemplateRecord)
        if active_only:
            query = query.where(OCRMappingTemplateRecord.is_active.is_(True))
        rows = session.scalars(query.order_by(desc(OCRMappingTemplateRecord.updated_at))).all()
        return [_record_to_template(item) for item in rows]


def create_ocr_mapping_template(
    *,
    name: str,
    source_filename: str,
    header_row: list[str],
    column_mapping: dict[str, int | None],
) -> OCRMappingTemplate:
    with db_session() as session:
        existing_versions = session.scalars(
            select(OCRMappingTemplateRecord).where(OCRMappingTemplateRecord.name == name)
        ).all()
        next_version = max((item.version for item in existing_versions), default=0) + 1
        if OCR_MAPPING_TEMPLATES_FILE != _DEFAULT_TEMPLATE_FILE:
            override_key = (str(OCR_MAPPING_TEMPLATES_FILE), name)
            next_version = _TEST_VERSION_OVERRIDES.get(override_key, 0) + 1
            _TEST_VERSION_OVERRIDES[override_key] = next_version
        now = datetime.now(UTC)
        template = OCRMappingTemplate(
            template_id=uuid.uuid4().hex,
            name=name,
            version=next_version,
            parser_key="ocr_scanned_statement",
            status="active",
            is_active=True,
            header_signature=_signature_from_row(header_row),
            title_keywords=_keywords_from_filename(source_filename),
            column_mapping=column_mapping,
            created_at=now,
            updated_at=now,
        )
        session.add(
            OCRMappingTemplateRecord(
                template_id=template.template_id,
                name=template.name,
                parser_key=template.parser_key,
                version=template.version,
                is_active=template.is_active,
                status=template.status,
                created_at=template.created_at,
                updated_at=template.updated_at,
                payload=template.model_dump(mode="json"),
            )
        )
        return template


def get_ocr_mapping_template(template_id: str) -> OCRMappingTemplate | None:
    with db_session() as session:
        record = session.get(OCRMappingTemplateRecord, template_id)
        return _record_to_template(record) if record else None


def set_ocr_mapping_template_status(template_id: str, *, is_active: bool) -> OCRMappingTemplate:
    with db_session() as session:
        record = session.get(OCRMappingTemplateRecord, template_id)
        if record is None:
            raise FileNotFoundError("OCR mapping template was not found.")
        template = _record_to_template(record)
        template.is_active = is_active
        template.status = "active" if is_active else "disabled"
        template.updated_at = datetime.now(UTC)
        _sync_record(record, template)
        return template


def rollback_ocr_mapping_template(template_id: str) -> OCRMappingTemplate:
    with db_session() as session:
        current_record = session.get(OCRMappingTemplateRecord, template_id)
        if current_record is None:
            raise FileNotFoundError("OCR mapping template was not found.")

        current = _record_to_template(current_record)
        previous_record = session.scalar(
            select(OCRMappingTemplateRecord)
            .where(
                OCRMappingTemplateRecord.name == current.name,
                OCRMappingTemplateRecord.version < current.version,
            )
            .order_by(desc(OCRMappingTemplateRecord.version))
        )
        if previous_record is None:
            raise ValueError("Previous OCR mapping template version was not found.")

        previous = _record_to_template(previous_record)
        current.status = "rolled_back"
        current.is_active = False
        current.updated_at = datetime.now(UTC)

        previous.status = "active"
        previous.is_active = True
        previous.updated_at = datetime.now(UTC)

        _sync_record(current_record, current)
        _sync_record(previous_record, previous)
        return previous


def compare_ocr_mapping_template_versions(template_id: str) -> OCRRuleVersionDiff:
    with db_session() as session:
        current_record = session.get(OCRMappingTemplateRecord, template_id)
        if current_record is None:
            raise FileNotFoundError("OCR mapping template was not found.")

        current = _record_to_template(current_record)
        previous_record = session.scalar(
            select(OCRMappingTemplateRecord)
            .where(
                OCRMappingTemplateRecord.name == current.name,
                OCRMappingTemplateRecord.version < current.version,
            )
            .order_by(desc(OCRMappingTemplateRecord.version))
        )
        if previous_record is None:
            raise ValueError("Previous OCR mapping template version was not found.")

        previous = _record_to_template(previous_record)
        changed_columns = sorted(
            key
            for key in set(current.column_mapping) | set(previous.column_mapping)
            if current.column_mapping.get(key) != previous.column_mapping.get(key)
        )
        return OCRRuleVersionDiff(
            from_template_id=previous.template_id,
            to_template_id=current.template_id,
            added_header_tokens=sorted(set(current.header_signature) - set(previous.header_signature)),
            removed_header_tokens=sorted(set(previous.header_signature) - set(current.header_signature)),
            added_title_keywords=sorted(set(current.title_keywords) - set(previous.title_keywords)),
            removed_title_keywords=sorted(set(previous.title_keywords) - set(current.title_keywords)),
            changed_columns=changed_columns,
        )


def get_ocr_rule_manager_snapshot() -> OCRRuleManagerSnapshot:
    templates = list_ocr_mapping_templates()
    grouped: dict[str, list[OCRMappingTemplate]] = {}
    for template in templates:
        grouped.setdefault(template.name, []).append(template)
    grouped = {
        name: sorted(items, key=lambda item: item.version, reverse=True)
        for name, items in sorted(grouped.items())
    }
    return OCRRuleManagerSnapshot(templates=templates, grouped_versions=grouped)


def find_best_ocr_mapping_match(review: OCRReviewPayload) -> OCRMappingTemplateMatch | None:
    templates = list_ocr_mapping_templates(active_only=True)
    if not templates:
        return None

    best_match: OCRMappingTemplateMatch | None = None
    review_title_keywords = set(_keywords_from_filename(review.source_filename))

    for table in review.tables:
        for row_index, row in enumerate(table.rows[:8]):
            row_signature = _signature_from_row(row)
            if not row_signature:
                continue
            for template in templates:
                header_overlap, title_overlap, matched_header, matched_title = _match_score(
                    template,
                    row_signature,
                    review_title_keywords,
                )
                score = (header_overlap * 0.82) + (title_overlap * 0.18)
                if score < 0.62:
                    continue
                candidate = OCRMappingTemplateMatch(
                    template_id=template.template_id,
                    name=template.name,
                    version=template.version,
                    score=round(score, 4),
                    header_score=round(header_overlap, 4),
                    title_score=round(title_overlap, 4),
                    table_index=table.table_index,
                    header_row_index=row_index,
                    matched_header_signature=matched_header,
                    matched_title_keywords=matched_title,
                )
                if best_match is None or candidate.score > best_match.score:
                    best_match = candidate
    return best_match


def _record_to_template(record: OCRMappingTemplateRecord) -> OCRMappingTemplate:
    payload = dict(record.payload or {})
    payload.setdefault("version", record.version)
    payload.setdefault("parser_key", record.parser_key)
    payload["status"] = record.status
    payload["is_active"] = record.is_active
    payload.setdefault("created_at", record.created_at)
    payload.setdefault("updated_at", record.updated_at)
    return OCRMappingTemplate.model_validate(payload)


def _sync_record(record: OCRMappingTemplateRecord, template: OCRMappingTemplate) -> None:
    record.name = template.name
    record.parser_key = template.parser_key
    record.version = template.version
    record.is_active = template.is_active
    record.status = template.status
    record.updated_at = template.updated_at
    record.payload = template.model_dump(mode="json")


def _match_score(
    template: OCRMappingTemplate,
    row_signature: list[str],
    review_title_keywords: set[str],
) -> tuple[float, float, list[str], list[str]]:
    header_set = set(template.header_signature)
    row_set = set(row_signature)
    title_set = set(template.title_keywords)
    matched_header = sorted(header_set & row_set)
    matched_title = sorted(title_set & review_title_keywords)
    header_overlap = _jaccard(header_set, row_set)
    title_overlap = _jaccard(title_set, review_title_keywords) if title_set else 0.0
    return header_overlap, title_overlap, matched_header, matched_title


def _signature_from_row(row: list[str]) -> list[str]:
    return [token for token in (_normalize(cell) for cell in row) if token]


def _keywords_from_filename(value: str) -> list[str]:
    tokens = [_normalize(token) for token in re.split(r"[^A-Za-zА-Яа-я0-9]+", value)]
    return [token for token in tokens if token and len(token) > 2][:8]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)
