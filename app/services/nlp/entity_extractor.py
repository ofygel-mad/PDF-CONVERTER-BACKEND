"""
Entity extractor: pulls numbers, percentages, column references,
operation verbs, and currencies from lemmatized Russian tokens.
"""
from __future__ import annotations

import re

from app.services.nlp.types import Entities, SmartContext
from app.services.nlp.russian_numbers import parse_all_numbers, parse_all_percentages

# Banking field aliases (RU → internal key)
_FIELD_ALIASES: dict[str, str] = {
    "приход": "income",
    "доход": "income",
    "зачисление": "income",
    "расход": "expense",
    "списание": "expense",
    "затрат": "expense",
    "сумм": "amount",
    "итог": "amount",
    "нетто": "net",
    "остаток": "running_sum",
    "баланс": "running_sum",
    "дата": "date",
    "описание": "detail",
    "контрагент": "detail",
    "операция": "operation",
    "комментарий": "comment",
    "валюта": "currency_op",
    "направление": "direction",
}

_CURRENCY_KEYWORDS: dict[str, str] = {
    "доллар": "usd", "usd": "usd", "dollar": "usd",
    "евро": "eur", "eur": "eur", "euro": "eur",
    "тенге": "kzt", "kzt": "kzt",
    "рубль": "rub", "rub": "rub",
    "юань": "cny", "cny": "cny",
}

_OP_VERBS: set[str] = {
    "делить", "поделить", "разделить", "деление",
    "умножить", "помножить", "умножение",
    "прибавить", "добавить", "сложить",
    "вычесть", "отнять", "минус", "вычитание",
    "плюс", "равно",
}


def extract(tokens: list[str], raw_text: str, context: SmartContext) -> Entities:
    """Extract entities from lemmatized tokens and raw text."""
    ent = Entities()

    # Numbers and percentages (from raw text — more reliable)
    ent.percentages = parse_all_percentages(raw_text)
    ent.numbers = [n for n in parse_all_numbers(raw_text)
                   if n not in [p * 100 for p in ent.percentages]]

    # Operation verbs
    for tok in tokens:
        if tok in _OP_VERBS:
            ent.op_verbs.append(tok)

    # Relative refs
    for tok in tokens:
        if tok in ("предыдущ", "предыдущей", "предыдущую", "прошл", "последн"):
            if "previous" not in ent.relative_refs:
                ent.relative_refs.append("previous")

    # Currencies
    text_lower = raw_text.lower()
    for kw, code in _CURRENCY_KEYWORDS.items():
        if kw in text_lower and code not in ent.currencies:
            ent.currencies.append(code)

    # Column references — match against context column labels and known aliases
    col_map = _build_column_map(context)
    for key, variants in col_map.items():
        for variant in variants:
            if variant in text_lower and key not in ent.column_refs:
                ent.column_refs.append(key)
                break

    # Also match field aliases directly
    for alias, field_key in _FIELD_ALIASES.items():
        if alias in text_lower and field_key not in ent.column_refs:
            ent.column_refs.append(field_key)

    # Banking keywords
    _BANKING_KW = [
        "ндс", "налог", "комиссия", "курс", "конверс", "авто-конверс",
        "нетто", "остаток", "баланс", "приход", "расход",
    ]
    for kw in _BANKING_KW:
        if kw in text_lower and kw not in ent.keywords:
            ent.keywords.append(kw)

    return ent


def _build_column_map(context: SmartContext) -> dict[str, list[str]]:
    """Map column_key → list of possible substrings to match in text."""
    result: dict[str, list[str]] = {}
    for col in context.columns:
        key = col.get("key", "")
        label = col.get("label", "").lower()
        variants = [label]
        # also add field alias matches
        for alias, field_key in _FIELD_ALIASES.items():
            if field_key == key:
                variants.append(alias)
        result[key] = variants
    # Add standard field aliases regardless of column presence
    for alias, field_key in _FIELD_ALIASES.items():
        if field_key not in result:
            result[field_key] = [alias]
    return result
