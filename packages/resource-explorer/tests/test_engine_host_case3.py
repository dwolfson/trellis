"""Engine host, case 3: Egeria dispatches RE's own Survey Definitions, one engine action per step.

Design: docs/design-notes/SLICE-ENGINE-HOST-CASE3-RE-DEFINITIONS-DISPATCHED-BY-EGERIA.md (§5.2, tests 1-9; C1-C4 and the
owner's "coordinated by Egeria" control). Builds on step 4's process reading and run line (mixed_process.py).

Only the pyegeria boundary is faked, with test_engine_host_e4's `FakeEgeria` (every client a
`create_autospec(<real class>, spec_set=True, instance=True)`). An action of a process carries what Egeria's
`EngineActionElement` carries (`processName`, `processStepGUID`, `processStepName`); its neighbourhood and its process
step's next-step links answer in the `get_all_related_elements` shape captured live for step 4 (M2:
tests/fixtures/egeria_6_2/engine_action__*). Everything between the sweep and the client is real: the sweep, the
queue, the synthetic-step executor, the capability gate, the report publisher, the native-survey Run path and its
read-back. A database step's runner is replaced only where it would open a connection (`_fake_runner`).
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from tests.test_engine_host_e4 import (  # noqa: F401 - fixtures and helpers reused
    DB_GUID,
    PRIVATE_DB_GUID,
    REQUESTER,
    _daemon_user,
    _restart,
    _rows,
    _run_queue_once,
    _sweep,
    egeria,
    no_connection,
    reg,
)

PKG = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "egeria_6_2"
STEPS_DIR = PKG / "docs" / "dr-egeria" / "engine-host" / "steps"
ENGINE_DOC = PKG / "docs" / "dr-egeria" / "engine-host" / "resource-explorer-survey-engine.md"
ANALYSIS = "GovActionProcess::DatabaseAnalysisSurvey"
SCOUTING = "GovActionProcess::DatabaseScoutingSurvey"
INSTANCE = "06994d5d-a228-408c-8842-fd6256db4c34"
INSTANCE_2 = "16994d5d-a228-408c-8842-fd6256db4c35"
TECH = "PostgreSQL Relational Database"
PASSWORD = "stored-pass-0123456789"


def _fx(name: str):
    return json.loads((FIXTURES / name).read_text())["answer"]


def _pv(value) -> dict:
    return {"class": "PrimitiveTypePropertyValue", "primitiveValue": value}


def _process_action(egeria, guid: str, step_key: str, *, definition: str = ANALYSIS, instance: str = INSTANCE,
                    next_guards=("Any",), previous: tuple[str, str, list] | None = None, target=DB_GUID,
                    status: str = "APPROVED", claimed_by: str | None = None, report: str | None = None) -> dict:
    """An engine action Egeria created for one step of an RE Survey Definition, as `EngineActionElement` carries it,
    with its neighbourhood (`get_all_related_elements`, M2 shape: Anchors to the process instance, ActionTargets,
    ControlFlow from the previous action) and its process step's next-step links."""
    from resource_explorer.engine_host import request_type_for_step

    group = definition.split("::", 1)[1]
    step_guid = f"step-{group}-{step_key}"
    a = egeria.add_action(guid, request_type=request_type_for_step(step_key), target=target, status=status,
                          claimed_by=claimed_by, report=report)
    a["processName"] = f"{definition}@1791853850864::{instance[::-1]}"
    a["processStepGUID"] = step_guid
    a["processStepName"] = f"GovActionProcessStep::{group}::{step_key}"
    start = copy.deepcopy(_fx("engine_action__next_step_after_survey__related.json")["startingElement"])
    start["elementGUID"] = guid
    for c in start.get("classifications") or []:
        if c.get("classificationName") == "Anchors":
            c["classificationProperties"]["propertiesAsStrings"]["anchorGUID"] = instance
    pvm = start["elementProperties"]["propertyValueMap"]
    pvm.update(requestType=_pv(a["requestType"]), processName=_pv(a["processName"]),
               requesterUserId=_pv(REQUESTER),
               activityStatus={"class": "EnumTypePropertyValue", "symbolicName": status})
    elements = [{"type": {"typeName": "ActionTarget"}, "elementAtEnd1": False,
                 "relationshipProperties": {"propertiesAsStrings": {"actionTargetName": t["actionTargetName"]}},
                 "element": {"elementGUID": t["actionTargetGUID"]}} for t in a["actionTargetElements"]]
    if previous is not None:
        prev_guid, prev_status, prev_guards = previous
        elements.append({"type": {"typeName": "ControlFlow"}, "elementAtEnd1": True,
                         "relationshipProperties": {"propertiesAsStrings": {"guard": "Any", "mandatoryGuard": "false"}},
                         "element": {"elementGUID": prev_guid, "elementProperties": {"propertyValueMap": {
                             "activityStatus": {"class": "EnumTypePropertyValue", "symbolicName": prev_status},
                             "completionGuards": {"class": "ArrayTypePropertyValue", "arrayValues": {
                                 "propertyValueMap": {str(i): _pv(g) for i, g in enumerate(prev_guards)}}},
                             "requestType": _pv("re-previous")}}}})
    egeria.graphs[guid] = {"startingElement": start, "elementList": elements}
    egeria.graphs[step_guid] = _step_graph(step_guid, next_guards)
    return a


