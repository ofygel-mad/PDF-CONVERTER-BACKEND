"""
Image preprocessing pipeline for scanned bank statement pages.

Steps per page:
  1. Grayscale conversion
  2. Otsu threshold → binary
  3. Deskew via Hough lines (±15° clamp)
  4. Denoise: fastNlMeansDenoising
  5. Contrast: CLAHE
  6. Stamp suppression: HSV saturation mask + inpaint
  7. Watermark reduction: subtract low-frequency component
  8. Quality score (Laplacian variance + binary density)
"""
from __future__ import annotations

import logging
import math

import numpy as np

from app.services.scanned.types import PreprocessedPage

log = logging.getLogger(__name__)

_MAX_SKEW_DEG = 15.0
_MIN_ROTATION_DEG = 0.2


def preprocess_page(bgr_img: np.ndarray, page_index: int = 0) -> PreprocessedPage:
    """Run full preprocessing pipeline on a single page image."""
    try:
        import cv2  # type: ignore
    except ImportError:
        log.warning("preprocessor: opencv not available — returning raw image")
        gray = np.mean(bgr_img, axis=2).astype(np.uint8) if bgr_img.ndim == 3 else bgr_img
        return PreprocessedPage(
            page_index=page_index,
            gray=gray,
            binary=gray,
            bgr=bgr_img,
            warnings=["opencv unavailable"],
        )

    warnings: list[str] = []

    # 1. Grayscale
    gray = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2GRAY)

    # 2. Otsu binary
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 3. Deskew
    angle, skew_warnings = _detect_skew(binary)
    warnings.extend(skew_warnings)
    if abs(angle) >= _MIN_ROTATION_DEG:
        bgr_img = _rotate(bgr_img, angle, cv2.BORDER_CONSTANT, (255, 255, 255))
        gray = _rotate(gray, angle, cv2.BORDER_CONSTANT, 255)
        _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    # 4. Denoise
    gray = cv2.fastNlMeansDenoising(gray, h=7)

    # 5. CLAHE contrast
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    gray = clahe.apply(gray)

    # 6. Stamp suppression
    bgr_img = suppress_stamps(bgr_img)

    # 7. Watermark reduction
    gray = _remove_watermark(gray)

    # 8. Quality score
    quality = _quality_score(gray, binary)
    if quality < 0.25:
        warnings.append(f"low_quality (score={quality:.2f})")

    return PreprocessedPage(
        page_index=page_index,
        gray=gray,
        binary=binary,
        bgr=bgr_img,
        rotation_angle=angle,
        quality_score=quality,
        warnings=warnings,
    )


def _detect_skew(binary: np.ndarray) -> tuple[float, list[str]]:
    """Detect page skew from horizontal Hough lines. Returns angle in degrees."""
    warnings: list[str] = []
    try:
        import cv2

        edges = cv2.Canny(binary, 50, 150, apertureSize=3)
        lines = cv2.HoughLinesP(edges, 1, math.pi / 180, threshold=100,
                                minLineLength=binary.shape[1] // 4, maxLineGap=20)
        if lines is None:
            return 0.0, warnings

        angles = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            if x2 != x1:
                angle = math.degrees(math.atan2(y2 - y1, x2 - x1))
                if abs(angle) < 45:   # near-horizontal lines only
                    angles.append(angle)

        if not angles:
            return 0.0, warnings

        median_angle = float(np.median(angles))
        if abs(median_angle) > _MAX_SKEW_DEG:
            warnings.append(f"skew_too_large ({median_angle:.1f}°) — auto-rotation skipped")
            return 0.0, warnings
        return median_angle, warnings
    except Exception as exc:
        log.debug("deskew failed: %s", exc)
        return 0.0, warnings


def _rotate(img: np.ndarray, angle: float, border_mode: int, border_value) -> np.ndarray:
    import cv2
    h, w = img.shape[:2]
    cx, cy = w // 2, h // 2
    M = cv2.getRotationMatrix2D((cx, cy), angle, 1.0)
    return cv2.warpAffine(img, M, (w, h),
                          flags=cv2.INTER_LINEAR,
                          borderMode=border_mode,
                          borderValue=border_value)


def suppress_stamps(bgr_img: np.ndarray) -> np.ndarray:
    """Remove red/blue stamp regions via HSV masking + inpainting."""
    try:
        import cv2
        hsv = cv2.cvtColor(bgr_img, cv2.COLOR_BGR2HSV)
        h, s, _ = cv2.split(hsv)
        # High-saturation red/blue regions (stamps)
        red_mask = ((h < 15) | (h > 165)) & (s > 140)
        blue_mask = ((h > 100) & (h < 135)) & (s > 140)
        stamp_mask = (red_mask | blue_mask).astype(np.uint8) * 255

        # Only suppress small/localised regions (< 5% of page area)
        total_pixels = bgr_img.shape[0] * bgr_img.shape[1]
        if np.sum(stamp_mask > 0) < 0.05 * total_pixels:
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            stamp_mask = cv2.dilate(stamp_mask, kernel, iterations=2)
            return cv2.inpaint(bgr_img, stamp_mask, 5, cv2.INPAINT_TELEA)
    except Exception as exc:
        log.debug("stamp suppression failed: %s", exc)
    return bgr_img


def _remove_watermark(gray: np.ndarray) -> np.ndarray:
    """Subtract low-frequency background component to reduce watermarks."""
    try:
        import cv2
        bg = cv2.GaussianBlur(gray, (0, 0), 40)
        diff = cv2.subtract(gray, bg)
        return cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)
    except Exception:
        return gray


def _quality_score(gray: np.ndarray, binary: np.ndarray) -> float:
    """Composite quality: sharpness (Laplacian variance) + binary text density."""
    try:
        import cv2
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        sharpness = min(1.0, lap_var / 500.0)
        density = float(np.sum(binary == 0)) / binary.size   # dark pixels = text
        density_score = 1.0 if 0.03 < density < 0.6 else 0.2
        return 0.7 * sharpness + 0.3 * density_score
    except Exception:
        return 0.5
