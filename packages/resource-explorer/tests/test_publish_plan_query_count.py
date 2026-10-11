"""publish_plan reads architecture_materialized_blueprints a constant number of times, however many
blueprints there are (it used to make two reads per blueprint, twice over: 1,064 queries on 266 blueprints)."""
from __future__ import annotations

import json

import pytest

from resource_explorer import architecture_publish as ap
from resource_explorer.registry import Project, ProjectRegistry

pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

READERS = ("get_materialized_blueprint", "get_materialized_blueprints",
           "get_materialized_blueprint_by_identity", "get_materialized_blueprints_by_identity")


def _registry(tmp_path, n):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    rows = []
    for i in range(n):
        persp = "physical" if i % 2 else "logical"
        rows.append({"check_name": "candidate_blueprint", "label": f"c{i}",
                     "detail": {"name": f"c{i}", "perspective": persp, "signal": "compose", "carrier": "compose.yaml",
                                "composed_into": "", "size": 0, "members": [], "children": [], "parent": "",
                                "oversized": False, "target_size": 8, "run_scope": "", "not_a_claim": True}})
    reg.upsert_finding("p", "architecture_blueprints", rows, surveyed_at="2026-09-03T00:00:00")
    for i in range(n):
        persp = "physical" if i % 2 else "logical"
        if i % 3 == 0:
            reg.record_component_verdict("repo", "p", f"{persp}::c{i}", "accepted", "", "",
                                         verdict_target="blueprint", decided_by="x")
        if i == 0:   # one already in Egeria: it holds its kind's plain identity
            reg.record_materialized_blueprint("repo", "p", persp, f"c{i}", "SolutionBlueprint::repo::p::logical", "g0")
    return reg


def _count(reg, monkeypatch):
    calls = []
    for name in READERS:
        if not hasattr(type(reg), name):
            continue
        real = getattr(type(reg), name)
        monkeypatch.setattr(type(reg), name, lambda self, *a, _r=real, _n=name, **k: calls.append(_n) or _r(self, *a, **k))
    return calls


@pytest.mark.parametrize("n", [5, 30])
def test_publish_plan_reads_the_blueprint_cache_at_most_twice(tmp_path, monkeypatch, n):
    reg = _registry(tmp_path, n)
    calls = _count(reg, monkeypatch)
    plan = ap.publish_plan(reg, "p")
    assert len(calls) <= 2, calls
    assert len(plan["blueprints"]["to_write"]) + len(plan["blueprints"]["needs_identifier"]) > 0


def test_the_identity_the_accept_pane_reads_is_unchanged(tmp_path):
    from resource_explorer.surveyors.repo_survey_definition_adapter import _candidate_blueprints_results
    reg = _registry(tmp_path, 6)
    by = {(b["perspective"], b["cluster_name"]): b["identity"] for b in _candidate_blueprints_results(reg, "p")}
    assert by[("logical", "c0")]["needs_identifier"] is False           # in Egeria: its own
    assert by[("logical", "c2")]["needs_identifier"] is True            # c0 holds the plain identity
    assert by[("logical", "c2")]["sentence"]
    # JSON-stable, for the before/after comparison in the handoff note
    json.dumps(ap.publish_plan(reg, "p"), sort_keys=True)
