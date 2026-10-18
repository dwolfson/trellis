"""RE's engine host on the Governance Engine view service (DESIGN-ENGINE-HOST-GOVERNANCE-ENGINE-API.md, §3).

Only the pyegeria client boundary is faked, with test_engine_host_e4's `FakeEgeria`: every client RE builds goes through
`egeria_clients._build`, which returns `create_autospec(<real class>, spec_set=True, instance=True)`, so a call binds
the INSTALLED pyegeria signature; the fake's Governance Engine answers as Egeria does (the approved listing holds only
the engine's APPROVED, unclaimed actions; an action target status is keyed on the ActionTarget relationship GUID), and
its Automated Curation refuses the deprecated engine-action wrappers outright. Everything between the sweep and the
client is real: the sweep, the queue, the synthetic-step executor, the publisher, the routes and the read-back.

§3 tests 1-5, plus the owner's Q1 (relationship GUID, never the element's), Q2 (Cancel for the starter and admins only)
and Q3 (no Cancel for a run RE did not start). Test 6 (the live read-only probe) is recorded in the builder's handoff.
"""
from __future__ import annotations

import ast
import inspect
import json
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tests.test_engine_host_case3 import ANALYSIS, INSTANCE, TECH, _process_action
from tests.test_engine_host_e4 import (  # noqa: F401 - fixtures and helpers reused
    DB_GUID,
    ENGINE_GUID,
    UNKNOWN_GUID,
    _daemon_user,
    _host,
    _rel_guid,
    _restart,
    _row,
    _rows,
    _run_queue_once,
    _sweep,
    egeria,
    no_connection,
    reg,
)

OTHER_ENGINE_GUID = "0a1b2c3d-0000-4000-8000-00000000e002"
ENGINE_HOST = Path(__file__).resolve().parent.parent / "resource_explorer" / "engine_host.py"
OLD_ENGINE_ACTION_CALLS = ("get_active_engine_actions", "get_active_claimed_engine_actions", "claim_engine_action",
                           "update_engine_action_status", "record_completion_status")


def _gev_calls(egeria, method: str | None = None) -> list:
    spec = egeria.of("GovernanceEngine")
    return [c for c in spec.mock_calls if c[0] and (method is None or c[0] == method)]


def _target_statuses(egeria, action_guid: str, element_guid: str) -> list[dict]:
    rel = _rel_guid(action_guid, element_guid)
    return [s for s in egeria.target_statuses if s["relationship"] == rel]


def _assert_bound_to_the_real_signatures(egeria) -> None:
    """§3 test 2: every call RE made on the Governance Engine client binds pyegeria's own signature."""
    from pyegeria import GovernanceEngine

    for name, args, kwargs in _gev_calls(egeria):
        inspect.signature(getattr(GovernanceEngine, name)).bind(None, *args, **kwargs)


# ── §3 test 1: end to end per write path ───────────────────────────────────────────────────────────────────────────

def test_completed_claims_runs_sets_each_target_and_completes_on_the_governance_engine(reg, egeria, no_connection):
    egeria.add_action("ea-ok")
    assert _sweep(reg).claimed == ["ea-ok"]
    _run_queue_once(reg)

    calls = [c[0] for c in _gev_calls(egeria) if c[0] != "create_egeria_bearer_token"]
    assert calls[:2] == ["get_approved_engine_actions", "claim_engine_action"], calls
    a = egeria.actions["ea-ok"]
    assert a["statusUpdates"] == ["IN_PROGRESS"]
    done = a["completion"]
    assert done["status"] == "ACTIONED" and done["guards"] == ["survey-completed"]
    # The ActionTarget's status, on the RELATIONSHIP (owner Q1): IN_PROGRESS at the start, ACTIONED at the end, with
    # the completion's own words.
    statuses = _target_statuses(egeria, "ea-ok", DB_GUID)
    assert [s["status"] for s in statuses] == ["IN_PROGRESS", "ACTIONED"], egeria.target_statuses
    assert statuses[0]["start_date"] and not statuses[0]["completion_date"]
    assert statuses[1]["completion_date"] and statuses[1]["message"] == done["message"]
    assert all(s["relationship"] != DB_GUID for s in egeria.target_statuses), "never the element's GUID"
    _assert_bound_to_the_real_signatures(egeria)

    row = _row(reg)          # the next read
    assert row["state"] == "succeeded"
    assert row["target"]["outcome"]["guard"] == "survey-completed"
    assert row["target"]["completion_recorded_at"]
    assert "target_status_errors" not in row["target"]
    assert row["target"]["action_targets"] == [{"name": "newAsset", "guid": DB_GUID,
                                                "relationship_guid": _rel_guid("ea-ok", DB_GUID)}]


