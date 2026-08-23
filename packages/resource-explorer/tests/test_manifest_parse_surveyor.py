"""Tests for ManifestParseSurveyor — the survey step that refreshes
project_dependencies and project_analysis_findings (kind="ci_quality"/
"repo_conventions") from a freshly extracted zipball.

Exists because those three tables were written only by IngestionPipeline (and,
for the latter two, refresh_profile()), never by a survey step — the same trap
project_file_inventory and project_code_symbols were in before
repo_file_inventory/repo_symbol_extraction closed it. The org-import/discovery
path deliberately skips ingestion, so for most resources these tables were
simply empty and every reader of them (DependencySurveyor, CiQualitySurveyor,
RepoConventionsSurveyor) reported a confident nothing forever.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.step_outcome import NO_SIGNAL, RECOVERED, UNVERIFIED
from resource_explorer.surveyors.sub_surveyors.manifest_parse import (
    STEP,
    ManifestParseSurveyor,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="myproj", display_name="My Project",
                github_url="https://github.com/test/myproj", collections=[])
    registry.add(p)
    return p


def _outcome_of(annotation) -> str:
    return annotation.json_properties.get("outcome", "")


def _by_summary_fragment(annotations, fragment):
    matches = [a for a in annotations if fragment in a.summary.lower()]
    assert len(matches) == 1, f"expected exactly one match for {fragment!r}, got {[a.summary for a in annotations]}"
    return matches[0]


def _write_manifest_repo(root):
    """A repo with a Python dependency manifest, a CI workflow that runs
    tests, and enough README/docs to pass repo_conventions' doc_breadth
    check — exercises all three sub-parses' "recovered" path at once."""
    (root / "pyproject.toml").write_text(
        '[project]\nname = "x"\ndependencies = ["requests>=2.0", "click"]\n'
    )
    (root / "README.md").write_text("# My Project\n\nSome docs.\n")
    workflows = root / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text("run: pytest tests/\n")
    (root / "SECURITY.md").write_text("## Reporting a vulnerability\nEmail security@example.com\n")
    (root / "Dockerfile").write_text("FROM python:3.12\n")
    return root


class TestAllThreeTablesWrittenFromOneRoot:
    """The three sub-parses each write into a different table from one shared
    extraction root — the core of what this step exists to do."""

    def test_dependencies_ci_and_conventions_all_persisted(self, tmp_path, registry, project):
        _write_manifest_repo(tmp_path)
        anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        assert len(anns) == 3
        assert all(a.analysis_step == STEP for a in anns)

        deps = registry.query_dependencies(project.slug)
        assert {d["dep_name"] for d in deps} == {"requests", "click"}

        ci_findings = registry.query_findings(project.slug, "ci_quality")
        assert any(f["check_name"] == "ci_runs_tests" and f["label"] == "pass" for f in ci_findings)

        conv_findings = registry.query_findings(project.slug, "repo_conventions")
        check_names = {f["check_name"] for f in conv_findings}
        assert check_names == {
            "security_policy_content", "automated_build", "deployment_docker",
            "catalog_info", "doc_breadth",
        }

    def test_shared_surveyed_at_threaded_through_every_write(self, tmp_path, registry, project):
        _write_manifest_repo(tmp_path)
        ManifestParseSurveyor(
            project, registry, local_path=str(tmp_path), surveyed_at="2026-08-23T00:00:00",
        ).run()

        deps = registry.query_dependencies(project.slug)
        assert deps  # upsert_dependencies stamped its own shared indexed_at internally

        ci_findings_raw = registry.query_findings_history_raw(project.slug, "ci_quality")
        assert all(f["surveyed_at"] == "2026-08-23T00:00:00" for f in ci_findings_raw)

        conv_findings_raw = registry.query_findings_history_raw(project.slug, "repo_conventions")
        assert all(f["surveyed_at"] == "2026-08-23T00:00:00" for f in conv_findings_raw)


class TestPerItemIsolation:
    """One sub-parse raising must not prevent the other two from writing —
    a hard rule in this codebase (see dependency.py's own precedent)."""

    def test_dependency_parser_raising_still_writes_ci_and_conventions(self, tmp_path, registry, project):
        _write_manifest_repo(tmp_path)
        with patch(
            "resource_explorer.ingestion.dependency_parser.DependencyParser.parse",
            side_effect=RuntimeError("boom"),
        ):
            anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        assert len(anns) == 3
        dep_ann = _by_summary_fragment(anns, "dependency parse failed")
        assert dep_ann.confidence == 0
        assert "boom" in dep_ann.explanation

        # The other two still wrote their tables.
        assert registry.query_findings(project.slug, "ci_quality")
        assert registry.query_findings(project.slug, "repo_conventions")
        assert not registry.query_dependencies(project.slug)

    def test_ci_workflow_parser_raising_still_writes_dependencies_and_conventions(
        self, tmp_path, registry, project
    ):
        _write_manifest_repo(tmp_path)
        with patch(
            "resource_explorer.ingestion.ci_workflow_parser.CiWorkflowParser.parse",
            side_effect=RuntimeError("kaboom"),
        ):
            anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        assert len(anns) == 3
        ci_ann = _by_summary_fragment(anns, "ci workflow parse failed")
        assert ci_ann.confidence == 0

        assert registry.query_dependencies(project.slug)
        assert registry.query_findings(project.slug, "repo_conventions")
        assert not registry.query_findings(project.slug, "ci_quality")

    def test_repo_conventions_parser_raising_still_writes_dependencies_and_ci(
        self, tmp_path, registry, project
    ):
        _write_manifest_repo(tmp_path)
        with patch(
            "resource_explorer.ingestion.repo_conventions_parser.RepoConventionsParser.parse",
            side_effect=RuntimeError("splat"),
        ):
            anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        assert len(anns) == 3
        conv_ann = _by_summary_fragment(anns, "repo conventions parse failed")
        assert conv_ann.confidence == 0

        assert registry.query_dependencies(project.slug)
        assert registry.query_findings(project.slug, "ci_quality")
        assert not registry.query_findings(project.slug, "repo_conventions")


