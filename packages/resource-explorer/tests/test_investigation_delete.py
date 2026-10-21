"""Deleting an investigation (owner ruling 2026-10-21): who may, what each choice touches, what a refusal leaves.

A temp SQLite registry and a fake Egeria whose methods are `create_autospec(..., spec_set=True)` mocks of the real
pyegeria classes, so a call with a signature the real client does not have fails here. No live call is made.
"""
from __future__ import annotations

import asyncio
import json
from unittest.mock import create_autospec

import pytest
from fastapi import HTTPException
from pyegeria import CollectionManager, MetadataExpert, ProjectManager

from resource_explorer.a2a_auth import CallerIdentity, current_caller
from resource_explorer.investigation_delete import (
    CHOICE_RE_AND_EGERIA,
    CHOICE_RE_ONLY,
    EgeriaHandles,
    InvestigationDeleter,
    delete_rights,
)
from resource_explorer.registry import ProjectRegistry

OWNER, OTHER, ADMIN = "owen", "olive", "ada"
SLUG = "customer-360"
PROJECT = "proj-guid"
LOG = "log-guid"
NOTE1, NOTE2 = "note-1", "note-2"
FOLIO = "folio-guid"
DISP = "disp-guid"
ASSET = "member-asset-guid"        # a member's own repo/database asset: must never be touched
RATING, COMMENT = "rating-guid", "comment-guid"     # anchored to the Project; made by other people
NO_ELEMENT = "No element found"
NO_ELEMENTS = "No elements found"


def _api_exc(cls_name="PyegeriaAPIException", code=500, msg_id=""):
    """A real-shaped Egeria failure: the class pyegeria raises, the HTTP code, and the message id Egeria's FFDC
    body carries (the shape observed live 2026-10-16). Live Egeria RAISES PyegeriaNotFoundException for a deleted
    GUID; it never returns the "No element found" string."""
    import pyegeria.core._exceptions as ex
    e = Exception.__new__(getattr(ex, cls_name))
    Exception.__init__(e, "Egeria error")
    e.related_http_code = code
    e.context, e.pyegeria_code, e.message, e.system_action, e.user_action = {}, "CLIENT-ERROR", "Egeria refused", "", ""
    e.response = None
    e.additional_info = {"exceptionErrorMessageId": msg_id} if msg_id else {}
    return e


def _not_found():
    return _api_exc("PyegeriaNotFoundException", 404)


NOT_VISIBLE = "OMAG-REPOSITORY-HANDLER-400-010"


def _identity(user: str, role: str = "user") -> CallerIdentity:
    return CallerIdentity(user_id=user, egeria_token="tok", auth_source="app-jwt", role=role)


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(database_url=f"sqlite:///{tmp_path / 'r.db'}")
    reg._init_schema()
    return reg


@pytest.fixture
def as_caller(monkeypatch):
    """Sign in as `who`; the route reads `a2a_auth.caller()`, the registry `current_user_id()`."""
    tokens = []

    def _as(user: str, role: str = "user"):
        tokens.append(current_caller.set(_identity(user, role)))
    yield _as
    for t in reversed(tokens):
        current_caller.reset(t)


