"""
Two-pass table detection for scanned bank statements.

Pass A — Morphological line detection (fast, clear grids).
Pass B — PaddleOCR PP-Structure fallback (borderless / skewed tables).
"""
from __future__ import annotations

import logging

import numpy as np

from app.services.scanned.types import CellBBox, TableRegion

log = logging.getLogger(__name__)

_MIN_CELLS = 2
_HIGH_VARIANCE_THRESHOLD = 3.0  # aspect-ratio variance → trigger Pass B


def detect_tables(page_img: np.ndarray) -> list[TableRegion]:
    """Detect tables in a preprocessed binary page image. Returns TableRegion list."""
    tables = _detect_morphological(page_img)
    if _needs_ppstructure_fallback(tables):
        pp_tables = _detect_ppstructure(page_img)
        if pp_tables:
            return pp_tables
    return tables


# ── Pass A: Morphological ──────────────────────────────────────────────────────

def _detect_morphological(img: np.ndarray) -> list[TableRegion]:
    try:
        import cv2
    except ImportError:
        log.warning("table_detector: opencv unavailable")
        return []

    # Ensure binary (white bg, black lines)
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    else:
        _, binary = cv2.threshold(img, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    h, w = binary.shape

    # Horizontal lines: erode with wide kernel
    h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (max(w // 20, 40), 1))
    h_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, h_kernel)

    # Vertical lines: erode with tall kernel
    v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(h // 20, 40)))
    v_lines = cv2.morphologyEx(binary, cv2.MORPH_OPEN, v_kernel)

    # Combine
    grid = cv2.add(h_lines, v_lines)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    grid = cv2.dilate(grid, kernel, iterations=2)

    # Find table bounding boxes
    contours, _ = cv2.findContours(grid, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    tables: list[TableRegion] = []
    for cnt in contours:
        x, y, cw, ch = cv2.boundingRect(cnt)
        if cw < 50 or ch < 30:
            continue
        cells = _extract_cells(h_lines[y:y+ch, x:x+cw], v_lines[y:y+ch, x:x+cw], x, y)
        if len(cells) < _MIN_CELLS:
            continue
        rows = (max(c.row for c in cells) + 1) if cells else 0
        cols = (max(c.col for c in cells) + 1) if cells else 0
        tables.append(TableRegion(
            bbox=(x, y, cw, ch),
            cells=cells,
            rows=rows,
            cols=cols,
            source="morphological",
        ))

    return tables


def _extract_cells(h_mask: np.ndarray, v_mask: np.ndarray, ox: int, oy: int) -> list[CellBBox]:
    """Reconstruct cell grid from horizontal and vertical line masks."""
    try:
        import cv2
        # Find horizontal line positions
        h_proj = np.sum(h_mask, axis=1) > h_mask.shape[1] * 0.3
        v_proj = np.sum(v_mask, axis=0) > v_mask.shape[0] * 0.3

        h_positions = _proj_to_positions(h_proj)
        v_positions = _proj_to_positions(v_proj)

        if len(h_positions) < 2 or len(v_positions) < 2:
            return []

        cells = []
        for ri in range(len(h_positions) - 1):
            for ci in range(len(v_positions) - 1):
                cy = h_positions[ri]
                ch = h_positions[ri + 1] - cy
                cx = v_positions[ci]
                cw = v_positions[ci + 1] - cx
                if cw > 5 and ch > 5:
                    cells.append(CellBBox(row=ri, col=ci,
                                          x=ox + cx, y=oy + cy,
                                          w=cw, h=ch))
        return cells
    except Exception as exc:
        log.debug("cell extraction failed: %s", exc)
        return []


def _proj_to_positions(proj: np.ndarray) -> list[int]:
    """Convert boolean projection to line boundary positions."""
    positions = []
    in_line = False
    for i, val in enumerate(proj):
        if val and not in_line:
            positions.append(i)
            in_line = True
        elif not val:
            in_line = False
    if not positions or positions[-1] < len(proj) - 1:
        positions.append(len(proj))
    return positions


# ── Pass B: PP-Structure fallback ──────────────────────────────────────────────

def _needs_ppstructure_fallback(tables: list[TableRegion]) -> bool:
    if len(tables) < 1:
        return True
    total_cells = sum(len(t.cells) for t in tables)
    if total_cells < _MIN_CELLS:
        return True
    # Check aspect-ratio variance
    if tables:
        widths = [t.bbox[2] for t in tables]
        heights = [t.bbox[3] for t in tables]
        if len(widths) > 1:
            ar = [w / h for w, h in zip(widths, heights) if h > 0]
            if ar and (max(ar) / (min(ar) + 1e-9)) > _HIGH_VARIANCE_THRESHOLD:
                return True
    return False


def _detect_ppstructure(img: np.ndarray) -> list[TableRegion]:
    """Use PaddleOCR PP-Structure for table detection."""
    try:
        from paddleocr import PPStructure  # type: ignore
        engine = PPStructure(table=True, lang="ch", show_log=False)
        if img.ndim == 2:
            import cv2
            img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
        result = engine(img)
        tables: list[TableRegion] = []
        for item in result:
            if item.get("type") != "table":
                continue
            bbox = item.get("bbox", [0, 0, img.shape[1], img.shape[0]])
            x, y, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
            # PP-Structure returns HTML table — parse rows/cols
            cells, rows, cols = _parse_ppstructure_cells(item, x, y)
            tables.append(TableRegion(
                bbox=(x, y, x2 - x, y2 - y),
                cells=cells,
                rows=rows,
                cols=cols,
                source="ppstructure",
            ))
        return tables
    except ImportError:
        log.debug("ppstructure: paddleocr not available")
    except Exception as exc:
        log.warning("ppstructure detection failed: %s", exc)
    return []


def _parse_ppstructure_cells(
    item: dict, ox: int, oy: int
) -> tuple[list[CellBBox], int, int]:
    """Parse PP-Structure result HTML into CellBBox list."""
    cells: list[CellBBox] = []
    rows = cols = 0
    try:
        from html.parser import HTMLParser

        class _TableParser(HTMLParser):
            def __init__(self):
                super().__init__()
                self.row = self.col = 0
                self.cells: list[CellBBox] = []
            def handle_starttag(self, tag, attrs):
                if tag == "tr":
                    self.col = 0
                elif tag in ("td", "th"):
                    self.cells.append(CellBBox(
                        row=self.row, col=self.col,
                        x=ox, y=oy, w=20, h=20,
                    ))
                    self.col += 1
            def handle_endtag(self, tag):
                if tag == "tr":
                    self.row += 1

        html = item.get("res", {}).get("html", "")
        parser = _TableParser()
        parser.feed(html)
        cells = parser.cells
        rows = max((c.row for c in cells), default=0) + 1
        cols = max((c.col for c in cells), default=0) + 1
    except Exception as exc:
        log.debug("ppstructure cell parse failed: %s", exc)
    return cells, rows, cols
