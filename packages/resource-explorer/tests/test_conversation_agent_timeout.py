"""ConversationAgent._run_persistent must not wait forever on a stuck tool.

2026-09-13 :8810 incident: `run_sync(lambda: asyncio.run(_inner()))` had no
timeout at all, so a tool call that hung (vector_search's Postgres connect)
blocked the calling thread — the event-loop thread, before the `ask` fix in
web/routes/query.py — indefinitely. `_run_persistent` now bounds the wait
with `config.agents.chat_timeout_seconds` and raises a clear `TimeoutError`
instead. Both branches (`asyncio.get_running_loop()` succeeds vs. raises
RuntimeError) must honor the same bound.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from resource_explorer.agents.conversation_agent import ConversationAgent
from resource_explorer.config import get_config


TIMEOUT = 0.2


@pytest.fixture
def tiny_timeout(monkeypatch):
    monkeypatch.setattr(get_config().agents, "chat_timeout_seconds", TIMEOUT)
    yield TIMEOUT


class _StuckAgent:
    """Stand-in for BeeAI's RequirementAgent: run() never returns."""

    async def run(self, prompt: str):
        await asyncio.sleep(100)  # far past TIMEOUT
        return "unreachable"


class TestRunPersistentTimesOutOffTheLoop:
    """No event loop already running on this thread — the branch every
    to_thread-run chat call (post-fix `ask`) actually takes."""

    def test_a_stuck_tool_ends_with_a_clear_timeout_within_the_bound(self, tiny_timeout):
        agent = ConversationAgent()
        agent._agent = _StuckAgent()

        t0 = time.monotonic()
        with pytest.raises(TimeoutError, match=str(tiny_timeout)):
            agent._run_persistent("question")
        elapsed = time.monotonic() - t0

        # Bounded by the configured timeout, with slack for the run_sync
        # defense-in-depth margin (+5s) — never anywhere near the 100s sleep.
        assert elapsed < tiny_timeout + 5


class TestRunPersistentTimesOutOnTheLoop:
    """A loop IS already running on this thread (asyncio.get_running_loop()
    succeeds) — the branch _run_persistent takes when called from inside an
    already-async context, bridged via concurrency.run_sync."""

    def test_a_stuck_tool_ends_with_a_clear_timeout_within_the_bound(self, tiny_timeout):
        agent = ConversationAgent()
        agent._agent = _StuckAgent()

        async def _inner():
            asyncio.get_running_loop()  # sanity: a loop is running here
            return agent._run_persistent("question")

        t0 = time.monotonic()
        with pytest.raises(TimeoutError, match=str(tiny_timeout)):
            asyncio.run(_inner())
        elapsed = time.monotonic() - t0

        assert elapsed < tiny_timeout + 5
