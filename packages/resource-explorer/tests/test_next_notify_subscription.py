""""🔔 Notify me" attached to a question row in /next's Questions-checklist
engine (re/next-automate-create-subscription).

Classic creates a subscription from a "🔔 Notify me" button on an Assessment/
Analysis CARD (index.html's `_createSubscriptionFromCard` /
"Cross-stage definitions") -- a card names exactly one analysis_id, so
classic's button fires the POST directly with no form. /next's Assessment
and Analysis stages are built (item 11) through the generic Questions-
checklist engine -- QUESTION ROWS, not a card grid -- and that card grid was
never going to get a /next equivalent (see stages/automate.js's own comment
block, corrected by this same change). So this attaches the action to the
question row instead: app.js's `provenanceLine()` grows a "🔔 notify me"
action wherever a row carries `analysis_ids`, wired (in `bindRowActions`) to
`openNotifyDialog()`, which opens a small dialog (worklist.js's
`openDialog()`) rather than firing directly, because a question's
`analysis_ids` is not always 1:1 with one analysis (a MIXED:/PARTIAL: answer
can name several) -- unlike a card, which always names exactly one.

No browser verification happened for THIS file's assertions with a signed-in
session -- those were checked live against the running dev server (see the
session's final report). These tests grep/slice function bodies out of the
concatenated source, the established pattern for /next JS modules without a
browser -- see test_next_automate_pane.py / test_next_discovery_import_search.py's
identical `_app()` helper, reproduced here.
"""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"


def _app():
    src = (NEXT / "app.js").read_text(encoding="utf-8")
    for f in sorted((NEXT / "stages").glob("*.js")):
        src += "\n" + f.read_text(encoding="utf-8")
    return src


def _reapi_src():
    return (NEXT.parent / "re-api.js").read_text(encoding="utf-8")


def _notify_dialog_body():
    app = _app()
    start = app.index("async function openNotifyDialog(")
    end = app.index("async function toggleMeasurementsInPlace(", start)
    return app[start:end]


class TestReApiCreateSubscriptionWrapper:
    """re-api.js gets a real wrapper, matching listSubscriptions'/
    setSubscriptionActive's existing shape and hitting the same route
    classic's `_createSubscriptionFromCard` posts to."""

    def test_wrapper_exists_and_posts_to_the_real_route(self):
        api = _reapi_src()
        assert "export const createSubscription = (" in api
        body = api[api.index("export const createSubscription"):]
        body = body[:body.index(";", body.index("post("))]
        assert "post('/api/automate/subscriptions'" in body

    def test_wrapper_sends_the_same_four_fields_the_backend_model_declares(self):
        # web/routes/automate.py's CreateSubscriptionRequest: entity_type,
        # entity_slug, analysis_id, label.
        api = _reapi_src()
        body = api[api.index("export const createSubscription"):]
        body = body[:body.index(";", body.index("post("))]
        assert "entity_type:" in body
        assert "entity_slug:" in body
        assert "analysis_id:" in body
        assert "label" in body


class TestNotifyActionAttachedToQuestionRows:
    """The actual attachment point this task had to find: a question row,
    not a card (there is no card grid in /next for Assessment/Analysis)."""

    def test_provenance_line_offers_notify_me_when_the_row_names_an_analysis(self):
        app = _app()
        fn = app[app.index("function provenanceLine("):app.index("function updateAnsweredCount(")]
        assert "data-notify=" in fn
        assert "notify me" in fn.lower()
        # Gated on analysis_ids, not on a specific answered state -- a
        # subscription is a standing watch, not tied to today's answer.
        assert "entry.analysis_ids || []).length" in fn

    def test_it_does_not_offer_notify_while_the_row_is_mid_run(self):
        app = _app()
        fn = app[app.index("function provenanceLine("):app.index("function updateAnsweredCount(")]
        notify_guard = fn[fn.index("data-notify=") - 400:fn.index("data-notify=")]
        assert "st !== 'running'" in notify_guard

    def test_bind_row_actions_wires_the_click_to_open_notify_dialog(self):
        app = _app()
        fn = app[app.index("function bindRowActions("):app.index("async function openNotifyDialog(")]
        assert "data-notify" in fn
        assert "openNotifyDialog(entry)" in fn


