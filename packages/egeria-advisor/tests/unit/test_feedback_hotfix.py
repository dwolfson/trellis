"""Phase 0 S4: the feedback hotfix (POST /api/feedback).

The live bug (2026-11-10): the route was `async def` and called the synchronous collector, whose
MLflow call retried a refused port for ~4 minutes and blocked EA's whole event loop; the route
answered {"status": "ok"} whatever happened; the intent label went into user_comment; votes had no
user id; the Postgres query_metrics update matched on query text only.

No MLflow, no Postgres, no Egeria: MLflow is a fake that hangs or refuses, Postgres a recording fake,
and the data root a temp directory.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time

import pytest

from advisor import feedback_collector as fcmod

_REAL_SUBMIT = fcmod.submit_mlflow_feedback      # captured before the autouse fixture stubs it

BODY = {"query": "what is a glossary?", "query_type": "explanation", "vote": 1,
        "perspective": "Data Steward", "routing_agent": "doc_agent",
        "response_text": "A glossary is ...", "intent_override": "explain"}


class FakeDB:
    def __init__(self, affected=1, fail=None):
        self.calls = []
        self.affected = affected
        self.fail = fail

    def execute_update(self, sql, params):
        self.calls.append((" ".join(sql.split()), params))
        if self.fail:
            raise self.fail
        return self.affected


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("ADVISOR_DATA_PATH", str(tmp_path))
    monkeypatch.setattr(fcmod, "_feedback_collector", None)
    monkeypatch.setattr(fcmod, "_mlflow_failure_logged", False)
    monkeypatch.setattr(fcmod, "_mlflow_disabled_logged", False)
    db = FakeDB()
    monkeypatch.setattr("advisor.db_consolidated.get_db_manager", lambda: db)
    # By default MLflow is a no-op here; tests that care replace it.
    monkeypatch.setattr(fcmod, "submit_mlflow_feedback", lambda *a, **k: None)
    yield db


def _records(tmp_path, name="user_feedback.jsonl"):
    path = tmp_path / "feedback" / name
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def http(monkeypatch):
    from fastapi.testclient import TestClient
    from advisor import auth
    from advisor.web.app import app
    monkeypatch.setattr(auth, "_auth_enabled", lambda: True)
    client = TestClient(app, raise_server_exceptions=False)

    def as_user(user):
        return {"Authorization": f"Bearer {auth.create_access_token(user_id=user, egeria_token='tok-' + user)}"}
    return client, as_user


# ── fields: user id recorded, intent not in user_comment ───────────────────────

def test_vote_records_user_id_and_keeps_intent_out_of_comment(http, tmp_path, _isolated):
    client, as_user = http
    r = client.post("/api/feedback", json=BODY, headers=as_user("erinoverview"))
    assert r.status_code == 200, r.text
    assert r.json() == {"status": "ok", "secondary": {"extended": "ok", "query_metrics": "ok"}}

    (primary,) = _records(tmp_path)
    assert primary["user_id"] == "erinoverview"
    assert primary["intent_override"] == "explain"
    assert primary["user_comment"] is None and primary["feedback_text"] is None
    assert "sentiment" not in primary                      # nothing the user wrote, nothing analysed
    (extended,) = _records(tmp_path, "feedback_extended.jsonl")
    assert extended["user_id"] == "erinoverview" and extended["intent_override"] == "explain"


# ── query_metrics: by user AND query, skipped without a user ───────────────────

def test_query_metrics_update_matches_user_and_query(_isolated):
    fc = fcmod.get_feedback_collector()
    out = fc.record_vote(query="q1", query_type="t", collections_searched=[], response_length=0,
                         rating="negative", user_id="peterprofile", intent_override="act")
    assert out == {"query_metrics": "ok"}
    sql, params = _isolated.calls[0]
    assert "WHERE user_id = %s AND query_text = %s" in sql
    assert params[-2:] == ("peterprofile", "q1")
    assert params[0] is False and params[1] == "negative"
    assert params[4] is None                               # feedback_text: never the intent label


def test_query_metrics_skipped_without_a_user(_isolated):
    fc = fcmod.get_feedback_collector()
    out = fc.record_vote(query="q1", query_type="t", collections_searched=[], response_length=0,
                         rating="positive", user_id=None)
    assert out == {"query_metrics": "skipped"}
    assert _isolated.calls == []                           # never a text-only guess


def test_query_metrics_no_match_and_error_are_reported(_isolated):
    fc = fcmod.get_feedback_collector()
    _isolated.affected = 0
    assert fc.record_vote(query="q", query_type="t", collections_searched=[], response_length=0,
                          rating="positive", user_id="u")["query_metrics"] == "no_match"
    _isolated.fail = RuntimeError("pg down")
    assert fc.record_vote(query="q", query_type="t", collections_searched=[], response_length=0,
                          rating="positive", user_id="u")["query_metrics"] == "error"


# ── honest status ──────────────────────────────────────────────────────────────

def test_primary_write_failure_is_500_with_the_reason(http, tmp_path, monkeypatch):
    client, as_user = http
    fc = fcmod.get_feedback_collector()
    fc.feedback_file = tmp_path / "no-such-dir" / "user_feedback.jsonl"   # the open() fails
    r = client.post("/api/feedback", json=BODY, headers=as_user("erinoverview"))
    assert r.status_code == 500
    assert r.json()["detail"].startswith("could not record your feedback: FileNotFoundError")


def test_extended_write_failure_is_reported_not_hidden(http, tmp_path, monkeypatch):
    client, as_user = http
    monkeypatch.setattr("advisor.web.feedback._extended_feedback_path",
                        lambda: tmp_path / "feedback" / "missing-dir" / "x.jsonl")
    monkeypatch.setattr("advisor.config.ensure_writable_dir", lambda *a, **k: None)
    r = client.post("/api/feedback", json=BODY, headers=as_user("erinoverview"))
    assert r.status_code == 200
    assert r.json()["secondary"]["extended"] == "error"
    assert len(_records(tmp_path)) == 1                    # the vote itself was kept


def test_cli_wrapper_still_returns_a_bool(tmp_path):
    fc = fcmod.get_feedback_collector()
    assert fc.record_feedback(query="q", query_type="t", collections_searched=[], response_length=0,
                              rating="positive") is True
    fc.feedback_file = tmp_path / "nope" / "f.jsonl"
    assert fc.record_feedback(query="q", query_type="t", collections_searched=[], response_length=0,
                              rating="positive") is False


# ── MLflow: never on the request path ──────────────────────────────────────────

def test_hanging_mlflow_does_not_delay_the_response(http, monkeypatch):
    """The real background submit, with an MLflow log that hangs for 3 s: the response is quick."""
    client, as_user = http
    monkeypatch.setattr(fcmod, "submit_mlflow_feedback", _REAL_SUBMIT)
    release = threading.Event()

    class Tracker:
        enabled = True
    monkeypatch.setattr("advisor.mlflow_tracking.get_mlflow_tracker", lambda: Tracker())

    def hang(self, entry, sentiment_result=None, raise_errors=False):
        release.wait(3)
    monkeypatch.setattr(fcmod.FeedbackCollector, "log_feedback_to_mlflow", hang)
    try:
        t0 = time.monotonic()
        r = client.post("/api/feedback", json=BODY, headers=as_user("erinoverview"))
        first = time.monotonic() - t0
        t0 = time.monotonic()
        r2 = client.post("/api/feedback", json={**BODY, "vote": -1}, headers=as_user("erinoverview"))
        second = time.monotonic() - t0
    finally:
        release.set()
    assert r.status_code == 200 and r2.status_code == 200
    assert first < 1.0 and second < 1.0, (first, second)


def test_refused_mlflow_is_logged_once_and_never_raises(monkeypatch):
    """MLflow that refuses: the job swallows it, logs one warning, and applies the fail-fast env."""
    class Tracker:
        enabled = True
    monkeypatch.setattr("advisor.mlflow_tracking.get_mlflow_tracker", lambda: Tracker())
    monkeypatch.delenv("MLFLOW_HTTP_REQUEST_MAX_RETRIES", raising=False)
    monkeypatch.delenv("MLFLOW_HTTP_REQUEST_TIMEOUT", raising=False)
    calls = []

    def refuse(self, entry, sentiment_result=None, raise_errors=False):
        calls.append(raise_errors)
        raise ConnectionRefusedError("[Errno 61] Connection refused: localhost:5000")
    monkeypatch.setattr(fcmod.FeedbackCollector, "log_feedback_to_mlflow", refuse)
    warnings = []
    monkeypatch.setattr(fcmod.logger, "warning", lambda msg, *a, **k: warnings.append(msg))
    fc = fcmod.get_feedback_collector()
    entry = fcmod.FeedbackEntry(timestamp="t", query="q", query_type="t", collections_searched=[],
                                response_length=0, rating="positive")
    for _ in range(3):
        _REAL_SUBMIT(fc, entry).result(5)
    assert calls == [True, True, True]
    assert len([w for w in warnings if "MLflow" in w]) == 1
    import os
    assert os.environ["MLFLOW_HTTP_REQUEST_MAX_RETRIES"] == "0"
    assert int(os.environ["MLFLOW_HTTP_REQUEST_TIMEOUT"]) <= 2


def test_mlflow_skipped_when_the_probe_disabled_tracking(monkeypatch):
    class Tracker:
        enabled = False
    monkeypatch.setattr("advisor.mlflow_tracking.get_mlflow_tracker", lambda: Tracker())
    called = []
    monkeypatch.setattr(fcmod.FeedbackCollector, "log_feedback_to_mlflow",
                        lambda *a, **k: called.append(1))
    fc = fcmod.get_feedback_collector()
    entry = fcmod.FeedbackEntry(timestamp="t", query="q", query_type="t", collections_searched=[],
                                response_length=0, rating="positive")
    _REAL_SUBMIT(fc, entry).result(5)
    assert called == []


# ── the event loop stays free while a vote is being written ────────────────────

def test_event_loop_serves_other_requests_while_a_vote_is_written(monkeypatch):
    """A slow primary write (1 s) runs in a worker thread: a second request on the same loop
    completes before the vote does. Under the old async route it would have waited behind it."""
    import httpx
    from advisor import auth
    from advisor.web.app import app
    monkeypatch.setattr(auth, "_auth_enabled", lambda: True)
    headers = {"Authorization": f"Bearer {auth.create_access_token(user_id='erinoverview', egeria_token='tok')}"}

    real_vote = fcmod.FeedbackCollector.record_vote

    def slow_vote(self, **kw):
        time.sleep(1.0)
        return real_vote(self, **kw)
    monkeypatch.setattr(fcmod.FeedbackCollector, "record_vote", slow_vote)

    async def go():
        done = []
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://ea") as client:
            async def vote():
                r = await client.post("/api/feedback", json=BODY, headers=headers)
                done.append("vote")
                return r

            async def other():
                # Any cheap route a signed-in non-admin may call: the probe is "does the loop answer",
                # not this route. (Not /api/feedback/extended: S1 made that admin-only.)
                await asyncio.sleep(0.1)
                r = await client.get("/api/auth/me", headers=headers)
                done.append("other")
                return r
            rv, ro = await asyncio.gather(vote(), other())
        return done, rv, ro

    done, rv, ro = asyncio.run(go())
    assert rv.status_code == 200 and ro.status_code == 200, (rv.text, ro.text)
    assert done == ["other", "vote"]



def test_anonymous_vote_records_no_user_and_skips_query_metrics(_isolated, tmp_path):
    """No signed-in user (e.g. anonymous mode): user_id None, and the query_metrics update is
    skipped rather than matched on text alone."""
    from advisor.web.feedback import _record_vote
    from advisor.web.shared import FeedbackRequest
    out = _record_vote(FeedbackRequest(**BODY), None)
    assert out["secondary"]["query_metrics"] == "skipped" and _isolated.calls == []
    assert _records(tmp_path)[0]["user_id"] is None
