"""Tests for SurveyOrchestrator's steps parameter.

Focus: steps=None must keep running every sub-surveyor and self-logging
exactly as before this parameter existed (regression guard); steps=[...]
must run only the named sub-surveyor(s) and must NOT self-log — the caller
(scheduler.py's per-analysis-id dispatch, or repo_survey_definition_adapter.py)
writes its own, more specific activity-log entry for a targeted run, and
self-logging too would double it.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator


@contextmanager
def _fake_zipball_root(*_args, **_kwargs):
    """Stand-in for _acquire_zipball_root (D6) — no real network call.
    Any full-run (steps=None) test now resolves this resource because
    repo_data_profiling declares requires_resources={"zipball_root": ...}."""
    yield "/fake/zipball/root"


@contextmanager
def _fake_git_clone_root(*_args, **_kwargs):
    """Stand-in for _acquire_git_clone_root — no real clone. Any full-run
    (steps=None) test now resolves this resource too, because
    repo_arch_coupling declares requires_resources={"git_clone_root": ...}."""
    yield "/fake/clone/root"


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    registry.add(Project(
        slug="myproj",
        display_name="My Project",
        github_url="https://github.com/test/myproj",
        description="",
    ))
    return "myproj"


def _patch_all_surveyors():
    """Patch every StepInfo.surveyor_cls in STEP_REGISTRY so .run() returns
    [] with no real filesystem/network work, while leaving us able to see
    which ones were actually constructed.

    Patching module-level class names (e.g. patch(".survey_orchestrator.
    HealthSurveyor")) doesn't work post-registry-consolidation — SurveyOrchestrator
    no longer imports these classes itself, and STEP_REGISTRY's StepInfo
    entries already hold direct references to the real class objects
    (captured once, at module-import time). Patching info.surveyor_cls on
    each entry directly is the only thing that actually intercepts
    construction.
    """
    mocks: dict[str, MagicMock] = {}
    patchers = []
    for step_key, info in STEP_REGISTRY.items():
        mock_cls = MagicMock()
        mock_cls.return_value.run.return_value = []
        p = patch.object(info, "surveyor_cls", mock_cls)
        p.start()
        patchers.append(p)
        mocks[step_key] = mock_cls
    # D6: repo_data_profiling now declares requires_resources -- patch the
    # actual zipball-download primitive so a full run doesn't hit the real
    # GitHub API in a unit test.
    zip_patcher = patch(
        "resource_explorer.surveyors.repo_survey_definition_adapter._acquire_zipball_root",
        _fake_zipball_root,
    )
    zip_patcher.start()
    patchers.append(zip_patcher)
    # repo_arch_coupling declares requires_resources={"git_clone_root": ...} —
    # patch the clone primitive too, same reasoning as the zipball one above.
    clone_patcher = patch(
        "resource_explorer.surveyors.repo_survey_definition_adapter._acquire_git_clone_root",
        _fake_git_clone_root,
    )
    clone_patcher.start()
    patchers.append(clone_patcher)
    return mocks, patchers


class TestStepsNone:
    def test_runs_all_ten_surveyors_and_self_logs(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey") as mock_log:
                SurveyOrchestrator(registry).run(project)
                for m in mocks.values():
                    m.return_value.run.assert_called_once()
                mock_log.assert_called_once()
        finally:
            for p in patchers:
                p.stop()

    def test_updates_last_surveyed_at(self, registry, project):
        _mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                assert registry.get(project).last_surveyed_at == ""
                SurveyOrchestrator(registry).run(project)
                assert registry.get(project).last_surveyed_at != ""
        finally:
            for p in patchers:
                p.stop()


class TestStepsFiltered:
    def test_runs_only_named_step_and_does_not_self_log(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey") as mock_log:
                SurveyOrchestrator(registry).run(project, steps=["repo_health"])
                mocks["repo_health"].return_value.run.assert_called_once()
                for key, m in mocks.items():
                    if key != "repo_health":
                        m.return_value.run.assert_not_called()
                mock_log.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_multiple_steps_all_run(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, steps=["repo_language", "repo_file_classification", "repo_file_structure"]
                )
                mocks["repo_language"].return_value.run.assert_called_once()
                mocks["repo_file_classification"].return_value.run.assert_called_once()
                mocks["repo_file_structure"].return_value.run.assert_called_once()
                mocks["repo_health"].return_value.run.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_unknown_step_key_is_silently_ignored(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                result = SurveyOrchestrator(registry).run(project, steps=["not_a_real_step"])
                for m in mocks.values():
                    m.return_value.run.assert_not_called()
                assert result.annotations == []
        finally:
            for p in patchers:
                p.stop()

    def test_step_filtered_run_also_updates_last_surveyed_at(self, registry, project):
        _mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                assert registry.get(project).last_surveyed_at == ""
                SurveyOrchestrator(registry).run(project, steps=["repo_health"])
                assert registry.get(project).last_surveyed_at != ""
        finally:
            for p in patchers:
                p.stop()


class TestScopeLocator:
    """D5/D6 repo scope-narrowing funnel plan — scope_locator is only
    forwarded to surveyors whose StepInfo.accepts_scope_locator is True;
    every other step is constructed exactly as before (no scope_locator
    kwarg at all), regardless of what scope_locator was passed to run()."""

    def test_forwarded_only_to_accepting_step(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, steps=["repo_api_structure", "repo_health"], scope_locator="src",
                )
                # repo_api_structure accepts_scope_locator=True
                _, kwargs = mocks["repo_api_structure"].call_args
                assert kwargs["scope_locator"] == "src"
                # repo_health does not declare accepts_scope_locator — must
                # never receive the kwarg (its constructor doesn't accept it).
                _, kwargs = mocks["repo_health"].call_args
                assert "scope_locator" not in kwargs
        finally:
            for p in patchers:
                p.stop()

    def test_default_scope_locator_is_empty_string(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(project, steps=["repo_api_structure"])
                _, kwargs = mocks["repo_api_structure"].call_args
                assert kwargs["scope_locator"] == ""
        finally:
            for p in patchers:
                p.stop()

    def test_all_four_corpus_shaped_steps_accept_scope_locator(self):
        for key in ("repo_file_size", "repo_api_structure", "repo_data_profiling", "repo_file_classification"):
            assert STEP_REGISTRY[key].accepts_scope_locator is True


class TestFastFlag:
    """A real, confirmed slowness fix: Coarse Scout could block 10+ minutes
    because HealthSurveyor's stats refresh made one GitHub API call per
    commit in the lookback window. fast=True is forwarded only to steps
    whose StepInfo.accepts_fast is True (repo_health today) — every other
    step is constructed exactly as before, no fast kwarg at all."""

    def test_forwarded_only_to_accepting_step(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, steps=["repo_health", "repo_language"], fast=True,
                )
                _, kwargs = mocks["repo_health"].call_args
                assert kwargs["fast"] is True
                # repo_language does not declare accepts_fast — must never
                # receive the kwarg (its constructor doesn't accept it).
                _, kwargs = mocks["repo_language"].call_args
                assert "fast" not in kwargs
        finally:
            for p in patchers:
                p.stop()

    def test_default_fast_is_false(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(project, steps=["repo_health"])
                _, kwargs = mocks["repo_health"].call_args
                assert kwargs["fast"] is False
        finally:
            for p in patchers:
                p.stop()

    def test_which_steps_accept_fast(self):
        """fast skips StatsFetcher's per-commit diff-stats calls. It moved with
        the fetch itself: repo_git_statistics now does the refresh, repo_health
        keeps the flag because its scoring window is the same 90-day history."""
        accepting = {k for k, info in STEP_REGISTRY.items() if info.accepts_fast}
        assert accepting == {"repo_health", "repo_git_statistics"}


class TestCostTierFilter:
    """Step cost tiers plan (docs/step-cost-tiers-plan.md, D5) —
    max_fetch_cost/max_compute_cost narrow step_keys_to_run by ordinal
    position, same set-narrowing shape steps=[...] already has. Both None
    (the default) must run every step, unchanged."""

    def test_both_none_runs_all_21_steps(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(project)
                for key, m in mocks.items():
                    m.return_value.run.assert_called_once()
        finally:
            for p in patchers:
                p.stop()

    def test_max_fetch_cost_none_excludes_every_download_and_api_heavy_step(self, registry, project):
        """Ceiling "none" must exclude the 4 zipball (download) steps and
        every step that makes its own API calls (repo_git_statistics,
        repo_sub_resource_survey) — anything above "none" on the fetch
        axis, regardless of compute_cost."""
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(project, max_fetch_cost="none")
                excluded = {k for k, info in STEP_REGISTRY.items() if info.fetch_cost != "none"}
                assert excluded == {
                    # repo_classification (2026-08-23) — declared the dataclass
                    # default fetch_cost="none" while making a dozen GitHub calls
                    # per repo. The presentation session measured it at 3 repos in
                    # 10 minutes against 1 second for the other three Discovery
                    # steps over 60 repos, and this assertion is the record that
                    # a "none" ceiling now excludes it.
                    "repo_classification",
                    "repo_file_inventory", "repo_homepage", "repo_data_profiling",
                    "repo_symbol_extraction", "repo_rag_ingestion",
                    # repo_website_ingestion (2026-08-20) — fetches the project's
                    # external site over HTTP, so it is not zero-fetch.
                    "repo_website_ingestion",
                    "repo_git_statistics", "repo_sub_resource_survey",
                    # repo_cve_scan (2026-08-26) — one batched call to OSV.dev.
                    # No repo download and nothing fetched about the repo
                    # itself, but still not zero-fetch.
                    "repo_cve_scan",
                    # repo_manifest_parse (2026-08-23) — shares the zipball, but
                    # sharing an extraction does not make a step zero-fetch: the
                    # download still has to happen for it to run at all.
                    "repo_manifest_parse",
                    # repo_arch_lens (2026-08-25) — reads the project's own
                    # architecture document, up to MAX_DOC_FILES GitHub calls and
                    # often against a DIFFERENT repository. It needs no shared
                    # resource (requires_resources={}), which is exactly the trap
                    # repo_classification fell into: an empty resource
                    # declaration is not evidence a step is zero-fetch.
                    "repo_arch_lens",
                    # repo_arch_detect/repo_arch_coupling (Phase 1 plan §4.2) —
                    # a zipball and a real git clone respectively, both downloads.
                    "repo_arch_detect", "repo_arch_coupling",
                }
                for key in excluded:
                    mocks[key].return_value.run.assert_not_called()
                for key, m in mocks.items():
                    if key not in excluded:
                        m.return_value.run.assert_called_once()
        finally:
            for p in patchers:
                p.stop()

    def test_max_compute_cost_low_excludes_medium_and_high_steps(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(project, max_compute_cost="low")
                excluded = {k for k, info in STEP_REGISTRY.items() if info.compute_cost != "low"}
                assert excluded == {
                    "repo_data_profiling", "repo_symbol_extraction", "repo_rag_ingestion",
                    # repo_website_ingestion (2026-08-20) — embeds the project's
                    # external site. medium rather than rag_ingestion's high: one
                    # page, not a whole repo.
                    "repo_website_ingestion",
                    # repo_arch_coupling — classify_subtree/cohesion computation
                    # over the whole import graph, medium not low.
                    "repo_arch_coupling",
                    # repo_manifest_parse is deliberately NOT here: it declares
                    # compute_cost="low" because it measures like
                    # repo_file_inventory (0.0-0.6s across 359-5,763 files), not
                    # like the medium steps. It was "medium" on a guess for a
                    # few hours; see its StepInfo comment for the numbers.
                }
                for key in excluded:
                    mocks[key].return_value.run.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_both_ceilings_combine_as_an_intersection(self, registry, project):
        """max_fetch_cost and max_compute_cost each narrow independently —
        a step must clear both ceilings to run."""
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, max_fetch_cost="none", max_compute_cost="low",
                )
                mocks["repo_health"].return_value.run.assert_called_once()
                for key in (
                    "repo_git_statistics", "repo_rag_ingestion", "repo_data_profiling",
                    "repo_symbol_extraction", "repo_sub_resource_survey",
                ):
                    mocks[key].return_value.run.assert_not_called()
        finally:
            for p in patchers:
                p.stop()

    def test_cost_ceiling_combines_with_explicit_steps_as_an_intersection(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, steps=["repo_health", "repo_rag_ingestion"], max_fetch_cost="none",
                )
                mocks["repo_health"].return_value.run.assert_called_once()
                mocks["repo_rag_ingestion"].return_value.run.assert_not_called()
        finally:
            for p in patchers:
                p.stop()
