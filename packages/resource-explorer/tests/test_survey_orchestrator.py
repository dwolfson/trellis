"""Tests for SurveyOrchestrator's steps parameter.

Focus: steps=None must keep running every sub-surveyor and self-logging
exactly as before this parameter existed (regression guard); steps=[...]
must run only the named sub-surveyor(s) and must NOT self-log — the caller
(scheduler.py's per-analysis-id dispatch, or repo_survey_definition_adapter.py)
writes its own, more specific activity-log entry for a targeted run, and
self-logging too would double it.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator


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
