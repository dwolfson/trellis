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
NO_ELEMENT = "No element found"
NO_ELEMENTS = "No elements found"


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
    """The Egeria elements that exist, and what was called, in order."""

    def __init__(self):
        self.exist = {PROJECT, LOG, NOTE1, NOTE2, FOLIO, DISP, ASSET}
        self.names = {LOG: ("NoteLog::RE::" + PROJECT), FOLIO: f"Folio::Investigation::{SLUG}",
                      DISP: f"WorkingSet::Investigation::{SLUG}::tracking"}
        self.calls: list[tuple[str, str]] = []
        self.refuse: dict[str, Exception] = {}
        self.stuck: set[str] = set()          # a delete that is sent but the element stays readable
        self.extra_logs: list[dict] = []     # NoteLogs RE did not make

    def pm(self):
        m = create_autospec(ProjectManager, instance=True, spec_set=True)

        def logs(element_guid, *a, **k):
            self.calls.append(("get_attached_note_logs", element_guid))
            out = ([_el(LOG, self.names[LOG], "Notes on x")] if LOG in self.exist else []) + self.extra_logs
            return out or NO_ELEMENTS

        def notes(note_log_guid, *a, **k):
            self.calls.append(("get_notes_for_note_log", note_log_guid))
            out = [_el(n, f"note::{n}", n) for n in (NOTE1, NOTE2) if n in self.exist]
            return out or NO_ELEMENTS

        def rm(kind):
            def _rm(guid, *a, **k):
                self.calls.append((kind, guid))
                if guid in self.refuse:
                    raise self.refuse[guid]
                if guid not in self.stuck:
                    self.exist.discard(guid)
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
            self.exist.discard(guid)

        def get(guid, *a, **k):
            self.calls.append(("get_collection_by_guid", guid))
            if guid not in self.exist:
                return NO_ELEMENT
            return {"elementHeader": {"guid": guid}, "properties": {"qualifiedName": self.names.get(guid, "")}}

        m.delete_collection.side_effect = rm
        m.get_collection_by_guid.side_effect = get
        return m

    def me(self):
        m = create_autospec(MetadataExpert, instance=True, spec_set=True)

        def get(guid=None, *a, **k):
            self.calls.append(("get_metadata_element_by_guid", guid))
            return {"elementHeader": {"guid": guid}} if guid in self.exist else NO_ELEMENT

        m.get_metadata_element_by_guid.side_effect = get
        return m

    def handles(self) -> EgeriaHandles:
        return EgeriaHandles(pm=self.pm(), cm=self.cm(), me=self.me())

    def write_calls(self):
        return [c for c in self.calls if c[0] in ("remove_note", "remove_note_log", "delete_collection",
                                                  "delete_project")]


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
        ("delete_collection", FOLIO), ("delete_collection", DISP), ("delete_project", PROJECT)]
    assert not any(ASSET == g for _, g in world.calls) and ASSET in world.exist
    assert world.exist == {ASSET}
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
    world = World()
    world.extra_logs = [_el("their-log", "NoteLog::Theirs", "Their notes")]
    world.exist.add("their-log")
    world.names[FOLIO] = "Folio::Somebody::Else"
    res = _deleter(registry, world).run(SLUG, CHOICE_RE_AND_EGERIA, by=OWNER)
    assert ("remove_note_log", "their-log") not in world.calls and ("delete_collection", FOLIO) not in world.calls
    assert {x["guid"] for x in res.left} >= {"their-log", FOLIO}


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
