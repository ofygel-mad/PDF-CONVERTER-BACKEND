"""
Main orchestrator for the scanned document pipeline.

build_scanned_document(filename, file_bytes) → ScannedDocument

Pipeline:
  PDF/image → pages (pymupdf/PIL) → preprocess → detect tables →
  OCR cells → post-process → ScannedDocument
"""
from __future__ import annotations

import logging

import numpy as np

from app.core.config import settings
from app.services.scanned.types import (
    ScannedDocument,
    ScannedPage,
    ScannedTable,
)

log = logging.getLogger(__name__)


def build_scanned_document(
    filename: str,
    file_bytes: bytes,
) -> ScannedDocument:
    """Full pipeline. Returns ScannedDocument with all tables extracted."""
    pages_bgr = _rasterize(file_bytes, filename)
    if not pages_bgr:
        return ScannedDocument(
            source_filename=filename,
            warnings=["no_pages_extracted"],
        )

    from app.services.scanned.preprocessor import preprocess_page
    from app.services.scanned.table_detector import detect_tables
    from app.services.scanned.ocr_engine import ocr_cells
    from app.services.scanned.postprocessor import postprocess_cells

    scanned_pages: list[ScannedPage] = []
    all_confs: list[float] = []
    doc_warnings: list[str] = []

    max_pages = settings.scan_max_pages
    if len(pages_bgr) > max_pages:
        doc_warnings.append(f"truncated_to_{max_pages}_pages")
        pages_bgr = pages_bgr[:max_pages]

    for page_idx, bgr in enumerate(pages_bgr):
        # 1. Preprocess
        prep = preprocess_page(bgr, page_index=page_idx)

        # 2. Detect tables (on binary image)
        tables = detect_tables(prep.binary)

        # 3. OCR + post-process per table
        scanned_tables: list[ScannedTable] = []
        for table_region in tables:
            raw_cells = ocr_cells(prep.bgr, table_region.cells)
            cells = postprocess_cells(raw_cells, table_region)
            header_row = _detect_header_row(cells)
            scanned_tables.append(ScannedTable(
                page_index=page_idx,
                region=table_region,
                cells=cells,
                header_row_index=header_row,
            ))
            all_confs.extend(c.confidence for c in cells if c.confidence > 0)

        page_warnings = list(prep.warnings)
        if prep.quality_score < settings.scan_min_quality_score:
            page_warnings.append("low_quality")

        scanned_pages.append(ScannedPage(
            page_index=page_idx,
            rotation_angle=prep.rotation_angle,
            quality_score=prep.quality_score,
            tables=scanned_tables,
            warnings=page_warnings,
        ))

    avg_conf = float(np.mean(all_confs)) if all_confs else 0.0
    return ScannedDocument(
        source_filename=filename,
        pages=scanned_pages,
        avg_confidence=avg_conf,
        warnings=doc_warnings,
    )


def _rasterize(file_bytes: bytes, filename: str) -> list[np.ndarray]:
    """Convert PDF or image bytes to list of BGR numpy arrays at 300 DPI."""
    fname_lower = filename.lower()
    if fname_lower.endswith(".pdf"):
        return _rasterize_pdf(file_bytes)
    return _rasterize_image(file_bytes)


def _rasterize_pdf(pdf_bytes: bytes) -> list[np.ndarray]:
    try:
        import fitz  # pymupdf  # type: ignore
        import cv2
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        pages = []
        for page in doc:
            mat = fitz.Matrix(300 / 72, 300 / 72)  # 300 DPI
            pix = page.get_pixmap(matrix=mat, alpha=False)
            arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)
            pages.append(bgr)
        doc.close()
        return pages
    except Exception as exc:
        log.warning("pdf rasterize failed: %s", exc)
        return []


def _rasterize_image(img_bytes: bytes) -> list[np.ndarray]:
    try:
        import cv2
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is not None:
            return [img]
    except Exception as exc:
        log.debug("image rasterize failed: %s", exc)
    try:
        from PIL import Image  # type: ignore
        import io
        import cv2
        pil_img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        arr = np.array(pil_img)
        return [cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)]
    except Exception as exc:
        log.warning("image rasterize (PIL) failed: %s", exc)
    return []


def _detect_header_row(cells) -> int:
    """Heuristic: first row where all cells are short (<4 chars avg) is header."""
    if not cells:
        return 0
    rows: dict[int, list] = {}
    for c in cells:
        rows.setdefault(c.row, []).append(c)
    for row_idx in sorted(rows.keys())[:3]:
        row_cells = rows[row_idx]
        avg_len = sum(len(c.text) for c in row_cells) / max(len(row_cells), 1)
        if avg_len < 20:   # short header labels
            return row_idx
    return 0
