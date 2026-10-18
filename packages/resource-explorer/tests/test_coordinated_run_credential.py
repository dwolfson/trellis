"""One-run credential for Egeria-coordinated runs (docs/design-notes/DESIGN-COORDINATED-RUN-CREDENTIAL.md §3).

One test per threat in §3's table, plus the holder's clear paths and one end-to-end run. Only the pyegeria boundary is
faked (test_engine_host_e4's `FakeEgeria`: every client a `create_autospec(<real class>, spec_set=True)`), the
step runner at its connection boundary (an autospec of the real `postgres_operations` runner), and the read-back
port (an autospec of `EgeriaSurveyPort`). Every value here is invented.
"""
from __future__ import annotations

import ast
import json
import logging
import sqlite3
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from resource_explorer import native_survey_run as _nsr
from tests.test_engine_host_case3 import (
    ANALYSIS,
    INSTANCE,
    INSTANCE_2,
    TECH,
    _process_action,
    _views,
    _with_credential,
)
from tests.test_engine_host_case3 import (
    PASSWORD as STORED_PASSWORD,
)
from tests.test_engine_host_e4 import (  # noqa: F401 - fixtures and helpers reused
    DB_GUID,
    _rows,
    _run_queue_once,
    _sweep,
    egeria,
    no_connection,
    reg,
)

#: The real start path, bound before any test replaces it, so each route test autospecs the real signature.
_REAL_SUBMIT = _nsr.submit_native_survey
_REAL_IDENTITY_FROM_CLAIMS = __import__("resource_explorer.auth", fromlist=["identity_from_claims"]).identity_from_claims
_REAL_REGISTRY_INIT = __import__("resource_explorer.registry", fromlist=["ProjectRegistry"]).ProjectRegistry.__init__
PKG = Path(__file__).resolve().parent.parent
SRC = PKG / "resource_explorer"
#: Invented. Shorter than 8 characters on purpose: RE redacts a STORED password only from 8 characters, so this proves
#: the one-run scope reaches the redaction (any length), and it has no shape `scrub_text` would recognise.
ONE_RUN_USER = "elevated_reader"
ONE_RUN_PASSWORD = "Zq7#wK!"
STARTER = "dan"


@pytest.fixture(autouse=True)
def _empty_holder(monkeypatch):
    """A fresh holder per test, on a clock the test can move."""
    from resource_explorer import run_credential_holder as h

    clock = {"now": 1000.0}
    monkeypatch.setattr(h, "_HOLDER", h._Holder(clock=lambda: clock["now"]))
    monkeypatch.delenv(h.TTL_ENV, raising=False)
    return clock


@pytest.fixture
def runner(monkeypatch):
    """`postgres_operations`' runner at its connection boundary: an autospec of the real one (the signature is
    bound), returning the shape the real runner returns. Records what it was handed."""
    from resource_explorer.surveyors.database import survey_definition_adapter as db

    real = db._ADAPTER.re_analysis_steps["postgres_operations"]
    fake = create_autospec(real, spec_set=True, return_value={
        "schema_info": {}, "operations": {"privilege_audit": None, "db_activity_signals": None, "db_resilience": None,
                                          "db_external_dependencies": None}})
    monkeypatch.setitem(db._ADAPTER.re_analysis_steps, "postgres_operations", fake)
    return fake


def _creds_handed(fake) -> list[tuple[str, str]]:
    return [(c.kwargs.get("db_user", ""), c.kwargs.get("db_pwd", "")) for c in fake.call_args_list]


def _start_with_credential(reg, egeria) -> str:
    """The coordinated start path (`submit_native_survey`, what the route calls) with a one-run credential."""
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.native_survey_run import port_session, submit_native_survey

    egeria.declared.add(ANALYSIS)
    egeria.assets.add(DB_GUID)
    with port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port:
        state = submit_native_survey(reg, port, "database", "coco_pharma", ANALYSIS, technology_type=TECH,
                                     submitted_by=STARTER, run_credential=(ONE_RUN_USER, ONE_RUN_PASSWORD))
    return state["engine_action_guid"]


