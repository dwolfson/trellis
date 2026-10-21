"""The native read-back sweep and the outbox drain on their own 60 s loop (2026-10-21), the card's "not checked
since" cue, and the annotation count label.

Defect (loading_bay, 2026-10-21): the scheduler tick ran `_run_due`, then RFA reconciliation, then the outbox drain,
then the read-back sweep, all on one thread every 900 s. A RagIngestion started inside `_run_due` ran 14+ minutes, so
an Egeria folder survey that finished in 7.4 s sat at "waiting" on its card. Nothing here reaches Egeria or a live
database; the Egeria port is an autospec of the real class.
"""
from __future__ import annotations

import dataclasses
import threading
import time
from datetime import datetime
from unittest.mock import create_autospec

import pytest

from resource_explorer import catalog_and_survey, egeria_clients, scheduler
from resource_explorer import native_survey_run as nsr
from resource_explorer.registry import DatabaseEntity, FileSystemEntity, ProjectRegistry

REAL_PORT = catalog_and_survey.PyegeriaRegistrationPort        # captured before any test patches the name
TECH = "PostgreSQL Relational Database"
SURVEY_QN = "PostgreSQLSurvey::survey-postgres-database"
ASSET = "aaaaaaaa-0000-0000-0000-000000000001"


@pytest.fixture
def registry(tmp_path, monkeypatch):
    reg = ProjectRegistry(db_path=str(tmp_path / "rb.db"))
    reg.register_database(DatabaseEntity(
        slug="adventureworks", display_name="AdventureWorks", db_type="postgresql", host="localhost", port=5432,
        database_name="adventureworks", egeria_asset_guid=ASSET))
    # The scheduler builds `ProjectRegistry()` inside its passes: hand it this one.
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry", lambda *a, **k: reg)
    return reg


def _port(seen: list):
    """An autospec of the real registration port (real signatures); `read_action` records WHO it is called as."""
    port = create_autospec(REAL_PORT, instance=True, spec_set=True)

    def read_action(guid):
        seen.append(egeria_clients.current_principal())
        return nsr.ActionRead(status="IN_PROGRESS", message="")

    port.read_action.side_effect = read_action
    return port


def _in_flight_row(registry, guid="ea-1"):
    registry.record_native_survey_submission("database", "adventureworks", SURVEY_QN, "2026-10-21T20:00:00",
                                             engine_action_guid=guid, submitted_by="dan")


# ── the tick no longer owns the sweep or the drain ──────────────────────────────────────────────────────────────────

def test_the_main_tick_no_longer_calls_the_sweep_or_the_drain(monkeypatch):
    calls = []
    for name in ("_run_due", "_reconcile_rfa_actions"):
        monkeypatch.setattr(scheduler, name, lambda n=name: calls.append(n))
    for name in ("_sweep_native_surveys", "_drain_egeria_outbox"):
        monkeypatch.setattr(scheduler, name, lambda n=name: calls.append("FORBIDDEN " + n))
    scheduler._tick()
    assert calls == ["_run_due", "_reconcile_rfa_actions"]


def test_a_pass_of_the_new_loop_runs_the_sweep_and_the_drain(monkeypatch):
    calls = []
    for name in ("_sweep_native_surveys", "_drain_egeria_outbox"):
        monkeypatch.setattr(scheduler, name, lambda n=name: calls.append(n))
    scheduler._readback_pass()
    assert calls == ["_sweep_native_surveys", "_drain_egeria_outbox"]


# ── idle: no Egeria call; in flight: read back; and as the daemon ───────────────────────────────────────────────────

def test_an_idle_pass_makes_no_port_call_and_builds_no_client(registry, monkeypatch):
    port_cls = create_autospec(REAL_PORT, spec_set=True)
    monkeypatch.setattr(catalog_and_survey, "PyegeriaRegistrationPort", port_cls)
    from resource_explorer import egeria_outbox

    def no_client(*a, **k):
        raise AssertionError("an empty outbox must not build an Egeria client")
    monkeypatch.setattr(egeria_outbox, "_default_clients", no_client)
    assert registry.list_in_flight_native_survey_runs(limit=1) == []
    scheduler._readback_pass()
    assert port_cls.mock_calls == [], "nothing awaiting read-back: the port is not even constructed"


def test_a_pass_with_one_row_in_flight_reads_it_back_as_the_scheduler_daemon(registry, monkeypatch):
    seen: list = []
    monkeypatch.setattr(catalog_and_survey, "PyegeriaRegistrationPort", lambda *a, **k: _port(seen))
    _in_flight_row(registry)
    scheduler._readback_pass()
    row = registry.list_native_survey_runs("database", "adventureworks", SURVEY_QN)[0]
    assert row["engine_action_status"] == "IN_PROGRESS" and row["engine_action_read_at"]
    assert len(seen) == 1
    who = seen[0]
    assert who.kind == "daemon" and who.reason == egeria_clients.DaemonReason.SCHEDULER, "never '' and never a person"


