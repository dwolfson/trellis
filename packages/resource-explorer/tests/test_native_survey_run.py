"""Native Egeria survey launch (BRIEF-NATIVE-EGERIA-SURVEY-LAUNCH.md).

The rule under test: every status word derives from a persisted proof row, never
from the branch that ran. So most of this is (a) a table over
`derive_native_state`, and (b) end-to-end runs against a fake Egeria port that
check what got PERSISTED, not what a function returned.
"""
from __future__ import annotations

import pytest

from resource_explorer import native_survey_run as nsr
from resource_explorer.registry import DatabaseEntity, ProjectRegistry

TECH = "PostgreSQL Relational Database"
SURVEY_QN = "PostgreSQLSurvey::survey-postgres-database"
CATALOG_QN = "PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess"
ASSET = "aaaaaaaa-0000-0000-0000-000000000001"


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.register_database(DatabaseEntity(
        slug="adventureworks", display_name="AdventureWorks", db_type="postgresql",
        host="localhost", port=5432, database_name="adventureworks",
        egeria_asset_guid=ASSET))
    reg.register_database(DatabaseEntity(
        slug="uncatalogued", display_name="Uncatalogued", db_type="postgresql",
        host="localhost", port=5432, database_name="uncatalogued"))
    return reg


class FakePort:
    """A scriptable Egeria. Records every call so a test can assert on what was
    (and was not) asked."""

    def __init__(self):
        self.assets = {ASSET}
        self.actions: dict[str, tuple[str, str]] = {}      # guid -> (status, message)
        self.reports: dict[str, str] = {}                  # action guid -> report guid
        self.report_annotations: dict[str, list[dict]] = {}
        self.originators: dict[str, str] = {}              # report guid -> action guid
        self.calls: list[tuple] = []
        self.initiate_error: Exception | None = None
        self.read_action_error: Exception | None = None
        self.read_report_error: Exception | None = None
        self._n = 0

    def asset_exists(self, guid):
        self.calls.append(("asset_exists", guid))
        return guid in self.assets

    def initiate(self, qn, target_name, target_guid):
        self.calls.append(("initiate", qn, target_name, target_guid))
        if self.initiate_error:
            raise self.initiate_error
        self._n += 1
        guid = f"eeeeeeee-0000-0000-0000-{self._n:012d}"
        self.actions[guid] = ("REQUESTED", "")
        return guid

    def read_action(self, guid):
        self.calls.append(("read_action", guid))
        if self.read_action_error:
            raise self.read_action_error
        status, message = self.actions[guid]
        return nsr.ActionRead(status=status, message=message)

    def report_guid_for_action(self, guid):
        self.calls.append(("report_guid_for_action", guid))
        return self.reports.get(guid)

    def read_report(self, report_guid):
        self.calls.append(("read_report", report_guid))
        if self.read_report_error:
            raise self.read_report_error
        return nsr.ReportRead(
            guid=report_guid, at="2026-09-30T12:00:00+00:00",
            originator_guid=self.originators.get(report_guid, ""),
            annotations=list(self.report_annotations.get(report_guid, [])))

    # scripting helpers
    def finish(self, action, status="COMPLETED", message="done", report=None, annotations=()):
        self.actions[action] = (status, message)
        if report:
            self.reports[action] = report
            self.originators[report] = action
            self.report_annotations[report] = [dict(a) for a in annotations]


def ann(n, **kw):
    return {"guid": f"ann-{n}", "annotation_type": "Capture Database Table Measurements",
            "analysis_step": "Profiling", "summary": f"table {n}", "explanation": "",
            "confidence": 0, "detail": {"tableName": f"t{n}"}, **kw}


def submit(registry, port, slug="adventureworks", qn=SURVEY_QN, by="dan"):
    return nsr.submit_native_survey(registry, port, "database", slug, qn,
                                    technology_type=TECH, submitted_by=by)


def latest(registry, slug="adventureworks", qn=SURVEY_QN):
    runs = registry.list_native_survey_runs("database", slug, qn)
    return runs[0] if runs else None