def _marker_row(reg, instance: str, *, marker: bool = True) -> dict:
    from resource_explorer import mixed_process

    extra = mixed_process.expected_steps_record(ANALYSIS)
    if marker:
        extra["run_credential"] = {"user": ONE_RUN_USER, "scope": "this run"}
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-18T09:00:00", engine_action_guid=instance, submitted_by=STARTER,
        started_as="process", started_by="egeria", started_in="re", declared_extra=extra)
    return next(r for r in reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
                if r["engine_action_guid"] == instance)


def _all_rows_json(reg) -> str:
    """The JSON of every row of every table in the test registry."""
    path = reg.database_url.split("sqlite:///", 1)[-1] if "sqlite:///" in reg.database_url else reg.database_url
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        dump = {t: [dict(r) for r in conn.execute(f'SELECT * FROM "{t}"')] for t in tables}
    finally:
        conn.close()
    return json.dumps(dump, default=str)


def _port(views):
    """The read-back boundary: an autospec of the real port RE uses, answering the instance's engine actions."""
    from resource_explorer import catalog_and_survey as cas

    port = create_autospec(cas.PyegeriaRegistrationPort, spec_set=True, instance=True)
    port.read_process_run.return_value = views
    return port


# ── threat: leak via logs, exception text or proof rows ──────────────────────────────────────────────────────

def test_a_step_that_raises_with_the_password_leaves_no_trace_in_logs_rows_or_egeria(reg, egeria, no_connection,
                                                                                    runner, caplog):
    _with_credential(reg)
    instance = _start_with_credential(reg, egeria)
    runner.side_effect = RuntimeError(f"FATAL: could not log in as {ONE_RUN_USER} using {ONE_RUN_PASSWORD} "
                                      f"(echo {ONE_RUN_PASSWORD!r})")
    _process_action(egeria, "ea-leak", "postgres_operations", instance=instance, next_guards=())
    caplog.set_level(logging.DEBUG)
    assert _sweep(reg).claimed == ["ea-leak"]
    assert _run_queue_once(reg) is not None

    assert _creds_handed(runner) == [(ONE_RUN_USER, ONE_RUN_PASSWORD)]     # it did run with it, and it raised
    [row] = _rows(reg)
    assert row["target"]["outcome"]["guard"] == "survey-failed", row["target"]["outcome"]
    assert "***" in row["target"]["outcome"]["message"]                    # the words are kept, the secret masked
    everything = _all_rows_json(reg)                                       # runs.target, step_runs.declared, activity
    for form in (ONE_RUN_PASSWORD, json.dumps(ONE_RUN_PASSWORD)[1:-1], repr(ONE_RUN_PASSWORD)[1:-1]):
        assert form not in everything
        assert form not in caplog.text
        assert all(form not in (r.getMessage() + (r.exc_text or "")) for r in caplog.records)
        assert form not in json.dumps(egeria.actions, default=str)        # the completion Egeria was told
        assert form not in json.dumps(egeria.target_statuses, default=str)
    assert STORED_PASSWORD not in everything


def test_an_error_raised_around_the_step_runner_is_masked_before_it_is_stored_or_sent(reg, egeria, no_connection,
                                                                                    runner, monkeypatch, caplog):
    """The executor itself raises (not the step): the engine host's own words (`_short`) carry the exception text,
    and the outcome is masked before it is stored on the run row or told to Egeria."""
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutor

    _with_credential(reg)
    instance = _start_with_credential(reg, egeria)
    boom = create_autospec(SurveyDefinitionExecutor.run_synthetic_step, side_effect=RuntimeError(
        f"adapter could not open a session for {ONE_RUN_USER}/{ONE_RUN_PASSWORD}"))
    monkeypatch.setattr(SurveyDefinitionExecutor, "run_synthetic_step", boom)
    _process_action(egeria, "ea-boom", "postgres_operations", instance=instance, next_guards=())
    caplog.set_level(logging.DEBUG)
    _sweep(reg)
    _run_queue_once(reg)

    assert boom.call_args.kwargs["db_pwd"] == ONE_RUN_PASSWORD           # it was handed the one-run credential
    [row] = _rows(reg)
    assert "could not run" in row["target"]["outcome"]["message"]
    assert ONE_RUN_PASSWORD not in _all_rows_json(reg)
    assert ONE_RUN_PASSWORD not in json.dumps(egeria.actions, default=str)
    assert ONE_RUN_PASSWORD not in caplog.text


