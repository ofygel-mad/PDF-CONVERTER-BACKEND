"""
Diff analyzer: reverse-engineers what a user did when editing a variant.

Compares original_rows (from the computed variant) vs edited_rows
(from the frontend after user edits) and produces DiffFinding objects
explaining each detected change in plain Russian.
"""
from __future__ import annotations

import re
import math
import statistics
from typing import Any

from app.schemas.statement import DiffFinding, AnalyzeDiffResponse

_EPS = 1e-9
_MIN_ROWS_FOR_PATTERN = 4
_PATTERN_THRESHOLD = 0.75


def _to_float(v: Any) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_numeric(v: Any) -> bool:
    return _to_float(v) is not None


def _ratio(a: float, b: float) -> float | None:
    if abs(b) < _EPS:
        return None
    return a / b


def _format_num(v: float) -> str:
    if abs(v) >= 1000:
        return f"{v:,.0f}"
    return f"{v:g}"


# ── Column-level analysis ──────────────────────────────────────────────────────

def _analyze_column_values(
    col_key: str,
    orig_vals: list[Any],
    edit_vals: list[Any],
    all_orig_rows: list[dict],
) -> list[DiffFinding]:
    findings: list[DiffFinding] = []

    # Pair non-null numeric values
    pairs: list[tuple[float, float, int]] = []  # (orig, edit, row_idx)
    for i, (o, e) in enumerate(zip(orig_vals, edit_vals)):
        of = _to_float(o)
        ef = _to_float(e)
        if of is not None and ef is not None and of != ef:
            pairs.append((of, ef, i))

    if not pairs:
        return findings

    # ── Ratio detection: edit = orig * k ──────────────────────────────────────
    ratios = [_ratio(ef, of) for of, ef, _ in pairs]
    valid_ratios = [r for r in ratios if r is not None]
    if len(valid_ratios) >= _MIN_ROWS_FOR_PATTERN:
        median_k = statistics.median(valid_ratios)
        if abs(median_k) > _EPS:
            matching = sum(
                1 for r in valid_ratios
                if abs(r - median_k) / max(abs(median_k), _EPS) < 0.05
            )
            conf = matching / len(valid_ratios)
            if conf >= _PATTERN_THRESHOLD:
                k_str = f"{median_k:.4f}".rstrip("0").rstrip(".")
                pct = abs(median_k) * 100
                if 0.005 <= abs(median_k) <= 2.0:
                    explanation = (
                        f"Колонка «{col_key}»: значения = оригинал × {k_str} "
                        f"({pct:.3g}%) — возможно, процент или курс конвертации"
                    )
                else:
                    explanation = (
                        f"Колонка «{col_key}»: значения умножены на {k_str}"
                    )
                findings.append(DiffFinding(
                    type="formula_detected",
                    column_key=col_key,
                    detected_formula=f"{{{col_key}}} * {k_str}",
                    confidence=round(conf, 3),
                    explanation_ru=explanation,
                ))
                return findings

    # ── Constant offset: edit = orig + c ──────────────────────────────────────
    offsets = [ef - of for of, ef, _ in pairs]
    if len(offsets) >= _MIN_ROWS_FOR_PATTERN:
        median_c = statistics.median(offsets)
        if abs(median_c) > _EPS:
            matching = sum(1 for d in offsets if abs(d - median_c) < max(abs(median_c) * 0.05, 0.01))
            conf = matching / len(offsets)
            if conf >= _PATTERN_THRESHOLD:
                c_str = _format_num(median_c)
                findings.append(DiffFinding(
                    type="formula_detected",
                    column_key=col_key,
                    detected_formula=f"{{{col_key}}} + {c_str}",
                    confidence=round(conf, 3),
                    explanation_ru=(
                        f"Колонка «{col_key}»: к каждому значению добавлено {c_str} "
                        f"(фиксированная поправка)"
                    ),
                ))
                return findings

    # ── Check if edit matches another column ──────────────────────────────────
    for other_key in ["income", "expense", "amount", "net"]:
        other_orig = [_to_float(r.get(other_key)) for r in all_orig_rows]
        other_edit_vals: list[tuple[float, float]] = []
        for i, (ef_val, _, row_idx) in enumerate(pairs):
            ov = other_orig[row_idx] if row_idx < len(other_orig) else None
            if ov is not None:
                other_edit_vals.append((ef_val, ov))

        if len(other_edit_vals) >= _MIN_ROWS_FOR_PATTERN:
            k_vals = [_ratio(ef_v, ov) for ef_v, ov in other_edit_vals]
            valid_k = [k for k in k_vals if k is not None]
            if valid_k:
                med_k = statistics.median(valid_k)
                matching = sum(1 for k in valid_k if abs(k - med_k) / max(abs(med_k), _EPS) < 0.05)
                conf = matching / len(valid_k)
                if conf >= _PATTERN_THRESHOLD and abs(med_k) > _EPS:
                    k_str = f"{med_k:.4f}".rstrip("0").rstrip(".")
                    if abs(med_k - 1.0) < 0.001:
                        findings.append(DiffFinding(
                            type="formula_detected",
                            column_key=col_key,
                            detected_formula=f"{{{other_key}}}",
                            confidence=round(conf, 3),
                            explanation_ru=(
                                f"Колонка «{col_key}» = поле «{other_key}» из исходных данных"
                            ),
                        ))
                    else:
                        findings.append(DiffFinding(
                            type="formula_detected",
                            column_key=col_key,
                            detected_formula=f"{{{other_key}}} * {k_str}",
                            confidence=round(conf, 3),
                            explanation_ru=(
                                f"Колонка «{col_key}» ≈ «{other_key}» × {k_str}"
                            ),
                        ))
                    return findings

    # ── Fallback: list specific changed cells ──────────────────────────────────
    if len(pairs) <= 5:
        details = ", ".join(
            f"строка {row_idx + 1}: {_format_num(of)} → {_format_num(ef)}"
            for of, ef, row_idx in pairs[:5]
        )
        findings.append(DiffFinding(
            type="cell_changed",
            column_key=col_key,
            confidence=1.0,
            explanation_ru=f"Ручные правки в колонке «{col_key}»: {details}",
        ))
    else:
        findings.append(DiffFinding(
            type="cell_changed",
            column_key=col_key,
            confidence=1.0,
            explanation_ru=(
                f"Изменено {len(pairs)} ячеек в колонке «{col_key}» "
                f"(паттерн не обнаружен)"
            ),
        ))

    return findings