def _step_graph(step_guid: str, next_guards) -> dict:
    """A GovernanceActionProcessStep's relationships, in the M2 entry shape: one NextGovernanceActionProcessStep per
    next step (this step at end 1), and the link from its previous step (this step at end 2)."""
    entries = [{"type": {"typeName": "NextGovernanceActionProcessStep"}, "elementAtEnd1": False,
                "relationshipGUID": f"{step_guid}-next-{i}",
                "relationshipProperties": {"propertiesAsStrings": {"guard": g, "mandatoryGuard": "false"}},
                "element": {"elementGUID": f"{step_guid}-after-{i}"}} for i, g in enumerate(next_guards)]
    entries.append({"type": {"typeName": "NextGovernanceActionProcessStep"}, "elementAtEnd1": True,
                    "relationshipProperties": {"propertiesAsStrings": {"guard": "survey-failed"}},
                    "element": {"elementGUID": f"{step_guid}-before"}})
    return {"startingElement": {"elementGUID": step_guid}, "elementList": entries}


@pytest.fixture
def ops_runner(monkeypatch):
    """postgres_operations' runner, at the adapter (the only stand-in): it records what it was handed and returns the
    shape the real runner returns, so the real annotation builder makes the report's annotations."""
    from resource_explorer.surveyors.database import survey_definition_adapter as db

    calls: list[dict] = []

    def run(db_entity, registry, db_user: str = "", db_pwd: str = "", scan_surveyed_at=None, **_):
        calls.append({"slug": db_entity.slug, "db_user": db_user, "db_pwd": db_pwd})
        return {"schema_info": {}, "operations": {"privilege_audit": None, "db_activity_signals": None,
                                                  "db_resilience": None, "db_external_dependencies": None}}

    monkeypatch.setitem(db._ADAPTER.re_analysis_steps, "postgres_operations", run)
    return calls


def _with_credential(reg, *, stats_role: bool | None = None):
    reg.update_database_credentials("coco_pharma", "egeria_user", PASSWORD)
    if stats_role is not None:
        reg.record_database_survey(slug="coco_pharma", schema_count=1, table_count=2, column_count=3,
                                   survey_data={"credential_capability": {
                                       "connected_as": "egeria_user", "stats_role": stats_role,
                                       "relation_total": 2, "relation_select": 2}},
                                   source="local", surveyed_at="2026-10-15T08:00:00")


# ── test 1: request types equal registry keys; guards equal step_outcome's mapping ──────────────────────────────

def _declared_types(text: str) -> dict[str, list[str]]:
    """{request type: producedGuards} of every GovernanceActionType a declaration document creates."""
    out = {}
    for block in text.split("## Create Governance Action Type")[1:]:
        qn = re.search(r"### Qualified Name\n(\S+)\n", block).group(1)
        guards = re.search(r"### Produced Guards\n(.+)\n", block).group(1)
        out[qn.split("::", 1)[1]] = [g.strip() for g in guards.split(",")]
    return out


def test_request_types_equal_both_registries_and_guards_equal_the_mapping():
    from resource_explorer import engine_host as eh
    from resource_explorer import step_outcome
    from resource_explorer.surveyors.database.survey_definition_adapter import DATABASE_STEP_REGISTRY
    from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
    from resource_explorer.surveyors.survey_step_host import attached_user_steps

    db_keys = set(DATABASE_STEP_REGISTRY) - attached_user_steps("database")
    expected = {eh.request_type_for_step(k): k for k in db_keys | set(STEP_REGISTRY)}
    steps_docs = {p.name: p.read_text() for p in sorted(STEPS_DIR.glob("*-steps.md"))}
    assert set(steps_docs) == {"database-steps.md", "repo-steps.md"}
    declared = {}
    for text in steps_docs.values():
        for rt, guards in _declared_types(text).items():
            assert rt not in declared, f"{rt} declared twice"
            declared[rt] = guards
            assert guards == list(step_outcome.produced_guards(expected[rt])), rt
    engine_doc = _declared_types(ENGINE_DOC.read_text())
    assert not set(engine_doc) & set(declared), "a step is declared by two documents"
    assert set(declared) | set(engine_doc) == set(expected)
    # Every registry request type is one RE's engine claims, mapped to its own step key.
    supported = eh.supported_request_types()
    assert {rt: supported[rt] for rt in expected} == expected
    # The mapping (review M1): every outcome also emits the guard RE's authored links carry, so an Egeria-coordinated
    # run goes on after any step exactly as RE's own executor follows `Any`.
    for g in ("survey-completed", "survey-invalid", "survey-failed"):
        assert step_outcome.completion_guards("postgres_operations", g) == (g, "Any")


# ── test 2: an executor per step in the published document; the reconciler flags none, two, or a wrong one ─────