def test_survey_invalid_sets_the_target_invalid_with_the_completion_words(reg, egeria, no_connection):
    egeria.add_action("ea-inv", target=UNKNOWN_GUID)
    assert _sweep(reg).claimed == ["ea-inv"]
    _run_queue_once(reg)

    done = egeria.actions["ea-inv"]["completion"]
    assert done["status"] == "INVALID" and done["guards"] == ["survey-invalid"]
    statuses = _target_statuses(egeria, "ea-inv", UNKNOWN_GUID)
    assert [s["status"] for s in statuses] == ["IN_PROGRESS", "INVALID"]
    assert statuses[1]["message"] == done["message"] and "not registered in Resource Explorer" in done["message"]
    row = _row(reg)
    assert row["state"] == "failed" and row["target"]["outcome"]["guard"] == "survey-invalid"


def test_failed_sets_the_target_failed_with_the_completion_words(reg, egeria, no_connection):
    egeria.add_action("ea-fail")
    _sweep(reg)
    egeria.fail["create_asset"] = RuntimeError("OMAG-COMMON-500-001 the repository is unavailable")
    _run_queue_once(reg)

    done = egeria.actions["ea-fail"]["completion"]
    assert done["status"] == "FAILED"
    statuses = _target_statuses(egeria, "ea-fail", DB_GUID)
    assert [s["status"] for s in statuses] == ["IN_PROGRESS", "FAILED"]
    assert statuses[1]["message"] == done["message"]
    assert _row(reg)["target"]["outcome"]["guard"] == "survey-failed"


def test_cancelled_mid_run_publishes_nothing_sends_no_completion_and_marks_the_target(reg, egeria, no_connection):
    """§2.4: Egeria cancels the process while RE runs step 2. The step runs to its end; before publishing RE reads the
    action back, sees CANCELLED, publishes no report, sends no completion, sets the worked target INVALID "cancelled in
    Egeria" and stores the outcome cancelled."""
    a = _process_action(egeria, "ea-mid", "db_derived")
    a["instance"] = INSTANCE
    assert _sweep(reg).claimed == ["ea-mid"]
    in_progress = egeria.of("GovernanceEngine").update_engine_action_status.side_effect

    def cancel_arrives_while_running(engine_action_guid, status, body=None):
        in_progress(engine_action_guid, status, body)
        egeria._cancel_process(INSTANCE)           # someone presses Cancel while the step runs

    egeria.of("GovernanceEngine").update_engine_action_status.side_effect = cancel_arrives_while_running
    _run_queue_once(reg)

    assert egeria.reports() == [], "a cancelled action publishes no report"
    assert egeria.actions["ea-mid"]["completion"] is None and not _gev_calls(egeria, "record_completion_status")
    statuses = _target_statuses(egeria, "ea-mid", DB_GUID)
    assert [(s["status"], s["message"]) for s in statuses] == [("IN_PROGRESS", None),
                                                              ("INVALID", "cancelled in Egeria")]
    row = _row(reg)
    assert row["state"] == "cancelled"
    outcome = row["target"]["outcome"]
    assert outcome["cancelled"] is True and outcome["message"] == "cancelled in Egeria"
    assert row["target"]["completion_not_sent"] == "cancelled in Egeria"
    assert "completion_recorded_at" not in row["target"]
    # The restart pass never completes a run Egeria cancelled (it is not even listed: CANCELLED is not active).
    assert _restart(reg).completed == []