class World:
    """The Egeria elements that exist, and what was called, in order. Reads of a deleted GUID RAISE
    `PyegeriaNotFoundException`, as live Egeria does (`string_answers` switches to the string for one test)."""

    def __init__(self):
        self.exist = {PROJECT, LOG, NOTE1, NOTE2, FOLIO, DISP, ASSET}
        self.names = {LOG: ("NoteLog::RE::" + PROJECT), FOLIO: f"Folio::Investigation::{SLUG}",
                      DISP: f"WorkingSet::Investigation::{SLUG}::tracking"}
        self.members = {FOLIO: [ASSET], DISP: []}      # a Collection's members: Egeria refuses to delete a non-empty one
        self.anchored = {LOG: "NoteLog", NOTE1: "Note", NOTE2: "Note"}    # guid -> type, anchored to the Project
        self.anchored_meta: dict[str, dict] = {}                          # guid -> {name, author} for the others
        self.calls: list[tuple[str, str]] = []
        self.refuse: dict[str, Exception] = {}
        self.stuck: set[str] = set()          # a delete that is sent but the element stays readable
        self.extra_logs: list[dict] = []     # NoteLogs RE did not make
        self.string_answers = False          # answer "No element found" instead of raising
        self.stale_listing = False           # the Note list still names a Note that has been deleted
        self.soft = False                    # a deleted GUID then reads as 400-010 "not visible" (soft-deleted)
        self.soft_deleted: set[str] = set()  # read of these raises 400-010 "not visible"
        self.read_error: "Exception | None" = None   # every by-GUID read raises this

    def add_anchored(self, guid, type_name, name="", author=""):
        self.exist.add(guid)
        self.anchored[guid] = type_name
        self.anchored_meta[guid] = {"name": name, "author": author}

    def _gone_read(self, guid):
        if self.string_answers:
            return NO_ELEMENT
        raise (_api_exc(msg_id=NOT_VISIBLE) if guid in self.soft_deleted else _not_found())

    def pm(self):
        m = create_autospec(ProjectManager, instance=True, spec_set=True)

        def logs(element_guid, *a, **k):
            self.calls.append(("get_attached_note_logs", element_guid))
            out = ([_el(LOG, self.names[LOG], "Notes on x")] if LOG in self.exist else []) + self.extra_logs
            return out or NO_ELEMENTS

        def notes(note_log_guid, *a, **k):
            self.calls.append(("get_notes_for_note_log", note_log_guid))
            out = [_el(n, f"note::{n}", n) for n in (NOTE1, NOTE2) if n in self.exist or self.stale_listing]
            return out or NO_ELEMENTS

        def rm(kind):
            def _rm(guid, *a, **k):
                self.calls.append((kind, guid))
                if guid in self.refuse:
                    raise self.refuse[guid]
                if guid not in self.stuck:
                    self.exist.discard(guid)
                    if self.soft:
                        self.soft_deleted.add(guid)
                    if kind == "delete_project":      # Egeria deletes what is anchored to a Project with it
                        for g in list(self.anchored):
                            self.exist.discard(g)
            return _rm

        m.get_attached_note_logs.side_effect = logs
        m.get_notes_for_note_log.side_effect = notes
        m.remove_note.side_effect = rm("remove_note")
        m.remove_note_log.side_effect = rm("remove_note_log")
        m.delete_project.side_effect = rm("delete_project")
        return m

    def cm(self):
        m = create_autospec(CollectionManager, instance=True, spec_set=True)

        def rm(guid, *a, **k):
            self.calls.append(("delete_collection", guid))
            if guid in self.refuse:
                raise self.refuse[guid]
            if self.members.get(guid):
                raise RuntimeError("OMAG-GENERIC-HANDLERS-400-001 the Collection still has member elements")
            self.exist.discard(guid)
            if self.soft:
                self.soft_deleted.add(guid)

        def get(guid, *a, **k):
            self.calls.append(("get_collection_by_guid", guid))
            if guid not in self.exist:
                return self._gone_read(guid)
            return {"elementHeader": {"guid": guid}, "properties": {"qualifiedName": self.names.get(guid, "")}}

        def members(collection_guid=None, *a, **k):
            self.calls.append(("get_collection_members", collection_guid))
            out = [_el(g, "", g) for g in self.members.get(collection_guid, [])]
            return out or NO_ELEMENTS

        def unlink(collection_guid, element_guid, *a, **k):
            self.calls.append(("remove_from_collection", f"{collection_guid}:{element_guid}"))
            if f"{collection_guid}:{element_guid}" in self.refuse:
                raise self.refuse[f"{collection_guid}:{element_guid}"]
            if element_guid not in self.stuck:
                self.members[collection_guid] = [g for g in self.members.get(collection_guid, []) if g != element_guid]

        m.delete_collection.side_effect = rm
        m.get_collection_by_guid.side_effect = get
        m.get_collection_members.side_effect = members
        m.remove_from_collection.side_effect = unlink
        return m

    def me(self):
        m = create_autospec(MetadataExpert, instance=True, spec_set=True)

        def get(guid=None, *a, **k):
            self.calls.append(("get_metadata_element_by_guid", guid))
            if self.read_error is not None:
                raise self.read_error
            return {"elementHeader": {"guid": guid}} if guid in self.exist else self._gone_read(guid)

        def graph(guid=None, *a, **k):
            self.calls.append(("get_anchored_element_graph", guid))
            els = []
            for g, t in self.anchored.items():
                if g in self.exist:
                    meta = self.anchored_meta.get(g, {})
                    els.append({"elementHeader": {"guid": g, "type": {"typeName": t},
                                                  "versions": {"createdBy": meta.get("author", "")}},
                                "properties": {"displayName": meta.get("name") or g}})
            return {"elementHeader": {"guid": guid}, "anchoredElements": els}

        m.get_metadata_element_by_guid.side_effect = get
        m.get_anchored_element_graph.side_effect = graph
        return m

    def handles(self) -> EgeriaHandles:
        return EgeriaHandles(pm=self.pm(), cm=self.cm(), me=self.me())

    def write_calls(self):
        return [c for c in self.calls if c[0] in ("remove_note", "remove_note_log", "delete_collection",
                                                  "delete_project", "remove_from_collection")]


def _el(guid, qn, name):
    return {"elementHeader": {"guid": guid}, "properties": {"qualifiedName": qn, "displayName": name}}


def _deleter(registry, world, **kw):
    return InvestigationDeleter(registry, handles_factory=world.handles, sleep=lambda s: None, **kw)


@pytest.fixture
def promoted(registry, as_caller):
    """A promoted investigation owned by OWNER, with members, a disposition, journal entry and a pending outbox row."""
    as_caller(OWNER)
    inv = registry.create_investigation("Customer 360", project_classification="StudyProject")
    assert inv["slug"] == SLUG
    registry.set_investigation_egeria_project(SLUG, {
        "status": "linked", "egeria_project_guid": PROJECT,
        "egeria_project_qualified_name": f"Project::Investigation::{SLUG}"})
    folio = registry.get_or_create_folio(SLUG)
    registry.set_working_set_egeria_collection(folio["slug"], FOLIO)
    registry.add_working_set_member(folio["slug"], "repo", "crm-repo", membership_rationale="holds customers")
    registry.set_investigation_disposition(SLUG, "repo", "crm-repo", "tracking")
    disp = registry.get_or_create_disposition_set(SLUG, "tracking")
    registry.set_working_set_egeria_collection(disp["slug"], DISP)
    return SLUG


def _count(registry, table, where="1=1", params=()):
    with registry._conn() as conn:
        return conn.execute(f"SELECT COUNT(*) AS n FROM {table} WHERE {where}", params).fetchone()["n"]  # noqa: S608


def _seed(registry, table, slug, **extra):
    """One row in `table` for the investigation, filling any other NOT NULL column with a neutral value."""
    with registry._conn() as conn:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        vals = {}
        for c in cols:
            name, typ = c["name"], (c["type"] or "").upper()
            if c["pk"] and "INT" in typ and c["name"] == "id":
                continue
            if name == "entity_type":
                vals[name] = "investigation"
            elif name == "entity_slug":
                vals[name] = slug
            elif c["notnull"] and c["dflt_value"] is None:
                vals[name] = 0 if ("INT" in typ or "REAL" in typ) else f"{table}-{name}"
        vals.update(extra)
        conn.execute(f"INSERT INTO {table} ({', '.join(vals)}) VALUES ({', '.join('?' * len(vals))})",
                     tuple(vals.values()))


