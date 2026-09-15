"""Per-call Egeria timing (owner's ruling, 2026-09-15): the instrumentation
the layer-2 catalogue-depth offer needs and nothing before it recorded --
every measured price up to this point (`RunCost`, `DepthOffer`) is per
ANALYSIS RUN, never per individual write or query.

Two things the owner named specifically:
- writes and queries are different cost populations, kept apart by `kind`;
- a query's cost is sensitive to its own parameters (graph depth, page
  size), so a reader must be able to bucket by them rather than averaging a
  shallow lookup together with a deep graph walk.
"""
from __future__ import annotations

import time

import pytest

from resource_explorer.egeria_timing import time_egeria_call
from resource_explorer.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


class TestRecordingAndReading:
    def test_nothing_recorded_is_told_apart_from_a_zero(self, registry):
        stats = registry.read_egeria_call_timing_stats("create_solution_component", "write")
        assert stats == {"count": 0, "median": None, "p90": None}

    def test_a_recorded_call_is_read_back(self, registry):
        registry.record_egeria_call_timing("create_solution_component", "write", 1.5)
        stats = registry.read_egeria_call_timing_stats("create_solution_component", "write")
        assert stats["count"] == 1 and stats["median"] == 1.5 and stats["p90"] == 1.5

    def test_median_and_p90_over_several_calls(self, registry):
        for s in [1.0, 1.0, 1.0, 1.0, 5.0]:   # p90 of 5 sorted values -> index 4 -> 5.0
            registry.record_egeria_call_timing("create_solution_component", "write", s)
        stats = registry.read_egeria_call_timing_stats("create_solution_component", "write")
        assert stats["count"] == 5 and stats["median"] == 1.0 and stats["p90"] == 5.0


class TestWritesAndQueriesAreNeverConflated:
    """The owner's first point: an insert/update and a lookup are different
    cost populations, and a median that mixes them hides both."""

    def test_a_write_and_a_query_of_the_same_name_are_separate_populations(self, registry):
        registry.record_egeria_call_timing("find_assets", "write", 9.0)
        registry.record_egeria_call_timing("find_assets", "query", 0.1)
        assert registry.read_egeria_call_timing_stats("find_assets", "write")["median"] == 9.0
        assert registry.read_egeria_call_timing_stats("find_assets", "query")["median"] == 0.1


class TestQueryParamsAreNotAveragedAway:
    """The owner's second point: query cost depends on the query's own
    parameters (graph depth, page size) -- a reader must be able to bucket
    by them, not fold a depth-1 lookup and a depth-5 walk into one median."""

    def test_param_filter_isolates_one_depth(self, registry):
        registry.record_egeria_call_timing("find_assets", "query", 0.1, params={"graph_query_depth": 1})
        registry.record_egeria_call_timing("find_assets", "query", 0.1, params={"graph_query_depth": 1})
        registry.record_egeria_call_timing("find_assets", "query", 4.0, params={"graph_query_depth": 5})

        shallow = registry.read_egeria_call_timing_stats(
            "find_assets", "query", param_filter={"graph_query_depth": 1})
        deep = registry.read_egeria_call_timing_stats(
            "find_assets", "query", param_filter={"graph_query_depth": 5})
        unfiltered = registry.read_egeria_call_timing_stats("find_assets", "query")

        assert shallow == {"count": 2, "median": 0.1, "p90": 0.1}
        assert deep == {"count": 1, "median": 4.0, "p90": 4.0}
        assert unfiltered["count"] == 3   # unfiltered still sees all three

    def test_a_param_filter_that_matches_nothing_is_absence_not_zero(self, registry):
        registry.record_egeria_call_timing("find_assets", "query", 0.1, params={"graph_query_depth": 1})
        stats = registry.read_egeria_call_timing_stats(
            "find_assets", "query", param_filter={"graph_query_depth": 99})
        assert stats == {"count": 0, "median": None, "p90": None}


class TestTheContextManager:
    def test_it_measures_and_records_on_success(self, registry):
        with time_egeria_call(registry, "create_asset", "write"):
            time.sleep(0.01)
        stats = registry.read_egeria_call_timing_stats("create_asset", "write")
        assert stats["count"] == 1 and stats["median"] > 0

    def test_it_still_records_and_reraises_on_failure(self, registry):
        with pytest.raises(ValueError):
            with time_egeria_call(registry, "create_asset", "write"):
                raise ValueError("Egeria said no")
        # The call still happened and took real time -- recorded, not lost.
        assert registry.read_egeria_call_timing_stats("create_asset", "write")["count"] == 1

    def test_a_none_registry_is_a_no_op_not_a_crash(self):
        """The optional-registry convention this codebase uses throughout
        (EgeriaPublisher itself can run with no registry) -- the timer must
        not require one."""
        with time_egeria_call(None, "create_asset", "write"):
            pass   # must not raise

    def test_a_recording_failure_never_masks_the_calls_own_exception(self, registry, monkeypatch):
        def boom(*a, **k):
            raise RuntimeError("registry is down")
        monkeypatch.setattr(registry, "record_egeria_call_timing", boom)
        with pytest.raises(ValueError, match="the real error"):
            with time_egeria_call(registry, "create_asset", "write"):
                raise ValueError("the real error")

    def test_params_travel_from_the_context_manager_to_the_row(self, registry):
        with time_egeria_call(registry, "find_assets", "query", params={"graph_query_depth": 3}):
            pass
        stats = registry.read_egeria_call_timing_stats(
            "find_assets", "query", param_filter={"graph_query_depth": 3})
        assert stats["count"] == 1
