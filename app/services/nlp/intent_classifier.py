"""
Intent classifier using precomputed intent embeddings.

Loads intent_embeddings.npy and intents.json at warmup.
Falls back to keyword matching if embeddings unavailable.
"""
from __future__ import annotations

import json
import logging
import os

import numpy as np

from app.services.nlp.types import IntentId

log = logging.getLogger(__name__)

_intent_labels: list[str] = []
_intent_matrix: np.ndarray | None = None  # shape: (n_intents, dim)
_keyword_index: dict[str, str] = {}       # keyword → intent_id (fallback)

_KEYWORDS: dict[str, str] = {
    "нетто": IntentId.compute_net,
    "net": IntentId.compute_net,
    "приход минус расход": IntentId.compute_net,
    "ндс": IntentId.compute_vat,
    "налог": IntentId.compute_vat,
    "vat": IntentId.compute_vat,
    "комиссия": IntentId.compute_fee,
    "commission": IntentId.compute_fee,
    "курс": IntentId.fx_convert,
    "конвертировать": IntentId.fx_convert,
    "пересчитать": IntentId.fx_convert,
    "доллар": IntentId.fx_convert,
    "евро": IntentId.fx_convert,
    "валют": IntentId.fx_convert,
    "умножить": IntentId.scale_by_constant,
    "умножь": IntentId.scale_by_constant,
    "процент": IntentId.scale_by_constant,
    "переименовать": IntentId.rename_column,
    "переименуй": IntentId.rename_column,
    "удалить": IntentId.remove_column,
    "убрать колонку": IntentId.remove_column,
    "поставить после": IntentId.reorder_column,
    "переместить": IntentId.reorder_column,
    "только расход": IntentId.filter_rows_direction,
    "только приход": IntentId.filter_rows_direction,
    "убрать мелк": IntentId.filter_rows_threshold,
    "предыдущую": IntentId.reference_previous,
    "предыдущей": IntentId.reference_previous,
    "делить": IntentId.assign_formula,
    "поделить": IntentId.assign_formula,
    "разделить": IntentId.assign_formula,
    "вычесть": IntentId.assign_formula,
    "прибавить": IntentId.assign_formula,
    "формул": IntentId.assign_formula,
    "равно полю": IntentId.assign_source_field,
    "= поле": IntentId.assign_source_field,
    "берём поле": IntentId.assign_source_field,
}


def load(embeddings_path: str | None = None, intents_path: str | None = None) -> bool:
    global _intent_labels, _intent_matrix

    base = os.path.join(os.path.dirname(__file__), "..", "..", "data", "nlp")
    base = os.path.normpath(base)

    if embeddings_path is None:
        embeddings_path = os.path.join(base, "intent_embeddings.npy")
    if intents_path is None:
        intents_path = os.path.join(base, "intents.json")

    try:
        if os.path.exists(intents_path):
            with open(intents_path, encoding="utf-8") as f:
                data = json.load(f)
            _intent_labels = [entry["intent"] for entry in data]
    except Exception as exc:
        log.warning("intent_classifier: failed to load intents.json: %s", exc)

    try:
        if os.path.exists(embeddings_path):
            _intent_matrix = np.load(embeddings_path)
            log.info("intent_classifier: loaded %d intent vectors", len(_intent_labels))
            return True
    except Exception as exc:
        log.warning("intent_classifier: failed to load embeddings: %s", exc)

    log.info("intent_classifier: embeddings unavailable, using keyword fallback")
    return False


def classify(text: str) -> tuple[str, float]:
    """Return (intent_id, confidence). Falls back to keyword matching."""
    if _intent_matrix is not None and _intent_labels:
        try:
            from app.services.nlp import embeddings as emb
            vec = emb.embed(text)
            scores = _intent_matrix @ vec  # cosine (vectors are pre-normalised)
            best_idx = int(np.argmax(scores))
            return _intent_labels[best_idx], float(scores[best_idx])
        except Exception as exc:
            log.debug("intent_classifier: embedding inference failed: %s", exc)

    return _keyword_classify(text)


def _keyword_classify(text: str) -> tuple[str, float]:
    tl = text.lower()
    for kw, intent in _KEYWORDS.items():
        if kw in tl:
            return intent, 0.60
    return IntentId.clarify_needed, 0.30