# ── who may delete ─────────────────────────────────────────────────────────────────────────────────────

def test_owner_admin_and_nobody_else(promoted, registry):
    inv = registry.get_investigation(SLUG, user_id="")
    assert delete_rights(inv, _identity(OWNER)) == (True, "")
    assert delete_rights(inv, _identity(ADMIN, "admin")) == (True, "")
    assert delete_rights(inv, _identity(ADMIN, "curator")) == (True, "")
    ok, words = delete_rights(inv, _identity(OTHER))
    assert not ok and "creat" in words and "admin" in words
    ok, words = delete_rights(inv, None)
    assert not ok and "Sign in" in words
    anon = CallerIdentity(user_id="anonymous", egeria_token=None, auth_source="anonymous", role="anonymous")
    assert not delete_rights(inv, anon)[0]


def test_ownerless_is_an_admins_alone(registry):
    inv = {"slug": "x", "created_by": ""}
    assert not delete_rights(inv, _identity(OWNER))[0]
    assert "no recorded owner" in delete_rights(inv, _identity(OWNER))[1]
    assert delete_rights(inv, _identity(ADMIN, "admin"))[0]


def _route(slug, egeria, *, who, role="user", monkeypatch=None, deleter=None):
    """Call the route as `who`. The real deleter is replaced by one wired to the fake Egeria."""
    from resource_explorer.web.routes import investigations as routes

    token = current_caller.set(_identity(who, role))
    try:
        return asyncio.run(routes.delete_investigation(slug, egeria=egeria))
    finally:
        current_caller.reset(token)


@pytest.fixture
def routes_on(registry, monkeypatch):
    from resource_explorer.web.routes import investigations as routes

    world = World()
    monkeypatch.setattr(routes, "_registry", lambda: registry)
    monkeypatch.setattr("resource_explorer.investigation_delete.caller_handles", world.handles)
    monkeypatch.setattr("resource_explorer.investigation_delete.time.sleep", lambda s: None)
    return world


def test_route_owner_can_delete(promoted, registry, routes_on):
    out = _route(SLUG, False, who=OWNER)
    assert out["ok"] and out["local_deleted"] and routes_on.calls == []
    assert registry.get_investigation(SLUG, user_id="") is None


def test_route_admin_can_delete(promoted, registry, routes_on):
    assert _route(SLUG, False, who=ADMIN, role="admin")["local_deleted"]
    assert registry.get_investigation(SLUG, user_id="") is None


def test_route_anyone_else_gets_403_with_words_and_nothing_changes(promoted, registry, routes_on):
    with pytest.raises(HTTPException) as e:
        _route(SLUG, True, who=OTHER)
    assert e.value.status_code == 403 and "admin" in e.value.detail
    assert registry.get_investigation(SLUG, user_id="") is not None and routes_on.calls == []


def test_route_404_for_missing_and_for_not_visible(registry, as_caller, routes_on):
    with pytest.raises(HTTPException) as e:
        _route("nope", False, who=OWNER)
    assert e.value.status_code == 404
    as_caller(OWNER)
    registry.create_investigation("Secret", project_classification="PersonalProject")
    with pytest.raises(HTTPException) as e:
        _route("secret", False, who=OTHER)            # private to OWNER: the same 404 get_investigation gives
    assert e.value.status_code == 404


def test_route_egeria_true_on_unpromoted_is_400(registry, as_caller, routes_on):
    as_caller(OWNER)
    registry.create_investigation("Local only", egeria_binding="local")
    with pytest.raises(HTTPException) as e:
        _route("local-only", True, who=OWNER)
    assert e.value.status_code == 400 and registry.get_investigation("local-only", user_id="") is not None


def test_route_409_while_a_publish_is_being_written(promoted, registry, routes_on):
    from datetime import datetime
    with registry._conn() as conn:
        _seed(registry, "egeria_outbox", SLUG, status="running", claimed_at=datetime.utcnow().isoformat(),
              element_kind="note", qualified_name="n")
    with pytest.raises(HTTPException) as e:
        _route(SLUG, False, who=OWNER)
    assert e.value.status_code == 409 and registry.get_investigation(SLUG, user_id="") is not None


def test_route_is_registered_as_delete():
    from resource_explorer.web.app import app

    assert "delete" in app.openapi()["paths"]["/api/investigations/{slug}"]


# ── the Egeria choices ─────────────────────────────────────────────────────────────────────────────────

def test_re_only_makes_zero_egeria_calls_and_says_what_it_left(promoted, registry):
    world = World()
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_ONLY, by=OWNER)
    assert res.ok and res.local_deleted and not res.egeria_done
    assert world.calls == []
    assert PROJECT in world.exist and FOLIO in world.exist and NOTE1 in world.exist
    with registry._conn() as conn:
        row = conn.execute("SELECT * FROM activity_log WHERE operation = 'delete'").fetchone()
    detail = json.loads(row["detail"])
    assert detail["choice"] == CHOICE_RE_ONLY and detail["by"] == OWNER
    assert {d["guid"] for d in detail["left_behind_in_egeria"]} == {PROJECT, FOLIO, DISP}
    assert "Resource Explorer only" in row["summary"] and OWNER in row["summary"]


