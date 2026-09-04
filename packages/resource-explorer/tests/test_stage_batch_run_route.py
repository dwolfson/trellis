"""Tests for POST /api/projects/{slug}/analyses/stage/{stage}/run — the
"Run all <Stage>" pinned batch action (2026-09-03, direct feedback: "make it
first and separate so a user can easily just select that and be confident
that all the surveys are being run"). Derives its step_keys live from the
catalog's own intent tags (REPO_ANALYSIS_STEP_MAP), not from a fixed Egeria
Survey Definition — see projects.py's run_stage_batch docstring for why.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.add(Project(
        slug="myproj", display_name="My Project",
        github_url="https://github.com/test/myproj",
    ))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


class TestRunStageBatchRoute:
    def test_404_for_unknown_repo(self, client):
        res = client.post("/api/projects/does-not-exist/analyses/stage/scouting/run")
        assert res.status_code == 404

    def test_400_for_stage_with_no_batch_runnable_analyses(self, client):
        # 'enrichment' has zero analysis_catalog entries — no step_keys, no batch.
        res = client.post("/api/projects/myproj/analyses/stage/enrichment/run")
        assert res.status_code == 400

    def test_starts_and_reports_step_and_analysis_counts_for_scouting(self, client):
        # scouting: repository_health (1 step) + language_file_classification
        # (3 steps) — repo_profile_refresh is action:"profile", excluded.
        # _run_stage_batch_background is threaded — patch it out so the test
        # doesn't wait on/depend on a real survey run.
        with patch("resource_explorer.web.routes.projects._run_stage_batch_background"):
            res = client.post("/api/projects/myproj/analyses/stage/scouting/run")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "started"
        assert body["analysis_count"] == 2
        assert body["step_count"] == 4
        assert "activity_id" in body


class TestRunStageBatchBackground:
    """Exercises the background function directly (not through a live
    thread) — same reasoning as test_scouting_overview_routes.py's
    TestRunSingleAnalysisBackground: dispatch logic, not thread plumbing."""

    def test_writes_ok_terminal_status_on_success(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.registry.ProjectRegistry.__init__",
            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
        )
        from resource_explorer.activity_logger import log_analysis_run
        from resource_explorer.web.routes.projects import _run_stage_batch_background

        activity_id = log_analysis_run(
            registry, "repo", "myproj", "My Project", "running",
            "Running…", "__stage_batch__", published=None,
        )
        fake_result = {"annotations": [], "errors": []}
        with patch(
            "resource_explorer.surveyors.repo_survey_definition_adapter._run_batch",
            return_value=fake_result,
        ):
            _run_stage_batch_background("myproj", "scouting", ["repo_health", "repo_language"], activity_id)

        entry = registry.get_activity(activity_id)
        assert entry["status"] == "ok"

    def test_writes_error_terminal_status_when_run_batch_raises(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.registry.ProjectRegistry.__init__",
            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
        )
        from resource_explorer.activity_logger import log_analysis_run
        from resource_explorer.web.routes.projects import _run_stage_batch_background

        activity_id = log_analysis_run(
            registry, "repo", "myproj", "My Project", "running",
            "Running…", "__stage_batch__", published=None,
        )
        with patch(
            "resource_explorer.surveyors.repo_survey_definition_adapter._run_batch",
            side_effect=RuntimeError("boom"),
        ):
            _run_stage_batch_background("myproj", "scouting", ["repo_health"], activity_id)

        entry = registry.get_activity(activity_id)
        assert entry["status"] == "error"
