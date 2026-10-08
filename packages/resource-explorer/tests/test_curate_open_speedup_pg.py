"""Postgres equivalence: the bulk recovery reads return exactly the per-scope reads, in the same order.

The ordering guarantee only means something on Postgres: rows tied on `surveyed_at` and duplicate
`metric_name` rows come back in whatever order the planner and sort give, which SQLite does not reproduce.
`query_findings_all_runs_by_scope` re-reads ambiguous scopes with the per-scope query and
`query_metrics_by_scope` orders by (metric_name, id); this re-proves both on every run that has Postgres.
Runs in the throwaway test schema (pg_registry); skipped without Postgres.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project

pytestmark = pytest.mark.requires_pgvector

KIND = "architecture_recovery"
SCOPES = ("", "svc/a", "svc/b")


@pytest.fixture
def seeded(pg_registry):
    r = pg_registry
    r.add(Project(slug="pgeq", display_name="pgeq", github_url="https://github.com/o/pgeq"))
    for ts, run in (("2026-10-01T00:00:00", "detect"), ("2026-10-02T00:00:00", "coupling"),
                    ("2026-10-02T00:00:00", "tied"), ("2026-10-03T00:00:00", "detect")):
        for scope in SCOPES:
            r.upsert_finding("pgeq", KIND, [
                {"check_name": "component", "label": run, "confidence": 60 + len(run),
                 "detail": {"slug": f"code::{scope}", "run_label": run, "type": f"T-{run}"}},
                {"check_name": "identity", "label": run, "summary": f"id {run}"},
                {"check_name": "shape", "label": run, "summary": f"shape {run}"},
            ], surveyed_at=ts, scope_locator=scope)
    for scope in SCOPES:
        r.upsert_metric("pgeq", KIND, {"confidence": 50.0, "evidence_count": 1.0},
                        surveyed_at="2026-10-01T00:00:00", scope_locator=scope)
        # two writers, same latest instant, same metric_name, different values
        r.upsert_metric("pgeq", KIND, {"evidence_count": 2.0, "confidence": 70.0, "cochange": 0.1},
                        surveyed_at="2026-10-03T00:00:00", scope_locator=scope, detail={"n": 1})
        r.upsert_metric("pgeq", KIND, {"evidence_count": 1.0, "confidence": 40.0},
                        surveyed_at="2026-10-03T00:00:00", scope_locator=scope)
    return r


def test_findings_bulk_is_exactly_the_per_scope_rows_in_the_same_order(seeded):
    bulk = seeded.query_findings_all_runs_by_scope(
        "pgeq", KIND, order_class=lambda row: row["check_name"] == "component")
    assert set(bulk) == set(SCOPES)
    for scope in SCOPES:
        assert bulk[scope] == seeded.query_findings_all_runs("pgeq", KIND, scope), repr(scope)
        assert len(bulk[scope]) == 12


def test_metrics_bulk_is_exactly_the_per_scope_dict_with_the_same_key_order(seeded):
    bulk = seeded.query_metrics_by_scope("pgeq", KIND)
    assert set(bulk) == set(SCOPES)
    for scope in SCOPES:
        want = seeded.query_metrics("pgeq", KIND, scope)
        assert bulk[scope] == want, repr(scope)
        assert json.dumps(bulk[scope]) == json.dumps(want), f"key order differs for {scope!r}"