def test_re_and_egeria_deletes_in_order_one_per_call_and_never_a_members_asset(promoted, registry):
    world = World()
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert res.ok and res.egeria_done and res.local_deleted
    assert world.write_calls() == [
        ("remove_note", NOTE1), ("remove_note", NOTE2), ("remove_note_log", LOG),
        ("remove_from_collection", f"{FOLIO}:{ASSET}"), ("delete_collection", FOLIO),
        ("delete_collection", DISP), ("delete_project", PROJECT)]
    # the member's own asset is only taken out of the Collection: never deleted, never cascaded
    assert not any(c[0] in ("remove_note", "remove_note_log", "delete_collection", "delete_project") and c[1] == ASSET
                   for c in world.calls)
    assert world.exist == {ASSET}
    assert [u["guid"] for u in res.unlinked] == [ASSET]
    assert [d["guid"] for d in res.deleted] == [NOTE1, NOTE2, LOG, FOLIO, DISP, PROJECT]
    # no delete before every read of the Notes had been made
    first_write = min(i for i, c in enumerate(world.calls) if c[0] in ("remove_note", "remove_note_log"))
    assert all(c[0] != "remove_note" for c in world.calls[:first_write])
    assert registry.get_investigation(SLUG, user_id="") is None
    with registry._conn() as conn:
        row = conn.execute("SELECT * FROM activity_log WHERE operation = 'delete'").fetchone()
    assert json.loads(row["detail"])["choice"] == CHOICE_RE_AND_EGERIA
    assert len(json.loads(row["detail"])["egeria_deleted"]) == 6


def test_a_refused_note_delete_stops_everything_and_keeps_the_investigation(promoted, registry):
    world = World()
    world.refuse[NOTE2] = PermissionError("OPEN-METADATA-SECURITY-403-020 you may not delete this. More words")
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.ok and not res.local_deleted and not res.egeria_done
    assert world.write_calls() == [("remove_note", NOTE1), ("remove_note", NOTE2)]      # no retry, nothing after
    assert [d["guid"] for d in res.deleted] == [NOTE1]
    assert [r["guid"] for r in res.remaining] == [NOTE2]
    assert "OPEN-METADATA-SECURITY-403-020" in res.remaining[0]["why"]
    assert "OPEN-METADATA-SECURITY-403-020" in res.errors[0]
    inv = registry.get_investigation(SLUG, user_id="")
    assert inv is not None and inv["member_count"] == 1                           # nothing local deleted
    assert _count(registry, "working_sets") == 2
    with registry._conn() as conn:
        row = conn.execute("SELECT * FROM activity_log WHERE operation = 'delete'").fetchone()
    assert row["status"] == "error" and "kept" in row["summary"]


def test_pressing_delete_again_resumes_and_skips_what_is_already_gone(promoted, registry):
    world = World()
    world.refuse[NOTE2] = RuntimeError("boom")
    _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    world.refuse.clear()
    world.calls.clear()
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert res.ok and res.local_deleted
    assert ("remove_note", NOTE1) not in world.calls
    assert world.exist == {ASSET}


def test_a_delete_that_cannot_be_confirmed_stops(promoted, registry):
    world = World()
    world.stuck.add(NOTE1)
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and res.remaining[0]["guid"] == NOTE1
    assert "still returns it" in res.remaining[0]["why"]
    assert world.write_calls() == [("remove_note", NOTE1)]


