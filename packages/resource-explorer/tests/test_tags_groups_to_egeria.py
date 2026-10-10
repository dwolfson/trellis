"""Brief T (2026-10-10): tags become public Egeria InformalTags; RE groups become Folio collections.

The owner, verbatim: "tags should be public", "Use Folio", "Yes, removing a tag removes it in Egeria".

No Egeria anywhere. The fake stands at the client boundary only: `egeria_outbox._default_clients` (what the
drain builds its clients from) returns a recording fake, and the zone reads are faked at `zone_access`'s client
constructors (tests/zone_fakes.py). Everything of RE's own between the route and the client (the plan, the
outbox, the drain, the creators) runs for real, and every test reads the NEXT state back through the same plan
the band reads.
"""
from __future__ import annotations

import json
import re

import pytest
from fastapi.testclient import TestClient

from resource_explorer import curation_egeria as ce
from resource_explorer import egeria_outbox as ob
from resource_explorer.auth import create_access_token
from resource_explorer.registry import DatabaseEntity, Project, ProjectRegistry
from tests.zone_fakes import element as zoned_element
from tests.zone_fakes import install as install_zones

pytestmark = pytest.mark.usefixtures("mock_egeria_client_connections")

ASSET = "11111111-2222-3333-4444-555555555555"
OTHER_ASSET = "99999999-2222-3333-4444-555555555555"


class FakeEgeria:
    """The two clients the creators reach (feedback-manager tags and CollectionManager), in one recording fake.
    Any element delete fails the test: Brief T never deletes an InformalTag or a Folio."""

    def __init__(self):
        self.tags: dict[str, dict] = {}          # guid -> {"name", "qn"}
        self.tag_links: set[tuple[str, str]] = set()
        self.folios: dict[str, dict] = {}        # guid -> {"qn", "name"}
        self.members: set[tuple[str, str]] = set()
        self.calls: list[tuple] = []
        self.fail: dict[str, Exception] = {}     # method name -> exception to raise once per call
        self._n = 0

    def _new(self, prefix):
        self._n += 1
        return f"{prefix}-{self._n:04d}"

    def _maybe_fail(self, name):
        if name in self.fail:
            raise self.fail[name]

    # feedback-manager (pyegeria ServerClient methods; signatures checked against pyegeria)
    def find_tags(self, search_string="*", starts_with=True, ends_with=False, ignore_case=True, **kw):
        self.calls.append(("find_tags", search_string))
        norm = (lambda x: x.lower()) if ignore_case else (lambda x: x)
        hits = [{"elementHeader": {"guid": g}, "properties": {"displayName": t["name"], "qualifiedName": t["qn"]}}
                for g, t in self.tags.items() if norm(search_string) in (norm(t["name"]), norm(t["qn"]))]
        return hits or "No elements found"

    def get_tags_by_name(self, name="*", **kw):
        self.calls.append(("get_tags_by_name", name))
        hits = [{"elementHeader": {"guid": g}, "properties": {"displayName": t["name"], "qualifiedName": t["qn"]}}
                for g, t in self.tags.items() if t["name"] == name]
        return hits or "No elements found"

    def create_informal_tag(self, display_name=None, description=None, qualified_name=None, body=None):
        self.calls.append(("create_informal_tag", display_name, qualified_name))
        self._maybe_fail("create_informal_tag")
        g = self._new("tag")
        self.tags[g] = {"name": display_name, "qn": qualified_name}
        return g

    def add_tag_to_element(self, element_guid, tag_guid, is_public=False, body=None):
        self.calls.append(("add_tag_to_element", element_guid, tag_guid, is_public))
        self._maybe_fail("add_tag_to_element")
        self.tag_links.add((element_guid, tag_guid))

    def remove_tag_from_element(self, element_guid, tag_guid, body=None):
        self.calls.append(("remove_tag_from_element", element_guid, tag_guid))
        self._maybe_fail("remove_tag_from_element")
        self.tag_links.discard((element_guid, tag_guid))

    def delete_tag(self, *a, **k):
        raise AssertionError("Brief T never deletes an InformalTag")

    # CollectionManager
    def get_collections_by_name(self, name=None, metadata_element_type_name="Collection", **kw):
        self.calls.append(("get_collections_by_name", name, metadata_element_type_name))
        hits = [{"elementHeader": {"guid": g}, "properties": {"qualifiedName": f["qn"], "displayName": f["name"]}}
                for g, f in self.folios.items() if f["qn"] == name]
        return hits or "No elements found"

    def create_collection(self, body=None, **kw):
        props = body["properties"]
        self.calls.append(("create_collection", props["typeName"], props["qualifiedName"]))
        g = self._new("folio")
        self.folios[g] = {"qn": props["qualifiedName"], "name": props["displayName"]}
        return g

    def add_to_collection(self, collection_guid, element_guid, body=None):
        self.calls.append(("add_to_collection", collection_guid, element_guid))
        self._maybe_fail("add_to_collection")
        self.members.add((collection_guid, element_guid))

    def remove_from_collection(self, collection_guid, element_guid, body=None):
        self.calls.append(("remove_from_collection", collection_guid, element_guid))
        self._maybe_fail("remove_from_collection")
        self.members.discard((collection_guid, element_guid))

    def delete_collection(self, *a, **k):
        raise AssertionError("Brief T never deletes a Folio")

    def names(self):
        return [c[0] for c in self.calls]


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    r.add(Project(slug="q", display_name="Q repo", github_url="https://github.com/x/q", description=""))
    r.set_egeria_asset_guid("p", ASSET)
    r.set_egeria_asset_guid("q", OTHER_ASSET)
    r.create_group("sales", "Sales platform", "The sales systems")
    r.create_group("hr", "HR", "")
    return r


