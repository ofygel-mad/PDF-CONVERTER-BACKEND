"""
Russian lemmatizer with graceful fallback chain:
  pymorphy3 → snowballstemmer → identity
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_morph = None
_stemmer = None
_mode: str = "identity"


def _init() -> None:
    global _morph, _stemmer, _mode
    if _mode != "identity":
        return
    try:
        import pymorphy3  # type: ignore
        _morph = pymorphy3.MorphAnalyzer()
        _mode = "pymorphy3"
        log.info("lemmatizer: using pymorphy3")
        return
    except Exception:
        pass
    try:
        from snowballstemmer import stemmer as _SnowballStemmer  # type: ignore
        _stemmer = _SnowballStemmer("russian")
        _mode = "snowball"
        log.info("lemmatizer: pymorphy3 unavailable, using snowball")
        return
    except Exception:
        pass
    log.warning("lemmatizer: no morphology library found, using identity")


def lemmatize(tokens: list[str]) -> list[str]:
    """Return list of lemmas/stems for the given lowercase tokens."""
    _init()
    if _mode == "pymorphy3" and _morph is not None:
        result = []
        for tok in tokens:
            parsed = _morph.parse(tok)
            result.append(parsed[0].normal_form if parsed else tok)
        return result
    if _mode == "snowball" and _stemmer is not None:
        return [_stemmer.stemWord(tok) for tok in tokens]
    return tokens


def lemmatize_word(word: str) -> str:
    return lemmatize([word])[0]
