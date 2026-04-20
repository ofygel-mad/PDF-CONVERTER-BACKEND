"""Unicode normalization and basic text cleaning for Russian input."""
from __future__ import annotations

import re
import unicodedata


def normalize(text: str) -> str:
    """NFC normalize, lowercase, collapse whitespace. Preserves digits, %, -, /."""
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r"[^\w\s%\-/.,]", " ", text, flags=re.UNICODE)
    text = re.sub(r"\s+", " ", text).strip()
    return text
