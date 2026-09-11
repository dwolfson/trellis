"""Per-run source-acquisition accounting — was this run cold or warm?

The funnel-cost spec calls caching the single biggest confounder in its §1 cost
ladder, and `CLAUDE.md` rule 17 measured why: acquisition at 22.64s cold against
1.28s warm, one repo's full route 110.5s → 14.4s as caching landed. A tier
median pooling those is a measurement of how many of its runs happened to be
first, not of the tier.

The recurring assertion is the same three-state one used for tokens: a zero must
say which kind of zero it is. `not-consulted` (a database survey touches no
source cache) is not `warm`.
"""
from __future__ import annotations

import pytest

from resource_explorer.observability import acquisition


class TestScoping:
    def test_recording_outside_a_scope_is_a_no_op(self):
        assert acquisition.current() is None
        acquisition.record_hit("zipball_root")
        acquisition.record_miss("git_clone_root")
        assert acquisition.current() is None

    def test_the_scope_is_removed_even_when_the_body_raises(self):
        with pytest.raises(RuntimeError):
            with acquisition.acquisition_scope():
                raise RuntimeError("boom")
        assert acquisition.current() is None, (
            "a failed run leaves its scope in force and the next run's lookups "
            "accumulate into it"
        )

    def test_nested_scopes_fold_into_the_enclosing_one(self):
        with acquisition.acquisition_scope() as outer:
            acquisition.record_hit("zipball_root")
            with acquisition.acquisition_scope() as inner:
                acquisition.record_miss("git_clone_root")
            assert inner.misses == 1
        assert outer.hits == 1 and outer.misses == 1
        assert outer.kinds_fetched == {"git_clone_root"}


class TestTheThreeStates:
    def test_no_lookups_is_not_consulted_rather_than_warm(self):
        """A database survey does no source acquisition. Calling that `warm`
        would put every one of them in the cheap bucket of a cost comparison
        they never participated in."""
        with acquisition.acquisition_scope() as a:
            pass
        assert a.state == "not-consulted"
        assert a.as_dict()["source_acquisition"] == "not-consulted"

    def test_all_hits_is_warm(self):
        with acquisition.acquisition_scope() as a:
            acquisition.record_hit("zipball_root")
            acquisition.record_hit("git_clone_root")
        assert a.state == "warm" and a.lookups == 2

    def test_a_single_miss_makes_the_run_cold(self):
        """One miss means a real download happened. A run that was warm on the
        zipball and cold on the clone paid the download, and averaging it in
        with fully-warm runs is what makes a tier median untrustworthy."""
        with acquisition.acquisition_scope() as a:
            acquisition.record_hit("zipball_root")
            acquisition.record_miss("git_clone_root")
        assert a.state == "cold"
        assert a.as_dict()["source_kinds_fetched"] == ["git_clone_root"]

    def test_which_kinds_were_fetched_survives_into_the_dict(self):
        with acquisition.acquisition_scope() as a:
            acquisition.record_miss("zipball_root")
            acquisition.record_miss("git_clone_root")
        assert a.as_dict()["source_kinds_fetched"] == ["git_clone_root", "zipball_root"]


class TestAgainstTheRealSourceCache:
    """Driven through SourceCache itself rather than by calling record_*
    directly — the wiring is the part that can silently come undone."""

    def _cache(self, tmp_path):
        from resource_explorer.github.source_cache import SourceCache
        return SourceCache(cache_dir=tmp_path / "cache")

    def test_a_real_miss_then_hit_is_attributed(self, tmp_path):
        cache = self._cache(tmp_path)
        with acquisition.acquisition_scope() as cold:
            assert cache.get("zipball_root", "acme/repo", "sha1") is None
        assert cold.state == "cold", "a genuine cache miss did not read as cold"

        cache.put("zipball_root", "acme/repo", "sha1",
                  lambda target: target.write_text("artifact"))

        with acquisition.acquisition_scope() as warm:
            assert cache.get("zipball_root", "acme/repo", "sha1") is not None
        assert warm.state == "warm" and warm.hits == 1

    def test_a_moved_sha_misses_and_reads_cold(self, tmp_path):
        """The property the SHA key exists for: new commit, new key, real
        fetch — and the accounting must say so rather than inheriting the
        previous run's warmth."""
        cache = self._cache(tmp_path)
        cache.put("zipball_root", "acme/repo", "sha1",
                  lambda target: target.write_text("artifact"))
        with acquisition.acquisition_scope() as a:
            assert cache.get("zipball_root", "acme/repo", "sha2") is None
        assert a.state == "cold"

    def test_the_shared_counters_still_work(self, tmp_path):
        """`hits`/`misses` are process-wide and were never read by anything;
        they are kept for debugging the cache itself and must not have been
        broken by adding the scope."""
        cache = self._cache(tmp_path)
        cache.get("zipball_root", "acme/repo", "nope")
        assert (cache.hits, cache.misses) == (0, 1)

    def test_lookups_outside_a_run_do_not_raise(self, tmp_path):
        """The CLI and tests use SourceCache with no scope open."""
        cache = self._cache(tmp_path)
        assert cache.get("zipball_root", "acme/repo", "sha") is None


class TestTheScopeIsOpenedAndPersisted:
    def test_the_run_queue_opens_an_acquisition_scope(self):
        import inspect
        from resource_explorer import run_queue
        src = inspect.getsource(run_queue)
        assert "acquisition_scope()" in src, (
            "run_queue executes handlers without an acquisition scope, so no "
            "run can say whether it fetched or reused"
        )

    def test_source_cache_reports_both_outcomes(self):
        import inspect
        from resource_explorer.github import source_cache
        src = inspect.getsource(source_cache.SourceCache.get)
        assert "record_miss" in src and "record_hit" in src, (
            "SourceCache.get no longer reports to the acquisition scope, so "
            "every run reads as not-consulted"
        )

    def test_a_fetching_run_with_no_llm_calls_is_still_logged(self):
        """The expensive case §1 cares most about: a big zipball download and
        no LLM work at all. Gating the log on token calls alone drops it."""
        import ast
        import inspect
        from resource_explorer import run_queue
        tree = ast.parse(inspect.getsource(run_queue.execute_run).lstrip())
        tests = [n.test for n in ast.walk(tree) if isinstance(n, ast.If)]
        assert any(isinstance(t, ast.BoolOp) and isinstance(t.op, ast.Or)
                   and "lookups" in ast.dump(t) for t in tests), (
            "the run-cost log is not gated on acquisition as well as tokens, so "
            "a run that only downloaded is recorded as having cost nothing"
        )

    def test_the_sink_accepts_and_splits_acquisition(self):
        import inspect
        from resource_explorer.observability import mlflow_tracking
        sig = inspect.signature(mlflow_tracking.log_run_usage)
        assert "acquisition" in sig.parameters
        src = inspect.getsource(mlflow_tracking.log_run_usage)
        assert 'params["source_acquisition"]' in src, (
            "source_acquisition is not logged as a param, so a cost query "
            "cannot filter cold runs out of a tier median"
        )