# ── the one function that turns proof into words ────────────────────────────

def run_row(**kw):
    base = {"surveyed_at": "2026-09-30T10:00:00", "engine_action_guid": "ea-1",
            "engine_action_status": "", "engine_action_message": "",
            "engine_action_read_at": "", "engine_action_read_error": "",
            "survey_report_guid": "", "survey_report_at": "", "report_read_at": "",
            "report_annotation_count": None, "submit_error": ""}
    base.update(kw)
    return base


class TestDeriveNativeState:
    def test_no_row_is_not_run(self):
        assert nsr.derive_native_state(None)["state"] == nsr.NOT_RUN

    def test_a_row_with_neither_guid_nor_error_proves_nothing(self):
        assert nsr.derive_native_state(run_row(engine_action_guid=""))["state"] == nsr.NOT_RUN

    def test_a_submission_that_never_got_a_guid_says_so(self):
        d = nsr.derive_native_state(run_row(engine_action_guid="", submit_error="HTTP 500"))
        assert d["state"] == nsr.SUBMIT_FAILED and d["error"] == "HTTP 500"
        assert d["engine_action_guid"] == ""

    def test_guid_alone_is_submitted_not_running(self):
        d = nsr.derive_native_state(run_row())
        assert d["state"] == nsr.SUBMITTED
        assert d["read_at"] == "" and d["egeria_status"] == ""
        assert d["submitted_at"] == "2026-09-30T10:00:00"

    def test_guid_with_only_a_failed_read_is_unreadable_not_running(self):
        d = nsr.derive_native_state(run_row(engine_action_read_error="connection refused",
                                            engine_action_read_at="2026-09-30T10:01:00"))
        assert d["state"] == nsr.UNREADABLE and d["error"] == "connection refused"

    @pytest.mark.parametrize("word", sorted(nsr.ACTIVE_STATUSES))
    def test_running_needs_an_egeria_status_read_back(self, word):
        d = nsr.derive_native_state(run_row(engine_action_status=word,
                                            engine_action_read_at="2026-09-30T10:02:00"))
        assert d["state"] == nsr.RUNNING
        assert d["egeria_status"] == word and d["read_at"] == "2026-09-30T10:02:00"

    def test_completed_without_a_report_is_not_complete(self):
        d = nsr.derive_native_state(run_row(engine_action_status="COMPLETED",
                                            engine_action_read_at="t"))
        assert d["state"] == nsr.AWAITING_REPORT

    def test_completed_with_a_report_guid_but_not_read_in_is_not_complete(self):
        d = nsr.derive_native_state(run_row(engine_action_status="COMPLETED",
                                            survey_report_guid="r-1"))
        assert d["state"] == nsr.AWAITING_REPORT

    def test_zero_annotations_is_a_legitimate_complete(self):
        d = nsr.derive_native_state(run_row(
            engine_action_status="COMPLETED", survey_report_guid="r-1",
            report_read_at="t", report_annotation_count=0), stored_annotation_count=0)
        assert d["state"] == nsr.COMPLETE and d["annotation_count"] == 0

    def test_complete_needs_the_stored_rows_to_match_the_recorded_count(self):
        row = run_row(engine_action_status="COMPLETED", survey_report_guid="r-1",
                      report_read_at="t", report_annotation_count=5)
        assert nsr.derive_native_state(row, stored_annotation_count=5)["state"] == nsr.COMPLETE
        assert nsr.derive_native_state(row, stored_annotation_count=4)["state"] == nsr.REPORT_INCOMPLETE
        assert nsr.derive_native_state(row, stored_annotation_count=None)["state"] == nsr.REPORT_INCOMPLETE

    @pytest.mark.parametrize("word", ["FAILED", "INVALID", "IGNORED", "CANCELLED", "ANYTHING_ELSE"])
    def test_any_other_terminal_word_is_shown_as_egeria_said_it(self, word):
        d = nsr.derive_native_state(run_row(engine_action_status=word,
                                            engine_action_message="engine host down"))
        assert d["state"] == nsr.FAILED
        assert d["egeria_status"] == word and d["message"] == "engine host down"

    def test_a_failure_with_no_message_is_never_blank(self):
        d = nsr.derive_native_state(run_row(engine_action_status="FAILED"))
        assert d["state"] == nsr.FAILED and d["message"].strip()

    def test_a_failed_action_is_never_complete_whatever_else_is_stored(self):
        d = nsr.derive_native_state(run_row(
            engine_action_status="FAILED", survey_report_guid="r-1",
            report_read_at="t", report_annotation_count=3), stored_annotation_count=3)
        assert d["state"] == nsr.FAILED


