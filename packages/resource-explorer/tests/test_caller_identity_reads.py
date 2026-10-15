"""Caller identity, read side (owner's decision 2026-10-14, option 2 of DESIGN-MCP-SERVER-AND-A2A-GAPS.md).

Everything synchronous that serves a signed-in request runs as the caller; queued writes stay on the service
account with the requester recorded. Inventory: docs/design-notes/evidence/IDENTITY-INVENTORY-2026-10-14.md.

Only the pyegeria boundary is faked: `egeria_clients._build` returns `create_autospec(cls, instance=True,
spec_set=True)` of the REAL pyegeria class RE asked for, so a call RE makes that pyegeria does not have fails
here too. Each assertion is on what reached that boundary: which bearer token was set, and whether a token was
minted from the service account's password.
"""
from __future__ import annotations

import asyncio
import json
import threading
from unittest.mock import create_autospec

import pytest

DAEMON_USER, DAEMON_PW = "re-daemon", "pw-daemon-not-a-real-one"
ERIN, ERIN_TOKEN = "erin", "tok-erin-signed-in"
PETER, PETER_TOKEN = "peter", "tok-peter-signed-in"


class Boundary:
    """Every pyegeria client the factory built: its class, the Egeria user it was built for, and the autospec."""

    def __init__(self):
        self.built: list[dict] = []
        self.configure: dict[str, callable] = {}
        self.lock = threading.Lock()

    def build(self, cls, view_server, platform_url, user_id, password):
        mock = create_autospec(cls, instance=True, spec_set=True)
        mock.create_egeria_bearer_token.return_value = f"minted-for-{user_id}"
        hook = self.configure.get(cls.__name__)
        if hook is not None:
            hook(mock)
        with self.lock:
            self.built.append({"cls": cls.__name__, "user": user_id, "mock": mock,
                               "thread": threading.current_thread().name})
        return mock

    def of(self, name):
        return [b for b in self.built if b["cls"] == name]


@pytest.fixture
def boundary(monkeypatch):
    from resource_explorer import config, egeria_clients

    cfg = config.get_config().model_copy(deep=True)
    cfg.egeria.user_id, cfg.egeria.user_password = DAEMON_USER, DAEMON_PW
    cfg.egeria.platform_url = "https://localhost:9443"
    monkeypatch.setattr(config, "get_config", lambda: cfg)
    b = Boundary()
    monkeypatch.setattr(egeria_clients, "_build", b.build)
    return b


def _signed_in(user, token):
    """Publish `user` as the web login's `_identity_middleware` does (same ContextVar, same CallerIdentity)."""
    from resource_explorer.a2a_auth import CallerIdentity, current_caller

    return current_caller.set(CallerIdentity(user_id=user, egeria_token=token, auth_source="app-jwt"))


def _sent_only_the_callers_token(entry, token):
    mock = entry["mock"]
    mock.set_bearer_token.assert_called_once_with(token)
    mock.create_egeria_bearer_token.assert_not_called()      # never the service account's password exchange
    assert entry["user"] != DAEMON_USER


# ── the web login publishes the same CallerIdentity the factory reads ─────────────────────────────────

def test_the_web_login_session_reaches_the_factory_as_the_caller(boundary):
    """A session JWT minted by RE's login, read back by `_identity_middleware`'s own function, is what
    `Caller()` acts as: the Egeria token inside the JWT is the one set on the client."""
    from pyegeria.omvs.metadata_expert import MetadataExpert

    from resource_explorer.a2a_auth import current_caller
    from resource_explorer.auth import create_access_token, decode_token, identity_from_claims
    from resource_explorer.egeria_clients import Caller, client_scope, egeria_client

    jwt = create_access_token(user_id=PETER, egeria_token=PETER_TOKEN)
    reset = current_caller.set(identity_from_claims(decode_token(jwt)))
    try:
        with client_scope():
            egeria_client(Caller(), purpose="test read").of(MetadataExpert)
    finally:
        current_caller.reset(reset)
    (entry,) = boundary.of("MetadataExpert")
    assert entry["user"] == PETER
    _sent_only_the_callers_token(entry, PETER_TOKEN)


# ── converted: the Technology Type catalog (a module-level instance serving every request) ────────────

def _fresh_route_catalog():
    import resource_explorer.web.routes.survey_definitions as route

    route._tech_type_catalog = None
    return route._get_tech_type_catalog()


