"""Tests for QueryCache — LRU eviction, TTL, project invalidation."""
from __future__ import annotations

import time

import pytest

from resource_explorer.query_cache import QueryCache


@pytest.fixture
def cache():
    return QueryCache(max_size=5, ttl_seconds=60)


class TestBasicOperations:
    def test_miss_returns_none(self, cache):
        assert cache.get("q", None, "general") is None

    def test_set_and_get(self, cache):
        cache.set("what is X", None, "general", "X is a thing")
        assert cache.get("what is X", None, "general") == "X is a thing"

    def test_query_normalization(self, cache):
        cache.set("  What Is X  ", None, "general", "X is a thing")
        assert cache.get("what is x", None, "general") == "X is a thing"

    def test_different_project_scopes_are_separate(self, cache):
        cache.set("q", "proj-a", "general", "answer A")
        cache.set("q", "proj-b", "general", "answer B")
        assert cache.get("q", "proj-a", "general") == "answer A"
        assert cache.get("q", "proj-b", "general") == "answer B"
        assert cache.get("q", None, "general") is None

    def test_different_intents_are_separate(self, cache):
        cache.set("q", None, "general", "general answer")
        cache.set("q", None, "statistical", "stats answer")
        assert cache.get("q", None, "general") == "general answer"
        assert cache.get("q", None, "statistical") == "stats answer"


class TestTTLExpiry:
    def test_expired_entry_returns_none(self):
        cache = QueryCache(max_size=10, ttl_seconds=1)
        cache.set("q", None, "general", "answer")
        assert cache.get("q", None, "general") == "answer"
        # Manually expire by backdating the entry
        cache._store[cache._key("q", None, "general")].expires_at = time.time() - 1
        assert cache.get("q", None, "general") is None


class TestLRUEviction:
    def test_oldest_entry_evicted_when_full(self):
        cache = QueryCache(max_size=3, ttl_seconds=3600)
        cache.set("q1", None, "g", "a1")
        cache.set("q2", None, "g", "a2")
        cache.set("q3", None, "g", "a3")
        # Access q1 to make it recently used
        cache.get("q1", None, "g")
        # Adding q4 should evict q2 (LRU)
        cache.set("q4", None, "g", "a4")
        assert cache.get("q2", None, "g") is None
        assert cache.get("q1", None, "g") == "a1"
        assert cache.get("q3", None, "g") == "a3"
        assert cache.get("q4", None, "g") == "a4"


class TestProjectInvalidation:
    def test_invalidate_project_removes_matching_entries(self, cache):
        cache.set("q1", "myproj", "general", "a1")
        cache.set("q2", "myproj", "statistical", "a2")
        cache.set("q3", "otherproj", "general", "a3")
        dropped = cache.invalidate_project("myproj")
        assert dropped == 2
        assert cache.get("q1", "myproj", "general") is None
        assert cache.get("q2", "myproj", "statistical") is None
        assert cache.get("q3", "otherproj", "general") == "a3"

    def test_invalidate_nonexistent_project_returns_zero(self, cache):
        assert cache.invalidate_project("ghost") == 0
