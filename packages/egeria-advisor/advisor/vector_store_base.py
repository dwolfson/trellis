"""
Abstract base class for vector store backends. pgvector is the only
implementation today (advisor/vector_store_pg.py); this interface exists to
keep the rest of the codebase decoupled from that choice.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

import numpy as np


@dataclass
class SearchResult:
    """Result from a vector similarity search."""
    id: str
    score: float
    text: str
    metadata: Dict[str, Any]


class BaseVectorStore(ABC):
    """Backend-agnostic interface for vector store operations."""

    @abstractmethod
    def connect(self) -> None:
        """Connect to the vector store."""
        ...

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect from the vector store."""
        ...

    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if currently connected."""
        ...

    @abstractmethod
    def create_collection(
        self,
        collection_name: str,
        description: str = "",
        drop_if_exists: bool = False,
        extra_fields: Optional[Any] = None,
    ) -> Any:
        """
        Create (or verify) a collection / table.

        extra_fields: unused by the pgvector backend (schema is determined
        by collection name); kept for interface flexibility.
        """
        ...

    @abstractmethod
    def create_index(
        self,
        collection_name: str,
        index_type: str = "HNSW",
        metric_type: str = "L2",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create a vector index on the collection."""
        ...

    @abstractmethod
    def insert_data(
        self,
        collection_name: str,
        texts: List[str],
        ids: Optional[List[str]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1000,
    ) -> int:
        """Insert texts (with auto-embedding) into the collection. Returns row count."""
        ...

    @abstractmethod
    def search(
        self,
        collection_name: str,
        query_text: Optional[str] = None,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 5,
        filter_expr: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        output_fields: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        """
        Nearest-neighbour search. Accepts either a text query or a pre-computed
        embedding. Returns results ordered by descending similarity score.
        """
        ...

    @abstractmethod
    def query_by_filter(
        self,
        collection_name: str,
        filter_expr: str,
        output_fields: List[str],
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        """
        Retrieve rows by scalar filter without a vector search.

        filter_expr uses the small filter-expression DSL defined in
        advisor.metadata_filters, translated to a SQL WHERE clause internally.
        """
        ...

    @abstractmethod
    def delete_entities(
        self,
        collection_name: str,
        ids: List[str],
    ) -> int:
        """Delete entities by ID. Returns the number of deleted rows."""
        ...

    @abstractmethod
    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        """Return basic stats: name, num_entities, schema summary."""
        ...

    @abstractmethod
    def list_collections(self) -> List[str]:
        """List all collection / table names."""
        ...

    @abstractmethod
    def delete_collection(self, collection_name: str) -> None:
        """Permanently drop a collection / table."""
        ...
