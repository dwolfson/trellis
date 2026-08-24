"""Tests for README finding 57: an unsupported-language repo (e.g. Rust)
must record `unverified`, not a silent zero, for both architecture-recovery
survey steps.

`step_outcome.py`'s own rule: "An approach with no known-positive check
cannot report `no_signal`, only `unverified`." `imports.py` extracts Python
and Java only; a Rust repo gives `repo_arch_coupling` nothing to read at all,
and `repo_arch_detect` nothing via manifests (no pyproject.toml/package.json/
settings.gradle), deployment units (no Dockerfile/compose), or code markers
(ast-grep rules are Python-only) either — so both steps must record why,
not just persist zero components and disappear.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.step_outcome import RECOVERED, UNVERIFIED
from resource_explorer.surveyors.arch_recovery import code_markers, imports
from resource_explorer.surveyors.sub_surveyors.arch_recovery_coupling import ArchCouplingSurveyor
from resource_explorer.surveyors.sub_surveyors.arch_recovery_detect import ArchDetectSurveyor

pytestmark = pytest.mark.skipif(
    code_markers._binary() is None, reason="ast-grep binary not available in this environment"
)


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="rustproj", display_name="Rust Proj", github_url="https://github.com/a/rustproj")
    registry.add(p)
    return p


def _write(root, rel, content=""):
    import os
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def _rust_only_git_repo(tmp_path):
    """A `unitycatalog_rs`-shaped fixture: real source, real Cargo.toml, no
    Python/Java anywhere — nothing either survey step's extractors can read."""
    root = str(tmp_path)
    _write(root, "Cargo.toml", '[package]\nname = "rustproj"\nversion = "0.1.0"\n')
    _write(root, "src/lib.rs", "pub fn helper() -> i32 { 1 }\n")
    _write(root, "src/main.rs", "mod lib;\nfn main() { lib::helper(); }\n")
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test",
         "commit", "-q", "-m", "initial"],
        cwd=root, check=True,
    )
    return root


class TestSupportedLanguageIsDerivedNotHardcoded:
    """Point 1: the check has to reflect what imports.py can extract, not a
    second list someone has to remember to keep in sync."""

    def test_supported_extensions_is_exactly_what_build_graph_scans(self):
        assert imports.SUPPORTED_EXTENSIONS == {".py": "python", ".java": "java"}

    def test_extractable_first_party_keeps_only_supported_extensions(self):
        files = ["a.py", "b.java", "c.rs", "d.go", "README.md"]
        assert imports.extractable_first_party(files) == ["a.py", "b.java"]

    def test_extractable_first_party_is_empty_for_a_rust_repo(self):
        files = ["src/lib.rs", "src/main.rs", "Cargo.toml"]
        assert imports.extractable_first_party(files) == []

    def test_languages_present_names_what_could_not_be_read(self):
        files = ["src/lib.rs", "src/main.rs", "Cargo.toml"]
        assert imports.languages_present(files) == {"rust": 2}

    def test_marker_languages_is_read_from_the_rule_files(self):
        # Asserted as a fact about the rule files rather than hardcoded
        # independently of them, so it breaks the day the rule set changes
        # rather than silently staying right by coincidence.
        #
        # It did exactly that. Go and Java marker rules landed (finding 94 — the
        # marker proposer had been Python-only, so every non-Python target was
        # running three proposers rather than four, and I had twice described it
        # as covering Java by reading the adjacent `rules-imports/` directory).
        # Updated to the new fact, not loosened: an assertion that any language
        # is present would stop catching the next silent change.
        assert code_markers.marker_languages() == {"go", "java", "python"}


class TestCouplingUnverifiedOnUnsupportedLanguage:
    def test_rust_only_repo_persists_unverified_not_a_silent_zero(self, tmp_path, project, registry):
        root = _rust_only_git_repo(tmp_path)

        results = ArchCouplingSurveyor(
            project, registry, source_path=root, history_path=root,
            surveyed_at="2026-08-22T00:00:00",
        ).run()

        assert results, "the step must still emit an annotation, not fail silently"
        # No component finding rows — that part of the old bug is expected and fine.
        scopes = registry.query_finding_scopes(project.slug, "architecture_recovery", check_name="component")
        assert scopes == []

        # But the run-summary row — persist_ir's one unconditional write — must
        # carry the outcome, which is the actual fix.
        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        assert run_summary["coupling_component_count"] == 0
        detail = run_summary["detail"]
        assert detail["outcome"] == UNVERIFIED
        assert detail["outcome_cause"] == "no_supported_source"
        assert detail["outcome_detail"]["languages_present"] == {"rust": 2}

    def test_python_repo_is_unaffected_by_the_unverified_check(self, tmp_path, project, registry):
        """Regression guard: a repo imports.py CAN read must not be swept
        into the new unverified path."""
        root = str(tmp_path)
        _write(root, "pyproject.toml", '[project]\nname = "archproj"\n')
        _write(root, "pkg/a.py", "from pkg.b import helper\n\ndef use():\n    return helper()\n")
        _write(root, "pkg/b.py", "def helper():\n    return 1\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "initial"],
            cwd=root, check=True,
        )

        ArchCouplingSurveyor(
            project, registry, source_path=root, history_path=root,
            surveyed_at="2026-08-22T00:00:00",
        ).run()

        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        assert run_summary["coupling_component_count"] >= 1
        detail = run_summary.get("detail") or {}
        # A recovered run's outcome_row (RECOVERED, cause="") also gets
        # attached now — assert it says RECOVERED, not unverified/partial.
        assert detail.get("outcome") == RECOVERED


