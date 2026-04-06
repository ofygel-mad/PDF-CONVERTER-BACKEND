from __future__ import annotations

from collections import defaultdict

from app.schemas.statement import (
    ParsedStatement,
    PreviewColumn,
    PreviewVariant,
    TransformationTemplate,
)


def build_variants(statement: ParsedStatement) -> list[PreviewVariant]:
    transactions = statement.transactions
    has_ai_categories = any(t.category for t in transactions)
    base: list[PreviewVariant] = [
        PreviewVariant(
            key="classic_financier",
            name="Финансист Классика",
            description="Максимально близко к целевому шаблону: приход, расход и слитая колонка деталей.",
            columns=[
                PreviewColumn(key="date", label="Дата"),
                PreviewColumn(key="income", label="Приход, ₸", kind="currency"),
                PreviewColumn(key="expense", label="Расход, ₸", kind="currency"),
                PreviewColumn(key="details_operation", label="Детали / Операция"),
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
        ),
        PreviewVariant(
            key="operation_split",
            name="Операция Отдельно",
            description="Разделяет вид операции и детали по отдельным колонкам для ручного анализа.",
            columns=[
                PreviewColumn(key="date", label="Дата"),
                PreviewColumn(key="operation", label="Операция"),
                PreviewColumn(key="detail", label="Детали"),
                PreviewColumn(key="income", label="Приход, ₸", kind="currency"),
                PreviewColumn(key="expense", label="Расход, ₸", kind="currency"),
                PreviewColumn(key="amount", label="Нетто, ₸", kind="currency"),
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
        ),
        PreviewVariant(
            key="counterparty_first",
            name="Контрагент Вперед",
            description="Сначала показывает получателя или источник денег, затем тип операции и направление.",
            columns=[
                PreviewColumn(key="date", label="Дата"),
                PreviewColumn(key="detail", label="Контрагент / Мерчант"),
                PreviewColumn(key="operation", label="Операция"),
                PreviewColumn(key="direction_label", label="Направление"),
                PreviewColumn(key="amount_abs", label="Сумма, ₸", kind="currency"),
            ],
            rows=[
                {
                    "date": row.date,
                    "detail": row.detail,
                    "operation": row.operation,
                    "direction_label": "Приход" if row.direction == "inflow" else "Расход",
                    "amount_abs": row.income if row.income is not None else row.expense,
                    "direction": row.direction,
                }
                for row in transactions
            ],
        ),
        PreviewVariant(
            key="daily_summary",
            name="Сводка По Дням",
            description="Группирует выписку по датам для управленческой картины cash-flow.",
            columns=[
                PreviewColumn(key="date", label="Дата"),
                PreviewColumn(key="income_total", label="Приход за день, ₸", kind="currency"),
                PreviewColumn(key="expense_total", label="Расход за день, ₸", kind="currency"),
                PreviewColumn(key="net_total", label="Нетто, ₸", kind="currency"),
                PreviewColumn(key="operations_count", label="Операций"),
            ],
            rows=_build_daily_rows(transactions),
        ),
        PreviewVariant(
            key="audit_flags",
            name="Аудит И Флаги",
            description="Подходит для проверки спорных операций и заметок перед финальной выгрузкой.",
            columns=[
                PreviewColumn(key="date", label="Дата"),
                PreviewColumn(key="direction_label", label="Направление"),
                PreviewColumn(key="amount_abs", label="Сумма, ₸", kind="currency"),
                PreviewColumn(key="operation", label="Операция"),
                PreviewColumn(key="detail", label="Детали"),
                PreviewColumn(key="flags_label", label="Флаги"),
                PreviewColumn(key="note", label="Примечание"),
            ],
            rows=[
                {
                    "date": row.date,
                    "direction_label": "Приход" if row.direction == "inflow" else "Расход",
                    "amount_abs": row.income if row.income is not None else row.expense,
                    "operation": row.operation,
                    "detail": row.detail,
                    "flags_label": ", ".join(row.flags) if row.flags else "OK",
                    "note": row.note,
                    "direction": row.direction,
                }
                for row in transactions
            ],
        ),
    ]
    if has_ai_categories:
        base.append(
            PreviewVariant(
                key="ai_categories",
                name="AI Категории",
                description="Каждой транзакции назначена категория расходов локальным AI-движком (без внешних API).",
                columns=[
                    PreviewColumn(key="date", label="Дата"),
                    PreviewColumn(key="category", label="Категория AI"),
                    PreviewColumn(key="detail", label="Контрагент"),
                    PreviewColumn(key="operation", label="Операция"),
                    PreviewColumn(key="income", label="Приход, ₸", kind="currency"),
                    PreviewColumn(key="expense", label="Расход, ₸", kind="currency"),
                ],
                rows=[
                    {
                        "date": row.date,
                        "category": row.category or "Прочее",
                        "detail": row.detail,
                        "operation": row.operation,
                        "income": row.income,
                        "expense": row.expense,
                        "direction": row.direction,
                    }
                    for row in transactions
                ],
            )
        )
    return base


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