# ── submit: what gets persisted ─────────────────────────────────────────────

class TestSubmit:
    def test_submits_the_configured_process_against_the_stored_asset(self, registry):
        port = FakePort()
        state = submit(registry, port)
        assert ("initiate", SURVEY_QN, "serverToSurvey", ASSET) in port.calls
        row = latest(registry)
        assert row["engine_action_guid"] == state["engine_action_guid"] != ""
        assert row["step_key"] == "egeria-native:" + SURVEY_QN
        assert row["executor"] == "egeria" and row["source"] == "egeria"
        assert row["submitted_by"] == "dan"

    def test_the_dispatch_is_proven_by_reading_the_action_back(self, registry):
        port = FakePort()
        state = submit(registry, port)
        assert [c[0] for c in port.calls if c[0] == "read_action"], "no read-back"
        row = latest(registry)
        assert row["engine_action_status"] == "REQUESTED"
        assert row["engine_action_read_at"]
        assert state["state"] == nsr.RUNNING and state["egeria_status"] == "REQUESTED"

    def test_if_the_read_back_fails_the_row_says_submitted_with_a_failed_read(self, registry):
        port = FakePort()
        port.read_action_error = RuntimeError("view server unreachable")
        state = submit(registry, port)
        assert state["state"] == nsr.UNREADABLE
        assert "unreachable" in state["error"]
        assert latest(registry)["engine_action_guid"]      # the proof of submission stands

    def test_egeria_refusing_the_submission_leaves_a_failure_row_and_no_guid(self, registry):
        port = FakePort()
        port.initiate_error = RuntimeError("OMAG-400 not recognized")
        with pytest.raises(nsr.NativeSurveyError):
            submit(registry, port)
        row = latest(registry)
        assert row["engine_action_guid"] == ""
        assert "not recognized" in row["submit_error"]
        assert nsr.derive_native_state(row)["state"] == nsr.SUBMIT_FAILED

    def test_a_resource_with_no_egeria_asset_says_why_and_asks_egeria_nothing(self, registry):
        port = FakePort()
        with pytest.raises(nsr.NativeSurveyCannotRun, match="Publish it to Egeria"):
            submit(registry, port, slug="uncatalogued")
        assert port.calls == []
        assert latest(registry, slug="uncatalogued") is None

    def test_a_stale_stored_guid_is_caught_before_submitting(self, registry):
        port = FakePort()
        port.assets.clear()
        with pytest.raises(nsr.NativeSurveyCannotRun, match="no asset with the GUID"):
            submit(registry, port)
        assert not [c for c in port.calls if c[0] == "initiate"]
        assert latest(registry) is None

    def test_a_process_that_needs_a_template_cannot_run_and_says_why(self, registry):
        port = FakePort()
        with pytest.raises(nsr.NativeSurveyCannotRun, match="template"):
            submit(registry, port, qn=CATALOG_QN)
        assert port.calls == []

    def test_the_delete_process_is_never_runnable(self, registry):
        port = FakePort()
        with pytest.raises(nsr.NativeSurveyCannotRun):
            submit(registry, port,
                   qn="PostgreSQLDatabase:DeleteAssetWithTemplateGovernanceActionProcess")
        assert port.calls == []

    def test_a_second_submit_while_one_is_in_flight_is_refused(self, registry):
        port = FakePort()
        submit(registry, port)
        with pytest.raises(nsr.NativeSurveyBusy):
            submit(registry, port)
        assert len([c for c in port.calls if c[0] == "initiate"]) == 1

    def test_the_prefect_columns_are_never_touched(self, registry):
        submit(registry, FakePort())
        row = latest(registry)
        assert row["flow_run_id"] == "" and row["dispatch_failed"] == ""