def test_the_holder_never_formats_the_password():
    from resource_explorer import run_credential_holder as h

    h.put("inst-repr", ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    held = h.take("inst-repr")
    for text in (repr(held), str(held), f"{held}", repr(h._HOLDER), str(h._HOLDER), repr(held.ran_as())):
        assert ONE_RUN_PASSWORD not in text
    assert held.ran_as() == {"user": ONE_RUN_USER, "scope": "this run"}


# ── threat: reuse after the run (each clear path) ────────────────────────────────────────────────────────────

def test_the_holder_is_cleared_when_the_run_line_says_the_run_is_over(reg):
    from resource_explorer import mixed_process
    from resource_explorer import native_survey_run as nsr
    from resource_explorer import run_credential_holder as h

    plan = [st.request_type for st in mixed_process.definition_process(ANALYSIS).steps[:2]]
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-18T09:00:00", engine_action_guid=INSTANCE, submitted_by=STARTER,
        started_as="process", started_by="egeria", started_in="re",
        declared_extra={"expected_steps": plan, "run_credential": {"user": ONE_RUN_USER, "scope": "this run"}})
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)

    # one of two steps done: still running, still held
    going = nsr.refresh_mixed_run(reg, _port(_views(1)), run, entity_type="database", slug="coco_pharma")
    assert going["state"] == "running" and h.take(INSTANCE) is not None
    # both done: the run line's own derivation says complete, and the holder is cleared
    done = nsr.refresh_mixed_run(reg, _port(_views(2)), run, entity_type="database", slug="coco_pharma")
    assert done["state"] == "complete" and h.take(INSTANCE) is None


def test_a_failed_or_cancelled_run_clears_it_too(reg):
    from resource_explorer import mixed_process
    from resource_explorer import native_survey_run as nsr
    from resource_explorer import run_credential_holder as h

    plan = [st.request_type for st in mixed_process.definition_process(ANALYSIS).steps[:2]]
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-18T09:00:00", engine_action_guid=INSTANCE, submitted_by=STARTER,
        started_as="process", started_by="egeria", started_in="re", declared_extra={"expected_steps": plan})
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    views = _views(1)
    views[0].status = "CANCELLED"
    out = nsr.refresh_mixed_run(reg, _port(views), run, entity_type="database", slug="coco_pharma")
    assert out.get("cancelled") is True and h.take(INSTANCE) is None


def test_cancel_run_clears_it_as_soon_as_egeria_accepts(reg):
    from resource_explorer import mixed_process
    from resource_explorer import native_survey_run as nsr
    from resource_explorer import run_credential_holder as h

    plan = [st.request_type for st in mixed_process.definition_process(ANALYSIS).steps[:2]]
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-18T09:00:00", engine_action_guid=INSTANCE, submitted_by=STARTER,
        started_as="process", started_by="egeria", started_in="re", declared_extra={"expected_steps": plan})
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    views = _views(1)
    views[0].status = "IN_PROGRESS"                    # Egeria accepted; its read-back does not show CANCELLED yet
    port = _port(views)
    out = nsr.cancel_process_run(reg, port, "database", "coco_pharma", run, by=STARTER)
    assert out["accepted"] is True and out["cancelled"] is False
    port.cancel_process_run.assert_called_once_with(INSTANCE)
    assert h.take(INSTANCE) is None


def test_a_cancel_egeria_did_not_accept_leaves_it_for_the_steps_still_to_run(reg):
    from resource_explorer import mixed_process
    from resource_explorer import native_survey_run as nsr
    from resource_explorer import run_credential_holder as h

    plan = [st.request_type for st in mixed_process.definition_process(ANALYSIS).steps[:2]]
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-18T09:00:00", engine_action_guid=INSTANCE, submitted_by=STARTER,
        started_as="process", started_by="egeria", started_in="re", declared_extra={"expected_steps": plan})
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    views = _views(1)
    views[0].status = "IN_PROGRESS"
    port = _port(views)
    port.cancel_process_run.side_effect = ConnectionError("no route to host")
    out = nsr.cancel_process_run(reg, port, "database", "coco_pharma", run, by=STARTER)
    assert out["accepted"] is False and h.take(INSTANCE) is not None