def test_the_route_catalog_reads_as_each_caller_and_never_serves_one_callers_answer_to_another(boundary):
    """`web/routes/survey_definitions.py` holds ONE catalog for the process. Erin reads first; Peter's read must
    reach Egeria with Peter's token and return Peter's answer, not Erin's cached one."""
    answers = {ERIN_TOKEN: {"displayName": "seen by erin"}, PETER_TOKEN: {"displayName": "seen by peter"}}

    def per_token(mock):
        def detail(name, output_format="JSON", **kw):
            token = mock.set_bearer_token.call_args.args[0]
            return answers[token]
        mock.get_tech_type_detail.side_effect = detail

    boundary.configure["AutomatedCuration"] = per_token
    from resource_explorer.egeria_clients import client_scope

    catalog = _fresh_route_catalog()
    try:
        reset = _signed_in(ERIN, ERIN_TOKEN)
        try:
            with client_scope():
                assert catalog.get_tech_type_detail("PostgreSQL Relational Database") == answers[ERIN_TOKEN]
        finally:
            from resource_explorer.a2a_auth import current_caller
            current_caller.reset(reset)

        reset = _signed_in(PETER, PETER_TOKEN)
        try:
            with client_scope():
                got = catalog.get_tech_type_detail("PostgreSQL Relational Database")
        finally:
            current_caller.reset(reset)
    finally:
        _fresh_route_catalog()

    assert got == answers[PETER_TOKEN], "Peter was served Erin's cached answer"
    peters = [b for b in boundary.of("AutomatedCuration") if b["user"] == PETER]
    assert len(peters) == 1
    _sent_only_the_callers_token(peters[0], PETER_TOKEN)
    peters[0]["mock"].get_tech_type_detail.assert_called_once()


def test_the_route_catalog_still_caches_within_one_caller(boundary):
    """Keyed per reader, not dropped: the same person asking twice is one Egeria read."""
    boundary.configure["AutomatedCuration"] = lambda m: setattr(m.get_tech_type_detail, "return_value", {"x": 1})
    from resource_explorer.a2a_auth import current_caller
    from resource_explorer.egeria_clients import client_scope

    catalog = _fresh_route_catalog()
    reset = _signed_in(ERIN, ERIN_TOKEN)
    try:
        for _ in range(2):
            with client_scope():
                catalog.get_tech_type_detail("PostgreSQL Relational Database")
    finally:
        current_caller.reset(reset)
        _fresh_route_catalog()
    calls = sum(b["mock"].get_tech_type_detail.call_count for b in boundary.of("AutomatedCuration"))
    assert calls == 1


# ── converted: the A2A / chat agents' hop onto the shared pool keeps the caller ─────────────────────

class _ReadsEgeriaAgent:
    """A stand-in for the BeeAI agent: its run reads Egeria as `Caller()`, from wherever it runs."""

    def __init__(self, seen: dict):
        self.seen = seen

    async def run(self, prompt):
        from pyegeria.omvs.metadata_expert import MetadataExpert

        from resource_explorer.a2a_auth import caller
        from resource_explorer.egeria_clients import Caller, egeria_client

        who = caller()
        self.seen["caller"] = who.user_id if who else None
        self.seen["thread"] = threading.current_thread().name
        egeria_client(Caller(), purpose="agent read", shared=False).of(MetadataExpert)
        return "answered"


def _run_in_event_loop(fn):
    """Call `fn` the way an A2A handler does: synchronously, from inside a running event loop."""
    async def handler():
        return fn()
    return asyncio.run(handler())


def test_an_a2a_agent_run_hops_to_the_pool_and_still_reads_egeria_as_the_caller(boundary, monkeypatch):
    from resource_explorer.a2a_auth import current_caller
    from resource_explorer.agents.stats_agent import StatsAgent

    seen: dict = {}
    agent = StatsAgent()
    monkeypatch.setattr(agent, "_build_agent", lambda: _ReadsEgeriaAgent(seen))
    reset = _signed_in(PETER, PETER_TOKEN)
    try:
        assert _run_in_event_loop(lambda: agent._run_agent("q")) == "answered"
    finally:
        current_caller.reset(reset)
    assert seen["thread"].startswith("re-sync"), "the run must have hopped onto the shared pool"
    assert seen["caller"] == PETER
    (entry,) = boundary.of("MetadataExpert")
    assert entry["thread"].startswith("re-sync")
    _sent_only_the_callers_token(entry, PETER_TOKEN)


