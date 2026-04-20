"""
OCR engine wrapper — uniform interface over PaddleOCR and RapidOCR.

Priority: PaddleOCR PP-OCRv4 → RapidOCR → empty (fail silently).
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.scanned.types import CellBBox, OCRCell

log = logging.getLogger(__name__)

_paddle_ocr = None
_rapid_ocr = None
_mode: str = "unavailable"


def _init() -> None:
    global _paddle_ocr, _rapid_ocr, _mode
    if _mode != "unavailable":
        return
    try:
        from paddleocr import PaddleOCR  # type: ignore
        _paddle_ocr = PaddleOCR(
            use_angle_cls=True,
            lang="ru",
            use_gpu=False,
            show_log=False,
        )
        _mode = "paddle"
        log.info("ocr_engine: using PaddleOCR (ru)")
        return
    except Exception as exc:
        log.debug("ocr_engine: PaddleOCR unavailable (%s)", exc)
    try:
        from rapidocr_onnxruntime import RapidOCR  # type: ignore
        _rapid_ocr = RapidOCR()
        _mode = "rapid"
        log.info("ocr_engine: using RapidOCR")
        return
    except Exception as exc:
        log.debug("ocr_engine: RapidOCR unavailable (%s)", exc)
    log.warning("ocr_engine: no OCR engine available — results will be empty")


def ocr_cells(
    page_img: np.ndarray,
    cells: list[CellBBox],
    margin: int = 4,
) -> list[OCRCell]:
    """
    Run OCR on each cell crop. Returns OCRCell list.
    Cells with confidence < 0.35 are marked low-confidence.
    """
    _init()
    results: list[OCRCell] = []
    h, w = page_img.shape[:2]

    for cell in cells:
        x1 = max(0, cell.x - margin)
        y1 = max(0, cell.y - margin)
        x2 = min(w, cell.x + cell.w + margin)
        y2 = min(h, cell.y + cell.h + margin)
        crop = page_img[y1:y2, x1:x2]
        if crop.size == 0:
            results.append(OCRCell(row=cell.row, col=cell.col, text="", confidence=0.0))
            continue
        text, conf = _run_ocr(crop)
        struck = _is_struck_through(crop)
        results.append(OCRCell(
            row=cell.row, col=cell.col,
            text=text, confidence=conf,
            struck_through=struck,
        ))
    return results


def _run_ocr(crop: np.ndarray) -> tuple[str, float]:
    if _mode == "paddle" and _paddle_ocr is not None:
        return _paddle_run(crop)
    if _mode == "rapid" and _rapid_ocr is not None:
        return _rapid_run(crop)
    return "", 0.0


def _paddle_run(crop: np.ndarray) -> tuple[str, float]:
    try:
        res = _paddle_ocr.ocr(crop, cls=True)
        if not res or not res[0]:
            return "", 0.0
        texts, confs = [], []
        for line in res[0]:
            if line and len(line) >= 2:
                texts.append(str(line[1][0]))
                confs.append(float(line[1][1]))
        text = "\n".join(texts)
        conf = float(np.mean(confs)) if confs else 0.0
        return text, conf
    except Exception as exc:
        log.debug("paddle ocr failed: %s", exc)
        return "", 0.0


def _rapid_run(crop: np.ndarray) -> tuple[str, float]:
    try:
        res, _ = _rapid_ocr(crop)
        if not res:
            return "", 0.0
        texts = [line[1] for line in res if line and len(line) > 1]
        confs = [float(line[2]) for line in res if line and len(line) > 2]
        return "\n".join(texts), float(np.mean(confs)) if confs else 0.5
    except Exception as exc:
        log.debug("rapid ocr failed: %s", exc)
        return "", 0.0


def _is_struck_through(crop: np.ndarray) -> bool:
    """Detect horizontal strikethrough line at 40%-60% of cell height."""
    try:
        import cv2
        if crop.ndim == 3:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        else:
            gray = crop
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        h = binary.shape[0]
        mid_band = binary[int(0.4 * h):int(0.6 * h), :]
        col_sum = np.sum(mid_band, axis=0)
        # Struck if >60% of columns have a dark pixel in the middle band
        return float(np.mean(col_sum > 0)) > 0.6
    except Exception:
        return False