class TestZerosAreRecordedNotDropped:
    """The pipeline writers guard with `if deps:`/`if findings:`, so a
    legitimate zero writes nothing and is indistinguishable from never having
    run. This step must record the zero instead."""

    def test_no_manifest_in_tree_is_a_provable_no_signal(self, tmp_path, registry, project):
        """No manifest anywhere in the extracted tree: the whole tree was
        walked (that walk IS the known-positive check), so "no dependencies"
        is the real, provable answer."""
        (tmp_path / "README.md").write_text("hello")
        anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        dep_ann = _by_summary_fragment(anns, "no dependency manifest found")
        assert not registry.query_dependencies(project.slug)
        assert _outcome_of(dep_ann) == NO_SIGNAL
        assert dep_ann.json_properties["outcome_known_positive"] is True

    def test_manifest_present_but_zero_deps_parsed_is_unverified(self, tmp_path, registry, project):
        """A manifest is right there (the known-positive fired) and nothing
        was parsed from it — a parser gap, not a repo with no dependencies.
        Must not be claimed as no_signal."""
        # An empty dependencies list is a legitimate pyproject.toml the
        # parser can read but that declares nothing under [project.dependencies].
        (tmp_path / "pyproject.toml").write_text('[project]\nname = "x"\n')
        anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        dep_ann = _by_summary_fragment(anns, "no dependencies parsed despite")
        assert not registry.query_dependencies(project.slug)
        assert _outcome_of(dep_ann) == UNVERIFIED
        assert dep_ann.json_properties["outcome_cause"] == "manifest_present_no_deps_parsed"

    def test_no_github_workflows_is_unverified_not_no_signal(self, tmp_path, registry, project):
        """CiWorkflowParser only ever looks at .github/workflows — a repo
        using Travis/CircleCI/Jenkins reads identically to one with no CI at
        all, so there is no known-positive available. Per step_outcome's
        rule this must be unverified, never no_signal."""
        (tmp_path / "README.md").write_text("hello")
        anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        ci_ann = _by_summary_fragment(anns, "no .github/workflows content")
        assert not registry.query_findings(project.slug, "ci_quality")
        assert _outcome_of(ci_ann) == UNVERIFIED
        assert ci_ann.json_properties["outcome_known_positive"] is False

    def test_repo_conventions_zero_findings_is_unverified(self, tmp_path, registry, project):
        """RepoConventionsParser's own contract is that it returns 5 findings
        unless the tree has zero files — there is no known-positive that
        would make an empty result provable rather than suspicious."""
        with patch(
            "resource_explorer.ingestion.repo_conventions_parser.RepoConventionsParser.parse",
            return_value=[],
        ):
            anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()

        conv_ann = _by_summary_fragment(anns, "no repo convention signals produced")
        assert not registry.query_findings(project.slug, "repo_conventions")
        assert _outcome_of(conv_ann) == UNVERIFIED

    def test_recovered_dependency_outcome_when_deps_found(self, tmp_path, registry, project):
        _write_manifest_repo(tmp_path)
        anns = ManifestParseSurveyor(project, registry, local_path=str(tmp_path)).run()
        dep_ann = _by_summary_fragment(anns, "dependency(s) parsed from")
        assert _outcome_of(dep_ann) == RECOVERED

    def test_recovered_metrics_snapshot_is_queryable(self, tmp_path, registry, project):
        """upsert_metric snapshots ("manifest_parse_dependencies" etc.) are
        what backs the analysis card's Results view — confirm they persist
        independently of the underlying tables."""
        _write_manifest_repo(tmp_path)
        ManifestParseSurveyor(
            project, registry, local_path=str(tmp_path), surveyed_at="2026-08-23T01:00:00",
        ).run()

        deps_metric = registry.query_metrics(project.slug, "manifest_parse_dependencies")
        assert deps_metric["count"] == 2
        assert deps_metric["detail"]["outcome"] == RECOVERED

        ci_metric = registry.query_metrics(project.slug, "manifest_parse_ci_quality")
        assert ci_metric["count"] == 3  # ci_runs_tests, ci_runs_lint, ci_runs_build

        conv_metric = registry.query_metrics(project.slug, "manifest_parse_conventions")
        assert conv_metric["count"] == 5
