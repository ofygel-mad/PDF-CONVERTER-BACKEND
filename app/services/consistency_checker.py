"""
Consistency checker for bank statement data.
Detects anomalies, duplicates, balance mismatches, date gaps, currency issues.
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import datetime, date
from typing import Any

from app.schemas.statement import ConsistencyWarning, ConsistencyReport


def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_date(s: Any) -> date | None:
    if not s:
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(str(s).strip()[:10], fmt).date()
        except ValueError:
            continue
    return None


def check_rows(
    rows: list[dict[str, Any]],
    reported_income: float | None = None,
    reported_expense: float | None = None,
) -> ConsistencyReport:
    """
    Run all consistency checks on a list of row dicts.
    Each row should have at minimum: date, income, expense, detail, direction.
    """
    warnings: list[ConsistencyWarning] = []

    # ── 1. Balance check ──────────────────────────────────────────────────────
    total_income = sum(
        _safe_float(r.get("income")) or 0.0 for r in rows
    )
    total_expense = sum(
        _safe_float(r.get("expense")) or 0.0 for r in rows
    )

    if reported_income is not None and abs(total_income - reported_income) > 1.0:
        warnings.append(ConsistencyWarning(
            type="balance_mismatch",
            severity="high",
            message_ru=(
                f"Сумма приходов в строках ({total_income:,.2f} ₸) "
                f"не совпадает с итогом выписки ({reported_income:,.2f} ₸). "
                f"Разница: {abs(total_income - reported_income):,.2f} ₸"
            ),
        ))

    if reported_expense is not None and abs(total_expense - reported_expense) > 1.0:
        warnings.append(ConsistencyWarning(
            type="balance_mismatch",
            severity="high",
            message_ru=(
                f"Сумма расходов в строках ({total_expense:,.2f} ₸) "
                f"не совпадает с итогом выписки ({reported_expense:,.2f} ₸). "
                f"Разница: {abs(total_expense - reported_expense):,.2f} ₸"
            ),
        ))

    # ── 2. Duplicate detection ────────────────────────────────────────────────
    seen_keys: dict[tuple, list[int]] = defaultdict(list)
    for i, row in enumerate(rows):
        key = (
            str(row.get("date", ""))[:10],
            str(_safe_float(row.get("income")) or 0.0),
            str(_safe_float(row.get("expense")) or 0.0),
            str(row.get("detail", ""))[:40],
        )
        seen_keys[key].append(i + 1)

    for key, indices in seen_keys.items():
        if len(indices) >= 2:
            warnings.append(ConsistencyWarning(
                type="duplicate_row",
                severity="medium",
                message_ru=(
                    f"Дублирующиеся строки: {len(indices)} одинаковых записей "
                    f"({key[0]}, {key[3][:30]})"
                ),
                affected_rows=indices,
            ))

    # ── 3. Date gap detection ──────────────────────────────────────────────────
    dates = sorted(filter(None, (_parse_date(r.get("date")) for r in rows)))
    if len(dates) >= 3:
        deltas = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
        median_delta = statistics.median(deltas)
        if median_delta <= 3:  # frequent transactions (daily/every few days)
            max_gap = max(deltas)
            if max_gap > max(7, median_delta * 5):
                gap_idx = deltas.index(max_gap)
                warnings.append(ConsistencyWarning(
                    type="date_gap",
                    severity="low",
                    message_ru=(
                        f"Пропуск дат: {max_gap} дней между "
                        f"{dates[gap_idx]} и {dates[gap_idx + 1]} "
                        f"(медиана: {median_delta:.1f} дн.) — возможно отсутствуют строки"
                    ),
                ))

    # ── 4. Amount anomaly detection (z-score) ─────────────────────────────────
    amounts: list[tuple[int, float]] = []
    for i, row in enumerate(rows):
        v = _safe_float(row.get("income")) or _safe_float(row.get("expense"))
        if v is not None and v > 0:
            amounts.append((i + 1, v))

    if len(amounts) >= 10:
        vals = [v for _, v in amounts]
        mean = statistics.mean(vals)
        stdev = statistics.stdev(vals)
        if stdev > 0:
            outliers = [(idx, v) for idx, v in amounts if abs(v - mean) / stdev > 3.5]
            if outliers:
                for idx, v in outliers[:3]:  # show up to 3
                    warnings.append(ConsistencyWarning(
                        type="anomaly",
                        severity="low",
                        message_ru=(
                            f"Необычно крупная сумма в строке {idx}: "
                            f"{v:,.2f} ₸ (средняя {mean:,.2f} ₸)"
                        ),
                        affected_rows=[idx],
                    ))

    # ── 5. Currency plausibility ──────────────────────────────────────────────
    for i, row in enumerate(rows):
        cur = str(row.get("currency_op") or "").upper().strip()
        if cur in ("USD", "EUR") and row.get("income") is not None:
            income_val = _safe_float(row.get("income"))
            if income_val and income_val > 0:
                # If income is very large and currency is foreign,
                # it might already be KZT — flag only extreme cases
                if income_val < 0.01:
                    warnings.append(ConsistencyWarning(
                        type="currency",
                        severity="medium",
                        message_ru=(
                            f"Строка {i + 1}: валюта {cur}, "
                            f"но сумма подозрительно мала ({income_val})"
                        ),
                        affected_rows=[i + 1],
                    ))

    return ConsistencyReport(
        warnings=warnings,
        is_clean=len(warnings) == 0,
    )
