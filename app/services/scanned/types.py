"""Dataclasses for the scanned document OCR pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PreprocessedPage:
    page_index: int
    gray: Any          # np.ndarray (grayscale)
    binary: Any        # np.ndarray (Otsu threshold)
    bgr: Any           # np.ndarray (colour, post-processing)
    rotation_angle: float = 0.0
    quality_score: float = 1.0
    warnings: list[str] = field(default_factory=list)


@dataclass
class CellBBox:
    row: int
    col: int
    x: int
    y: int
    w: int
    h: int


@dataclass
class TableRegion:
    bbox: tuple[int, int, int, int]   # (x, y, w, h) in page coords
    cells: list[CellBBox] = field(default_factory=list)
    rows: int = 0
    cols: int = 0
    source: str = "morphological"     # "morphological" | "ppstructure"


@dataclass
class OCRCell:
    row: int
    col: int
    text: str
    confidence: float = 1.0
    struck_through: bool = False


@dataclass
class ScannedTable:
    page_index: int
    region: TableRegion
    cells: list[OCRCell] = field(default_factory=list)
    header_row_index: int = 0


@dataclass
class ScannedPage:
    page_index: int
    rotation_angle: float
    quality_score: float
    tables: list[ScannedTable] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class ScannedDocument:
    source_filename: str
    pages: list[ScannedPage] = field(default_factory=list)
    avg_confidence: float = 1.0
    warnings: list[str] = field(default_factory=list)
