"""Run-now for schedules, and the cache warm being genuinely best-effort.

Dan, 2026-09-01: "With schedules and Surveys in Automate, seems like there
should be a run now option?" There was not — schedules had GET/POST/DELETE and
`scheduler._run_due()` fires on a timer with no way to trigger one. So a
schedule could only be waited for, and confirming one worked meant watching for
its slot to come round.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app


@pytest.fixture
def client():
    return TestClient(app)


class TestScheduleRunNow:
    def test_it_dispatches_through_the_same_path_the_timer_uses(self, client):
        """Not a second implementation. If "run now" and "ran on schedule" used
        different dispatch they could diverge, and the entire value of this is
        confirming what the SCHEDULE will do."""
        reg = MagicMock()
        reg.get_schedules.return_value = [
            {"analysis_id": "repo_health", "target_kind": "analysis",
             "schedule": "daily", "next_run": "2026-09-02T00:00:00"}]
        with patch("resource_explorer.web.routes.schedules.ProjectRegistry", return_value=reg), \
             patch("resource_explorer.web.routes.schedules._require_resource"), \
             patch("resource_explorer.scheduler._execute",
                   return_value=("kafka", "github", [])) as ex:
            resp = client.post("/api/schedules/repo/kafka/repo_health/run")
        assert resp.status_code == 200, resp.text
        assert ex.called, "must dispatch via scheduler._execute, not a parallel path"
        assert resp.json()["status"] == "ok"

    def test_it_does_not_advance_the_schedule(self, client):
        """An out-of-band run must not move `next_run`.

        Advancing it because someone TESTED the schedule would silently skip the
        next real slot — invisible until an expected run did not happen. The
        response says so explicitly rather than leaving a caller to infer it
        from a 200.
        """
        reg = MagicMock()
        reg.get_schedules.return_value = [
            {"analysis_id": "repo_health", "target_kind": "analysis",
             "schedule": "daily", "next_run": "2026-09-02T00:00:00"}]
        with patch("resource_explorer.web.routes.schedules.ProjectRegistry", return_value=reg), \
             patch("resource_explorer.web.routes.schedules._require_resource"), \
             patch("resource_explorer.scheduler._execute", return_value=("k", "g", [])):
            body = client.post("/api/schedules/repo/kafka/repo_health/run").json()
        assert body["next_run_advanced"] is False
        assert body["next_run"] == "2026-09-02T00:00:00"
        assert not any("update_schedule" in c[0] for c in reg.method_calls), \
            "the schedule row must not be written by a run-now"

    def test_an_unscheduled_analysis_is_404_not_a_silent_run(self, client):
        """This endpoint runs THE SCHEDULE. Running an analysis that has none
        would answer a different question from the one asked, and the error
        names the endpoint that does do that."""
        reg = MagicMock()
        reg.get_schedules.return_value = []
        with patch("resource_explorer.web.routes.schedules.ProjectRegistry", return_value=reg), \
             patch("resource_explorer.web.routes.schedules._require_resource"), \
             patch("resource_explorer.scheduler._execute") as ex:
            resp = client.post("/api/schedules/repo/kafka/nope/run")
        assert resp.status_code == 404
        assert not ex.called, "must not run anything when there is no schedule"
        assert "analyses/nope/run" in resp.json()["detail"]

    def test_errors_from_the_run_reach_the_caller(self, client):
        """Known-negative for the success path: a failing run must NOT return
        ok. A scheduled run that fails writes to the activity log where nobody
        may look; a run someone asked for should tell them."""
        reg = MagicMock()
        reg.get_schedules.return_value = [
            {"analysis_id": "repo_health", "target_kind": "analysis",
             "schedule": "daily", "next_run": ""}]
        with patch("resource_explorer.web.routes.schedules.ProjectRegistry", return_value=reg), \
             patch("resource_explorer.web.routes.schedules._require_resource"), \
             patch("resource_explorer.scheduler._execute",
                   return_value=("k", "g", ["boom"])):
            body = client.post("/api/schedules/repo/kafka/repo_health/run").json()
        assert body["status"] == "completed_with_errors"
        assert body["errors"] == ["boom"]

    def test_a_raising_run_is_a_502_not_a_200(self, client):
        reg = MagicMock()
        reg.get_schedules.return_value = [
            {"analysis_id": "repo_health", "target_kind": "analysis",
             "schedule": "daily", "next_run": ""}]
        with patch("resource_explorer.web.routes.schedules.ProjectRegistry", return_value=reg), \
             patch("resource_explorer.web.routes.schedules._require_resource"), \
             patch("resource_explorer.scheduler._execute", side_effect=RuntimeError("nope")):
            resp = client.post("/api/schedules/repo/kafka/repo_health/run")
        assert resp.status_code == 502
        assert "nope" in resp.json()["detail"]


class TestCacheWarmIsBestEffort:
    """The warm is an optimisation. Every failure mode must be a reason to stop
    warming, never a reason to fail — Egeria is legitimately not up yet when
    this process starts, and a warm that raised would take the server down for
    a performance improvement."""

    def test_an_unreachable_egeria_does_not_raise(self):
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

        r = SurveyDefinitionReader()
        with patch.object(SurveyDefinitionReader, "_resolve_question_guids",
                          side_effect=ConnectionError("platform not up")):
            out = r.warm_question_guid_cache(["Q1", "Q2"])
        assert out["warmed"] == 0
        assert out["skipped"] == "ConnectionError"

    def test_it_actually_warms_when_egeria_answers(self):
        """Known-negative for the test above: a method that always returned
        `warmed: 0` would satisfy it."""
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

        r = SurveyDefinitionReader()
        with patch.object(SurveyDefinitionReader, "_resolve_question_guids",
                          return_value=[("Q1", "guid-1"), ("Q2", None)]):
            out = r.warm_question_guid_cache(["Q1", "Q2"])
        assert out["warmed"] == 2
        # Q2 resolving to None is recorded as checked-but-absent, exactly as the
        # request path would record it. The warm changes WHEN the lookup
        # happens, never WHAT it concludes.
        assert out["resolved"] == 1