# ── Row removal analysis ───────────────────────────────────────────────────────

def _analyze_removed_rows(
    orig_rows: list[dict],
    edit_rows: list[dict],
) -> list[DiffFinding]:
    """Detect which rows were removed and why."""
    findings: list[DiffFinding] = []
    if len(orig_rows) <= len(edit_rows):
        return findings

    n_removed = len(orig_rows) - len(edit_rows)

    # Try to identify removed rows by finding orig rows not in edit
    edit_keys = set()
    for r in edit_rows:
        key = (str(r.get("date", ""))[:10], str(r.get("detail", ""))[:40])
        edit_keys.add(key)

    removed: list[dict] = []
    for r in orig_rows:
        key = (str(r.get("date", ""))[:10], str(r.get("detail", ""))[:40])
        if key not in edit_keys:
            removed.append(r)

    if not removed:
        findings.append(DiffFinding(
            type="row_removed",
            confidence=0.6,
            explanation_ru=f"Удалено {n_removed} строк (конкретные строки не определены)",
        ))
        return findings

    # Check for common characteristics in removed rows
    # 1. Amount threshold
    amounts = [_to_float(r.get("income") or r.get("expense")) for r in removed]
    valid_amounts = [a for a in amounts if a is not None]
    if valid_amounts:
        max_removed = max(valid_amounts)
        min_removed = min(valid_amounts)
        avg_removed = statistics.mean(valid_amounts)

        kept_amounts = [
            _to_float(r.get("income") or r.get("expense"))
            for r in orig_rows
            if (str(r.get("date", ""))[:10], str(r.get("detail", ""))[:40]) in edit_keys
        ]
        valid_kept = [a for a in kept_amounts if a is not None]

        if valid_kept and max_removed < statistics.mean(valid_kept) * 0.3:
            findings.append(DiffFinding(
                type="filter_detected",
                confidence=0.82,
                explanation_ru=(
                    f"Удалено {len(removed)} строк с малыми суммами "
                    f"(до {max_removed:,.2f} ₸) — похоже на фильтр мелких операций"
                ),
            ))
            return findings

    # 2. Direction filter
    directions = [str(r.get("direction", "")).lower() for r in removed]
    if directions:
        if all(d == "outflow" for d in directions):
            findings.append(DiffFinding(
                type="filter_detected",
                confidence=0.90,
                explanation_ru=f"Удалено {len(removed)} строк — все расходы (direction=outflow)",
            ))
            return findings
        if all(d == "inflow" for d in directions):
            findings.append(DiffFinding(
                type="filter_detected",
                confidence=0.90,
                explanation_ru=f"Удалено {len(removed)} строк — все поступления (direction=inflow)",
            ))
            return findings

    # 3. Keyword in detail
    details = [str(r.get("detail", "")).lower() for r in removed]
    words: dict[str, int] = {}
    for d in details:
        for word in re.findall(r"[а-яa-z]{4,}", d):
            words[word] = words.get(word, 0) + 1
    common = [w for w, cnt in words.items() if cnt >= max(2, len(removed) * 0.5)]
    if common:
        kw = common[0]
        findings.append(DiffFinding(
            type="filter_detected",
            confidence=0.78,
            explanation_ru=(
                f"Удалено {len(removed)} строк, содержащих «{kw}» в описании "
                f"— возможно, фильтр по типу операции"
            ),
        ))
        return findings

    findings.append(DiffFinding(
        type="row_removed",
        confidence=0.7,
        explanation_ru=f"Удалено {len(removed)} строк (общий признак не определён)",
    ))
    return findings


