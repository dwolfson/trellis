"""docs/blueprint-materialization-plan.md Phase C — the new `data.blueprints`
key on `_architecture_recovery_results`, read from clustering.py's
candidate_blueprint findings and merged with verdict/materialization state
via `curate.py`'s own key shape (f"{perspective}::{cluster_name}").
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _architecture_recovery_results,
    _candidate_blueprints_results,
)


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="A test project",
        collections=["myproj_python_code", "myproj_markdown_docs"],
    ))
    return r


def _seed_cluster(registry, slug, *, members=None, children=None, oversized=False,
                  name="core-services", perspective="physical",
                  surveyed_at="2026-09-03T00:00:00"):
    registry.upsert_finding(slug, "architecture_blueprints", [{
        "check_name": "candidate_blueprint", "label": name,
        "detail": {"name": name, "perspective": perspective, "signal": "compose",
                   "carrier": "compose.yaml", "composed_into": "",
                   "size": len(members or []), "members": members or [],
                   "children": children or [], "parent": "", "oversized": oversized,
                   "target_size": 8, "run_scope": "", "not_a_claim": True},
    }], surveyed_at=surveyed_at)


class TestCandidateBlueprintsResults:
    def test_no_clusters_returns_empty_list(self, registry):
        assert _candidate_blueprints_results(registry, "myproj") == []

    def test_one_cluster_round_trips(self, registry):
        _seed_cluster(registry, "myproj", members=["a", "b"])
        out = _candidate_blueprints_results(registry, "myproj")
        assert len(out) == 1
        bp = out[0]
        assert bp["perspective"] == "physical"
        assert bp["cluster_name"] == "core-services"
        assert bp["members"] == ["a", "b"]
        assert bp["oversized"] is False
        assert bp["verdict"] is None
        assert bp["materialized"] is None

    def test_oversized_flag_passes_through(self, registry):
        _seed_cluster(registry, "myproj", members=["a"] * 12, oversized=True)
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["oversized"] is True

    def test_two_perspectives_are_distinct_entries(self, registry):
        _seed_cluster(registry, "myproj", perspective="physical", name="core")
        _seed_cluster(registry, "myproj", perspective="deployment", name="core")
        out = _candidate_blueprints_results(registry, "myproj")
        keys = {(bp["perspective"], bp["cluster_name"]) for bp in out}
        assert keys == {("physical", "core"), ("deployment", "core")}

    def test_later_survey_supersedes_earlier_for_same_identity(self, registry):
        _seed_cluster(registry, "myproj", members=["a"], surveyed_at="2026-09-01T00:00:00")
        _seed_cluster(registry, "myproj", members=["a", "b", "c"], surveyed_at="2026-09-03T00:00:00")
        out = _candidate_blueprints_results(registry, "myproj")
        assert len(out) == 1
        assert out[0]["members"] == ["a", "b", "c"]

    def test_verdict_and_materialization_are_merged_on(self, registry):
        _seed_cluster(registry, "myproj", members=["a"])
        registry.record_component_verdict(
            "repo", "myproj", "physical::core-services", "accepted", "", "",
            verdict_target="blueprint",
        )
        registry.record_materialized_blueprint(
            "repo", "myproj", "physical", "core-services",
            "SolutionBlueprint::repo::myproj::physical::core-services", "bp-guid-1",
        )
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["verdict"]["verdict"] == "accepted"
        assert out[0]["materialized"]["guid"] == "bp-guid-1"

    def test_a_child_cluster_carries_its_own_entry(self, registry):
        registry.upsert_finding("myproj", "architecture_blueprints", [{
            "check_name": "candidate_blueprint", "label": "backend",
            "detail": {"name": "backend", "perspective": "physical", "signal": "path",
                       "carrier": "", "composed_into": "", "size": 2,
                       "members": ["a", "b"], "children": [], "parent": "core",
                       "oversized": False, "target_size": 8, "run_scope": "",
                       "not_a_claim": True},
        }], surveyed_at="2026-09-03T00:00:00")
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["parent"] == "core"

    def test_component_verdicts_do_not_leak_into_blueprint_results(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        registry.record_component_verdict("repo", "myproj", "src/web", "accepted", "", "")
        _seed_cluster(registry, "myproj", members=["web"])
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["verdict"] is None


class TestArchitectureRecoveryResultsCarriesBlueprints:
    def test_blueprints_key_present_and_empty_by_default(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        result = _architecture_recovery_results(registry, "myproj")
        assert result["blueprints"] == []

    def test_blueprints_key_carries_seeded_clusters(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        _seed_cluster(registry, "myproj", members=["web"])
        result = _architecture_recovery_results(registry, "myproj")
        assert len(result["blueprints"]) == 1


class TestMemberAndChildStatus:
    """2026-09-03 Curate redesign — member_status/child_status resolve a
    blueprint's members/children to their own verdict/materialization state,
    so the frontend can render "which members are already approved" without
    a second round trip."""

    def test_member_with_no_verdict_is_awaiting(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        _seed_cluster(registry, "myproj", members=["web"])
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["member_status"] == [
            {"slug": "web", "scope_locator": "src/web", "verdict": None, "materialized": None},
        ]

    def test_member_with_a_verdict_and_materialization_resolves_both(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        registry.record_component_verdict("repo", "myproj", "src/web", "accepted", "", "")
        registry.record_materialized_component(
            "repo", "myproj", "src/web", "SolutionComponent::repo::myproj::src/web", "guid-web",
        )
        _seed_cluster(registry, "myproj", members=["web"])
        out = _candidate_blueprints_results(registry, "myproj")
        st = out[0]["member_status"][0]
        assert st["verdict"]["verdict"] == "accepted"
        assert st["materialized"]["guid"] == "guid-web"

    def test_member_slug_with_no_matching_component_has_empty_scope(self, registry):
        """A member slug that clustering.py knows about but that has no
        currently-live component finding (e.g. withdrawn since the cluster
        was proposed) resolves to scope_locator="" and null verdict/
        materialized — never raises, never crashes the whole read."""
        _seed_cluster(registry, "myproj", members=["ghost"])
        out = _candidate_blueprints_results(registry, "myproj")
        assert out[0]["member_status"] == [
            {"slug": "ghost", "scope_locator": "", "verdict": None, "materialized": None},
        ]

    def test_child_blueprint_verdict_resolves_by_perspective_and_name(self, registry):
        _seed_cluster(registry, "myproj", perspective="physical", name="parent-bp",
                      children=["child-bp"])
        registry.upsert_finding("myproj", "architecture_blueprints", [{
            "check_name": "candidate_blueprint", "label": "child-bp",
            "detail": {"name": "child-bp", "perspective": "physical", "signal": "compose",
                       "carrier": "", "composed_into": "", "size": 1, "members": ["web"],
                       "children": [], "parent": "parent-bp", "oversized": False,
                       "target_size": 8, "run_scope": "", "not_a_claim": True},
        }], surveyed_at="2026-09-03T00:00:00")
        registry.record_component_verdict(
            "repo", "myproj", "physical::child-bp", "accepted", "", "",
            verdict_target="blueprint",
        )
        out = _candidate_blueprints_results(registry, "myproj")
        parent = next(bp for bp in out if bp["cluster_name"] == "parent-bp")
        assert parent["child_status"] == [
            {"cluster_name": "child-bp",
             "verdict": {"verdict": "accepted", "retyped_to": "", "note": "",
                         "decided_at": parent["child_status"][0]["verdict"]["decided_at"]},
             "materialized": None},
        ]


class TestComponentBlueprintBacklink:
    """2026-09-03 Curate redesign item 5 — "jump from a component to its
    candidate blueprints". Derived from the blueprints list's own `members`
    at read time (never trusted from Component.blueprint, which is
    single-valued and overwritten per clustering() call — see the
    docstring on _architecture_recovery_results' backlink block)."""

    def test_component_with_no_blueprint_membership_has_empty_backlink(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        result = _architecture_recovery_results(registry, "myproj")
        assert result["components"][0]["candidate_blueprints"] == []

    def test_component_in_one_blueprint_has_one_backlink(self, registry):
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        _seed_cluster(registry, "myproj", members=["web"], perspective="logical", name="core")
        result = _architecture_recovery_results(registry, "myproj")
        assert result["components"][0]["candidate_blueprints"] == [
            {"perspective": "logical", "cluster_name": "core"},
        ]

    def test_component_claimed_by_two_perspectives_has_both_backlinks(self, registry):
        """The exact case Component.blueprint (single-valued, last-write-
        wins) would get wrong — a component proposed into both a logical
        AND a physical blueprint must show both, not just whichever
        clustering() call happened to run last."""
        registry.upsert_finding("myproj", "architecture_recovery", [{
            "check_name": "component", "label": "manifest",
            "detail": {"name": "web", "slug": "web", "type": "Software Service"},
        }], surveyed_at="2026-09-03T00:00:00", scope_locator="src/web")
        _seed_cluster(registry, "myproj", members=["web"], perspective="logical", name="core")
        _seed_cluster(registry, "myproj", members=["web"], perspective="physical", name="deploy-unit")
        result = _architecture_recovery_results(registry, "myproj")
        backlinks = result["components"][0]["candidate_blueprints"]
        assert {(b["perspective"], b["cluster_name"]) for b in backlinks} == {
            ("logical", "core"), ("physical", "deploy-unit"),
        }
