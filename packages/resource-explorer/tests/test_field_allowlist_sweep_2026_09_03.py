"""Regression guards for the remaining fixes in Backlog.md item 3's
31-reader field-allowlist sweep (2026-09-03) — every reader here previously
dropped a real, load-bearing field the writer had already computed and
persisted. Uses a real ProjectRegistry (SQLite) and seeds data directly
through upsert_finding/upsert_metric rather than re-simulating each
surveyor's full write path, since the point of each test is "does the
reader surface what was persisted", not "does the surveyor compute it
correctly" (covered by each surveyor's own test file).
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import (
    _architecture_interfaces_results,
    _architecture_recovery_results,
    _cii_badge_results,
    _ci_quality_results,
    _data_profile_results,
    _interface_surface_results,
    _manifest_parse_results,
    _repo_conventions_results,
    _website_ingestion_results,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="acme-widget", display_name="widget",
                github_url="https://github.com/acme/widget", collections=[])
    registry.add(p)
    return p


class TestCiQualityResultsSurfacesDetail:
    def test_workflow_files_and_full_keyword_list_reach_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "ci_quality", [{
            "check_name": "runs_tests", "label": "pass", "confidence": 100,
            "summary": "CI runs tests (matched: pytest, unittest, nose)",
            "detail": {"workflow_files": [".github/workflows/ci.yml", ".github/workflows/nightly.yml"],
                       "matched_keywords": ["pytest", "unittest", "nose", "tox"]},
        }])
        out = _ci_quality_results(registry, project.slug)
        row = out["findings"][0]
        assert row["detail"]["workflow_files"] == [
            ".github/workflows/ci.yml", ".github/workflows/nightly.yml"]
        assert row["detail"]["matched_keywords"] == ["pytest", "unittest", "nose", "tox"]


class TestInterfaceSurfaceResultsSurfacesDetail:
    def test_file_count_and_full_file_list_reach_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "interface_surface", [{
            "check_name": "openapi", "label": "specified", "confidence": 90,
            "summary": "Specification file(s): a.yaml, b.yaml, c.yaml …",
            "detail": {"evidence": "specification file",
                       "files": ["a.yaml", "b.yaml", "c.yaml", "d.yaml", "e.yaml"],
                       "file_count": 5},
        }])
        out = _interface_surface_results(registry, project.slug)
        row = out["findings"][0]
        assert row["detail"]["file_count"] == 5
        assert len(row["detail"]["files"]) == 5


class TestCiiBadgeResultsSurfacesDetail:
    def test_badge_url_and_unmet_criteria_reach_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "cii_badge", [{
            "check_name": "badge_level", "label": "passing", "confidence": 100,
            "summary": "CII badge: passing (87%)",
            "detail": {"registered": True, "level": "passing", "tiered_percentage": 87,
                       "project_id": "1234", "url": "https://www.bestpractices.dev/projects/1234"},
        }, {
            "check_name": "criteria_coverage", "label": "gap", "confidence": 100,
            "summary": "12 unmet criteria",
            "detail": {"met": 88, "unmet": 12,
                       "unmet_criteria": ["crypto_weaknesses", "hardening", "warnings_fixed"]},
        }])
        out = _cii_badge_results(registry, project.slug)
        by_check = {r["check_name"]: r for r in out["findings"]}
        assert by_check["badge_level"]["detail"]["url"] == \
            "https://www.bestpractices.dev/projects/1234"
        assert by_check["badge_level"]["detail"]["project_id"] == "1234"
        assert by_check["criteria_coverage"]["detail"]["unmet_criteria"] == [
            "crypto_weaknesses", "hardening", "warnings_fixed"]


class TestRepoConventionsResultsSurfacesDetail:
    def test_full_path_and_full_keyword_and_file_lists_reach_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "repo_conventions", [{
            "check_name": "security_policy_content", "label": "pass", "confidence": 100,
            "summary": "SECURITY.md found",
            "detail": {"path": ".github/SECURITY.md",
                       "matched_keywords": ["vulnerability", "disclosure", "report", "responsible", "cve"]},
        }, {
            "check_name": "automated_build", "label": "pass", "confidence": 100,
            "summary": "Build automation: a.yml, b.yml, c.yml",
            "detail": {"files": ["a.yml", "b.yml", "c.yml", "d.yml", "e.yml"]},
        }])
        out = _repo_conventions_results(registry, project.slug)
        by_check = {r["check_name"]: r for r in out["findings"]}
        assert by_check["security_policy_content"]["detail"]["path"] == ".github/SECURITY.md"
        assert len(by_check["security_policy_content"]["detail"]["matched_keywords"]) == 5
        assert len(by_check["automated_build"]["detail"]["files"]) == 5


class TestManifestParseResultsSurfacesOutcomeDetail:
    def test_manifests_list_reaches_the_reader(self, registry, project):
        registry.upsert_metric(project.slug, "manifest_parse_dependencies", {"count": 0}, detail={
            "outcome": "unverified", "outcome_cause": "manifest_present_nothing_parsed",
            "outcome_known_positive": False,
            "outcome_detail": {"manifests": ["package.json", "pyproject.toml"]},
        })
        out = _manifest_parse_results(registry, project.slug)
        assert out["dependencies"]["manifests"] == ["package.json", "pyproject.toml"]

    def test_error_text_reaches_the_reader(self, registry, project):
        registry.upsert_metric(project.slug, "manifest_parse_ci_quality", {"count": 0}, detail={
            "outcome": "unverified", "outcome_cause": "parse_error",
            "outcome_known_positive": False,
            "outcome_detail": {"error": "YAMLError: mapping values are not allowed here"},
        })
        out = _manifest_parse_results(registry, project.slug)
        assert out["ci_quality"]["error"] == "YAMLError: mapping values are not allowed here"

    def test_no_outcome_detail_does_not_crash(self, registry, project):
        registry.upsert_metric(project.slug, "manifest_parse_conventions", {"count": 3}, detail={
            "outcome": "recovered", "outcome_cause": "", "outcome_known_positive": True,
        })
        out = _manifest_parse_results(registry, project.slug)
        assert "manifests" not in out["conventions"]
        assert "error" not in out["conventions"]


class TestWebsiteIngestionResultsSurfacesOwnerAndError:
    def test_ingested_by_and_ingested_at_reach_the_reader(self, registry, project):
        registry.upsert_metric(project.slug, "website_ingestion", {"chunks": 0, "pages_fetched": 0}, detail={
            "reason": "already_ingested", "ingested_by": "another-repo", "ingested_at": "2026-08-01",
        })
        out = _website_ingestion_results(registry, project.slug)
        assert out["ingested_by"] == "another-repo"
        assert out["ingested_at"] == "2026-08-01"

    def test_error_reaches_the_reader(self, registry, project):
        registry.upsert_metric(project.slug, "website_ingestion", {"chunks": 0, "pages_fetched": 0}, detail={
            "reason": "discovery_failed", "error": "ConnectionError: name resolution failed",
        })
        out = _website_ingestion_results(registry, project.slug)
        assert out["error"] == "ConnectionError: name resolution failed"

    def test_empty_ingested_by_is_dropped_not_shown_as_blank(self, registry, project):
        """Matches the existing filter behaviour for url/collection/reason —
        an empty descriptive field must not render as a label with nothing
        beside it."""
        registry.upsert_metric(project.slug, "website_ingestion", {"chunks": 3, "pages_fetched": 1}, detail={
            "reason": "", "url": "https://example.com",
        })
        out = _website_ingestion_results(registry, project.slug)
        assert "ingested_by" not in out
        assert "error" not in out


class TestArchitectureInterfacesResultsSurfacesOperationCount:
    def test_operation_count_reaches_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "architecture_interfaces", [{
            "check_name": "port:api", "label": "Input-Output", "confidence": 70,
            "summary": "web — HTTP API",
            "detail": {"component": "web", "port": "api", "direction": "Input-Output",
                       "protocol": "HTTP", "kind": "port",
                       "evidence": {"path": "compose.yaml", "line": 12},
                       "additionalProperties": {"operationCount": "18", "interfaceName": "WebAPI"}},
        }])
        out = _architecture_interfaces_results(registry, project.slug)
        dep = out["deployments"][0]
        comp = dep["components"][0]
        assert comp["ports"][0]["operation_count"] == "18"


class TestArchitectureRecoveryResultsSurfacesIdentityAndBlueprint:
    def test_identity_and_blueprint_reach_the_reader(self, registry, project):
        registry.upsert_finding(project.slug, "architecture_recovery", [{
            "check_name": "component", "label": "code_marker", "confidence": 80,
            "summary": "web service",
            "detail": {"name": "web", "slug": "web", "type": "service",
                       "perspective": "physical", "outcome": "recovered",
                       "identity": {"method": "deployment-unit", "value": "web",
                                    "deployment_context": "compose"},
                       "blueprint": "physical::core-services"},
        }], scope_locator="services/web")
        out = _architecture_recovery_results(registry, project.slug)
        comp = next(c for c in out["components"] if c["path"] == "services/web")
        assert comp["identity"] == {"method": "deployment-unit", "value": "web",
                                    "deployment_context": "compose"}
        assert comp["blueprint"] == "physical::core-services"

    def test_missing_identity_and_blueprint_are_none_not_a_crash(self, registry, project):
        registry.upsert_finding(project.slug, "architecture_recovery", [{
            "check_name": "component", "label": "code_marker", "confidence": 80,
            "summary": "web service",
            "detail": {"name": "web", "slug": "web", "type": "service"},
        }], scope_locator="services/web")
        out = _architecture_recovery_results(registry, project.slug)
        comp = next(c for c in out["components"] if c["path"] == "services/web")
        assert comp["identity"] is None
        assert comp["blueprint"] is None


class TestDataProfileResultsSurfacesFormats:
    def test_formats_breakdown_reaches_the_reader(self, registry, project):
        registry.upsert_metric(project.slug, "data_profile", {
            "total_files": 5, "total_size_bytes": 1024,
        }, detail={
            "outcome": "recovered", "outcome_cause": "", "outcome_known_positive": True,
            "formats": {
                "csv": {"count": 3, "total_size": "800", "directories": ["data/"]},
                "parquet": {"count": 2, "total_size": "224", "directories": ["data/raw/"]},
            },
        })
        out = _data_profile_results(registry, project.slug)
        assert out["formats"]["csv"]["count"] == 3
        assert out["formats"]["parquet"]["directories"] == ["data/raw/"]

    def test_no_metric_yet_returns_empty_formats_not_a_crash(self, registry, project):
        out = _data_profile_results(registry, project.slug)
        assert out["formats"] == {}
