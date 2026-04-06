from __future__ import annotations

from app.core.config import settings
from app.schemas.statement import VisionStatus


def get_vision_status() -> VisionStatus:
    azure_ocr_available = bool(
        settings.azure_document_intelligence_endpoint and settings.azure_document_intelligence_key
    )
    local_ocr_available = False
    try:
        import rapidocr  # noqa: F401
        import onnxruntime  # noqa: F401

        local_ocr_available = True
    except ImportError:
        local_ocr_available = False

    ocr_available = azure_ocr_available or local_ocr_available
    if azure_ocr_available:
        ocr_backend = "azure-document-intelligence"
    elif local_ocr_available:
        ocr_backend = "rapidocr-local"
    else:
        ocr_backend = "disabled"

    try:
        import ultralytics  # noqa: F401
    except ImportError:
        return VisionStatus(
            available=False,
            backend="disabled",
            ocr_available=ocr_available,
            ocr_backend=ocr_backend,
            note="AI vision module is optional. OCR parsing is handled separately and can process scanned PDFs or image statements when configured.",
            use_cases=[
                "detect statement/table regions on scanned pages",
                "crop receipts or screenshot fragments before OCR",
                "route image-heavy documents into a separate vision pipeline",
            ],
        )

    return VisionStatus(
        available=True,
        backend="ultralytics-ai",
        ocr_available=ocr_available,
        ocr_backend=ocr_backend,
        note="AI vision module is available for scan-heavy or image-based documents.",
        use_cases=[
            "detect statement/table regions on scanned pages",
            "crop receipts or screenshot fragments before OCR",
            "route image-heavy documents into a separate vision pipeline",
        ],
    )