def test_the_ttl_ends_it_two_hours_from_the_start_and_is_never_unbounded(_empty_holder, monkeypatch):
    from resource_explorer import run_credential_holder as h

    clock = _empty_holder
    h.put("inst-ttl", ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    clock["now"] += 7199
    assert h.take("inst-ttl") is not None
    clock["now"] += 1
    assert h.take("inst-ttl") is None
    # configurable, and a value that is not a finite positive number is the default, never "forever"
    for raw, want in (("60", 60.0), ("0", 7200.0), ("-5", 7200.0), ("inf", 7200.0), ("nan", 7200.0),
                      ("soon", 7200.0), ("", 7200.0)):
        monkeypatch.setenv(h.TTL_ENV, raw)
        assert h.configured_ttl() == want, raw
    with pytest.raises(ValueError):
        h.put("inst-forever", ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER, ttl=float("inf"))


def test_process_exit_clears_it():
    from resource_explorer import run_credential_holder as h

    h.put("inst-exit", ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    h._at_exit()
    assert h.take("inst-exit") is None
    tree = ast.parse((SRC / "run_credential_holder.py").read_text())
    registered = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "register" and getattr(n.func.value, "id", "") == "atexit"]
    assert [getattr(c.args[0], "id", "") for c in registered] == ["_at_exit"]


# ── threat: pick-up by a concurrent run on the same database ─────────────────────────────────────────────────

def test_two_instances_on_one_database_each_step_uses_its_own_credential(reg, egeria, no_connection, runner):
    from resource_explorer import run_credential_holder as h

    _with_credential(reg)
    _marker_row(reg, INSTANCE)
    _marker_row(reg, INSTANCE_2, marker=False)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    _process_action(egeria, "ea-with", "postgres_operations", instance=INSTANCE, next_guards=())
    _process_action(egeria, "ea-without", "postgres_operations", instance=INSTANCE_2, next_guards=())
    assert sorted(_sweep(reg).claimed) == ["ea-with", "ea-without"]
    _run_queue_once(reg)
    _run_queue_once(reg)

    assert sorted(_creds_handed(runner)) == sorted([(ONE_RUN_USER, ONE_RUN_PASSWORD), ("egeria_user", STORED_PASSWORD)])
    by_action = {r["target"]["engine_action_guid"]: r["target"]["outcome"] for r in _rows(reg)}
    assert by_action["ea-with"]["ran_as"] == {"user": ONE_RUN_USER, "scope": "this run"}
    assert "ran_as" not in by_action["ea-without"]
    # the instance-2 run never says it ran as the elevated login
    other = next(r for r in reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
                 if r["engine_action_guid"] == INSTANCE_2)
    assert "ran_as" not in json.loads(other["declared"])


# ── threat: silent fallback after a restart ──────────────────────────────────────────────────────────────────

def test_after_a_restart_a_step_of_a_run_that_asked_for_one_is_refused_and_never_uses_the_stored_login(
        reg, egeria, no_connection, runner):
    _with_credential(reg)
    _marker_row(reg, INSTANCE)                    # the start recorded the marker; the holder is empty (restarted)
    _process_action(egeria, "ea-after", "postgres_operations", instance=INSTANCE, next_guards=())
    assert _sweep(reg).claimed == ["ea-after"]
    _run_queue_once(reg)

    runner.assert_not_called()                    # neither the stored login nor anything else
    done = egeria.actions["ea-after"]["completion"]
    assert done["status"] == "INVALID"
    assert "the one-run credential was lost when Resource Explorer restarted; re-run with options" in done["message"]
    [row] = _rows(reg)
    assert row["target"]["outcome"]["guard"] == "survey-invalid"
    assert STORED_PASSWORD not in _all_rows_json(reg)


def test_a_run_that_never_asked_for_one_still_uses_the_stored_login(reg, egeria, no_connection, runner):
    _with_credential(reg)
    _marker_row(reg, INSTANCE, marker=False)
    _process_action(egeria, "ea-plain", "postgres_operations", instance=INSTANCE, next_guards=())
    _sweep(reg)
    _run_queue_once(reg)
    assert _creds_handed(runner) == [("egeria_user", STORED_PASSWORD)]


def test_an_unreadable_marker_is_refused_never_guessed(reg, monkeypatch):
    from resource_explorer import engine_host

    monkeypatch.setattr(reg, "list_native_survey_runs", create_autospec(reg.list_native_survey_runs,
                                                                         side_effect=OSError("registry gone")))
    held, refusal = engine_host._one_run_credential(reg, {"request_type": "re-postgres-operations",
                                                         "process_instance_guid": INSTANCE, "slug": "coco_pharma",
                                                         "definition": ANALYSIS})
    assert held is None and refusal.startswith(engine_host.RUN_CREDENTIAL_UNKNOWN_SENTENCE)


# ── threat: applied to a native Egeria step ──────────────────────────────────────────────────────────────────

def test_a_native_step_never_reads_the_holder(reg, monkeypatch, runner, no_connection):
    from resource_explorer import engine_host
    from resource_explorer import run_credential_holder as h

    _with_credential(reg)
    h.put(INSTANCE, ONE_RUN_USER, ONE_RUN_PASSWORD, STARTER)
    spy = create_autospec(h.take, side_effect=h.take)
    monkeypatch.setattr(h, "take", spy)
    target = {"slug": "coco_pharma", "step_key": "postgres_operations", "request_type": "survey-postgres-database",
              "process_instance_guid": INSTANCE, "definition": ANALYSIS, "engine_action_guid": "ea-native",
              "asset_guid": DB_GUID}
    assert engine_host._one_run_credential(reg, target) == (None, "")
    engine_host._decide_one(reg, target)
    spy.assert_not_called()
    assert _creds_handed(runner) == [("egeria_user", STORED_PASSWORD)]
    # and the run line says, per step, that a step Egeria runs itself uses the stored credential
    from resource_explorer import native_survey_run as nsr

    row = {"engine_action_guid": INSTANCE, "executor_ref": ANALYSIS, "declared": json.dumps({
        "run_credential": {"user": ONE_RUN_USER, "scope": "this run"},
        "expected_steps": ["survey-postgres-database", "re-db-derived"]})}
    assert nsr.derive_mixed_state(row)["native_steps"] == [1]


# ── threat: someone else supplies or reads it ────────────────────────────────────────────────────────────────

_ALLOWED = {"put", "take", "clear", "SCOPE", "RunCredential", "configured_ttl", "TTL_ENV", "DEFAULT_TTL_SECONDS"}


def test_nothing_lists_or_reads_the_holder_but_take_and_only_the_engine_host_takes():
    # The module's surface: no listing, no iteration, no membership, no route.
    tree = ast.parse((SRC / "run_credential_holder.py").read_text())
    holder = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "_Holder")
    methods = {n.name for n in holder.body if isinstance(n, ast.FunctionDef)}
    assert methods == {"__init__", "__repr__", "_expire", "put", "take", "clear", "_clear_all"}, methods
    public = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and not n.name.startswith("_")}
    assert public == {"configured_ttl", "RunCredential", "put", "take", "clear"}, public

    # Every other module: only the three functions and the constants; `take` only in the engine host; `put` only in
    # the coordinated start path; never the private holder; no route reads it.
    uses: dict[str, set[str]] = {}
    for path in SRC.rglob("*.py"):
        if path.name == "run_credential_holder.py":
            continue
        text = path.read_text()
        if "run_credential_holder" not in text:
            continue
        mod = ast.parse(text)
        names: set[str] = set()
        for node in ast.walk(mod):
            if isinstance(node, ast.ImportFrom) and node.module == "resource_explorer.run_credential_holder":
                names |= {a.name for a in node.names}
            elif isinstance(node, ast.Attribute) and getattr(node.value, "id", "") == "run_credential_holder":
                names.add(node.attr)
        uses[str(path.relative_to(SRC))] = names
    assert all(names <= _ALLOWED for names in uses.values()), uses
    assert {p for p, n in uses.items() if "take" in n} == {"engine_host.py"}, uses
    assert {p for p, n in uses.items() if "put" in n} == {"native_survey_run.py"}, uses
    assert all(not ({"put", "take", "clear"} & n) for p, n in uses.items() if p.startswith("web/")), uses