def test_the_published_definition_carries_one_executor_per_step_and_the_reconciler_flags_drift():
    from resource_explorer import engine_host as eh
    from resource_explorer.surveyors import survey_definition_reconciler as rec
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions

    doc_path = PKG / "docs" / "dr-egeria" / "survey-definitions-database" / "database-survey-definition-analysis.md"
    text = doc_path.read_text()
    doc = documented_definitions()["DatabaseAnalysisSurvey"]
    blocks = text.split("## Link Action to Action Executor")[1:]
    links = [(re.search(r"### Governance Action Type\n(\S+)", b).group(1),
              re.search(r"### Governance Engine\n(\S+)", b).group(1),
              re.search(r"### Request Type\n(\S+)", b).group(1)) for b in blocks]
    assert sorted(links) == sorted((f"GovActionProcessStep::DatabaseAnalysisSurvey::{k}", eh.ENGINE_QUALIFIED_NAME,
                                    eh.request_type_for_step(k)) for k in doc.steps)
    # the generator writes what the document says
    from resource_explorer.surveyors.dr_egeria_survey_publisher import PublishableStep, render_executor_block
    assert render_executor_block("DatabaseAnalysisSurvey", PublishableStep("db_derived", "d", "t")).count(
        "### Request Type\nre-db-derived") == 1

    step_qn = "GovActionProcessStep::DatabaseAnalysisSurvey::postgres_operations"
    kw = {"engine_qualified_name": eh.ENGINE_QUALIFIED_NAME, "expected_request_type": "re-postgres-operations"}
    live = _step_graph("s1", ["Any"])          # a live-shaped step element with no executor yet (all 127 today)
    none = rec.executors_from_related(live)
    assert [d.problem for d in rec.diff_executors(step_qn, "postgres_operations", "resource-explorer", none, **kw)] \
        == ["missing"]

    def executor(rt, engine_qn=eh.ENGINE_QUALIFIED_NAME, n=0):
        return {"type": {"typeName": "GovernanceActionExecutor"}, "elementAtEnd1": False, "relationshipGUID": f"x{n}",
                "relationshipProperties": {"propertiesAsStrings": {"requestType": rt}},
                "element": {"elementGUID": f"eng{n}", "elementProperties": {"propertiesAsStrings": {
                    "qualifiedName": engine_qn}}}}

    one = copy.deepcopy(live)
    one["elementList"].append(executor("re-postgres-operations"))
    assert rec.diff_executors(step_qn, "postgres_operations", "resource-explorer",
                              rec.executors_from_related(one), **kw) == []
    two = copy.deepcopy(one)
    two["elementList"].append(executor("re-postgres-operations", n=1))
    assert [d.problem for d in rec.diff_executors(step_qn, "postgres_operations", "resource-explorer",
                                                  rec.executors_from_related(two), **kw)] == ["several"]
    wrong = copy.deepcopy(live)
    wrong["elementList"].append(executor("re-db-derived"))
    assert [d.problem for d in rec.diff_executors(step_qn, "postgres_operations", "resource-explorer",
                                                  rec.executors_from_related(wrong), **kw)] == ["wrong_request_type"]
    elsewhere = rec.diff_executors(step_qn, "postgres_operations", "prefect", rec.executors_from_related(one), **kw)
    assert [d.problem for d in elsewhere] == ["executes_at_disagrees"]


# ── test 3: dispatch by request type (and the write path end to end) ───────────────────────────────────────────

def test_a_definition_step_runs_its_registry_step_on_the_resolved_database_and_completes(reg, egeria, no_connection,
                                                                                         ops_runner):
    _with_credential(reg)
    _process_action(egeria, "ea-ops", "postgres_operations", definition=SCOUTING, next_guards=())
    assert _sweep(reg).claimed == ["ea-ops"]
    assert _run_queue_once(reg) is not None

    assert ops_runner == [{"slug": "coco_pharma", "db_user": "egeria_user", "db_pwd": PASSWORD}]
    action = egeria.actions["ea-ops"]
    assert action["processingEngineUserId"] == _daemon_user() and action["statusUpdates"] == ["IN_PROGRESS"]
    done = action["completion"]
    [(report_guid, body)] = egeria.reports()
    assert done["status"] == "ACTIONED" and done["guards"] == ["survey-completed", "Any"], done
    assert done["targets"] == [{"actionTargetName": "surveyReport", "actionTargetGUID": report_guid}]
    assert body["properties"]["purpose"] == "re-postgres-operations"
    assert {"type": "ReportOriginator", "end1": "ea-ops", "end2": report_guid} in [
        {k: r[k] for k in ("type", "end1", "end2")} for r in egeria.relationships]
    assert egeria.annotations_under(report_guid) == 4       # the real builder: one per unsupported sub-analysis
    [row] = _rows(reg)
    assert row["state"] == "succeeded"
    assert row["target"]["outcome"]["annotation_count"] == 4
    assert PASSWORD not in json.dumps(row) and PASSWORD not in json.dumps(egeria.actions)


