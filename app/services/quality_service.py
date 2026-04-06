from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from datetime import datetime

from app.schemas.statement import ParsedStatement, QualityFlag, QualitySummary, RowDiagnostic

GENERIC_OPERATIONS = {
    "operation",
    "операция",
    "incoming transfer",
    "outgoing transfer",
}

SEVERITY_WEIGHTS = {
    "low": 0.08,
    "medium": 0.18,
    "high": 0.35,
}

# Amounts that are exact multiples of this threshold are considered "round"
_ROUND_DIVISORS = (100, 500, 1000, 5000, 10_000, 50_000, 100_000)

# A transaction amount is "large" when it exceeds this multiple of the session median
_LARGE_AMOUNT_MULTIPLIER = 5.0


def _compute_session_median(transactions) -> float:
    amounts = [abs(t.amount) for t in transactions if t.amount != 0]
    if not amounts:
        return 0.0
    return statistics.median(amounts)


def analyze_statement_quality(statement: ParsedStatement) -> tuple[QualitySummary, list[RowDiagnostic]]:
    duplicate_counter = Counter(
        (row.date, round(abs(row.amount), 2), row.detail.strip().lower(), row.direction)
        for row in statement.transactions
    )
    direction_lookup = defaultdict(set)
    for row in statement.transactions:
        key = (row.date, round(abs(row.amount), 2), row.detail.strip().lower())
        direction_lookup[key].add(row.direction)

    median_amount = _compute_session_median(statement.transactions)

    diagnostics: list[RowDiagnostic] = []
    severity_totals = {"high": 0, "medium": 0, "low": 0}

    for index, row in enumerate(statement.transactions, start=1):
        flags = list(_collect_row_flags(row, duplicate_counter, direction_lookup, median_amount))
        actionable_flags = [flag for flag in flags if flag.code != "manually_corrected"]
        confidence = _calculate_confidence(flags)

        if actionable_flags:
            seen = {flag.severity for flag in actionable_flags}
            for severity in seen:
                severity_totals[severity] += 1

        diagnostics.append(
            RowDiagnostic(
                row_number=index,
                date=row.date,
                operation=row.operation,
                detail=row.detail,
                amount=row.amount,
                confidence=confidence,
                source=row.source,
                corrected=row.corrected,
                flags=flags,
            )
        )

    totals_mismatch = _has_totals_mismatch(statement)
    recommendations = _build_recommendations(diagnostics, totals_mismatch)
    overall_confidence = round(
        sum(item.confidence for item in diagnostics) / len(diagnostics),
        2,
    ) if diagnostics else 1.0
    if totals_mismatch:
        overall_confidence = max(0.1, round(overall_confidence - 0.12, 2))

    total = len(diagnostics) or 1
    anomaly_count = severity_totals["high"] + severity_totals["medium"]
    anomaly_score = round(min(1.0, anomaly_count / total), 3)

    summary = QualitySummary(
        overall_confidence=overall_confidence,
        anomaly_score=anomaly_score,
        review_required_count=sum(
            1 for item in diagnostics if any(flag.code != "manually_corrected" for flag in item.flags)
        ),
        high_risk_count=severity_totals["high"],
        medium_risk_count=severity_totals["medium"],
        low_risk_count=severity_totals["low"],
        clean_count=sum(
            1 for item in diagnostics if not any(flag.code != "manually_corrected" for flag in item.flags)
        ),
        corrected_count=sum(1 for item in diagnostics if item.corrected),
        totals_mismatch=totals_mismatch,
        recommendations=recommendations,
    )
    return summary, diagnostics


