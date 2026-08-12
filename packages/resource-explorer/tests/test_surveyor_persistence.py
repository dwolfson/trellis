"""Tests for Phase B's persistence calls in SecurityHygieneSurveyor
(renamed from SecuritySurveyor — analysis-kind extensibility redesign),
DocumentationSurveyor, ApiStructureSurveyor, and DataProfilerSurveyor —
each surveyor's existing annotation-building behavior must be unchanged
(regression guard); each must additionally persist correctly-shaped
findings/metrics via the generic project_analysis_findings/
project_analysis_metrics tables (all four now go through
upsert_finding()/upsert_metric(), not the deprecated per-kind tables/
functions from Phase B).
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import FileClassifierSurveyor
from resource_explorer.surveyors.sub_surveyors.api_structure import ApiStructureSurveyor
from resource_explorer.surveyors.sub_surveyors.data_profiler import DataProfilerSurveyor
from resource_explorer.surveyors.sub_surveyors.documentation import DocumentationSurveyor
from resource_explorer.surveyors.sub_surveyors.file_size import FileSizeSurveyor
from resource_explorer.surveyors.sub_surveyors.ci_quality import CiQualitySurveyor
from resource_explorer.surveyors.sub_surveyors.license_classifier import LicenseClassifierSurveyor
from resource_explorer.surveyors.sub_surveyors.security_features import SecurityFeaturesSurveyor
from resource_explorer.surveyors.sub_surveyors.security_hygiene import SecurityHygieneSurveyor
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
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


class TestSecurityHygieneSurveyorPersistence:
    def test_persists_three_findings(self, registry, project):
        SecurityHygieneSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "security_hygiene")
        assert len(findings) == 3
        assert {f["check_name"] for f in findings} == {"security_policy", "ci_config", "license"}

    def test_no_artifacts_means_all_gaps(self, registry, project):
        annotations = SecurityHygieneSurveyor(project, registry).run()
        # regression guard: existing annotation-building behavior unchanged
        assert len(annotations) == 3
        assert all(isinstance(a, RequestForActionAnnotation) for a in annotations)
        findings = registry.query_findings("myproj", "security_hygiene")
        assert all(f["label"] == "gap" for f in findings)  # "status" (pass/gap) -> generic "label"

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        SecurityHygieneSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_findings("myproj", "security_hygiene")
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)

    def test_defaults_to_fresh_timestamp_when_not_given(self, registry, project):
        SecurityHygieneSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "security_hygiene")
        assert all(f["surveyed_at"] for f in findings)  # non-empty, standalone-callable


class TestDocumentationSurveyorPersistence:
    def test_persists_quality_score_finding_always(self, registry, project):
        DocumentationSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "documentation")
        quality = [f for f in findings if f["check_name"] == "quality_score"]
        assert len(quality) == 1

    def test_no_signals_yields_minimal_quality(self, registry, project):
        annotations = DocumentationSurveyor(project, registry).run()
        # regression guard: overall quality annotation always present
        assert any(isinstance(a, ClassificationAnnotation) and "Minimal" in a.summary for a in annotations)
        findings = registry.query_findings("myproj", "documentation")
        quality = next(f for f in findings if f["check_name"] == "quality_score")
        assert quality["label"] == "Minimal"

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        DocumentationSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_findings("myproj", "documentation")
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)

    def _seed_inventory(self, registry, slug, *paths):
        with registry._conn() as conn:
            for p in paths:
                conn.execute(
                    "INSERT INTO project_file_inventory (project_slug, file_path, indexed_at) "
                    "VALUES (?, ?, ?)",
                    (slug, p, "2026-01-01T00:00:00"),
                )

    def test_hygiene_files_detected_from_file_inventory_not_code_symbols(self, registry, project):
        # Regression guard for the B3 bug fix — README/CHANGELOG/etc never
        # get project_code_symbols rows (only .py/.js/.java/.go do), so this
        # must read project_file_inventory instead.
        self._seed_inventory(registry, "myproj", "README.md", "CHANGELOG.md")
        annotations = DocumentationSurveyor(project, registry).run()
        hygiene = next(
            (a for a in annotations if "Hygiene files found" in a.summary), None,
        )
        assert hygiene is not None
        assert set(hygiene.candidate_classifications) == {"README", "Changelog"}

    def test_codeowners_detected_at_root(self, registry, project):
        self._seed_inventory(registry, "myproj", "CODEOWNERS")
        annotations = DocumentationSurveyor(project, registry).run()
        hygiene = next(a for a in annotations if "Hygiene files found" in a.summary)
        assert "Code owners" in hygiene.candidate_classifications

    def test_codeowners_detected_in_github_dir(self, registry, project):
        self._seed_inventory(registry, "myproj", ".github/CODEOWNERS")
        annotations = DocumentationSurveyor(project, registry).run()
        hygiene = next(a for a in annotations if "Hygiene files found" in a.summary)
        assert "Code owners" in hygiene.candidate_classifications

    def test_codeowners_not_recognized_outside_canonical_locations(self, registry, project):
        # e.g. a nested "src/CODEOWNERS" isn't one of GitHub's 3 recognized
        # locations — must not be reported as present.
        self._seed_inventory(registry, "myproj", "src/CODEOWNERS")
        annotations = DocumentationSurveyor(project, registry).run()
        hygiene = next((a for a in annotations if "Hygiene files found" in a.summary), None)
        assert hygiene is None


class TestLicenseClassifierSurveyorPersistence:
    def _seed_stats(self, registry, slug, license_name="", spdx_id=""):
        # Raw INSERT (mirrors TestApiStructureSurveyorPersistence._seed_symbols
        # below) — no generic project_stats writer exists outside StatsFetcher
        # itself, which needs a live GitHub call.
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_stats (project_slug, fetched_at, license, license_spdx_id) "
                "VALUES (?, ?, ?, ?)",
                (slug, "2026-01-01T00:00:00", license_name, spdx_id),
            )

    def test_no_license_detected(self, registry, project):
        annotations = LicenseClassifierSurveyor(project, registry).run()
        assert len(annotations) == 1
        assert annotations[0].candidate_classifications == ["none"]
        findings = registry.query_findings("myproj", "license_classification")
        assert len(findings) == 1
        assert findings[0]["label"] == "none"

    def test_permissive_license_classified(self, registry, project):
        self._seed_stats(registry, "myproj", "MIT License", "MIT")
        annotations = LicenseClassifierSurveyor(project, registry).run()
        assert annotations[0].candidate_classifications == ["permissive"]
        findings = registry.query_findings("myproj", "license_classification")
        assert findings[0]["label"] == "permissive"

    def test_strong_copyleft_license_classified(self, registry, project):
        self._seed_stats(registry, "myproj", "GNU General Public License v3.0", "GPL-3.0")
        annotations = LicenseClassifierSurveyor(project, registry).run()
        assert annotations[0].candidate_classifications == ["strong_copyleft"]

    def test_source_available_license_not_confused_with_boost(self, registry, project):
        # BUSL-1.1 (Business Source License) vs BSL-1.0 (Boost Software
        # License, permissive) — the exact naming-collision risk the
        # surveyor's own docstring calls out.
        self._seed_stats(registry, "myproj", "Business Source License 1.1", "BUSL-1.1")
        annotations = LicenseClassifierSurveyor(project, registry).run()
        assert annotations[0].candidate_classifications == ["source_available"]

    def test_unrecognized_spdx_id_is_unknown_not_permissive(self, registry, project):
        self._seed_stats(registry, "myproj", "Some Custom License", "LicenseRef-custom")
        annotations = LicenseClassifierSurveyor(project, registry).run()
        assert annotations[0].candidate_classifications == ["unknown"]

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        self._seed_stats(registry, "myproj", "MIT License", "MIT")
        LicenseClassifierSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_findings("myproj", "license_classification")
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)


class TestSecurityFeaturesSurveyorPersistence:
    def _seed_stats(self, registry, slug, features_json):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_stats (project_slug, fetched_at, security_and_analysis_json) "
                "VALUES (?, ?, ?)",
                (slug, "2026-01-01T00:00:00", features_json),
            )

    def test_no_stats_row_yields_no_findings(self, registry, project):
        annotations = SecurityFeaturesSurveyor(project, registry).run()
        assert annotations == []
        assert registry.query_findings("myproj", "security_features") == []

    def test_none_status_features_are_skipped_not_gaps(self, registry, project):
        # All 7 features unavailable (None) — GitHub never exposed the data
        # for this repo (no admin access) — none should be reported as gaps.
        self._seed_stats(registry, "myproj", '{"advanced_security": null, "secret_scanning": null}')
        annotations = SecurityFeaturesSurveyor(project, registry).run()
        assert annotations == []
        assert registry.query_findings("myproj", "security_features") == []

    def test_enabled_and_disabled_features_classified(self, registry, project):
        self._seed_stats(
            registry, "myproj",
            '{"advanced_security": "enabled", "secret_scanning": "disabled", "dependabot_security_updates": null}',
        )
        annotations = SecurityFeaturesSurveyor(project, registry).run()
        assert len(annotations) == 2  # the null one is skipped
        findings = registry.query_findings("myproj", "security_features")
        assert len(findings) == 2
        by_check = {f["check_name"]: f["label"] for f in findings}
        assert by_check["advanced_security"] == "pass"
        assert by_check["secret_scanning"] == "gap"
        assert "dependabot_security_updates" not in by_check

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        self._seed_stats(registry, "myproj", '{"advanced_security": "enabled"}')
        SecurityFeaturesSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        findings = registry.query_findings("myproj", "security_features")
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)


class TestCiQualitySurveyorPersistence:
    """CiQualitySurveyor is read-only at survey time (same relationship
    DependencySurveyor has with project_dependencies) — it just re-emits
    whatever IngestionPipeline._parse_ci_workflows() last wrote."""

    def test_no_findings_yields_no_annotations(self, registry, project):
        assert CiQualitySurveyor(project, registry).run() == []

    def test_reemits_persisted_findings_as_annotations(self, registry, project):
        registry.upsert_finding(
            "myproj", "ci_quality",
            [
                {"check_name": "ci_runs_tests", "label": "pass", "summary": "CI runs tests", "confidence": 80},
                {"check_name": "ci_runs_lint", "label": "gap", "summary": "CI does not run lint", "confidence": 80},
            ],
            surveyed_at="2026-01-01T00:00:00",
        )
        annotations = CiQualitySurveyor(project, registry).run()
        assert len(annotations) == 2
        labels = {a.json_properties["check_name"]: a.candidate_classifications[0] for a in annotations}
        assert labels == {"ci_runs_tests": "pass", "ci_runs_lint": "gap"}

    def test_does_not_write_new_findings(self, registry, project):
        # Regression guard: this surveyor must never call upsert_finding
        # itself — re-parsing/re-persisting is IngestionPipeline's job.
        registry.upsert_finding(
            "myproj", "ci_quality",
            [{"check_name": "ci_runs_tests", "label": "pass", "summary": "x", "confidence": 80}],
            surveyed_at="2026-01-01T00:00:00",
        )
        CiQualitySurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "ci_quality")
        assert len(findings) == 1
        assert all(f["surveyed_at"] == "2026-01-01T00:00:00" for f in findings)


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
        assert registry.query_metrics("myproj", "api_structure") == {}

    def test_persists_snapshot_when_symbols_exist(self, registry, project):
        self._seed_symbols(registry, "myproj")
        annotations = ApiStructureSurveyor(project, registry).run()
        assert len(annotations) == 2  # regression guard: 1 per-language + 1 total, unchanged
        metrics = registry.query_metrics("myproj", "api_structure")
        assert metrics["symbol_count"] == 1
        history = registry.query_metrics_history("myproj", "api_structure", "symbol_count")
        assert len(history) == 1

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        self._seed_symbols(registry, "myproj")
        ApiStructureSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        metrics = registry.query_metrics("myproj", "api_structure")
        assert metrics["surveyed_at"] == "2026-01-01T00:00:00"

    def test_scope_locator_filters_symbols_and_persists_scoped(self, registry, project):
        # D5/D6 repo scope-narrowing funnel plan — scoping.py-based path filter.
        self._seed_symbols(registry, "myproj")
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_code_symbols (project_slug, file_path, language, kind, name, "
                "qualified_name, signature, docstring, start_line, end_line) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("myproj", "other/mod2.py", "python", "function", "g", "mod2.g", "def g()", "", 1, 2),
            )
        annotations = ApiStructureSurveyor(project, registry, scope_locator="mod.py").run()
        assert len(annotations) == 2
        metrics = registry.query_metrics("myproj", "api_structure", scope_locator="mod.py")
        assert metrics["symbol_count"] == 1  # only mod.py's symbol, not other/mod2.py's
        # Whole-resource metrics (default scope_locator="") stay untouched/absent.
        assert registry.query_metrics("myproj", "api_structure") == {}


class TestDataProfilerSurveyorPersistence:
    def _seed_inventory(self, registry, slug):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (slug, "data/sample.csv", 1234, "2026-01-01T00:00:00"),
            )

    def test_no_inventory_persists_nothing(self, registry, project):
        DataProfilerSurveyor(project, registry).run()
        assert registry.query_metrics("myproj", "data_profile") == {}

    def test_persists_snapshot_when_data_files_exist(self, registry, project):
        self._seed_inventory(registry, "myproj")
        annotations = DataProfilerSurveyor(project, registry).run()
        assert len(annotations) >= 1  # regression guard: Tier 1 summary always emitted
        metrics = registry.query_metrics("myproj", "data_profile")
        assert metrics["total_files"] == 1
        assert metrics["total_size_bytes"] == 1234
        history = registry.query_metrics_history("myproj", "data_profile", "total_files")
        assert len(history) == 1

    def test_shared_surveyed_at_threaded_through(self, registry, project):
        self._seed_inventory(registry, "myproj")
        DataProfilerSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        metrics = registry.query_metrics("myproj", "data_profile")
        assert metrics["surveyed_at"] == "2026-01-01T00:00:00"

    def test_scope_locator_filters_data_files_and_persists_scoped(self, registry, project):
        self._seed_inventory(registry, "myproj")
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                ("myproj", "other/sample2.csv", 999, "2026-01-01T00:00:00"),
            )
        annotations = DataProfilerSurveyor(project, registry, scope_locator="data").run()
        assert len(annotations) >= 1
        metrics = registry.query_metrics("myproj", "data_profile", scope_locator="data")
        assert metrics["total_files"] == 1
        assert metrics["total_size_bytes"] == 1234
        assert registry.query_metrics("myproj", "data_profile") == {}


class TestFileSizeSurveyorScoping:
    """FileSizeSurveyor has no catalog entry (never independently persisted a
    metric snapshot — findings-only) but is mechanically corpus-shaped per
    the target-shape audit; D5/D6 repo scope-narrowing funnel plan."""

    def _seed_inventory(self, registry, slug):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (slug, "src/big.bin", 2_000_000, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (slug, "other/small.bin", 100, "2026-01-01T00:00:00"),
            )

    def test_default_scope_sees_all_files(self, registry, project):
        self._seed_inventory(registry, "myproj")
        annotations = FileSizeSurveyor(project, registry).run()
        measures = [a for a in annotations if isinstance(a, ResourceMeasureAnnotation)]
        assert measures[0].resource_properties["total_files"] == 2

    def test_scope_locator_filters_to_matching_files_only(self, registry, project):
        self._seed_inventory(registry, "myproj")
        annotations = FileSizeSurveyor(project, registry, scope_locator="src").run()
        measures = [a for a in annotations if isinstance(a, ResourceMeasureAnnotation)]
        assert measures[0].resource_properties["total_files"] == 1
        assert measures[0].resource_properties["total_size_bytes"] == 2_000_000


class TestFileClassifierSurveyorScoping:
    """D5/D6 repo scope-narrowing funnel plan — repo_file_classification is
    mechanically corpus-shaped (classify_file_paths() is already
    path-agnostic), even though its bundling catalog id
    (language_file_classification) is gated whole_resource_only for the UI
    (D6) since a sibling bundled step's output can't be scoped. The trend
    write (upsert_file_type_counts) must be skipped for a scoped run."""

    def _seed_inventory(self, registry, slug):
        with registry._conn() as conn:
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (slug, "src/mod.py", 100, "2026-01-01T00:00:00"),
            )
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, file_size_bytes, indexed_at) "
                "VALUES (?, ?, ?, ?)",
                (slug, "other/mod2.py", 100, "2026-01-01T00:00:00"),
            )

    def test_default_scope_persists_trend_row(self, registry, project):
        self._seed_inventory(registry, "myproj")
        FileClassifierSurveyor(project, registry).run()
        assert registry.query_file_type_counts("myproj") != []

    def test_scope_locator_filters_paths_and_skips_trend_write(self, registry, project):
        self._seed_inventory(registry, "myproj")
        annotations = FileClassifierSurveyor(project, registry, scope_locator="src").run()
        assert annotations  # still produces classification annotations for the scoped subset
        measures = [a for a in annotations if isinstance(a, ResourceMeasureAnnotation)]
        assert measures[0].json_properties["total_files"] == 1
        # Scoped runs must not pollute the whole-repo file-type-count trend.
        assert registry.query_file_type_counts("myproj") == []
