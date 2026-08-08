"""Tests for the externalized analysis catalog
(configdata/analysis_catalog.yaml + its loader/reader)."""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.surveyors import analysis_catalog_reader as acr


def setup_function(_fn):
    acr.clear_cache()


ALL_INTENTS = {
    "scouting",
    "assessment",
    "discovery",
    "analysis",
    "enrichment",
    "understanding",
    "curate",
}


class TestLoadCatalog:
    def test_repo_analyses_loaded(self):
        analyses = acr.get_analyses("repo", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "language_file_classification" in ids
        assert "egeria_publish" in ids

    def test_database_analyses_loaded(self):
        analyses = acr.get_analyses("database", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "schema_inventory" in ids
        assert "egeria_db_survey" in ids

    def test_filesystem_analyses_loaded(self):
        analyses = acr.get_analyses("filesystem", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "filesystem_inventory" in ids

    def test_unknown_resource_type_returns_empty(self):
        assert acr.get_analyses("nonexistent", include_egeria_live=False) == []

    def test_returns_plain_dicts_not_dataclasses(self):
        analyses = acr.get_analyses("repo", include_egeria_live=False)
        assert all(isinstance(a, dict) for a in analyses)

    def test_all_intent_values_are_within_the_canonical_seven(self):
        for rtype in ("repo", "database", "filesystem"):
            for a in acr.get_analyses(rtype, include_egeria_live=False):
                assert a["intent"] in ALL_INTENTS, f"{a['id']} has unexpected intent {a['intent']!r}"

    def test_reclassified_entries_moved_to_analysis_intent(self):
        # These were 'assessment' in the old catalog; the intent-shell rewrite
        # reclassifies them to 'analysis' (structural/quantitative, not scored).
        analyses = {a["id"]: a for a in acr.get_analyses("repo", include_egeria_live=False)}
        assert analyses["dependency_analysis"]["intent"] == "analysis"
        assert analyses["data_file_profiling"]["intent"] == "analysis"
        assert analyses["api_structure"]["intent"] == "analysis"

    def test_publish_actions_reclassified_to_curate(self):
        repo = {a["id"]: a for a in acr.get_analyses("repo", include_egeria_live=False)}
        db = {a["id"]: a for a in acr.get_analyses("database", include_egeria_live=False)}
        assert repo["egeria_publish"]["intent"] == "curate"
        assert db["egeria_db_survey"]["intent"] == "curate"


class TestFilterByIntent:
    def test_filters_to_scouting(self):
        analyses = acr.get_analyses("repo", intent="scouting", include_egeria_live=False)
        assert {a["id"] for a in analyses} == {"language_file_classification", "repository_health"}

    def test_filters_to_assessment(self):
        analyses = acr.get_analyses("repo", intent="assessment", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert ids == {"security_scan", "documentation_coverage"}

    def test_intent_all_returns_everything(self):
        unfiltered = acr.get_analyses("repo", include_egeria_live=False)
        all_intent = acr.get_analyses("repo", intent="all", include_egeria_live=False)
        assert len(unfiltered) == len(all_intent)

    def test_discovery_and_enrichment_have_no_entries_by_design(self):
        for rtype in ("repo", "database", "filesystem"):
            assert acr.get_analyses(rtype, intent="discovery", include_egeria_live=False) == []
            assert acr.get_analyses(rtype, intent="enrichment", include_egeria_live=False) == []


class TestFilterByPerspective:
    def test_filters_to_security(self):
        analyses = acr.get_analyses("database", perspective="security", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "privilege_audit" in ids
        assert "index_health" not in ids  # tagged only 'dba', no 'all'

    def test_all_perspective_entries_included_regardless(self):
        analyses = acr.get_analyses("repo", perspective="security", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "language_file_classification" in ids  # tagged 'all'

    def test_perspective_all_returns_everything(self):
        unfiltered = acr.get_analyses("database", include_egeria_live=False)
        all_persp = acr.get_analyses("database", perspective="all", include_egeria_live=False)
        assert len(unfiltered) == len(all_persp)


class TestListPerspectives:
    def test_returns_distinct_real_perspectives(self):
        perspectives = acr.list_perspectives()
        assert "all" not in perspectives
        assert "dba" in perspectives
        assert "security" in perspectives
        assert "steward" in perspectives
        assert "data_scientist" in perspectives

    def test_sorted(self):
        perspectives = acr.list_perspectives()
        assert perspectives == sorted(perspectives)


class TestEgeriaLiveMerge:
    def test_disabled_by_default_flag_returns_local_only(self):
        analyses = acr.get_analyses("database", include_egeria_live=False)
        assert all(not a.get("live_from_egeria") for a in analyses)

    def test_merge_failure_is_fail_soft_and_returns_local_only(self):
        with patch(
            "resource_explorer.surveyors.egeria_tech_type_catalog.EgeriaTechTypeCatalog"
        ) as MockCatalog:
            MockCatalog.return_value.get_produced_annotation_types.side_effect = RuntimeError("no connection")
            analyses = acr.get_analyses("database", include_egeria_live=True)
        # Local entries still present, no exception propagated.
        ids = {a["id"] for a in analyses}
        assert "schema_inventory" in ids
        assert all(not a.get("live_from_egeria") for a in analyses)

    def test_merge_success_appends_egeria_native_entries(self):
        with patch(
            "resource_explorer.surveyors.egeria_tech_type_catalog.EgeriaTechTypeCatalog"
        ) as MockCatalog:
            MockCatalog.return_value.get_produced_annotation_types.return_value = [
                {
                    "name": "Column Data Quality",
                    "description": "Native column-level quality scoring.",
                    "explanation": "",
                    "annotation_type": "DataClassAnnotation",
                    "analysis_step_name": "profile-columns",
                }
            ]
            analyses = acr.get_analyses("database", include_egeria_live=True)
        live = [a for a in analyses if a.get("live_from_egeria")]
        assert len(live) == 1
        assert live[0]["name"] == "Column Data Quality"
        assert live[0]["source"] == "egeria"

    def test_resource_type_without_known_tech_type_gets_no_live_entries(self):
        # 'repo' has no entry in _RESOURCE_TYPE_TO_TECH_TYPE yet.
        analyses = acr.get_analyses("repo", include_egeria_live=True)
        assert all(not a.get("live_from_egeria") for a in analyses)
