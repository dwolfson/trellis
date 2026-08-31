"""Configuration for the shared query cache.

A plain frozen dataclass, deliberately: this package never reads the
environment. Each app resolves its own settings (RE's pydantic `CacheConfig`,
EA's constructor defaults) into one of these and hands it over — the same
split `trellis-vectorstore` uses for `PgVectorStoreConfig`.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QueryCacheConfig:
    """How a `QueryCache` behaves.

    `ttl_seconds=None` means entries never expire on their own — they leave
    only by LRU eviction or explicit invalidation. That is Egeria Advisor's
    historical behaviour and is preserved rather than silently given a TTL.
    """

    max_size: int = 1000
    ttl_seconds: float | None = 3600.0
    backend: str = "memory"  # "memory" | "redis"
    redis_url: str = ""

    # Redis key namespacing. Defaults match Resource Explorer's existing keys
    # so an already-running Redis keeps the same layout after the extraction.
    key_prefix: str = "pe:cache:"
    scope_prefix: str = "pe:project:"

    def __post_init__(self) -> None:
        if self.max_size < 1:
            raise ValueError(f"max_size must be >= 1, got {self.max_size}")
        if self.ttl_seconds is not None and self.ttl_seconds <= 0:
            raise ValueError(f"ttl_seconds must be > 0 or None, got {self.ttl_seconds}")
        if self.backend not in ("memory", "redis"):
            raise ValueError(f"backend must be 'memory' or 'redis', got {self.backend!r}")
        if self.backend == "redis" and not self.redis_url:
            raise ValueError("backend='redis' requires a redis_url")

    @property
    def uses_redis(self) -> bool:
        return self.backend == "redis" and bool(self.redis_url)