# ── Column structure changes ───────────────────────────────────────────────────

def _analyze_column_structure(
    orig_cols: list[dict],
    edit_cols: list[dict],
) -> list[DiffFinding]:
    findings: list[DiffFinding] = []
    orig_keys = {c.get("key"): c for c in orig_cols}
    edit_keys = {c.get("key"): c for c in edit_cols}

    for key, col in orig_keys.items():
        if key not in edit_keys:
            findings.append(DiffFinding(
                type="column_removed",
                column_key=key,
                confidence=1.0,
                explanation_ru=f"Колонка «{col.get('label', key)}» удалена",
            ))

    for key, col in edit_keys.items():
        if key not in orig_keys:
            findings.append(DiffFinding(
                type="column_added",
                column_key=key,
                confidence=1.0,
                explanation_ru=f"Добавлена новая колонка «{col.get('label', key)}»",
            ))
        elif key in orig_keys:
            orig_label = orig_keys[key].get("label", "")
            edit_label = col.get("label", "")
            if orig_label != edit_label:
                findings.append(DiffFinding(
                    type="label_change",
                    column_key=key,
                    confidence=1.0,
                    explanation_ru=(
                        f"Колонка переименована: «{orig_label}» → «{edit_label}»"
                    ),
                ))

    return findings


# ── Hint-guided re-analysis ────────────────────────────────────────────────────

_HINT_PATTERNS: list[tuple[list[str], str, str]] = [
    # (keywords, formula_template, explanation_template)
    (["курс", "rate", "конверт", "usd", "eur", "доллар", "евро"],
     "{amount} / {rate}",
     "Конвертация по курсу {rate} — замените число на актуальный курс"),
    (["ндс", "nds", "vat", "налог"],
     "{amount} * 0.12",
     "НДС 12% от суммы (при ставке 20% измените на 0.20)"),
    (["комисс", "fee", "процент"],
     "{amount} * 0.015",
     "Комиссия (1.5% — скорректируйте)"),
    (["нетто", "net", "чист"],
     "{income} - {expense}",
     "Нетто = Приход − Расход"),
    (["только расход", "outflow", "списани"],
     "IF({direction}==\"outflow\", {expense}, 0)",
     "Только расходы"),
    (["только приход", "inflow", "поступ"],
     "IF({direction}==\"inflow\", {income}, 0)",
     "Только поступления"),
    (["убр", "удал", "исключ", "фильтр"],
     None,
     "Фильтрация строк по условию"),
]


