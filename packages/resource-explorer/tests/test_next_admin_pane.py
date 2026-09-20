"""Admin's own /next surface (PLAN-FINISH-REPOS.md item 5): pinning that the
header's ⚙ Admin button opens a real overlay panel — chrome-level, decoupled
from #intent-nav, the same pattern as Activity — with five real ports
(Annotation Types browse, Question Catalog, Logs, Feedback, Prefect) and six
named, specific deferrals (Groups, Discovery Sources, Egeria Alignment,
Egeria Links, Publish Queue, Repair), each linking out to classic via the
shared `oldUiHref()` helper.

No browser verification of a signed-in session happened for this file — see
docs/design-notes/ITEM-5-ADMIN-IMPLEMENTED.md for what was and was not
checked live. These tests grep/slice function bodies out of the concatenated
source, the established pattern for /next JS modules without a browser —
see test_next_activity_pane.py and test_next_automate_pane.py's identical
`_app()` helper, reproduced here.
"""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"

DEFERRED_TAB_IDS = [
    "admin-groups",
    "admin-discovery-sources",
    "admin-egeria-links",
    "admin-outbox",
]
BUILT_TAB_IDS = [
    "annotations",
    "admin-question-catalog",
    "admin-prefect",
    "admin-feedback",
    "admin-logs",
    "admin-resync",
    "admin-repair",
]


def _app():
    src = (NEXT / "app.js").read_text(encoding="utf-8")
    for f in sorted((NEXT / "stages").glob("*.js")):
        src += "\n" + f.read_text(encoding="utf-8")
    return src


def _admin_index_src():
    return (NEXT / "admin" / "index.js").read_text(encoding="utf-8")


def _admin_module(name):
    return (NEXT / "admin" / name).read_text(encoding="utf-8")


def _index_html():
    return (NEXT / "index.html").read_text(encoding="utf-8")


def _reapi_src():
    return (NEXT.parent / "re-api.js").read_text(encoding="utf-8")


class TestAdminIsNotAStagesEntry:
    """Admin is a header-triggered overlay, exactly like Activity -- not a
    STAGES array entry with `built: true`, and not read via currentNavIntent."""

    def test_admin_is_absent_from_the_stages_array(self):
        app = _app()
        stages_block = app[app.index("const STAGES = ["):app.index("];", app.index("const STAGES = ["))]
        assert "id: 'admin'" not in stages_block

    def test_the_module_documents_why_it_is_not_a_stage(self):
        src = _admin_index_src()
        assert "NOT one of app.js's STAGES entries" in src
        assert "decoupled from" in src


class TestTheHeaderButtonOpensAdmin:
    def test_the_placeholder_outbound_link_is_gone(self):
        html = _index_html()
        assert "Admin and feedback are not built in /next" not in html

    def test_the_header_control_is_a_button_not_an_outbound_link(self):
        html = _index_html()
        assert 'id="admin-open-btn"' in html
        btn_start = html.index('id="admin-open-btn"')
        tag_start = html.rindex("<", 0, btn_start)
        assert html[tag_start:tag_start + 10].lower().startswith("<button")

    def test_app_js_wires_the_button_to_openadminpanel(self):
        app = _app()
        assert "import { openAdminPanel } from '/static/next/admin/index.js';" in app
        assert "function wireAdminButton()" in app
        body = app[app.index("function wireAdminButton()"):app.index("function wireAdminButton()") + 400]
        assert "$('admin-open-btn')" in body
        assert "openAdminPanel()" in body

    def test_the_wiring_is_idempotent(self):
        app = _app()
        body = app[app.index("function wireAdminButton()"):app.index("function wireAdminButton()") + 400]
        assert "if (adminButtonWired) return;" in body


class TestGroupsAndTabsMatchClassic:
    """Classic groups eleven panes into Configure/Reconcile/Observe
    (commits 4fb48071/26320f89). The /next port must offer the same
    grouping and the same set of destinations -- not a reshuffled subset."""

    def test_three_groups_named_configure_reconcile_observe(self):
        src = _admin_index_src()
        assert "{ name: 'Configure'" in src
        assert "{ name: 'Reconcile'" in src
        assert "{ name: 'Observe'" in src

    def test_every_classic_tab_id_is_present(self):
        src = _admin_index_src()
        for tab_id in BUILT_TAB_IDS + DEFERRED_TAB_IDS:
            assert f"id: '{tab_id}'" in src, f"missing tab id {tab_id!r}"

    def test_exactly_five_tabs_are_wired_to_a_real_renderer(self):
        src = _admin_index_src()
        render_count = src.count("render: render")
        assert render_count == len(BUILT_TAB_IDS)


