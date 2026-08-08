"""
Simple LRU cache for query results to improve performance.

Caches query results to avoid redundant vector searches for frequently
asked questions.
"""

from typing import Optional, Any, Dict
from functools import lru_cache
from dataclasses import dataclass
import hashlib
import json
from loguru import logger


@dataclass
class CachedResult:
    """Cached query result with metadata."""
    result: Any
    query_hash: str
    hit_count: int = 0


class QueryCache:
    """
    Simple LRU cache for query results.
    
    Caches results based on query text and parameters to avoid
    redundant vector searches.
    """
    
    def __init__(self, max_size: int = 100):
        """
        Initialize query cache.
        
        Args:
            max_size: Maximum number of cached queries
        """
        self.max_size = max_size
        self.cache: Dict[str, CachedResult] = {}
        self.hits = 0
        self.misses = 0
        logger.info(f"Initialized QueryCache with max_size={max_size}")
    
    def _generate_key(self, query: str, **kwargs) -> str:
        """
        Generate cache key from query and parameters.
        
        Args:
            query: Query text
            **kwargs: Additional parameters (top_k, filters, etc.)
        
        Returns:
            Cache key string
        """
        # Create a deterministic key from query and params
        cache_data = {
            "query": query.lower().strip(),
            **{k: v for k, v in sorted(kwargs.items()) if v is not None}
        }
        cache_str = json.dumps(cache_data, sort_keys=True)
        return hashlib.md5(cache_str.encode()).hexdigest()
    
    def get(self, query: str, **kwargs) -> Optional[Any]:
        """
        Get cached result if available.
        
        Args:
            query: Query text
            **kwargs: Query parameters
        
        Returns:
            Cached result or None if not found
        """
        key = self._generate_key(query, **kwargs)
        
        if key in self.cache:
            self.hits += 1
            cached = self.cache[key]
            cached.hit_count += 1
            logger.debug(f"Cache HIT for query (hits: {cached.hit_count})")
            return cached.result
        
        self.misses += 1
        logger.debug(f"Cache MISS for query")
        return None
    
    def set(self, query: str, result: Any, **kwargs) -> None:
        """
        Cache a query result.
        
        Args:
            query: Query text
            result: Result to cache
            **kwargs: Query parameters
        """
        key = self._generate_key(query, **kwargs)
        
        # Implement simple LRU: remove oldest if at capacity
        if len(self.cache) >= self.max_size and key not in self.cache:
            # Remove least recently used (first item)
            oldest_key = next(iter(self.cache))
            del self.cache[oldest_key]
            logger.debug(f"Cache full, evicted oldest entry")
        
        self.cache[key] = CachedResult(
            result=result,
            query_hash=key,
            hit_count=0
        )
        logger.debug(f"Cached result for query")
    
    def clear(self) -> None:
        """Clear all cached results."""
        self.cache.clear()
        self.hits = 0
        self.misses = 0
        logger.info("Cache cleared")
    
    def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dictionary with cache stats
        """
        total_requests = self.hits + self.misses
        hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
        
        return {
            "size": len(self.cache),
            "max_size": self.max_size,
            "hits": self.hits,
            "misses": self.misses,
            "total_requests": total_requests,
            "hit_rate": hit_rate,
            "most_popular": self._get_most_popular(5)
        }
    
    def _get_most_popular(self, n: int = 5) -> list:
        """Get n most frequently accessed queries."""
        sorted_items = sorted(
            self.cache.items(),
            key=lambda x: x[1].hit_count,
            reverse=True
        )
        return [
            {"hash": k[:8], "hits": v.hit_count}
            for k, v in sorted_items[:n]
        ]


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