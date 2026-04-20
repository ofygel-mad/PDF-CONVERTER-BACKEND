"""
Russian phonetic encoder (simplified Metaphone-RU).

Collapses vowel-swap typos and voiced/unvoiced pairs so that:
  "камиссия" == "комиссия"
  "абмена"   == "обмена"
  "задание"  == "задание" (unchanged)
"""
from __future__ import annotations

import re

# Unstressed vowel normalisation: А/О → A, И/Е/Э/Ы → I
_VOWEL_MAP = str.maketrans("аоуэыиеёюя", "aauuiiiiau")

# Voiced→unvoiced (final devoicing and assimilation)
_DEVOICE = str.maketrans("бвгджз", "пфктшс")

# Doubled consonants → single
_DOUBLE_RE = re.compile(r"(.)\1+")


def phonetic_key(word: str) -> str:
    """Return phonetic key for a Russian word (lowercase input expected)."""
    w = word.lower()

    # 1. Remove soft/hard sign
    w = w.replace("ъ", "").replace("ь", "")

    # 2. Normalise unstressed vowels (О↔А, Е/И↔И)
    w = w.translate(_VOWEL_MAP)

    # 3. Final devoicing + assimilation
    w = w.translate(_DEVOICE)

    # 4. Collapse doubles
    w = _DOUBLE_RE.sub(r"\1", w)

    # 5. Remove remaining non-ASCII (was Cyrillic, now only a-z remain)
    w = re.sub(r"[^a-z]", "", w)

    return w
