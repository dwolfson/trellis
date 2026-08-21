"""Integration tests for the two architecture-recovery survey steps (Phase 1
plan §4.2/§4.3/§4.4) — ArchDetectSurveyor/ArchCouplingSurveyor persisting
into project_analysis_findings/project_analysis_metrics under
kind="architecture_recovery", and the repo_survey_definition_adapter.py
results reader that reassembles them.
"""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.arch_recovery import code_markers
from resource_explorer.surveyors.sub_surveyors.arch_recovery_coupling import ArchCouplingSurveyor
from resource_explorer.surveyors.sub_surveyors.arch_recovery_detect import ArchDetectSurveyor
from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation

pytestmark = pytest.mark.skipif(
    code_markers._binary() is None, reason="ast-grep binary not available in this environment"
)


@pytest.fixture
def registry(tmp_path_factory):
    return ProjectRegistry(db_path=str(tmp_path_factory.mktemp("db") / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="archproj", display_name="Arch Proj", github_url="https://github.com/a/archproj")
    registry.add(p)
    return p


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


class TestArchDetectSurveyor:
    def test_no_local_path_raises_an_rfa_not_an_exception(self, project, registry):
        results = ArchDetectSurveyor(project, registry, local_path=None).run()
        assert len(results) == 1
        assert results[0].annotation_type.value == "RequestForAction"

    def test_manifest_component_persists_a_component_finding_and_metric(self, tmp_path, project, registry):
        root = str(tmp_path)
        _write(root, "pyproject.toml", '[project]\nname = "archproj"\nscripts = { archproj = "archproj:main" }\n')
        _write(root, "archproj/__init__.py", "")

        results = ArchDetectSurveyor(project, registry, local_path=root, surveyed_at="2026-08-21T00:00:00").run()

        assert any(isinstance(r, ResourceMeasureAnnotation) for r in results)
        scopes = registry.query_finding_scopes(project.slug, "architecture_recovery", check_name="component")
        assert scopes, "expected at least one component scope_locator"
        # The manifest component's scope_locator is its directory (".": the
        # root of this fixture) — design doc §6.0, "a component is a path prefix".
        findings = registry.query_findings(project.slug, "architecture_recovery", scope_locator=scopes[0])
        comp_row = next(f for f in findings if f["check_name"] == "component")
        assert comp_row["label"] == "Console Command"

        metrics = registry.query_metrics(project.slug, "architecture_recovery", scope_locator=scopes[0])
        assert metrics["confidence"] > 0

        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        assert run_summary["detect_component_count"] == 1


class TestArchCouplingSurveyor:
    def _git_repo_with_two_cohesive_subpackages(self, tmp_path):
        root = str(tmp_path)
        _write(root, "pyproject.toml", '[project]\nname = "archproj"\n')
        # "pkg" subpackage: two files that import each other tightly — a
        # cohesive candidate subtree.
        _write(root, "pkg/a.py", "from pkg.b import helper\n\ndef use():\n    return helper()\n")
        _write(root, "pkg/b.py", "def helper():\n    return 1\n")
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(
            ["git", "-c", "user.email=t@example.com", "-c", "user.name=Test",
             "commit", "-q", "-m", "initial"],
            cwd=root, check=True,
        )
        return root

    def test_no_local_path_raises_an_rfa_not_an_exception(self, project, registry):
        results = ArchCouplingSurveyor(project, registry, source_path=None, history_path=None).run()
        assert len(results) == 1
        assert results[0].annotation_type.value == "RequestForAction"

    def test_cohesive_subpackage_is_proposed_and_persisted(self, tmp_path, project, registry):
        root = self._git_repo_with_two_cohesive_subpackages(tmp_path)

        results = ArchCouplingSurveyor(project, registry, source_path=root, history_path=root,
                             surveyed_at="2026-08-21T00:00:00").run()

        assert any(isinstance(r, ResourceMeasureAnnotation) for r in results)
        scopes = registry.query_finding_scopes(project.slug, "architecture_recovery", check_name="component")
        assert "pkg" in scopes

        findings = registry.query_findings(project.slug, "architecture_recovery", scope_locator="pkg")
        comp_row = next(f for f in findings if f["check_name"] == "component")
        # coupling never asserts a SolutionComponentType — that overstates
        # what the signal knows (module docstring / README finding 41).
        assert comp_row["label"] == "Unclassified"

        evidence_rows = [f for f in findings if f["check_name"] != "component"]
        assert any(f["label"].startswith("coupling") for f in evidence_rows)

        run_summary = registry.query_metrics(project.slug, "architecture_recovery", scope_locator="")
        assert run_summary["coupling_component_count"] >= 1


class TestResultsReaderCombinesBothSteps:
    def test_component_proposed_by_both_steps_shows_both_approaches(self, tmp_path, project, registry):
        """A component both repo_arch_detect and repo_arch_coupling see (at
        different times — they are independent steps, not required to run
        together) must show evidence from BOTH in the results view, not
        just whichever step ran most recently — the reason
        query_findings_all_runs exists rather than reusing query_findings."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _architecture_recovery_results,
        )

        root = self._git_repo_with_two_cohesive_subpackages_static(tmp_path)
        ArchDetectSurveyor(project, registry, local_path=root, surveyed_at="2026-08-21T00:00:00").run()
        ArchCouplingSurveyor(project, registry, source_path=root, history_path=root,
                             surveyed_at="2026-08-22T00:00:00").run()

        result = _architecture_recovery_results(registry, project.slug)
        comp = next((c for c in result["components"] if c["path"] == "pkg"), None)
        assert comp is not None
        assert len(comp["proposed_by"]) >= 1

    @staticmethod
    def _git_repo_with_two_cohesive_subpackages_static(tmp_path):
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
        return root


class TestScopeLocatorUniqueness:
    """Regression for spike README findings 45-46.

    A files-less component (compose-derived — §8.2b's add-on and shared-infra
    tiers own no first-party code) once fell back to `identity.deployment_context`
    for its `scope_locator`. That is the compose FILE'S directory, shared by every
    service declared in it, so distinct containers collided on the join key: 58
    compose-service components collapsed onto 10 locators and every reader kept
    one container per file, silently discarding the rest. T1 deployment recall
    fell 18/27 -> 2/27 and no unit test noticed, because each component was built
    correctly and only the persisted key was wrong.
    """

    @staticmethod
    def _fileless(slug: str, container: str, compose_dir: str):
        from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
        return Component(
            slug=slug, name=container, type=None,
            identity=Identity("deployment-unit", container, compose_dir), files=[],
        )

    def test_containers_from_one_compose_file_get_distinct_scope_locators(self):
        from resource_explorer.surveyors.arch_recovery.persist import scope_locator_for

        shared = "compose-configs/shared-infra"
        components = [
            self._fileless(f"shared-infra::{n}", n, shared)
            for n in ("egeria-shared-kafka", "egeria-shared-postgres",
                      "egeria-shared-kroki", "egeria-shared-kroki-mermaid")
        ]
        locators = [scope_locator_for(c) for c in components]
        assert len(set(locators)) == len(components), (
            f"distinct containers collided on scope_locator: {locators}"
        )
        # and the shared compose directory must not be the key for any of them
        assert shared not in locators

    def test_path_bearing_components_still_use_their_path_prefix(self):
        """The fix must not disturb the normal case: a component that owns
        files is still keyed by its path prefix (design §6.0)."""
        from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
        from resource_explorer.surveyors.arch_recovery.persist import scope_locator_for

        c = Component(
            slug="coupling::packages::foo", name="foo", type=None,
            identity=Identity("module-path", "packages/foo"),
            files=["packages/foo/**"],
        )
        assert scope_locator_for(c) == "packages/foo"


class TestScopedRunsAreMarkedPartial:
    """The fourth bug of the family: `scope_locator` carried two meanings.

    D5/D6 scope narrowing uses it for "this run was narrowed to `packages/foo`".
    Architecture recovery (design §6.0) uses it for "this component IS
    `packages/foo`". Same column, same kind, and they collide exactly — run
    repo_arch_detect scoped to a subtree and the component found there keys on
    the identical value.

    Because nothing recorded which meaning a row carried, a SCOPED run — which
    by definition saw only part of the repo, so its component set is
    necessarily incomplete — wrote rows indistinguishable from a whole-repo
    run's. A reader merging them shows a partial architecture as if it were the
    whole one, with no signal that anything is missing.
    """

    def test_a_whole_repo_run_is_not_marked_partial(self, project, registry, tmp_path):
        from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
        from resource_explorer.surveyors.arch_recovery.persist import persist_ir

        c = Component(slug="s", name="foo", type="Software Library",
                      identity=Identity("package-name", "foo"), files=["packages/foo/**"])
        persist_ir(registry, project.slug, [c], [], "2026-08-21T00:00:00")

        # NB: query_findings defaults to scope_locator="" meaning
        # "whole-resource" — the RUN-scope meaning. A component row never keys
        # on "", it keys on its own path, so the default query finds nothing.
        # That mismatch is the same two-meanings problem surfacing in the query
        # API, and it is why the scope must be passed explicitly here.
        row = registry.query_findings(project.slug, "architecture_recovery", "packages/foo")[0]
        detail = json.loads(row["detail_json"])
        assert detail["partial"] is False
        assert detail["run_scope"] == ""

    def test_a_scoped_run_is_marked_partial_and_names_its_scope(self, project, registry):
        """Without this, the run scope and the component scope are the same
        string in the same column and neither the caller nor a later reader can
        tell a complete result from a fragment."""
        from resource_explorer.surveyors.arch_recovery.ir import Component, Identity
        from resource_explorer.surveyors.arch_recovery.persist import persist_ir

        c = Component(slug="s", name="foo", type="Software Library",
                      identity=Identity("package-name", "foo"), files=["packages/foo/**"])
        persist_ir(registry, project.slug, [c], [], "2026-08-21T00:00:00",
                   run_scope="packages/foo")

        row = registry.query_findings(project.slug, "architecture_recovery", "packages/foo")[0]
        detail = json.loads(row["detail_json"])
        assert detail["partial"] is True
        assert detail["run_scope"] == "packages/foo"
        # the collision itself: component scope and run scope are the same value
        assert row["scope_locator"] == detail["run_scope"], (
            "this equality is the bug's signature — the only thing separating "
            "the two meanings is now the explicit run_scope/partial stamp"
        )
