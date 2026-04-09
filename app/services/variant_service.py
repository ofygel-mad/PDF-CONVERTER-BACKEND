from __future__ import annotations

from collections import defaultdict

from app.schemas.statement import (
    ParsedStatement,
    PreviewColumn,
    PreviewVariant,
    TransformationTemplate,
)
from app.services.kaspi_business_statement import (
    derive_counterparty_type,
    derive_flow_group,
    derive_flow_signal,
    derive_kaspi_bucket,
)

PRIMARY_GROUP = "primary"
KASPI_BUSINESS_GROUP = "kaspi_business_plus"


def build_variants(statement: ParsedStatement) -> list[PreviewVariant]:
    transactions = statement.transactions
    variants = _build_primary_variants(transactions)
    if statement.metadata.parser_key == "kaspi_business_statement":
        variants.extend(_build_kaspi_business_variants(transactions))
    if any(t.category for t in transactions):
        variants.append(_build_ai_variant(transactions))
    return variants


def apply_template_to_variant(
    variant: PreviewVariant,
    template: TransformationTemplate,
) -> PreviewVariant:
    configured_columns = [column for column in template.columns if column.enabled]
    column_order = [column.key for column in configured_columns]

    rows = []
    for row in variant.rows:
        shaped_row = {key: row.get(key) for key in column_order}
        if "direction" in row:
            shaped_row["direction"] = row["direction"]
        rows.append(shaped_row)

    return PreviewVariant(
        key=f"template::{template.template_id}",
        name=template.name,
        description=template.description or variant.description,
        columns=[
            PreviewColumn(key=column.key, label=column.label, kind=column.kind)
            for column in configured_columns
        ],
        rows=rows,
        group=variant.group,
        template_id=template.template_id,
        base_variant_key=template.base_variant_key,
    )


def build_template_seed(variant: PreviewVariant) -> list[dict[str, str | bool]]:
    return [
        {
            "key": column.key,
            "label": column.label,
            "kind": column.kind,
            "enabled": True,
        }
        for column in variant.columns
    ]


