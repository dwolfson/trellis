"""Source-level regression tests for /next's §17.1 prerequisite-proposal UI.

`docs/Backlog.md` logged the gap this closes: classic (index.html) has a
working "answering this needs X first — estimated Ns; run it?" prompt wired
to `/api/prerequisites/plan` and `/api/prerequisites/run`
(`resource_explorer/web/routes/prerequisites.py`), and `/next` (the
intent-based UI under `resource_explorer/web/static/next/`) had no
equivalent — a `/next` user whose run crossed a cost tier got nothing.

No JS test runner is wired into this suite (see test_re_api_entity_type_
threading.py's own note), so this pins the fix at the source level, the same
technique used there and in test_fact_answer_rendering.py for index.html:
read the real shipped source, extract the function/branch under test, and
assert on what it actually does — not a re-implementation of it in Python
that could drift from the JS without either failing.

Design judgment call this pins (see this branch's PR description for the
full reasoning): `/next` calls `POST /api/prerequisites/plan` PROACTIVELY,
before dispatching a run, rather than reading a `proposal` embedded in a
results payload the way classic's `_renderPrerequisiteProposal` does.
`prerequisite_resolver.Resolution.as_plan()`'s own docstring says `/plan` has
"no live consumer today; the classic UI reads `proposal.as_dict()`
directly" — so `/next` becomes `/plan`'s first live consumer, using the
endpoint's own documented purpose ("asks what a step would need WITHOUT
running anything") exactly as designed, rather than depending on whichever
analysis results readers happen to attach `_status.proposal` to their output
(confirmed NOT to be uniformly wired for the repo `SurveyOrchestrator` skip
path at the time of this change — the `step_skipped`/`prerequisite_auto_run`
annotations it writes are not read back by any results reader today).
"""
from __future__ import annotations

from pathlib import Path

NEXT_DIR = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"
APP_JS = NEXT_DIR / "app.js"
RE_API = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "re-api.js"


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


def _fn_arrow(js: str, name: str) -> str:
    """`export const NAME = (...) => ...;` through its terminating `;` at
    depth 0 — mirrors test_re_api_entity_type_threading.py's `_fn`."""
    marker = f"export const {name} ="
    start = js.index(marker)
    i = start + len(marker)
    depth = 0
    started = False
    while True:
        ch = js[i]
        if ch in "([{":
            depth += 1
            started = True
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0 and started:
            i += 1
            break
        i += 1
    return js[start:i]


def _fn_decl(js: str, signature: str) -> str:
    """A `function NAME(...) { ... }` declaration (or `async function`),
    given its exact `function ...(` signature text, through the matching
    closing brace.

    The signature text may itself contain the destructured-parameter's own
    `{...}` (e.g. `"async function rerun(entry, i,"` matched against
    `rerun(entry, i, { background = false } = {})`), so the params are
    skipped as a BALANCED paren group first -- scanning for the first bare
    `{` would stop inside that default-value object literal, not at the
    function body."""
    start = js.index(signature)
    paren = js.index("(", start)
    params_end = paren + len(_balanced(js, paren))
    brace = js.index("{", params_end)
    return js[start:brace] + _balanced(js, brace)


def _re_api_source() -> str:
    return RE_API.read_text()


def _app_js_source() -> str:
    return APP_JS.read_text()


class TestReApiExposesPrerequisiteEndpoints:
    """The shared client (re-api.js, imported by /next and available to
    classic) gets the two §17.1 endpoints as real functions — not re-declared
    inline the way index.html's classic UI currently does."""

    def test_plan_prerequisites_posts_to_the_plan_endpoint(self):
        fn = _fn_arrow(_re_api_source(), "planPrerequisites")
        assert "/api/prerequisites/plan" in fn
        assert "entity_type" in fn and "step_key" in fn

    def test_run_prerequisites_posts_to_the_run_endpoint(self):
        fn = _fn_arrow(_re_api_source(), "runPrerequisites")
        assert "/api/prerequisites/run" in fn
        assert "demanded_by" in fn
        # Steps travel as an array under the client's own name for them —
        # the accept path always names what it is running, never a bare "go".
        assert "steps" in fn


class TestNextChecksThePlanBeforeRunning:
    """The core wiring: /next's Questions-checklist run path (`rerun`, the
    one generic dispatcher every stage's row uses — Scouting through Curate,
    per app.js's own header comment) asks `/api/prerequisites/plan` before
    it ever calls `runAnalysis`."""

    def test_rerun_calls_the_plan_check_before_queuing_a_run(self):
        src = _app_js_source()
        fn = _fn_decl(src, "async function rerun(entry, i,")
        assert "checkPrerequisitePlan" in fn
        # The plan check must run BEFORE the row is marked queued/in-flight —
        # asking after the fact would be the exact "run that silently
        # degrades" failure §17.1 exists to replace.
        plan_pos = fn.index("checkPrerequisitePlan")
        queued_pos = fn.index("runsInFlight.set")
        assert plan_pos < queued_pos, (
            "the plan check must happen before the row is marked as running")

    def test_the_plan_check_can_be_skipped_for_a_post_accept_retry(self):
        fn = _fn_decl(_app_js_source(), "async function rerun(entry, i,")
        assert "skipPlanCheck" in fn

    def test_plan_check_calls_the_plan_endpoint_with_the_analysis_id_as_step_key(self):
        fn = _fn_decl(_app_js_source(), "async function checkPrerequisitePlan(")
        assert "planPrerequisites(" in fn
        assert "analysisId" in fn

    def test_a_proposal_response_records_a_pending_proposal_and_stops_the_run(self):
        fn = _fn_decl(_app_js_source(), "async function checkPrerequisitePlan(")
        assert "'proposal'" in fn
        assert "pendingProposals.set" in fn
        assert "return true" in fn

    def test_a_plan_check_failure_does_not_block_the_run(self):
        """The plan endpoint being briefly unreachable must not wedge every
        run in the Questions checklist from then on — the catch path must
        fall through to running, matching pre-§17.1 behaviour."""
        fn = _fn_decl(_app_js_source(), "async function checkPrerequisitePlan(")
        assert "catch" in fn
        assert "return false" in fn


