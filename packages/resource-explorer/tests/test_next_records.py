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


class TestTheThreeActsOnAReport:
    """REPORT-ACTS (2026-09-14). Verified in a browser: the whole-report
    footer, '2 of 19 rows picked' on ticking, acts gated for anonymous with
    the sentence, the journal seeded with the citation alone."""

    def test_the_default_is_the_whole_report_and_rows_are_secondary(self):
        app = _app()
        body = app[app.index("function recordActsHtml("):app.index("function recordUsesHtml(")]
        assert "The whole report · " in body
        assert "or pick rows above to act on some of them" in body
        assert "Sign in to act on a report — a work item needs someone who raised it." in body

    def test_the_journal_opens_seeded_with_a_citation_not_a_sentence(self):
        app = _app()
        body = app[app.index("function wireRecordActs("):app.index("function wireDispositionPicker(") if "function wireDispositionPicker(" in app[app.index("function wireRecordActs("):] else None]
        assert "ta.value = `Per “${rec.name}” (${String(rec.requested_at).slice(0, 10)}): `;" in body
        assert "ta.dataset.citesRecord = id;" in body
        # the use is recorded when the entry lands, never written for the person
        assert "actOnRecord(slug, cites, { action: 'journal', journalId: out.id || '' })" in app

    def test_a_failed_act_says_not_recorded_and_the_buttons_stay_live(self):
        app = _app()
        body = app[app.index("function wireRecordActs("):]
        assert "not recorded" in body and "b.disabled = false;" in body

    def test_uses_and_corrections_sit_on_the_record(self):
        app = _app()
        body = app[app.index("function recordUsesHtml("):app.index("function wireRecordActs(")]
        assert "Used · " in body and "Corrected by “" in body

    def test_a_correction_is_save_as_report_naming_what_it_corrects(self):
        app = _app()
        body = app[app.index("function wireRecordActs("):]
        assert "corrects: id" in body and "data-record-correct" in body
        acts = app[app.index("function recordActsHtml("):app.index("function recordUsesHtml(")]
        assert "r.out_of_date && !r.corrected_by?.id" in acts, "offered on a stale, uncorrected record"
