"""Tests for SurveyOrchestrator's steps parameter.

Focus: steps=None must keep running every sub-surveyor and self-logging
exactly as before this parameter existed (regression guard); steps=[...]
must run only the named sub-surveyor(s) and must NOT self-log — the caller
(scheduler.py's per-analysis-id dispatch, or repo_survey_definition_adapter.py)
writes its own, more specific activity-log entry for a targeted run, and
self-logging too would double it.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from resource_explorer.registry import Project, ProjectRegistry
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
    """Patch every sub-surveyor class the orchestrator instantiates so
    .run() returns [] with no real filesystem/network work, while leaving
    us able to see which ones were actually constructed."""
    targets = [
        "resource_explorer.surveyors.survey_orchestrator.FileClassifierSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.FileStructureSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.FileSizeSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.DataProfilerSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.LanguageSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.HealthSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.DependencySurveyor",
        "resource_explorer.surveyors.survey_orchestrator.DocumentationSurveyor",
        "resource_explorer.surveyors.survey_orchestrator.SecuritySurveyor",
        "resource_explorer.surveyors.survey_orchestrator.ApiStructureSurveyor",
    ]
    patchers = {t.rsplit(".", 1)[-1]: patch(t) for t in targets}
    mocks = {name: p.start() for name, p in patchers.items()}
    for m in mocks.values():
        m.return_value.run.return_value = []
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
            for p in patchers.values():
                p.stop()

    def test_updates_last_surveyed_at(self, registry, project):
        _mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                assert registry.get(project).last_surveyed_at == ""
                SurveyOrchestrator(registry).run(project)
                assert registry.get(project).last_surveyed_at != ""
        finally:
            for p in patchers.values():
                p.stop()


class TestStepsFiltered:
    def test_runs_only_named_step_and_does_not_self_log(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey") as mock_log:
                SurveyOrchestrator(registry).run(project, steps=["repo_health"])
                mocks["HealthSurveyor"].return_value.run.assert_called_once()
                for name, m in mocks.items():
                    if name != "HealthSurveyor":
                        m.return_value.run.assert_not_called()
                mock_log.assert_not_called()
        finally:
            for p in patchers.values():
                p.stop()

    def test_multiple_steps_all_run(self, registry, project):
        mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                SurveyOrchestrator(registry).run(
                    project, steps=["repo_language", "repo_file_classification", "repo_file_structure"]
                )
                mocks["LanguageSurveyor"].return_value.run.assert_called_once()
                mocks["FileClassifierSurveyor"].return_value.run.assert_called_once()
                mocks["FileStructureSurveyor"].return_value.run.assert_called_once()
                mocks["HealthSurveyor"].return_value.run.assert_not_called()
        finally:
            for p in patchers.values():
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
            for p in patchers.values():
                p.stop()

    def test_step_filtered_run_also_updates_last_surveyed_at(self, registry, project):
        _mocks, patchers = _patch_all_surveyors()
        try:
            with patch("resource_explorer.surveyors.survey_orchestrator.log_survey"):
                assert registry.get(project).last_surveyed_at == ""
                SurveyOrchestrator(registry).run(project, steps=["repo_health"])
                assert registry.get(project).last_surveyed_at != ""
        finally:
            for p in patchers.values():
                p.stop()
