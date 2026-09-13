"""POST /api/query/ must not block the event loop.

2026-09-13 :8810 incident: `ask` called ConversationAgent.handle() (a
synchronous, potentially slow call — LLM + tool calls, one of which is a
Postgres vector_search) directly on the coroutine, which runs on the one
uvicorn event-loop thread. A single stuck tool call froze every request
being served, not just the one that triggered it. The fix moves that call
off the loop with asyncio.to_thread; this test proves the property with a
concurrent, trivial request that must not wait behind a slow `ask`.
"""
from __future__ import annotations

import threading
import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.agents.conversation_agent import ConversationAgent


SLEEP_SECONDS = 2.0


def _slow_handle(self, query, resource_slug=None, **kwargs):
    time.sleep(SLEEP_SECONDS)
    return "slow answer"


@pytest.fixture
def client(monkeypatch):
    # Off, not the default: the embedded worker's own startup (leader
    # elections, cache warms) adds a few hundred ms of one-time lifespan
    # noise that has nothing to do with what this test checks and would
    # make the elapsed-time assertion flaky.
    monkeypatch.setenv("EXPLORER_EMBED_WORKER", "false")

    from resource_explorer.web.app import app

    # MUST be `with TestClient(app) as client`, not a bare TestClient(app):
    # starlette's TestClient only reuses one blocking portal (one event-loop
    # thread) across requests when entered as a context manager — otherwise
    # every .get()/.post() gets its own fresh portal/loop and two requests
    # could never observe one blocking the other, silently defeating this
    # whole test regardless of what web/routes/query.py does.
    with TestClient(app) as c:
        yield c


class TestAskDoesNotBlockTheLoop:
    def test_a_trivial_endpoint_answers_while_ask_is_still_running(self, client):
        with patch.object(ConversationAgent, "handle", _slow_handle), \
             patch("resource_explorer.web.routes.query._persist_turn"):
            results: dict[str, float] = {}

            def _do_ask() -> None:
                t0 = time.monotonic()
                resp = client.post(
                    "/api/query/",
                    json={"query": "slow one", "session_id": "loop-test-session"},
                )
                results["ask_status"] = resp.status_code
                results["ask_elapsed"] = time.monotonic() - t0

            asker = threading.Thread(target=_do_ask)
            asker.start()
            # Give `ask` time to actually start (and, before the fix, to
            # seize the loop thread) before firing the trivial request.
            time.sleep(SLEEP_SECONDS / 3)

            t0 = time.monotonic()
            health_resp = client.get("/health")  # pure liveness — touches nothing slow
            health_elapsed = time.monotonic() - t0

            asker.join(timeout=SLEEP_SECONDS * 3)

        assert health_resp.status_code == 200
        # The whole point: /health must not have waited behind the slow
        # `ask` call. Before the fix this reliably took >= SLEEP_SECONDS
        # because both requests shared one blocked event-loop thread.
        assert health_elapsed < SLEEP_SECONDS / 2, (
            f"/health took {health_elapsed:.2f}s while ask() was sleeping "
            f"{SLEEP_SECONDS}s — the event loop was blocked"
        )
        assert results["ask_status"] == 200
        assert results["ask_elapsed"] >= SLEEP_SECONDS
