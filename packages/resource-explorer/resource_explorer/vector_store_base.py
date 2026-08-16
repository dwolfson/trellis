"""Re-export shim — BaseVectorStore/SearchResult now live in the shared
trellis-vectorstore package (packages/trellis-vectorstore/), extracted from
this module and Egeria Advisor's independently-evolved equivalent. Kept as
a thin re-export so every existing `from resource_explorer.vector_store_base
import SearchResult` (etc.) import stays valid with zero call-site changes.
See docs/trellis-vectorstore-extraction.md and trellis_vectorstore's own
module docstring for the extraction's design rationale.
"""
from __future__ import annotations

from trellis_vectorstore import BaseVectorStore, SearchResult

__all__ = ["BaseVectorStore", "SearchResult"]