def test_the_pass_declares_its_identity_in_a_bare_thread_that_inherited_none(registry, monkeypatch):
    """A bare threading.Thread drops ContextVars: the pass must set the daemon itself, even beside a signed-in caller."""
    seen: list = []
    monkeypatch.setattr(catalog_and_survey, "PyegeriaRegistrationPort", lambda *a, **k: _port(seen))
    _in_flight_row(registry)
    errors: list = []

    def target():
        try:
            scheduler._readback_pass()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)
    t = threading.Thread(target=target)
    t.start()
    t.join(10)
    assert not errors and len(seen) == 1 and seen[0].kind == "daemon"


# ── a long _run_due does not delay the new loop ─────────────────────────────────────────────────────────────────────

def test_a_long_run_due_does_not_delay_the_readback_pass(registry, monkeypatch):
    seen: list = []
    monkeypatch.setattr(catalog_and_survey, "PyegeriaRegistrationPort", lambda *a, **k: _port(seen))
    _in_flight_row(registry)
    started, release = threading.Event(), threading.Event()

    def long_run_due():
        started.set()
        release.wait(30)
    monkeypatch.setattr(scheduler, "_run_due", long_run_due)
    monkeypatch.setattr(scheduler, "_reconcile_rfa_actions", lambda: None)
    tick = threading.Thread(target=scheduler._tick)
    tick.start()
    try:
        assert started.wait(10)
        t0 = time.monotonic()
        scheduler._readback_pass()                     # while the tick is still inside _run_due
        assert tick.is_alive(), "the fake _run_due is still blocking"
        assert len(seen) == 1 and time.monotonic() - t0 < 5
    finally:
        release.set()
        tick.join(10)


# ── start/stop: bounded, and only the leader runs it ────────────────────────────────────────────────────────────────

def test_start_runs_both_threads_and_stop_ends_both_within_the_bound(monkeypatch):
    monkeypatch.setattr(scheduler, "_CHECK_INTERVAL_SECONDS", 3600)
    monkeypatch.setattr(scheduler, "_READBACK_INTERVAL_SECONDS", 3600)
    scheduler.stop_scheduler()
    scheduler.start_scheduler()
    try:
        names = {t.name for t in threading.enumerate()}
        assert {"resource-explorer-scheduler", "resource-explorer-readback"} <= names
        t0 = time.monotonic()
    finally:
        scheduler.stop_scheduler(timeout=5.0)
    assert time.monotonic() - t0 < 5.0
    names = {t.name for t in threading.enumerate()}
    assert "resource-explorer-scheduler" not in names and "resource-explorer-readback" not in names


def test_the_loop_is_started_only_by_the_leader(monkeypatch):
    """The read-back loop is started by `start_scheduler`, which the worker calls only after winning the `scheduler`
    advisory lock; a process that loses the election never starts it."""
    from resource_explorer import worker

    started = []
    spec = dataclasses.replace(worker._scheduler_spec(), start=lambda: started.append("start"),
                               stop=lambda: started.append("stop"), interval_seconds=0.01)
    assert worker._scheduler_spec().start is scheduler.start_scheduler
    assert worker._scheduler_spec().stop is scheduler.stop_scheduler

    class Standby:
        key = 1

        def __init__(self, name): ...
        def acquire(self): return False
        def release(self): ...
    monkeypatch.setattr(worker, "LeaderLock", Standby)
    stop = threading.Event()
    t = threading.Thread(target=worker._supervise, args=(spec, stop, False))
    t.start()
    time.sleep(0.1)
    stop.set()
    t.join(5)
    assert started == [] and not any(th.name == "resource-explorer-readback" for th in threading.enumerate())


# ── "not checked since": from the proof row's read_at only ──────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 21, 21, 0, 0)


def _row(read_at, **kw):
    base = {"surveyed_at": "2026-10-21T20:00:00", "engine_action_guid": "ea-1", "engine_action_status": "APPROVED",
            "engine_action_message": "", "engine_action_read_at": read_at, "engine_action_read_error": "",
            "survey_report_guid": "", "survey_report_at": "", "report_read_at": "",
            "report_annotation_count": None, "submit_error": ""}
    base.update(kw)
    return base


def test_the_cue_shows_when_the_proof_row_was_read_three_minutes_ago_and_not_at_one():
    old = nsr.derive_native_state(_row("2026-10-21T20:57:00"), now=NOW)          # 3 min old (fake clock)
    fresh = nsr.derive_native_state(_row("2026-10-21T20:59:00"), now=NOW)        # 1 min old
    assert old["state"] == nsr.RUNNING and old["not_checked_since"] == "2026-10-21T20:57:00"
    assert fresh["state"] == nsr.RUNNING and fresh["not_checked_since"] == ""


