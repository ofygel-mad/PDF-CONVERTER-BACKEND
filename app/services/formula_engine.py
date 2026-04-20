"""
Safe formula evaluation engine for column calculations.

Formulas use {field_name} syntax for variable substitution.
Example: "{amount} * 0.12"  →  evaluates with row context.
"""
from __future__ import annotations

import re
import math
import statistics
from typing import Any

from simpleeval import SimpleEval, NameNotDefined, EvalWithCompoundTypes


# Fields available in formula context (StatementTransaction fields + computed)
AVAILABLE_FIELDS: set[str] = {
    "income", "expense", "amount", "net", "direction",
    "date", "detail", "operation", "comment", "currency_op",
    "processing_date", "document_number", "note",
    "source_confidence", "row_index",
}

_VAR_RE = re.compile(r"\{(\w+)\}")


def _build_context(row: dict[str, Any], row_index: int = 0) -> dict[str, Any]:
    """Build evaluation context from a row dict."""
    ctx: dict[str, Any] = {}
    for field in AVAILABLE_FIELDS:
        ctx[field] = row.get(field)

    # Computed helpers
    income = row.get("income") or 0.0
    expense = row.get("expense") or 0.0
    amount_raw = row.get("amount")
    if amount_raw is None:
        amount_raw = income if income else expense
    ctx["income"] = income
    ctx["expense"] = expense
    ctx["amount"] = float(amount_raw) if amount_raw is not None else 0.0
    ctx["net"] = income - expense
    ctx["row_index"] = row_index

    # Alias: direction as string
    ctx["direction"] = row.get("direction", "")
    return ctx


def _safe_functions() -> dict[str, Any]:
    return {
        "round": round,
        "abs": abs,
        "int": int,
        "float": float,
        "str": str,
        "len": len,
        "min": min,
        "max": max,
        "upper": lambda s: str(s).upper() if s is not None else "",
        "lower": lambda s: str(s).lower() if s is not None else "",
        "trim": lambda s: str(s).strip() if s is not None else "",
        "concat": lambda *args: "".join(str(a) for a in args),
        "IF": lambda cond, a, b: a if cond else b,
        "ЕСЛИ": lambda cond, a, b: a if cond else b,
        "ISNULL": lambda v, default=0: default if v is None else v,
        "EMPTY": lambda v: v is None or str(v).strip() == "",
        "sqrt": math.sqrt,
        "floor": math.floor,
        "ceil": math.ceil,
    }


def _preprocess(formula: str) -> str:
    """Replace {field} with field name for simpleeval."""
    return _VAR_RE.sub(r"\1", formula.strip())


class FormulaResult:
    __slots__ = ("value", "error", "provenance")

    def __init__(self, value: Any, error: str | None, provenance: str):
        self.value = value
        self.error = error
        self.provenance = provenance


def evaluate(formula: str, row: dict[str, Any], row_index: int = 0) -> FormulaResult:
    """
    Evaluate a formula against a single row context.
    Returns FormulaResult with .value, .error, .provenance.
    """
    provenance = f"formula_engine::{formula}"
    if not formula or not formula.strip():
        return FormulaResult(None, "empty formula", provenance)

    expr = _preprocess(formula)
    ctx = _build_context(row, row_index)

    try:
        ev = SimpleEval(names=ctx, functions=_safe_functions())
        result = ev.eval(expr)
        # Normalise floats to avoid float noise
        if isinstance(result, float):
            result = round(result, 10)
        return FormulaResult(result, None, provenance)
    except NameNotDefined as e:
        return FormulaResult(None, f"неизвестная переменная: {e}", provenance)
    except ZeroDivisionError:
        return FormulaResult(None, "деление на ноль", provenance)
    except Exception as e:  # noqa: BLE001
        return FormulaResult(None, str(e), provenance)


def evaluate_column(
    formula: str,
    rows: list[dict[str, Any]],
) -> list[FormulaResult]:
    """Evaluate formula for every row. Keeps running_sum state."""
    running_total: float = 0.0
    results: list[FormulaResult] = []

    for i, row in enumerate(rows):
        # Inject running_sum into context
        augmented = {**row, "running_sum": running_total}
        result = evaluate(formula, augmented, row_index=i + 1)
        if result.error is None and isinstance(result.value, (int, float)):
            running_total += float(result.value)
        results.append(result)

    return results


def validate_formula(formula: str) -> tuple[bool, str | None]:
    """
    Validate formula syntax without a real row.
    Returns (is_valid, error_message).
    """
    dummy_row = {f: 100.0 for f in AVAILABLE_FIELDS}
    dummy_row["direction"] = "inflow"
    dummy_row["detail"] = "test"
    dummy_row["date"] = "2024-01-01"
    dummy_row["comment"] = ""
    result = evaluate(formula, dummy_row)
    if result.error:
        return False, result.error
    return True, None
