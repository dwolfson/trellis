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

    # Actions without findings -- not surveys, never candidates for a Results
    # dashboard (docs/Backlog.md "Survey Results dashboards cover 14 of 29
    # analyses"). egeria_publish writes to Egeria; rag_ingestion/
    # website_ingestion feed pgvector; repo_profile_refresh refreshes the
    # coarse profile tables another card already reads.
    _NON_SURVEY_ACTIONS = frozenset({
        "egeria_publish", "rag_ingestion", "website_ingestion", "repo_profile_refresh",
    })

    def test_every_findings_producing_analysis_has_a_dashboard(self):
        """Ratchet against the coverage gap this whole registry was built to
        close: 15 of 29 analyses had no dashboard as of 2026-08-31, 11 of
        them real gaps rather than non-survey actions. A future analysis
        added to the catalog with no dashboard entry should fail here loudly,
        not sit invisible in the Results tab until someone happens to
        re-audit by hand."""
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        all_ids = {a["id"] for a in get_analyses("repo", include_egeria_live=False)}
        covered: set[str] = set()
        for dashboard in SURVEY_RESULT_DASHBOARDS.values():
            covered.update(dashboard.analysis_ids)
        missing = all_ids - covered - self._NON_SURVEY_ACTIONS
        assert not missing, f"analyses with no Results dashboard: {sorted(missing)}"

    def test_custom_dashboards_declare_a_renderer_name(self):
        for dashboard in SURVEY_RESULT_DASHBOARDS.values():
            if dashboard.render == "custom":
                assert dashboard.custom_renderer

    def test_security_overview_spans_the_expected_analysis_ids(self):
        """2026-08-31: gained the three externally-sourced trust signals
        (cve_scan, foss_scorecard, cii_badge) — same "is this trustworthy"
        question, asked from outside the repo instead of inside it."""
        d = SURVEY_RESULT_DASHBOARDS["security_overview"]
        assert set(d.analysis_ids) == {
            "security_scan", "security_features", "ci_quality",
            "license_classification", "repo_conventions",
            "cve_scan", "foss_scorecard", "cii_badge",
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
        reports repository_health (scouting) and maturity (discovery, retagged
        from assessment 2026-08-20)."""
        for stage in ("scouting", "discovery"):
            resp = client.get(
                f"/api/projects/myproj/survey-results?stage={stage}&include_empty=true")
            ids = {d["id"] for d in resp.json()["dashboards"]}
            assert "health_maturity" in ids, f"missing from {stage}"

    def test_stage_filter_excludes_other_stages(self, client):
        resp = client.get(
            "/api/projects/myproj/survey-results?stage=analysis&include_empty=true")
        ids = {d["id"] for d in resp.json()["dashboards"]}
        assert "security_overview" not in ids   # discovery/assessment, not analysis
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

    def test_each_analysis_carries_its_headline(self, client, registry):
        """2026-08-31: security_overview's scorecard gained dedicated tiles for
        cve_scan/foss_scorecard/cii_badge, sourced from `headline` (added to
        the Tier-2 payload alongside `results`) rather than re-deriving a
        summary from raw findings in JS — the same {label, tone} shape the
        Tier-1 stat tiles already use."""
        registry.upsert_finding("myproj", "cve_scan", [
            {"check_name": "advisory", "label": "found", "summary": "CVE-2024-1234"},
        ])
        registry.upsert_metric("myproj", "cve_scan", {"advisories": 1, "packages_affected": 1,
                                                       "checked": 3},
                                detail={"scanned": True, "recorded": 3})
        resp = client.get("/api/projects/myproj/survey-results")
        security = next(d for d in resp.json()["dashboards"] if d["id"] == "security_overview")
        cve = next(a for a in security["analyses"] if a["analysis_id"] == "cve_scan")
        assert cve["headline"]["tone"] == "bad"
        assert "1 advisor" in cve["headline"]["label"]

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
