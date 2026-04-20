"""
Statistical pattern detector: infers formulas by analysing column values.

Given a new column's values and the existing context columns,
detects relationships like:
  - col_A = col_B * constant   (ratio detection)
  - col_A = col_B - col_C      (linear combination)
  - col_A = running sum of col_B
  - col_A = 0 whenever direction == "outflow"  (conditional filter)
"""
from __future__ import annotations

import math
import statistics
from typing import Any

from app.schemas.statement import ColumnRecommendation

_EPS = 1e-9
_MIN_ROWS = 5          # minimum non-null rows to attempt detection
_RATIO_THRESHOLD = 0.80  # fraction of rows that must satisfy the pattern


def _to_floats(values: list[Any]) -> list[float | None]:
    result: list[float | None] = []
    for v in values:
        try:
            result.append(float(v))
        except (TypeError, ValueError):
            result.append(None)
    return result


def _valid_pairs(
    a: list[float | None], b: list[float | None]
) -> list[tuple[float, float]]:
    return [(x, y) for x, y in zip(a, b) if x is not None and y is not None]


def _ratio_confidence(
    target: list[float | None],
    source: list[float | None],
) -> tuple[float | None, float]:
    """
    Check if target ≈ source * k for some constant k.
    Returns (k, confidence) where confidence ∈ [0, 1].
    """
    pairs = _valid_pairs(target, source)
    if len(pairs) < _MIN_ROWS:
        return None, 0.0

    ratios: list[float] = []
    for t, s in pairs:
        if abs(s) > _EPS:
            ratios.append(t / s)

    if len(ratios) < _MIN_ROWS:
        return None, 0.0

    median_k = statistics.median(ratios)
    if abs(median_k) < _EPS:
        return None, 0.0

    matching = sum(1 for r in ratios if abs(r - median_k) / max(abs(median_k), _EPS) < 0.05)
    confidence = matching / len(ratios)
    return median_k, confidence


def _linear_combination_confidence(
    target: list[float | None],
    col_a: list[float | None],
    col_b: list[float | None],
    sign_b: float = -1.0,
) -> float:
    """
    Check if target ≈ col_a + sign_b * col_b (e.g., A - B).
    Returns confidence in [0, 1].
    """
    triples = [
        (t, a, b)
        for t, a, b in zip(target, col_a, col_b)
        if t is not None and a is not None and b is not None
    ]
    if len(triples) < _MIN_ROWS:
        return 0.0

    matching = sum(
        1 for t, a, b in triples
        if abs(t - (a + sign_b * b)) / max(abs(t), _EPS) < 0.05
    )
    return matching / len(triples)


def _running_sum_confidence(
    target: list[float | None],
    source: list[float | None],
) -> float:
    """Check if target is a running (cumulative) sum of source."""
    pairs = [(t, s) for t, s in zip(target, source) if t is not None and s is not None]
    if len(pairs) < _MIN_ROWS:
        return 0.0

    running = 0.0
    matches = 0
    for t, s in pairs:
        running += s
        if abs(t - running) / max(abs(running), _EPS) < 0.05:
            matches += 1

    return matches / len(pairs)


def _conditional_zero_confidence(
    target: list[float | None],
    direction_values: list[str | None],
    direction: str,
) -> float:
    """Check if target is always 0 (or None) when direction != direction."""
    relevant = [
        t for t, d in zip(target, direction_values)
        if d is not None and d != direction
    ]
    if len(relevant) < _MIN_ROWS:
        return 0.0
    zeros = sum(1 for v in relevant if v is None or abs(float(v or 0)) < _EPS)
    return zeros / len(relevant)


def detect(
    sample_values: list[Any],
    context_columns: dict[str, list[Any]],
    direction_values: list[str | None] | None = None,
) -> list[ColumnRecommendation]:
    """
    Infer likely formula for a new column given its values and context.

    Args:
        sample_values: the new column's values (may include None)
        context_columns: {col_key: [values...]} for existing columns
        direction_values: list of "inflow"/"outflow" strings if available

    Returns list of ColumnRecommendation sorted by confidence.
    """
    target = _to_floats(sample_values)
    results: list[ColumnRecommendation] = []

    ctx_floats: dict[str, list[float | None]] = {
        k: _to_floats(v) for k, v in context_columns.items()
    }

    # 1. Ratio detection: target ≈ source * k
    for col_key, col_vals in ctx_floats.items():
        k, conf = _ratio_confidence(target, col_vals)
        if conf >= _RATIO_THRESHOLD and k is not None:
            k_str = f"{k:.4f}".rstrip("0").rstrip(".")
            formula = f"{{{col_key}}} * {k_str}"
            pct = abs(k) * 100
            if 0.1 <= abs(k) <= 2.0:
                explanation = f"Похоже на {pct:.2g}% от «{col_key}»"
            else:
                explanation = f"Похоже на «{col_key}» × {k_str}"
            results.append(ColumnRecommendation(
                formula=formula,
                explanation=explanation,
                confidence=round(conf, 3),
                category="formula",
                source="pattern",
            ))

    # 2. Subtraction: target ≈ income - expense
    if "income" in ctx_floats and "expense" in ctx_floats:
        conf = _linear_combination_confidence(
            target, ctx_floats["income"], ctx_floats["expense"], -1.0
        )
        if conf >= _RATIO_THRESHOLD:
            results.append(ColumnRecommendation(
                formula="{income} - {expense}",
                explanation="Нетто: Приход − Расход",
                confidence=round(conf, 3),
                category="formula",
                source="pattern",
            ))

    # 3. Running sum
    for col_key, col_vals in ctx_floats.items():
        conf = _running_sum_confidence(target, col_vals)
        if conf >= _RATIO_THRESHOLD:
            results.append(ColumnRecommendation(
                formula=f"running_sum",
                explanation=f"Нарастающий итог «{col_key}»",
                confidence=round(conf, 3),
                category="aggregate",
                source="pattern",
            ))
            break  # one running sum is enough

    # 4. Conditional filter (inflow-only / outflow-only)
    if direction_values:
        for direction, label, field in [
            ("inflow", "только приходы", "income"),
            ("outflow", "только расходы", "expense"),
        ]:
            conf = _conditional_zero_confidence(target, direction_values,
                                                "outflow" if direction == "inflow" else "inflow")
            if conf >= _RATIO_THRESHOLD:
                results.append(ColumnRecommendation(
                    formula=f'IF({{direction}}=="{direction}", {{{field}}}, 0)',
                    explanation=f"Фильтр: {label}",
                    confidence=round(conf, 3),
                    category="formula",
                    source="pattern",
                ))

    # Deduplicate and sort
    seen: set[str] = set()
    unique: list[ColumnRecommendation] = []
    for r in results:
        if r.formula not in seen:
            seen.add(r.formula)
            unique.append(r)

    unique.sort(key=lambda r: r.confidence, reverse=True)
    return unique[:4]