def test_an_unknown_request_type_is_not_claimed_and_is_recorded_once(reg, egeria, caplog):
    from resource_explorer.engine_host import EngineHost

    egeria.add_action("ea-unknown", request_type="re-no-such-step")
    host = EngineHost(registry=reg)
    try:
        with caplog.at_level("WARNING", logger="resource_explorer.engine_host"):
            first, second = host.sweep_once(), host.sweep_once()
    finally:
        host.close()
    assert first.skipped.get("unknown_request_type") == ["ea-unknown"] and not first.claimed
    assert second.skipped.get("unknown_request_type") == ["ea-unknown"]
    assert egeria.actions["ea-unknown"]["processingEngineUserId"] is None
    assert sum("ea-unknown" in r.getMessage() for r in caplog.records) == 1


def test_an_out_of_scope_repository_step_is_claimed_and_completed_invalid_naming_why(reg, egeria):
    egeria.add_action("ea-repo", request_type="re-repo-arch-coupling")
    assert _sweep(reg).claimed == ["ea-repo"]
    _run_queue_once(reg)
    done = egeria.actions["ea-repo"]["completion"]
    assert done["status"] == "INVALID" and done["guards"] == ["survey-invalid"]
    assert "fetches sources or calls models" in done["message"]
    assert egeria.reports() == []


# ── test 4: a guard no authored link consumes ends the process, and RE says so ─────────────────────────────────

def test_a_guard_no_next_step_consumes_ends_the_process_and_the_run_says_so(reg, egeria, no_connection):
    # db_derived with no stored inventory completes survey-invalid; its (hand-authored) next link takes only
    # "survey-completed", which it does not produce, and not "Any".
    _process_action(egeria, "ea-dd", "db_derived", next_guards=("survey-completed",),
                    target="0a1b2c3d-0000-4000-8000-0000000000d3")
    assert _sweep(reg).claimed == ["ea-dd"]
    _run_queue_once(reg)
    done = egeria.actions["ea-dd"]["completion"]
    assert done["guards"] == ["survey-invalid", "Any"]           # Egeria is told the guards
    note = "process ended after db_derived: guard survey-invalid has no next step"
    assert note in done["message"]
    [row] = _rows(reg)
    assert row["target"]["outcome"]["process_note"] == note
    # Nothing else runs: no other action was created, claimed or completed.
    assert [g for g, a in egeria.actions.items() if a["completion"]] == ["ea-dd"]


# ── test 5: credential capability ─────────────────────────────────────────────────────────────────────────────

def test_a_step_the_stored_credential_cannot_serve_is_invalid_with_the_launchers_reason(reg, egeria, no_connection,
                                                                                       ops_runner):
    from resource_explorer.surveyors import credential_capability, prerequisite_resolver
    from resource_explorer.surveyors.database.survey_definition_adapter import DATABASE_STEP_REGISTRY

    _with_credential(reg, stats_role=False)
    _process_action(egeria, "ea-cap", "postgres_operations", next_guards=())
    assert _sweep(reg).claimed == ["ea-cap"]
    _run_queue_once(reg)

    entity = reg.get_database("coco_pharma", allow_unreadable=True)
    launcher = prerequisite_resolver.resolve(reg, entity, "postgres_operations", DATABASE_STEP_REGISTRY,
                                             capability_probe=credential_capability.stored_probe(reg, entity))
    [reason] = [r.detail for r in launcher.proposal.reasons if r.kind == "capability"]
    assert reason.startswith("needs `stats`: connected as egeria_user")
    done = egeria.actions["ea-cap"]["completion"]
    assert done["status"] == "INVALID" and done["guards"] == ["survey-invalid", "Any"]
    assert reason in done["message"]                             # the launcher's own reason, nothing invented
    assert "can run, but not completely" not in done["message"]  # never "did not run ... can run" (review M2)
    assert egeria.reports() == [] and ops_runner == []           # nothing run, no report


# ── test 6: no double running ───────────────────────────────────────────────────────────────────────────────────

