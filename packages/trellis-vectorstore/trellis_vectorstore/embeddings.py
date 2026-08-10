"""Embedding provider seam.

Neither app's actual embedding machinery moves here — RE lazily imports
module-level functions (embed_texts/embed_one) specifically to keep heavy
ML imports (torch, sentence-transformers) off this package's import path
until an embedding is actually needed; EA holds a stateful
EmbeddingGenerator object (encode_batch/encode). This Protocol is the
minimal common shape both existing implementations already satisfy — each
app writes a small adapter class, not a rewrite of its embedding code.
"""
from __future__ import annotations

from typing import Protocol, Sequence, runtime_checkable


@runtime_checkable
class EmbeddingProvider(Protocol):
    def embed_texts(self, texts: Sequence[str]) -> Sequence[Sequence[float]]:
        """Batch-embed. Returns one embedding vector per input text, same order."""
        ...

    def embed_query(self, text: str) -> Sequence[float]:
        """Embed a single query string."""
        ...
