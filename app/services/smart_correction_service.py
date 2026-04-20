"""
Smart Correction Service — orchestrates the NLP pipeline for Russian hint interpretation.

Public API:
    warmup()  — call at app startup to pre-load heavy resources
    refine(findings, user_hint, context) → RefineResult

Confidence bands:
    >= 0.75 → emit refined DiffFinding(s)
    0.45–0.75 → emit base findings + ClarifyQuestion
    < 0.45   → fallback to diff_analyzer.apply_hint()
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from functools import lru_cache

from app.core.config import settings
from app.schemas.statement import ClarifyQuestion, DiffFinding
from app.services.nlp.types import SmartContext

log = logging.getLogger(__name__)

_nlp_available = False


# ── Public data types ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RefineResult:
    findings: list[DiffFinding]
    narrative_ru: str
    clarifications: list[ClarifyQuestion]
    confidence: float


# ── Startup ────────────────────────────────────────────────────────────────────

def warmup() -> None:
    """Pre-load NLP models. Failures are logged and the feature auto-disables."""
    global _nlp_available
    if not settings.smart_nlp_enabled:
        log.info("smart_correction_service: disabled via config")
        return
    try:
        from app.services.nlp import embeddings as emb
        from app.services.nlp import intent_classifier
        from app.services.nlp import lemmatizer
        from app.services.nlp import typo_corrector

        emb.load(settings.smart_nlp_model_path)
        intent_classifier.load()
        lemmatizer.lemmatize(["тест"])          # trigger lazy init
        typo_corrector.correct(["тест"])        # trigger lazy SymSpell load
        _nlp_available = True
        log.info("smart_correction_service: ready (embeddings mode: %s)", emb._mode)
    except Exception as exc:
        log.warning("smart_correction_service: warmup failed (%s) — using fallback", exc)
        _nlp_available = False


# ── Main entry point ───────────────────────────────────────────────────────────

def refine(
    findings: list[DiffFinding],
    user_hint: str,
    context: SmartContext,
) -> RefineResult:
    """
    Refine diff findings using a free-form Russian hint.
    Returns a RefineResult with updated findings and a narrative.
    """
    if not user_hint or not user_hint.strip():
        narrative = _build_narrative(findings)
        return RefineResult(
            findings=findings,
            narrative_ru=narrative,
            clarifications=[],
            confidence=1.0,
        )

    try:
        return _run_pipeline(findings, user_hint, context)
    except Exception as exc:
        log.warning("smart_correction_service.refine: pipeline error (%s) — using fallback", exc)
        return _fallback(findings, user_hint)


# ── NLP pipeline ───────────────────────────────────────────────────────────────

def _run_pipeline(
    findings: list[DiffFinding],
    user_hint: str,
    context: SmartContext,
) -> RefineResult:
    from app.services.nlp import normalizer
    from app.services.nlp import lemmatizer
    from app.services.nlp import typo_corrector
    from app.services.nlp import entity_extractor
    from app.services.nlp import intent_classifier
    from app.services.nlp import formula_builder

    # Inject column labels into typo corrector dictionary for this request
    _inject_column_labels(context)

    # 1. Normalize
    norm_text = normalizer.normalize(user_hint)

    # 2. Tokenize
    tokens = norm_text.split()

    # 3. Typo correction
    corrected = typo_corrector.correct(tokens)

    # 4. Lemmatize
    lemmas = lemmatizer.lemmatize(corrected)

    # 5. Entity extraction
    corrected_text = " ".join(corrected)
    entities = entity_extractor.extract(lemmas, corrected_text, context)

    # 6. Intent classification
    intent_id, intent_conf = intent_classifier.classify(corrected_text)

    # 7. Formula building
    build_result = formula_builder.build(intent_id, entities, context)

    # 8. Formula validation
    formula_valid = True
    if build_result.formula:
        try:
            from app.services import formula_engine
            is_valid, err = formula_engine.validate_formula(build_result.formula)
            if not is_valid:
                log.debug("smart_correction: invalid formula %r: %s", build_result.formula, err)
                formula_valid = False
        except Exception:
            pass  # formula_engine unavailable → skip validation

    # 9. Confidence scoring
    typo_dist = _typo_distance_norm(tokens, corrected)
    entity_completeness = _entity_completeness(entities, intent_id)
    final_confidence = (
        0.5 * intent_conf
        + 0.3 * (1.0 - typo_dist)
        + 0.2 * entity_completeness
    )
    if not formula_valid:
        final_confidence *= 0.6

    # 10. Apply result based on confidence band
    threshold = settings.smart_nlp_confidence_threshold
    clarify_threshold = settings.smart_nlp_clarify_threshold

    if final_confidence >= threshold and build_result.formula:
        # High confidence — produce refined finding
        refined = _apply_result(findings, build_result, context)
        return RefineResult(
            findings=refined,
            narrative_ru=_build_narrative(refined),
            clarifications=[],
            confidence=final_confidence,
        )

    if clarify_threshold <= final_confidence < threshold:
        # Mid confidence — keep base findings + add clarify question
        clarify = _build_clarify_question(entities, build_result, intent_id, context)
        # Mark matching finding as needing clarification
        patched = _mark_needs_clarification(findings, context.target_column_key)
        return RefineResult(
            findings=patched,
            narrative_ru=_build_narrative(patched),
            clarifications=[clarify] if clarify else [],
            confidence=final_confidence,
        )

    # Low confidence — fallback
    return _fallback(findings, user_hint)


def _fallback(findings: list[DiffFinding], user_hint: str) -> RefineResult:
    from app.services.diff_analyzer import apply_hint
    try:
        refined = apply_hint(user_hint, findings)
    except Exception:
        refined = findings
    return RefineResult(
        findings=refined,
        narrative_ru=_build_narrative(refined),
        clarifications=[],
        confidence=0.40,
    )


# ── Narrative generator ────────────────────────────────────────────────────────

def _build_narrative(findings: list[DiffFinding]) -> str:
    if not findings:
        return "Изменений не обнаружено."

    parts: list[str] = []
    for f in findings:
        if f.type == "formula_detected" and f.detected_formula:
            col = f"«{f.column_key}»" if f.column_key else "колонка"
            parts.append(f"{col} = {f.detected_formula}")
        elif f.type == "column_added" and f.column_key:
            parts.append(f"добавлена колонка «{f.column_key}»")
        elif f.type == "column_removed" and f.column_key:
            parts.append(f"удалена колонка «{f.column_key}»")
        elif f.type == "label_change":
            parts.append(f.explanation_ru)
        elif f.type == "filter_detected":
            parts.append(f.explanation_ru)
        elif f.type == "row_removed":
            parts.append(f.explanation_ru)

    if not parts:
        return findings[0].explanation_ru if findings else "Изменения применены."

    return "Таблица построена так: " + "; ".join(parts) + "."


# ── Helpers ────────────────────────────────────────────────────────────────────

def _apply_result(
    findings: list[DiffFinding],
    build_result,
    context: SmartContext,
) -> list[DiffFinding]:
    """Merge build_result into findings list."""
    from app.services.nlp.types import IntentId

    target_key = context.target_column_key
    new_finding = DiffFinding(
        type="formula_detected" if build_result.formula else "filter_detected",
        column_key=target_key,
        detected_formula=build_result.formula,
        confidence=build_result.confidence,
        explanation_ru=build_result.explanation_ru,
        intent=build_result.intent,
        needs_clarification=False,
    )

    # Replace existing finding for the same column if present
    updated = []
    replaced = False
    for f in findings:
        if f.column_key == target_key and f.type in ("formula_detected", "column_added"):
            updated.append(new_finding)
            replaced = True
        else:
            updated.append(f)

    if not replaced:
        updated.append(new_finding)

    # Apply patch ops (filter, rename, etc.)
    for op in build_result.patch_ops:
        patch_finding = _patch_op_to_finding(op, target_key)
        if patch_finding:
            updated.append(patch_finding)

    return updated


def _patch_op_to_finding(op: dict, column_key: str | None) -> DiffFinding | None:
    op_type = op.get("op")
    if op_type == "filter_direction":
        direction = op.get("direction", "outflow")
        label = "Расход" if direction == "outflow" else "Приход"
        return DiffFinding(
            type="filter_detected",
            column_key=None,
            detected_formula=None,
            confidence=0.80,
            explanation_ru=f"Фильтр: оставить только «{label}»",
        )
    if op_type == "filter_threshold":
        val = op.get("value", 0)
        return DiffFinding(
            type="filter_detected",
            column_key=None,
            detected_formula=None,
            confidence=0.80,
            explanation_ru=f"Фильтр: убраны строки с суммой < {val:,.0f}",
        )
    if op_type == "rename":
        return DiffFinding(
            type="label_change",
            column_key=column_key,
            confidence=0.75,
            explanation_ru=f"Переименование колонки «{column_key}»",
        )
    return None


def _build_clarify_question(
    entities,
    build_result,
    intent_id: str,
    context: SmartContext,
) -> ClarifyQuestion | None:
    choices: list[str] = []
    formulas: list[str] = []

    if entities.column_refs and entities.numbers:
        for ref in entities.column_refs[:2]:
            for num in entities.numbers[:2]:
                choices.append(f"{{{ref}}} / {num}")
                formulas.append(f"{{{ref}}} / {num}")
                choices.append(f"{{{ref}}} * {num}")
                formulas.append(f"{{{ref}}} * {num}")

    if not choices and build_result.formula:
        choices = [build_result.formula]
        formulas = [build_result.formula]

    if not choices:
        return None

    return ClarifyQuestion(
        question_ru="Вы имели в виду одну из этих формул?",
        choices=choices[:4],
        choice_formulas=formulas[:4],
        column_key=context.target_column_key,
    )


def _mark_needs_clarification(
    findings: list[DiffFinding],
    target_key: str | None,
) -> list[DiffFinding]:
    result = []
    for f in findings:
        if f.column_key == target_key:
            result.append(f.model_copy(update={"needs_clarification": True}))
        else:
            result.append(f)
    return result


def _inject_column_labels(context: SmartContext) -> None:
    try:
        from app.services.nlp import typo_corrector
        words = []
        for col in context.columns:
            label = col.get("label", "")
            if label:
                words.extend(label.lower().split())
        typo_corrector.add_domain_words(words)
    except Exception:
        pass


def _typo_distance_norm(original: list[str], corrected: list[str]) -> float:
    if not original:
        return 0.0
    changes = sum(1 for a, b in zip(original, corrected) if a != b)
    return changes / len(original)


def _entity_completeness(entities, intent_id: str) -> float:
    from app.services.nlp.types import IntentId
    if intent_id in (IntentId.compute_net, IntentId.assign_source_field):
        return 1.0
    if intent_id == IntentId.fx_convert:
        has_rate = bool(entities.numbers and any(50 < n < 5000 for n in entities.numbers))
        return 1.0 if has_rate else 0.5
    if intent_id in (IntentId.compute_vat, IntentId.compute_fee, IntentId.scale_by_constant):
        return 1.0 if entities.percentages else 0.6
    if intent_id == IntentId.filter_rows_threshold:
        return 1.0 if entities.numbers else 0.4
    if intent_id == IntentId.assign_formula:
        return min(1.0, 0.3 * len(entities.op_verbs) + 0.4 * len(entities.column_refs))
    return 0.7