# ── §3 test 2: the fakes bind the real signatures ──────────────────────────────────────────────────────────────────

def test_the_governance_engine_fake_refuses_a_keyword_pyegeria_does_not_have(reg, egeria):
    egeria.add_action("ea-sig")
    _sweep(reg)
    engine = egeria.of("GovernanceEngine")
    with pytest.raises(TypeError):
        engine.update_action_target_status(_rel_guid("ea-sig", DB_GUID), "ACTIONED", completionMessage="camel")
    with pytest.raises(TypeError):
        engine.get_approved_engine_actions(ENGINE_GUID, startFrom=0)


# ── §3 test 3: the client-side screen stays the gate ───────────────────────────────────────────────────────────────

def test_a_listing_that_returns_another_engines_work_still_claims_none_of_it(reg, egeria):
    """The server filters by engine; RE's `_screen` still checks the engine GUID. If the listing ever returns more
    than it should, nothing of another engine's is claimed. (Fail on purpose: with `_screen`'s engine-GUID check
    removed, this test fails.)"""
    egeria.overreturn = True
    theirs = egeria.add_action("ea-theirs")
    theirs["governanceEngineGUID"] = OTHER_ENGINE_GUID
    result = _sweep(reg)
    assert result.claimed == [] and "ea-theirs" in result.skipped.get("other_engine", [])
    assert not _gev_calls(egeria, "claim_engine_action")
    assert _rows(reg) == []


# ── §3 test 4: adoption is the restart pass's alone ────────────────────────────────────────────────────────────────

def test_an_own_claim_with_no_row_is_adopted_by_the_restart_pass_and_never_by_the_sweep(reg, egeria):
    egeria.add_action("ea-orphan", status="ACTIVATING", claimed_by=_daemon_user())
    assert _sweep(reg).adopted == [] and _rows(reg) == [], "the approved listing never shows a claimed action"
    egeria.overreturn = True                       # even a listing that shows it: the sweep leaves it
    swept = _sweep(reg)
    assert swept.adopted == [] and "ea-orphan" in swept.skipped.get("already_claimed", [])
    assert _rows(reg) == []
    egeria.overreturn = False
    assert _restart(reg).adopted == ["ea-orphan"]
    assert [r["target"]["engine_action_guid"] for r in _rows(reg)] == ["ea-orphan"]
    assert not _gev_calls(egeria, "claim_engine_action"), "adopted, never claimed a second time"


# ── §3 test 5: no Automated Curation engine-action call is left ────────────────────────────────────────────────────

