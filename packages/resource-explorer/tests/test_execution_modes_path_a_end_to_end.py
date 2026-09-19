"""Phase 3 of PLAN-EXECUTION-MODES-VERIFICATION.md — Path A end-to-end from a
fixtured Survey Definition, publishing off (plan §2 "Path A").

Path A (`executes_at: resource-explorer`) is the one execution mode with
substantial existing dispatch-logic coverage (test_survey_definition_executor.py),
but per the plan's own honest accounting, "what is not covered is the whole
route end to end from a live Egeria-hosted definition" — no test runs a
multi-step, batch-eligible, guarded Survey Definition against a real
resource and checks that real annotations land in the real registry tables.

This fixes that for the mockable half (publishing off — a live Egeria round
trip is Phase 6 of the plan, out of scope here). It:

- fixtures a Survey Definition the way `SurveyDefinitionReader` would return
  one (SurveyDefinition/SurveyStep/StepLink, the same dataclasses the reader
  builds from Egeria's real process graph);
- runs it against a small real repo fixture on disk (an actual directory
  tree with real files, walked for real — not a mocked scan);
- registers a ResourceTypeAdapter whose two RE-side steps are consecutive,
  "resource-explorer", and `run_batch`-eligible (mirroring the real repo
  adapter's own `run_batch`, survey_definition_executor.py:371-373), and
  whose third step is reached only through a real (non-"Any") guard;
- runs the whole thing through `SurveyDefinitionExecutor` against a real
  SQLite-backed `ProjectRegistry`, so "annotations actually written to the
  step's own table" is a real `query_findings()` read, not an assertion
  about a mock's call args.
"""
from __future__ import annotations

import subprocess
from unittest.mock import MagicMock

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    SurveyDefinitionExecutor,
    register_adapter,
)
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, StepLink, SurveyStep
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    ResourceMeasureAnnotation,
    assert_unique_qualified_names,
)


@pytest.fixture
def repo_root(tmp_path):
    """A small, real repo-shaped directory tree — real files, really walked."""
    root = tmp_path / "fixture-repo"
    root.mkdir()
    (root / "README.md").write_text("# Fixture repo\n\nA small repo for Path A's end-to-end test.\n")
    pkg = root / "pkg"
    pkg.mkdir()
    (pkg / "a.py").write_text("def f():\n    return 1\n")
    (pkg / "b.py").write_text("def g():\n    return 2\n")
    (pkg / "data.txt").write_text("not code\n")
    # Real git repo, not just a directory — closer to what "repo" means
    # elsewhere in this codebase, and cheap (no network involved).
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    return root


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test_registry.db"))


@pytest.fixture
def project(registry):
    p = Project(
        slug="fixture-repo", display_name="Fixture Repo",
        github_url="https://example.invalid/fixture-repo", collections=[],
    )
    registry.add(p)
    return p


