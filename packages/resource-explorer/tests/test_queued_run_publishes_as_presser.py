"""A queued run publishes AS the person who pressed it (architect ruling, option a, 2026-10-21).

Only the pyegeria boundary is faked (`create_autospec(AssetMaker, spec_set=True)`); the identity machinery
(`egeria_clients`, `a2a_auth`, `presser_hold`, `run_queue`, the executor) is real, so a regression that makes the
publish act as the service account fails here. Every token and name is invented. A token is a real unsigned-claims JWT
only because RE reads its `exp` the same way (`trellis_auth.egeria_token_expiry`, unverified).
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import jwt
import pytest

from resource_explorer import presser_hold, run_queue
from resource_explorer.a2a_auth import CallerIdentity
from resource_explorer.egeria_clients import (
    Daemon,
    DaemonReason,
    acting_as,
    current_principal,
)
from resource_explorer.presser_hold import SIGN_IN_EXPIRED_WORDS, PresserSignInExpired
from resource_explorer.surveyors import survey_definition_executor as sde
from resource_explorer.surveyors.survey_definition_reader import SurveyDefinition, SurveyStep

PRESSER = "peterprofile"
DAEMON_NAME = "resourceexplorernpa"


def _token(exp_in: float, marker: str = "alpha") -> str:
    return jwt.encode({"sub": PRESSER, "exp": int(time.time() + exp_in), "marker": marker}, "k", algorithm="HS256")


LIVE_TOKEN = _token(3600, "live-session-token")
EXPIRED_TOKEN = _token(-60, "expired-session-token")


@pytest.fixture(autouse=True)
def _clean_hold():
    presser_hold.clear_all()
    yield
    presser_hold.clear_all()


# ── the hold ────────────────────────────────────────────────────────────────

def test_the_token_is_in_no_text_form_of_the_hold():
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    held = presser_hold.take("run-1")
    assert held is not None and held.token == LIVE_TOKEN
    for text in (repr(held), str(held), repr(presser_hold._HOLDER)):
        assert LIVE_TOKEN not in text and "live-session-token" not in text


def test_nothing_is_held_without_a_run_a_person_or_a_token():
    assert presser_hold.hold("", PRESSER, LIVE_TOKEN) is False
    assert presser_hold.hold("run-1", "", LIVE_TOKEN) is False
    assert presser_hold.hold("run-1", PRESSER, None) is False
    assert presser_hold.take("run-1") is None


def test_a_held_session_ends_with_the_run_at_the_tokens_expiry_and_at_the_cap(monkeypatch):
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    presser_hold.release("run-1")
    assert presser_hold.take("run-1") is None
    # the token's own exp bounds the hold (an hour token is not kept for the 2 h cap)
    presser_hold.hold("run-2", PRESSER, _token(30))
    assert presser_hold.take("run-2").expires_at <= time.time() + 31
    # the cap bounds a token with no exp
    monkeypatch.setenv(presser_hold.TTL_ENV, "5")
    presser_hold.hold("run-3", PRESSER, "opaque-token-without-exp")
    assert presser_hold.take("run-3").expires_at <= time.time() + 6
    # a hold past its time is gone
    clock = [1000.0]
    holder = presser_hold._Holder(clock=lambda: clock[0])
    holder.put("r", PRESSER, LIVE_TOKEN, ttl=10)
    clock[0] = 1011.0
    assert holder.take("r") is None


# ── who the publish acts as ─────────────────────────────────────────────────

def _worker_as_daemon(row_requester=PRESSER):
    return acting_as(Daemon(DaemonReason.RUN_QUEUE, requested_by=row_requester))


def test_a_pressed_run_acts_as_the_presser_inside_the_publish_and_as_the_daemon_outside_it():
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    with _worker_as_daemon(), presser_hold.pressed_run("run-1", PRESSER):
        assert current_principal().kind == "daemon"                      # the run's measuring stays the daemon's
        with presser_hold.publishing_as_presser():
            who = current_principal()
            assert (who.kind, who.user_id, who.token, who.is_service_account) == ("caller", PRESSER, LIVE_TOKEN, False)
        assert current_principal().kind == "daemon"                      # and it comes back


def test_a_run_nobody_pressed_publishes_as_the_service_account():
    with _worker_as_daemon(row_requester=None):
        with presser_hold.publishing_as_presser():
            who = current_principal()
        assert who.kind == "daemon" and who.is_service_account and who.token is None


def test_a_pressed_run_with_nothing_held_refuses_before_the_block_runs():
    ran = []
    with _worker_as_daemon(), presser_hold.pressed_run("run-never-held", PRESSER):
        with pytest.raises(PresserSignInExpired) as raised:
            with presser_hold.publishing_as_presser():
                ran.append("wrote")
    assert ran == [] and str(raised.value) == SIGN_IN_EXPIRED_WORDS


def test_an_expired_token_and_another_persons_hold_both_refuse():
    presser_hold._HOLDER.put("run-1", PRESSER, EXPIRED_TOKEN, ttl=3600)
    presser_hold.hold("run-2", "someone_else", LIVE_TOKEN)
    for run_id in ("run-1", "run-2"):
        with _worker_as_daemon(), presser_hold.pressed_run(run_id, PRESSER):
            with pytest.raises(PresserSignInExpired):
                with presser_hold.publishing_as_presser():
                    raise AssertionError("must not run")


def test_the_words_are_the_agreed_sentence():
    assert SIGN_IN_EXPIRED_WORDS == "published: no · your sign-in expired · press Publish on the card"


# ── the executor: the real publish seam ─────────────────────────────────────

def _run_definition(publish, *, hold_for=None):
    """One real `SurveyDefinitionExecutor.run` over a fake 'fake_qid' adapter whose publish is `publish`."""
    adapter = sde.ResourceTypeAdapter(
        entity_type="fake_qid", technology_type="Fake Qid Tech",
        re_analysis_steps={"known_step": MagicMock(return_value={"ok": True})},
        get_entity=lambda registry, slug: object(), publish=publish)
    sde.register_adapter(adapter)
    survey_def = SurveyDefinition(
        process_guid="proc-1", display_name="Fake", qualified_name="GovActionProcess::Fake",
        supported_technology_type="Fake Qid Tech",
        steps=[SurveyStep(guid="s1", display_name="Known", qualified_name="Step::Known",
                          executes_at="resource-explorer", re_analysis_step="known_step")])
    reader = MagicMock()
    reader.fetch.return_value = survey_def
    reader.find_candidate_process_guids.return_value = [
        {"guid": "proc-1", "qualified_name": "GovActionProcess::Fake", "display_name": "Fake"}]
    registry = MagicMock()
    registry.get_survey_definition_guid.return_value = None
    registry.has_assigned_egeria_project.return_value = True
    executor = sde.SurveyDefinitionExecutor(registry, reader=reader)
    return executor.run(entity_type="fake_qid", slug="my-fake")


@pytest.fixture
def no_write_refusal(monkeypatch):
    monkeypatch.setattr("resource_explorer.workflows.curate.person_write_refusal", lambda *a, **k: "")


def test_a_pressed_runs_publish_calls_the_port_under_the_presser_never_the_daemon(no_write_refusal, monkeypatch):
    seen = []

    def publish(entity, outputs, at, registry):
        seen.append(current_principal())
        return "report-guid-1"

    monkeypatch.setattr(presser_hold, "read_published_by", lambda guid: PRESSER)
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    with _worker_as_daemon(), presser_hold.pressed_run("run-1", PRESSER):
        result = _run_definition(publish)
    assert len(seen) == 1
    assert (seen[0].kind, seen[0].user_id, seen[0].token) == ("caller", PRESSER, LIVE_TOKEN)
    assert not seen[0].is_service_account
    assert result["egeria_report_guid"] == "report-guid-1" and result["published"] is True
    assert result["published_as"] == PRESSER


def test_an_automated_run_publishes_as_the_service_account(no_write_refusal, monkeypatch):
    seen = []

    def publish(entity, outputs, at, registry):
        seen.append(current_principal())
        return "report-guid-2"

    monkeypatch.setattr(presser_hold, "read_published_by", lambda guid: DAEMON_NAME)
    with _worker_as_daemon(row_requester=None):                           # scheduled / dispatched: no person, no flag
        result = _run_definition(publish)
    assert len(seen) == 1 and seen[0].kind == "daemon" and seen[0].is_service_account and seen[0].token is None
    assert result["published"] is True and result["published_as"] == DAEMON_NAME


@pytest.mark.parametrize("held", ["nothing", "expired"])
def test_an_expired_or_absent_session_writes_nothing_and_says_so(held, no_write_refusal, monkeypatch):
    calls = []
    monkeypatch.setattr(presser_hold, "read_published_by", lambda guid: calls.append(guid) or "x")
    if held == "expired":
        presser_hold._HOLDER.put("run-1", PRESSER, EXPIRED_TOKEN, ttl=3600)
    with _worker_as_daemon(), presser_hold.pressed_run("run-1", PRESSER):
        result = _run_definition(lambda *a, **k: calls.append("PUBLISHED AS " + current_principal().user_id) or "g")
    assert calls == []                                                    # no publish, as anyone; no read-back either
    assert result["publish_state"] == SIGN_IN_EXPIRED_WORDS
    assert result["published"] is False and result["egeria_report_guid"] == ""
    assert "published_as" not in result
    assert result["errors"] == []                                         # the measuring succeeded; nothing failed


def test_published_as_comes_from_the_read_back_not_from_the_path_the_code_took(no_write_refusal, monkeypatch):
    """The regression this exists to show: a pressed run whose report Egeria says the daemon created."""
    monkeypatch.setattr(presser_hold, "read_published_by", lambda guid: DAEMON_NAME)
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    with _worker_as_daemon(), presser_hold.pressed_run("run-1", PRESSER):
        result = _run_definition(lambda *a, **k: "report-guid-3")
    assert result["published_as"] == DAEMON_NAME                          # shown as it is, so the card shows the fault
    monkeypatch.setattr(presser_hold, "read_published_by", lambda guid: "")
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    with _worker_as_daemon(), presser_hold.pressed_run("run-1", PRESSER):
        unread = _run_definition(lambda *a, **k: "report-guid-3")
    assert "published_as" not in unread                                   # could not tell: said as nothing


# ── the read-back itself ────────────────────────────────────────────────────

def test_the_read_back_is_one_get_by_guid_and_reads_versions_created_by(monkeypatch):
    from pyegeria import AssetMaker

    maker = create_autospec(AssetMaker, instance=True, spec_set=True)
    maker.get_asset_by_guid.return_value = {"elementHeader": {"guid": "g", "versions": {"createdBy": PRESSER}}}
    clients = MagicMock()
    clients.of.return_value = maker
    seen = {}

    def fake_client(identity, *, purpose, view_server=None, platform_url=None, shared=True):
        seen["identity"], seen["purpose"] = identity, purpose
        return clients

    monkeypatch.setattr("resource_explorer.egeria_clients.egeria_client", fake_client)
    with _worker_as_daemon():
        assert presser_hold.read_published_by("g") == PRESSER
    maker.get_asset_by_guid.assert_called_once()
    assert maker.get_asset_by_guid.call_args.args == ("g",)
    clients.of.assert_called_once_with(AssetMaker)
    assert seen["purpose"] == "publish read-back"


def test_the_read_back_says_nothing_when_it_cannot_tell(monkeypatch):
    assert presser_hold.created_by_of({}) == "" and presser_hold.created_by_of(None) == ""
    assert presser_hold.created_by_of({"elementHeader": {"versions": {}}}) == ""
    assert presser_hold.created_by_of({"versions": {"createdBy": "top"}}) == "top"
    monkeypatch.setattr("resource_explorer.egeria_clients.egeria_client",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom " + LIVE_TOKEN)))
    with _worker_as_daemon():
        assert presser_hold.read_published_by("g") == ""
    assert presser_hold.read_published_by("") == ""


# ── the queue ───────────────────────────────────────────────────────────────

def _row(run_id, registry_target):
    return {"id": run_id, "kind": "survey_definition_run", "target": json.dumps(registry_target),
            "requested_by": PRESSER, "result_ref": "", "claimed_by": "w"}


def _stub_execute(monkeypatch, record):
    def fake(entity_type, slug, params, activity_id, *, registry=None):
        record["pressed"] = presser_hold.is_pressed()
        record["principal_in_run"] = current_principal()
        try:
            with presser_hold.publishing_as_presser():
                record["principal_in_publish"] = current_principal()
        except PresserSignInExpired as exc:
            record["expired"] = str(exc)
        from resource_explorer.workflows.survey_definition import SurveyDefinitionRunResult

        return SurveyDefinitionRunResult(status="ok")

    monkeypatch.setattr("resource_explorer.workflows.survey_definition.execute_and_record_definition", fake)


def _params(**kw):
    from resource_explorer.workflows.survey_definition import SurveyDefinitionRunParams

    return SurveyDefinitionRunParams(survey_definition_ref="GovActionProcess::X", started_by_person=PRESSER, **kw).to_dict()


def test_the_queue_runs_a_pressed_row_as_the_presser_at_publish_and_releases_the_hold(monkeypatch):
    record = {}
    _stub_execute(monkeypatch, record)
    registry = MagicMock()
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    outcome = run_queue.execute_run(
        _row("run-1", {"entity_type": "database", "slug": "d", "params": _params(publish_as_presser=True)}), registry)
    assert outcome.state == "succeeded"
    assert record["pressed"] is True
    assert record["principal_in_run"].kind == "daemon"                    # measuring: the queue's daemon, as before
    assert record["principal_in_publish"].kind == "caller" and record["principal_in_publish"].token == LIVE_TOKEN
    assert presser_hold.take("run-1") is None                             # released when the run ended


def test_a_row_claimed_where_nothing_is_held_ends_with_the_expired_words_not_the_daemon(monkeypatch):
    record = {}
    _stub_execute(monkeypatch, record)
    run_queue.execute_run(
        _row("run-elsewhere", {"entity_type": "database", "slug": "d", "params": _params(publish_as_presser=True)}),
        MagicMock())
    assert record["expired"] == SIGN_IN_EXPIRED_WORDS and "principal_in_publish" not in record


def test_a_row_that_is_not_pressed_is_not_touched(monkeypatch):
    record = {}
    _stub_execute(monkeypatch, record)
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    run_queue.execute_run(
        _row("run-1", {"entity_type": "database", "slug": "d", "params": _params(publish_as_presser=False)}),
        MagicMock())
    assert record["pressed"] is False and record["principal_in_publish"].kind == "daemon"


def test_the_hold_is_released_even_when_the_run_crashes(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("handler exploded")

    monkeypatch.setattr("resource_explorer.workflows.survey_definition.execute_and_record_definition", boom)
    presser_hold.hold("run-1", PRESSER, LIVE_TOKEN)
    outcome = run_queue.execute_run(
        _row("run-1", {"entity_type": "database", "slug": "d", "params": _params(publish_as_presser=True)}),
        MagicMock())
    assert outcome.state == "failed" and presser_hold.take("run-1") is None


# ── the press route: the token is held, never stored ────────────────────────

def test_the_press_holds_the_session_and_the_row_carries_no_token(tmp_path, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from resource_explorer.registry import DatabaseEntity, ProjectRegistry

    registry = ProjectRegistry(db_path=str(tmp_path / "press.db"))
    registry.register_database(DatabaseEntity(slug="mydb", display_name="My DB", db_type="postgresql", host="localhost",
                                              port=5432, database_name="mydb"))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setattr(
        "resource_explorer.a2a_auth.caller",
        lambda: CallerIdentity(user_id=PRESSER, egeria_token=LIVE_TOKEN, auth_source="app-jwt", role="user"))
    from resource_explorer.web.app import app

    caplog.set_level(logging.DEBUG)
    resp = TestClient(app).post("/api/survey-definitions/database/mydb/run",
                                json={"survey_definition_ref": "GovActionProcess::Test"})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    held = presser_hold.take(run_id)
    assert held is not None and (held.person, held.token) == (PRESSER, LIVE_TOKEN)
    row = registry.get_run(run_id)
    target = json.loads(row["target"])
    assert target["params"]["publish_as_presser"] is True and target["params"]["started_by_person"] == PRESSER
    # the token (or any piece of it) is in no stored text and no log line
    stored = json.dumps(row, default=str) + json.dumps(registry.get_activity(resp.json()["activity_id"]), default=str)
    for secret in (LIVE_TOKEN, "live-session-token"):
        assert secret not in stored
        assert secret not in caplog.text


def test_a_signed_out_press_is_not_a_pressed_run(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.registry import DatabaseEntity, ProjectRegistry

    registry = ProjectRegistry(db_path=str(tmp_path / "press2.db"))
    registry.register_database(DatabaseEntity(slug="mydb", display_name="My DB", db_type="postgresql", host="localhost",
                                              port=5432, database_name="mydb"))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    from resource_explorer.web.app import app

    resp = TestClient(app).post("/api/survey-definitions/database/mydb/run",
                                json={"survey_definition_ref": "GovActionProcess::Test"})
    assert resp.status_code == 200, resp.text
    run_id = resp.json()["run_id"]
    assert presser_hold.take(run_id) is None
    assert json.loads(registry.get_run(run_id)["target"])["params"]["publish_as_presser"] is False


def test_nothing_in_the_source_writes_the_hold_anywhere_but_memory():
    """The module imports no store, opens no file and has no logger: the token has nowhere to go."""
    import ast

    tree = ast.parse(Path(presser_hold.__file__).read_text())
    imported = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    imported |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    assert not imported & {"sqlite3", "psycopg2", "json", "logging", "pickle", "shelve", "tempfile"}
    called = {getattr(n.func, "id", getattr(n.func, "attr", "")) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    assert not called & {"open", "print", "getLogger", "dump", "dumps"}
