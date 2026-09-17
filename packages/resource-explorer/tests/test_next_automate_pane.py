"""Automate's pane in /next (PLAN-FINISH-REPOS.md item 4): pinning the real
part of the port (subscription and schedule listing/toggling, against the
same routes classic uses) and the honesty of the one deliberate gap
(subscription creation, which rides on an Assessment/Analysis card neither
of which is built in /next).

No browser verification happened for this file with a signed-in session --
see docs/design-notes/ITEM-4-AUTOMATE-IMPLEMENTED.md for what was and was
not checked live. These tests grep/slice function bodies out of the
concatenated source, the established pattern for /next JS modules without a
browser -- see test_next_curate_pane.py and test_next_understanding_pane.py's
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


def _automate_src():
    return (NEXT / "stages" / "automate.js").read_text(encoding="utf-8")


def _reapi_src():
    return (NEXT.parent / "re-api.js").read_text(encoding="utf-8")


class TestAutomateIsWiredIn:
    """The three wiring points PLAN-FINISH-REPOS.md's stub asked for: the
    STAGES flag, the import line, and a dispatch that bypasses the generic
    Questions engine (same shape as Understanding's)."""

    def test_automate_is_marked_built_in_the_stages_array(self):
        app = _app()
        stages = app[app.index("const STAGES = ["):app.index("];", app.index("const STAGES = ["))]
        automate_line = [
            l for l in stages.splitlines() if "id: 'automate'" in l
        ][0]
        assert "built: true" in automate_line

    def test_app_js_imports_the_automate_module(self):
        app = _app()
        assert "from '/static/next/stages/automate.js';" in app
        assert "renderAutomate" in app

    def test_load_pane_dispatches_automate_before_the_generic_pane_and_returns(self):
        app = _app()
        i = app.index("if (state.stage === 'automate') {")
        block = app[i:app.index("}", app.index("await renderAutomate();", i))]
        assert "await renderAutomate();" in block
        assert "return;" in app[i:i + 400]
        # It must come before the generic "not in /next" built-check, the way
        # Understanding's branch does, or a stage flagged built:true here
        # would still fall through to the shared Questions engine.
        j = app.index("if (stageDef?.frame || !stageDef?.built) {")
        assert i < j


class TestSubscriptionsAreReal:
    def test_lists_subscriptions_against_the_real_route(self):
        api = _reapi_src()
        assert "export const listSubscriptions = (" in api
        assert "/api/automate/subscriptions" in api

    def test_toggling_calls_activate_or_deactivate(self):
        api = _reapi_src()
        assert "export const setSubscriptionActive = (id, active) =>" in api
        body = api[api.index("export const setSubscriptionActive"):api.index(
            ";", api.index("export const setSubscriptionActive"))]
        assert "activate" in body and "deactivate" in body

    def test_a_subscription_with_no_schedule_says_it_can_never_fire(self):
        src = _automate_src()
        assert "has_schedule === false" in src
        assert "never fires (no schedule)" in src

    def test_the_filter_checkbox_only_appears_with_a_selected_resource(self):
        src = _automate_src()
        body = src[src.index("async function renderSubscriptions("):src.index(
            "async function renderSchedules(")]
        assert "const filterToggle = slug" in body
        assert "data-automate-filter" in body

    def test_toggle_button_disables_itself_and_reports_a_save_failure_on_the_button(self):
        src = _automate_src()
        body = src[src.index("[data-toggle-sub]"):]
        assert "b.disabled = true;" in body
        assert "Not saved:" in body


class TestSchedulesAreReal:
    def test_lists_all_schedules_against_the_real_global_route(self):
        api = _reapi_src()
        assert "export const listAllSchedules = () => get('/api/schedules/');" in api

    def test_delete_hits_the_real_delete_route_and_confirms_first(self):
        api = _reapi_src()
        assert "export const deleteSchedule = (entityType, entitySlug, analysisId) =>" in api
        assert "method: 'DELETE'" in api[api.index("export const deleteSchedule"):]

        src = _automate_src()
        body = src[src.index("[data-delete-sched]"):]
        assert "window.confirm(" in body
        assert "deleteSchedule(entityType, entitySlug, analysisId)" in body


class TestSubscriptionCreationIsHonestlyDeferred:
    """The one real gap: creating a subscription rides on an Assessment/
    Analysis card, and neither stage is built in /next. The pane must say
    that specifically -- not a generic 'not built' -- and the link out must
    actually work (same oldUiHref() every other deferred surface uses,
    preserving the selected resource when there is one)."""

    def test_the_pane_names_the_specific_missing_piece_not_a_generic_gap(self):
        src = _automate_src()
        assert "\"🔔 Notify me\" action" in src
        assert "Assessment/Analysis" in src
        assert "not built in /next yet" in src

    def test_it_links_out_via_the_shared_old_ui_href_helper(self):
        app = _app()
        assert "export function oldUiHref() {" in app
        src = _automate_src()
        assert "oldUiHref } from '/static/next/app.js';" in src
        assert "oldUiHref()" in src

    def test_no_create_subscription_form_exists_in_this_module(self):
        # If a create form gets added later without updating this deferral
        # copy, that is a real product decision -- this pins that it hasn't
        # happened silently.
        src = _automate_src()
        assert "createSubscription" not in src
        assert "CreateSubscriptionRequest" not in src


class TestAutomateHasItsOwnSubnavNotTheSharedSubTabs:
    def test_automate_does_not_render_the_standard_sub_tabs_row(self):
        src = _automate_src()
        assert "subTabsHtml" not in src
        assert "bindSubTabs" not in src

    def test_it_toggles_between_exactly_two_tabs(self):
        src = _automate_src()
        body = src[src.index("function subnavHtml()"):src.index("function bindSubnav(")]
        assert "'subscriptions'" in body and "'schedules'" in body
