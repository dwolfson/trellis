"""Parity slice G2, part 2: a credential override for ONE run (PI-016), the
"try Egeria first" switch (PI-018) and the per-step "answered by" provenance.

The override credential is session memory only: it must never reach the run
queue (which persists its payload in the registry), an activity row, a log line
or a response. Every secret here is an obviously fake value, and each test
greps what was stored, logged and returned for it. No real connection, no
Egeria, temp sqlite registries only.
"""
from __future__ import annotations

import json
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    SurveyDefinitionExecutor,
    register_adapter,
)
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, SurveyStep

FAKE_PW = "test-password-not-real"


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    assert not getattr(r, "is_postgres", False)
    r.register_database(DatabaseEntity(
        slug="mydb", display_name="My DB", db_type="postgresql", host="localhost", port=5432,
        database_name="mydb", db_user="stored_user", db_password="stored-password-not-real"))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


def _everything(registry) -> str:
    rows = registry.list_activity(limit=1000)
    runs = registry.list_runs()
    return json.dumps({"activity": rows, "runs": runs}, default=str)


def _executor_world(registry, *, local_raises=False):
    seen = {}

    def local_runner(entity, reg, **kw):
        seen["local"] = {k: kw.get(k) for k in ("db_user",)}
        if local_raises:
            raise RuntimeError(f"connect failed for password {kw['db_pwd']}")
        return {"ok": True}

    def adaptive(entity, reg, step, **kw):
        seen["adaptive_force_custom"] = kw.get("force_custom")
        return {"status": "ok", "source": "custom" if kw.get("force_custom") else "egeria"}

    def native(entity, reg, step, **kw):
        return {"status": "ok"}

    adapter = ResourceTypeAdapter(
        entity_type="g2fake", technology_type="G2 Fake",
        re_analysis_steps={"local_step": local_runner},
        get_entity=lambda r, slug: type("E", (), {"db_user": "stored_user",
                                                  "db_password": "stored-password-not-real",
                                                  "display_name": slug})(),
        publish=MagicMock(return_value=""),
        other_engine_handlers={"egeria": native, "egeria-adaptive": adaptive},
    )
    register_adapter(adapter)
    sd = SurveyDefinition(
        process_guid="p1", display_name="G2", qualified_name="GovActionProcess::G2",
        supported_technology_type="G2 Fake",
        steps=[
            SurveyStep(guid="a", display_name="Local", qualified_name="Step::Local",
                       executes_at="resource-explorer", re_analysis_step="local_step"),
            SurveyStep(guid="b", display_name="Adaptive", qualified_name="Step::Adaptive",
                       executes_at="egeria-adaptive", re_analysis_step=None),
            SurveyStep(guid="c", display_name="Native", qualified_name="Step::Native",
                       executes_at="egeria", re_analysis_step=None),
        ])
    reader = MagicMock()
    reader.fetch.return_value = sd
    reader.find_candidate_process_guids.return_value = [
        {"guid": "p1", "qualified_name": "GovActionProcess::G2", "display_name": "G2"}]
    return SurveyDefinitionExecutor(registry, reader=reader), seen


# ── provenance: which source answered each step; who a step ran as ──────────

def test_every_step_says_which_source_answered_and_only_local_work_says_ran_as(registry):
    ex, seen = _executor_world(registry)
    res = ex.run("g2fake", "x", db_user="one_off_user", db_pwd=FAKE_PW,
                 credential_scope="this run", engine_override="resource-explorer")
    steps = {s["step"]: s for s in res["steps"]}
    assert steps["Step::Local"]["answered_by"] == "local"
    assert steps["Step::Local"]["ran_as"] == {"user": "one_off_user", "scope": "this run"}
    assert steps["Step::Adaptive"]["answered_by"] == "egeria"           # the handler's own `source`
    assert "ran_as" not in steps["Step::Adaptive"]                      # Egeria's answer used no RE credential
    assert steps["Step::Native"]["answered_by"] == "egeria"
    assert "ran_as" not in steps["Step::Native"]
    assert seen["local"]["db_user"] == "one_off_user"                   # the override was what connected
    assert FAKE_PW not in json.dumps(res)


def test_a_local_scan_inside_the_adaptive_step_ran_as_the_override_user(registry):
    ex, seen = _executor_world(registry)
    res = ex.run("g2fake", "x", db_user="one_off_user", db_pwd=FAKE_PW, credential_scope="this run",
                 force_custom=True, engine_override="resource-explorer")
    adaptive = next(s for s in res["steps"] if s["step"] == "Step::Adaptive")
    assert seen["adaptive_force_custom"] is True
    assert adaptive["answered_by"] == "custom"
    assert adaptive["ran_as"] == {"user": "one_off_user", "scope": "this run"}


def test_a_run_on_the_stored_credential_claims_no_ran_as(registry):
    ex, _ = _executor_world(registry)
    res = ex.run("g2fake", "x")
    assert all("ran_as" not in s for s in res["steps"])
    assert all("answered_by" in s for s in res["steps"])


