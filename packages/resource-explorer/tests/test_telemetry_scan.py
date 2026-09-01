"""Tests for TelemetryScanSurveyor — repo_telemetry_scan
(docs/gap-analyses-design.md §2). Not registered (task scope boundary) —
invoked directly here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.telemetry_scan import (
    FINDING_KIND,
    TelemetryScanSurveyor,
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


class TestOutcomeMapping:
    def test_empty_inventory_is_unverified(self, tmp_path, registry, project):
        root = tmp_path / "root"
        root.mkdir()
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        assert any(a.json_properties.get("outcome_cause") == "empty_file_inventory"
                   for a in anns)

    def test_no_source_files_is_unverified_not_no_signal_KNOWN_NEGATIVE(
        self, tmp_path, registry, project
    ):
        """Known-negative for the design's own stated trap: a data-only repo
        (no scannable source extension anywhere) must NOT report a
        confident 'no telemetry' — proves the extra known-positive
        (source_files_considered) actually gates the outcome, not just
        has_file_inventory."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "data.csv": "a,b,c\n1,2,3\n",
            "config.yaml": "key: value\n",
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        summary = [a for a in anns if a.json_properties.get("outcome")]
        assert summary
        assert summary[0].json_properties["outcome"] == "unverified"
        assert summary[0].json_properties["outcome_cause"] == "no_source_files_in_inventory"

    def test_clean_source_is_no_signal_with_known_positive(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "app.py": "import requests\n\ndef fetch(url):\n    return requests.get(url)\n",
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows[0]["label"] == "no_signal"
        summary_ann = [a for a in anns if a.json_properties.get("outcome") == "no_signal"]
        assert summary_ann
        assert summary_ann[0].json_properties["outcome_known_positive"] is True

    def test_telemetry_sdk_match_is_recovered(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "app.py": "sentry_dsn = 'https://x@o1.ingest.sentry.io/1'\n",
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows[0]["label"] == "recovered"
        matches = _finding(registry, project.slug, "telemetry_call_site")
        assert matches

    def test_rfa_only_when_matched_and_undisclosed(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "app.py": "sentry_dsn = 'https://x@o1.ingest.sentry.io/1'\n",
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        rfas = [a for a in anns if a.__class__.__name__ == "RequestForActionAnnotation"]
        assert rfas

    def test_no_rfa_when_matched_but_disclosed(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "app.py": "sentry_dsn = 'https://x@o1.ingest.sentry.io/1'\n",
            "PRIVACY.md": "We use telemetry for crash reporting. See our opt-out.\n",
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        rfas = [a for a in anns if a.__class__.__name__ == "RequestForActionAnnotation"]
        assert not rfas
        disc = _finding(registry, project.slug, "disclosure_document")
        assert disc[0]["label"] == "pass"

    def test_does_not_flag_a_plain_api_client_as_telemetry_KNOWN_NEGATIVE(
        self, tmp_path, registry, project
    ):
        """Known-negative: a normal HTTP client call must not itself trigger
        a match — only curated telemetry-SDK/analytics-vendor patterns
        should."""
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "client.py": (
                "import requests\n\n"
                "def get_widget(widget_id):\n"
                "    return requests.get(f'https://api.example.com/widgets/{widget_id}')\n"
            ),
        })
        anns = TelemetryScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        assert rows[0]["label"] == "no_signal"