def apply_hint(hint: str, findings: list[DiffFinding]) -> list[DiffFinding]:
    """
    Refine findings using a free-text hint from the user.
    Extracts numbers, keywords, and updates formulas.
    """
    lower = hint.lower()
    numbers = re.findall(r"\d+(?:[.,]\d+)?", lower)
    updated = list(findings)

    for keywords, formula_template, explanation_template in _HINT_PATTERNS:
        if any(kw in lower for kw in keywords):
            formula = formula_template
            explanation = explanation_template

            # Substitute first number found into formula
            if numbers and "{rate}" in (formula or ""):
                num = numbers[0].replace(",", ".")
                formula = formula.replace("{rate}", num)
                explanation = explanation.replace("{rate}", num)
            elif numbers and formula and "*" in formula:
                # Replace factor with extracted number if it looks like a rate/percent
                num = float(numbers[0].replace(",", "."))
                if num > 1:
                    num = num / 100.0
                formula = re.sub(r"\d+\.\d+", f"{num}", formula)
                explanation += f" (использован коэффициент {num:.4f})"

            # Update or add finding for formula columns
            formula_findings = [f for f in updated if f.type in ("formula_detected", "column_added")]
            if formula_findings and formula:
                for ff in formula_findings[:1]:
                    updated[updated.index(ff)] = DiffFinding(
                        type="formula_detected",
                        column_key=ff.column_key,
                        detected_formula=formula,
                        confidence=0.88,
                        explanation_ru=f"По подсказке пользователя: {explanation}",
                    )
            elif formula:
                updated.append(DiffFinding(
                    type="formula_detected",
                    detected_formula=formula,
                    confidence=0.80,
                    explanation_ru=f"По подсказке пользователя: {explanation}",
                ))
            break

    return updated


def apply_smart_result(
    findings: list[DiffFinding],
    smart_findings: list[DiffFinding],
    target_column_key: str | None = None,
) -> list[DiffFinding]:
    """
    Merge smart NLP findings into the base findings list.
    Smart findings for the target_column_key replace existing findings;
    others are appended. apply_hint() remains the documented fallback.
    """
    if not smart_findings:
        return findings

    smart_keys = {f.column_key for f in smart_findings if f.column_key}
    result = [f for f in findings if f.column_key not in smart_keys]
    result.extend(smart_findings)
    return result


# ── Main entry point ───────────────────────────────────────────────────────────

def analyze_diff(
    orig_columns: list[dict],
    orig_rows: list[dict],
    edit_columns: list[dict],
    edit_rows: list[dict],
    user_hint: str | None = None,
) -> AnalyzeDiffResponse:
    findings: list[DiffFinding] = []

    # 1. Column structure changes
    findings.extend(_analyze_column_structure(orig_columns, edit_columns))

    # 2. Row removals
    findings.extend(_analyze_removed_rows(orig_rows, edit_rows))

    # 3. Value changes per column
    common_keys = [
        c.get("key") for c in edit_columns
        if any(oc.get("key") == c.get("key") for oc in orig_columns)
    ]
    for col_key in common_keys:
        if not col_key:
            continue
        orig_vals = [r.get(col_key) for r in orig_rows[: len(edit_rows)]]
        edit_vals = [r.get(col_key) for r in edit_rows]
        col_findings = _analyze_column_values(col_key, orig_vals, edit_vals, orig_rows)
        findings.extend(col_findings)

    # 4. Apply user hint if provided
    if user_hint and user_hint.strip():
        findings = apply_hint(user_hint, findings)

    # 5. Build summary
    if not findings:
        summary = "Существенных изменений по сравнению с оригиналом не обнаружено."
    else:
        parts: list[str] = []
        label_changes = [f for f in findings if f.type == "label_change"]
        col_removed = [f for f in findings if f.type == "column_removed"]
        col_added = [f for f in findings if f.type == "column_added"]
        row_removed = [f for f in findings if f.type in ("row_removed", "filter_detected")]
        formulas = [f for f in findings if f.type == "formula_detected"]
        cells = [f for f in findings if f.type == "cell_changed"]

        if col_added:
            parts.append(f"добавлено {len(col_added)} колонок")
        if col_removed:
            parts.append(f"удалено {len(col_removed)} колонок")
        if label_changes:
            parts.append(f"переименовано {len(label_changes)} колонок")
        if row_removed:
            parts.append(f"удалены строки ({row_removed[0].explanation_ru[:60]})")
        if formulas:
            parts.append(
                f"обнаружены вычисления: {'; '.join(f.explanation_ru[:60] for f in formulas[:2])}"
            )
        if cells and not formulas:
            parts.append(f"ручные правки в {len(cells)} колонках")

        summary = "Изменения: " + ", ".join(parts) + "."

    return AnalyzeDiffResponse(findings=findings, summary_ru=summary)
