"""Admin's own /next surface (PLAN-FINISH-REPOS.md item 5): pinning that the
header's ⚙ Admin button opens a real overlay panel — chrome-level, decoupled
from #intent-nav, the same pattern as Activity — with six real ports
(Annotation Types browse, Question Catalog, Logs, Feedback, Prefect,
Discovery Sources) and five named, specific deferrals (Groups, Egeria
Alignment, Egeria Links, Publish Queue, Repair), each linking out to classic
via the shared `oldUiHref()` helper.

Discovery Sources was ported from a deferral to a full build under
SPEC-ADMIN-THE-FOUR-GAPS.md §3 — see TestDiscoverySourcesPane below and
docs/design-notes/DISCOVERY-SOURCES-ADMIN-IMPLEMENTED.md.

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
    "admin-resync",
    "admin-egeria-links",
    "admin-outbox",
    "admin-repair",
]
BUILT_TAB_IDS = [
    "annotations",
    "admin-question-catalog",
    "admin-prefect",
    "admin-feedback",
    "admin-logs",
    "admin-discovery-sources",
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

    def test_renders_a_detail_view_with_edit_and_delete(self):
        src = _admin_module("annotation_types.js")
        assert "export async function renderAnnotationTypes(host)" in src
        assert "data-edit" in src
        assert "data-delete" in src

    def test_mutations_are_no_longer_deferred_to_classic(self):
        """SPEC-ADMIN-THE-FOUR-GAPS.md §4 (2026-09-20): register/edit/delete
        against the routes that already existed — this pane used to punt
        every write to classic via `oldUiHref()`; it doesn't anymore."""
        src = _admin_module("annotation_types.js")
        assert "oldUiHref" not in src
        api = _reapi_src()
        assert "registerAnnotationType" in api
        assert "updateAnnotationType" in api
        assert "deleteAnnotationType" in api

    def test_delete_confirmation_names_blast_radius_or_says_unknown(self):
        """§0/§4: a destructive confirmation must say how many annotations
        are affected, or say the count is unknown — never imply zero."""
        src = _admin_module("annotation_types.js")
        assert "getAnnotationTypeUsage" in src
        assert "UNKNOWN" in src or "unknown" in src


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

    def test_add_and_retire_are_offered_but_no_edit_form_exists(self):
        """SPEC-ADMIN-THE-FOUR-GAPS.md §4 (2026-09-20, project owner decision):
        append-only — add and retire are real UI actions here; there is no
        third path that reworks an existing question's own text."""
        src = _admin_module("question_catalog.js")
        assert "addQuestionCatalogEntry" in src
        assert "retireQuestionCatalogEntry" in src
        assert "data-retire" in src
        assert "updateQuestionCatalogEntry" not in src
        assert "editQuestionCatalogEntry" not in src

    def test_retired_questions_are_shown_distinctly_not_hidden(self):
        src = _admin_module("question_catalog.js")
        assert "retired" in src
        assert "LIFECYCLE" in src


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


class TestDiscoverySourcesPane:
    """SPEC-ADMIN-THE-FOUR-GAPS.md §3: run's own route is read-only (returns
    candidates, imports nothing), so this pane must preview before either of
    its two effectful actions — importing from a run, and applying a
    refresh — never fire-and-hope. Delete's confirmation must be worded from
    the registry's actual (no-FK) behaviour, not a guess."""

    def test_reads_and_writes_against_the_real_routes(self):
        api = _reapi_src()
        assert "export const listDiscoverySources = ()" in api
        assert "export const createDiscoverySource = (" in api
        assert "export const deleteDiscoverySource = (" in api
        assert "export const runDiscoverySource = (" in api
        assert "export const previewSourceRefresh = (" in api
        assert "export const applySourceRefresh = (" in api
        assert "export const searchDiscoveryRepos = (" in api
        assert "export const importDiscoveredRepos = (" in api

    def test_export_render_function_exists(self):
        src = _admin_module("discovery_sources.js")
        assert "export async function renderDiscoverySources(host)" in src

    def test_run_shows_candidates_before_any_import_is_possible(self):
        """The route itself never imports (checked against
        run_discovery_source in web/routes/discovery.py) -- the module's
        own header must say so, and importing must be a distinct,
        confirmed follow-up action, not something doRun triggers itself."""
        src = _admin_module("discovery_sources.js")
        assert "READ-ONLY" in src
        assert "no import" in src.lower()
        i = src.index("async function doRun(")
        run_body = src[i:src.index("\n}", i)]
        assert "importDiscoveredRepos" not in run_body

    def test_import_confirmation_names_the_count_and_destination(self):
        src = _admin_module("discovery_sources.js")
        i = src.index("async function doImportSelected(")
        body = src[i:src.index("\n}", i)]
        assert "window.confirm(" in body
        assert "picked.length" in body
        assert "dest" in body  # names the destination group (or "no group")

    def test_refresh_previews_before_it_applies(self):
        src = _admin_module("discovery_sources.js")
        i = src.index("async function doRefresh(")
        body = src[i:src.index("\n}", i)]
        assert "previewSourceRefresh(" in body
        assert "window.confirm(" in body
        confirm_pos = body.index("window.confirm(")
        apply_pos = body.index("applySourceRefresh(")
        assert confirm_pos < apply_pos

    def test_delete_confirmation_says_imported_repos_are_unaffected(self):
        """registry.py's discovery_sources table has no foreign key into
        projects -- deleting a source cannot touch anything already
        imported from it, and the confirmation must say so rather than
        reading as a generic destructive warning."""
        src = _admin_module("discovery_sources.js")
        i = src.index("async function doDelete(")
        body = src[i:src.index("\n}", i)]
        assert "window.confirm(" in body
        assert "does not affect any repositories already imported" in body

    def test_three_add_paths_are_present(self):
        src = _admin_module("discovery_sources.js")
        assert "'search'" in src and "searchFormHtml" in src
        assert "listFormHtml" in src
        assert "quickAddHtml" in src

    def test_save_github_source_is_not_treated_as_an_add_source_path(self):
        """Checked against classic's actual code before porting (spec's own
        §6 lesson): _saveGithubSource posts to /api/discovery/github-base-url
        (the GitHub API endpoint override), not a discovery source create --
        it must not appear here as if it were a third source-creation path."""
        src = _admin_module("discovery_sources.js")
        # The comment discussing why it's excluded may mention the route by
        # name; what must never appear is an actual call to it.
        assert "'/api/discovery/github-base-url'" not in src
        assert "not create a discovery source" in src.lower()
