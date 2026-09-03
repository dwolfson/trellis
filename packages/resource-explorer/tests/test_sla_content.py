"""Tests for SlaContentSurveyor — repo_sla_content
(docs/gap-analyses-design.md §4). Not registered (task scope boundary) —
invoked directly here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.sla_content import (
    FINDING_KIND,
    SlaContentSurveyor,
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


class TestNeverPassGapVocabulary:
    """Design §4's most-emphasised rule: label is present/absent, NEVER
    pass/gap — absence is the common, unremarkable case."""

    def test_absent_case_never_uses_pass_gap_labels(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["label"] == "absent"
        assert rows[0]["label"] not in {"pass", "gap"}

    def test_present_case_never_uses_pass_gap_labels(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "We guarantee 99.9% uptime and respond to P1 issues within 1 hour.\n",
        })
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["label"] == "present"
        assert rows[0]["label"] not in {"pass", "gap"}


class TestNoRfaForAbsence:
    """Design §4: absence must NEVER produce a RequestForActionAnnotation
    from this analysis alone. Known-negative angle: a naive port of
    SecurityHygieneSurveyor's pattern (RFA-per-gap) would fail this."""

    def test_absence_never_emits_an_rfa(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        anns = SlaContentSurveyor(project, registry, local_path=str(root)).run()
        assert not any(a.__class__.__name__ == "RequestForActionAnnotation" for a in anns)

    def test_presence_also_never_emits_an_rfa(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "99.9% uptime, business hours support.\n",
        })
        anns = SlaContentSurveyor(project, registry, local_path=str(root)).run()
        assert not any(a.__class__.__name__ == "RequestForActionAnnotation" for a in anns)


class TestOutcomeMapping:
    def test_empty_inventory_is_unverified(self, tmp_path, registry, project):
        root = tmp_path / "root"
        root.mkdir()
        anns = SlaContentSurveyor(project, registry, local_path=str(root)).run()
        assert any(a.json_properties.get("outcome_cause") == "empty_file_inventory"
                   for a in anns)

    def test_no_candidate_paths_is_no_signal_with_checked_list(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"main.py": "print('x')\n"})
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["label"] == "absent"
        assert rows[0]["detail"]["outcome"] == "no_signal"
        assert rows[0]["detail"]["outcome_known_positive"] is True

    def test_candidate_present_no_sla_keywords_is_no_signal_KNOWN_NEGATIVE(
        self, tmp_path, registry, project
    ):
        """Known-negative: a generic SUPPORT.md ('file an issue') must NOT
        be read as SLA-shaped content."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "Please file an issue on GitHub if you need help.\n",
        })
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["label"] == "absent"
        assert rows[0]["detail"]["outcome"] == "no_signal"

    def test_sla_shaped_content_is_recovered_and_lists_paths_checked(
        self, tmp_path, registry, project
    ):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "We guarantee 99.9% uptime.\n",
            "README.md": "# hi\n",
        })
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["label"] == "present"
        assert "SUPPORT.md" in rows[0]["detail"]["candidate_paths_checked"]
        evidence = _finding(registry, project.slug, "sla_content_evidence")
        assert evidence

    def test_candidate_paths_checked_recorded_even_when_absent(self, tmp_path, registry, project):
        """The searched-and-absent list IS the known-positive per design
        §4 — must be present even on the absent branch."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"SUPPORT.md": "file an issue\n"})
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "sla_content")
        assert rows[0]["detail"]["candidate_paths_checked"]


class TestMustNotClaimTruth:
    def test_summary_text_disclaims_verification(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "We guarantee 99.9% uptime.\n",
        })
        anns = SlaContentSurveyor(project, registry, local_path=str(root)).run()
        summary = [a for a in anns if a.json_properties.get("outcome") == "recovered"]
        assert summary
        text = summary[0].summary.lower()
        assert "not" in text and ("verify" in text or "honoured" in text or "true" in text)


class TestScanSummaryOnEveryRun:
    """The shared _gap_analysis_results reader (repo_survey_definition_adapter.py)
    reads status from a check_name='scan_summary' row — its own docstring says
    each of the four GAP analyses writes one. Only the empty-inventory
    _unverified() path did; every normal-run branch wrote 'sla_content'
    instead, silently dropping the status envelope on every completed run.
    Backlog.md item 3's 31-reader sweep."""

    def test_absent_branch_writes_scan_summary(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "# hi\n"})
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows, "no scan_summary row on a normal completed run"

    def test_present_branch_writes_scan_summary(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "SUPPORT.md": "We guarantee 99.9% uptime and respond to P1 issues within 1 hour.\n",
        })
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows, "no scan_summary row on a normal completed run"
        assert rows[0]["label"] == "recovered"

    def test_no_candidate_paths_branch_still_writes_scan_summary(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"main.py": "print('hi')\n"})
        SlaContentSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows, "no scan_summary row when there were no candidate paths at all"
