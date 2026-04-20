"""
CLI helper — run once to generate intent_embeddings.npy from intents.json.

Usage:
    python -m app.services.nlp.build_intent_embeddings
"""
from __future__ import annotations

import json
import os
import sys

import numpy as np


def build(intents_path: str, output_path: str, model_path: str | None = None) -> None:
    with open(intents_path, encoding="utf-8") as f:
        intents_data = json.load(f)

    from app.services.nlp import embeddings as emb
    if not emb.load(model_path):
        print("WARNING: ONNX model not available; embeddings will be hash-based.")

    print(f"Building embeddings for {len(intents_data)} intents…")
    vectors = []
    for entry in intents_data:
        phrases = entry["phrases"]
        phrase_vecs = np.stack([emb.embed(p) for p in phrases])
        # Average all phrase embeddings and renormalize
        mean_vec = phrase_vecs.mean(axis=0)
        norm = np.linalg.norm(mean_vec)
        if norm > 0:
            mean_vec /= norm
        vectors.append(mean_vec)
        print(f"  {entry['intent']}: {len(phrases)} phrases")

    matrix = np.stack(vectors)
    np.save(output_path, matrix)
    print(f"Saved {matrix.shape} matrix to {output_path}")


if __name__ == "__main__":
    base = os.path.join(os.path.dirname(__file__), "..", "..", "data", "nlp")
    base = os.path.normpath(base)
    build(
        intents_path=os.path.join(base, "intents.json"),
        output_path=os.path.join(base, "intent_embeddings.npy"),
    )
