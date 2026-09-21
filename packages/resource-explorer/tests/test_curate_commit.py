"""curate_commit.execute_curation's `publish_asset` step (2026-09-20 freshness
gate) -- pressing Catalogue used to always run
`SurveyOrchestrator(...).run(slug, steps=None)`, a full unconditional
re-survey every time. See curate_commit.py's module docstring for the
project owner's framing this responds to. These tests cover the decision
logic in `_resurvey_plan` plus its wiring into `execute_curation`: only
previously-run, currently-stale analyses are re-surveyed; never-run
analyses are excluded even when technically "stale"; an all-fresh repo
still gets its asset created if one doesn't exist yet; a repo with no run
history at all still gets one full survey (nothing to be selective about
on a genuine first catalogue).
"""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from resource_explorer.activity_logger import log_analysis_run
from resource_explorer.curate_plan import Curations
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.workflows.curate_commit import STEPS, _resurvey_plan, execute_curation


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    r.set_project_context(
        "repo", "p", status="linked",
        egeria_project_guid="proj-guid", egeria_project_qualified_name="Project::p",
    )
    return r


def _seed_run(registry, analysis_id: str, *, status: str = "succeeded", ago_seconds: int = 0):
    """Write one analysis_run activity row, same shape
    log_analysis_run/get_analysis_last_run use -- ts is stamped 'now' by the
    logger, so a fresh run is the default; `ago_seconds` back-dates it in the
    activity_log table directly to simulate a stale one."""
    activity_id = log_analysis_run(
        registry, "repo", "p", "P repo", status, f"ran {analysis_id}", analysis_id,
    )
    if ago_seconds:
        from datetime import datetime, timedelta, timezone
        ts = (datetime.now(timezone.utc) - timedelta(seconds=ago_seconds)).isoformat()
        with registry._conn() as conn:
            conn.execute("UPDATE activity_log SET ts = ? WHERE id = ?", (ts, activity_id))
    return activity_id


def _fake_survey_result(slug="p", n_annotations=0):
    from resource_explorer.surveyors.survey_report import SurveyResult
    result = SurveyResult(resource_slug=slug, project_display_name="P repo",
                          github_url="https://github.com/x/p")
    result.annotations = [MagicMock() for _ in range(n_annotations)]
    return result


def _make_curation(registry, slug="p"):
    return Curations(registry).create(
        "repo", slug, author="peterprofile", selection={}, manifest={}, steps=list(STEPS),
    )["id"]


FRESH_SECONDS = 60  # well inside any reasonable RunsConfig.freshness_seconds
STALE_SECONDS = 60 * 60 * 24 * 365  # a year ago -- stale under any config


class TestResurveyPlan:
    def test_no_history_at_all_runs_full_survey(self, registry):
        steps, note = _resurvey_plan(registry, "p")
        assert steps is None
        assert "no run history" in note

    def test_mixed_stale_fresh_and_never_run_only_returns_stale_steps(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"fresh_one": ["fresh_step"], "stale_one": ["stale_step_a", "stale_step_b"]},
        )
        _seed_run(registry, "fresh_one", ago_seconds=FRESH_SECONDS)
        _seed_run(registry, "stale_one", ago_seconds=STALE_SECONDS)
        # "never_run" has no row at all -- must never appear in the output,
        # even though an analysis with no last-run is trivially "not fresh".

        steps, note = _resurvey_plan(registry, "p")

        assert steps == ["stale_step_a", "stale_step_b"]
        assert "fresh_step" not in (steps or [])
        assert "1 of 2" in note or "1" in note  # 1 fresh, 1 stale, out of 2 with history

    def test_all_fresh_returns_empty_step_list(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"fresh_one": ["fresh_step"]},
        )
        _seed_run(registry, "fresh_one", ago_seconds=FRESH_SECONDS)

        steps, note = _resurvey_plan(registry, "p")

        assert steps == []
        assert "already fresh" in note

    def test_error_last_run_counts_as_history_but_not_fresh(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"flaky": ["flaky_step"]},
        )
        _seed_run(registry, "flaky", status="error", ago_seconds=FRESH_SECONDS)

        steps, note = _resurvey_plan(registry, "p")

        # Recorded moments ago, but an error run is never fresh -- eligible
        # for re-run even though its last attempt failed.
        assert steps == ["flaky_step"]


