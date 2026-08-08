"""Tests for Phase B's new persistence calls in SecuritySurveyor,
DocumentationSurveyor, and ApiStructureSurveyor — each surveyor's existing
annotation-building behavior must be unchanged (regression guard); each
must additionally persist correctly-shaped findings/snapshots.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.api_structure import ApiStructureSurveyor
from resource_explorer.surveyors.sub_surveyors.documentation import DocumentationSurveyor
from resource_explorer.surveyors.sub_surveyors.security import SecuritySurveyor
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    RequestForActionAnnotation,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(
        slug="myproj", display_name="My Project",
        github_url="https://github.com/test/myproj", collections=[],
    )
    registry.add(p)
    return p


class TestSecuritySurveyorPersistence:
    def test_persists_three_findings(self, registry, project):
        SecuritySurveyor(project, registry).run()
        findings = registry.query_security_findings("myproj")
        assert len(findings) == 3
        assert {f["check_name"] for f in findings} == {"security_policy", "ci_config", "license"}

    def test_no_artifacts_means_all_gaps(self, registry, project):
        annotations = SecuritySurveyor(project, registry).run()
        # regression guard: existing annotation-building behavior unchanged
        assert len(annotations) == 3
        assert all(isinstance(a, RequestForActionAnnotation) for a in annotations)
        findings = registry.query_security_findings("myproj")
        assert all(f["status"] == "gap" for f in findings)

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        SecuritySurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_security_findings("myproj")
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)

    def test_defaults_to_fresh_timestamp_when_not_given(self, registry, project):
        SecuritySurveyor(project, registry).run()
        findings = registry.query_security_findings("myproj")
        assert all(f["surveyed_at"] for f in findings)  # non-empty, standalone-callable


class TestDocumentationSurveyorPersistence:
    def test_persists_quality_score_finding_always(self, registry, project):
        DocumentationSurveyor(project, registry).run()
        findings = registry.query_documentation_findings("myproj")
        quality = [f for f in findings if f["finding_type"] == "quality_score"]
        assert len(quality) == 1

    def test_no_signals_yields_minimal_quality(self, registry, project):
        annotations = DocumentationSurveyor(project, registry).run()
        # regression guard: overall quality annotation always present
        assert any(isinstance(a, ClassificationAnnotation) and "Minimal" in a.summary for a in annotations)
        findings = registry.query_documentation_findings("myproj")
        assert findings[0]["label"] == "Minimal"

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        DocumentationSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_documentation_findings("myproj")
        assert findings[0]["surveyed_at"] == "2026-01-01T00:00:00"


class TestApiStructureSurveyorPersistence:
    def _seed_symbols(self, registry, slug):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_code_symbols (project_slug, file_path, language, kind, name, "
                "qualified_name, signature, docstring, start_line, end_line) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("myproj", "mod.py", "python", "function", "f", "mod.f", "def f()", "", 1, 2),
            )

    def test_no_symbols_persists_nothing(self, registry, project):
        annotations = ApiStructureSurveyor(project, registry).run()
        assert annotations == []  # regression guard: unchanged early-return
        assert registry.query_api_structure_history("myproj") == []

    def test_persists_snapshot_when_symbols_exist(self, registry, project):
        self._seed_symbols(registry, "myproj")
        annotations = ApiStructureSurveyor(project, registry).run()
        assert len(annotations) == 2  # regression guard: 1 per-language + 1 total, unchanged
        history = registry.query_api_structure_history("myproj")
        assert len(history) == 1
        assert history[0]["symbol_count"] == 1

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        self._seed_symbols(registry, "myproj")
        ApiStructureSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        history = registry.query_api_structure_history("myproj")
        assert history[0]["surveyed_at"] == "2026-01-01T00:00:00"
