"""REPORT-RECORD-AND-TWO-CALLS C2 and C4 in the shell: save as report as
the fourth act, the whole-list state, Records beside the journal and the
verdict trail. Verified in a browser on egeria_workspaces_git."""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


class TestTheAct:
    def test_the_fourth_act_and_the_whole_list_state(self):
        app = _app()
        body = app[app.index("function wireSelection("):app.index("async function openMembers(")]
        assert 'data-report-sel' in body and '>save as report<' in body
        assert "The whole list · " in body and "data-report-whole" in body
        assert "work list, RFA and journal need a selection" in body
        assert "Sign in to save a report — a record needs an author." in body
        assert "render();   // the whole-list state, before any pick" in body

    def test_the_server_snapshots_the_list_not_the_client(self):
        app = _app()
        body = app[app.index("function wireSelection("):app.index("async function openMembers(")]
        assert "saveReport(slug, analysisId, {" in body
        assert "groups" not in body.split("async function save(")[1].split("}\n  function render")[0], "the client sends names, never rows"


class TestWhereTheyLive:
    def test_records_sit_beside_the_journal_and_the_trail(self):
        app = _app()
        pane = app[app.index("async function loadDispositionPane("):app.index("function renderJournalWrite(")]
        assert 'id="records"' in pane and 'id="journal-write"' in pane and 'id="disposition-history"' in pane
        assert "await renderRecords(slug);" in pane

    def test_a_report_shows_its_header_and_out_of_date_and_exports(self):
        app = _app()
        body = app[app.index("async function renderRecords("):]
        assert "rep.header" in body and "r.out_of_date" in body
        assert "recordExportHref(slug, r.id, 'md')" in body and "recordExportHref(slug, r.id, 'csv')" in body
        assert "curateRecordHtml(r)" in body, "a catalogue record shows its steps inline"
        assert "No record has been written for this resource yet" in body
