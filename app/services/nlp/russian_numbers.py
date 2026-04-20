"""Parse numbers from Russian text: digits, words, percentages."""
from __future__ import annotations

import re

_WORD_MAP: dict[str, float] = {
    "ноль": 0, "нуль": 0,
    "один": 1, "одна": 1, "одно": 1,
    "два": 2, "две": 2,
    "три": 3, "четыре": 4, "пять": 5,
    "шесть": 6, "семь": 7, "восемь": 8,
    "девять": 9, "десять": 10,
    "одиннадцать": 11, "двенадцать": 12, "тринадцать": 13,
    "четырнадцать": 14, "пятнадцать": 15, "шестнадцать": 16,
    "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40,
    "пятьдесят": 50, "шестьдесят": 60, "семьдесят": 70,
    "восемьдесят": 80, "девяносто": 90, "сто": 100,
    "двести": 200, "триста": 300, "четыреста": 400, "пятьсот": 500,
    "шестьсот": 600, "семьсот": 700, "восемьсот": 800, "девятьсот": 900,
    "тысяча": 1000, "тысяч": 1000, "тыс": 1000,
    "миллион": 1_000_000, "млн": 1_000_000,
    "полтора": 1.5, "полторы": 1.5,
    "четверть": 0.25, "половина": 0.5,
}

_DIGIT_RE = re.compile(r"\b(\d[\d\s]*(?:[.,]\d+)?)\s*(%)?")


def parse_number(text: str) -> float | None:
    """Return first numeric value found (digit or word form). Percent → 0..1."""
    # digit patterns first
    m = _DIGIT_RE.search(text)
    if m:
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw)
            if m.group(2):
                return val / 100.0
            return val
        except ValueError:
            pass

    # word patterns
    tokens = text.lower().split()
    for i, tok in enumerate(tokens):
        if tok in _WORD_MAP:
            val = _WORD_MAP[tok]
            # check if followed by "процент"
            if i + 1 < len(tokens) and tokens[i + 1].startswith("процент"):
                return val / 100.0
            return val

    return None


def parse_all_numbers(text: str) -> list[float]:
    """Return all numeric literals in order of appearance."""
    results: list[float] = []
    for m in _DIGIT_RE.finditer(text):
        raw = m.group(1).replace(" ", "").replace(",", ".")
        try:
            val = float(raw)
            if m.group(2):
                val /= 100.0
            results.append(val)
        except ValueError:
            pass
    return results


def parse_all_percentages(text: str) -> list[float]:
    """Return explicit percentage values as 0..1 fractions."""
    pct_re = re.compile(r"(\d+(?:[.,]\d+)?)\s*%")
    results = []
    for m in pct_re.finditer(text):
        try:
            results.append(float(m.group(1).replace(",", ".")) / 100.0)
        except ValueError:
            pass
    # also "N процент"
    tok_re = re.compile(r"(\d+(?:[.,]\d+)?)\s+процент")
    for m in tok_re.finditer(text):
        try:
            results.append(float(m.group(1).replace(",", ".")) / 100.0)
        except ValueError:
            pass
    return results
