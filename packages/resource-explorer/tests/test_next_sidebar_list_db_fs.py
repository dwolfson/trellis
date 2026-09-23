"""Sidebar lists databases/filesystems in /next (re/next-sidebar-list-db-fs,
2026-09-22).

A prior agent unblocked /next's Survey pane for databases/filesystems
(PR #215, test_next_db_fs_gate_removal.py) but flagged, without fixing, that
the sidebar itself never called `listDatabases()`/`listFilesystems()` --
both already existed and worked in re-api.js, but nothing in app.js imported
or called them. Clicking the "DBs"/"FS" chips just showed a static
"Databases and filesystems · not built in /next" message with a link out to
classic, even though the chips looked like they should do something. The
only way to view a database/filesystem in /next was to hand-edit the URL
(`?type=db&resource=<slug>`).

This slice makes the sidebar actually fetch and render clickable rows for
db/fs, wired through the SAME `apiEntityType()` translator PR #215 added --
'db' is /next's own UI shorthand and is never a valid entity_type
server-side (see that function's own docstring/tests).

No browser verification with a signed-in session is asserted by these tests
-- see test_next_discovery_import_search.py's identical rationale. These
tests grep/slice the concatenated source, the established pattern for
/next JS modules without a browser. Live browser verification of this slice
is documented in the PR description, not encoded as a test here.
"""
from __future__ import annotations

from pathlib import Path

NEXT = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next"
API = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "re-api.js"


def _app():
    return (NEXT / "app.js").read_text(encoding="utf-8")


def _api():
    return API.read_text(encoding="utf-8")


class TestReApiAlreadyExposedTheseCalls:
    """Confirms the premise: the API helpers this slice wires up already
    existed and worked before this change -- the gap was purely that
    app.js never called them."""

    def test_list_databases_and_filesystems_exist(self):
        src = _api()
        assert "export const listDatabases = () => get('/api/databases/');" in src
        assert "export const listFilesystems = () => get('/api/filesystems/');" in src


class TestAppJsNowImportsAndUsesBothCalls:
    def test_imports_list_databases_and_filesystems(self):
        src = _app()
        start = src.index("} from '/static/re-api.js';")
        head = src[:start]
        assert "listDatabases" in head
        assert "listFilesystems" in head

    def test_ensure_resource_list_loaded_calls_both(self):
        src = _app()
        start = src.index("async function ensureResourceListLoaded(")
        end = src.index("\n}", start)
        body = src[start:end]
        assert "listDatabases()" in body
        assert "listFilesystems()" in body
        # Cached behind a loaded flag, not re-fetched unconditionally.
        assert "state.databasesLoaded" in body
        assert "state.filesystemsLoaded" in body


class TestStaticNotBuiltMessageIsGone:
    """The old blanket stub this task exists to replace."""

    def test_old_stub_message_is_gone(self):
        src = _app()
        assert "Databases and filesystems · not built in /next" not in src


class TestFetchOnSwitchBehaviour:
    """Switching the sidebar's Repos/DBs/FS chip used to just re-render from
    whatever was already fetched (repos only, fetched once in start()) --
    nothing fetched on switch, for any resource type, before this slice."""

    def test_type_chip_click_calls_switch_resource_type(self):
        src = _app()
        start = src.index("el.querySelectorAll('button[data-type]')")
        end = src.index("\n", start)
        line = src[start:end]
        assert "switchResourceType(b.dataset.type)" in line

    def test_switch_resource_type_fetches_and_reselects(self):
        src = _app()
        start = src.index("async function switchResourceType(")
        end = src.index("\n}", start)
        body = src[start:end]
        assert "ensureResourceListLoaded(type)" in body
        # Re-selects a resource of the NEW type when the old selection
        # doesn't belong to it -- otherwise selectedSlug can point at a
        # repo while resourceType says 'db'.
        assert "currentResourceRows()" in body
        assert "state.selectedSlug = rows[0]?.slug || null" in body

    def test_start_fetches_the_url_named_type_on_boot(self):
        # ?type=db&resource=<slug> on a cold load must not leave
        # state.databases empty forever -- start() only ever fetched repos.
        src = _app()
        start = src.index("async function start() {")
        end = src.index("\nAuth.init(start)")
        body = src[start:end]
        assert "ensureResourceListLoaded(state.resourceType)" in body


class TestRowsRenderAndAreClickable:
    def test_non_repo_branch_calls_the_row_renderer(self):
        src = _app()
        assert "state.resourceType !== 'repo' ? nonRepoRowsHtml()" in src

    def test_row_renderer_emits_clickable_slug_buttons(self):
        src = _app()
        start = src.index("function nonRepoRowsHtml() {")
        end = src.index("\nfunction renderSidebar() {", start)
        body = src[start:end]
        assert "data-nonrepo-slug=" in body
        # Groups by group_slug the same way repos are grouped -- both
        # DatabaseSummary and FileSystemSummary carry this field.
        assert "group_slug" in body

    def test_click_handler_selects_and_loads_the_pane(self):
        src = _app()
        start = src.index("button[data-nonrepo-slug]")
        end = src.index("\n  }));", start)
        body = src[start:end]
        assert "state.selectedSlug = b.dataset.nonrepoSlug" in body
        assert "loadPane()" in body


class TestHonestDegradedState:
    """Whatever's still genuinely missing (select-mode bulk actions,
    disposition, per-group collapse memory) must say so, not silently
    disappear with no explanation -- this project's absence-state
    discipline, same rule test_next_db_fs_gate_removal.py's
    paneNeedsRepoBackend tests hold the rest of the app to."""

    def test_row_renderer_names_what_it_did_not_port(self):
        src = _app()
        start = src.index("function nonRepoRowsHtml() {")
        end = src.index("\nfunction renderSidebar() {", start)
        body = src[start:end]
        assert "repo-only in /next" in body

    def test_loading_state_is_distinct_from_empty_state(self):
        # "never fetched" must not render identically to "fetched, zero
        # results" -- the find-absence-as-answer trap this session's own
        # skill exists to catch.
        src = _app()
        start = src.index("function nonRepoRowsHtml() {")
        end = src.index("\nfunction renderSidebar() {", start)
        body = src[start:end]
        assert "Loading ${label}s…" in body
        assert "No ${label}s registered." in body


class TestApiEntityTypeStillGuardsTheOnlySharpEdge:
    """This slice adds new call sites (listDatabases/listFilesystems) but
    they take no entity_type parameter at all -- 'db' vs 'database' isn't a
    risk here the way it was for the Survey pane's endpoints. This test
    pins that apiEntityType() itself, and its existing call sites from
    PR #215, are untouched by this change."""

    def test_api_entity_type_helper_still_present_and_unchanged(self):
        src = _app()
        assert "export function apiEntityType(resourceType) {" in src
        assert "resourceType === 'db' ? 'database' : resourceType" in src
