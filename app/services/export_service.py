from __future__ import annotations

import csv
from io import BytesIO, StringIO

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from app.schemas.statement import ParsedStatement
from app.services.template_service import get_template
from app.services.variant_service import apply_template_to_variant, build_variants

HEADER_FILL = PatternFill(fill_type="solid", fgColor="1F4E79")
HEADER_FONT = Font(color="FFFFFF", bold=True)
INFLOW_FILL = PatternFill(fill_type="solid", fgColor="E2EFDA")
OUTFLOW_FILL = PatternFill(fill_type="solid", fgColor="FCE4D6")
TITLE_FONT = Font(bold=True, size=14)
LABEL_FONT = Font(bold=True)


def export_statement(statement: ParsedStatement, variant_key: str) -> bytes:
    variants = {variant.key: variant for variant in build_variants(statement)}
    if variant_key.startswith("template::"):
        template_id = variant_key.split("template::", maxsplit=1)[1]
        template = get_template(template_id)
        if template is None:
            raise ValueError("Шаблон для экспорта не найден.")
        base_variant = variants.get(template.base_variant_key)
        if base_variant is None:
            raise ValueError("Базовый вариант шаблона не найден.")
        variants[variant_key] = apply_template_to_variant(base_variant, template)
    if variant_key not in variants:
        raise ValueError("Неизвестный вариант таблицы.")

    variant = variants[variant_key]
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Preview Export"
    audit_sheet = workbook.create_sheet("Audit Trail")

    _write_metadata(sheet, statement)
    header_row = 9

    for column_index, column in enumerate(variant.columns, start=1):
        cell = sheet.cell(row=header_row, column=column_index, value=column.label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    for row_index, row in enumerate(variant.rows, start=header_row + 1):
        for column_index, column in enumerate(variant.columns, start=1):
            value = row.get(column.key)
            cell = sheet.cell(row=row_index, column=column_index, value=value)
            if row.get("direction") == "inflow":
                cell.fill = INFLOW_FILL
            elif row.get("direction") == "outflow":
                cell.fill = OUTFLOW_FILL

    for column_index, column in enumerate(variant.columns, start=1):
        max_length = max(
            len(str(column.label)),
            *(len(str(row.get(column.key, ""))) for row in variant.rows[:100]),
        )
        sheet.column_dimensions[get_column_letter(column_index)].width = min(max(max_length + 2, 12), 44)

    _write_audit_sheet(audit_sheet, statement, variant)

    stream = BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def _write_metadata(sheet, statement: ParsedStatement) -> None:
    metadata = statement.metadata
    sheet.merge_cells("A1:F1")
    sheet["A1"] = metadata.title
    sheet["A1"].font = TITLE_FONT

    top_rows = [
        ("Клиент:", metadata.account_holder, "Пополнения", metadata.totals.topup_total),
        ("Номер карты:", metadata.card_number, "Переводы", metadata.totals.transfer_total),
        ("Номер счета:", metadata.account_number, "Покупки", metadata.totals.purchase_total),
        ("Валюта счета:", metadata.currency, "Снятия", metadata.totals.cash_withdrawal_total),
        ("Доступно на старте:", metadata.opening_balance, None, None),
        ("Доступно на финише:", metadata.closing_balance, None, None),
    ]

    for row_number, (left_label, left_value, right_label, right_value) in enumerate(top_rows, start=2):
        sheet.cell(row=row_number, column=1, value=left_label).font = LABEL_FONT
        sheet.cell(row=row_number, column=2, value=left_value)
        if right_label is not None:
            sheet.cell(row=row_number, column=4, value=right_label)
        if right_value is not None:
            sheet.cell(row=row_number, column=5, value=right_value)


def export_statement_csv(statement: ParsedStatement, variant_key: str) -> bytes:
    """Return a UTF-8 CSV of the chosen variant (with BOM for Excel compatibility)."""
    variants = {variant.key: variant for variant in build_variants(statement)}
    if variant_key.startswith("template::"):
        template_id = variant_key.split("template::", maxsplit=1)[1]
        template = get_template(template_id)
        if template is None:
            raise ValueError("Шаблон для экспорта не найден.")
        base_variant = variants.get(template.base_variant_key)
        if base_variant is None:
            raise ValueError("Базовый вариант шаблона не найден.")
        variants[variant_key] = apply_template_to_variant(base_variant, template)
    if variant_key not in variants:
        raise ValueError("Неизвестный вариант таблицы.")

    variant = variants[variant_key]
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow([col.label for col in variant.columns])
    for row in variant.rows:
        writer.writerow([row.get(col.key, "") for col in variant.columns])

    # BOM for correct Cyrillic display in Excel on Windows
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def _write_audit_sheet(sheet, statement: ParsedStatement, variant) -> None:
    headers = [
        "Export row",
        "Export column",
        "Export header",
        "Value",
        "Source row",
        "Provenance",
        "Confidence",
        "Correction",
        "Template transform",
    ]
    for column_index, label in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column_index, value=label)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT

    transaction_lookup = {index: item for index, item in enumerate(statement.transactions, start=1)}
    row_pointer = 2
    for export_row_number, row in enumerate(variant.rows, start=1):
        source_row = transaction_lookup.get(export_row_number)
        for export_column_number, column in enumerate(variant.columns, start=1):
            value = row.get(column.key)
            provenance = source_row.source if source_row else "derived_variant"
            confidence = source_row.source_confidence if source_row else None
            correction = "yes" if source_row and source_row.corrected else "no"
            template_transform = "yes" if variant.template_id else "no"
            sheet.cell(row=row_pointer, column=1, value=export_row_number)
            sheet.cell(row=row_pointer, column=2, value=export_column_number)
            sheet.cell(row=row_pointer, column=3, value=column.label)
            sheet.cell(row=row_pointer, column=4, value=value)
            sheet.cell(row=row_pointer, column=5, value=export_row_number if source_row else None)
            sheet.cell(row=row_pointer, column=6, value=provenance)
            sheet.cell(row=row_pointer, column=7, value=confidence)
            sheet.cell(row=row_pointer, column=8, value=correction)
            sheet.cell(row=row_pointer, column=9, value=template_transform)
            row_pointer += 1

    for column_index in range(1, len(headers) + 1):
        sheet.column_dimensions[get_column_letter(column_index)].width = 20