def test_engine_host_names_no_automated_curation_client_and_no_old_listing():
    """`engine_host.py` builds no `AutomatedCuration` client at all (cancel lives on the route's port) and calls none
    of the server-wide or deprecated listings. Checked on the code, not the docstrings."""
    tree = ast.parse(ENGINE_HOST.read_text())
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names}
    assert "AutomatedCuration" not in names | imported
    called = {n.func.attr for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "get_active_engine_actions" not in called
    # The other four are called, and only on the Governance Engine client (the fake refuses them on Automated
    # Curation, so the end-to-end tests above fail on any regression).
    assert {"claim_engine_action", "update_engine_action_status", "record_completion_status",
            "get_active_claimed_engine_actions", "get_approved_engine_actions",
            "update_action_target_status"} <= called


def test_the_governance_engine_client_never_falls_back_to_the_old_urls():
    from pyegeria import GovernanceEngine

    from resource_explorer import engine_host

    assert inspect.signature(GovernanceEngine.__init__).parameters["legacy_fallback"].default is False

    class Client:
        legacy_fallback = True

    assert engine_host.governance_engine_client(Client()).legacy_fallback is False


class _NotFound(Exception):
    related_http_code = 404


def test_a_view_server_without_the_service_is_said_once_and_nothing_falls_back(reg, egeria, caplog):
    egeria.add_action("ea-404")
    host = _host(reg)
    try:
        host.sweep_once()                                     # builds the specs
        egeria.of("GovernanceEngine").get_approved_engine_actions.side_effect = _NotFound("HTTP 404 Not Found")
        with caplog.at_level(logging.WARNING, logger="resource_explorer.engine_host"):
            first = host.sweep_once()
            second = host.sweep_once()
    finally:
        host.close()
    said = [r for r in caplog.records if "governance-engine view service" in r.getMessage()]
    assert len(said) == 1, [r.getMessage() for r in caplog.records]
    assert first.claimed == [] == second.claimed
    assert "governance-engine" in first.note


# ── owner Q1: the relationship GUID or nothing ─────────────────────────────────────────────────────────────────────

def test_a_target_without_a_relationship_guid_gets_no_status_and_the_run_says_so(reg, egeria, no_connection):
    a = egeria.add_action("ea-norel")
    for t in a["actionTargetElements"]:
        t.pop("actionTargetRelationshipGUID")
    _sweep(reg)
    _run_queue_once(reg)
    assert not _gev_calls(egeria, "update_action_target_status"), "never the element's GUID instead"
    row = _row(reg)
    assert row["state"] == "succeeded", "a target status is a courtesy; the completion still goes"
    [err] = row["target"]["target_status_errors"]
    assert err["target"] == DB_GUID and "actionTargetRelationshipGUID" in err["error"]


def test_a_target_status_egeria_refuses_is_recorded_and_never_blocks_the_completion(reg, egeria, no_connection):
    egeria.add_action("ea-tsfail")
    _sweep(reg)
    egeria.fail["update_action_target_status"] = RuntimeError("read timeout")
    _run_queue_once(reg)
    assert egeria.actions["ea-tsfail"]["completion"]["status"] == "ACTIONED"
    row = _row(reg)
    assert row["state"] == "succeeded"
    [err] = row["target"]["target_status_errors"]
    assert err["status"] == "IN_PROGRESS" and "read timeout" in err["error"]
    # The end status still went (one failure does not stop the next update).
    assert [s["status"] for s in _target_statuses(egeria, "ea-tsfail", DB_GUID)] == ["ACTIONED"]


# ── §2.4: Cancel on the definition card (owner Q2, Q3), end to end through the route ───────────────────────────────

STARTER = "dan"


def _running_definition_run(reg, egeria, *, started_in: str = "re") -> dict:
    """An Egeria-coordinated run of the Database Analysis Survey on coco_pharma, step 1 running in Egeria."""
    from resource_explorer import mixed_process
    from resource_explorer import native_survey_run as nsr

    first = sorted(mixed_process.definition_process(ANALYSIS).steps, key=lambda st: st.number)[0]
    a = _process_action(egeria, "ea-step1", first.request_type[len("re-"):].replace("-", "_"), status="IN_PROGRESS",
                        claimed_by=_daemon_user())
    a["instance"] = INSTANCE
    egeria.graphs[INSTANCE] = {"startingElement": {"elementGUID": INSTANCE}, "elementList": [
        {"type": {"typeName": "ActionRequester"}, "elementAtEnd1": True,
         "element": {"elementGUID": "ea-step1", "type": {"typeName": "EngineAction"}}}]}
    assert reg.record_native_survey_submission_once(
        "database", "coco_pharma", ANALYSIS, "2026-10-17T09:00:00", engine_action_guid=INSTANCE,
        submitted_by=STARTER if started_in == "re" else "", started_as="process", started_by="egeria",
        started_in=started_in, declared_extra=mixed_process.expected_steps_record(ANALYSIS))
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.egeria_clients import Daemon, DaemonReason

    with nsr.port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port:
        state = nsr.refresh_mixed_run(reg, port, run, entity_type="database", slug="coco_pharma")
    assert state["state"] == "running", state
    return run


@pytest.fixture
def web(reg, egeria, monkeypatch):
    who = {"user_id": STARTER, "admin": False}
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", reg.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user",
                        lambda request: {"user_id": who["user_id"], "egeria_token": f"tok-{who['user_id']}",
                                         "role": "user"})
    monkeypatch.setattr("resource_explorer.web.admin_auth.is_admin_request", lambda request, cfg: who["admin"])
    from resource_explorer.web.app import app

    return TestClient(app), who


