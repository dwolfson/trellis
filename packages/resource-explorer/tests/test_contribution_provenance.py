"""Tests for ContributionProvenanceSurveyor — repo_contribution_provenance
(docs/gap-analyses-design.md §3). Not registered (task scope boundary) —
invoked directly here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.contribution_provenance import (
    FINDING_KIND,
    ContributionProvenanceSurveyor,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="myrepo", display_name="My Repo",
                github_url="https://github.com/test/myrepo", collections=[])
    registry.add(p)
    return p


def _write_inventory(registry, slug, root: Path, files: dict[str, str]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    paths = []
    for rel, content in files.items():
        full = root / rel
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(content)
        paths.append((rel, len(content)))
    registry.upsert_file_inventory(slug, paths)


def _finding(registry, slug, check_name):
    rows = registry.query_findings(slug, FINDING_KIND)
    matches = [r for r in rows if r["check_name"] == check_name]
    for r in matches:
        r["detail"] = json.loads(r["detail_json"]) if r.get("detail_json") else {}
    return matches


class TestStatedCheck:
    def test_empty_inventory_is_unverified(self, tmp_path, registry, project):
        root = tmp_path / "root"
        root.mkdir()
        anns = ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        assert any(a.json_properties.get("outcome_cause") == "empty_file_inventory"
                   for a in anns)

    def test_no_contributing_doc_is_no_signal_stated(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_stated")
        assert rows[0]["label"] == "no_signal"
        assert rows[0]["detail"]["outcome_known_positive"] is True

    def test_filename_present_but_no_keyword_is_no_signal_KNOWN_NEGATIVE(
        self, tmp_path, registry, project
    ):
        """Known-negative for the exact SecurityHygieneSurveyor shallowness
        this analysis exists to not repeat: filename presence alone must
        NOT be read as 'stated'."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "Please run the tests and open a PR. Thanks!\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_stated")
        assert rows[0]["label"] == "no_signal"

    def test_dco_keyword_present_is_recovered(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "We require the Developer Certificate of Origin (DCO).\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_stated")
        assert rows[0]["label"] == "recovered"


class TestEnforcedCheck:
    def test_no_config_found_is_unknown_not_gap(self, tmp_path, registry, project):
        """This is the honest limitation named in the module docstring:
        branch-protection data is not fetched anywhere in this codebase, so
        'no config found by filename' can never become a confirmed 'gap' —
        it is 'unknown'."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "We use DCO.\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_enforced")
        assert rows[0]["label"] == "unknown"

    def test_bot_config_present_is_partial_not_pass_KNOWN_NEGATIVE(
        self, tmp_path, registry, project
    ):
        """Known-negative for design §3's explicit rule: a config file's
        mere presence must be 'partial', never 'pass' — this asserts the
        weaker label, not the stronger one a naive implementation might
        default to."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "We use DCO.\n",
            ".clabot": "{}\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_enforced")
        assert rows[0]["label"] == "partial"
        assert rows[0]["label"] != "pass"

    def test_dco_workflow_present_is_partial(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "We use DCO.\n",
            ".github/workflows/dco.yml": "name: DCO Check\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_enforced")
        assert rows[0]["label"] == "partial"


class TestCombinedNoStoryFinding:
    def test_no_doc_and_no_config_emits_combined_finding(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        anns = ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_provenance")
        assert rows
        assert rows[0]["label"] == "no_signal"

    def test_combined_finding_absent_when_config_exists_even_without_doc(
        self, tmp_path, registry, project
    ):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "README.md": "# hi\n",
            ".clabot": "{}\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "cla_dco_provenance")
        assert not rows


class TestUnreadableContributing:
    def test_unreadable_is_unverified_not_no_signal(self, tmp_path, registry, project, monkeypatch):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"CONTRIBUTING.md": "We use DCO.\n"})

        surveyor = ContributionProvenanceSurveyor(project, registry, local_path=str(root))
        orig_read_text = Path.read_text

        def broken_read_text(self, *a, **kw):
            if self.name == "CONTRIBUTING.md":
                raise OSError("simulated unreadable file")
            return orig_read_text(self, *a, **kw)

        monkeypatch.setattr(Path, "read_text", broken_read_text)
        surveyor.run()
        rows = _finding(registry, project.slug, "cla_dco_stated")
        assert rows[0]["label"] == "unverified"
        assert rows[0]["detail"]["outcome_cause"] == "contributing_doc_unreadable"


class TestScanSummaryOnEveryRun:
    """The shared _gap_analysis_results reader (repo_survey_definition_adapter.py)
    reads status from a check_name='scan_summary' row — its own docstring says
    each of the four GAP analyses writes one. Only the empty-inventory
    _unverified() path did; the normal-run path never wrote one at all,
    silently dropping the status envelope on every completed run.
    Backlog.md item 3's 31-reader sweep."""

    def test_normal_run_writes_scan_summary(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "CONTRIBUTING.md": "We use DCO.\n",
        })
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows, "no scan_summary row on a normal completed run"
        assert rows[0]["label"] == "recovered"

    def test_no_signal_run_still_writes_scan_summary(self, tmp_path, registry, project):
        """Neither a stated document nor enforcement config — the
        cla_dco_provenance no_signal branch — must still leave a
        scan_summary row behind."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        ContributionProvenanceSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows, "no scan_summary row on a normal completed run"
