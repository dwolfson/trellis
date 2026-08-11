"""Tests for SubResourceSurveyor — the survey half of the Assessment
sub-resource cataloging plan (docs/assessment-sub-resource-cataloging.md).
Covers D1's worthiness heuristics, D9's tiered metadata capture (CODEOWNERS
free/whole-repo, Tier-2 commit dates worthy-subset-only), and D10/D11's
size/mode distribution metrics."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.sub_resource_survey import SubResourceSurveyor


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


def _seed_inventory(registry, slug, paths_with_sizes, modes_by_path=None):
    registry.upsert_file_inventory(slug, paths_with_sizes, modes_by_path=modes_by_path)


def _no_codeowners_no_commits():
    """Patch target used by every test that doesn't care about
    CODEOWNERS/Tier-2 — a GitHubClient whose get_file_content always
    returns None (no CODEOWNERS found) and whose get_commits always
    returns an empty PaginatedList-alike."""
    client = MagicMock()
    client.get_file_content.return_value = None
    commits = MagicMock()
    commits.totalCount = 0
    client.get_repo.return_value.get_commits.return_value = commits
    return patch(
        "resource_explorer.github.client.GitHubClient", return_value=client
    )


class TestNoInventory:
    def test_empty_inventory_produces_a_single_low_confidence_annotation(self, registry, project):
        results = SubResourceSurveyor(project, registry).run()
        assert len(results) == 1
        assert "No file inventory" in results[0].summary
        assert results[0].confidence == 50


class TestWellKnownFileHeuristic:
    def test_readme_at_root_is_worthy(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        readme = next(f for f in findings if f["check_name"] == "README.md")
        assert readme["label"] == "worthy"

    def test_security_md_nested_within_max_depth_is_worthy(self, registry, project):
        _seed_inventory(registry, "myproj", [("docs/SECURITY.md", 10)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry, max_depth=2).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        sec = next(f for f in findings if f["check_name"] == "docs/SECURITY.md")
        assert sec["label"] == "worthy"

    def test_well_known_file_beyond_max_depth_is_not_considered_at_all(self, registry, project):
        _seed_inventory(registry, "myproj", [("a/b/c/LICENSE", 10)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry, max_depth=2).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        assert not any(f["check_name"] == "a/b/c/LICENSE" for f in findings)

    def test_non_well_known_file_never_appears_as_its_own_entry(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10), ("random.py", 5)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        assert not any(f["check_name"] == "random.py" for f in findings)


class TestFolderWorthinessHeuristic:
    def _seed_folder(self, registry, slug, folder, file_count):
        paths = [(f"{folder}/f{i}.py", 10) for i in range(file_count)]
        _seed_inventory(registry, slug, paths)

    def test_folder_with_one_file_is_too_small(self, registry, project):
        self._seed_folder(registry, "myproj", "src", 1)
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        src = next(f for f in findings if f["check_name"] == "src")
        assert src["label"] == "not_worthy"
        assert src["summary"] == "too_small"

    def test_folder_with_two_files_is_worthy_lower_boundary(self, registry, project):
        self._seed_folder(registry, "myproj", "src", 2)
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        src = next(f for f in findings if f["check_name"] == "src")
        assert src["label"] == "worthy"
        assert src["summary"] == "top_level_structural_folder"

    def test_folder_with_200_files_is_worthy_upper_boundary(self, registry, project):
        self._seed_folder(registry, "myproj", "src", 200)
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        src = next(f for f in findings if f["check_name"] == "src")
        assert src["label"] == "worthy"

    def test_folder_with_201_files_is_too_broad(self, registry, project):
        self._seed_folder(registry, "myproj", "src", 201)
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        src = next(f for f in findings if f["check_name"] == "src")
        assert src["label"] == "not_worthy"
        assert src["summary"] == "too_broad"

    def test_not_worthy_folders_are_still_listed_not_omitted(self, registry, project):
        """The finding must show 'considered N, recommended M' — not-worthy
        folders stay in the list with a reason, not silently dropped."""
        self._seed_folder(registry, "myproj", "node_modules", 500)
        with _no_codeowners_no_commits():
            results = SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        assert any(f["check_name"] == "node_modules" and f["label"] == "not_worthy" for f in findings)
        assert "1 considered, 0 recommended" in results[0].summary


class TestSyntheticRootFolderRule:
    def test_root_folder_added_when_root_file_is_worthy(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        root = next(f for f in findings if f["check_name"] == "(root)")
        assert root["label"] == "worthy"

    def test_no_synthetic_root_when_no_root_file_is_worthy(self, registry, project):
        _seed_inventory(registry, "myproj", [("src/main.py", 10), ("src/util.py", 5)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        assert not any(f["check_name"] == "(root)" for f in findings)

    def test_nested_well_known_file_does_not_trigger_synthetic_root(self, registry, project):
        """Only a *root-level* worthy file needs the synthetic root — a
        nested one already has a real containing folder candidate."""
        _seed_inventory(registry, "myproj", [("docs/SECURITY.md", 10)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry, max_depth=2).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        assert not any(f["check_name"] == "(root)" for f in findings)


class TestCodeowners:
    def test_owners_attached_when_codeowners_present(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        client = MagicMock()
        client.get_file_content.return_value = "README.md @docs-team\n"
        commits = MagicMock(totalCount=0)
        client.get_repo.return_value.get_commits.return_value = commits
        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        readme = next(f for f in findings if f["check_name"] == "README.md")
        import json
        detail = json.loads(readme["detail_json"]) if readme.get("detail_json") else {}
        assert detail.get("owners") == ["@docs-team"]

    def test_no_codeowners_file_yields_empty_owners_not_an_error(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        with _no_codeowners_no_commits():
            results = SubResourceSurveyor(project, registry).run()
        # Ran to completion (no _warn RFA-style failure annotation).
        assert len(results) == 1
        assert "considered" in results[0].summary

    def test_last_matching_codeowners_rule_wins(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        client = MagicMock()
        client.get_file_content.return_value = "* @default-owner\nREADME.md @docs-team\n"
        commits = MagicMock(totalCount=0)
        client.get_repo.return_value.get_commits.return_value = commits
        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        readme = next(f for f in findings if f["check_name"] == "README.md")
        import json
        detail = json.loads(readme["detail_json"])
        assert detail["owners"] == ["@docs-team"]


class TestTier2CostBoundary:
    """Regression guard on D9's cost-boundary claim: Tier-2 commit-date
    fetching must be called only for the worthy subset, never the full
    inventory."""

    def test_get_commits_called_only_for_worthy_entries(self, registry, project):
        _seed_inventory(
            registry, "myproj",
            [("README.md", 10)] + [(f"junk/f{i}.txt", 1) for i in range(300)],
        )
        client = MagicMock()
        client.get_file_content.return_value = None
        commits = MagicMock(totalCount=1)
        commits.__getitem__ = MagicMock(return_value=MagicMock(
            commit=MagicMock(author=MagicMock(date=MagicMock(isoformat=lambda: "2026-01-01T00:00:00")))
        ))
        client.get_repo.return_value.get_commits.return_value = commits
        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            SubResourceSurveyor(project, registry).run()

        # "junk" folder has 300 files -> too_broad -> not worthy -> no
        # get_commits call for it. Only README.md (worthy) + the synthetic
        # root (path="" -> skipped, no get_commits since path is falsy).
        calls = client.get_repo.return_value.get_commits.call_args_list
        paths_queried = [c.kwargs.get("path") for c in calls]
        assert paths_queried == ["README.md"]

    def test_last_updated_and_first_added_populated_for_worthy_entry(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        client = MagicMock()
        client.get_file_content.return_value = None
        first_commit = MagicMock(commit=MagicMock(author=MagicMock(
            date=MagicMock(isoformat=lambda: "2025-01-01T00:00:00"))))
        last_commit = MagicMock(commit=MagicMock(author=MagicMock(
            date=MagicMock(isoformat=lambda: "2026-01-01T00:00:00"))))
        commits = MagicMock(totalCount=2)
        commits.__getitem__ = MagicMock(side_effect=lambda i: {0: last_commit, 1: first_commit}[i])
        client.get_repo.return_value.get_commits.return_value = commits
        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            SubResourceSurveyor(project, registry).run()
        findings = registry.query_findings("myproj", "repo_sub_resource_survey")
        readme = next(f for f in findings if f["check_name"] == "README.md")
        import json
        detail = json.loads(readme["detail_json"])
        assert detail["last_updated_at"] == "2026-01-01T00:00:00"
        assert detail["first_added_at"] == "2025-01-01T00:00:00"

    def test_tier2_failure_is_best_effort_not_fatal(self, registry, project):
        _seed_inventory(registry, "myproj", [("README.md", 10)])
        client = MagicMock()
        client.get_file_content.return_value = None
        client.get_repo.return_value.get_commits.side_effect = Exception("rate limited")
        with patch("resource_explorer.github.client.GitHubClient", return_value=client):
            results = SubResourceSurveyor(project, registry).run()
        assert len(results) == 1
        assert "considered" in results[0].summary


class TestSizeAndModeDistributions:
    def test_size_and_mode_metrics_persisted(self, registry, project):
        _seed_inventory(
            registry, "myproj",
            [("a.py", 500), ("b.py", 2_000)],
            modes_by_path={"a.py": "100644", "b.py": "100755"},
        )
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry).run()
        metrics = registry.query_metrics("myproj", "repo_sub_resource_survey")
        assert metrics["total_size_bytes"] == 2_500
        assert metrics["file_count"] == 2
        assert metrics["mode_regular_count"] == 1
        assert metrics["mode_executable_count"] == 1
        assert metrics["detail"]["size_buckets"]["<1KB"] == 1
        assert metrics["detail"]["size_buckets"]["1KB-10KB"] == 1
        assert metrics["detail"]["mode_counts"]["regular"] == 1
        assert metrics["detail"]["mode_counts"]["executable"] == 1

    def test_repeated_runs_append_not_overwrite(self, registry, project):
        """D11 growth-over-time regression guard."""
        _seed_inventory(registry, "myproj", [("a.py", 100)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry, surveyed_at="2026-01-01T00:00:00").run()
        _seed_inventory(registry, "myproj", [("a.py", 100), ("b.py", 200)])
        with _no_codeowners_no_commits():
            SubResourceSurveyor(project, registry, surveyed_at="2026-02-01T00:00:00").run()

        history = registry.query_metrics_history("myproj", "repo_sub_resource_survey", "total_size_bytes")
        assert [h["surveyed_at"] for h in history] == ["2026-01-01T00:00:00", "2026-02-01T00:00:00"]
        assert [h["metric_value"] for h in history] == [100, 300]