def test_a_failure_that_echoes_the_password_is_scrubbed_from_rows_result_and_logs(registry, caplog):
    caplog.set_level(logging.DEBUG)
    ex, _ = _executor_world(registry, local_raises=True)
    res = ex.run("g2fake", "x", db_user="one_off_user", db_pwd=FAKE_PW, credential_scope="this run",
                 engine_override="resource-explorer")
    assert res["errors"], "the failure must still be reported"
    assert FAKE_PW not in json.dumps(res)
    assert FAKE_PW not in _everything(registry)
    assert FAKE_PW not in caplog.text
    assert "***" in " ".join(res["errors"])


def test_the_log_filter_is_removed_when_the_run_ends(registry):
    root = logging.getLogger()
    before = [list(h.filters) for h in root.handlers]
    ex, _ = _executor_world(registry)
    ex.run("g2fake", "x", db_user="u", db_pwd=FAKE_PW, credential_scope="this run")
    assert [list(h.filters) for h in root.handlers] == before


# ── the route: an override never reaches the queue ──────────────────────────

def test_an_override_run_is_not_enqueued_and_nothing_stored_carries_the_password(client, registry, caplog):
    caplog.set_level(logging.DEBUG)
    started = threading.Event()
    captured = {}

    def fake_background(entity_type, slug, body, activity_id):
        captured.update(entity_type=entity_type, slug=slug, body=body, activity_id=activity_id)
        started.set()

    with patch("resource_explorer.web.routes.survey_definitions._run_survey_definition_background",
               fake_background):
        r = client.post("/api/survey-definitions/database/mydb/run", json={
            "survey_definition_ref": "GovActionProcess::X", "db_user": "one_off_user", "db_pwd": FAKE_PW})
        assert started.wait(5)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["status"] == "started" and data["run_id"] is None      # not queued: the queue persists its payload
    assert registry.list_runs() == []
    assert data["ran_as"] == {"user": "one_off_user", "scope": "this run"}
    assert FAKE_PW not in r.text
    assert FAKE_PW not in _everything(registry)
    assert FAKE_PW not in caplog.text
    entry = registry.get_activity(data["activity_id"])
    assert entry["status"] == "running"
    assert json.loads(entry["detail"])["ran_as"] == {"user": "one_off_user", "scope": "this run"}
    # the worker thread got the secret in memory, forced to the local engine
    from resource_explorer.web.routes.survey_definitions import _params
    p = _params(captured["body"])
    assert p.db_pwd == FAKE_PW and p.engine_override == "resource-explorer" and p.credential_scope == "this run"


def test_an_override_needs_both_a_user_and_a_password(client, registry):
    r = client.post("/api/survey-definitions/database/mydb/run",
                    json={"survey_definition_ref": "X", "db_pwd": FAKE_PW})
    assert r.status_code == 400
    assert FAKE_PW not in r.text
    assert registry.list_runs() == [] and registry.list_activity(limit=50) == []


def test_a_run_without_an_override_is_still_queued_and_carries_force_custom(client, registry):
    r = client.post("/api/survey-definitions/database/mydb/run",
                    json={"survey_definition_ref": "X", "force_custom": True})
    assert r.status_code == 200
    row = registry.list_runs(state="queued")[0]
    params = json.loads(row["target"])["params"]
    assert params["force_custom"] is True
    assert params["db_pwd"] == "" and params["credential_scope"] == ""


def test_run_definition_passes_force_custom_only_when_asked(registry):
    from resource_explorer.workflows.survey_definition import SurveyDefinitionRunParams, run_definition

    with patch("resource_explorer.surveyors.survey_definition_executor.run_survey_definition",
               return_value={"steps": [], "errors": []}) as run:
        run_definition("database", "mydb", SurveyDefinitionRunParams(survey_definition_ref="X"), registry=registry)
        assert "force_custom" not in run.call_args.kwargs
        run_definition("database", "mydb",
                       SurveyDefinitionRunParams(survey_definition_ref="X", force_custom=True), registry=registry)
        assert run.call_args.kwargs["force_custom"] is True


def test_the_recording_wrapper_scrubs_an_exception_that_echoes_the_password(registry, caplog):
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutorError
    from resource_explorer.workflows.survey_definition import (
        SurveyDefinitionRunParams, execute_and_record_definition)
    from resource_explorer.activity_logger import log_survey

    caplog.set_level(logging.DEBUG)
    aid = log_survey(registry, entity_type="database", entity_slug="mydb", entity_name="mydb",
                     entity_location="", intent="assessment", status="running", summary="Running…")
    params = SurveyDefinitionRunParams(survey_definition_ref="X", db_user="one_off_user", db_pwd=FAKE_PW,
                                       credential_scope="this run")
    with patch("resource_explorer.workflows.survey_definition.run_definition",
               side_effect=SurveyDefinitionExecutorError(f"could not log in with {FAKE_PW}")):
        out = execute_and_record_definition("database", "mydb", params, aid, registry=registry)
    assert out.status == "error"
    assert FAKE_PW not in json.dumps(registry.get_activity(aid), default=str)
    assert FAKE_PW not in out.summary and FAKE_PW not in caplog.text
    detail = json.loads(registry.get_activity(aid)["detail"])
    assert detail["ran_as"] == {"user": "one_off_user", "scope": "this run"}
