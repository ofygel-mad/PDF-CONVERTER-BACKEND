"""
Post-processing for raw OCR cells:
- Numeric cleanup (merge split numbers, normalise separators)
- Multi-line merging within a cell
- Low-confidence marking [?]
"""
from __future__ import annotations

import re

from app.services.scanned.types import OCRCell, TableRegion

_LOW_CONF = 0.60
_NUMBER_SPLIT_RE = re.compile(r"(\d[\d\s]*)[,.](\d{2})$")  # "1 250 ,00" → "1250.00"


def postprocess_cells(
    cells: list[OCRCell],
    region: TableRegion,
) -> list[OCRCell]:
    result = []
    for cell in cells:
        text = _merge_lines(cell.text)
        text = _fix_numeric(text)
        if cell.confidence < _LOW_CONF and text:
            text = f"[?] {text}"
        result.append(OCRCell(
            row=cell.row,
            col=cell.col,
            text=text,
            confidence=cell.confidence,
            struck_through=cell.struck_through,
        ))
    return result


def _merge_lines(text: str) -> str:
    """Collapse internal newlines that are OCR line breaks within one cell."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return " ".join(lines)


def _fix_numeric(text: str) -> str:
    """Clean up split numbers like '1 250 000 ,00' → '1250000.00'."""
    # Remove spaces inside digit groups
    text = re.sub(r"(\d)\s+(\d)", r"\1\2", text)
    # Normalise decimal separator
    m = _NUMBER_SPLIT_RE.search(text)
    if m:
        integer_part = m.group(1).replace(" ", "")
        decimal_part = m.group(2)
        text = text[:m.start()] + f"{integer_part}.{decimal_part}" + text[m.end():]
    return text