def test_a_definition_started_in_re_creates_no_engine_action_and_its_row_says_re(reg, egeria, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.web.app import app

    def _factory(*a, **k):
        return reg

    _factory.RUN_STATES = ProjectRegistry.RUN_STATES
    _factory.RUN_KINDS = ProjectRegistry.RUN_KINDS
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", _factory)
    res = TestClient(app).post("/api/survey-definitions/database/coco_pharma/run",
                               json={"survey_definition_ref": ANALYSIS})
    assert res.status_code == 200, res.text
    [row] = reg.list_runs(kind="survey_definition_run")
    params = json.loads(row["target"])["params"]
    assert params["started_by"] == "re" and "started_by_person" in params
    assert not egeria.method_calls("initiate_gov_action_process") and not egeria.method_calls("claim_engine_action")
    assert reg.list_runs(kind="engine_action") == []


def test_a_definition_started_in_egeria_creates_no_re_coordinated_run(reg, egeria, no_connection):
    _process_action(egeria, "ea-first", "db_derived")
    assert _sweep(reg).claimed == ["ea-first"]
    [row] = _rows(reg)
    assert row["target"]["started_by"] == "egeria"
    assert row["target"]["definition"] == ANALYSIS
    assert reg.list_runs(kind="survey_definition_run") == []


# ── test 7: one step key, two definitions ───────────────────────────────────────────────────────────────────────

def test_a_shared_step_runs_once_per_process_instance_each_report_on_its_own_action(reg, egeria, no_connection,
                                                                                    ops_runner):
    _with_credential(reg)
    _process_action(egeria, "ea-scout", "postgres_operations", definition=SCOUTING, instance=INSTANCE, next_guards=())
    _process_action(egeria, "ea-anal", "postgres_operations", definition=ANALYSIS, instance=INSTANCE_2,
                    next_guards=())
    assert sorted(_sweep(reg).claimed) == ["ea-anal", "ea-scout"]
    _run_queue_once(reg)
    _run_queue_once(reg)
    assert len(ops_runner) == 2
    reports = dict((r["end1"], r["end2"]) for r in egeria.relationships if r["type"] == "ReportOriginator")
    assert set(reports) == {"ea-scout", "ea-anal"} and len(set(reports.values())) == 2
    for guid in ("ea-scout", "ea-anal"):
        assert egeria.actions[guid]["completion"]["targets"] == [
            {"actionTargetName": "surveyReport", "actionTargetGUID": reports[guid]}]
    by_definition = {r["target"]["definition"]: r["target"]["process_instance_guid"] for r in _rows(reg)}
    assert by_definition == {SCOUTING: INSTANCE, ANALYSIS: INSTANCE_2}


# ── test 8: a restart in the middle of a three-step instance ───────────────────────────────────────────────────

def test_a_restart_mid_run_reruns_nothing_completed_recovers_the_running_step_and_waits(reg, egeria, no_connection,
                                                                                        monkeypatch):
    # Step 1 (column profile) completed before the restart; step 2 (nested columns) RE had claimed in Egeria and
    # died before writing its row; step 3 (db_derived) does not exist yet: Egeria creates it after step 2.
    _process_action(egeria, "ea-1", "postgres_column_profile", status="COMPLETED", claimed_by=_daemon_user())
    _process_action(egeria, "ea-2", "postgres_nested_columns", previous=("ea-1", "COMPLETED", ["survey-completed",
                                                                                                "Any"]),
                    status="IN_PROGRESS", claimed_by=_daemon_user())
    from resource_explorer.surveyors.database import survey_definition_adapter as db

    ran: list[str] = []
    monkeypatch.setitem(db._ADAPTER.re_analysis_steps, "postgres_column_profile",
                        lambda e, r, **k: ran.append("postgres_column_profile") or {})
    monkeypatch.setitem(db._ADAPTER.re_analysis_steps, "postgres_nested_columns",
                        lambda e, r, **k: ran.append("postgres_nested_columns") or {"schema_info": {}})
    result = _restart(reg)
    assert result.adopted == ["ea-2"]                      # the running one, recovered
    _run_queue_once(reg)
    assert ran == ["postgres_nested_columns"]              # the completed step is not run again
    assert egeria.actions["ea-2"]["completion"]["guards"][0] in ("survey-completed", "survey-failed")
    assert [r["target"]["engine_action_guid"] for r in _rows(reg)] == ["ea-2"]   # step 3 waits for Egeria
    assert _run_queue_once(reg) is None


# ── test 9: private not claimed; off means off ─────────────────────────────────────────────────────────────────

def test_a_private_resource_is_not_claimed_and_off_means_off(reg, egeria, monkeypatch):
    _make_private(reg, "alice_db")
    _process_action(egeria, "ea-pub", "postgres_operations", next_guards=())
    _process_action(egeria, "ea-priv", "postgres_operations", next_guards=(), target=PRIVATE_DB_GUID,
                    instance=INSTANCE_2)
    swept = _sweep(reg)
    assert swept.claimed == ["ea-pub"]
    assert swept.skipped.get("private_target") == ["ea-priv"]
    assert egeria.actions["ea-priv"]["processingEngineUserId"] is None

    monkeypatch.setenv("RE_ENGINE_HOST_ENABLED", "false")
    before = len(egeria.calls)
    _process_action(egeria, "ea-off", "postgres_operations", next_guards=(), instance="pi-off")
    off = _sweep(reg)
    assert off.note and not off.claimed and len(egeria.calls) == before


def _make_private(reg, slug: str) -> None:
    """A database in a private investigation, the way RE records one (as test_engine_host_e4 does)."""
    from resource_explorer.a2a_auth import CallerIdentity, current_caller

    reset = current_caller.set(CallerIdentity(user_id="alice", egeria_token=None, auth_source="app-jwt"))
    try:
        inv = reg.create_investigation("Alice Private", project_classification="PersonalProject")
        ws = reg.get_or_create_working_set(inv["slug"])
        reg.add_working_set_member(ws["slug"], "database", slug)
    finally:
        current_caller.reset(reset)
    assert reg.private_owner_for_entity("database", slug) == "alice"


# ── C4: Understanding reads an N-step run as one line with the definition's name ───────────────────────────────

def _view(guid, step_key, status, guards, report="", instance=INSTANCE):
    from resource_explorer.engine_host import request_type_for_step
    from resource_explorer.mixed_process import EngineActionView

    return EngineActionView(guid=guid, status=status, request_type=request_type_for_step(step_key), requester=REQUESTER,
                            process_name=f"{ANALYSIS}@1791853850864::x", instance_guid=instance,
                            completion_guards=list(guards), report_guids=[report] if report else [])


def test_an_egeria_coordinated_definition_run_reads_as_one_line_with_every_step():
    from resource_explorer import mixed_process

    views = [_view("a1", "postgres_column_profile", "COMPLETED", ["survey-completed", "Any"], "r1aaaaaa-0000"),
             _view("a2", "postgres_nested_columns", "COMPLETED", ["survey-completed", "Any"], "r2bbbbbb-0000"),
             _view("a3", "db_derived", "INVALID", ["survey-invalid", "Any"])]
    [line] = mixed_process.group_by_process(views)
    assert line.process.display_name == "Database Analysis Survey"
    words = mixed_process.run_line_words(line, started="10-15", started_in=mixed_process.STARTED_IN_EGERIA)
    assert words == ("Database Analysis Survey · step 1 postgres_column_profile ✓ report r1aaaaaa · step 2 "
                     "postgres_nested_columns ✓ report r2bbbbbb · step 3 db_derived ✗ survey-invalid · step 4 "
                     "postgres_operations not started yet · started in Egeria by peterprofile 10-15")
    from_re = mixed_process.run_line_words(line, started_in=mixed_process.STARTED_IN_RE, started_by="dan")
    assert from_re.endswith("· started in RE by dan")


def test_the_engine_host_lists_an_egeria_started_definition_run_once_per_process_instance(reg, egeria, no_connection,
                                                                                         ops_runner):
    from resource_explorer import native_survey_run as nsr

    _with_credential(reg)
    _process_action(egeria, "ea-3", "db_derived")
    _process_action(egeria, "ea-4", "postgres_operations", previous=("ea-3", "COMPLETED", ["survey-completed", "Any"]),
                    next_guards=())
    assert sorted(_sweep(reg).claimed) == ["ea-3", "ea-4"]
    _run_queue_once(reg)
    _run_queue_once(reg)
    [row] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    assert row["engine_action_guid"] == INSTANCE
    declared = json.loads(row["declared"])
    assert declared["started_by"] == "egeria" and declared["started_in"] == "egeria"
    listed = [r for r in nsr.native_survey_rows(reg, "database", "coco_pharma", TECH) if r["kind"] == "re_definition"]
    assert [(r["qualified_name"], r["display_name"]) for r in listed] == [(ANALYSIS, "Database Analysis Survey")]
    # Each step's own GovernanceActionType row is NOT listed for a definition step: one run, one row.
    assert reg.list_native_survey_runs("database", "coco_pharma", "ResourceExplorerSurvey::re-db-derived") == []


# ── the "coordinated by Egeria" control (owner, 2026-10-15) ─────────────────────────────────────────────────────

def test_the_control_is_hidden_with_a_sentence_when_the_engine_host_is_off(reg, monkeypatch):
    from resource_explorer import native_survey_run as nsr

    monkeypatch.delenv("RE_ENGINE_HOST_ENABLED", raising=False)
    off = nsr.coordinate_control(reg, "database", "coco_pharma", ANALYSIS)
    assert off["label"] == "coordinated by Egeria" and off["available"] is False
    assert off["why_not"] == nsr.ENGINE_HOST_OFF
    monkeypatch.setenv("RE_ENGINE_HOST_ENABLED", "true")
    assert nsr.coordinate_control(reg, "database", "coco_pharma", ANALYSIS)["available"] is True
    # never on a repository definition's row at all (review L6)
    assert nsr.coordinate_control(reg, "repo", "anything", "GovActionProcess::RepoScoutingSurvey") is None


def test_the_control_starts_the_process_through_egeria_and_records_started_by_egeria(reg, egeria, no_connection):
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.native_survey_run import port_session, submit_native_survey

    egeria.declared.add(ANALYSIS)
    egeria.assets.add(DB_GUID)
    with port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port:
        state = submit_native_survey(reg, port, "database", "coco_pharma", ANALYSIS, technology_type=TECH,
                                     submitted_by="dan")
    assert egeria.process_starts == [{"process": ANALYSIS, "request_parameters": None, "action_targets": [
        {"class": "NewActionTarget", "actionTargetName": "newAsset", "actionTargetGUID": DB_GUID}]}]
    assert state["state"] == "submitted"
    [row] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    assert row["engine_action_guid"] == "pi-1" and row["submitted_by"] == "dan"
    declared = json.loads(row["declared"])
    assert {k: declared[k] for k in ("started_as", "started_by", "started_in")} == {
        "started_as": "process", "started_by": "egeria", "started_in": "re"}
    assert re.fullmatch(r"Database Analysis Survey · step 1 postgres_column_profile not started yet · started in RE "
                        r"by dan \d\d-\d\d", declared["process_run"]["words"]), declared["process_run"]["words"]
    # No double running: the press made no RE-coordinated run and no engine action of RE's own.
    assert reg.list_runs(kind="survey_definition_run") == [] and reg.list_runs(kind="engine_action") == []

    # When RE's engine host then runs the instance's first step, the run is not listed a second time.
    _process_action(egeria, "ea-first", "db_derived", instance="pi-1")
    assert _sweep(reg).claimed == ["ea-first"]
    _run_queue_once(reg)
    assert len(reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)) == 1


