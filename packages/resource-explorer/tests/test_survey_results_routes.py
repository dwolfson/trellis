"""Tests for the Survey Results dashboard routes
(docs/survey-results-dashboard-plan.md):
GET /{slug}/survey-results (Tier 2), GET /{slug}/survey-results/summary (Tier 1).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    ANALYSIS_KINDS,
    SURVEY_RESULT_DASHBOARDS,
    get_dashboard_perspectives,
)


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
    ))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestSurveyResultDashboardsRegistry:
    def test_every_dashboard_analysis_id_resolves_to_a_real_analysis_kind(self):
        # Regression guard, same spirit as the D3 CSV<->STEP_REGISTRY guard —
        # a dashboard referencing a renamed/removed analysis_id should fail
        # loudly here, not silently drop it at render time.
        for dashboard in SURVEY_RESULT_DASHBOARDS.values():
            unknown = [a for a in dashboard.analysis_ids if a not in ANALYSIS_KINDS]
            assert not unknown, f"{dashboard.id}: unknown analysis_ids {unknown}"

    def test_custom_dashboards_declare_a_renderer_name(self):
        for dashboard in SURVEY_RESULT_DASHBOARDS.values():
            if dashboard.render == "custom":
                assert dashboard.custom_renderer

    def test_security_overview_spans_the_expected_analysis_ids(self):
        d = SURVEY_RESULT_DASHBOARDS["security_overview"]
        assert set(d.analysis_ids) == {
            "security_scan", "security_features", "ci_quality",
            "license_classification", "repo_conventions",
        }


class TestGetDashboardPerspectives:
    def test_union_across_analysis_ids_deduped_and_order_stable(self):
        perspectives = get_dashboard_perspectives(["security_scan"])
        assert perspectives  # security_scan is answered by real Questions
        assert len(perspectives) == len(set(perspectives))

    def test_unknown_analysis_id_yields_empty_list(self):
        assert get_dashboard_perspectives(["not_a_real_analysis_id"]) == []


class TestSurveyResultsRoute:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/projects/not-a-real-repo/survey-results")
        assert resp.status_code == 404

    def test_include_empty_returns_every_registered_dashboard(self, client):
        """The old unconditional behaviour, now behind an explicit opt-in."""
        resp = client.get("/api/projects/myproj/survey-results?include_empty=true")
        assert resp.status_code == 200
        data = resp.json()
        assert {d["id"] for d in data["dashboards"]} == set(SURVEY_RESULT_DASHBOARDS.keys())

    def test_unsurveyed_repo_shows_no_cards_by_default(self, client):
        """The reported bug: Results advertised analyses the repo had never been
        surveyed for. Every dashboard was returned unconditionally, and a card
        with nothing behind it rendered as an empty shell — six cards spanning
        thirteen analyses for a repo where only a couple had ever run."""
        resp = client.get("/api/projects/myproj/survey-results")
        assert resp.json()["dashboards"] == []

    def test_empty_state_analyses_still_carry_shaped_results_when_asked(self, client):
        """Readers return a shaped-but-empty dict rather than raising, and that
        stays true — the gate is applied on top of it, not instead of it."""
        resp = client.get("/api/projects/myproj/survey-results?include_empty=true")
        data = resp.json()
        security = next(d for d in data["dashboards"] if d["id"] == "security_overview")
        assert all(a["results"] is not None for a in security["analyses"])  # findings=[] dict, not None
        for a in security["analyses"]:
            assert a["results"]["findings"] == []
        assert security["has_results"] is False

    def test_shaped_but_empty_results_do_not_count_as_data(self, client):
        """`{"findings": [], "gap_count": 0}` is truthy, so a plain truthiness
        check reported five-of-five analyses present for a repo that had been
        surveyed for none of them. Found live on a repo that has never had a
        deep survey."""
        resp = client.get("/api/projects/myproj/survey-results?include_empty=true")
        for d in resp.json()["dashboards"]:
            assert d["has_results"] is False, f"{d['id']} claims data it does not have"

    def test_every_dashboard_declares_its_stages(self, client):
        """Stage is derived from analysis_catalog.yaml's per-analysis intent, so
        a card cannot drift from the analyses it reports on."""
        resp = client.get("/api/projects/myproj/survey-results?include_empty=true")
        canonical = {"scouting", "discovery", "assessment", "analysis",
                     "enrichment", "understanding", "curate", "automate"}
        for d in resp.json()["dashboards"]:
            assert d["stages"], f"{d['id']} has no stage — it would be invisible everywhere"
            assert set(d["stages"]) <= canonical

    def test_stage_filter_selects_membership_not_equality(self, client):
        """A card spanning stages must appear under each of them: health_maturity
        reports repository_health (scouting) and maturity (assessment)."""
        for stage in ("scouting", "assessment"):
            resp = client.get(
                f"/api/projects/myproj/survey-results?stage={stage}&include_empty=true")
            ids = {d["id"] for d in resp.json()["dashboards"]}
            assert "health_maturity" in ids, f"missing from {stage}"

    def test_stage_filter_excludes_other_stages(self, client):
        resp = client.get(
            "/api/projects/myproj/survey-results?stage=analysis&include_empty=true")
        ids = {d["id"] for d in resp.json()["dashboards"]}
        assert "security_overview" not in ids   # assessment-only
        assert "dependencies" in ids

    def test_unknown_stage_yields_nothing_rather_than_everything(self, client):
        resp = client.get(
            "/api/projects/myproj/survey-results?stage=nonsense&include_empty=true")
        assert resp.json()["dashboards"] == []

    def test_populated_findings_surface_through_the_dashboard(self, client, registry):
        registry.upsert_finding("myproj", "security_hygiene", [
            {"check_name": "license", "label": "gap", "summary": "No SECURITY.md"},
        ])
        resp = client.get("/api/projects/myproj/survey-results")
        data = resp.json()
        security = next(d for d in data["dashboards"] if d["id"] == "security_overview")
        sec_scan = next(a for a in security["analyses"] if a["analysis_id"] == "security_scan")
        assert sec_scan["results"]["gap_count"] == 1

    def test_each_dashboard_carries_a_perspectives_list(self, client):
        resp = client.get("/api/projects/myproj/survey-results")
        data = resp.json()
        for d in data["dashboards"]:
            assert isinstance(d["perspectives"], list)


class TestSurveyResultsSummaryRoute:
    def test_unknown_repo_returns_404(self, client):
        resp = client.get("/api/projects/not-a-real-repo/survey-results/summary")
        assert resp.status_code == 404

    def test_no_data_yields_empty_tiles_not_an_error(self, client):
        resp = client.get("/api/projects/myproj/survey-results/summary?phase=scouting")
        assert resp.status_code == 200
        assert resp.json()["tiles"] == []

    def test_scouting_phase_only_returns_scouting_tagged_headlines(self, client, registry):
        # language_file_classification is scouting-tagged and has a headline
        # reader; security_scan is assessment-tagged — populating both and
        # asking for phase=scouting must surface only the former.
        registry.upsert_file_type_counts("myproj", {"Python": 3})
        registry.upsert_finding("myproj", "security_hygiene", [
            {"check_name": "license", "label": "pass", "summary": "MIT"},
        ])
        resp = client.get("/api/projects/myproj/survey-results/summary?phase=scouting")
        tiles = resp.json()["tiles"]
        assert {t["analysis_id"] for t in tiles} == {"language_file_classification"}

    def test_assessment_phase_surfaces_security_headline(self, client, registry):
        registry.upsert_finding("myproj", "security_hygiene", [
            {"check_name": "license", "label": "pass", "summary": "MIT"},
        ])
        resp = client.get("/api/projects/myproj/survey-results/summary?phase=assessment")
        tiles = resp.json()["tiles"]
        sec_tile = next(t for t in tiles if t["analysis_id"] == "security_scan")
        assert sec_tile["status"] == "ok"
        assert "1" in sec_tile["label"]

    def test_no_phase_returns_tiles_across_every_intent(self, client, registry):
        registry.upsert_file_type_counts("myproj", {"Python": 3})
        registry.upsert_finding("myproj", "security_hygiene", [
            {"check_name": "license", "label": "pass", "summary": "MIT"},
        ])
        resp = client.get("/api/projects/myproj/survey-results/summary")
        tiles = {t["analysis_id"] for t in resp.json()["tiles"]}
        assert {"language_file_classification", "security_scan"}.issubset(tiles)

    def test_headline_reader_exists_for_every_ANALYSIS_KINDS_entry_with_results(self):
        # Not every kind needs a headline (repository_health has no results
        # view at all), but every kind that DOES have a results view should
        # have SOME headline compression, or its data is invisible to Tier 1
        # entirely (silent gap, the exact failure class this guards against).
        missing = [
            k for k, v in ANALYSIS_KINDS.items()
            if v.results and not v.results.headline_reader
        ]
        assert missing == []
