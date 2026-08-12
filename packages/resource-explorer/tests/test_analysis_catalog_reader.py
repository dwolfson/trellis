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
        assert {a["id"] for a in analyses} == {
            "language_file_classification", "repository_health", "repo_profile_refresh",
        }

    def test_filters_to_assessment(self):
        analyses = acr.get_analyses("repo", intent="assessment", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert ids == {"security_scan", "documentation_coverage", "license_classification"}

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

    def test_perspective_excludes_entries_not_tagged_for_it(self):
        analyses = acr.get_analyses("database", perspective="data_scientist", include_egeria_live=False)
        ids = {a["id"] for a in analyses}
        assert "privilege_audit" not in ids  # tagged 'security'/'dba', no 'all'
        assert "schema_inventory" in ids  # tagged 'all'

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


class TestTargetShape:
    """Repo scope-narrowing funnel plan, D5 — every catalog entry declares
    a target_shape; every live-Egeria-merged entry defaults to the
    conservative whole_resource_only since its real shape isn't known."""

    def test_every_local_entry_has_a_target_shape(self):
        for rtype in ("repo", "database", "filesystem"):
            for a in acr.get_analyses(rtype, include_egeria_live=False):
                assert a["target_shape"] in {
                    "corpus", "single_container", "single_leaf", "whole_resource_only",
                }, a["id"]

    def test_matches_the_grounded_inventory_for_a_sample(self):
        # Regression guard against the target-shape audit going stale —
        # spot-checks a few entries whose shape was specifically corrected
        # or discussed during design, not every single one.
        by_id = {a["id"]: a for a in acr.get_analyses("repo", include_egeria_live=False)}
        assert by_id["security_scan"]["target_shape"] == "whole_resource_only"
        assert by_id["api_structure"]["target_shape"] == "corpus"
        assert by_id["data_file_profiling"]["target_shape"] == "corpus"
        assert by_id["language_file_classification"]["target_shape"] == "whole_resource_only"

        db_by_id = {a["id"]: a for a in acr.get_analyses("database", include_egeria_live=False)}
        assert db_by_id["schema_inventory"]["target_shape"] == "single_container"
        assert db_by_id["egeria_db_survey"]["target_shape"] == "whole_resource_only"

    def test_egeria_live_merged_entry_defaults_to_whole_resource_only(self):
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
        live = next(a for a in analyses if a.get("live_from_egeria"))
        assert live["target_shape"] == "whole_resource_only"


class TestShapeCompatibility:
    """D6 — a target_shape only makes sense against certain selected
    sub-resource kinds."""

    def test_corpus_is_compatible_with_anything(self):
        assert acr.is_shape_compatible("corpus", "folder") is True
        assert acr.is_shape_compatible("corpus", "file") is True
        assert acr.is_shape_compatible("corpus", "schema") is True
        assert acr.is_shape_compatible("corpus", "table") is True

    def test_single_container_only_compatible_with_container_kinds(self):
        assert acr.is_shape_compatible("single_container", "folder") is True
        assert acr.is_shape_compatible("single_container", "schema") is True
        assert acr.is_shape_compatible("single_container", "file") is False
        assert acr.is_shape_compatible("single_container", "table") is False

    def test_single_leaf_only_compatible_with_leaf_kinds(self):
        assert acr.is_shape_compatible("single_leaf", "file") is True
        assert acr.is_shape_compatible("single_leaf", "table") is True
        assert acr.is_shape_compatible("single_leaf", "folder") is False

    def test_whole_resource_only_is_never_compatible_with_a_selection(self):
        assert acr.is_shape_compatible("whole_resource_only", "folder") is False
        assert acr.is_shape_compatible("whole_resource_only", "file") is False

    def test_compatible_analyses_filters_the_full_catalog(self):
        # A folder selection should surface api_structure/data_file_profiling
        # (corpus) but never repository_health/security_scan (whole-resource-only).
        ids = {a["id"] for a in acr.compatible_analyses("repo", "folder", include_egeria_live=False)}
        assert "api_structure" in ids
        assert "data_file_profiling" in ids
        assert "repository_health" not in ids
        assert "security_scan" not in ids

    def test_compatible_analyses_for_a_file_selection(self):
        ids = {a["id"] for a in acr.compatible_analyses("repo", "file", include_egeria_live=False)}
        assert "api_structure" in ids  # corpus degrades fine to one file
        assert "repository_health" not in ids