def test_a_chat_agent_turn_hops_to_the_pool_and_still_reads_egeria_as_the_caller(boundary, monkeypatch):
    from resource_explorer.a2a_auth import current_caller
    from resource_explorer.agents.conversation_agent import ConversationAgent

    seen: dict = {}
    agent = ConversationAgent()
    monkeypatch.setattr(agent, "_get_agent", lambda: _ReadsEgeriaAgent(seen))
    reset = _signed_in(ERIN, ERIN_TOKEN)
    try:
        assert _run_in_event_loop(lambda: agent._run_persistent("q")) == "answered"
    finally:
        current_caller.reset(reset)
    assert seen["thread"].startswith("re-sync") and seen["caller"] == ERIN
    (entry,) = boundary.of("MetadataExpert")
    _sent_only_the_callers_token(entry, ERIN_TOKEN)


def test_the_hop_does_not_leak_the_caller_into_the_pool_thread_afterwards(boundary, monkeypatch):
    """The copied context is per call: the pool thread that served Peter holds no caller for the next job."""
    from resource_explorer.a2a_auth import caller, current_caller
    from resource_explorer.agents.stats_agent import StatsAgent
    from resource_explorer.concurrency import run_sync

    seen: dict = {}
    agent = StatsAgent()
    monkeypatch.setattr(agent, "_build_agent", lambda: _ReadsEgeriaAgent(seen))
    reset = _signed_in(PETER, PETER_TOKEN)
    try:
        _run_in_event_loop(lambda: agent._run_agent("q"))
    finally:
        current_caller.reset(reset)
    leftovers = {run_sync(lambda: caller()) for _ in range(16)}
    assert leftovers == {None}


# ── unchanged: a queued write carries the requester and drains on the service account ──────────────

@pytest.fixture
def reg(tmp_path):
    from resource_explorer.registry import ProjectRegistry, Project

    r = ProjectRegistry(db_path=str(tmp_path / "reads.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p"))
    return r


def test_a_queued_write_keeps_its_requester_and_drains_on_the_service_account(boundary, reg, monkeypatch):
    """Option 2's other half, untouched by this change: Peter's queued collection membership is applied by the
    background drain (no one signed in) as `Daemon(OUTBOX, requested_by=peter)`: the client is the daemon's,
    its token minted from the daemon's credential, never Peter's; the row still names Peter."""
    from tests.zone_fakes import open_access

    open_access(monkeypatch, caller_if_none=PETER)
    from resource_explorer import egeria_clients, egeria_outbox

    acting: list = []

    def add(mock):
        def record(*a, **k):
            acting.append(egeria_clients._acting.get())
        mock.add_to_collection.side_effect = record

    boundary.configure["CollectionManager"] = add
    boundary.configure["AutomatedCuration"] = lambda m: setattr(
        m.get_guid_for_name, "return_value", "No elements found")
    rid = reg.enqueue_outbox_element("repo", "p", "collection_membership", "CollectionMembership::c::m",
                                     {"collection_guid": "c", "member_guid": "m", "requested_by": PETER})
    from resource_explorer.a2a_auth import caller

    assert caller() is None, "the background drain has no signed-in person"
    summary = egeria_outbox.drain_outbox(reg, identity=egeria_clients.Daemon(egeria_clients.DaemonReason.OUTBOX))
    assert summary["done"] == 1, summary

    assert len(acting) == 1
    who = acting[0]
    assert who.kind == "daemon" and who.reason == "outbox_drain"
    assert who.requested_by == PETER and who.client_user == DAEMON_USER
    managers = boundary.of("CollectionManager")
    assert managers and {m["user"] for m in managers} == {DAEMON_USER}
    for m in boundary.built:
        tokens = {c.args[0] for c in m["mock"].set_bearer_token.call_args_list}
        assert PETER_TOKEN not in tokens
    assert any(m["mock"].create_egeria_bearer_token.called for m in boundary.built), "the daemon minted"
    row = reg.get_outbox_element(rid)
    assert row["status"] == "done"
    assert json.loads(row["payload_json"])["requested_by"] == PETER
