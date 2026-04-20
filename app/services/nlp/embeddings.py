"""
ONNX sentence-embedding singleton.

Loads rubert_tiny2.onnx (or any compatible model) once at process start.
Falls back to a bag-of-chars hash embedding if ONNX is unavailable,
so the intent classifier still works (with lower accuracy).
"""
from __future__ import annotations

import hashlib
import logging
import os
from functools import lru_cache
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)

_session = None
_tokenizer = None
_mode: str = "unavailable"


def load(model_path: str | None = None) -> bool:
    """Load ONNX model. Returns True on success."""
    global _session, _tokenizer, _mode
    if _mode != "unavailable":
        return _mode != "hash_fallback"

    if model_path is None:
        base = os.path.dirname(__file__)
        model_path = os.path.join(base, "..", "..", "data", "nlp", "rubert_tiny2.onnx")
        model_path = os.path.normpath(model_path)

    if not os.path.exists(model_path):
        log.warning("embeddings: ONNX model not found at %s — using hash fallback", model_path)
        _mode = "hash_fallback"
        return False

    try:
        import onnxruntime as ort  # type: ignore
        _session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])

        # Try to load tokenizer (transformers or tokenizers library)
        tok_dir = os.path.dirname(model_path)
        try:
            from tokenizers import Tokenizer  # type: ignore
            tok_file = os.path.join(tok_dir, "tokenizer.json")
            if os.path.exists(tok_file):
                _tokenizer = Tokenizer.from_file(tok_file)
                _mode = "onnx"
                log.info("embeddings: ONNX model loaded (tokenizers library)")
                return True
        except Exception:
            pass
        try:
            from transformers import AutoTokenizer  # type: ignore
            _tokenizer = AutoTokenizer.from_pretrained(tok_dir)
            _mode = "onnx"
            log.info("embeddings: ONNX model loaded (transformers library)")
            return True
        except Exception:
            pass

        log.warning("embeddings: ONNX loaded but no tokenizer found — using hash fallback")
    except Exception as exc:
        log.warning("embeddings: onnxruntime unavailable (%s) — using hash fallback", exc)

    _mode = "hash_fallback"
    return False


def _hash_embed(text: str, dim: int = 128) -> np.ndarray:
    """Deterministic bag-of-bigram hash embedding. Fast but low accuracy."""
    vec = np.zeros(dim, dtype=np.float32)
    for i in range(len(text) - 1):
        bigram = text[i:i + 2]
        h = int(hashlib.md5(bigram.encode()).hexdigest(), 16) % dim
        vec[h] += 1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm > 0 else vec


@lru_cache(maxsize=512)
def embed(text: str) -> np.ndarray:
    """Return normalized embedding vector for text."""
    if _mode == "onnx" and _session is not None and _tokenizer is not None:
        try:
            return _embed_onnx(text)
        except Exception as exc:
            log.debug("embeddings: ONNX inference failed (%s), using hash", exc)
    return _hash_embed(text)


def _embed_onnx(text: str) -> np.ndarray:
    if hasattr(_tokenizer, "encode"):
        # tokenizers library
        enc = _tokenizer.encode(text)
        input_ids = np.array([enc.ids], dtype=np.int64)
        attention_mask = np.array([enc.attention_mask], dtype=np.int64)
    else:
        # transformers AutoTokenizer
        enc = _tokenizer(text, return_tensors="np", truncation=True, max_length=128)
        input_ids = enc["input_ids"].astype(np.int64)
        attention_mask = enc["attention_mask"].astype(np.int64)

    inputs = {"input_ids": input_ids, "attention_mask": attention_mask}
    outputs = _session.run(None, inputs)
    # Mean-pool last hidden state
    last_hidden = outputs[0]  # (1, seq_len, hidden)
    mask = attention_mask[0, :, np.newaxis]
    pooled = (last_hidden[0] * mask).sum(axis=0) / mask.sum()
    norm = np.linalg.norm(pooled)
    return (pooled / norm).astype(np.float32)