@pytest.fixture
def egeria(monkeypatch):
    """The client boundary: the drain's client bundle, recording which identity it was built for."""
    fake = FakeEgeria()
    fake.identities = []

    def default_clients(identity=None):
        fake.identities.append(ob.drain_identity(identity))
        return ob.OutboxClients(feedback=fake, collection_manager=fake, acting_as="fake"), lambda qn: ""

    monkeypatch.setattr(ob, "_default_clients", default_clients)
    install_zones(monkeypatch)            # no zone in use: every element answers with no ZoneMembership
    return fake


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None, **kw: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer import auth
    from resource_explorer.web.app import app
    from resource_explorer.web.routes import curate as curate_routes
    from resource_explorer.web.routes import projects as project_routes

    monkeypatch.setattr(curate_routes, "get_current_user", auth.get_current_user)
    monkeypatch.setattr(project_routes, "get_current_user", auth.get_current_user)
    return TestClient(app)


def as_user(user_id: str = "peterprofile") -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id=user_id, egeria_token="t")}


def state(client, slug="p", entity_type="repo"):
    r = client.get(f"/api/curate/egeria-state/{entity_type}/{slug}", headers=as_user())
    assert r.status_code == 200, r.text
    return r.json()


def item(st, kind, name):
    return next((i for i in st["items"] if i["kind"] == kind and i["name"] == name), None)


def rows(registry, kind=None):
    out = registry.list_outbox_rows_for_kinds("repo", "p", ce.KINDS)
    return [r for r in out if kind is None or r["element_kind"] == kind]


# ── 1. add a tag: found or created, then linked ─────────────────────────────────────────────────────────────

def test_adding_a_tag_creates_the_public_tag_once_and_links_it_and_the_next_read_says_in_egeria(client, registry, egeria):
    r = client.post("/api/curate/tags/repo/p", json={"tag": "Sales"}, headers=as_user())
    assert r.status_code == 200, r.text
    tag_guid = next(iter(egeria.tags))
    assert egeria.tags[tag_guid] == {"name": "Sales", "qn": "InformalTag::sales"}, "typed case kept (round 2)"
    assert (ASSET, tag_guid) in egeria.tag_links
    i = item(state(client), "tag", "sales")
    assert i["state"] == "in_egeria" and i["word"] == "in Egeria" and i["action"] == "" and i["egeria_guid"] == tag_guid
    assert state(client)["to_send"] == 0, "after a fully successful press the plan has nothing left to do"
    # the same name on another resource FINDS the tag: never a second InformalTag
    assert client.post("/api/curate/tags/repo/q", json={"tag": "sales"}, headers=as_user()).status_code == 200
    assert len(egeria.tags) == 1
    assert (OTHER_ASSET, tag_guid) in egeria.tag_links
    assert egeria.names().count("create_informal_tag") == 1