def test_the_cue_boundary_is_two_loop_intervals():
    assert nsr.NOT_CHECKED_AFTER_S == 2 * scheduler._READBACK_INTERVAL_SECONDS
    exactly = nsr.derive_native_state(_row("2026-10-21T20:58:00"), now=NOW)       # 120 s: not older than 120 s
    over = nsr.derive_native_state(_row("2026-10-21T20:57:59"), now=NOW)
    assert exactly["not_checked_since"] == "" and over["not_checked_since"]


def test_a_finished_run_or_one_never_read_carries_no_cue():
    done = nsr.derive_native_state(_row("2026-10-21T20:00:00", engine_action_status="FAILED"), now=NOW)
    never = nsr.derive_native_state(_row(""), now=NOW)
    assert done["not_checked_since"] == "" and never["not_checked_since"] == ""


def test_the_cue_is_in_the_rows_the_card_reads(registry):
    _in_flight_row(registry)
    registry.record_native_survey_readback("ea-1", read_at="2000-01-01T00:00:00", status="APPROVED")
    row = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]
    assert row["run"]["not_checked_since"] == "2000-01-01T00:00:00"


# ── the count label ─────────────────────────────────────────────────────────────────────────────────────────────────

def _ann(n, kind="Capture File Counts"):
    return {"guid": f"ann-{n}", "annotation_type": kind, "analysis_step": "", "summary": f"a{n}", "explanation": "",
            "confidence": 0, "detail": {}}


class _Port:
    def __init__(self, annotations):
        self.annotations = annotations

    def read_action(self, guid):
        return nsr.ActionRead(status="COMPLETED", message="done")

    def report_guid_for_action(self, guid):
        return "rep-1"

    def read_report(self, report_guid):
        return nsr.ReportRead(guid=report_guid, at="2026-10-21T20:00:00+00:00", originator_guid="ea-1",
                              annotations=self.annotations)


def test_a_filesystem_report_with_seven_incl_the_names_log_gets_the_three_part_label(registry, tmp_path):
    root = tmp_path / "lake"
    root.mkdir()
    registry.register_filesystem(FileSystemEntity(slug="lake", display_name="Lake", local_mount_point=str(root),
                                                  canonical_mount_point="/deployments/lake", egeria_asset_guid=ASSET))
    registry.record_native_survey_submission("filesystem", "lake", nsr.FOLDER_SURVEY_QN, "2026-10-21T20:00:00",
                                             engine_action_guid="ea-1", submitted_by="dan")
    anns = [_ann(i) for i in range(1, 7)] + [_ann(7, nsr.NAMES_LOG_ANNOTATION)]
    run = registry.list_native_survey_runs("filesystem", "lake", nsr.FOLDER_SURVEY_QN)[0]
    derived = nsr.refresh_run(registry, _Port(anns), run, entity_type="filesystem", slug="lake")
    assert derived["state"] == nsr.COMPLETE
    assert derived["count_label"] == ("7 annotations on the report; 6 read into RE; "
                                      "1 not read by design (file-name log)")
    assert registry.count_native_survey_annotations("rep-1") == 6          # the 6 are what is stored


def test_a_database_report_gets_the_single_label(registry):
    _in_flight_row(registry)
    run = registry.list_native_survey_runs("database", "adventureworks", SURVEY_QN)[0]
    derived = nsr.refresh_run(registry, _Port([_ann(i) for i in range(1, 8)]), run, entity_type="database",
                              slug="adventureworks")
    assert derived["count_label"] == "7 annotations on the report · read into RE"


def test_a_row_read_before_the_totals_were_kept_gets_no_label_not_a_guess(registry):
    _in_flight_row(registry)
    run = registry.list_native_survey_runs("database", "adventureworks", SURVEY_QN)[0]
    registry.record_native_survey_report("ea-1", entity_type="database", slug="adventureworks",
                                         process_qualified_name=SURVEY_QN, report_guid="rep-9", report_at="t",
                                         read_at="t", annotations=[_ann(1), _ann(2)])          # no totals passed
    registry.record_native_survey_readback("ea-1", read_at="t", status="COMPLETED")
    derived = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
    assert derived["state"] == nsr.COMPLETE and derived["annotation_count"] == 2 and derived["count_label"] == ""


def test_the_totals_are_kept_without_new_columns(registry):
    """No DDL: the totals ride in the step_runs row's existing `declared` JSON."""
    import json

    _in_flight_row(registry)
    registry.record_native_survey_report("ea-1", entity_type="database", slug="adventureworks",
                                         process_qualified_name=SURVEY_QN, report_guid="rep-9", report_at="t",
                                         read_at="t", annotations=[_ann(1)],
                                         report_totals={"on_report": 3, "not_read_by_design": 0})
    row = registry.list_native_survey_runs("database", "adventureworks", SURVEY_QN)[0]
    assert json.loads(row["declared"])["report_totals"] == {"on_report": 3, "not_read_by_design": 0}
