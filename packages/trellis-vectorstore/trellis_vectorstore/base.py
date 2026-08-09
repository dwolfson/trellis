"""Abstract base class for vector store backends — extracted from Resource
Explorer's and Egeria Advisor's independently-evolved BaseVectorStore ABCs.

This ABC is the union of what both apps' real (not aspirational) usage
needed, confirmed by direct code reading before merging:

- collection_exists()/delete_by_metadata() were RE-only; EA's equivalent
  (_table_exists) was private and had zero callers anywhere in EA. Promoted
  unconditionally — additive for EA, no behavior change.
- SearchResult.collection was RE-only (populated by RE's own multi-collection
  wrapper). Defaulted to "" so every existing EA construction keeps working
  unchanged.
- search()'s filter_expr/filters and query_by_filter()'s filter_expr/
  output_fields were EA-only; RE simply never passes them (every one
  defaults to producing RE's old unfiltered behavior — see pg.py).
- extra_fields (on create_collection) and output_fields (on search()) are
  dropped entirely: both were declared on EA's old ABC but never referenced
  by EA's real implementation body, and no live caller passed either.
  output_fields survives only on query_by_filter(), where it's genuinely
  used.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    collection: str = ""  # populated by multi-collection callers; "" for single-collection search


class BaseVectorStore(ABC):
    """Backend-agnostic interface for vector store operations."""

    @abstractmethod
    def connect(self) -> None: ...

    @abstractmethod
    def disconnect(self) -> None: ...

    @abstractmethod
    def is_connected(self) -> bool: ...

    @abstractmethod
    def create_collection(
        self,
        collection_name: str,
        drop_if_exists: bool = False,
    ) -> str: ...

    @abstractmethod
    def create_index(
        self,
        collection_name: str,
        index_type: str = "HNSW",
        metric_type: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None: ...

    @abstractmethod
    def collection_exists(self, collection_name: str) -> bool: ...

    @abstractmethod
    def insert_data(
        self,
        collection_name: str,
        texts: list[str],
        ids: list[str] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> int: ...

    @abstractmethod
    def insert_with_embeddings(
        self,
        collection_name: str,
        texts: list[str],
        embeddings: list[Any],
        ids: list[str] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> int:
        """Insert rows using pre-computed embeddings, skipping re-embedding —
        used by data-migration scripts where embeddings already exist."""
        ...

    @abstractmethod
    def search(
        self,
        collection_name: str,
        query_text: str | None = None,
        query_embedding: np.ndarray | None = None,
        top_k: int = 5,
        filter_expr: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]: ...

    @abstractmethod
    def query_by_filter(
        self,
        collection_name: str,
        filter_expr: str | None = None,
        output_fields: Sequence[str] = ("id", "text", "metadata"),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Scalar-filtered query, no vector search. filter_expr uses the
        small DSL in trellis_vectorstore.filters. Filters scalar columns
        only — a collection with no extra scalar columns (every RE
        collection) will raise Postgres UndefinedColumn if filter_expr
        references one; that's a real error, not something to guard
        against, since such a collection has nothing to filter."""
        ...

    @abstractmethod
    def delete_entities(self, collection_name: str, ids: list[str]) -> int: ...

    @abstractmethod
    def delete_by_metadata(self, collection_name: str, field: str, values: list[str]) -> int:
        """Delete every row whose metadata->>field is in values. Backs
        row-level incremental re-indexing (delete-then-reinsert per changed
        file) instead of collection-level drop+rebuild."""
        ...

    @abstractmethod
    def get_collection_stats(self, collection_name: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_collections(self) -> list[str]: ...

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None: ...
