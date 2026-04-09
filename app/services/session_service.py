from __future__ import annotations

import uuid
from datetime import UTC
from difflib import SequenceMatcher

from sqlalchemy import select

from app.core.database import db_session
from app.models.persistence import CorrectionMemoryRecord, PreferenceRecordDB, SessionRecord
from app.schemas.statement import (
    AIInsightsSummary,
    ParsedStatement,
    PreferenceRecord,
    SessionSummary,
    StatementTotals,
    StatementTransaction,
)
from app.services.ai_engine import enrich_statement as _ai_enrich


def save_session(statement: ParsedStatement) -> str:
    statement = _apply_correction_memory(statement)
    statement, ai_insights = _ai_enrich(statement)
    statement = statement.model_copy(
        update={
            "ai_insights": AIInsightsSummary(
                summary=ai_insights.summary,
                category_breakdown=ai_insights.category_breakdown,
                top_merchants=ai_insights.top_merchants,
                recurring=ai_insights.recurring,
                trend=ai_insights.trend,
                anomalies=ai_insights.anomalies,
                ai_available=ai_insights.ai_available,
            )
        }
    )
    session_id = uuid.uuid4().hex
    with db_session() as session:
        session.add(
            SessionRecord(
                session_id=session_id,
                parser_key=statement.metadata.parser_key,
                source_filename=statement.metadata.source_filename,
                title=statement.metadata.title,
                payload=statement.model_dump(mode="json"),
            )
        )
    return session_id


def load_session(session_id: str) -> ParsedStatement:
    with db_session() as session:
        record = session.get(SessionRecord, session_id)
        if record is None:
            raise FileNotFoundError("Сессия предпросмотра не найдена.")
        return ParsedStatement.model_validate(record.payload)


def update_session_transaction(
    session_id: str,
    row_number: int,
    *,
    date: str | None = None,
    amount: float | None = None,
    operation: str | None = None,
    detail: str | None = None,
    direction: str | None = None,
    note: str | None = None,
) -> ParsedStatement:
    with db_session() as session:
        record = session.get(SessionRecord, session_id)
        if record is None:
            raise FileNotFoundError("Сессия предпросмотра не найдена.")
        statement = ParsedStatement.model_validate(record.payload)

        transaction_index = row_number - 1
        if transaction_index < 0 or transaction_index >= len(statement.transactions):
            raise IndexError("Строка для редактирования не найдена.")

        current = statement.transactions[transaction_index]
        next_date = date or current.date
        next_direction = direction or current.direction
        raw_amount = amount if amount is not None else abs(current.amount)
        signed_amount = abs(raw_amount) if next_direction == "inflow" else -abs(raw_amount)
        next_operation = operation or current.operation
        next_detail = detail or current.detail

        _remember_correction(session, statement.metadata.parser_key, "operation", current.operation, next_operation)
        _remember_correction(session, statement.metadata.parser_key, "detail", current.detail, next_detail)

        statement.transactions[transaction_index] = StatementTransaction(
            date=next_date,
            amount=round(signed_amount, 2),
            income=round(abs(raw_amount), 2) if next_direction == "inflow" else None,
            expense=round(abs(raw_amount), 2) if next_direction == "outflow" else None,
            operation=next_operation,
            detail=next_detail,
            details_operation=_compose_details_operation(next_detail, next_operation, current.comment),
            direction=next_direction,
            document_number=current.document_number,
            operation_datetime=current.operation_datetime,
            comment=current.comment,
            raw_counterparty=current.raw_counterparty,
            note=note if note is not None else current.note,
            flags=current.flags,
            source="manual_correction",
            source_confidence=1.0,
            corrected=True,
        )
        statement.metadata.totals = _calculate_totals(statement.transactions)
        record.payload = statement.model_dump(mode="json")
        record.title = statement.metadata.title
        record.source_filename = statement.metadata.source_filename
        record.parser_key = statement.metadata.parser_key
        return statement


def save_preference(preference: PreferenceRecord) -> PreferenceRecord:
    with db_session() as session:
        record = session.get(PreferenceRecordDB, preference.parser_key)
        payload = preference.model_dump(mode="json")
        if record is None:
            session.add(
                PreferenceRecordDB(
                    parser_key=preference.parser_key,
                    updated_at=preference.updated_at,
                    payload=payload,
                )
            )
        else:
            record.updated_at = preference.updated_at
            record.payload = payload
    return preference


def get_preference(parser_key: str) -> PreferenceRecord | None:
    with db_session() as session:
        record = session.get(PreferenceRecordDB, parser_key)
        if record is None:
            return None
        return PreferenceRecord.model_validate(record.payload)


def list_preferences() -> list[PreferenceRecord]:
    with db_session() as session:
        rows = session.scalars(select(PreferenceRecordDB)).all()
        return [PreferenceRecord.model_validate(item.payload) for item in rows]


def list_recent_sessions(limit: int = 12) -> list[SessionSummary]:
    with db_session() as session:
        rows = session.scalars(
            select(SessionRecord).order_by(SessionRecord.created_at.desc()).limit(limit)
        ).all()
        sessions = [
            SessionSummary(
                session_id=row.session_id,
                parser_key=row.parser_key,
                source_filename=row.source_filename,
                title=row.title,
                account_holder=ParsedStatement.model_validate(row.payload).metadata.account_holder,
                period_start=ParsedStatement.model_validate(row.payload).metadata.period_start,
                period_end=ParsedStatement.model_validate(row.payload).metadata.period_end,
                transaction_count=ParsedStatement.model_validate(row.payload).metadata.transaction_count,
                created_at=row.created_at if row.created_at.tzinfo else row.created_at.replace(tzinfo=UTC),
            )
            for row in rows
        ]
        return sessions