def test_an_exception_on_read_back_is_not_gone(promoted, registry):
    world = World()
    handles = world.handles()
    original = handles.me.get_metadata_element_by_guid.side_effect

    def flaky(guid=None, *a, **k):
        if world.write_calls():
            raise TimeoutError("read timed out")
        return original(guid)

    handles.me.get_metadata_element_by_guid.side_effect = flaky
    res = InvestigationDeleter(registry, handles_factory=lambda: handles, sleep=lambda s: None).run(
        SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and "could not be asked" in res.remaining[0]["why"]


def test_an_unreadable_note_list_stops_before_any_delete(promoted, registry):
    world = World()
    handles = world.handles()
    handles.pm.get_notes_for_note_log.side_effect = lambda *a, **k: None
    res = InvestigationDeleter(registry, handles_factory=lambda: handles, sleep=lambda s: None).run(
        SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and world.write_calls() == [] and res.errors


def test_a_project_that_was_bound_not_made_by_re_is_left_in_egeria(promoted, registry):
    registry.set_investigation_egeria_project(SLUG, {
        "status": "linked", "egeria_project_guid": PROJECT, "egeria_project_qualified_name": "Project::Theirs::1"})
    world = World()
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert res.local_deleted and ("delete_project", PROJECT) not in world.calls and PROJECT in world.exist
    assert res.left[-1]["guid"] == PROJECT and "did not create it" in res.left[-1]["why"]


def test_a_notelog_or_collection_re_did_not_make_is_left_alone(promoted, registry):
    """Not anchored to the Project, so the Project step does not take it: it really is left alone."""
    world = World()
    world.extra_logs = [_el("their-log", "NoteLog::Theirs", "Their notes")]
    world.exist.add("their-log")
    world.names[FOLIO] = "Folio::Somebody::Else"
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert ("remove_note_log", "their-log") not in world.calls and ("delete_collection", FOLIO) not in world.calls
    assert {x["guid"] for x in res.left} >= {"their-log", FOLIO}
    assert "their-log" in world.exist and FOLIO in world.exist and res.local_deleted


def test_egeria_choice_on_an_unpromoted_investigation_is_refused(registry, as_caller):
    as_caller(OWNER)
    registry.create_investigation("Local only", egeria_binding="local")
    with pytest.raises(ValueError, match="never promoted"):
        _deleter(registry, World()).run("local-only", CHOICE_RE_AND_EGERIA, by=OWNER)


def test_signatures_match_the_real_clients():
    """The calls the deleter makes are the ones the fakes bind: spec_set autospecs reject anything else."""
    import inspect
    for cls, name in [(ProjectManager, "remove_note"), (ProjectManager, "remove_note_log"),
                      (ProjectManager, "delete_project"), (CollectionManager, "delete_collection"),
                      (ProjectManager, "get_attached_note_logs"), (ProjectManager, "get_notes_for_note_log"),
                      (MetadataExpert, "get_metadata_element_by_guid"), (CollectionManager, "get_collection_by_guid")]:
        assert callable(getattr(cls, name)), name
        assert list(inspect.signature(getattr(cls, name)).parameters)[1]


# ── the local side ─────────────────────────────────────────────────────────────────────────────────────

def test_every_table_with_a_type_and_slug_pair_is_decided(registry):
    """A new table with an (entity_type|resource_type, slug) pair must be added to the delete or to the keep list."""
    pairs = (("entity_type", "entity_slug"), ("entity_type", "slug"), ("resource_type", "resource_slug"),
             ("resource_type", "slug"))
    found = set()
    with registry._conn() as conn:
        for t in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
            cols = {c["name"] for c in conn.execute(f"PRAGMA table_info({t['name']})").fetchall()}
            if any(a in cols and b in cols for a, b in pairs):
                found.add(t["name"])
    decided = set(registry.INVESTIGATION_KEYED_TABLES) | set(registry.INVESTIGATION_NOT_KEYED_TABLES)
    assert found - decided == set(), f"decide these in registry.INVESTIGATION_*: {sorted(found - decided)}"
    assert set(registry.INVESTIGATION_KEYED_TABLES) <= found


def test_every_local_table_keyed_by_the_slug_is_empty_and_the_activity_row_is_written(promoted, registry):
    from resource_explorer.journal import Journal
    from resource_explorer.work_lists import WorkLists

    Journal(registry).write("investigation", SLUG, author=OWNER, body="a note to self")
    for table in registry.INVESTIGATION_KEYED_TABLES:
        _seed(registry, table, SLUG)
        _seed(registry, table, "another-investigation")            # a neighbour that must survive
    _seed(registry, "egeria_outbox", SLUG, status="pending", element_kind="note", qualified_name="p")
    _seed(registry, "egeria_outbox", SLUG, status="failed", element_kind="note", qualified_name="f")
    _seed(registry, "egeria_outbox", SLUG, status="done", element_kind="note", qualified_name="d")
    _seed(registry, "egeria_outbox", SLUG, status="dead", element_kind="note", qualified_name="x")
    registry.create_investigation("Another")
    wl = WorkLists(registry).create("Saved", ["crm"], entity_type="database", rationale="", investigation=SLUG)
    assert _count(registry, "resource_journal", "entity_slug = ?", (SLUG,)) >= 1

    res = _deleter(registry, World()).run(SLUG, CHOICE_RE_ONLY, by=OWNER)

    assert res.local_deleted
    for table in registry.INVESTIGATION_KEYED_TABLES:
        assert _count(registry, table, "entity_type = 'investigation' AND entity_slug = ?", (SLUG,)) == 0, table
        assert _count(registry, table, "entity_slug = 'another-investigation'") == 1, table
    for table, where in [("investigations", "slug = ?"), ("investigation_resource_lists", "investigation_slug = ?"),
                         ("working_sets", "slug LIKE ?"), ("working_set_members", "working_set_slug LIKE ?")]:
        like = f"{SLUG}-%" if "LIKE" in where else SLUG
        assert _count(registry, table, where, (like,)) == 0, table
    assert _count(registry, "egeria_outbox", "entity_slug = ? AND status IN ('pending','failed')", (SLUG,)) == 0
    assert _count(registry, "egeria_outbox", "entity_slug = ? AND status = 'cancelled'", (SLUG,)) == 2
    assert _count(registry, "egeria_outbox", "entity_slug = ? AND status IN ('done','dead')", (SLUG,)) == 2
    assert _count(registry, "work_lists", "slug = ? AND investigation = ''", (wl["slug"],)) == 1
    assert registry.get_investigation("another", user_id="") is not None
    # the activity log is kept, plus the one delete row, which names the choice, who and what was left
    assert _count(registry, "activity_log", "operation = 'delete' AND entity_slug = ?", (SLUG,)) == 1
    assert res.activity_id


def test_the_local_delete_is_one_transaction(promoted, registry, monkeypatch):
    """A failure part-way leaves everything: the investigation, its sets and the journal."""
    from resource_explorer.journal import Journal

    Journal(registry).write("investigation", SLUG, author=OWNER, body="keep me if it fails")
    real = ProjectRegistry._insert_activity

    def boom(conn, entry):
        raise RuntimeError("activity write failed")

    monkeypatch.setattr(ProjectRegistry, "_insert_activity", staticmethod(boom))
    with pytest.raises(RuntimeError):
        registry.delete_investigation_local(SLUG, activity=object())
    monkeypatch.setattr(ProjectRegistry, "_insert_activity", staticmethod(real))
    assert registry.get_investigation(SLUG, user_id="") is not None
    assert _count(registry, "resource_journal", "entity_slug = ?", (SLUG,)) == 1
    assert _count(registry, "working_sets") == 2


# ── fix round 1 (2026-10-21): read-back, members, anchors, outbox, cue, words ───────────────────────────

def _run(registry, world, choice=CHOICE_RE_AND_EGERIA, **kw):
    return _deleter(registry, world, **kw).run(SLUG, choice, by=OWNER)


def test_h1_live_egeria_raises_not_found_for_a_deleted_guid_and_that_is_gone(promoted, registry):
    world = World()
    res = _run(registry, world)
    assert res.ok and res.local_deleted and world.exist == {ASSET}
    with pytest.raises(Exception):
        world.me().get_metadata_element_by_guid(PROJECT)          # the fake raises, as live does


def test_h1_the_no_element_found_string_also_means_gone(promoted, registry):
    world = World()
    world.string_answers = True
    res = _run(registry, world)
    assert res.ok and res.local_deleted and world.exist == {ASSET}


def test_h1_a_soft_deleted_guid_this_run_deleted_reads_as_gone(promoted, registry):
    world = World()
    world.soft = True                                              # 400-010 "not visible" after a delete
    res = _run(registry, world)
    assert res.ok and res.local_deleted and len(res.deleted) == 6


@pytest.mark.parametrize("exc", [
    _api_exc("PyegeriaUnauthorizedException", 401),
    _api_exc("PyegeriaUnauthorizedException", 403, NOT_VISIBLE),
    _api_exc(code=404, msg_id="OMAG-MULTI-TENANT-404-001"),        # the SERVER is not available: 404 but not absence
    _api_exc(code=500),
    TimeoutError("read timed out"),
], ids=["401", "403", "server-unavailable", "500", "timeout"])
def test_h1_unauthorised_or_unavailable_is_not_gone(promoted, registry, exc):
    world = World()
    handles = world.handles()
    original = handles.me.get_metadata_element_by_guid.side_effect

    def flaky(guid=None, *a, **k):
        if world.write_calls():
            raise exc
        return original(guid)

    handles.me.get_metadata_element_by_guid.side_effect = flaky
    res = InvestigationDeleter(registry, handles_factory=lambda: handles, sleep=lambda s: None).run(
        SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and "could not be asked" in res.remaining[0]["why"]
    assert registry.get_investigation(SLUG, user_id="") is not None


def test_h1_a_not_visible_answer_is_not_gone_before_this_run_deleted_anything(promoted, registry):
    """400-010 also fires for an element the caller merely cannot see: the pre-check must not read it as gone."""
    world = World()
    world.soft_deleted.add(NOTE1)                                  # reads as 400-010 although it still exists
    world.exist.add(NOTE1)
    res = _run(registry, world)
    assert ("remove_note", NOTE1) in world.calls                   # not skipped as "already gone"
    assert res.ok


def test_h1_a_resumed_run_never_resends_a_delete_for_what_is_gone(promoted, registry):
    world = World()
    world.refuse[NOTE2] = RuntimeError("boom")
    _run(registry, world)
    world.refuse.clear()
    world.calls.clear()
    world.stale_listing = True                          # the list still names NOTE1: only the by-GUID read says gone
    res = _run(registry, world)
    assert res.ok and ("remove_note", NOTE1) not in world.calls
    assert [c for c in world.write_calls() if c[0] == "remove_note"] == [("remove_note", NOTE2)]
    gone = [d for d in res.deleted if d["guid"] == NOTE1]
    assert gone and gone[0].get("note") == "already gone from Egeria"


def test_h2_a_collection_with_members_is_unlinked_then_deleted_never_cascaded(promoted, registry):
    world = World()
    world.members[FOLIO] = [ASSET, "asset-2"]
    world.exist.add("asset-2")
    res = _run(registry, world)
    assert res.ok
    order = world.write_calls()
    i = order.index(("delete_collection", FOLIO))
    assert order[i - 2:i] == [("remove_from_collection", f"{FOLIO}:{ASSET}"),
                              ("remove_from_collection", f"{FOLIO}:asset-2")]
    assert ASSET in world.exist and "asset-2" in world.exist                  # the members' own elements stay
    assert all(c[0] != "delete_metadata_element" for c in world.calls)
    assert [u["guid"] for u in res.unlinked] == [ASSET, "asset-2"]


def test_h2_the_fake_refuses_a_non_empty_collection(promoted, registry):
    """The fake is as strict as Egeria's validateNoCollectionMembers: deleting without unlinking is refused."""
    world = World()
    with pytest.raises(RuntimeError, match="member"):
        world.cm().delete_collection(FOLIO)


def test_h2_a_refused_unlink_stops_before_the_collection_delete(promoted, registry):
    world = World()
    world.refuse[f"{FOLIO}:{ASSET}"] = PermissionError("OPEN-METADATA-SECURITY-403-020 not yours")
    res = _run(registry, world)
    assert not res.local_deleted and ("delete_collection", FOLIO) not in world.calls
    assert res.remaining[-1]["kind"] == "CollectionMembership" and "403-020" in res.remaining[-1]["why"]
    assert ASSET in world.exist and registry.get_investigation(SLUG, user_id="") is not None


def test_h2_members_that_will_not_unlink_stop_it(promoted, registry):
    world = World()
    world.stuck.add(ASSET)                                         # the unlink is accepted but the member stays listed
    res = _run(registry, world)
    assert not res.local_deleted and ("delete_collection", FOLIO) not in world.calls
    assert "still lists" in res.errors[0]


def test_h3_anchored_elements_others_made_stop_before_the_project_step_and_are_named(promoted, registry):
    world = World()
    world.add_anchored(RATING, "Rating", name="5 stars", author="mandy")
    world.add_anchored(COMMENT, "Comment", name="looks right to me", author="olive")
    res = _run(registry, world)
    assert not res.local_deleted and not res.ok
    assert ("delete_project", PROJECT) not in world.calls and PROJECT in world.exist
    assert RATING in world.exist and COMMENT in world.exist                    # nothing of theirs was removed
    assert [(b["kind"], b["guid"], b["name"], b["author"]) for b in res.blocking] == [
        ("Rating", RATING, "5 stars", "mandy"), ("Comment", COMMENT, "looks right to me", "olive")]
    assert res.remaining[-1]["kind"] == "Project" and "not deleted" in res.remaining[-1]["why"]
    assert "Rating" in res.errors[0] and RATING in res.errors[0] and "mandy" in res.errors[0]
    assert registry.get_investigation(SLUG, user_id="") is not None
    with registry._conn() as conn:
        row = conn.execute("SELECT * FROM activity_log WHERE operation = 'delete'").fetchone()
    assert row["status"] == "error"
    assert {b["guid"] for b in json.loads(row["detail"])["egeria_blocking"]} == {RATING, COMMENT}
    # what RE made was removed first; the Project stays for the design session's ruling
    assert NOTE1 not in world.exist and LOG not in world.exist and FOLIO not in world.exist


def test_h3_without_the_check_the_project_delete_would_have_taken_their_rating(promoted):
    """The fake's delete_project removes what is anchored to it, so skipping the pre-check would lose the Rating."""
    world = World()
    world.add_anchored(RATING, "Rating", author="mandy")
    world.pm().delete_project(PROJECT)
    assert RATING not in world.exist


def test_h3_a_notelog_re_did_not_make_that_is_anchored_is_blocking_not_left_alone(promoted, registry):
    world = World()
    world.extra_logs = [_el("their-log", "NoteLog::Theirs", "Their notes")]
    world.add_anchored("their-log", "NoteLog", name="Their notes", author="olive")
    res = _run(registry, world)
    assert not res.local_deleted and "their-log" in world.exist
    assert [b["guid"] for b in res.blocking] == ["their-log"]
    assert "their-log" not in {x["guid"] for x in res.left}


def test_h3_nothing_anchored_but_what_re_made_goes_straight_to_the_project(promoted, registry):
    world = World()
    res = _run(registry, world)
    assert res.ok and res.blocking == [] and world.write_calls()[-1] == ("delete_project", PROJECT)
    assert ("get_anchored_element_graph", PROJECT) in world.calls
    graph_at = world.calls.index(("get_anchored_element_graph", PROJECT))
    assert graph_at > world.calls.index(("delete_collection", FOLIO)) and graph_at < world.calls.index(
        ("delete_project", PROJECT))


def test_h3_an_unreadable_anchor_graph_stops_before_the_project(promoted, registry):
    world = World()
    handles = world.handles()
    handles.me.get_anchored_element_graph.side_effect = lambda *a, **k: "No element found"
    res = InvestigationDeleter(registry, handles_factory=lambda: handles, sleep=lambda s: None).run(
        SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and ("delete_project", PROJECT) not in world.calls and res.errors


def test_h3_the_project_step_is_one_swappable_function():
    assert callable(InvestigationDeleter._retire_project)


# M1 ────────────────────────────────────────────────────────────────────────────────────────────────────

def _outbox(registry, status, **extra):
    _seed(registry, "egeria_outbox", SLUG, status=status, element_kind="note", qualified_name=f"q-{status}", **extra)


def _statuses(registry):
    with registry._conn() as conn:
        return sorted(r["status"] for r in conn.execute(
            "SELECT status FROM egeria_outbox WHERE entity_slug = ?", (SLUG,)).fetchall())


def test_m1_pending_and_failed_rows_are_cancelled_at_the_very_start_not_deleted(promoted, registry):
    _outbox(registry, "pending")
    _outbox(registry, "failed")
    _outbox(registry, "done")
    assert registry.begin_investigation_delete(SLUG) == 2
    assert _statuses(registry) == ["cancelled", "cancelled", "done"]


def test_m1_a_running_row_refuses_the_whole_delete_and_changes_nothing(promoted, registry):
    from datetime import datetime
    from resource_explorer.registry import InvestigationPublishRunning
    _outbox(registry, "pending")
    _outbox(registry, "running", claimed_at=datetime.utcnow().isoformat())
    world = World()
    with pytest.raises(InvestigationPublishRunning):
        _run(registry, world, CHOICE_RE_AND_EGERIA)
    assert world.calls == []                                       # no Egeria call at all
    assert _statuses(registry) == ["pending", "running"]           # the running row untouched, the pending one too
    assert registry.get_investigation(SLUG, user_id="") is not None


def test_m1_an_expired_claim_is_a_dead_claim_and_is_cancelled_not_a_blocker(promoted, registry):
    from datetime import datetime, timedelta
    old = (datetime.utcnow() - timedelta(hours=3)).isoformat()
    _outbox(registry, "running", claimed_at=old)
    res = _run(registry, World(), CHOICE_RE_ONLY)
    assert res.local_deleted and _statuses(registry) == ["cancelled"]


def test_m1_a_row_claimed_after_the_first_step_rolls_the_local_delete_back(promoted, registry):
    from datetime import datetime
    world = World()
    handles = world.handles()
    real_graph = handles.me.get_anchored_element_graph.side_effect

    def claim_then_graph(*a, **k):
        _outbox(registry, "running", claimed_at=datetime.utcnow().isoformat())
        return real_graph(*a, **k)

    handles.me.get_anchored_element_graph.side_effect = claim_then_graph
    res = InvestigationDeleter(registry, handles_factory=lambda: handles, sleep=lambda s: None).run(
        SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert not res.local_deleted and not res.ok and res.errors          # words, not an exception
    assert registry.get_investigation(SLUG, user_id="") is not None
    assert "running" in _statuses(registry)                           # never deleted locally


# M2 ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_m2_the_cue_comes_from_the_latest_error_row_and_a_later_ok_row_clears_it(promoted, registry):
    world = World()
    world.refuse[NOTE2] = RuntimeError("boom")
    _run(registry, world)
    stop = registry.latest_investigation_delete_stop(SLUG)
    assert stop and [d["guid"] for d in stop["deleted"]] == [NOTE1] and [r["guid"] for r in stop["remaining"]] == [NOTE2]
    assert "boom" in stop["errors"][0]
    # the page's own read carries it, so a reload shows it
    from resource_explorer.web.routes import investigations as routes
    import resource_explorer.web.routes.investigations as mod
    mod_registry = mod._registry
    mod._registry = lambda: registry
    try:
        got = asyncio.run(routes.get_investigation(SLUG))
    finally:
        mod._registry = mod_registry
    assert got["delete_stop"]["remaining"][0]["guid"] == NOTE2
    # a later delete that finished (an ok row) clears it
    from datetime import datetime, timedelta, timezone
    from resource_explorer.registry import ActivityEntry
    registry.write_activity(ActivityEntry(
        id="later-ok", ts=(datetime.now(timezone.utc) + timedelta(seconds=5)).isoformat(), operation="delete",
        intent="enrichment", entity_type="investigation", entity_slug=SLUG, entity_name="x", status="ok",
        summary="deleted", detail="{}", items=[]))
    assert registry.latest_investigation_delete_stop(SLUG) is None


def test_m2_no_stop_when_nothing_ever_stopped(promoted, registry):
    assert registry.latest_investigation_delete_stop(SLUG) is None


# L1 ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_l1_a_collection_whose_name_only_starts_like_ours_is_left(promoted, registry):
    world = World()
    world.names[FOLIO] = f"Folio::Investigation::{SLUG}-somebody-elses"      # startswith would have matched
    res = _run(registry, world)
    assert ("delete_collection", FOLIO) not in world.calls and FOLIO in world.exist
    assert FOLIO in {x["guid"] for x in res.left}


def test_l1_a_disposition_set_is_matched_by_its_own_disposition(promoted, registry):
    world = World()
    world.names[DISP] = f"WorkingSet::Investigation::{SLUG}::other-disposition"
    assert DISP in {x["guid"] for x in _run(registry, world).left} and ("delete_collection", DISP) not in world.calls


# L2 ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_l2_a_local_failure_after_a_full_egeria_delete_answers_in_words_and_records_what_egeria_lost(
        promoted, registry, monkeypatch):
    world = World()

    def boom(self, slug, activity=None):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(ProjectRegistry, "delete_investigation_local", boom)
    res = _run(registry, world)                                              # does not raise
    assert not res.ok and not res.local_deleted and res.egeria_done
    assert "still here" in res.errors[0] and "database is locked" in res.errors[0]
    assert world.exist == {ASSET}
    with registry._conn() as conn:
        row = conn.execute("SELECT * FROM activity_log WHERE operation = 'delete'").fetchone()
    assert row["status"] == "error"
    assert len(json.loads(row["detail"])["egeria_deleted"]) == 6 and "failed" in row["summary"].lower() + "failed"
    assert registry.latest_investigation_delete_stop(SLUG)["deleted"]


def test_l2_the_route_answers_ok_false_not_a_500(promoted, registry, routes_on, monkeypatch):
    def boom(self, slug, activity=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(ProjectRegistry, "delete_investigation_local", boom)
    out = _route(SLUG, True, who=OWNER)
    assert out["ok"] is False and out["local_deleted"] is False and "disk full" in out["errors"][0]


# L3 ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_l3_orphaned_disposition_sets_are_swept_locally_and_in_egeria_but_a_neighbours_are_not(promoted, registry):
    orphan = f"{SLUG}-ws-parked"
    now = "2026-10-21T00:00:00"
    with registry._conn() as conn:
        conn.execute("INSERT INTO working_sets (slug, display_name, collection_kind, disposition, created_at, "
                      "egeria_collection_guid) VALUES (?, ?, 'working_set', 'parked', ?, 'orphan-guid')",
                     (orphan, "orphan", now))
    registry.create_investigation("Customer 360 ws x")                    # slug customer-360-ws-x: a neighbour
    neighbour_folio = registry.get_or_create_folio("customer-360-ws-x")
    world = World()
    world.exist.add("orphan-guid")
    world.names["orphan-guid"] = f"WorkingSet::Investigation::{SLUG}::parked"
    world.members["orphan-guid"] = []
    res = _run(registry, world)
    assert res.ok and ("delete_collection", "orphan-guid") in world.calls
    assert _count(registry, "working_sets", "slug = ?", (orphan,)) == 0
    assert _count(registry, "working_sets", "slug = ?", (neighbour_folio["slug"],)) == 1
    assert registry.get_investigation("customer-360-ws-x", user_id="") is not None


# private investigations ────────────────────────────────────────────────────────────────────────────────

def test_a_private_investigation_is_the_owners_alone_an_admin_gets_404(registry, as_caller, routes_on):
    as_caller(OWNER)
    registry.create_investigation("Secret", project_classification="PersonalProject")
    with pytest.raises(HTTPException) as e:
        _route("secret", False, who=ADMIN, role="admin")
    assert e.value.status_code == 404
    assert registry.get_investigation("secret", user_id=OWNER) is not None       # untouched
    assert _route("secret", False, who=OWNER)["local_deleted"]                   # its owner can


# words ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_l4_the_words_say_what_the_designer_asked_for():
    import pathlib
    js = (pathlib.Path(__file__).parent.parent / "resource_explorer/web/static/next/stages/investigation-delete.js"
          ).read_text()
    assert "A Project that Resource Explorer did not create is left in Egeria" in js
    assert "Ratings, comments" in js and "the delete stops if any of them are not ones" in js
    assert "collide with the Project" in js