def test_a_later_step_handed_every_earlier_steps_report_runs_and_is_not_refused(reg, egeria, no_connection):
    # Egeria hands step 3 the previous action's targets AND step 2's new one (prepareEngineActionFromProcessStep), so
    # it arrives with two surveyReport targets. A definition step takes no report: it runs.
    a = _process_action(egeria, "ea-3", "db_derived", report="r2bbbbbb-0000-4000-8000-000000000002",
                        previous=("ea-2", "COMPLETED", ["survey-completed", "Any"]))
    a["actionTargetElements"].append({"actionTargetName": "surveyReport",
                                      "actionTargetGUID": "r1aaaaaa-0000-4000-8000-000000000001"})
    a["actionTargetElements"].append({"actionTargetName": "newAsset", "actionTargetGUID": DB_GUID})
    assert _sweep(reg).claimed == ["ea-3"]
    _run_queue_once(reg)
    done = egeria.actions["ea-3"]["completion"]
    assert done["guards"] == ["survey-completed", "Any"], done
    assert "other target" not in done["message"]                 # the asset Egeria listed twice is one target


# ── review round 1 (H1, M1, L1, L2, L4, L5) ────────────────────────────────────────────────────────────────────

def test_every_published_step_ignores_multiple_triggers():
    """H1(a): duplicate next-step links (Dr.Egeria's Link Next only adds) must not start a step twice."""
    from resource_explorer.surveyors.survey_definition_docs import documented_definitions

    for path in sorted((PKG / "docs" / "dr-egeria").glob("survey-definitions*/*-survey-definition-*.md")):
        text = path.read_text()
        blocks = text.split("## Create Governance Action Process Step")[1:]
        assert blocks, path
        for block in blocks:
            block = block.split("___")[0]
            assert "### Ignore Multiple Triggers\ntrue\n" in block, (path.name, block[:120])
    assert documented_definitions()["DatabaseAnalysisSurvey"].steps    # the parser still reads the steps