class TestDeferralsAreSpecificNotGeneric:
    """The Automate item's house style (ITEM-4-AUTOMATE-IMPLEMENTED.md):
    name specifically what is deferred and why, not a generic 'not built'
    string, and link out via the shared oldUiHref() helper."""

    def test_every_deferred_tab_names_a_specific_does_and_why(self):
        src = _admin_index_src()
        for tab_id in DEFERRED_TAB_IDS:
            i = src.index(f"id: '{tab_id}'")
            block = src[i:src.index("} },", i) + 4]
            assert "does:" in block
            assert "why:" in block
            # A generic placeholder would defeat the whole point of naming
            # the reason -- each block's `why` must be long enough to be an
            # actual explanation, not a one-word stub.
            why_start = block.index("why:")
            why_text = block[why_start:why_start + 200]
            assert len(why_text) > 40

    def test_deferred_panes_link_out_via_the_shared_helper(self):
        src = _admin_index_src()
        assert "import { $, esc, icon, oldUiHref } from '/static/next/app.js';" in src
        assert "oldUiHref()" in src

    def test_no_deferred_tab_id_also_carries_a_render_function(self):
        src = _admin_index_src()
        for tab_id in DEFERRED_TAB_IDS:
            i = src.index(f"id: '{tab_id}'")
            block = src[i:src.index("} },", i) + 4]
            assert "render:" not in block


class TestAnnotationTypesBrowse:
    def test_lists_against_the_real_route(self):
        api = _reapi_src()
        assert "export const listAnnotationTypes = () => get('/api/analyses/annotation-types');" in api

    def test_renders_a_detail_view_and_names_the_deferred_mutations(self):
        src = _admin_module("annotation_types.js")
        assert "export async function renderAnnotationTypes(host)" in src
        assert "Register" in src or "Edit/Delete in current UI" in src
        assert "oldUiHref" in src


class TestQuestionCatalogBrowse:
    def test_reads_the_real_route(self):
        api = _reapi_src()
        assert "/api/analyses/question-catalog" in api

    def test_filters_by_stage_and_perspective_client_side(self):
        src = _admin_module("question_catalog.js")
        assert "state.stage" in src
        assert "state.perspectives" in src

    def test_export_render_function_exists(self):
        src = _admin_module("question_catalog.js")
        assert "export async function renderQuestionCatalog(host)" in src


class TestLogsPane:
    def test_reads_the_real_route(self):
        api = _reapi_src()
        assert "export const listLogs = (" in api
        assert "/api/logs/" in api

    def test_three_distinct_empty_states_not_one_generic_message(self):
        src = _admin_module("logs.js")
        assert "buffer is empty" in src
        assert "No records match this filter" in src
        assert "No records to show" in src

    def test_auto_refresh_stops_when_switching_away_from_this_pane(self):
        src = _admin_module("logs.js")
        assert "adminPane !== 'logs'" in src


class TestFeedbackPane:
    def test_reads_the_real_gated_route(self):
        src = _admin_module("feedback.js")
        assert "/api/curate/feedback" in src

    def test_reuses_classics_admin_token_key_and_header(self):
        src = _admin_module("feedback.js")
        assert "re_admin_token" in src
        assert "X-Admin-Token" in src

    def test_a_403_renders_the_token_gate_not_an_empty_list(self):
        src = _admin_module("feedback.js")
        assert "res.status === 403" in src
        assert "tokenGateHtml" in src

    def test_absent_rating_renders_an_em_dash_not_zero_stars(self):
        src = _admin_module("feedback.js")
        i = src.index("function ratingHtml")
        body = src[i:i + 300]
        assert "r === null || r === undefined" in body
        assert "—" in body


class TestPrefectPane:
    def test_reads_status_and_flow_runs_and_can_cancel(self):
        api = _reapi_src()
        assert "export const getPrefectStatus = ()" in api
        assert "export const listPrefectFlowRuns = (" in api
        assert "export const cancelPrefectFlowRun = (" in api

    def test_cancel_is_confirmed_before_the_write(self):
        src = _admin_module("prefect.js")
        assert "window.confirm(" in src