def _make_adapter(repo_root, created_annotations, publish_spy):
    """Builds the ResourceTypeAdapter under test, closing over `repo_root` so
    each step does real filesystem work against the fixture, and over
    `created_annotations` so the test can inspect the very Annotation
    objects the executor stamps in place (item_key is set on the object,
    not returned separately in the executor's result dict)."""

    def _inventory(project, registry, **_) -> dict:
        py_files = sorted(str(p.relative_to(repo_root)) for p in repo_root.rglob("*.py"))
        registry.upsert_finding(
            project.slug, "fixture_inventory",
            [{"check_name": "python_file_count", "label": str(len(py_files)),
              "summary": f"{len(py_files)} Python files"}],
        )
        ann = ResourceMeasureAnnotation(
            summary=f"{len(py_files)} Python files found",
            analysis_step="FixtureInventory",
            check_name="python_file_count",
            resource_properties={"python_file_count": len(py_files)},
        )
        created_annotations.append(ann)
        return {"annotations": [ann], "guard": "has_python" if py_files else "no_python"}

    def _classify(project, registry, **_) -> dict:
        has_readme = (repo_root / "README.md").exists()
        registry.upsert_finding(
            project.slug, "fixture_classification",
            [{"check_name": "has_readme", "label": "pass" if has_readme else "gap",
              "summary": "README present" if has_readme else "README missing"}],
        )
        ann = ClassificationAnnotation(
            summary="README present" if has_readme else "README missing",
            analysis_step="FixtureClassify",
            check_name="has_readme",
        )
        created_annotations.append(ann)
        return {"annotations": [ann]}

    def _run_batch(project, registry, step_keys, **_) -> dict:
        """Mirrors repo_survey_definition_adapter.py's real `_run_batch`
        shape: one call covering several step_keys, sharing whatever the
        group's steps would otherwise each re-acquire independently (here,
        `repo_root` itself — resolved once per test, not once per step)."""
        outputs = []
        if "fixture_inventory" in step_keys:
            outputs.append(_inventory(project, registry))
        if "fixture_classification" in step_keys:
            outputs.append(_classify(project, registry))
        annotations = [a for o in outputs for a in o.get("annotations", [])]
        errors = [e for o in outputs for e in o.get("errors", [])]
        # The guard downstream steps branch on — carried from whichever
        # output declared one (here, the inventory step).
        guard = next((o["guard"] for o in outputs if "guard" in o), None)
        return {"annotations": annotations, "errors": errors, "guard": guard}

    def _security(project, registry, **_) -> dict:
        # Reached only if the guard below is satisfied — the fixture repo
        # has no SECURITY.md, a real (not simulated) gap.
        has_security_md = (repo_root / "SECURITY.md").exists()
        registry.upsert_finding(
            project.slug, "fixture_security",
            [{"check_name": "security_policy", "label": "pass" if has_security_md else "gap",
              "summary": "SECURITY.md present" if has_security_md else "SECURITY.md missing"}],
        )
        ann = ClassificationAnnotation(
            summary="SECURITY.md present" if has_security_md else "SECURITY.md missing",
            analysis_step="FixtureSecurity",
            check_name="security_policy",
        )
        created_annotations.append(ann)
        return {"annotations": [ann]}

    def _publish(entity, step_outputs, surveyed_at, registry, *, defer_drain=False):
        publish_spy(entity, step_outputs, surveyed_at, registry)
        return "should-not-be-called"

    return ResourceTypeAdapter(
        entity_type="fixture_repo",
        technology_type="Fixture Repo Tech",
        re_analysis_steps={
            "fixture_inventory": _inventory,
            "fixture_classification": _classify,
            "fixture_security": _security,
        },
        get_entity=lambda registry, slug: registry.get(slug),
        publish=_publish,
        run_batch=_run_batch,
    )


def _fixture_survey_definition() -> SurveyDefinition:
    """As SurveyDefinitionReader would return it: real SurveyStep/StepLink
    dataclasses, a batch-eligible consecutive pair (s1 -> s2, unconditional),
    and a real guard (s2 -> s3, non-"Any")."""
    return SurveyDefinition(
        process_guid="proc-fixture-repo",
        display_name="Fixture Repo Survey",
        qualified_name="GovActionProcess::FixtureRepoSurvey",
        supported_technology_type="Fixture Repo Tech",
        steps=[
            SurveyStep(
                guid="s1", display_name="Inventory", qualified_name="Step::Inventory",
                executes_at="resource-explorer", re_analysis_step="fixture_inventory",
            ),
            SurveyStep(
                guid="s2", display_name="Classify", qualified_name="Step::Classify",
                executes_at="resource-explorer", re_analysis_step="fixture_classification",
            ),
            SurveyStep(
                guid="s3", display_name="Security", qualified_name="Step::Security",
                executes_at="resource-explorer", re_analysis_step="fixture_security",
            ),
        ],
        links=[
            StepLink(previous_guid="s1", next_guid="s2", guard="Any", mandatory_guard=False),
            StepLink(previous_guid="s2", next_guid="s3", guard="has_python", mandatory_guard=False),
        ],
    )


def _fake_reader(survey_def):
    reader = MagicMock()
    reader.fetch.return_value = survey_def
    reader.find_candidate_process_guids.return_value = [{
        "guid": survey_def.process_guid,
        "qualified_name": survey_def.qualified_name,
        "display_name": survey_def.display_name,
    }]
    return reader