def test_a_step_started_twice_in_one_run_runs_once_and_the_second_is_invalid(reg, egeria, no_connection):
    """H1(b): two engine actions for the same process step of the same process instance (a duplicate link fired)."""
    _process_action(egeria, "ea-dup-1", "db_derived")
    _process_action(egeria, "ea-dup-2", "db_derived")              # same instance, same step
    _process_action(egeria, "ea-other-run", "db_derived", instance=INSTANCE_2)   # another run: its own step
    assert sorted(_sweep(reg).claimed) == ["ea-dup-1", "ea-dup-2", "ea-other-run"]
    for _ in range(3):
        _run_queue_once(reg)
    first, second, other = (egeria.actions[g]["completion"] for g in ("ea-dup-1", "ea-dup-2", "ea-other-run"))
    assert first["guards"] == ["survey-completed", "Any"] and other["guards"] == ["survey-completed", "Any"]
    assert second["status"] == "INVALID" and second["guards"] == ["survey-invalid", "Any"]
    assert "triggered twice in this run; the first ran (engine action ea-dup-1)" in second["message"]
    assert sorted(e1 for e1, _ in [(r["end1"], r) for r in egeria.relationships if r["type"] == "ReportOriginator"]) \
        == ["ea-dup-1", "ea-other-run"]                          # the second wrote no report


def test_a_private_repository_target_is_not_claimed(reg, egeria):
    """L1: a repository request type's private target is left unclaimed, like a database's."""
    from resource_explorer.a2a_auth import CallerIdentity, current_caller
    from resource_explorer.registry import Project

    repo_guid = "0a1b2c3d-0000-4000-8000-0000000000e7"
    reg.add(Project(slug="alice_repo", display_name="alice_repo", github_url="https://github.com/a/alice_repo",
                    egeria_asset_guid=repo_guid))
    reset = current_caller.set(CallerIdentity(user_id="alice", egeria_token=None, auth_source="app-jwt"))
    try:
        inv = reg.create_investigation("Alice Repo", project_classification="PersonalProject")
        ws = reg.get_or_create_working_set(inv["slug"])
        reg.add_working_set_member(ws["slug"], "repo", "alice_repo")
    finally:
        current_caller.reset(reset)
    assert reg.repo_slug_for_asset_guid(repo_guid) == "alice_repo"
    assert reg.private_owner_for_entity("repo", "alice_repo") == "alice"
    egeria.add_action("ea-private-repo", request_type="re-repo-arch-coupling", target=repo_guid)
    swept = _sweep(reg)
    assert swept.claimed == [] and swept.skipped.get("private_target") == ["ea-private-repo"]
    assert egeria.actions["ea-private-repo"]["processingEngineUserId"] is None


