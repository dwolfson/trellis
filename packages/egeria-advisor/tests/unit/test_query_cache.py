"""Tests for EA's QueryCache adapter over the shared trellis-querycache.

The eviction tests are the point: before the extraction this cache was a plain
`dict` evicting the oldest *insertion*, despite being named and documented as
an LRU throughout. `test_a_hot_entry_survives_a_newer_cold_one` fails against
that old implementation — verified directly against `HEAD:advisor/query_cache.py`
during the extraction — and passes now.
"""
import pytest

from advisor.query_cache import QueryCache, get_query_cache


@pytest.fixture
def cache():
    return QueryCache(max_size=5)


class TestBasicOperations:
    def test_miss_returns_none(self, cache):
        assert cache.get("q") is None

    def test_set_and_get(self, cache):
        cache.set("what is X", {"chunks": [1, 2]})
        assert cache.get("what is X") == {"chunks": [1, 2]}

    def test_query_is_normalized_for_case_and_whitespace(self, cache):
        cache.set("  What Is X  ", "answer")
        assert cache.get("what is x") == "answer"

    def test_parameters_are_part_of_the_key(self, cache):
        cache.set("q", "five", top_k=5)
        cache.set("q", "ten", top_k=10)
        assert cache.get("q", top_k=5) == "five"
        assert cache.get("q", top_k=10) == "ten"

    def test_caches_the_retrieval_result_shape_rag_retrieval_actually_stores(self, cache):
        """`RAGRetriever` caches a list of result objects, not a string."""
        results = [{"text": "a", "score": 0.9}, {"text": "b", "score": 0.8}]
        cache.set("q", results, top_k=5, min_score=0.7, use_multi=True)
        assert cache.get("q", top_k=5, min_score=0.7, use_multi=True) == results

    def test_a_false_parameter_still_distinguishes_the_key(self, cache):
        cache.set("q", "multi", use_multi=True)
        cache.set("q", "single", use_multi=False)
        assert cache.get("q", use_multi=True) == "multi"
        assert cache.get("q", use_multi=False) == "single"


class TestLRUEviction:
    def test_a_hot_entry_survives_a_newer_cold_one(self):
        """The bug this extraction fixed. The old FIFO implementation evicted
        `hot` — the most-requested entry — because it was inserted first."""
        cache = QueryCache(max_size=2)
        cache.set("hot", "a")
        cache.set("cold", "b")
        for _ in range(3):
            cache.get("hot")
        cache.set("new", "c")
        assert cache.get("hot") == "a"
        assert cache.get("cold") is None

    def test_never_grows_past_max_size(self):
        cache = QueryCache(max_size=3)
        for i in range(20):
            cache.set(f"q{i}", i)
        assert len(cache.cache) == 3


class TestNoTTL:
    def test_entries_do_not_expire_on_their_own(self, cache):
        """EA has never had a TTL; the extraction did not quietly add one."""
        cache.set("q", "answer")
        assert cache.cache[cache.key("q")].expires_at is None


class TestStatsAndBackCompat:
    def test_stats_report_hits_misses_and_rate(self, cache):
        cache.set("q", "a")
        cache.get("q")
        cache.get("absent")
        stats = cache.get_stats()
        assert (stats["hits"], stats["misses"], stats["hit_rate"]) == (1, 1, 50.0)

    def test_most_popular_ranks_by_hit_count(self, cache):
        cache.set("hot", "a")
        cache.set("warm", "b")
        for _ in range(4):
            cache.get("hot")
        cache.get("warm")
        assert [p["hits"] for p in cache.get_stats()["most_popular"][:2]] == [4, 1]

    def test_clear_empties_the_cache_and_the_counters(self, cache):
        cache.set("q", "a")
        cache.get("q")
        cache.clear()
        assert cache.get("q") is None
        assert cache.get_stats()["hits"] == 0

    def test_exposes_the_attributes_admin_and_scripts_read(self, cache):
        """`max_size`, `hits`, `misses` and `cache` were plain attributes on the
        old implementation; admin.py and scripts/test_cache_performance.py
        still read them."""
        cache.set("q", "a")
        cache.get("q")
        assert cache.max_size == 5
        assert cache.hits == 1
        assert cache.misses == 0
        assert len(cache.cache) == 1

    def test_deprecated_get_most_popular_spelling_still_works(self, cache):
        cache.set("q", "a")
        assert cache._get_most_popular(1) == cache.most_popular(1)


class TestGlobalInstance:
    def test_get_query_cache_returns_the_same_instance(self):
        assert get_query_cache() is get_query_cache()