class TestDetectUnverifiedOnUnsupportedLanguage:
    def test_rust_only_repo_with_no_manifest_or_deployment_signal_is_unverified(
        self, tmp_path, project, registry,
    ):
        root = _rust_only_git_repo(tmp_path)

        results = ArchDetectSurveyor(
            project, registry, local_path=root, surveyed_at="2026-08-22T00:00:00",
        ).run()

        assert results
        scopes = registry.query_finding_scopes(project.slug, "architecture_recovery", check_name="component")
        assert scopes == []

        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        assert run_summary["detect_component_count"] == 0
        detail = run_summary["detail"]
        assert detail["outcome"] == UNVERIFIED
        assert detail["outcome_cause"] == "no_supported_source"

    def test_a_dockerfile_makes_a_language_less_repo_a_real_zero_not_unverified(
        self, tmp_path, project, registry,
    ):
        """Point 4: detect has a way to find something (Dockerfile/compose)
        that does not depend on source-language extraction at all. A
        Rust repo whose Dockerfile is a bare build context (no owned
        first-party code beyond the Dockerfile itself) still can't produce a
        component — detectors.py's own "build context, not a component" rule
        — but detect DID have a real chance to look, so this must not be
        conflated with the fully-blind no_supported_source case."""
        root = _rust_only_git_repo(tmp_path)
        _write(root, "deploy/Dockerfile", "FROM rust:1\n")
        # exclusion.scan() reads git-tracked files only (docstring: "excludes
        # everything .gitignore covers ... without parsing a single gitignore
        # rule") — an untracked file added after the initial commit would
        # never reach first_party, which would make this test's Dockerfile
        # invisible to detect for a reason unrelated to what it is testing.
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "add dockerfile"],
            cwd=root, check=True,
        )

        ArchDetectSurveyor(
            project, registry, local_path=root, surveyed_at="2026-08-22T00:00:00",
        ).run()

        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        detail = run_summary["detail"]
        # A build-context-only Dockerfile still means detect could not find a
        # component to persist, but it is not the "no_supported_source"
        # unverified — the Dockerfile leg genuinely ran, so this is instead
        # the general no_signal-if-known-positive degradation (point 2).
        assert detail["outcome_cause"] != "no_supported_source"


class TestResultsReaderSurfacesUnverified:
    def test_unverified_run_is_visible_at_the_top_level_with_a_populated_surveyed_at(
        self, tmp_path, project, registry,
    ):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_headline,
            _architecture_recovery_results,
        )

        root = _rust_only_git_repo(tmp_path)
        ArchCouplingSurveyor(
            project, registry, source_path=root, history_path=root,
            surveyed_at="2026-08-22T00:00:00",
        ).run()

        out = _architecture_recovery_results(registry, project.slug)
        # This is the exact defect: before the fix, zero components meant
        # surveyed_at stayed "" and the run was indistinguishable from
        # "never ran".
        assert out["surveyed_at"] == "2026-08-22T00:00:00"
        assert out["unverified"] == ["coupling"]
        assert "coupling" in out["run_outcomes"]
        assert out["run_outcomes"]["coupling"]["outcome"] == UNVERIFIED

        headline = _architecture_recovery_headline(registry, project.slug)
        assert headline is not None
        assert "Unverified" in headline["label"]

    def test_query_metrics_history_raw_round_trips_detail(self, project, registry):
        registry.upsert_metric(
            project.slug, "architecture_recovery", {"coupling_component_count": 0.0},
            detail={"outcome": UNVERIFIED, "outcome_cause": "no_supported_source"},
            surveyed_at="2026-08-22T00:00:00", scope_locator="",
        )
        history = registry.query_metrics_history_raw(
            project.slug, "architecture_recovery", "coupling_component_count", scope_locator="",
        )
        assert len(history) == 1
        detail = json.loads(history[0]["detail_json"])
        assert detail["outcome"] == UNVERIFIED
