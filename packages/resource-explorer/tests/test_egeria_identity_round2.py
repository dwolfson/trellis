"""Brief I round 2: caller runs are claimed only by the process holding the token, the token
map's lifecycle, the CLI refusal, daemon_entry's explicit marker, the popover record of a daemon
call inside a person's request, the stored-credential cache key, and the publisher's Ownership
stamp no longer swallowing a missing sign-in. Fake clients only; nothing reaches Egeria."""
from __future__ import annotations

import json
import os
import time

import pytest

from resource_explorer import egeria_clients as ec
from resource_explorer import run_queue as rq


@pytest.fixture
def reg(tmp_path, monkeypatch):
    from resource_explorer.registry import ProjectRegistry

    r = ProjectRegistry(db_path=str(tmp_path / "r2.db"))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", r.__dict__) or None)
    rq._caller_tokens.clear()
    yield r
    rq._caller_tokens.clear()


@pytest.fixture
def ran(monkeypatch):
    seen = []

    def handler(target, result_ref):
        seen.append(ec.current_principal())
        return rq.RunOutcome(state="succeeded")
    monkeypatch.setitem(rq.HANDLERS, "publish_architecture", handler)
    return seen


# ── item 2: only the owning process claims a caller run ─────────────────────

def test_a_publish_is_run_by_its_own_processs_executor_and_never_by_a_separate_worker(reg, ran, signed_in_caller, monkeypatch):
    run_id = rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    assert json.loads(reg.get_run(run_id)["runner"])["caller_runs_of"]["pid"] == os.getpid()
    # a separate worker (any ordinary claimer) never takes it
    assert rq.claim_and_execute_once(reg) is None
    assert rq.claim_and_execute_once(reg, kinds=["publish_architecture"]) is None
    # another web process's executor does not take it either
    with monkeypatch.context() as m:
        m.setattr(rq, "process_marker", lambda: '{"caller_runs_of": {"pid": 1}}')
        assert rq.CallerRunExecutor().run_once(reg) is None
    # this process's executor does, with the embedded worker off
    from resource_explorer.config import get_config

    monkeypatch.setattr(get_config().runtime, "embed_worker", False)
    assert rq.CallerRunExecutor().run_once(reg)["id"] == run_id
    assert reg.get_run(run_id)["state"] == "succeeded"
    assert ran[0].kind == "caller" and ran[0].user_id == "test-caller"


def test_every_web_process_starts_the_caller_run_executor_even_with_no_embedded_worker(monkeypatch):
    import asyncio

    from resource_explorer.web import app as web_app

    started = []
    monkeypatch.setattr(web_app, "_embed_worker_enabled", lambda: False)
    monkeypatch.setattr("resource_explorer.run_queue.start_caller_run_executor", lambda: started.append(1))
    monkeypatch.setattr("resource_explorer.run_queue.stop_caller_run_executor", lambda: None)

    from contextlib import asynccontextmanager

    async def go():
        async with asynccontextmanager(web_app._lifespan)(web_app.app):
            pass
    monkeypatch.setattr("resource_explorer.surveyors.prefect_adapter.alog_prefect_reachability_at_startup",
                        lambda: asyncio.sleep(0))
    asyncio.run(go())
    assert started == [1]


def test_ordinary_queued_work_is_still_claimed_by_any_worker(reg):
    reg.enqueue_run("analysis_run", {"slug": "p"}, requested_by="erin")
    seen = {}
    rq.HANDLERS["analysis_run"], old = (lambda t, r: seen.setdefault("ran", True) and rq.RunOutcome("succeeded")), \
        rq.HANDLERS["analysis_run"]
    try:
        assert rq.claim_and_execute_once(reg) is not None
    finally:
        rq.HANDLERS["analysis_run"] = old
    assert seen == {"ran": True}


# ── item 7: the token map's lifecycle ───────────────────────────────────────

def test_the_token_is_in_the_map_before_the_row_is_committed(reg, signed_in_caller, monkeypatch):
    seen = {}
    real = reg.enqueue_run

    def spy(kind, target=None, **kw):
        seen["in_map_at_insert"] = rq._caller_tokens.has(kw["run_id"])
        return real(kind, target, **kw)
    monkeypatch.setattr(reg, "enqueue_run", spy)
    rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    assert seen == {"in_map_at_insert": True}