# ── read-back: running -> complete, findings, dedup ─────────────────────────

class TestReadBack:
    def _submitted(self, registry, port):
        return submit(registry, port)["engine_action_guid"]

    def test_running_then_complete_reads_the_report_in(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)

        port.actions[action] = ("IN_PROGRESS", "")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        assert nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]["state"] == nsr.RUNNING

        port.finish(action, report="rep-1", annotations=[ann(1), ann(2), ann(3)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.COMPLETE
        assert run["report_guid"] == "rep-1" and run["annotation_count"] == 3
        assert run["report_at"] == "2026-09-30T12:00:00+00:00"
        assert run["read_at"]
        assert len(registry.query_native_survey_annotations("rep-1")) == 3

    def test_reading_the_same_completed_report_again_writes_nothing_new(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, report="rep-1", annotations=[ann(1), ann(2)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        nsr.sweep_in_flight(registry, port)
        assert len([c for c in port.calls if c[0] == "read_report"]) == 1
        assert registry.count_native_survey_annotations("rep-1") == 2

    def test_a_retried_report_read_cannot_duplicate_rows(self, registry):
        """Force the second read through the writer directly: the store itself,
        not only the caller's caution, must refuse a second copy."""
        port = FakePort()
        action = self._submitted(registry, port)
        for _ in range(3):
            registry.record_native_survey_report(
                action, entity_type="database", slug="adventureworks",
                process_qualified_name=SURVEY_QN, report_guid="rep-1", report_at="t",
                read_at="t", annotations=[ann(1), ann(2)])
        assert registry.count_native_survey_annotations("rep-1") == 2
        assert latest(registry)["report_annotation_count"] == 2

    def test_the_count_comes_from_the_store_not_from_the_list_passed_in(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        registry.record_native_survey_report(
            action, entity_type="database", slug="adventureworks",
            process_qualified_name=SURVEY_QN, report_guid="rep-1", report_at="t",
            read_at="t", annotations=[ann(1), ann(2), {"guid": "", "summary": "no guid"}])
        assert latest(registry)["report_annotation_count"] == 2

    def test_a_lost_stored_row_downgrades_complete(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, report="rep-1", annotations=[ann(1), ann(2)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        with registry._conn() as conn:
            conn.execute("DELETE FROM native_survey_annotations WHERE annotation_guid = 'ann-1'")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.REPORT_INCOMPLETE

    def test_completed_with_no_report_yet_is_awaiting_not_complete(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action)                       # COMPLETED, no report linked
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.AWAITING_REPORT
        # ...and the report is found on a later read, by the relationship
        port.finish(action, report="rep-1", annotations=[ann(1)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        assert nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]["state"] == nsr.COMPLETE

    def test_a_report_that_names_a_different_originator_is_refused(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, report="rep-1", annotations=[ann(1)])
        port.originators["rep-1"] = "some-other-action"
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.AWAITING_REPORT and "originated" in run["error"]
        assert registry.count_native_survey_annotations("rep-1") == 0

    def test_a_failed_report_read_is_a_read_error_not_a_zero_annotation_complete(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, report="rep-1", annotations=[ann(1)])
        port.read_report_error = RuntimeError("timeout")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.AWAITING_REPORT
        assert run["egeria_status"] == "COMPLETED"      # last good status kept
        assert "timeout" in run["error"]

    def test_a_failed_read_keeps_the_last_good_status(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.actions[action] = ("IN_PROGRESS", "")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        port.read_action_error = RuntimeError("503")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.RUNNING and run["egeria_status"] == "IN_PROGRESS"
        assert "503" in run["error"]

    def test_a_failed_survey_shows_egeria_status_and_message_and_reads_no_report(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, status="FAILED", message="OMES-SURVEY-ACTION-0007 could not connect")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["state"] == nsr.FAILED and run["egeria_status"] == "FAILED"
        assert "could not connect" in run["message"]
        assert not [c for c in port.calls if c[0] == "read_report"]
        # a terminal failure is final: nothing more is read for it
        n = len(port.calls)
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        assert len(port.calls) == n

    def test_the_sweep_finishes_runs_nobody_is_watching(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, report="rep-1", annotations=[ann(1)])
        assert nsr.sweep_in_flight(registry, port) == 1
        assert nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]["state"] == nsr.COMPLETE
        assert nsr.sweep_in_flight(registry, port) == 0

    def test_the_sweep_does_not_revisit_failed_or_finished_runs(self, registry):
        port = FakePort()
        action = self._submitted(registry, port)
        port.finish(action, status="FAILED", message="x")
        nsr.sweep_in_flight(registry, port)
        assert registry.list_in_flight_native_survey_runs() == []


# ── a second run ────────────────────────────────────────────────────────────

class TestSecondRun:
    def test_a_second_run_is_dated_beside_the_first_and_never_duplicates_it(self, registry):
        port = FakePort()
        first = submit(registry, port)["engine_action_guid"]
        port.finish(first, report="rep-1", annotations=[ann(1), ann(2)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")

        second = submit(registry, port)["engine_action_guid"]      # allowed: first is complete
        assert second != first
        port.finish(second, report="rep-2", annotations=[ann(1), ann(2), ann(3)])
        nsr.refresh_resource(registry, port, "database", "adventureworks")

        assert registry.count_native_survey_annotations("rep-1") == 2
        assert registry.count_native_survey_annotations("rep-2") == 3
        # every annotation is stored once per report, and no report is stored twice
        with registry._conn() as conn:
            total = conn.execute("SELECT COUNT(*) FROM native_survey_annotations").fetchone()[0]
            distinct = conn.execute(
                "SELECT COUNT(DISTINCT report_guid || annotation_guid) FROM native_survey_annotations"
            ).fetchone()[0]
        assert total == distinct == 5
        # the row reports the newest run
        run = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)[0]["run"]
        assert run["report_guid"] == "rep-2" and run["annotation_count"] == 3

    def test_a_failed_run_can_be_retried(self, registry):
        port = FakePort()
        first = submit(registry, port)["engine_action_guid"]
        port.finish(first, status="FAILED", message="x")
        nsr.refresh_resource(registry, port, "database", "adventureworks")
        assert submit(registry, port)["engine_action_guid"] != first


# ── the rows a resource shows ───────────────────────────────────────────────

class TestRows:
    def test_lists_runnable_and_unrunnable_with_reasons_and_never_the_delete(self, registry):
        rows = nsr.native_survey_rows(registry, "database", "adventureworks", TECH)
        by = {r["qualified_name"]: r for r in rows}
        assert set(by) == {SURVEY_QN, CATALOG_QN}
        assert by[SURVEY_QN]["runnable"] and by[SURVEY_QN]["cannot_run_reason"] == ""
        assert not by[CATALOG_QN]["runnable"] and by[CATALOG_QN]["cannot_run_reason"]
        assert all(r["run"]["state"] == nsr.NOT_RUN for r in rows)

    def test_an_uncatalogued_resource_says_why_on_the_row(self, registry):
        rows = nsr.native_survey_rows(registry, "database", "uncatalogued", TECH)
        survey = next(r for r in rows if r["qualified_name"] == SURVEY_QN)
        assert not survey["runnable"] and "Publish it to Egeria" in survey["cannot_run_reason"]

    def test_listing_makes_no_egeria_call(self, registry):
        # native_survey_rows takes no port at all: it cannot reach Egeria.
        import inspect
        assert "port" not in inspect.signature(nsr.native_survey_rows).parameters