def test_an_unreadable_stored_credential_is_invalid_and_never_tried_empty(reg, egeria, no_connection, ops_runner,
                                                                          monkeypatch):
    """L4: never a driver error with an empty password."""
    import resource_explorer.credential_crypto as crypto

    _with_credential(reg)

    def cannot(_raw):
        raise ValueError("no key")

    monkeypatch.setattr(crypto, "decrypt_db_password", cannot)
    assert reg.get_database("coco_pharma", allow_unreadable=True).credential_status == "unreadable"
    _process_action(egeria, "ea-unread", "postgres_operations", next_guards=())
    assert _sweep(reg).claimed == ["ea-unread"]
    _run_queue_once(reg)
    done = egeria.actions["ea-unread"]["completion"]
    assert done["status"] == "INVALID" and "stored credential unreadable" in done["message"]
    assert ops_runner == [] and egeria.reports() == []


def test_the_run_press_and_the_engine_host_write_one_run_line_whoever_is_first(reg, egeria, no_connection):
    """L5: the engine host listed the instance first (its first step ran before Run's own write); the press is then
    recorded on that row, not as a second run line."""
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.egeria_clients import Daemon, DaemonReason
    from resource_explorer.native_survey_run import port_session, submit_native_survey

    egeria.declared.add(ANALYSIS)
    egeria.assets.add(DB_GUID)
    started = egeria._start_process

    def start_then_engine_host_lists_it(*a, **k):
        guid = started(*a, **k)
        reg.record_native_survey_submission_once("database", "coco_pharma", ANALYSIS, "2026-10-15T09:00:00",
                                                 engine_action_guid=guid, submitted_by=REQUESTER,
                                                 started_as="engine-host", started_by="egeria", started_in="egeria")
        return guid

    egeria._start_process = start_then_engine_host_lists_it
    with port_session(cas.PyegeriaRegistrationPort(identity=Daemon(DaemonReason.SCHEDULER))) as port:
        submit_native_survey(reg, port, "database", "coco_pharma", ANALYSIS, technology_type=TECH, submitted_by="dan")
    [row] = reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)
    assert row["engine_action_guid"] == "pi-1" and row["submitted_by"] == "dan"
    assert json.loads(row["declared"])["started_in"] == "re"
    # and the other order: the engine host writes second and adds nothing
    assert reg.record_native_survey_submission_once("database", "coco_pharma", ANALYSIS, "2026-10-15T09:01:00",
                                                    engine_action_guid="pi-1", started_in="egeria") is False
    assert len(reg.list_native_survey_runs("database", "coco_pharma", ANALYSIS)) == 1


def test_an_re_run_records_and_shows_where_it_was_started():
    """L2: RE's own Run records started_by "re" and who pressed; Understanding's last-run line reads both back."""
    from resource_explorer.workflows.survey_definition import SurveyDefinitionRunParams

    params = SurveyDefinitionRunParams(survey_definition_ref=ANALYSIS, started_by_person="dan")
    again = SurveyDefinitionRunParams.from_dict(params.to_dict())
    assert (again.started_by, again.started_by_person) == ("re", "dan")


def test_the_last_run_line_reads_where_an_re_run_was_started(tmp_path):
    from resource_explorer.registry import ProjectRegistry

    reg = ProjectRegistry(db_path=str(tmp_path / "lastrun.db"))
    from resource_explorer.activity_logger import log_survey

    log_survey(reg, entity_type="database", entity_slug="coco_pharma", entity_name="coco_pharma",
               entity_location="", intent="assessment", status="ok", summary="ran",
               detail=json.dumps({"survey_definition_ref": ANALYSIS, "started_by": "re", "started_by_person": "dan"}))
    entry = reg.get_survey_definition_last_activity("database", "coco_pharma")[ANALYSIS]
    assert (entry["last_run_started_by"], entry["last_run_by"]) == ("re", "dan")


def test_a_definition_run_goes_on_after_a_failed_step_and_reads_running_until_done():
    """M1: an Egeria-coordinated definition run continues past an invalid step, as RE's executor would."""
    from resource_explorer.native_survey_run import RUNNING, derive_mixed_state

    row = {"engine_action_guid": INSTANCE, "executor_ref": ANALYSIS, "surveyed_at": "2026-10-15T09:00:00",
           "engine_action_status": "IN_PROGRESS", "engine_action_read_at": "2026-10-15T09:01:00",
           "declared": json.dumps({"process_run": {"words": "w", "steps": [
               {"status": "COMPLETED", "guards": ["survey-completed", "Any"]},
               {"status": "INVALID", "guards": ["survey-invalid", "Any"]},
               {"status": "IN_PROGRESS", "guards": []}]}})}
    assert derive_mixed_state(row)["state"] == RUNNING
