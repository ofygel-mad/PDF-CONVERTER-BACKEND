from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IntentId(str, Enum):
    assign_formula = "assign_formula"
    assign_source_field = "assign_source_field"
    scale_by_constant = "scale_by_constant"
    fx_convert = "fx_convert"
    compute_net = "compute_net"
    compute_vat = "compute_vat"
    compute_fee = "compute_fee"
    rename_column = "rename_column"
    reorder_column = "reorder_column"
    remove_column = "remove_column"
    filter_rows_direction = "filter_rows_direction"
    filter_rows_threshold = "filter_rows_threshold"
    filter_rows_keyword = "filter_rows_keyword"
    reference_previous = "reference_previous"
    clarify_needed = "clarify_needed"


@dataclass
class Entities:
    numbers: list[float] = field(default_factory=list)
    percentages: list[float] = field(default_factory=list)   # 0..1 fractions
    column_refs: list[str] = field(default_factory=list)     # resolved column keys
    relative_refs: list[str] = field(default_factory=list)   # e.g. 'previous'
    op_verbs: list[str] = field(default_factory=list)        # lemmas: делить, умножить…
    currencies: list[str] = field(default_factory=list)      # usd, kzt, eur…
    keywords: list[str] = field(default_factory=list)        # banking domain keywords


@dataclass
class SmartContext:
    columns: list[dict] = field(default_factory=list)
    recent_rows: list[dict] = field(default_factory=list)    # up to 20 rows
    parser_key: str = ""
    target_column_key: str | None = None


@dataclass
class BuildResult:
    formula: str | None
    explanation_ru: str
    confidence: float
    intent: str
    patch_ops: list[dict] = field(default_factory=list)      # structural ops