def list_correction_memory(parser_key: str | None = None) -> list[dict]:
    with db_session() as session:
        query = select(CorrectionMemoryRecord)
        if parser_key:
            query = query.where(CorrectionMemoryRecord.parser_key == parser_key)
        rows = session.scalars(query.order_by(CorrectionMemoryRecord.frequency.desc())).all()
        return [
            {
                "correction_id": row.correction_id,
                "parser_key": row.parser_key,
                "field_name": row.field_name,
                "original_value": row.original_value,
                "corrected_value": row.corrected_value,
                "frequency": row.frequency,
                "last_seen_at": row.last_seen_at.isoformat(),
            }
            for row in rows
        ]


def _remember_correction(
    session,
    parser_key: str,
    field_name: str,
    original_value: str,
    corrected_value: str,
) -> None:
    if not original_value or not corrected_value or original_value == corrected_value:
        return
    existing = session.scalar(
        select(CorrectionMemoryRecord).where(
            CorrectionMemoryRecord.parser_key == parser_key,
            CorrectionMemoryRecord.field_name == field_name,
            CorrectionMemoryRecord.original_value == original_value,
            CorrectionMemoryRecord.corrected_value == corrected_value,
        )
    )
    if existing is None:
        session.add(
            CorrectionMemoryRecord(
                parser_key=parser_key,
                field_name=field_name,
                original_value=original_value,
                corrected_value=corrected_value,
                frequency=1,
            )
        )
    else:
        existing.frequency += 1


def _calculate_totals(transactions: list[StatementTransaction]) -> StatementTotals:
    totals = {
        "income_total": 0.0,
        "expense_total": 0.0,
        "purchase_total": 0.0,
        "transfer_total": 0.0,
        "topup_total": 0.0,
        "cash_withdrawal_total": 0.0,
    }
    for transaction in transactions:
        if transaction.income is not None:
            totals["income_total"] += transaction.income
        if transaction.expense is not None:
            totals["expense_total"] += transaction.expense
        if transaction.operation == "Покупка" and transaction.expense is not None:
            totals["purchase_total"] += transaction.expense
        if transaction.operation == "Перевод" and transaction.expense is not None:
            totals["transfer_total"] += transaction.expense
        if transaction.operation == "Пополнение" and transaction.income is not None:
            totals["topup_total"] += transaction.income
        if transaction.operation == "Снятие" and transaction.expense is not None:
            totals["cash_withdrawal_total"] += transaction.expense
    return StatementTotals(**{key: round(value, 2) for key, value in totals.items()})


def _compose_details_operation(detail: str, operation: str, comment: str | None) -> str:
    if comment:
        return " | ".join(part for part in [detail, comment] if part)
    return f"{detail} {operation}".strip()


_FUZZY_THRESHOLD = 0.84  # minimum similarity to apply a fuzzy correction


def _fuzzy_best_match(value: str, candidates: dict[str, str]) -> tuple[str, float] | None:
    """Return (corrected_value, similarity) for the best fuzzy match, or None."""
    best_ratio = 0.0
    best_corrected: str | None = None
    value_lower = value.lower()
    for original, corrected in candidates.items():
        ratio = SequenceMatcher(None, value_lower, original.lower()).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best_corrected = corrected
    if best_corrected is not None and best_ratio >= _FUZZY_THRESHOLD:
        return best_corrected, best_ratio
    return None


def _apply_correction_memory(statement: ParsedStatement) -> ParsedStatement:
    with db_session() as session:
        rows = session.scalars(
            select(CorrectionMemoryRecord).where(
                CorrectionMemoryRecord.parser_key == statement.metadata.parser_key,
                CorrectionMemoryRecord.frequency >= 1,
            )
        ).all()
        if not rows:
            return statement
        # Exact-match maps
        exact_map = {
            (row.field_name, row.original_value): row.corrected_value
            for row in rows
        }
        # Fuzzy candidates split by field
        op_candidates = {
            row.original_value: row.corrected_value
            for row in rows
            if row.field_name == "operation"
        }
        detail_candidates = {
            row.original_value: row.corrected_value
            for row in rows
            if row.field_name == "detail"
        }

    changed = False
    for index, transaction in enumerate(statement.transactions):
        # Prefer exact match
        next_operation = exact_map.get(("operation", transaction.operation))
        next_detail = exact_map.get(("detail", transaction.detail))

        # Fall back to fuzzy match
        op_confidence = 1.0
        detail_confidence = 1.0
        if next_operation is None:
            fuzzy = _fuzzy_best_match(transaction.operation, op_candidates)
            if fuzzy:
                next_operation, op_confidence = fuzzy
        if next_detail is None:
            fuzzy = _fuzzy_best_match(transaction.detail, detail_candidates)
            if fuzzy:
                next_detail, detail_confidence = fuzzy

        next_operation = next_operation or transaction.operation
        next_detail = next_detail or transaction.detail

        if next_operation == transaction.operation and next_detail == transaction.detail:
            continue
        changed = True
        applied_confidence = min(op_confidence, detail_confidence)
        statement.transactions[index] = transaction.model_copy(
            update={
                "operation": next_operation,
                "detail": next_detail,
                "details_operation": f"{next_detail} {next_operation}".strip(),
                "source": "correction_memory",
                "source_confidence": max(transaction.source_confidence or 0.0, round(applied_confidence * 0.9, 2)),
            }
        )
    if changed:
        statement.metadata.totals = _calculate_totals(statement.transactions)
    return statement