class TestExecuteCurationPublishAssetStep:
    def test_stale_and_fresh_mix_only_reruns_stale_steps(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"fresh_one": ["fresh_step"], "stale_one": ["stale_step"]},
        )
        _seed_run(registry, "fresh_one", ago_seconds=FRESH_SECONDS)
        _seed_run(registry, "stale_one", ago_seconds=STALE_SECONDS)
        cid = _make_curation(registry)

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub:
            MockOrch.return_value.run.return_value = _fake_survey_result(n_annotations=2)
            MockPub.return_value.publish.return_value = "report-guid-1"
            registry.set_egeria_asset_guid = MagicMock()  # not asserted; publish path may call it
            with patch.object(ProjectRegistry, "get_egeria_asset_guid", return_value="asset-guid-1"):
                rec = execute_curation(registry, cid)

            MockOrch.return_value.run.assert_called_once_with("p", steps=["stale_step"])

        publish_step = next(s for s in rec["steps"] if s["name"] == "publish_asset")
        assert publish_step["state"] == "done"
        assert "stale" in publish_step["detail"]

    def test_all_fresh_with_existing_asset_skips_survey_and_publish(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"fresh_one": ["fresh_step"]},
        )
        _seed_run(registry, "fresh_one", ago_seconds=FRESH_SECONDS)
        cid = _make_curation(registry)

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub, \
             patch.object(ProjectRegistry, "get_egeria_asset_guid", return_value="asset-guid-existing"):
            rec = execute_curation(registry, cid)

            MockOrch.return_value.run.assert_not_called()
            MockPub.return_value.publish.assert_not_called()

        publish_step = next(s for s in rec["steps"] if s["name"] == "publish_asset")
        assert publish_step["state"] == "done"
        assert "asset-guid-existing" in publish_step["detail"]
        assert "already published" in publish_step["detail"]

    def test_all_fresh_without_existing_asset_still_ensures_asset_exists(self, registry, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.surveyors.repo_survey_definition_adapter.REPO_ANALYSIS_SOURCE_STEPS",
            {"fresh_one": ["fresh_step"]},
        )
        _seed_run(registry, "fresh_one", ago_seconds=FRESH_SECONDS)
        cid = _make_curation(registry)

        guid_calls = {"n": 0}

        def fake_get_guid(self, slug):
            # No cached asset guid before publish; publish "creates" one.
            guid_calls["n"] += 1
            return "" if guid_calls["n"] == 1 else "new-asset-guid"

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub, \
             patch.object(ProjectRegistry, "get_egeria_asset_guid", fake_get_guid, create=True):
            MockOrch.return_value.run.return_value = _fake_survey_result(n_annotations=0)
            MockPub.return_value.publish.return_value = "report-guid-empty"

            rec = execute_curation(registry, cid)

            # Nothing was stale, so the survey is called with an EMPTY step
            # list -- not None (that would re-run everything) and not
            # skipped outright (there's no asset yet to skip for).
            MockOrch.return_value.run.assert_called_once_with("p", steps=[])
            MockPub.return_value.publish.assert_called_once()

        publish_step = next(s for s in rec["steps"] if s["name"] == "publish_asset")
        assert publish_step["state"] == "done"
        assert "new-asset-guid" in publish_step["detail"]

    def test_no_run_history_runs_full_survey(self, registry):
        cid = _make_curation(registry)

        with patch("resource_explorer.surveyors.survey_orchestrator.SurveyOrchestrator") as MockOrch, \
             patch("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher") as MockPub, \
             patch.object(ProjectRegistry, "get_egeria_asset_guid", return_value="fresh-asset-guid"):
            MockOrch.return_value.run.return_value = _fake_survey_result(n_annotations=5)
            MockPub.return_value.publish.return_value = "report-guid-full"

            rec = execute_curation(registry, cid)

            MockOrch.return_value.run.assert_called_once_with("p", steps=None)

        publish_step = next(s for s in rec["steps"] if s["name"] == "publish_asset")
        assert publish_step["state"] == "done"
        assert "no run history" in publish_step["detail"] or "first catalogue" in publish_step["detail"]
