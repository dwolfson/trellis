"""LRU query cache — in-process by default, Redis-backed optionally."""
from __future__ import annotations

import hashlib
import json
import time
from collections import OrderedDict

from resource_explorer.config import get_config


class QueryCache:
    """
    LRU cache keyed on (normalized_query, project_slug, intent).

    Biggest latency win in the system — implement before optimizing retrieval.
    In-memory by default; set CACHE__BACKEND=redis + CACHE__REDIS_URL to use Redis.
    TTL is per-entry; expired entries are evicted lazily (memory) or by Redis TTL.
    """

    def __init__(self, max_size: int | None = None, ttl_seconds: int | None = None) -> None:
        cfg = get_config().cache
        self._max_size = max_size or cfg.max_size
        self._ttl = ttl_seconds or cfg.ttl_seconds

        # Redis only when default construction (no overrides) and explicitly configured
        use_redis = (
            max_size is None
            and ttl_seconds is None
            and cfg.backend == "redis"
            and cfg.redis_url
        )
        if use_redis:
            self._redis = self._connect_redis(cfg.redis_url)
            self._store = None
        else:
            self._redis = None
            self._store: OrderedDict[str, tuple[str, float, str | None]] = OrderedDict()

    # ── key helpers ───────────────────────────────────────────────────────────

    def _key(self, query: str, project_slug: str | None, intent: str) -> str:
        payload = json.dumps({"q": query.strip().lower(), "p": project_slug, "i": intent})
        return hashlib.sha256(payload.encode()).hexdigest()

    # ── public interface ──────────────────────────────────────────────────────

    def get(self, query: str, project_slug: str | None, intent: str) -> str | None:
        if self._redis is not None:
            return self._redis_get(query, project_slug, intent)
        return self._mem_get(query, project_slug, intent)

    def set(self, query: str, project_slug: str | None, intent: str, response: str) -> None:
        if self._redis is not None:
            self._redis_set(query, project_slug, intent, response)
        else:
            self._mem_set(query, project_slug, intent, response)

    def invalidate_project(self, project_slug: str) -> int:
        """Drop all cached entries for a project (call after re-indexing)."""
        if self._redis is not None:
            return self._redis_invalidate(project_slug)
        return self._mem_invalidate(project_slug)

    # ── in-memory backend ─────────────────────────────────────────────────────

    def _mem_get(self, query: str, project_slug: str | None, intent: str) -> str | None:
        key = self._key(query, project_slug, intent)
        entry = self._store.get(key)
        if entry is None:
            return None
        value, expires_at, _slug = entry
        if time.time() > expires_at:
            del self._store[key]
            return None
        self._store.move_to_end(key)
        return value

    def _mem_set(self, query: str, project_slug: str | None, intent: str, response: str) -> None:
        key = self._key(query, project_slug, intent)
        self._store[key] = (response, time.time() + self._ttl, project_slug)
        self._store.move_to_end(key)
        while len(self._store) > self._max_size:
            self._store.popitem(last=False)

    def _mem_invalidate(self, project_slug: str) -> int:
        to_delete = [k for k, (_v, _t, slug) in self._store.items() if slug == project_slug]
        for k in to_delete:
            del self._store[k]
        return len(to_delete)

    # ── Redis backend ─────────────────────────────────────────────────────────

    _CACHE_PREFIX = "pe:cache:"
    _PROJECT_PREFIX = "pe:project:"

    def _connect_redis(self, url: str):
        import redis
        return redis.from_url(url, decode_responses=True)

    def _redis_get(self, query: str, project_slug: str | None, intent: str) -> str | None:
        key = self._CACHE_PREFIX + self._key(query, project_slug, intent)
        raw = self._redis.get(key)
        if raw is None:
            return None
        return json.loads(raw)["response"]

    def _redis_set(self, query: str, project_slug: str | None, intent: str, response: str) -> None:
        key = self._CACHE_PREFIX + self._key(query, project_slug, intent)
        payload = json.dumps({"response": response, "project_slug": project_slug})
        self._redis.setex(key, self._ttl, payload)
        if project_slug is not None:
            project_set = f"{self._PROJECT_PREFIX}{project_slug}:keys"
            self._redis.sadd(project_set, key)
            self._redis.expire(project_set, self._ttl * 2)

    def _redis_invalidate(self, project_slug: str) -> int:
        project_set = f"{self._PROJECT_PREFIX}{project_slug}:keys"
        keys = self._redis.smembers(project_set)
        if not keys:
            return 0
        deleted = self._redis.delete(*keys)
        self._redis.delete(project_set)
        return deleted