def _start_route(monkeypatch, *, who: str | None, user: str = ONE_RUN_USER, pwd: str = ONE_RUN_PASSWORD,
                 daemon: bool = False):
    """POST the coordinated start with a credential, as `who` (None: nobody signed in). The start path itself is an
    autospec of the real `submit_native_survey`, so the route's gate is all that is under test here."""
    from fastapi.testclient import TestClient

    from resource_explorer import native_survey_run as nsr
    from resource_explorer.registry import DatabaseEntity, ProjectRegistry

    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": who or "", "egeria_token": "tok", "role": "user"})
    monkeypatch.setattr("resource_explorer.auth.identity_from_claims",
                        lambda c: _REAL_IDENTITY_FROM_CLAIMS(c) if who else None)
    monkeypatch.setattr("resource_explorer.egeria_clients.is_daemon_user", lambda u: daemon and bool(u))
    from tests.zone_fakes import open_access

    open_access(monkeypatch)
    submit = create_autospec(_REAL_SUBMIT, spec_set=True,
                             return_value={"engine_action_guid": "pi-9", "state": "submitted"})
    monkeypatch.setattr(nsr, "submit_native_survey", submit)
    monkeypatch.setattr(nsr, "native_survey_rows", lambda *a, **k: [])
    monkeypatch.setattr("resource_explorer.web.routes.native_surveys._port", lambda: object())
    monkeypatch.setattr(nsr, "port_session", lambda p: __import__("contextlib").nullcontext(p))
    import tempfile

    db = ProjectRegistry.__new__(ProjectRegistry)
    _REAL_REGISTRY_INIT(db, db_path=str(Path(tempfile.mkdtemp()) / "route.db"))
    db.register_database(DatabaseEntity(slug="coco_pharma", display_name="coco_pharma", db_type="postgresql",
                                        host="localhost", port=5442, database_name="coco_pharma",
                                        egeria_asset_guid=DB_GUID))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", db.__dict__) or None)
    from resource_explorer.web.app import app

    resp = TestClient(app).post("/api/native-surveys/database/coco_pharma/run",
                                json={"process_qualified_name": ANALYSIS, "db_user": user, "db_pwd": pwd})
    return resp, submit, db


