"""
Abstract base class for vector store backends. pgvector is the only
implementation today (resource_explorer/vector_store_pg.py); this interface
exists to keep the rest of the codebase decoupled from that choice, and
structurally mirrors Egeria Advisor's own vector_store_base.py so a future
shared `trellis-vectorstore` package (see migration plan decision D3) starts
from two similar, independently-adapted implementations rather than one.

Unlike EA's version, RE uses one uniform per-collection schema
(id, embedding, text, metadata) for every collection — no per-collection
extra scalar columns — so create_collection()/insert_data() take no
extra_fields parameter here. collection_exists() and delete_by_metadata()
are additions not present in EA's ABC: collection_exists() closes a leak
where a caller previously reached past the public interface to call
Milvus-specific has_collection() directly; delete_by_metadata() backs the
real row-level incremental-indexing rework (migration plan decision D4).
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    id: str
    score: float
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)
    collection: str = ""  # populated by multi-collection callers; empty for single-collection search


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
        metric_type: str = "COSINE",
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
    def search(
        self,
        collection_name: str,
        query_text: str | None = None,
        query_embedding: np.ndarray | None = None,
        top_k: int = 5,
    ) -> list[SearchResult]: ...

    @abstractmethod
    def query_by_filter(
        self,
        collection_name: str,
        field: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Filter-only query returning id/text/metadata rows, no vector search.
        Used by list_source_files()-style scans over metadata."""
        ...

    @abstractmethod
    def delete_entities(self, collection_name: str, ids: list[str]) -> int: ...

    @abstractmethod
    def delete_by_metadata(self, collection_name: str, field: str, values: list[str]) -> int:
        """Delete every row whose metadata->>field is in values. Backs real
        row-level incremental re-indexing (delete-then-reinsert per changed
        file) instead of collection-level drop+rebuild."""
        ...

    @abstractmethod
    def get_collection_stats(self, collection_name: str) -> dict[str, Any]: ...

    @abstractmethod
    def list_collections(self) -> list[str]: ...

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None: ...
