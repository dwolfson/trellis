"""
LRU cache for query results — a thin adapter over the shared `trellis-querycache`.

Caches query results to avoid redundant vector searches for frequently
asked questions.

**This cache was not an LRU until the extraction.** It was named and
documented as one throughout, but was a plain `dict` that evicted the oldest
*insertion* and never reordered on access — so a frequently-hit entry was
evicted while a colder one inserted later survived. Adopting
`trellis_querycache.QueryCache` (RE's genuine `OrderedDict` + `move_to_end()`
implementation) fixes that as a side effect. See
`docs/re-ea-consolidation-audit.md` item 1.

Two deliberate continuities with the old behaviour:
  * no TTL by default — entries leave only by LRU eviction or `clear()`,
    which is what this cache has always done;
  * in-memory only — the shared class can use Redis, but EA has never
    configured one and this adapter does not start.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from loguru import logger
from trellis_querycache import QueryCache as _SharedQueryCache
from trellis_querycache import QueryCacheConfig


class QueryCache(_SharedQueryCache):
    """LRU cache for query results, keyed on query text plus parameters."""

    def __init__(self, max_size: int = 100):
        """
        Initialize query cache.

        Args:
            max_size: Maximum number of cached queries
        """
        super().__init__(QueryCacheConfig(max_size=max_size, ttl_seconds=None))
        logger.info(f"Initialized QueryCache with max_size={max_size}")

    def get(self, query: str, **kwargs) -> Optional[Any]:
        """
        Get cached result if available.

        Args:
            query: Query text
            **kwargs: Query parameters (top_k, filters, etc.)

        Returns:
            Cached result or None if not found
        """
        result = super().get(query, **kwargs)
        logger.debug("Cache HIT for query" if result is not None else "Cache MISS for query")
        return result

    def set(self, query: str, result: Any, **kwargs) -> None:
        """
        Cache a query result.

        Args:
            query: Query text
            result: Result to cache
            **kwargs: Query parameters
        """
        super().set(query, result, **kwargs)
        logger.debug("Cached result for query")

    def clear(self) -> None:
        """Clear all cached results."""
        super().clear()
        logger.info("Cache cleared")

    # ── back-compat surface ───────────────────────────────────────────────
    # The old implementation exposed these as plain attributes; admin.py and
    # scripts/test_cache_performance.py read them.

    @property
    def max_size(self) -> int:
        return self._config.max_size

    @property
    def hits(self) -> int:
        return self._hits

    @property
    def misses(self) -> int:
        return self._misses

    @property
    def cache(self) -> Dict[str, Any]:
        """The backing store. Was a `dict[str, CachedResult]`; is now the
        shared `OrderedDict[str, CacheEntry]`. Same keys, and `.hit_count` is
        still there — but an entry now also carries `expires_at`/`scope`."""
        return self._store

    def _get_most_popular(self, n: int = 5) -> list:
        """Deprecated spelling of `most_popular()`, kept for existing callers."""
        return self.most_popular(n)


# Global cache instance
_query_cache: Optional[QueryCache] = None


def get_query_cache(max_size: int = 100) -> QueryCache:
    """
    Get or create global query cache instance.

    Args:
        max_size: Maximum cache size

    Returns:
        QueryCache instance
    """
    global _query_cache
    if _query_cache is None:
        _query_cache = QueryCache(max_size=max_size)
    return _query_cache