def test_only_the_signed_in_starter_can_supply_one(monkeypatch):
    resp, submit, _ = _start_route(monkeypatch, who=None)
    assert resp.status_code == 401 and submit.call_count == 0
    resp, submit, _ = _start_route(monkeypatch, who="re-daemon", daemon=True)
    assert resp.status_code == 403 and submit.call_count == 0
    resp, submit, _ = _start_route(monkeypatch, who=STARTER, pwd="")
    assert resp.status_code == 400 and submit.call_count == 0
    assert ONE_RUN_PASSWORD not in resp.text


def test_the_route_gate_itself_refuses_res_own_service_account(monkeypatch):
    """Sign-in already refuses RE's daemon account (the 403 above comes from there); the start route's own gate refuses
    it too, so a daemon identity that reached the route by another door still cannot supply a credential."""
    from fastapi import HTTPException

    from resource_explorer.web.routes import native_surveys as route
    from tests.zone_fakes import signed_in

    monkeypatch.setattr("resource_explorer.egeria_clients.is_daemon_user", lambda u: u == "re-daemon")
    monkeypatch.setattr("resource_explorer.egeria_clients._token_expiry", lambda token: None)
    from resource_explorer.a2a_auth import current_caller

    token = signed_in("re-daemon")
    try:
        body = route.RunRequest(process_qualified_name=ANALYSIS, db_user=ONE_RUN_USER, db_pwd=ONE_RUN_PASSWORD)
        with pytest.raises(HTTPException) as refused:
            route._run_credential(body, "re-daemon")
        assert refused.value.status_code == 403
        assert route._run_credential(body, STARTER) == (ONE_RUN_USER, ONE_RUN_PASSWORD)
        assert route._run_credential(route.RunRequest(process_qualified_name=ANALYSIS), STARTER) is None
        assert ONE_RUN_PASSWORD not in repr(body)
    finally:
        current_caller.reset(token)


def test_the_start_route_passes_it_down_as_the_signed_in_person_and_logs_no_secret(monkeypatch):
    resp, submit, db = _start_route(monkeypatch, who=STARTER)
    assert resp.status_code == 200, resp.text
    kwargs = submit.call_args.kwargs
    assert kwargs["submitted_by"] == STARTER and kwargs["run_credential"] == (ONE_RUN_USER, ONE_RUN_PASSWORD)
    assert ONE_RUN_PASSWORD not in resp.text
    everything = _all_rows_json(db)
    assert ONE_RUN_PASSWORD not in everything
    with db._conn() as conn:
        details = [json.loads(dict(r)["detail"] or "{}") for r in conn.execute("SELECT detail FROM activity_log").fetchall()]
    assert {"user": ONE_RUN_USER, "scope": "this run"} in [d.get("run_credential") for d in details], details


