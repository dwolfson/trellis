"""LRU query cache — a thin adapter over the shared `trellis-querycache`.

The implementation moved to `trellis_querycache` (Trellis consolidation, see
`docs/re-ea-consolidation-audit.md` item 1); this file keeps RE's own
vocabulary — a *resource* scope, an *intent* parameter — over the shared class,
and resolves RE's pydantic `CacheConfig` into the shared frozen config.

Behaviour is unchanged: same LRU + TTL semantics, same Redis key layout
(`pe:cache:` / `pe:project:` — Redis key strings are layer two and deliberately
unrenamed, like the SQL columns), so an already-running Redis keeps its shape.
The key *digest* changed with the extraction, so entries cached before an
upgrade simply read as misses — a cold start, not a correctness problem.
"""
from __future__ import annotations

from trellis_querycache import QueryCache as _SharedQueryCache
from trellis_querycache import QueryCacheConfig

from resource_explorer.config import get_config


class QueryCache(_SharedQueryCache):
    """
    LRU cache keyed on (normalized_query, resource_slug, intent).

    Biggest latency win in the system — implement before optimizing retrieval.
    In-memory by default; set CACHE__BACKEND=redis + CACHE__REDIS_URL to use Redis.
    TTL is per-entry; expired entries are evicted lazily (memory) or by Redis TTL.
    """

    def __init__(self, max_size: int | None = None, ttl_seconds: int | None = None) -> None:
        cfg = get_config().cache

        # Redis only when default construction (no overrides) and explicitly
        # configured — an explicitly-sized cache is a caller wanting its own
        # local one, not a share of the deployment-wide store.
        use_redis = (
            max_size is None
            and ttl_seconds is None
            and cfg.backend == "redis"
            and bool(cfg.redis_url)
        )
        super().__init__(
            QueryCacheConfig(
                max_size=max_size or cfg.max_size,
                ttl_seconds=ttl_seconds or cfg.ttl_seconds,
                backend="redis" if use_redis else "memory",
                redis_url=cfg.redis_url if use_redis else "",
                key_prefix="pe:cache:",
                scope_prefix="pe:project:",
            )
        )

    # ── RE's interface over the shared one ────────────────────────────────

    def _key(self, query: str, resource_slug: str | None, intent: str) -> str:
        return self.key(query, resource_slug, {"intent": intent})

    def get(self, query: str, resource_slug: str | None, intent: str) -> str | None:
        return super().get(query, scope=resource_slug, intent=intent)

    def set(self, query: str, resource_slug: str | None, intent: str, response: str) -> None:
        super().set(query, response, scope=resource_slug, intent=intent)

    def invalidate_project(self, resource_slug: str) -> int:
        """Drop all cached entries for a resource (call after re-indexing).

        Method name keeps `_project` to match main after the #22 rename, which
        moved the parameter and left the method name alone — every caller
        (`scheduler.py`, `webhook.py`, `cli/main.py`, `projects.py`, `tui/app.py`)
        still calls it by that name.
        """
        return self.invalidate_scope(resource_slug)