def _build_primary_variants(transactions) -> list[PreviewVariant]:
    variants: list[PreviewVariant] = [
        PreviewVariant(
            key="classic_financier",
            name="\u0424\u0438\u043d\u0430\u043d\u0441\u0438\u0441\u0442 \u041a\u043b\u0430\u0441\u0441\u0438\u043a\u0430",
            description=(
                "\u0411\u0430\u0437\u043e\u0432\u0430\u044f \u043b\u0435\u043d\u0442\u0430: "
                "\u0434\u0430\u0442\u0430, \u043f\u0440\u0438\u0445\u043e\u0434, "
                "\u0440\u0430\u0441\u0445\u043e\u0434 \u0438 \u043e\u0431\u044a\u0435\u0434\u0438\u043d\u0435\u043d\u043d\u0430\u044f "
                "\u0441\u0442\u0440\u043e\u043a\u0430 \u0434\u0435\u0442\u0430\u043b\u0435\u0439."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(
                    key="income",
                    label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(
                    key="expense",
                    label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(
                    key="details_operation",
                    label="\u0414\u0435\u0442\u0430\u043b\u0438 / \u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f",
                ),
            ],
            rows=[
                {
                    "date": row.date,
                    "income": row.income,
                    "expense": row.expense,
                    "details_operation": row.details_operation,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=PRIMARY_GROUP,
        ),
        PreviewVariant(
            key="operation_split",
            name="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f \u041e\u0442\u0434\u0435\u043b\u044c\u043d\u043e",
            description=(
                "\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f \u0438 \u0434\u0435\u0442\u0430\u043b\u0438 "
                "\u0432 \u0440\u0430\u0437\u043d\u044b\u0445 \u043a\u043e\u043b\u043e\u043d\u043a\u0430\u0445."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(key="operation", label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f"),
                PreviewColumn(key="detail", label="\u0414\u0435\u0442\u0430\u043b\u0438"),
                PreviewColumn(
                    key="income",
                    label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(
                    key="expense",
                    label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(key="amount", label="\u041d\u0435\u0442\u0442\u043e, \u20b8", kind="currency"),
            ],
            rows=[
                {
                    "date": row.date,
                    "operation": row.operation,
                    "detail": row.detail,
                    "income": row.income,
                    "expense": row.expense,
                    "amount": row.amount,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=PRIMARY_GROUP,
        ),
        PreviewVariant(
            key="counterparty_first",
            name="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442 \u0412\u043f\u0435\u0440\u0435\u0434",
            description=(
                "\u041f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442 \u043d\u0430 "
                "\u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u0435 \u0438 "
                "\u043d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0438 \u043f\u043e\u0442\u043e\u043a\u0430."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(
                    key="detail",
                    label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442 / \u041c\u0435\u0440\u0447\u0430\u043d\u0442",
                ),
                PreviewColumn(key="operation", label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f"),
                PreviewColumn(
                    key="direction_label",
                    label="\u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
                ),
                PreviewColumn(key="amount_abs", label="\u0421\u0443\u043c\u043c\u0430, \u20b8", kind="currency"),
            ],
            rows=[
                {
                    "date": row.date,
                    "detail": row.detail,
                    "operation": row.operation,
                    "direction_label": _direction_label(row.direction),
                    "amount_abs": row.income if row.income is not None else row.expense,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=PRIMARY_GROUP,
        ),
        PreviewVariant(
            key="daily_summary",
            name="\u0421\u0432\u043e\u0434\u043a\u0430 \u041f\u043e \u0414\u043d\u044f\u043c",
            description=(
                "\u0413\u0440\u0443\u043f\u043f\u0438\u0440\u043e\u0432\u043a\u0430 \u043f\u043e "
                "\u0434\u0430\u0442\u0430\u043c \u0434\u043b\u044f \u043a\u0430\u0440\u0442\u0438\u043d\u044b cash-flow."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(
                    key="income_total",
                    label="\u041f\u0440\u0438\u0445\u043e\u0434 \u0437\u0430 \u0434\u0435\u043d\u044c, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(
                    key="expense_total",
                    label="\u0420\u0430\u0441\u0445\u043e\u0434 \u0437\u0430 \u0434\u0435\u043d\u044c, \u20b8",
                    kind="currency",
                ),
                PreviewColumn(key="net_total", label="\u041d\u0435\u0442\u0442\u043e, \u20b8", kind="currency"),
                PreviewColumn(
                    key="operations_count",
                    label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u0439",
                ),
            ],
            rows=_build_daily_rows(transactions),
            group=PRIMARY_GROUP,
        ),
        PreviewVariant(
            key="audit_flags",
            name="\u0410\u0443\u0434\u0438\u0442 \u0418 \u0424\u043b\u0430\u0433\u0438",
            description=(
                "\u041b\u0435\u043d\u0442\u0430 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438 "
                "\u0441\u043f\u043e\u0440\u043d\u044b\u0445 \u0438 \u0440\u0438\u0441\u043a\u043e\u0432\u044b\u0445 "
                "\u0441\u0442\u0440\u043e\u043a."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(
                    key="direction_label",
                    label="\u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
                ),
                PreviewColumn(key="amount_abs", label="\u0421\u0443\u043c\u043c\u0430, \u20b8", kind="currency"),
                PreviewColumn(key="operation", label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f"),
                PreviewColumn(key="detail", label="\u0414\u0435\u0442\u0430\u043b\u0438"),
                PreviewColumn(key="flags_label", label="\u0424\u043b\u0430\u0433\u0438"),
                PreviewColumn(key="note", label="\u041f\u0440\u0438\u043c\u0435\u0447\u0430\u043d\u0438\u0435"),
            ],
            rows=[
                {
                    "date": row.date,
                    "direction_label": _direction_label(row.direction),
                    "amount_abs": row.income if row.income is not None else row.expense,
                    "operation": row.operation,
                    "detail": row.detail,
                    "flags_label": ", ".join(row.flags) if row.flags else "OK",
                    "note": row.note,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=PRIMARY_GROUP,
        ),
    ]
    return variants


def _build_kaspi_business_variants(transactions) -> list[PreviewVariant]:
    return [
        PreviewVariant(
            key="business_compact_classic",
            name="\u041a\u043b\u0430\u0441\u0441\u0438\u043a\u0430",
            description=(
                "\u041a\u043e\u043c\u043f\u0430\u043a\u0442\u043d\u0430\u044f \u043b\u0435\u043d\u0442\u0430 "
                "\u0434\u043b\u044f \u0444\u0438\u043d\u0430\u043b\u044c\u043d\u043e\u0439 \u0432\u044b\u0433\u0440\u0443\u0437\u043a\u0438."
            ),
            columns=[
                PreviewColumn(key="document_number", label="\u2116 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430"),
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430 \u043e\u043f\u0435\u0440\u0430\u0446\u0438\u0438"),
                PreviewColumn(key="income", label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="expense", label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
                PreviewColumn(key="comment", label="\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439"),
            ],
            rows=[
                {
                    "document_number": row.document_number,
                    "date": row.date,
                    "income": row.income,
                    "expense": row.expense,
                    "detail": row.detail,
                    "comment": row.comment,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=KASPI_BUSINESS_GROUP,
        ),
        PreviewVariant(
            key="business_flow_lens",
            name="\u041f\u043e\u0442\u043e\u043a",
            description=(
                "\u041b\u0435\u043d\u0442\u0430 \u043f\u043e\u0442\u043e\u043a\u043e\u0432 "
                "\u043f\u043e \u0442\u0438\u043f\u0443 \u0434\u0432\u0438\u0436\u0435\u043d\u0438\u044f."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(key="flow_group", label="\u041f\u043e\u0442\u043e\u043a"),
                PreviewColumn(key="flow_signal", label="\u0421\u0438\u0433\u043d\u0430\u043b"),
                PreviewColumn(key="income", label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="expense", label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
                PreviewColumn(key="comment", label="\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439"),
            ],
            rows=[
                {
                    "date": row.date,
                    "flow_group": derive_flow_group(row),
                    "flow_signal": derive_flow_signal(row),
                    "income": row.income,
                    "expense": row.expense,
                    "detail": row.detail,
                    "comment": row.comment,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=KASPI_BUSINESS_GROUP,
        ),
        PreviewVariant(
            key="business_counterparty_grid",
            name="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u044b",
            description=(
                "\u0410\u043a\u0446\u0435\u043d\u0442 \u043d\u0430 "
                "\u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u0430\u0445 \u0438 "
                "\u0438\u0445 \u0442\u0438\u043f\u0435."
            ),
            columns=[
                PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
                PreviewColumn(
                    key="counterparty_type",
                    label="\u0422\u0438\u043f \u043a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442\u0430",
                ),
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(key="income", label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="expense", label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="document_number", label="\u2116 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430"),
                PreviewColumn(key="comment", label="\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439"),
            ],
            rows=[
                {
                    "detail": row.detail,
                    "counterparty_type": derive_counterparty_type(row.detail),
                    "date": row.date,
                    "income": row.income,
                    "expense": row.expense,
                    "document_number": row.document_number,
                    "comment": row.comment,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=KASPI_BUSINESS_GROUP,
        ),
        PreviewVariant(
            key="business_kaspi_stream",
            name="Kaspi \u041f\u043e\u0442\u043e\u043a\u0438",
            description=(
                "\u0421\u0435\u0433\u043c\u0435\u043d\u0442\u0430\u0446\u0438\u044f "
                "\u0432\u044b\u0440\u0443\u0447\u043a\u0438, \u043a\u043e\u043c\u0438\u0441\u0441\u0438\u0439, "
                "\u0434\u0435\u043f\u043e\u0437\u0438\u0442\u043e\u0432 \u0438 \u0432\u044b\u0432\u043e\u0434\u0430."
            ),
            columns=[
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(key="kaspi_bucket", label="Kaspi bucket"),
                PreviewColumn(key="operation", label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f"),
                PreviewColumn(key="income", label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="expense", label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8", kind="currency"),
                PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
                PreviewColumn(key="comment", label="\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439"),
            ],
            rows=[
                {
                    "date": row.date,
                    "kaspi_bucket": derive_kaspi_bucket(row),
                    "operation": row.operation,
                    "income": row.income,
                    "expense": row.expense,
                    "detail": row.detail,
                    "comment": row.comment,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=KASPI_BUSINESS_GROUP,
        ),
        PreviewVariant(
            key="business_control_ledger",
            name="\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c",
            description=(
                "\u041a\u043e\u043d\u0442\u0440\u043e\u043b\u044c\u043d\u0430\u044f "
                "\u043b\u0435\u043d\u0442\u0430 \u0434\u043b\u044f \u0441\u0432\u0435\u0440\u043a\u0438 "
                "\u0438 \u0431\u044b\u0441\u0442\u0440\u043e\u0433\u043e \u0444\u0438\u043b\u044c\u0442\u0440\u0430."
            ),
            columns=[
                PreviewColumn(key="document_number", label="\u2116 \u0434\u043e\u043a\u0443\u043c\u0435\u043d\u0442\u0430"),
                PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
                PreviewColumn(
                    key="direction_label",
                    label="\u041d\u0430\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435",
                ),
                PreviewColumn(key="amount_abs", label="\u0421\u0443\u043c\u043c\u0430, \u20b8", kind="currency"),
                PreviewColumn(key="flow_group", label="\u041f\u043e\u0442\u043e\u043a"),
                PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
                PreviewColumn(key="comment", label="\u041a\u043e\u043c\u043c\u0435\u043d\u0442\u0430\u0440\u0438\u0439"),
            ],
            rows=[
                {
                    "document_number": row.document_number,
                    "date": row.date,
                    "direction_label": _direction_label(row.direction),
                    "amount_abs": row.income if row.income is not None else row.expense,
                    "flow_group": derive_flow_group(row),
                    "detail": row.detail,
                    "comment": row.comment,
                    "direction": row.direction,
                }
                for row in transactions
            ],
            group=KASPI_BUSINESS_GROUP,
        ),
    ]


def _build_ai_variant(transactions) -> PreviewVariant:
    return PreviewVariant(
        key="ai_categories",
        name="AI \u041a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u0438",
        description=(
            "\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u0430\u044f AI-\u0440\u0430\u0437\u043c\u0435\u0442\u043a\u0430 "
            "\u0442\u0440\u0430\u043d\u0437\u0430\u043a\u0446\u0438\u0439."
        ),
        columns=[
            PreviewColumn(key="date", label="\u0414\u0430\u0442\u0430"),
            PreviewColumn(key="category", label="AI \u043a\u0430\u0442\u0435\u0433\u043e\u0440\u0438\u044f"),
            PreviewColumn(key="detail", label="\u041a\u043e\u043d\u0442\u0440\u0430\u0433\u0435\u043d\u0442"),
            PreviewColumn(key="operation", label="\u041e\u043f\u0435\u0440\u0430\u0446\u0438\u044f"),
            PreviewColumn(key="income", label="\u041f\u0440\u0438\u0445\u043e\u0434, \u20b8", kind="currency"),
            PreviewColumn(key="expense", label="\u0420\u0430\u0441\u0445\u043e\u0434, \u20b8", kind="currency"),
        ],
        rows=[
            {
                "date": row.date,
                "category": row.category or "\u041f\u0440\u043e\u0447\u0435\u0435",
                "detail": row.detail,
                "operation": row.operation,
                "income": row.income,
                "expense": row.expense,
                "direction": row.direction,
            }
            for row in transactions
        ],
        group=PRIMARY_GROUP,
    )


def _direction_label(direction: str) -> str:
    return (
        "\u041f\u0440\u0438\u0445\u043e\u0434"
        if direction == "inflow"
        else "\u0420\u0430\u0441\u0445\u043e\u0434"
    )


def _build_daily_rows(transactions):
    grouped = defaultdict(lambda: {"income_total": 0.0, "expense_total": 0.0, "operations_count": 0})
    for row in transactions:
        current = grouped[row.date]
        current["income_total"] += row.income or 0.0
        current["expense_total"] += row.expense or 0.0
        current["operations_count"] += 1

    rows = []
    for date, values in grouped.items():
        direction = "inflow" if values["income_total"] >= values["expense_total"] else "outflow"
        rows.append(
            {
                "date": date,
                "income_total": round(values["income_total"], 2),
                "expense_total": round(values["expense_total"], 2),
                "net_total": round(values["income_total"] - values["expense_total"], 2),
                "operations_count": values["operations_count"],
                "direction": direction,
            }
        )
    return rows
