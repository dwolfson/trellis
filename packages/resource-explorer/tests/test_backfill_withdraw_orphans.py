"""The live/orphaned split used by step 4's backfill.

The rule decides what gets withdrawn from already-published data, so it is
pinned here rather than left to a script nobody re-reads. Its crux: **the
unlabelled rows ARE the same two steps before `run_label` existed**, so once any
labelled run exists, keeping the last unlabelled run alive would defeat the
whole exercise — measured on `egeria_git`, that would hold 870 superseded scopes
open forever.
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

_spec = importlib.util.spec_from_file_location(
    "backfill_withdraw_orphans",
    pathlib.Path(__file__).parent.parent / "scripts" / "backfill_withdraw_orphans.py",
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
live_and_orphaned = _mod.live_and_orphaned


class _Registry:
    """Only what `live_and_orphaned` reads."""

    def __init__(self, rows):
        self._rows = rows

    def query_findings_history_raw(self, slug, kind):
        return self._rows


def _row(scope, ts, run_label=None, check_name="component"):
    detail = {} if run_label is None else {"run_label": run_label}
    return {"check_name": check_name, "scope_locator": scope,
            "surveyed_at": ts, "detail_json": detail}


class TestLiveAndOrphaned:
    def test_with_no_labelled_runs_the_latest_unlabelled_run_is_live(self):
        """egeria_workspaces_git's shape: 15 unlabelled runs, nothing else."""
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("a", "2026-08-01"), _row("b", "2026-08-01"),
            _row("a", "2026-08-02"),
        ]), "s")
        assert live == {"a"}
        assert orphaned == {"b"}

    def test_once_labelled_runs_exist_unlabelled_becomes_history(self):
        """The crux. Treating "(unlabelled)" as just another writer keeps its
        last run alive forever — on egeria that is 870 superseded scopes."""
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("old1", "2026-08-01"), _row("old2", "2026-08-01"),
            _row("new", "2026-08-02", run_label="detect"),
        ]), "s")
        assert live == {"new"}
        assert orphaned == {"old1", "old2"}

    def test_the_live_set_is_the_union_across_labels(self):
        """detect and coupling both write, and a scope either claims is live."""
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("d", "2026-08-02", run_label="detect"),
            _row("c", "2026-08-02", run_label="coupling"),
            _row("gone", "2026-08-01", run_label="detect"),
        ]), "s")
        assert live == {"d", "c"}
        assert orphaned == {"gone"}

    def test_an_earlier_run_of_the_same_label_is_superseded(self):
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("a", "2026-08-01", run_label="detect"),
            _row("b", "2026-08-01", run_label="detect"),
            _row("a", "2026-08-02", run_label="detect"),
        ]), "s")
        assert live == {"a"}
        assert orphaned == {"b"}

    def test_one_label_lagging_does_not_orphan_its_scopes(self):
        """coupling may not have run since detect did. Its own latest run still
        counts, or a step that simply ran less recently would be erased."""
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("c", "2026-08-01", run_label="coupling"),
            _row("d", "2026-08-05", run_label="detect"),
        ]), "s")
        assert live == {"c", "d"}
        assert orphaned == set()

    def test_non_component_rows_are_ignored(self):
        """Evidence, structural nodes and withdrawals are not proposals."""
        live, orphaned, _ = live_and_orphaned(_Registry([
            _row("a", "2026-08-02", run_label="detect"),
            _row("b", "2026-08-03", run_label="detect", check_name="structural_node"),
        ]), "s")
        assert live == {"a"}
        assert orphaned == set()

    def test_an_empty_history_withdraws_nothing(self):
        assert live_and_orphaned(_Registry([]), "s") == (set(), set(), {})

    @pytest.mark.parametrize("bad", ["not json", "", None])
    def test_an_unparseable_detail_is_treated_as_unlabelled_not_dropped(self, bad):
        """Dropping the row would quietly shrink the live set, which withdraws
        MORE than intended — the dangerous direction for a backfill."""
        rows = [{"check_name": "component", "scope_locator": "a",
                 "surveyed_at": "2026-08-02", "detail_json": bad}]
        live, orphaned, _ = live_and_orphaned(_Registry(rows), "s")
        assert live == {"a"}
        assert orphaned == set()
