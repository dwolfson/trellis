"""Shared TTL/LRU query cache for Trellis apps.

    from trellis_querycache import QueryCache, QueryCacheConfig

    cache = QueryCache(QueryCacheConfig(max_size=500, ttl_seconds=600))
    cache.set("what is X", answer, scope="my-repo", intent="general")
    cache.get("what is X", scope="my-repo", intent="general")
    cache.invalidate_scope("my-repo")

Each app wraps this in a thin adapter that names the scope in its own
vocabulary — see `resource_explorer/query_cache.py` and
`advisor/query_cache.py`.
"""
from trellis_querycache.cache import CacheEntry, QueryCache
from trellis_querycache.config import QueryCacheConfig

__all__ = ["CacheEntry", "QueryCache", "QueryCacheConfig"]
