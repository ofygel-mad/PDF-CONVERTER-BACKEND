"""
Column Advisor — the central "brain" that combines lexical analysis,
pattern detection, and formula validation to recommend column formulas.
"""
from __future__ import annotations

from app.schemas.statement import (
    AdvisorColumnRequest,
    AdvisorColumnResponse,
    ColumnRecommendation,
)
from app.services import lexical_analyzer, pattern_detector
from app.services.formula_engine import validate_formula


def advise(request: AdvisorColumnRequest) -> AdvisorColumnResponse:
    """
    Main entry point for column formula recommendation.
    Combines lexical + statistical analysis, deduplicates, validates.
    """
    recs: list[ColumnRecommendation] = []

    # 1. Lexical analysis (always run — fast, zero data needed)
    lexical_recs = lexical_analyzer.analyze(request.column_name)
    recs.extend(lexical_recs)

    # 2. Pattern detection (only if sample values provided)
    if len(request.sample_values) >= 4:
        pattern_recs = pattern_detector.detect(
            sample_values=request.sample_values,
            context_columns=request.context_columns,
            direction_values=None,
        )
        recs.extend(pattern_recs)

    # 3. Validate formulas — remove syntactically invalid ones
    validated: list[ColumnRecommendation] = []
    for rec in recs:
        if rec.category == "mapping":
            # Mapping columns are field references, always valid
            validated.append(rec)
        elif rec.formula == "running_sum":
            validated.append(rec)
        else:
            ok, _ = validate_formula(rec.formula)
            if ok:
                validated.append(rec)

    # 4. Deduplicate by formula, keeping highest confidence
    best: dict[str, ColumnRecommendation] = {}
    for rec in validated:
        if rec.formula not in best or rec.confidence > best[rec.formula].confidence:
            best[rec.formula] = rec

    # 5. Boost pattern-detected recommendations that agree with lexical
    lexical_formulas = {r.formula for r in lexical_recs}
    pattern_formulas = {r.formula for r in pattern_recs} if len(request.sample_values) >= 4 else set()
    for formula, rec in best.items():
        if formula in lexical_formulas and formula in pattern_formulas:
            # Both lexical and statistical agree → boost confidence
            best[formula] = ColumnRecommendation(
                formula=rec.formula,
                explanation=rec.explanation + " ✓ подтверждено статистикой",
                confidence=min(1.0, rec.confidence + 0.08),
                category=rec.category,
                source="lexical+pattern",
            )

    # 6. Sort and return top results
    final = sorted(best.values(), key=lambda r: r.confidence, reverse=True)
    return AdvisorColumnResponse(recommendations=final[:5])