class TestAutoRunWithinTierIsReflectedHonestly:
    """The within-budget half of §17.1: no prompt, but the delay must not be
    silent (design's condition 3, and CLAUDE.md rule 16's spirit — a run that
    took longer than usual with no visible reason)."""

    def test_an_auto_run_plan_status_leaves_a_note_rather_than_a_silent_run(self):
        fn = _fn_decl(_app_js_source(), "async function checkPrerequisitePlan(")
        assert "'auto_run'" in fn
        assert "autoRanNotes.set" in fn

    def test_the_note_is_rendered_and_consumed_exactly_once(self):
        """A stale caveat that outlives the run it described would misdescribe
        every later render of the row as still being about a prerequisite."""
        fn = _fn_decl(_app_js_source(), "function autoRanNoteHtml(")
        assert "autoRanNotes.get" in fn
        assert "autoRanNotes.delete" in fn


class TestCrossingTierRendersAnAcceptDeclinePrompt:
    """The crossing-tier half: an actual prompt, matching classic's own three
    required elements (design §17.1) — WHAT would run, WHAT it costs, WHY it
    is being asked."""

    def test_the_proposal_row_states_the_steps_the_cost_and_the_measurement_basis(self):
        fn = _fn_decl(_app_js_source(), "function prerequisiteProposalHtml(")
        assert "p.steps" in fn
        assert "estimated_seconds" in fn
        assert "estimated_is_measured" in fn

    def test_the_proposal_row_offers_accept_and_decline(self):
        fn = _fn_decl(_app_js_source(), "function prerequisiteProposalHtml(")
        assert "data-prereq-accept" in fn
        assert "data-prereq-decline" in fn

    def test_accept_runs_the_named_steps_then_retries_the_original_request(self):
        fn = _fn_decl(_app_js_source(), "async function acceptPrerequisiteProposal(")
        assert "runPrerequisites(" in fn
        assert "proposal.steps" in fn
        # The retry must skip the plan check -- otherwise an accepted chain
        # immediately re-asks about the very thing it just ran.
        assert "skipPlanCheck: true" in fn

    def test_accept_attributes_the_run_to_the_demanding_step(self):
        """`/api/prerequisites/run`'s own contract (prerequisites.py) records
        `demanded_by` on the producers' step_runs rows so an accepted chain's
        cost is attributable -- the client must actually send it, not an
        empty string, or every accepted proposal's cost floats free."""
        fn = _fn_decl(_app_js_source(), "async function acceptPrerequisiteProposal(")
        assert "proposal.demanding_step" in fn

    def test_decline_clears_the_pending_proposal_without_calling_the_server(self):
        fn = _fn_decl(_app_js_source(), "function declinePrerequisiteProposal(")
        assert "pendingProposals.delete" in fn
        # Declining is purely local -- design's own words: "or leave it —
        # nothing has run." No fetch/post belongs in this path.
        assert "fetch(" not in fn
        assert "post(" not in fn

    def test_a_pending_proposal_takes_over_row_state_before_a_run_starts(self):
        """A pending proposal must pre-empt every other row state (loading,
        answered, unrun, ...) -- it is asked BEFORE a run is dispatched, so
        it cannot be layered on top of `running`."""
        fn = _fn_decl(_app_js_source(), "function rowInner(entry, i, env)")
        assert "pendingProposals.get" in fn
        pending_check = fn.index("pending ?")
        running_check = fn.index("running ?")
        assert running_check < pending_check, (
            "running must be checked first syntactically so a genuinely "
            "in-flight run is never re-described as a pending proposal")


class TestProposalHasItsOwnGlyphAndTone:
    """Glyph AND colour both carry the state (app.js's own stated rule) — a
    proposal must not silently borrow `unrun`'s or `human`'s marks, which
    would misdescribe a pending decision as one of those other states."""

    def test_glyph_table_has_a_proposal_entry(self):
        src = _app_js_source()
        glyph_start = src.index("const GLYPH = {")
        glyph_block = _balanced(src, src.index("{", glyph_start))
        assert "proposal:" in glyph_block

    def test_state_tone_table_has_a_proposal_entry(self):
        src = _app_js_source()
        tone_start = src.index("const STATE_TONE = {")
        tone_block = _balanced(src, src.index("{", tone_start))
        assert "proposal:" in tone_block