def test_a_tag_that_already_exists_in_egeria_is_found_by_name_not_created(client, registry, egeria):
    egeria.tags["tag-portal"] = {"name": "sales", "qn": "InformalTag::::peter::sales::1760000000"}
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    assert "create_informal_tag" not in egeria.names()
    assert (ASSET, "tag-portal") in egeria.tag_links


def test_the_inline_drain_runs_as_the_person_and_the_row_records_who_asked(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user("peterprofile"))
    assert [i.kind for i in egeria.identities] == ["caller"]
    assert egeria.identities[0].user_id == "peterprofile"
    assert json.loads(rows(registry, ce.TAG_LINK)[0]["payload_json"])["by"] == "peterprofile"


# ── 2. remove a tag: unlinked, the tag element never deleted ────────────────────────────────────────────────

def test_removing_a_tag_unlinks_it_and_never_deletes_the_tag(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    tag_guid = next(iter(egeria.tags))
    r = client.delete("/api/curate/tags/repo/p/sales", headers=as_user())
    assert r.status_code == 200, r.text
    assert (ASSET, tag_guid) not in egeria.tag_links
    assert tag_guid in egeria.tags, "the InformalTag element stays in Egeria"
    assert ("remove_tag_from_element", ASSET, tag_guid) in egeria.calls
    i = item(state(client), "tag", "sales")
    assert i["state"] == "unlinked" and not i["desired"]
    detach = rows(registry, ce.TAG_DETACH)[0]
    assert json.loads(detach["payload_json"])["tag_guid"] == tag_guid


def test_no_creator_or_module_code_calls_an_element_delete():
    import inspect

    src = inspect.getsource(ce)
    code = "\n".join(line for line in src.splitlines() if not line.strip().startswith(("#", '"""')))
    assert not re.search(r"\.(delete_tag|delete_collection|delete_element|delete_metadata_element)\(", code)


def test_a_re_add_before_the_removal_was_sent_retires_the_unsent_unlink(registry, egeria):
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

    with acting_as(Daemon(DaemonReason.SCHEDULER)):
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False)
        registry.remove_resource_tag("repo", "p", "sales")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        out = ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False)
    assert out["cancelled"] and not out["queued"]
    assert "remove_tag_from_element" not in egeria.names()
    assert item({"items": out["items"]}, "tag", "sales")["state"] == "in_egeria"


# ── 3. not in Egeria: local, then linked at the next publish ────────────────────────────────────────────────

def test_a_resource_not_in_egeria_keeps_the_tag_local_then_links_it_on_the_next_publish(client, registry, egeria):
    registry.set_egeria_asset_guid("p", "")
    assert client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user()).status_code == 200
    assert client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"},
                       headers=as_user()).status_code == 200
    assert egeria.calls == [] and rows(registry) == []
    st = state(client)
    assert item(st, "tag", "sales")["state"] == "not_yet"
    assert item(st, "tag", "sales")["word"] == "not yet (resource not in Egeria)"
    assert item(st, "group", "sales")["state"] == "not_yet"
    # the publish hook (EgeriaPublisher._publish_pending_curation) after the asset exists
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

    registry.set_egeria_asset_guid("p", ASSET)
    with acting_as(Daemon(DaemonReason.SCHEDULER)):
        ce.publish_pending_curation(registry, "repo", "p", ASSET)
    st = state(client)
    assert item(st, "tag", "sales")["state"] == "in_egeria"
    assert item(st, "group", "sales")["state"] == "in_egeria"
    folio = next(iter(egeria.folios))
    assert (folio, ASSET) in egeria.members
    # round 2: the row records the triggering publish's requester; this daemon job has none, so none
    assert json.loads(rows(registry, ce.TAG_LINK)[0]["payload_json"])["by"] == ""


def test_the_repo_publisher_calls_the_curation_hook_with_the_new_asset(monkeypatch):
    import inspect

    from resource_explorer.surveyors import egeria_publisher

    src = inspect.getsource(egeria_publisher.EgeriaPublisher.publish)
    assert "_publish_pending_curation(result.resource_slug, asset_guid)" in src


# ── 4. group -> Folio, idempotent ───────────────────────────────────────────────────────────────────────────