def test_a_failed_enqueue_leaves_no_token_behind(reg, signed_in_caller, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("registry gone")
    monkeypatch.setattr(reg, "enqueue_run", boom)
    with pytest.raises(RuntimeError):
        rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    assert rq._caller_tokens.ids() == []


def test_cancelling_a_queued_caller_run_drops_its_token(reg, signed_in_caller):
    from fastapi.testclient import TestClient

    from resource_explorer.auth import create_access_token
    from resource_explorer.web.app import app

    run_id = rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    hdr = {"Authorization": "Bearer " + create_access_token(user_id="test-caller", egeria_token="t")}
    assert TestClient(app).post(f"/api/runs/{run_id}/cancel", headers=hdr).status_code == 200
    assert not rq._caller_tokens.has(run_id)


def test_the_sweep_drops_a_token_whose_run_was_cancelled_elsewhere(reg, signed_in_caller):
    run_id = rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    assert reg.cancel_queued_run(run_id)                    # e.g. from the CLI, another process
    rq.sweep_caller_runs(reg)
    assert not rq._caller_tokens.has(run_id)


def test_the_ttl_sweep_fails_a_run_whose_token_waited_too_long(reg, signed_in_caller, monkeypatch):
    run_id = rq.enqueue_as_caller(reg, "publish_architecture", {"slug": "p"})
    real_time = time.time
    with monkeypatch.context() as m:
        m.setattr(time, "time", lambda: real_time() + rq.CALLER_TOKEN_TTL_SECONDS + 5)
        assert rq.sweep_caller_runs(reg) == [run_id]
    row = reg.get_run(run_id)
    assert row["state"] == "failed" and row["error"] == ec.EXPIRED_SENTENCE
    assert not rq._caller_tokens.has(run_id)


def test_a_run_owned_by_a_dead_process_on_this_host_is_failed_by_the_sweep(reg, signed_in_caller):
    import socket

    dead = json.dumps({"caller_runs_of": {"host": socket.gethostname(), "pid": 2 ** 22 + 12345,
                                          "started_at": "x"}}, sort_keys=True)
    run_id = reg.enqueue_run("publish_architecture", {"slug": "p"}, requested_by="x", owner=dead)
    assert rq.sweep_caller_runs(reg) == [run_id]
    assert reg.get_run(run_id)["error"] == ec.EXPIRED_SENTENCE


def test_the_cli_refuses_to_queue_a_persons_own_action():
    from typer.testing import CliRunner

    from resource_explorer.cli.runs_commands import runs_app

    out = CliRunner().invoke(runs_app, ["enqueue", "publish_architecture", '{"slug": "p"}',
                                        "--requested-by", "dan"])
    assert out.exit_code == 1
    assert rq.CLI_NO_SIGN_IN in out.output


# ── item 5: daemon_entry only in a Prefect worker process ───────────────────

def test_daemon_entry_needs_the_prefect_worker_marker(monkeypatch):
    @ec.daemon_entry(ec.DaemonReason.PREFECT_FLOW)
    def flow():
        return ec.current_principal()

    monkeypatch.delenv(ec.PREFECT_WORKER_MARKER, raising=False)
    with pytest.raises(ec.NoCallerIdentity):               # a missing caller elsewhere raises
        flow()
    monkeypatch.setenv(ec.PREFECT_WORKER_MARKER, "flow-run-1")
    assert flow().reason == "prefect_flow"


# ── item 7: popover, stored key, publisher ──────────────────────────────────

class _Fake:
    def __init__(self, *a):
        self.token = None

    def set_bearer_token(self, t):
        self.token = t

    def create_egeria_bearer_token(self, *a):
        self.token = "minted"
        return "minted"


def test_a_daemon_call_inside_a_persons_request_is_recorded_under_that_person(monkeypatch, signed_in_caller):
    monkeypatch.setattr(ec, "_last_by_user", {})
    ec.egeria_client(ec.Daemon(ec.DaemonReason.REACHABILITY), purpose="reachability").of(_Fake)
    rec = ec.last_egeria_identity("test-caller")
    assert rec["as"] == "service account (background)" and rec["purpose"] == "reachability"


def test_an_edited_stored_password_is_a_new_client(monkeypatch):
    def entity(pw):
        return type("E", (), {"egeria_user": "s", "egeria_password": pw, "egeria_url": ""})()

    with ec.client_scope():
        a = ec.egeria_client(ec.StoredOrDaemon(entity("one"), ec.DaemonReason.OUTBOX), purpose="t")
        b = ec.egeria_client(ec.StoredOrDaemon(entity("two"), ec.DaemonReason.OUTBOX), purpose="t")
        c = ec.egeria_client(ec.StoredOrDaemon(entity("one"), ec.DaemonReason.OUTBOX), purpose="t")
    assert a is not b and a is c


def test_the_publishers_ownership_stamp_lets_a_missing_sign_in_through(monkeypatch):
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    def no_one(*a, **k):
        raise ec.NoCallerIdentity()
    monkeypatch.setattr("resource_explorer.egeria_identity.classification_client", no_one)
    pub = EgeriaPublisher(platform_url="https://x")
    pub._identity = ec.Daemon(ec.DaemonReason.SCHEDULER)
    with pytest.raises(ec.NoCallerIdentity):
        pub._stamp_governance("g1")
