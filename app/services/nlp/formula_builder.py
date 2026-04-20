"""
Formula builder: converts (intent, entities, context) → {field} syntax formula string.
"""
from __future__ import annotations

import logging

from app.services.nlp.types import BuildResult, Entities, IntentId, SmartContext

log = logging.getLogger(__name__)

# Russian operation verb → Python operator
_VERB_OP: dict[str, str] = {
    "делить": "/", "поделить": "/", "разделить": "/", "деление": "/",
    "умножить": "*", "помножить": "*", "умножение": "*",
    "прибавить": "+", "добавить": "+", "сложить": "+",
    "вычесть": "-", "отнять": "-", "минус": "-", "вычитание": "-",
}

_INTENT_EXPLANATIONS: dict[str, str] = {
    IntentId.assign_formula: "формула задана вручную",
    IntentId.fx_convert: "конвертация валюты",
    IntentId.compute_net: "нетто = приход − расход",
    IntentId.compute_vat: "НДС",
    IntentId.compute_fee: "комиссия",
    IntentId.scale_by_constant: "умножение на коэффициент",
    IntentId.assign_source_field: "прямое поле",
    IntentId.filter_rows_direction: "фильтр по направлению",
    IntentId.filter_rows_threshold: "фильтр по сумме",
    IntentId.filter_rows_keyword: "фильтр по ключевому слову",
    IntentId.rename_column: "переименование",
    IntentId.remove_column: "удаление колонки",
    IntentId.reorder_column: "перемещение колонки",
    IntentId.reference_previous: "ссылка на предыдущую колонку",
    IntentId.clarify_needed: "требуется уточнение",
}


def build(intent: str, entities: Entities, context: SmartContext) -> BuildResult:
    """Build a formula or patch op from classified intent + extracted entities."""
    target_key = _resolve_target(entities, context)
    explanation = _INTENT_EXPLANATIONS.get(intent, intent)

    try:
        if intent == IntentId.compute_net:
            return BuildResult(
                formula="{income} - {expense}",
                explanation_ru="Нетто: приход − расход",
                confidence=0.92,
                intent=intent,
            )

        if intent == IntentId.compute_vat:
            rate = entities.percentages[0] if entities.percentages else 0.12
            return BuildResult(
                formula=f"{{amount}} * {rate}",
                explanation_ru=f"НДС {rate * 100:.4g}%",
                confidence=0.88,
                intent=intent,
            )

        if intent == IntentId.compute_fee:
            rate = entities.percentages[0] if entities.percentages else None
            if rate is not None:
                return BuildResult(
                    formula=f"{{amount}} * {rate}",
                    explanation_ru=f"Комиссия {rate * 100:.4g}%",
                    confidence=0.85,
                    intent=intent,
                )

        if intent == IntentId.fx_convert:
            # Prefer expense field for outflow conversions
            src = _pick_amount_field(entities, default="expense")
            rate = _pick_fx_rate(entities)
            if rate:
                formula = f"{{{src}}} / {rate}"
                ccy = entities.currencies[0].upper() if entities.currencies else "USD"
                return BuildResult(
                    formula=formula,
                    explanation_ru=f"Конвертация в {ccy} по курсу {rate}",
                    confidence=0.87,
                    intent=intent,
                )

        if intent == IntentId.scale_by_constant:
            factor = _pick_factor(entities)
            src = _pick_amount_field(entities)
            if factor is not None:
                return BuildResult(
                    formula=f"{{{src}}} * {factor}",
                    explanation_ru=f"Умножить {src} × {factor}",
                    confidence=0.80,
                    intent=intent,
                )

        if intent == IntentId.assign_source_field:
            field = entities.column_refs[0] if entities.column_refs else "amount"
            return BuildResult(
                formula=f"{{{field}}}",
                explanation_ru=f"Прямое поле «{field}»",
                confidence=0.90,
                intent=intent,
            )

        if intent == IntentId.assign_formula:
            return _build_from_verbs(entities, context)

        if intent == IntentId.filter_rows_direction:
            return _build_direction_filter(entities)

        if intent == IntentId.filter_rows_threshold:
            threshold = entities.numbers[0] if entities.numbers else None
            if threshold:
                return BuildResult(
                    formula=None,
                    explanation_ru=f"Фильтр: убрать строки с суммой < {threshold:,.0f}",
                    confidence=0.80,
                    intent=intent,
                    patch_ops=[{"op": "filter_threshold", "value": threshold}],
                )

        if intent == IntentId.rename_column:
            return BuildResult(
                formula=None,
                explanation_ru="Переименование колонки",
                confidence=0.75,
                intent=intent,
                patch_ops=[{"op": "rename", "column_key": target_key}],
            )

    except Exception as exc:
        log.debug("formula_builder: error for intent %s: %s", intent, exc)

    return BuildResult(
        formula=None,
        explanation_ru="Не удалось построить формулу — требуется уточнение",
        confidence=0.30,
        intent=IntentId.clarify_needed,
    )


def _resolve_target(entities: Entities, context: SmartContext) -> str | None:
    if context.target_column_key:
        return context.target_column_key
    if entities.column_refs:
        # Skip standard field names as targets; they're more likely operands
        for ref in entities.column_refs:
            col_keys = {c.get("key") for c in context.columns}
            if ref in col_keys:
                return ref
    return None


def _pick_amount_field(entities: Entities, default: str = "amount") -> str:
    for ref in entities.column_refs:
        if ref in ("income", "expense", "amount", "net"):
            return ref
    return default


def _pick_fx_rate(entities: Entities) -> float | None:
    # FX rates are typically 100-1000 range
    for n in entities.numbers:
        if 50 < n < 5000:
            return n
    return None


def _pick_factor(entities: Entities) -> float | None:
    if entities.percentages:
        return entities.percentages[0]
    for n in entities.numbers:
        if 0 < n < 1000:
            return n
    return None


def _build_from_verbs(entities: Entities, context: SmartContext) -> BuildResult:
    if not entities.op_verbs:
        return BuildResult(formula=None, explanation_ru="Не ясна операция",
                           confidence=0.30, intent=IntentId.clarify_needed)
    op = _VERB_OP.get(entities.op_verbs[0], "+")
    refs = entities.column_refs or ["amount"]
    if len(refs) >= 2:
        formula = f"{{{refs[0]}}} {op} {{{refs[1]}}}"
        expl = f"{{refs[0]}} {op} {{refs[1]}}"
    elif refs and entities.numbers:
        formula = f"{{{refs[0]}}} {op} {entities.numbers[0]}"
        expl = f"{{refs[0]}} {op} {entities.numbers[0]}"
    else:
        return BuildResult(formula=None, explanation_ru="Не хватает операндов",
                           confidence=0.30, intent=IntentId.clarify_needed)
    return BuildResult(formula=formula, explanation_ru=expl, confidence=0.72,
                       intent=IntentId.assign_formula)


def _build_direction_filter(entities: Entities) -> BuildResult:
    text = " ".join(entities.keywords + entities.op_verbs)
    direction = "outflow" if any(k in text for k in ("расход", "списан")) else "inflow"
    label = "Расход" if direction == "outflow" else "Приход"
    return BuildResult(
        formula=None,
        explanation_ru=f"Фильтр: оставить только «{label}»",
        confidence=0.82,
        intent=IntentId.filter_rows_direction,
        patch_ops=[{"op": "filter_direction", "direction": direction}],
    )