def _collect_row_flags(row, duplicate_counter, direction_lookup, median_amount: float = 0.0) -> list[QualityFlag]:
    flags: list[QualityFlag] = []

    if row.flags:
        flags.append(
            QualityFlag(
                code="source_attention_flag",
                severity="medium",
                message="Source parser marked this operation for manual review.",
            )
        )

    if row.source == "ocr" and not row.corrected:
        severity = "medium" if (row.source_confidence or 0.0) < 0.75 else "low"
        flags.append(
            QualityFlag(
                code="ocr_extracted_row",
                severity=severity,
                message="This row was extracted from OCR and should be checked before export.",
            )
        )

    if row.corrected:
        flags.append(
            QualityFlag(
                code="manually_corrected",
                severity="low",
                message="This row was manually corrected in the review panel.",
            )
        )

    if row.note:
        flags.append(
            QualityFlag(
                code="note_present",
                severity="low",
                message="The operation includes an extra note or remark.",
            )
        )

    if not row.detail or row.detail.strip() == row.operation.strip():
        flags.append(
            QualityFlag(
                code="detail_missing",
                severity="medium",
                message="Counterparty or merchant detail is missing or too generic.",
            )
        )

    if row.operation.strip().lower() in GENERIC_OPERATIONS:
        flags.append(
            QualityFlag(
                code="generic_operation",
                severity="medium",
                message="Operation type is generic and may need relabeling.",
            )
        )

    if row.amount == 0:
        flags.append(
            QualityFlag(
                code="zero_amount",
                severity="high",
                message="Operation amount is zero and likely parsed incorrectly.",
            )
        )

    if row.income is not None and row.expense is not None:
        flags.append(
            QualityFlag(
                code="both_sides_present",
                severity="high",
                message="Both income and expense are filled in the same row.",
            )
        )

    if row.direction == "inflow":
        if row.income is None:
            flags.append(
                QualityFlag(
                    code="inflow_without_income",
                    severity="high",
                    message="Direction is inflow but income value is empty.",
                )
            )
        if row.amount < 0:
            flags.append(
                QualityFlag(
                    code="inflow_negative_amount",
                    severity="high",
                    message="Direction is inflow but net amount is negative.",
                )
            )

    if row.direction == "outflow":
        if row.expense is None:
            flags.append(
                QualityFlag(
                    code="outflow_without_expense",
                    severity="high",
                    message="Direction is outflow but expense value is empty.",
                )
            )
        if row.amount > 0:
            flags.append(
                QualityFlag(
                    code="outflow_positive_amount",
                    severity="high",
                    message="Direction is outflow but net amount is positive.",
                )
            )

    duplicate_key = (row.date, round(abs(row.amount), 2), row.detail.strip().lower(), row.direction)
    if duplicate_counter[duplicate_key] > 1:
        flags.append(
            QualityFlag(
                code="possible_duplicate",
                severity="low",
                message="A very similar operation appears multiple times.",
            )
        )

    reversal_key = (row.date, round(abs(row.amount), 2), row.detail.strip().lower())
    if len(direction_lookup[reversal_key]) > 1:
        flags.append(
            QualityFlag(
                code="possible_reversal_pair",
                severity="medium",
                message="Matching inflow and outflow with the same amount exist on the same date.",
            )
        )

    if _is_unparsed_date(row.date):
        flags.append(
            QualityFlag(
                code="date_format_unusual",
                severity="low",
                message="Date format is unusual and should be checked before export.",
            )
        )

    abs_amount = abs(row.amount)
    if abs_amount > 0 and any(abs_amount % d == 0 for d in _ROUND_DIVISORS):
        flags.append(
            QualityFlag(
                code="round_amount",
                severity="low",
                message="Amount is a suspiciously round number — verify it is not an estimate or placeholder.",
            )
        )

    if median_amount > 0 and abs_amount > _LARGE_AMOUNT_MULTIPLIER * median_amount:
        flags.append(
            QualityFlag(
                code="unusually_large_amount",
                severity="medium",
                message="Amount is significantly larger than the typical transaction for this statement.",
            )
        )

    return flags


def _calculate_confidence(flags: list[QualityFlag]) -> float:
    confidence = 1.0
    for flag in flags:
        confidence -= SEVERITY_WEIGHTS.get(flag.severity, 0.08)
    return round(max(0.1, confidence), 2)


def _has_totals_mismatch(statement: ParsedStatement) -> bool:
    metadata = statement.metadata
    if metadata.opening_balance is None or metadata.closing_balance is None:
        return False

    net_change = sum(item.amount for item in statement.transactions)
    expected_closing = round(metadata.opening_balance + net_change, 2)
    return abs(expected_closing - metadata.closing_balance) > 0.05


def _build_recommendations(diagnostics: list[RowDiagnostic], totals_mismatch: bool) -> list[str]:
    recommendations: list[str] = []
    if totals_mismatch:
        recommendations.append("Check opening/closing balances against parsed net cash flow.")

    if any(flag.code == "generic_operation" for row in diagnostics for flag in row.flags):
        recommendations.append("Rename generic operation labels before saving the default template.")

    if any(flag.code == "detail_missing" for row in diagnostics for flag in row.flags):
        recommendations.append("Review rows with missing counterparty details before export.")

    if any(flag.code == "ocr_extracted_row" for row in diagnostics for flag in row.flags):
        recommendations.append("Review OCR-extracted rows and correct key fields before export.")

    if any(flag.severity == "high" for row in diagnostics for flag in row.flags):
        recommendations.append("Resolve high-risk rows first; they can materially change the Excel output.")

    return recommendations[:4]


def _is_unparsed_date(value: str) -> bool:
    for pattern in ("%d.%m.%y", "%d.%m.%Y"):
        try:
            datetime.strptime(value, pattern)
            return False
        except ValueError:
            continue
    return True