def test_a_credential_is_offered_only_for_a_coordinated_re_definition(reg, egeria):
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.native_survey_run import (
        NativeSurveyCannotRun,
        port_session,
        submit_native_survey,
    )

    egeria.assets.add(DB_GUID)
    with port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port:
        with pytest.raises(NativeSurveyCannotRun):
            submit_native_survey(reg, port, "database", "coco_pharma", "ResourceExplorerSurvey::re-db-derived",
                                 technology_type=TECH, submitted_by=STARTER,
                                 run_credential=(ONE_RUN_USER, ONE_RUN_PASSWORD))
        egeria.declared.add(ANALYSIS)
        with pytest.raises(NativeSurveyCannotRun):           # nobody signed in started it
            submit_native_survey(reg, port, "database", "coco_pharma", ANALYSIS, technology_type=TECH,
                                 submitted_by="", run_credential=(ONE_RUN_USER, ONE_RUN_PASSWORD))
    assert egeria.process_starts == []


def test_a_failed_start_holds_nothing(reg, egeria, monkeypatch):
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer import run_credential_holder as h
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.native_survey_run import NativeSurveyError, port_session, submit_native_survey

    egeria.declared.add(ANALYSIS)
    egeria.assets.add(DB_GUID)

    def refuse(*a, **k):
        raise RuntimeError("Egeria said no")

    egeria._start_process = refuse
    put = create_autospec(h.put, side_effect=h.put)
    monkeypatch.setattr(h, "put", put)
    with port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port, \
            pytest.raises(NativeSurveyError):
        submit_native_survey(reg, port, "database", "coco_pharma", ANALYSIS, technology_type=TECH,
                             submitted_by=STARTER, run_credential=(ONE_RUN_USER, ONE_RUN_PASSWORD))
    put.assert_not_called()


# ── end to end ───────────────────────────────────────────────────────────────────────────────────────────────

def test_start_with_a_credential_then_claim_then_the_step_runs_with_it_and_the_run_line_says_so(
        reg, egeria, no_connection, runner):
    from resource_explorer import native_survey_run as nsr
    from resource_explorer import run_credential_holder as h

    _with_credential(reg)
    instance = _start_with_credential(reg, egeria)
    assert h.take(instance) is not None
    [row] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    declared = json.loads(row["declared"])
    assert declared["run_credential"] == {"user": ONE_RUN_USER, "scope": "this run"}
    assert nsr.derive_mixed_state(row)["ran_as"] is None              # asked for, not yet used: no "ran as"

    _process_action(egeria, "ea-e2e", "postgres_operations", instance=instance, next_guards=())
    assert _sweep(reg).claimed == ["ea-e2e"]
    _run_queue_once(reg)

    assert _creds_handed(runner) == [(ONE_RUN_USER, ONE_RUN_PASSWORD)]
    assert egeria.actions["ea-e2e"]["completion"]["status"] == "ACTIONED"
    [run_row] = _rows(reg)
    assert run_row["target"]["outcome"]["ran_as"] == {"user": ONE_RUN_USER, "scope": "this run"}
    [row] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    derived = nsr.derive_mixed_state(row)
    assert derived["ran_as"] == {"user": ONE_RUN_USER, "scope": "this run"}
    assert derived["run_credential"] == {"user": ONE_RUN_USER, "scope": "this run"}
    assert derived["native_steps"] == [] and derived["credential_lost"] is False
    # the row the page draws carries it (the words are the page's: RUN_CREDENTIAL_WORDS.ranAs)
    listed = next(r for r in nsr.native_survey_rows(reg, "database", "coco_pharma", TECH)
                  if r["qualified_name"] == ANALYSIS)
    assert listed["run"]["ran_as"] == {"user": ONE_RUN_USER, "scope": "this run"}
    everything = _all_rows_json(reg)
    assert ONE_RUN_PASSWORD not in everything and STORED_PASSWORD not in everything
