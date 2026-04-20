"""
Bridge: ScannedDocument → OCRReviewPayload

Feeds the first detected table into the existing
create_ocr_review_session → materialize_ocr_review → build_variants pipeline.
"""
from __future__ import annotations

import logging
import uuid
from typing import Any

from app.services.scanned.types import ScannedDocument, ScannedTable

log = logging.getLogger(__name__)


def to_ocr_review_payload(document: ScannedDocument) -> dict[str, Any]:
    """Convert ScannedDocument → OCRReviewPayload dict (matches existing schema)."""
    # Find the largest table across all pages
    best_table = _find_best_table(document)
    if best_table is None:
        return _empty_payload(document.source_filename)

    rows = _cells_to_rows(best_table)
    cell_conf = _cell_confidences(best_table)

    # Reuse available_fields from the existing ocr_service module if importable
    available_fields = _get_available_fields()

    return {
        "review_id": str(uuid.uuid4()),
        "source_filename": document.source_filename,
        "lines": _flatten_text(document),
        "tables": [
            {
                "table_index": 0,
                "rows": rows,
                "suggested_header_row_index": best_table.header_row_index,
                "cell_confidence": cell_conf,
            }
        ],
        "suggested_table_index": 0,
        "suggested_header_row_index": best_table.header_row_index,
        "available_fields": available_fields,
    }


def _find_best_table(document: ScannedDocument) -> ScannedTable | None:
    best = None
    best_size = 0
    for page in document.pages:
        for table in page.tables:
            size = len(table.cells)
            if size > best_size:
                best_size = size
                best = table
    return best


def _cells_to_rows(table: ScannedTable) -> list[list[str]]:
    if not table.cells:
        return []
    rows_count = max(c.row for c in table.cells) + 1
    cols_count = max(c.col for c in table.cells) + 1
    grid: list[list[str]] = [[""] * cols_count for _ in range(rows_count)]
    for cell in table.cells:
        grid[cell.row][cell.col] = cell.text
    return grid


def _cell_confidences(table: ScannedTable) -> list[list[float | None]]:
    if not table.cells:
        return []
    rows_count = max(c.row for c in table.cells) + 1
    cols_count = max(c.col for c in table.cells) + 1
    grid: list[list[float | None]] = [[None] * cols_count for _ in range(rows_count)]
    for cell in table.cells:
        grid[cell.row][cell.col] = round(cell.confidence, 3)
    return grid


def _flatten_text(document: ScannedDocument) -> list[str]:
    """Flatten all cell text into a line list (for OCR review text display)."""
    lines: list[str] = []
    for page in document.pages:
        for table in page.tables:
            for cell in table.cells:
                if cell.text.strip():
                    lines.append(cell.text.strip())
    return lines


def _empty_payload(filename: str) -> dict[str, Any]:
    return {
        "review_id": str(uuid.uuid4()),
        "source_filename": filename,
        "lines": [],
        "tables": [],
        "suggested_table_index": None,
        "suggested_header_row_index": None,
        "available_fields": _get_available_fields(),
    }


def _get_available_fields() -> list[dict[str, Any]]:
    try:
        from app.services.ocr_service import GENERIC_HEADER_TOKENS  # type: ignore
        return [{"key": k, "label": k, "required": False} for k in GENERIC_HEADER_TOKENS]
    except Exception:
        return [
            {"key": "date", "label": "Дата", "required": True},
            {"key": "income", "label": "Приход", "required": False},
            {"key": "expense", "label": "Расход", "required": False},
            {"key": "detail", "label": "Описание", "required": False},
            {"key": "amount", "label": "Сумма", "required": False},
        ]