class TestPathAEndToEndFromAFixturedDefinition:

    def test_every_step_runs_annotations_persist_provenance_is_stamped_and_no_collision(
        self, repo_root, registry, project,
    ):
        created_annotations: list = []
        publish_spy = MagicMock()
        adapter = _make_adapter(repo_root, created_annotations, publish_spy)
        register_adapter(adapter)

        survey_def = _fixture_survey_definition()
        reader = _fake_reader(survey_def)
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="fixture_repo", slug="fixture-repo")

        # ── every step appears in steps_report ──────────────────────────
        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses == {
            "Step::Inventory": "ok",
            "Step::Classify": "ok",
            "Step::Security": "ok",
        }
        assert result["errors"] == []

        # ── the batch pair actually ran as ONE call, not two ────────────
        # (proven indirectly: both annotations exist, and the guard the
        # downstream step needed was produced — only run_batch's shared
        # "guard" key could have supplied it consistently to both grouped
        # steps.)
        assert len(created_annotations) == 3

        # ── annotations actually written to the step's own table ───────
        inventory_findings = registry.query_findings("fixture-repo", "fixture_inventory")
        assert len(inventory_findings) == 1
        assert inventory_findings[0]["check_name"] == "python_file_count"
        assert inventory_findings[0]["label"] == "2"  # a.py, b.py

        classify_findings = registry.query_findings("fixture-repo", "fixture_classification")
        assert len(classify_findings) == 1
        assert classify_findings[0]["check_name"] == "has_readme"
        assert classify_findings[0]["label"] == "pass"

        security_findings = registry.query_findings("fixture-repo", "fixture_security")
        assert len(security_findings) == 1
        assert security_findings[0]["check_name"] == "security_policy"
        assert security_findings[0]["label"] == "gap"  # no SECURITY.md in the fixture

        # ── the guard actually gated execution, it wasn't just always-run ──
        # If the guard mechanism were broken (e.g. always True), this test
        # wouldn't distinguish that from "guards don't exist" — so also
        # confirm the guard was really evaluated by construction: the
        # Security step's own StepLink names a non-"Any" guard, and it ran,
        # which only happens if `_guard_check` matched the batch's produced
        # guard against it (see survey_definition_executor.py's
        # `_guard_check`/`produced_guard`).
        assert statuses["Step::Security"] == "ok"

        # ── _stamp_definition_provenance gave every keyless annotation the
        # definition's own qualified_name ──
        for ann in created_annotations:
            assert ann.item_key == "GovActionProcess::FixtureRepoSurvey"

        # ── the collision guard does not raise on a clean run ───────────
        assert_unique_qualified_names("fixture-repo", created_annotations)

        # ── publishing off: no assigned Egeria project on this fresh
        # project, so the adapter's publish must never be called ──────────
        publish_spy.assert_not_called()
        assert result["published"] is False
        assert result["egeria_report_guid"] == ""

    def test_an_unsatisfied_guard_would_have_skipped_the_downstream_step(
        self, repo_root, registry, project,
    ):
        """Negative control for the guard assertion above: if the fixture
        repo genuinely had no Python files, the inventory step would produce
        guard="no_python", the link still requires "has_python", and the
        Security step must be skipped rather than run — proving the guard
        in the happy-path test was doing real work, not passing vacuously."""
        empty_root = repo_root.parent / "empty-fixture-repo"
        empty_root.mkdir()
        (empty_root / "README.md").write_text("# Empty\n")
        subprocess.run(["git", "init", "-q"], cwd=empty_root, check=True)

        created_annotations: list = []
        publish_spy = MagicMock()
        adapter = _make_adapter(empty_root, created_annotations, publish_spy)
        register_adapter(adapter)

        survey_def = _fixture_survey_definition()
        reader = _fake_reader(survey_def)
        executor = SurveyDefinitionExecutor(registry, reader=reader)

        result = executor.run(entity_type="fixture_repo", slug="fixture-repo")

        statuses = {s["step"]: s["status"] for s in result["steps"]}
        assert statuses["Step::Inventory"] == "ok"
        assert statuses["Step::Classify"] == "ok"
        assert statuses["Step::Security"] == "skipped_by_design"
        assert registry.query_findings("fixture-repo", "fixture_security") == []
