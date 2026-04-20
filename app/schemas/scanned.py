"""Pydantic schemas for the scanned document OCR API."""
from __future__ import annotations

from pydantic import BaseModel, Field


class ScanResultMeta(BaseModel):
    scan_id: str
    source_filename: str
    page_count: int
    avg_confidence: float
    rotation_angles: list[float] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    tables_found: int = 0


class PreviewTableRow(BaseModel):
    page: int
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    confidence: float = 1.0


class ScanResponse(BaseModel):
    scan_id: str
    meta: ScanResultMeta
    preview_tables: list[PreviewTableRow] = Field(default_factory=list)
