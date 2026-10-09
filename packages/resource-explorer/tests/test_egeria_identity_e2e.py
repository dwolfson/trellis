"""Brief I, per converted area: which identity reaches the pyegeria boundary.

Every test drives RE's real path and fakes ONLY the pyegeria client classes (patched where RE
imports them from). The fake records, per client built, the Egeria user it was built for, the
bearer token set on it, and whether it minted its own (a password exchange: the daemon). The
assertion is on that record — "the person's token reached Egeria" or "the daemon minted" — never
on an RE-internal flag.

Nothing here contacts Egeria.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time

import pytest

PERSON, PERSON_TOKEN = "dana", "tok-dana-signed-in"
DAEMON_USER, DAEMON_PW = "re-daemon", "pw-daemon-not-a-real-one"


class Boundary:
    """What reached pyegeria: one dict per client constructed."""

    def __init__(self):
        self.clients: list[dict] = []
        self.calls: list[tuple] = []

    def users_and_tokens(self):
        return {(c["cls"], c["user"], c["token"], c["minted"]) for c in self.clients}

    def fake(self, name, **methods):
        boundary = self

        class Fake:
            def __init__(self, *args, **kwargs):
                self._rec = {"cls": name, "server": args[0] if args else "", "user": args[2] if len(args) > 2 else "",
                             "token": None, "minted": False}
                boundary.clients.append(self._rec)

            def set_bearer_token(self, token):
                self._rec["token"] = token

            def create_egeria_bearer_token(self, *a, **k):
                self._rec["minted"] = True
                self._rec["token"] = f"minted-for-{self._rec['user']}"
                return self._rec["token"]

            def __getattr__(self, attr):
                if attr in methods:
                    fn = methods[attr]

                    def call(*a, **k):
                        boundary.calls.append((name, attr, self._rec["user"], self._rec["token"]))
                        return fn(*a, **k)
                    return call
                raise AttributeError(attr)

        Fake.__name__ = name
        return Fake


@pytest.fixture
def boundary(monkeypatch):
    b = Boundary()
    # The daemon's configured credential, on a COPY of the config (never the shared one).
    from resource_explorer import config

    cfg = config.get_config().model_copy(deep=True)
    cfg.egeria.user_id, cfg.egeria.user_password = DAEMON_USER, DAEMON_PW
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    return b


@pytest.fixture
def reg(tmp_path, monkeypatch):
    from resource_explorer.registry import ProjectRegistry, Project

    r = ProjectRegistry(db_path=str(tmp_path / "e2e.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p"))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", r.__dict__) or None)
    return r


def _token(user=PERSON, egeria_token=PERSON_TOKEN):
    from resource_explorer.auth import create_access_token

    return {"Authorization": "Bearer " + create_access_token(user_id=user, egeria_token=egeria_token)}


@pytest.fixture
def client(reg):
    from fastapi.testclient import TestClient

    from resource_explorer.web.app import app

    return TestClient(app)


# ── bulk ops: Delete in Egeria (a route) → the signed-in Caller ───────────────

def test_bulk_delete_in_egeria_reaches_egeria_with_the_callers_token(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")
    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker", delete_asset=lambda g: None))
    r = client.post("/api/egeria/linkage/delete-in-egeria",
                    json={"targets": [{"entity_type": "repo", "slug": "p"}], "dry_run": False}, headers=_token())
    assert r.status_code == 200, r.text
    assert r.json()["succeeded"] == 1
    assert boundary.users_and_tokens() == {("AssetMaker", PERSON, PERSON_TOKEN, False)}
    assert boundary.calls == [("AssetMaker", "delete_asset", PERSON, PERSON_TOKEN)]


def test_bulk_delete_with_no_caller_is_401_and_builds_no_client(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")
    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker", delete_asset=lambda g: None))
    r = client.post("/api/egeria/linkage/delete-in-egeria",
                    json={"targets": [{"entity_type": "repo", "slug": "p"}], "dry_run": False})
    assert r.status_code == 401, r.text
    assert boundary.clients == [], "no caller must never fall back to the service account"


def test_bulk_delete_with_an_expired_sign_in_is_401_with_the_sentence(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")
    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker", delete_asset=lambda g: None))
    headers = _token()
    # The Egeria token's own exp has passed while the app session still stands (the factory reads
    # the Egeria token's exp; patched here, after the app JWT was minted).
    monkeypatch.setattr("resource_explorer.egeria_clients._token_expiry", lambda tok: int(time.time()) - 5)
    r = client.post("/api/egeria/linkage/delete-in-egeria",
                    json={"targets": [{"entity_type": "repo", "slug": "p"}], "dry_run": False}, headers=headers)
    assert r.status_code == 401
    assert r.json()["detail"] == "your Egeria sign-in expired; sign in again"
    assert boundary.clients == []


def test_a_refusal_is_reported_as_egerias_and_never_retried_as_anyone_else(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")

    class Refused(Exception):
        related_http_code = 403

    def refuse(guid):
        raise Refused("OPEN-METADATA-SECURITY-403-007 User dana is not authorized to issue operation "
                      "Delete on Asset guid-p. More text here.")
    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker", delete_asset=refuse))
    r = client.post("/api/egeria/linkage/delete-in-egeria",
                    json={"targets": [{"entity_type": "repo", "slug": "p"}], "dry_run": False}, headers=_token())
    detail = r.json()["details"][0]
    assert detail["result"] == "failed"
    assert detail["message"].startswith("refused by Egeria: OPEN-METADATA-SECURITY-403-007 User dana")
    assert len(boundary.clients) == 1 and boundary.clients[0]["user"] == PERSON
    assert not any(c["minted"] for c in boundary.clients), "never retried as the service account"


# ── linkage recheck (a route) → the signed-in Caller ─────────────────────────

def test_linkage_recheck_route_reads_as_the_caller(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")
    monkeypatch.setattr("pyegeria.omvs.metadata_expert.MetadataExpert", boundary.fake(
        "MetadataExpert", get_metadata_element_by_guid=lambda g: {"elementHeader": {"guid": g}}))
    r = client.post("/api/egeria/linkage/recheck", headers=_token())
    assert r.status_code == 200, r.text
    assert boundary.users_and_tokens() == {("MetadataExpert", PERSON, PERSON_TOKEN, False)}


# ── read routes: documentation-source read-back, project search → Caller ─────

def test_doc_source_read_back_route_reads_as_the_caller(boundary, reg, client, monkeypatch):
    reg.set_egeria_asset_guid("p", "guid-p")
    monkeypatch.setattr("resource_explorer.web.routes.doc_sources._publish_status",
                        lambda *a, **k: {"is_published": True, "note": ""})
    monkeypatch.setattr("pyegeria.omvs.metadata_expert.MetadataExpert", boundary.fake(
        "MetadataExpert", get_related_metadata_elements=lambda *a, **k: "No elements found"))
    r = client.get("/api/doc-sources/repo/p", headers=_token())
    assert r.status_code == 200, r.text
    assert boundary.users_and_tokens() == {("MetadataExpert", PERSON, PERSON_TOKEN, False)}


def test_project_search_route_reads_as_the_caller(boundary, reg, client, monkeypatch):
    from resource_explorer.config import get_config

    monkeypatch.setenv("EGERIA_PLATFORM_URL", get_config().egeria.platform_url)   # the allowed one
    monkeypatch.setattr("pyegeria.ProjectManager", boundary.fake("ProjectManager", find_projects=lambda *a, **k: []))
    r = client.get("/api/project-context/search/candidates?q=x", headers=_token())
    assert r.status_code == 200, r.text
    assert boundary.users_and_tokens() == {("ProjectManager", PERSON, PERSON_TOKEN, False)}


# ── egeria_resync: the scheduled pass → Daemon(RESYNC) ────────────────────────

def test_the_resync_loop_runs_as_the_daemon(boundary, reg, monkeypatch):
    from resource_explorer import egeria_resync

    for cls in ("AssetMaker", "ProjectManager", "CollectionManager", "ClassificationExplorer"):
        monkeypatch.setattr(f"pyegeria.{cls}", boundary.fake(cls))
    monkeypatch.setattr("resource_explorer.omsecrets_reproject.heal_missing", lambda: None)
    stop = threading.Event()
    seen = {}

    def one_pass(registry=None):
        stop.set()                                   # exactly one pass, whatever happens below
        ok, why = egeria_resync.EgeriaResync(registry=reg)._connect()
        seen["connected"] = (ok, why)
        try:
            from resource_explorer.egeria_clients import current_principal

            seen["principal"] = current_principal()
        except Exception as exc:  # noqa: BLE001 - recorded, asserted below
            seen["principal"] = exc
        return {"reachable": True, "applied": {}}

    monkeypatch.setattr(egeria_resync, "scan_and_clear", one_pass)
    egeria_resync._loop(0, stop)
    assert seen["connected"][0], seen["connected"]
    assert seen["principal"].kind == "daemon" and seen["principal"].reason == "egeria_resync"
    users = {(c["cls"], c["user"]) for c in boundary.clients}
    assert users == {(c, DAEMON_USER) for c in
                     ("AssetMaker", "ProjectManager", "CollectionManager", "ClassificationExplorer")}
    assert sum(c["minted"] for c in boundary.clients) == 1, "one token, shared across sub-clients"
    assert {c["token"] for c in boundary.clients} == {f"minted-for-{DAEMON_USER}"}


# ── reachability → Daemon(REACHABILITY), even with a person signed in ─────────

def test_reachability_runs_as_the_daemon_even_from_a_signed_in_request(boundary, monkeypatch, signed_in_caller):
    from resource_explorer import reachability

    monkeypatch.setattr("pyegeria.AutomatedCuration", boundary.fake("AutomatedCuration"))
    monkeypatch.setattr("pyegeria.MetadataExpert", boundary.fake("MetadataExpert"))
    reachability._get_clients()
    assert {(c["cls"], c["user"]) for c in boundary.clients} == {
        ("AutomatedCuration", DAEMON_USER), ("MetadataExpert", DAEMON_USER)}
    assert not any(c["token"] == "tok-test-caller" for c in boundary.clients)


# ── the scheduler tick (RFA sync) → Daemon(SCHEDULER) ─────────────────────────

def test_the_scheduler_tick_runs_rfa_sync_as_the_daemon(boundary, monkeypatch):
    from resource_explorer import rfa_egeria_sync, scheduler

    monkeypatch.setattr("pyegeria.MyProfile", boundary.fake("MyProfile"))
    monkeypatch.setattr("pyegeria.MetadataExpert", boundary.fake("MetadataExpert"))
    for name in ("_run_due", "_drain_egeria_outbox", "_sweep_native_surveys"):
        monkeypatch.setattr(scheduler, name, lambda: None)
    monkeypatch.setattr(scheduler, "_reconcile_rfa_actions", lambda: rfa_egeria_sync._get_clients())
    scheduler._tick()
    assert {(c["cls"], c["user"]) for c in boundary.clients} == {
        ("MyProfile", DAEMON_USER), ("MetadataExpert", DAEMON_USER)}


# ── the outbox: inline drains run as the person; only the background loop is the daemon ─

def _drain_fakes(boundary, monkeypatch):
    for cls in ("AssetMaker", "AutomatedCuration", "ExternalReferences"):
        monkeypatch.setattr(f"pyegeria.{cls}", boundary.fake(cls))
    monkeypatch.setattr("pyegeria.CollectionManager", boundary.fake(
        "CollectionManager", add_to_collection=lambda *a, **k: None))
    monkeypatch.setattr("pyegeria.omvs.data_discovery.DataDiscovery", boundary.fake("DataDiscovery"))
    monkeypatch.setattr("pyegeria.omvs.metadata_expert.MetadataExpert", boundary.fake("MetadataExpert"))


def test_an_inline_drain_in_a_persons_request_runs_as_that_person(boundary, reg, monkeypatch, signed_in_caller):
    from resource_explorer.egeria_outbox import drain_outbox

    _drain_fakes(boundary, monkeypatch)
    reg.enqueue_outbox_element("repo", "p", "collection_membership", "CollectionMembership::c::m",
                               {"collection_guid": "c", "member_guid": "m"})
    assert drain_outbox(reg)["done"] == 1
    adds = [c for c in boundary.calls if c[1] == "add_to_collection"]
    assert {(u, t) for _, _, u, t in adds} == {("test-caller", "tok-test-caller")}
    assert not any(c["minted"] for c in boundary.clients), "never the daemon for a person's act"


def test_the_background_drain_loop_runs_as_the_daemon_even_beside_a_person(boundary, reg, monkeypatch, signed_in_caller):
    from resource_explorer import scheduler

    _drain_fakes(boundary, monkeypatch)
    reg.enqueue_outbox_element("repo", "p", "collection_membership", "CollectionMembership::c::m",
                               {"collection_guid": "c", "member_guid": "m"})
    scheduler._drain_egeria_outbox()
    adds = [c for c in boundary.calls if c[1] == "add_to_collection"]
    assert adds and {(u, t) for _, _, u, t in adds} == {(DAEMON_USER, f"minted-for-{DAEMON_USER}")}
    assert not any(c["token"] == "tok-test-caller" for c in boundary.clients)


def test_a_drain_with_no_identity_claims_nothing_and_sends_nothing(boundary, reg, monkeypatch):
    from resource_explorer.egeria_outbox import drain_outbox

    _drain_fakes(boundary, monkeypatch)
    rid = reg.enqueue_outbox_element("repo", "p", "collection_membership", "CollectionMembership::c::m",
                                     {"collection_guid": "c", "member_guid": "m"})
    out = drain_outbox(reg)
    assert out["claimed"] == 0 and "sign in" in out["identity_error"]
    assert boundary.clients == []
    assert reg.get_outbox_element(rid)["status"] == "pending"


# ── the catalogue gateway: Curate route → Caller; drain → stored credential or daemon ─

def _db_entity(**kw):
    from resource_explorer.registry import DatabaseEntity

    return DatabaseEntity(slug="db", display_name="Shop", db_type="postgresql", host="localhost",
                          port=5442, database_name="shop", **kw)


def test_the_gateway_on_a_curate_route_acts_as_the_caller_and_ignores_stored_credentials(boundary, monkeypatch, signed_in_caller):
    from resource_explorer.catalogue_commit import make_gateway

    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker"))
    gw = make_gateway(_db_entity(egeria_user="stored-user", egeria_password="stored-pw"))
    gw._client("AssetMaker")
    assert boundary.users_and_tokens() == {("AssetMaker", "test-caller", "tok-test-caller", False)}


def test_the_drain_gateway_keeps_a_stored_credential_and_else_uses_the_daemon(boundary, monkeypatch):
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as
    from resource_explorer.egeria_outbox import _catalogue_gateway

    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker"))

    class Clients:
        catalogue_gateway = None

        def __init__(self, entity):
            self._entity = entity

        def require(self, name):
            entity = self._entity
            return type("R", (), {"get_database": lambda self, slug, allow_unreadable=True: entity})()

    with acting_as(Daemon(DaemonReason.OUTBOX)):                 # the background loop
        _catalogue_gateway(Clients(_db_entity(egeria_user="stored-user", egeria_password="stored-pw")),
                           {"slug": "db"})._client("AssetMaker")
        _catalogue_gateway(Clients(_db_entity()), {"slug": "db"})._client("AssetMaker")
    assert [(c["user"], c["minted"]) for c in boundary.clients] == [("stored-user", True), (DAEMON_USER, True)]


def test_an_inline_drain_gateway_runs_as_the_person_not_the_stored_credential(boundary, monkeypatch, signed_in_caller):
    from resource_explorer.egeria_outbox import _catalogue_gateway

    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker"))
    entity = _db_entity(egeria_user="stored-user", egeria_password="stored-pw")
    clients = type("C", (), {"catalogue_gateway": None, "require": lambda self, n: type(
        "R", (), {"get_database": lambda self, slug, allow_unreadable=True: entity})()})()
    _catalogue_gateway(clients, {"slug": "db"})._client("AssetMaker")
    assert boundary.users_and_tokens() == {("AssetMaker", "test-caller", "tok-test-caller", False)}


# ── item 1: no credential goes to a platform RE is not configured for ────────

def test_an_entity_naming_another_platform_is_refused_and_nothing_is_sent(boundary, monkeypatch, signed_in_caller):
    from resource_explorer.catalogue_commit import make_gateway
    from resource_explorer.egeria_clients import PlatformNotAllowed

    monkeypatch.setattr("pyegeria.AssetMaker", boundary.fake("AssetMaker"))
    gw = make_gateway(_db_entity(egeria_url="https://evil.invalid"))
    with pytest.raises(PlatformNotAllowed, match="not configured for: https://evil.invalid:443"):
        gw._client("AssetMaker")
    assert boundary.clients == [], "no client built, no token sent"


def test_a_stored_credential_never_leaves_its_own_entitys_platform(boundary, monkeypatch):
    from resource_explorer.egeria_clients import (
        DaemonReason, PlatformNotAllowed, StoredOrDaemon, egeria_client,
    )

    monkeypatch.setattr("resource_explorer.egeria_clients.allowed_platforms",
                        lambda: frozenset({"https://a.invalid:443", "https://b.invalid:443"}))
    ident = StoredOrDaemon(_db_entity(egeria_url="https://a.invalid", egeria_user="s", egeria_password="p"),
                           DaemonReason.OUTBOX)
    with pytest.raises(PlatformNotAllowed):
        egeria_client(ident, purpose="t", platform_url="https://b.invalid").of(boundary.fake("AssetMaker"))
    egeria_client(ident, purpose="t", platform_url="https://a.invalid").of(boundary.fake("AssetMaker"))
    assert [c["user"] for c in boundary.clients] == ["s"]


def test_a_publish_route_naming_another_platform_is_403_and_sends_nothing(boundary, reg, client, monkeypatch):
    from resource_explorer.registry import FileSystemEntity

    reg.register_filesystem(FileSystemEntity(slug="fs", display_name="FS", local_mount_point="/tmp",
                                             egeria_url="https://evil.invalid"))
    monkeypatch.setattr(reg, "get_latest_filesystem_survey", lambda slug: {"survey_data": {}}, raising=False)
    for cls in ("AutomatedCuration", "AssetMaker"):
        monkeypatch.setattr(f"pyegeria.{cls}", boundary.fake(cls))
    monkeypatch.setattr("pyegeria.omvs.data_discovery.DataDiscovery", boundary.fake("DataDiscovery"))
    r = client.post("/api/filesystems/fs/publish", json={}, headers=_token())
    assert r.status_code == 403, r.text
    assert "not configured for: https://evil.invalid:443" in r.json()["detail"]
    assert boundary.clients == []


# ── the run queue: a survey → Daemon(RUN_QUEUE, requested_by), Ownership = requester ─

def test_a_queued_survey_runs_as_the_daemon_and_stamps_ownership_as_the_requester(boundary, reg, monkeypatch):
    from resource_explorer import run_queue as rq

    stamped = []
    monkeypatch.setattr("pyegeria.ClassificationExplorer", boundary.fake(
        "ClassificationExplorer",
        add_ownership_to_element=lambda guid, body: stamped.append(body["properties"]["owner"])))

    def handler(target, result_ref):
        from resource_explorer.egeria_identity import caller_credentials, set_ownership

        who = caller_credentials()
        assert set_ownership("guid-x", who.user_id) is True
        return rq.RunOutcome(state="succeeded")

    monkeypatch.setitem(rq.HANDLERS, "analysis_run", handler)
    reg.enqueue_run("analysis_run", {"slug": "p"}, requested_by="erin")
    row = reg.claim_next_run("host:1", {"pid": os.getpid()})
    assert rq.execute_run(row, reg).state == "succeeded"
    assert stamped == ["erin"], "Ownership names the person who asked"
    assert [(c["user"], c["minted"]) for c in boundary.clients] == [(DAEMON_USER, True)], \
        "and the daemon authenticates"


# ── the run queue: a queued Publish → Daemon(RUN_QUEUE, requested_by) ─────
# Owner's Egeria-consistent ruling (2026-10-09): a queued write is committed by RE's daemon, and
# the person is the recorded requester and the Ownership owner.

def test_a_queued_publish_is_committed_by_the_daemon_with_ownership_the_requester(boundary, reg, monkeypatch):
    from resource_explorer import run_queue as rq

    stamped = []
    monkeypatch.setattr("pyegeria.ClassificationExplorer", boundary.fake(
        "ClassificationExplorer",
        add_ownership_to_element=lambda guid, body: stamped.append(body["properties"]["owner"])))

    def handler(target, result_ref):
        from resource_explorer.egeria_identity import caller_credentials, set_ownership

        who = caller_credentials()
        assert who.kind == "daemon" and who.requested_by == "dana"
        assert set_ownership("guid-bp", who.user_id) is True
        return rq.RunOutcome(state="succeeded")

    monkeypatch.setitem(rq.HANDLERS, "publish_architecture", handler)
    run_id = reg.enqueue_run("publish_architecture", {"slug": "p"}, requested_by="dana")
    row = reg.claim_next_run("host:1", {"pid": os.getpid()})
    assert rq.execute_run(row, reg).state == "succeeded"
    assert stamped == ["dana"]
    assert [(c["user"], c["minted"]) for c in boundary.clients] == [(DAEMON_USER, True)]
    assert reg.get_run(run_id)["requested_by"] == "dana"


@pytest.mark.parametrize("kind", ["publish_architecture", "curate_commit", "catalogue_commit",
                                  "materialize_components"])
def test_a_persons_queued_action_with_no_requester_fails_loudly_and_writes_nothing(boundary, reg, monkeypatch, kind):
    from resource_explorer import run_queue as rq

    ran = []
    monkeypatch.setitem(rq.HANDLERS, kind, lambda t, r: ran.append(1) or rq.RunOutcome("succeeded"))
    run_id = reg.enqueue_run(kind, {"slug": "p"})
    row = reg.claim_next_run("host:1", {"pid": os.getpid()})
    out = rq.execute_run(row, reg)
    assert out.state == "failed" and out.error == rq.NO_REQUESTER_SENTENCE
    assert ran == [] and boundary.clients == []
    assert reg.get_run(run_id)["error"] == rq.NO_REQUESTER_SENTENCE