def test_a_group_becomes_a_folio_with_the_member_and_a_re_sync_queues_nothing(client, registry, egeria):
    r = client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    assert r.status_code == 200, r.text
    assert r.json()["egeria"]["items"]
    folio = next(iter(egeria.folios))
    assert egeria.folios[folio] == {"qn": "Folio::RE::group::sales", "name": "Sales platform"}
    assert (folio, ASSET) in egeria.members
    g = item(state(client), "group", "sales")
    assert g["state"] == "in_egeria" and g["label"] == "Sales platform"
    n_rows, n_calls = len(rows(registry)), len(egeria.calls)
    again = client.post("/api/curate/egeria-sync/repo/p", json={}, headers=as_user())
    assert again.status_code == 200 and again.json()["queued"] == []
    assert len(rows(registry)) == n_rows and len(egeria.calls) == n_calls
    # a second member finds the Folio by qualifiedName
    client.post("/api/projects/q/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    assert len(egeria.folios) == 1 and (folio, OTHER_ASSET) in egeria.members


def test_moving_between_groups_detaches_then_attaches_and_never_deletes_a_folio(client, registry, egeria):
    client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    sales = next(iter(egeria.folios))
    client.post("/api/projects/p/group", json={"group_slug": "hr", "resource_type": "repo"}, headers=as_user())
    hr = next(g for g in egeria.folios if g != sales)
    assert (sales, ASSET) not in egeria.members and (hr, ASSET) in egeria.members
    assert ("remove_from_collection", sales, ASSET) in egeria.calls
    st = state(client)
    assert item(st, "group", "sales")["state"] == "unlinked"
    assert item(st, "group", "hr")["state"] == "in_egeria"
    assert len(egeria.folios) == 2
    # ungrouped: the membership goes, the Folio stays
    client.post("/api/projects/p/group", json={"group_slug": "", "resource_type": "repo"}, headers=as_user())
    assert (hr, ASSET) not in egeria.members and hr in egeria.folios


def test_deleting_a_group_reports_the_folio_and_unlinks_its_members(client, registry, egeria):
    client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    folio = next(iter(egeria.folios))
    r = client.delete("/api/projects/groups/sales", headers=as_user())
    assert r.status_code == 200, r.text
    assert r.json()["egeria"]["folio_qualified_name"] == "Folio::RE::group::sales"
    assert r.json()["egeria"]["left_in_egeria"] is True
    assert folio in egeria.folios and (folio, ASSET) not in egeria.members


# ── 5. unlinks are destructive kinds ────────────────────────────────────────────────────────────────────────

def test_unlinks_are_destructive_outbox_kinds_and_links_are_not():
    for kind in (ce.TAG_DETACH, ce.GROUP_DETACH):
        assert kind in ob.DESTRUCTIVE_OUTBOX_KINDS and ob.is_destructive_outbox_kind(kind)
    for kind in (ce.TAG_LINK, ce.GROUP_LINK):
        assert not ob.is_destructive_outbox_kind(kind)
        assert kind in ob._CREATORS
    assert set(ce.KINDS) <= set(ob._CREATORS) and set(ce.KINDS) <= ob._SELF_RESOLVING_KINDS


def test_a_failed_unlink_is_dead_at_once_never_re_sent_and_retried_only_by_a_person(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    egeria.fail["remove_tag_from_element"] = RuntimeError("OMAG-REPOSITORY-HANDLER-500 the repository is busy")
    client.delete("/api/curate/tags/repo/p/sales", headers=as_user())
    detach = rows(registry, ce.TAG_DETACH)[0]
    assert detach["status"] == "dead" and detach["attempts"] == 1
    assert detach["last_error"].startswith(ob.NOT_RETRIED)
    i = item(state(client), "tag", "sales")
    assert i["state"] == "failed" and i["retry"] and "repository is busy" in i["reason"]
    # neither the drain nor a later sync sends it again
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

    with acting_as(Daemon(DaemonReason.OUTBOX)):
        ob.drain_outbox(registry)
    again = client.post("/api/curate/egeria-sync/repo/p", json={}, headers=as_user())
    assert again.json()["queued"] == []
    assert egeria.names().count("remove_tag_from_element") == 1
    # the person's retry: a NEW row, the dead one untouched
    egeria.fail.clear()
    r = client.post("/api/curate/egeria-sync/repo/p", json={"retry": {"kind": "tag", "name": "sales"}},
                    headers=as_user())
    assert r.status_code == 200, r.text
    detaches = rows(registry, ce.TAG_DETACH)
    assert len(detaches) == 2 and detaches[1]["status"] == "dead" and detaches[0]["status"] == "done"
    assert item(state(client), "tag", "sales")["state"] == "unlinked"


def test_a_retry_of_an_item_that_did_not_fail_is_refused(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    r = client.post("/api/curate/egeria-sync/repo/p", json={"retry": {"kind": "tag", "name": "sales"}},
                    headers=as_user())
    assert r.status_code == 409


def test_a_failed_link_retries_on_its_own_and_says_so(client, registry, egeria):
    egeria.fail["add_tag_to_element"] = RuntimeError("connection reset")
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    link = rows(registry, ce.TAG_LINK)[0]
    assert link["status"] == "failed"
    i = item(state(client), "tag", "sales")
    assert i["state"] == "retrying" and i["word"] == "pending · retrying" and "connection reset" in i["reason"]


def test_a_removal_retires_a_link_that_never_landed_instead_of_racing_it(client, registry, egeria):
    egeria.fail["add_tag_to_element"] = RuntimeError("connection reset")
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    client.delete("/api/curate/tags/repo/p/sales", headers=as_user())
    link = rows(registry, ce.TAG_LINK)[0]
    assert link["status"] == "cancelled"
    assert rows(registry, ce.TAG_DETACH) == [], "nothing landed, so there is nothing to unlink"
    assert item(state(client), "tag", "sales") is None


def test_rows_for_an_asset_that_is_no_longer_the_resources_are_never_detached(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    registry.set_egeria_asset_guid("p", "77777777-2222-3333-4444-555555555555")      # wiped and re-published
    registry.remove_resource_tag("repo", "p", "sales")
    out = client.post("/api/curate/egeria-sync/repo/p", json={}, headers=as_user()).json()
    assert out["queued"] == [] and "remove_tag_from_element" not in egeria.names()


# ── 6. curation access ──────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def zoned(monkeypatch, egeria):
    """The asset is in a secured zone that grants only `salesTeam` (ADD_FEEDBACK/ATTACH/... via DEFAULT)."""
    fake = install_zones(monkeypatch)
    fake.elements[ASSET] = zoned_element(ASSET, zones=["sales-zone"], owners=["someone-else"])
    fake.controls["sales-zone"] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
    return fake


def test_curation_access_refuses_a_tag_and_records_nothing(client, registry, egeria, zoned):
    r = client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    assert r.status_code == 403
    assert "sales-zone" in r.json()["detail"]
    assert registry.list_resource_tags("repo", "p") == [] and rows(registry) == [] and egeria.calls == []


def test_curation_access_refuses_a_group_change_and_records_nothing(client, registry, egeria, zoned):
    r = client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    assert r.status_code == 403
    assert registry.get("p").group_slug == "" and rows(registry) == []


def test_the_tag_check_asks_for_add_feedback_as_egeria_does(client, registry, egeria, zoned):
    """A control that grants ADD_FEEDBACK and UPDATE_PROPERTIES (and nothing by DEFAULT) lets the tag through:
    the check names Egeria's own operation for a tag link."""
    zoned.controls["sales-zone"] = {"associatedSecurityList": {
        "ADD_FEEDBACK": ["allUsers"], "UPDATE_PROPERTIES": ["allUsers"], "DEFAULT": ["salesTeam"]}}
    r = client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    assert r.status_code == 200, r.text
    assert item(state(client), "tag", "sales")["state"] == "in_egeria"


def test_a_signed_out_sync_is_401(client):
    assert client.post("/api/curate/egeria-sync/repo/p", json={}).status_code == 401


# ── 7. a database resource uses the same path ───────────────────────────────────────────────────────────────

def test_a_database_tag_links_to_the_database_asset(client, registry, egeria):
    registry.register_database(DatabaseEntity(slug="db1", display_name="db1", db_type="postgresql", host="h", port=5432,
                                               database_name="db1", egeria_asset_guid=OTHER_ASSET))
    with registry._conn() as conn:
        conn.execute("UPDATE databases SET egeria_asset_guid=? WHERE slug=?", (OTHER_ASSET, "db1"))
    r = client.post("/api/curate/tags/database/db1", json={"tag": "pii"}, headers=as_user())
    assert r.status_code == 200, r.text
    tag_guid = next(iter(egeria.tags))
    assert (OTHER_ASSET, tag_guid) in egeria.tag_links
    assert item(state(client, "db1", "database"), "tag", "pii")["state"] == "in_egeria"


# ── 8. the drain's feedback client: same factory, built only when a tag row needs it ─────────────────────

def test_the_default_drain_builds_the_feedback_client_from_the_factory_only_on_first_use(monkeypatch):
    built = []

    class Factory:
        def of(self, cls):
            built.append(cls.__name__)
            return f"client:{cls.__name__}"

    class FakePublisher:
        def __init__(self, *a, identity=None, **k):
            self._discovery = self._metadata_expert = self._collection_manager = None

        def _connect(self):
            self._clients = Factory()

        def _find_element_guid(self, qn):
            return ""

    monkeypatch.setattr("resource_explorer.surveyors.egeria_publisher.EgeriaPublisher", FakePublisher)
    monkeypatch.setattr("resource_explorer.egeria_clients._daemon_credential", lambda: ("svc-fake", "pw-fake"))
    from resource_explorer.egeria_clients import Daemon, DaemonReason

    clients, _ = ob._default_clients(Daemon(DaemonReason.OUTBOX))
    assert built == [], "a drain with no tag rows builds no feedback client"
    assert clients.require("feedback") == "client:ClassificationExplorer"
    assert clients.require("feedback") == "client:ClassificationExplorer" and built == ["ClassificationExplorer"]


# ══ round 2 (review of e637cc09) ═══════════════════════════════════════════════════════════════════════════

def _daemon(requested_by=None):
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as

    return acting_as(Daemon(DaemonReason.OUTBOX, requested_by=requested_by))


def _row(registry, row_id):
    return next(r for r in rows(registry) if r["id"] == row_id)


def _claim(registry, row_id):
    """What a concurrent drainer's claim does to a row: running, with a fresh claim."""
    from datetime import datetime
    with registry._conn() as conn:
        conn.execute("UPDATE egeria_outbox SET status='running', claimed_at=? WHERE id=?",
                     (datetime.utcnow().isoformat(), row_id))


# R2-1: a group delete is a detach of every member: author required, DETACH checked per member first ────────

def test_r2_a_signed_out_group_delete_is_401_and_changes_nothing(client, registry, egeria):
    client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    r = client.delete("/api/projects/groups/sales")
    assert r.status_code == 401
    assert registry.get_group("sales") is not None and registry.get("p").group_slug == "sales"


def test_r2_a_group_delete_is_refused_whole_when_a_member_may_not_be_detached(client, registry, egeria, monkeypatch):
    client.post("/api/projects/p/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    client.post("/api/projects/q/group", json={"group_slug": "sales", "resource_type": "repo"}, headers=as_user())
    n_rows = len(registry.list_outbox_rows_for_kinds("repo", "q", ce.KINDS))
    fake = install_zones(monkeypatch)
    fake.elements[OTHER_ASSET] = zoned_element(OTHER_ASSET, zones=["sales-zone"], owners=["someone-else"])
    fake.controls["sales-zone"] = {"associatedSecurityList": {"DETACH": ["salesTeam"], "DEFAULT": ["allUsers"]}}
    r = client.delete("/api/projects/groups/sales", headers=as_user())
    assert r.status_code == 403
    assert "q" in r.json()["detail"] and "sales-zone" in r.json()["detail"]
    assert registry.get_group("sales") is not None
    assert registry.get("p").group_slug == "sales" and registry.get("q").group_slug == "sales"
    assert len(registry.list_outbox_rows_for_kinds("repo", "q", ce.KINDS)) == n_rows
    assert not [c for c in egeria.calls if c[0] == "remove_from_collection"]


def test_r2_the_group_delete_route_no_longer_skips_the_access_check():
    import inspect

    from resource_explorer.web.routes import projects
    src = inspect.getsource(projects.delete_group)
    assert "check_access=False" not in src and "_require_group_author" in src


# R2-2: a cancel that loses to a drain's claim re-plans instead of trusting the stale plan ──────────────────

def test_r2_a_re_add_whose_old_unlink_was_claimed_first_still_ends_linked(registry, egeria, monkeypatch):
    with _daemon("peterprofile"):
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False)
        registry.remove_resource_tag("repo", "p", "sales")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        detach = rows(registry, ce.TAG_DETACH)[0]["id"]
        real_cancel = registry.cancel_outbox_row

        def claimed_first(row_id, reason):
            _claim(registry, row_id)                   # the drain took it a moment before the cancel
            return real_cancel(row_id, reason)
        monkeypatch.setattr(registry, "cancel_outbox_row", claimed_first)
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        out = ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        assert out["cancelled"] == [] and len(out["queued"]) == 1, "a fresh link is queued behind the landing unlink"
        # the claimed unlink lands, then the link
        tag_guid = next(iter(egeria.tags))
        egeria.tag_links.discard((ASSET, tag_guid))
        registry.mark_outbox_done(detach, tag_guid)
        ob.drain_outbox(registry)
    assert (ASSET, tag_guid) in egeria.tag_links
    assert item(ce.plan_as_dict(ce.curation_plan(registry, "repo", "p")), "tag", "sales")["state"] == "in_egeria"


def test_r2_a_removal_whose_unsent_link_was_claimed_first_unlinks_after_it_lands(registry, egeria, monkeypatch):
    with _daemon("peterprofile"):
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        link = rows(registry, ce.TAG_LINK)[0]["id"]
        real_cancel = registry.cancel_outbox_row

        def claimed_first(row_id, reason):
            _claim(registry, row_id)
            return real_cancel(row_id, reason)
        monkeypatch.setattr(registry, "cancel_outbox_row", claimed_first)
        registry.remove_resource_tag("repo", "p", "sales")
        out = ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        assert out["cancelled"] == [] and len(out["queued"]) == 1, "an unlink is queued behind the landing link"
        # the claimed link lands in Egeria
        egeria.tags["tag-x"] = {"name": "sales", "qn": "InformalTag::sales"}
        egeria.tag_links.add((ASSET, "tag-x"))
        registry.mark_outbox_done(link, "tag-x")
        ob.drain_outbox(registry)
    assert (ASSET, "tag-x") not in egeria.tag_links
    assert item(ce.plan_as_dict(ce.curation_plan(registry, "repo", "p")), "tag", "sales")["state"] == "unlinked"


# R2-3: an unlink never overtakes a link still being sent ───────────────────────────────────────────────────

def test_r2_an_unlink_waits_while_its_link_is_running_and_never_shows_unlinked_early(registry, egeria):
    with _daemon("peterprofile"):
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False, drain=False)
        link = rows(registry, ce.TAG_LINK)[0]["id"]
        _claim(registry, link)                          # another drainer is sending the link right now
        registry.remove_resource_tag("repo", "p", "sales")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False)
        detach = rows(registry, ce.TAG_DETACH)[0]
        assert detach["status"] == "pending" and detach["attempts"] == 0, "deferred, not attempted"
        assert "remove_tag_from_element" not in egeria.names()
        st = item(ce.plan_as_dict(ce.curation_plan(registry, "repo", "p")), "tag", "sales")
        assert st["state"] == "pending" and st["state"] != "unlinked"
        # the link lands; the unlink then goes
        egeria.tags["tag-x"] = {"name": "sales", "qn": "InformalTag::sales"}
        egeria.tag_links.add((ASSET, "tag-x"))
        registry.mark_outbox_done(link, "tag-x")
        ob.drain_outbox(registry)
    assert (ASSET, "tag-x") not in egeria.tag_links
    assert _row(registry, detach["id"])["status"] == "done"


# R2-4: each row records its own requester; never another decision's author ───────────────────────────────

def test_r2_a_tag_unlink_from_a_publish_with_nobody_asking_records_no_requester(registry, egeria):
    with _daemon("peterprofile"):
        registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
        ce.sync_curation(registry, "repo", "p", by="peterprofile", check_access=False)
    registry.record_group_change("repo", "p", "", "erinoverview")
    registry.remove_resource_tag("repo", "p", "sales")
    with _daemon(None):
        ce.publish_pending_curation(registry, "repo", "p", ASSET)
    by = json.loads(rows(registry, ce.TAG_DETACH)[0]["payload_json"])["by"]
    assert by == "", "not the last group change's author"


def test_r2_a_publish_hook_records_the_publish_requester(registry, egeria):
    registry.add_resource_tag("repo", "p", "sales", author="peterprofile")
    with _daemon("garygeeke"):
        ce.publish_pending_curation(registry, "repo", "p", ASSET)
    assert json.loads(rows(registry, ce.TAG_LINK)[0]["payload_json"])["by"] == "garygeeke"


# R2-5: the tag keeps the case it was typed in; matching ignores case; a taken qualifiedName is adopted ──────

def test_r2_a_tag_keeps_the_typed_case_in_egeria_with_a_lower_case_key(client, registry, egeria):
    client.post("/api/curate/tags/repo/p", json={"tag": "Sales EMEA"}, headers=as_user())
    (t,) = egeria.tags.values()
    assert t == {"name": "Sales EMEA", "qn": "InformalTag::sales emea"}
    assert registry.list_resource_tags("repo", "p") == ["sales emea"]


def test_r2_an_existing_tag_in_another_case_is_found_not_duplicated(client, registry, egeria):
    egeria.tags["tag-up"] = {"name": "SALES", "qn": "InformalTag::::peter::SALES::1760000000"}
    client.post("/api/curate/tags/repo/p", json={"tag": "Sales"}, headers=as_user())
    assert "create_informal_tag" not in egeria.names()
    assert (ASSET, "tag-up") in egeria.tag_links


def test_r2_a_qualified_name_taken_under_another_display_name_is_adopted_not_dead(client, registry, egeria):
    egeria.tags["tag-qn"] = {"name": "Sales team", "qn": "InformalTag::sales"}
    egeria.fail["create_informal_tag"] = RuntimeError(
        "SERVER_ERROR_500 OMAG-COMMON-409-001 the qualifiedName InformalTag::sales is not available for use")
    client.post("/api/curate/tags/repo/p", json={"tag": "sales"}, headers=as_user())
    assert (ASSET, "tag-qn") in egeria.tag_links
    assert rows(registry, ce.TAG_LINK)[0]["status"] == "done"


# R2-6: CLI and batch group changes go through the same access check ───────────────────────────────────────

@pytest.fixture
def cli_caller_reset():
    """The CLI's `activate` sets the caller ContextVar set-and-forget (one command = one process); a test must
    not leak it into the next test."""
    from resource_explorer.a2a_auth import current_caller

    token = current_caller.set(None)
    yield
    current_caller.reset(token)


def test_r2_the_cli_refuses_a_group_change_without_a_signed_in_caller(registry, monkeypatch, cli_caller_reset):
    from typer.testing import CliRunner

    from resource_explorer.cli import session as cli_session
    from resource_explorer.cli.main import app
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **kw: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setattr(cli_session, "load_session", lambda: None)
    for args in (["group", "assign", "repo", "p", "sales"], ["group", "unassign", "repo", "p"],
                 ["group", "remove", "sales", "--yes"]):
        r = CliRunner().invoke(app, args)
        assert r.exit_code == cli_session.EXIT_NOT_SIGNED_IN, (args, r.output)
    assert registry.get("p").group_slug == "" and registry.get_group("sales") is not None


def test_r2_the_cli_refuses_a_group_change_curation_access_denies(registry, monkeypatch, cli_caller_reset):
    from typer.testing import CliRunner

    from resource_explorer.cli import session as cli_session
    from resource_explorer.cli.main import app
    from resource_explorer.egeria_identity import EgeriaIdentity
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **kw: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setattr(cli_session, "require_identity", lambda console=None: EgeriaIdentity(
        user_id="peterprofile", token="t", kind="caller"))
    fake = install_zones(monkeypatch)
    fake.elements[ASSET] = zoned_element(ASSET, zones=["sales-zone"], owners=["someone-else"])
    fake.controls["sales-zone"] = {"associatedSecurityList": {"DEFAULT": ["salesTeam"]}}
    r = CliRunner().invoke(app, ["group", "assign", "repo", "p", "sales"])
    assert r.exit_code == 1 and "sales-zone" in r.output
    assert registry.get("p").group_slug == ""


def test_r2_a_batch_import_group_change_is_refused_without_a_caller(registry, cli_caller_reset):
    from resource_explorer.batch_io import import_file

    registry.add(Project(slug="r", display_name="r", github_url="https://github.com/x/r", description=""))
    text = "resource_type,address,group\nrepo,https://github.com/x/r,sales\n"
    res = import_file(registry, text, accept_changes=[{"line": 2, "field": "group"}])
    assert registry.get("r").group_slug == ""
    assert any("not permitted" in f["message"] for f in res["failures"]), res