class TestNotifyDialogCallsTheRealEndpoint:
    def test_it_reuses_the_shared_dialog_shell(self):
        body = _notify_dialog_body()
        assert "openDialog('🔔 Notify me'" in body

    def test_submit_calls_the_real_create_subscription_wrapper(self):
        body = _notify_dialog_body()
        assert "await createSubscription(" in body

    def test_entity_type_is_repo_matching_the_repo_only_questions_gate(self):
        # The Questions engine this hangs off is itself gated to
        # state.resourceType === 'repo' in loadPane() -- see the "Repos
        # only, in /next" branch. There is no other entity_type this dialog
        # could legitimately send today.
        body = _notify_dialog_body()
        call = body[body.index("await createSubscription("):]
        call = call[:call.index(")") + 1]
        assert "'repo'" in call

    def test_a_failed_create_shows_the_error_and_re_enables_the_button(self):
        body = _notify_dialog_body()
        catch_block = body[body.index("} catch (err) {", body.index("await createSubscription(")):]
        catch_block = catch_block[:catch_block.index("}\n  });")]
        assert "btn.disabled = false" in catch_block
        assert "errEl.textContent = err.message" in catch_block

    def test_success_closes_the_dialog_so_automate_shows_it_on_next_visit(self):
        # Automate's own renderSubscriptions() re-fetches listSubscriptions()
        # on every render rather than caching (see stages/automate.js) -- so
        # there is nothing to push into from here; closing the dialog is
        # enough for the new row to appear the next time that pane renders.
        body = _notify_dialog_body()
        submit = body[body.index("#notify-submit').addEventListener"):]
        try_block = submit[submit.index("try {"):submit.index("} catch")]
        assert "closeCellDetail()" in try_block


class TestNonOneToOneQuestionToAnalysisIsHandledHonestly:
    """The real finding from investigating the Questions engine: a
    question's `analysis_ids` is not always length 1 (MIXED:/PARTIAL:
    answers can name several analyses). A subscription watches ONE analysis,
    so silently picking analysis_ids[0] -- the convention `rerun`/
    `openRunChoice` already use elsewhere in this file for re-running --
    would risk subscribing to the wrong one. This must never happen here."""

    def test_multiple_analysis_ids_render_a_picker_not_a_silent_default(self):
        body = _notify_dialog_body()
        assert "ids.length > 1" in body
        assert 'name="notify-analysis"' in body
        # It must actually let the reader choose -- radio inputs, not just a
        # list of names with no way to select one.
        assert 'type="radio"' in body

    def test_submit_reads_the_checked_radio_when_there_is_a_choice(self):
        body = _notify_dialog_body()
        submit = body[body.index("#notify-submit').addEventListener"):]
        assert 'notify-analysis"]:checked' in submit

    def test_a_single_analysis_id_skips_the_picker_but_still_confirms_which_one(self):
        body = _notify_dialog_body()
        single_branch = body[body.index(": `<input type=\"hidden\""):body.index(
            "<label class=\"mb-[3px] block text-caveat text-ink-muted\">Label")]
        assert "notify-analysis-only" in single_branch

    def test_it_never_reaches_for_analysis_ids_zero_the_way_rerun_does(self):
        # rerun()/openRunChoice() elsewhere in app.js legitimately pick
        # analysis_ids[0] (re-running is idempotent and safe to under-target).
        # openNotifyDialog must not borrow that shortcut for a standing watch
        # -- it only ever reads `ids[0]` as the DEFAULT for a single-id row
        # (already known to be the only choice), never to skip a real pick
        # among several.
        body = _notify_dialog_body()
        assert "entry.analysis_ids || [])[0]" not in body
