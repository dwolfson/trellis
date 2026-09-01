"""Tests for SecretScanSurveyor and secret_ruleset.py — repo_secret_scan
(docs/gap-analyses-design.md §1). Not registered in STEP_REGISTRY (task
scope boundary) — invoked directly here.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors import secret_ruleset as ruleset_mod
from resource_explorer.surveyors.sub_surveyors.secret_scan import (
    FINDING_KIND,
    SecretScanSurveyor,
)
from resource_explorer.surveyors import result_status


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


class TestKnownPositiveSelfTest:
    """The load-bearing check design §1 insists on: the ruleset's own
    fixture, not a scanned-file count."""

    def test_self_test_passes_against_the_real_vendored_ruleset(self):
        rules = ruleset_mod.load_ruleset()
        result = ruleset_mod.run_self_test(rules)
        assert result.passed, f"missing rule ids: {sorted(result.missing_rule_ids)}"

    def test_self_test_fails_loudly_on_an_empty_ruleset_KNOWN_NEGATIVE(self, tmp_path):
        """Known-negative: an artificially neutered ruleset (a copy of the
        real TOML with every rule's regex replaced by something that can
        never match) must fail the self-test rather than silently pass —
        proving this guard can actually fail, per the task's own rule."""
        import tomllib
        with ruleset_mod.DEFAULT_RULESET_PATH.open("rb") as fh:
            data = tomllib.load(fh)
        broken_toml = tmp_path / "broken.toml"
        lines = ["title = \"broken\"\n"]
        for rule in data["rules"]:
            if rule["id"] not in ruleset_mod._SELF_TEST_EXPECTED_RULE_IDS:
                continue
            lines.append("[[rules]]\n")
            lines.append(f'id = "{rule["id"]}"\n')
            lines.append('description = "neutered"\n')
            # A regex that can never match anything.
            lines.append('regex = \'\'\'$unmatchable^\'\'\'\n')
        broken_toml.write_text("".join(lines))

        rules = ruleset_mod.load_ruleset(broken_toml)
        result = ruleset_mod.run_self_test(rules)
        assert not result.passed
        assert result.missing_rule_ids == ruleset_mod._SELF_TEST_EXPECTED_RULE_IDS


class TestRulesetUnavailableIsSkippedByDesign:
    def test_missing_ruleset_file_emits_skipped_by_design_not_no_signal(
        self, tmp_path, registry, project
    ):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"a.py": "x = 1\n"})

        missing_path = tmp_path / "does-not-exist.toml"

        import resource_explorer.surveyors.sub_surveyors.secret_scan as secret_scan_mod

        real_load_ruleset = ruleset_mod.load_ruleset  # captured BEFORE patching

        def fake_load_ruleset():
            return real_load_ruleset(missing_path)

        secret_scan_mod.ruleset_mod.load_ruleset = fake_load_ruleset
        try:
            anns = SecretScanSurveyor(project, registry, local_path=str(root)).run()
        finally:
            secret_scan_mod.ruleset_mod.load_ruleset = real_load_ruleset

        assert any(
            result_status.SKIPPED_BY_DESIGN in getattr(a, "candidate_classifications", [])
            for a in anns
        )
        rows = _finding(registry, project.slug, "ruleset_available")
        assert rows and rows[0]["label"] == result_status.SKIPPED_BY_DESIGN


class TestOutcomeMapping:
    def test_empty_inventory_is_unverified(self, tmp_path, registry, project):
        # No upsert_file_inventory call at all.
        root = tmp_path / "root"
        root.mkdir()
        anns = SecretScanSurveyor(project, registry, local_path=str(root)).run()
        summary = [a for a in anns if "empty" in a.summary.lower()]
        assert summary
        assert summary[0].json_properties["outcome"] == "unverified"
        assert summary[0].json_properties["outcome_cause"] == "empty_file_inventory"

    def test_clean_scan_is_no_signal_with_known_positive(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "README.md": "# Hello\n\nJust a normal repo.\n",
            "app.py": "def main():\n    print('hi')\n",
        })
        anns = SecretScanSurveyor(project, registry, local_path=str(root)).run()
        summary_rows = _finding(registry, project.slug, "scan_summary")
        assert summary_rows
        assert summary_rows[0]["label"] == "no_signal"

        summary_ann = [a for a in anns if "No matches against" in a.summary]
        assert summary_ann
        props = summary_ann[0].json_properties
        assert props["outcome"] == "no_signal"
        assert props["outcome_known_positive"] is True
        assert "not a claim" in summary_ann[0].summary.lower()

    def test_real_match_is_recovered_and_masked(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "config.py": 'aws_key = "AKIATESTFAKEKEY2345Q"\n',
        })
        anns = SecretScanSurveyor(project, registry, local_path=str(root)).run()

        summary_rows = _finding(registry, project.slug, "scan_summary")
        assert summary_rows[0]["label"] == "recovered"

        match_rows = _finding(registry, project.slug, "secret_pattern")
        assert match_rows
        row = match_rows[0]
        assert row["label"] == "aws-access-token"
        assert "AKIATESTFAKEKEY2345Q" not in str(row)  # never persisted raw

        rfas = [a for a in anns if a.__class__.__name__ == "RequestForActionAnnotation"]
        assert rfas
        assert "AKIATESTFAKEKEY2345Q" not in rfas[0].explanation

    def test_excerpt_is_masked_not_raw(self):
        masked = ruleset_mod.mask_excerpt("AKIATESTFAKEKEY2345Q")
        assert masked != "AKIATESTFAKEKEY2345Q"
        assert masked.startswith("AKIA")
        assert "*" in masked


class TestRulesetFreshness:
    def test_freshness_finding_is_always_emitted_when_ruleset_available(
        self, tmp_path, registry, project
    ):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"a.py": "x = 1\n"})
        SecretScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "ruleset_freshness")
        assert rows
        assert rows[0]["label"] in {"current", "stale"}
        assert rows[0]["detail"]["provider_name"] == "gitleaks"


class TestProvenanceOnEveryRow:
    """Design §1: 'ruleset and ruleset_version belong in EVERY persisted
    row this step writes — both the per-match findings above and the
    summary/outcome row below — not just the ones with hits.'"""

    def test_provider_fields_present_on_clean_scan_summary(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {"README.md": "hello\n"})
        SecretScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "scan_summary")
        detail = rows[0]["detail"]
        assert detail["provider_name"] == "gitleaks"
        assert detail["provider_kind"] == "vendored_ruleset"
        assert detail["version_or_as_of"]

    def test_provider_fields_present_on_match_rows(self, tmp_path, registry, project):
        root = tmp_path / "root"
        _write_inventory(registry, project.slug, root, {
            "config.py": 'aws_key = "AKIATESTFAKEKEY2345Q"\n',
        })
        SecretScanSurveyor(project, registry, local_path=str(root)).run()
        rows = _finding(registry, project.slug, "secret_pattern")
        assert rows[0]["detail"]["provider_name"] == "gitleaks"
