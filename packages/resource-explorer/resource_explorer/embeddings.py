"""Sentence-transformer embeddings with automatic MPS/CUDA/CPU device selection."""
from __future__ import annotations

import torch
from sentence_transformers import SentenceTransformer

from resource_explorer.config import get_config

_model: SentenceTransformer | None = None


def _resolve_device(device: str) -> str:
    if device != "auto":
        return device
    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def get_embedding_model() -> SentenceTransformer:
    global _model
    if _model is None:
        cfg = get_config().embeddings
        device = _resolve_device(cfg.device)
        try:
            # Prefer cached model to avoid HF Hub network calls on every load
            _model = SentenceTransformer(cfg.model, device=device, local_files_only=True)
        except Exception:
            _model = SentenceTransformer(cfg.model, device=device)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    model = get_embedding_model()
    return model.encode(texts, convert_to_numpy=True).tolist()


def embed_one(text: str) -> list[float]:
    return embed([text])[0]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """Alias for embed() used by MultiCollectionStore."""
    return embed(texts)