class TestResyncPane:
    """SPEC-ADMIN-THE-FOUR-GAPS.md §1 — Resync is global drift reconciliation,
    a different job from Repair (per-repo correction). The whole design is:
    do not flatten a Finding's `repair_step`/`needs_decision` into "a row with
    a button" — three distinct shapes, not one generic list item."""

    def test_reads_the_real_scan_and_apply_routes(self):
        api = _reapi_src()
        assert "export const getResyncScan = ()" in api
        assert "/api/egeria/resync/scan" in api
        assert "export const applyResyncSteps = (" in api
        assert "/api/egeria/resync/apply" in api

    def test_export_render_function_exists(self):
        src = _admin_module("resync.js")
        assert "export async function renderResync(host)" in src

    def test_unreachable_is_never_rendered_as_no_drift(self):
        src = _admin_module("resync.js")
        assert "d.reachable" in src
        assert "Deliberately not reported as" in src

    def test_scheduled_steps_get_a_state_row_not_a_fix_button(self):
        src = _admin_module("resync.js")
        assert "clear_stale_assets" in src
        assert "clear_orphan_publish_claims" in src
        assert "flag_vanished_publishes" in src
        assert "function scheduledRowHtml" in src
        body = src[src.index("function scheduledRowHtml"):src.index("function scheduledRowHtml") + 1400]
        assert "Run now" in body
        # A scheduled row must not carry the same tick-a-box affordance as a
        # repairable one -- it is a status report with a "run now" action,
        # not a selectable fix.
        assert "data-resync-step" not in body

    def test_no_button_when_repair_step_is_empty(self):
        src = _admin_module("resync.js")
        assert "function decisionRowHtml" in src
        body = src[src.index("function decisionRowHtml"):src.index("function decisionRowHtml") + 900]
        assert "checkbox" not in body
        assert "<button" not in body

    def test_needs_decision_is_framed_as_a_question_not_an_action(self):
        src = _admin_module("resync.js")
        body = src[src.index("function decisionRowHtml"):src.index("function decisionRowHtml") + 900]
        assert "your call" in body

    def test_clear_stale_investigations_names_the_binding_it_unbinds(self):
        """The most dangerous control in the product per egeria_resync.py's
        own comment above SAFE_SCHEDULED_STEPS -- its confirmation must say
        what it unbinds and how many, not just "clears N records"."""
        src = _admin_module("resync.js")
        i = src.index("clear_stale_investigations:")
        block = src[i:i + 700]
        assert "UNBIND" in block.upper()
        assert "Project" in block

    def test_apply_selected_confirms_before_writing(self):
        src = _admin_module("resync.js")
        assert "window.confirm(" in src
        assert "async function applySelected" in src

    def test_expensive_steps_default_unticked(self):
        src = _admin_module("resync.js")
        assert "f.expensive ? '' : 'checked'" in src


class TestRepairPane:
    """SPEC-ADMIN-THE-FOUR-GAPS.md §1 -- Repair is per-repository correction,
    NOT drift reconciliation; it needs no design beyond §0's blast-radius
    rule, including naming what an action does NOT do."""

    def test_reads_the_real_repair_routes(self):
        api = _reapi_src()
        for fn in (
            "repairRename", "repairGithubUrl", "repairEnableCollection",
            "getRepairDrift", "getRepairMemberships",
            "repairRepointMembership", "repairDropMembership",
        ):
            assert f"export const {fn} = " in api
        assert "/api/admin/repair/repos/" in api

    def test_export_render_function_exists(self):
        src = _admin_module("repair.js")
        assert "export async function renderRepair(host)" in src

    def test_destructive_actions_are_confirmed(self):
        src = _admin_module("repair.js")
        assert src.count("window.confirm(") >= 3  # rename, github-url change, drop membership

    def test_names_what_it_does_not_do(self):
        """SPEC-ADMIN-THE-FOUR-GAPS.md §0's sharpest example -- classic's
        "this does not delete your files on disk" -- ported here for the
        repair actions whose names sound more destructive than they are."""
        src = _admin_module("repair.js")
        assert "does not touch GitHub" in src
        assert "does not remove the repo from RE" in src or "does not remove it from RE" in src

    def test_is_distinct_from_resync_not_folded_together(self):
        src = _admin_module("repair.js")
        assert "NOT Resync" in src
        resync_src = _admin_module("resync.js")
        assert "NOT Repair" in resync_src
