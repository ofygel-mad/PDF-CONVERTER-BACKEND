"""
Scanned document OCR routes.

POST /transforms/scan                  → upload → ScanResponse
GET  /transforms/scan/{scan_id}/docx   → download .docx
POST /transforms/scan/{scan_id}/to-review → push into OCR review flow
"""
from __future__ import annotations

import logging
import uuid
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from app.schemas.scanned import PreviewTableRow, ScanResponse, ScanResultMeta

log = logging.getLogger(__name__)

router = APIRouter(tags=["scanned"])

# In-memory scan store (replace with DB persistence when needed)
_scan_store: dict[str, dict] = {}


@router.post("/transforms/scan", response_model=ScanResponse)
async def scan_document(file: UploadFile = File(...)) -> ScanResponse:
    """
    Upload a scanned PDF or image.
    Returns scan_id + table preview for display in the UI.
    """
    try:
        from app.services.scanned.structured_builder import build_scanned_document
    except ImportError:
        raise HTTPException(status_code=503, detail="Scanned OCR pipeline not available")

    content = await file.read()
    filename = file.filename or "scan.pdf"

    document = build_scanned_document(filename, content)
    scan_id = str(uuid.uuid4()).replace("-", "")

    # Build preview tables
    preview: list[PreviewTableRow] = []
    for page in document.pages:
        for table in page.tables:
            cells = table.cells
            if not cells:
                continue
            rows_count = max(c.row for c in cells) + 1
            cols_count = max(c.col for c in cells) + 1
            grid: list[list[str]] = [[""] * cols_count for _ in range(rows_count)]
            for c in cells:
                grid[c.row][c.col] = c.text

            headers = grid[table.header_row_index] if rows_count > 0 else []
            data_rows = [r for i, r in enumerate(grid) if i != table.header_row_index]
            avg_conf = sum(c.confidence for c in cells) / max(len(cells), 1)

            preview.append(PreviewTableRow(
                page=page.page_index + 1,
                headers=headers,
                rows=data_rows[:10],  # preview: first 10 data rows
                confidence=round(avg_conf, 3),
            ))

    # Persist for downstream endpoints
    _scan_store[scan_id] = {"document": document, "filename": filename}

    rotation_angles = [p.rotation_angle for p in document.pages]
    warnings = list(document.warnings)
    for page in document.pages:
        warnings.extend(page.warnings)

    meta = ScanResultMeta(
        scan_id=scan_id,
        source_filename=filename,
        page_count=len(document.pages),
        avg_confidence=round(document.avg_confidence, 3),
        rotation_angles=rotation_angles,
        warnings=list(dict.fromkeys(warnings)),  # deduplicate
        tables_found=sum(len(p.tables) for p in document.pages),
    )

    return ScanResponse(scan_id=scan_id, meta=meta, preview_tables=preview)


@router.get("/transforms/scan/{scan_id}/docx")
async def download_scan_docx(scan_id: str) -> StreamingResponse:
    """Download the structured .docx built from a previously uploaded scan."""
    entry = _scan_store.get(scan_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Скан не найден")

    try:
        from app.services.scanned.docx_writer import write_docx
    except ImportError:
        raise HTTPException(status_code=503, detail="python-docx not available")

    docx_bytes = write_docx(entry["document"])
    if not docx_bytes:
        raise HTTPException(status_code=503, detail="Не удалось создать Word-документ")

    filename = entry["filename"].rsplit(".", 1)[0] + "_ocr.docx"
    return StreamingResponse(
        BytesIO(docx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/transforms/scan/{scan_id}/to-review")
async def scan_to_review(scan_id: str):
    """
    Push a completed scan into the existing OCR review flow.
    Returns a full PreviewResponse as if the file had been uploaded normally.
    """
    entry = _scan_store.get(scan_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Скан не найден")

    try:
        from app.services.scanned.review_adapter import to_ocr_review_payload
        from app.services.ocr_review_service import create_ocr_review_session  # type: ignore
    except ImportError as exc:
        raise HTTPException(status_code=503, detail=f"OCR review pipeline not available: {exc}")

    document = entry["document"]
    payload = to_ocr_review_payload(document)

    # Delegate to existing OCR review session creation
    review_id = await create_ocr_review_session(payload)

    return {
        "review_id": review_id,
        "message": "Скан передан в OCR-проверку",
        "source_filename": document.source_filename,
        "tables_found": sum(len(p.tables) for p in document.pages),
    }