def _def_row(client) -> dict:
    r = client.get("/api/native-surveys/database/coco_pharma")
    assert r.status_code == 200, r.text
    rows = r.json()["surveys"]
    return next(r for r in rows if r["qualified_name"] == ANALYSIS)


def mixed_process_plan() -> list:
    from resource_explorer import mixed_process

    return mixed_process.expected_steps_record(ANALYSIS)["expected_steps"]


CANCEL_URL = f"/api/native-surveys/database/coco_pharma/process-runs/{INSTANCE}/cancel"


def test_the_starter_cancels_as_themself_and_the_line_reads_cancelled_only_from_egerias_read_back(reg, egeria, web):
    client, _who = web
    _running_definition_run(reg, egeria)
    assert _def_row(client)["process_cancel"]["offered"] is True

    r = client.post(CANCEL_URL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["accepted"] is True and body["cancelled"] is True and body["refused"] == ""
    # Made as the person who pressed, never the service account (owner rule, 2026-10-14).
    [(guid, who)] = egeria.cancels
    assert guid == INSTANCE and who.kind == "caller" and who.user_id == STARTER
    assert ("AutomatedCuration", STARTER) in egeria.built
    # The proof row, then the line: ⊘ cancelled from the read-back.
    [run] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    press = json.loads(run["declared"])["cancel"]
    assert {k: press[k] for k in ("by", "instance_guid", "answer")} == {"by": STARTER, "instance_guid": INSTANCE,
                                                                        "answer": "accepted"}
    row = _def_row(client)
    assert row["run"]["egeria_status"] == "CANCELLED" and row["run"]["cancel"]["state"] == "done"
    done = row["run"]["cancel"]
    assert done["by"] == STARTER and done["at"] and done["of"] == len(mixed_process_plan()) and done["finished"] == 0
    assert not done.get("outside")
    assert "⊘ cancelled" in row["run"]["line"] and row["in_flight"] is False
    assert row["process_cancel"]["offered"] is False


def test_an_accepted_cancel_egeria_has_not_applied_yet_reads_cancelling_from_the_press_row(reg, egeria, web):
    client, _who = web
    _running_definition_run(reg, egeria)
    egeria.ignore_cancel = True                 # Egeria accepts the call; its read-back still says IN_PROGRESS
    body = client.post(CANCEL_URL).json()
    assert body["accepted"] is True and body["cancelled"] is False
    row = _def_row(client)
    assert row["run"]["state"] == "running" and row["run"]["cancel"]["state"] == "pending"
    assert row["process_cancel"]["offered"] is False, "no second press while one is pending"
    assert client.post(CANCEL_URL).status_code == 409


def test_a_cancel_egeria_refuses_shows_egerias_reason_and_changes_nothing_else(reg, egeria, web):
    from tests.test_engine_host_e4 import _refusal

    client, _who = web
    _running_definition_run(reg, egeria)
    egeria.fail["cancel_governance_action_process"] = _refusal(
        "OMAG-GENERIC-HANDLERS-403-009", "the process instance has already completed")
    body = client.post(CANCEL_URL).json()
    assert body["accepted"] is False and "already completed" in body["refused"]
    row = _def_row(client)
    assert row["run"]["state"] == "running"
    c = row["run"]["cancel"]
    assert c["state"] == "refused" and "already completed" in c["reason"] and c["kind"] == "not_permitted"
    assert row["process_cancel"]["offered"] is True, "not permitted: Cancel run stays"


def test_a_cancel_refused_because_the_run_had_finished_is_too_late(reg, egeria, web):
    from tests.test_engine_host_e4 import _refusal

    client, _who = web
    _running_definition_run(reg, egeria)
    start = egeria.graphs["ea-step1"]["startingElement"]["elementProperties"]["propertyValueMap"]
    start["activityStatus"]["symbolicName"] = "FAILED"            # it ended before the press reached Egeria
    egeria.fail["cancel_governance_action_process"] = _refusal("OMAG-GENERIC-HANDLERS-400-001", "not active")
    body = client.post(CANCEL_URL).json()
    assert body["refused_kind"] == "too_late"
    row = _def_row(client)
    assert row["run"]["cancel"]["kind"] == "too_late" and row["process_cancel"]["offered"] is False


def test_an_unreachable_egeria_is_not_sent_never_refused_and_cancel_comes_back(reg, egeria, web):
    client, _who = web
    _running_definition_run(reg, egeria)
    egeria.fail["cancel_governance_action_process"] = ConnectionError("connection refused")   # no HTTP answer
    body = client.post(CANCEL_URL).json()
    assert body["unsent"] and body["refused"] == "" and body["accepted"] is False
    row = _def_row(client)
    assert row["run"]["cancel"]["state"] == "unsent"
    assert row["process_cancel"]["offered"] is True


def test_q2_only_the_starter_or_an_admin_is_offered_cancel_and_anyone_else_is_refused(reg, egeria, web):
    client, who = web
    _running_definition_run(reg, egeria)
    who["user_id"] = "peterprofile"
    assert _def_row(client)["process_cancel"]["offered"] is False
    r = client.post(CANCEL_URL)
    assert r.status_code == 403 and egeria.cancels == []
    who["admin"] = True
    assert _def_row(client)["process_cancel"]["offered"] is True
    assert client.post(CANCEL_URL).status_code == 200
    [(_guid, by)] = egeria.cancels
    assert by.user_id == "peterprofile", "an admin's cancel runs as the admin who pressed"


def test_q3_a_run_re_did_not_start_has_no_cancel_for_anyone_admins_included(reg, egeria, web):
    client, who = web
    _running_definition_run(reg, egeria, started_in="egeria")
    for user, admin in ((STARTER, False), ("peterprofile", True)):
        who["user_id"], who["admin"] = user, admin
        row = _def_row(client)
        assert row["process_cancel"]["offered"] is False, (user, admin)
        assert row["process_cancel"]["outside"] is True, "the line says it was started outside RE"
        assert client.post(CANCEL_URL).status_code == 409
    assert egeria.cancels == []


def test_cancel_needs_a_signed_in_person(reg, egeria, web, monkeypatch):
    client, _who = web
    _running_definition_run(reg, egeria)
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
    assert client.post(CANCEL_URL).status_code in (401, 403)
    assert egeria.cancels == []


def test_a_run_cancelled_outside_re_says_so_and_a_step_re_still_runs_is_finishing(reg, egeria, web):
    client, _who = web
    _running_definition_run(reg, egeria)
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

    with acting_as(Daemon(DaemonReason.SCHEDULER)):
        egeria._cancel_process(INSTANCE)                    # cancelled in Egeria, no press of RE's
    egeria.cancels.clear()
    reg.enqueue_run("engine_action", {"engine_action_guid": "ea-step1"}, requested_by="")   # RE still holds the step
    client.post("/api/native-surveys/database/coco_pharma/refresh")
    row = _def_row(client)
    c = row["run"]["cancel"]
    assert c["state"] == "done" and c["outside"] is True and "by" not in c
    assert row["process_cancel"]["finishing"]["step"] == 1
