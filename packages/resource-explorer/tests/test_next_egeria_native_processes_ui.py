"""Egeria-native survey processes in /next's unified Survey & analyses list.

Superseded scope (this test file used to pin the ORIGINAL fix, #244 --
`/next` silently dropping `egeria_native_processes` entirely): REPLY-SURVEY-
ANALYSES-PANE-USER-FACING-MODEL.md §1/§3 (2026-09-25) ruled that the standing
"Also known to Egeria" section this original fix built is itself the wrong
shape -- it makes RE's own authorship vocabulary the pane's opening fact,
which is exactly what the project owner's live feedback said not to do (see
that doc's §0). The section is gone; a native process is now a UNIFIED row
like any other, with `runnable: false` and a gate reason of "not runnable
from Resource Explorer yet" -- the same shape a blocked local analysis row
already used for its own `runnable_reason`.

The underlying FACT this file protects is unchanged and still real: Egeria's
own native survey/governance processes for a technology type must not
silently disappear from the pane just because RE has authored no Survey
Definition candidate for it. Only the PRESENTATION changed (one row in one
list, not a separate section) -- so this file keeps checking the fact,
against the new shape.

No JS test runner is wired into this suite (see test_next_prerequisite_
proposal_ui.py's own note), so this pins the fix at the source level: read
the real shipped source, extract the function/branch under test, and assert
on what it actually does.
"""
from __future__ import annotations

from pathlib import Path

NEXT_DIR = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"
APP_JS = NEXT_DIR / "app.js"


def _balanced(js: str, start: int) -> str:
    """From `start` (pointing at an opening brace/paren), the matching close."""
    depth = 0
    i = start
    started = False
    while True:
        ch = js[i]
        if ch in "([{":
            depth += 1
            started = True
        elif ch in ")]}":
            depth -= 1
        if started and depth == 0:
            return js[start:i + 1]
        i += 1


def _fn_decl(js: str, signature: str) -> str:
    """A `function NAME(...) { ... }` declaration (or `async function`),
    given its exact `function ...(` signature text, through the matching
    closing brace."""
    start = js.index(signature)
    paren = js.index("(", start)
    params_end = paren + len(_balanced(js, paren))
    brace = js.index("{", params_end)
    return js[start:brace] + _balanced(js, brace)


def _app_js_source() -> str:
    return APP_JS.read_text()


class TestTheStandingSectionIsGone:
    """§1/§3: "Also known to Egeria" was the fourth place "which engine"
    appeared, and the doc rules it goes entirely -- dissolved into rows."""

    def test_also_known_to_egeria_text_no_longer_exists(self):
        assert "Also known to Egeria" not in _app_js_source()

    def test_the_old_dedicated_section_renderer_is_gone(self):
        # nativeProcessesSectionHtml built a whole separate visual block with
        # its own heading; that function is retired, not just unused.
        assert "function nativeProcessesSectionHtml(" not in _app_js_source()


class TestNativeProcessesBecomeUnifiedRows:
    """A native process is merged into the same flat list as every Survey
    Definition candidate and local analysis, with a gate reason instead of a
    separate informational block."""

    def _fn(self) -> str:
        return _fn_decl(_app_js_source(), "async function renderAnalysesIndexSection(")

    def test_it_reads_egeria_native_processes_off_the_survey_data_argument(self):
        fn = self._fn()
        assert "surveyData.egeria_native_processes" in fn

    def test_a_native_process_row_carries_the_not_runnable_gate_reason(self):
        fn = self._fn()
        assert "not runnable from Resource Explorer yet" in fn
        assert "runnable: false" in fn

    def test_a_native_process_row_reads_display_name_and_kind(self):
        fn = self._fn()
        assert "p.display_name" in fn
        assert "nativeProcessKindLabel(p.kind)" in fn

    def test_native_process_rows_are_merged_into_the_same_items_list_as_candidates(self):
        # One `items` array feeds the one flat list -- native-process rows are
        # pushed onto it exactly like survey-candidate and analysis rows, not
        # rendered into a separate section string.
        fn = self._fn()
        native_push = fn.index("for (const p of nativeProcesses)")
        items_decl = fn.index("const items = []")
        assert items_decl < native_push
        assert "items.push(" in fn[native_push:fn.index("}", fn.index("items.push(", native_push))]

    def test_the_call_is_not_nested_inside_an_empty_candidates_check(self):
        # Native processes are read and turned into rows unconditionally --
        # not gated behind "candidates is empty" the way the old empty-state
        # fallback special-cased them.
        fn = self._fn()
        native_loop = fn.index("for (const p of nativeProcesses)")
        candidates_loop = fn.index("for (const c of candidates)")
        assert candidates_loop < native_loop, (
            "native-process rows should be appended after candidate rows in "
            "the same unconditional merge, not gated behind a candidates "
            "empty-check")

    def test_native_processes_carry_no_run_button_still(self):
        # Still informational in the sense that matters: nothing wires a run
        # for a native process -- `runnable: false` above is what suppresses
        # unifiedSurveyRowHtml's run button for this row.
        fn = self._fn()
        native_block_start = fn.index("for (const p of nativeProcesses)")
        native_block = fn[native_block_start:fn.index("items.push(", native_block_start)]
        assert "data-unified-run" not in native_block


class TestGateReasonIsVisibleNotJustATooltip:
    """REPLY §1's "what it needs" column is a visible row line, shown only
    when the row is not runnable -- not merely a hover title, which is how
    the old disabled-button gate reason was rendered (invisible until
    hovered, previously reported live as "the button works but doesn't do
    anything")."""

    def test_unified_row_renderer_shows_the_gate_reason_as_a_visible_line(self):
        fn = _fn_decl(_app_js_source(), "function unifiedSurveyRowHtml(")
        assert "row.gateReason" in fn
        assert "needs:" in fn
