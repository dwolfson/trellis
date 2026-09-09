"""Token accounting at the `llm_client` chokepoint.

Phoenix captures token counts for BeeAI and nothing else — measured 2026-09-09,
same process and prompt: a BeeAI `OllamaChatModel.run()` produced a span with
`prompt=17 completion=2 total=19`, a `get_llm().complete()` produced no span at
all. These tests pin the counter that covers the ten `llm_client` call sites
tracing cannot see.

The recurring assertion is the three-state one: a zero must say which kind of
zero it is. `no scope` / `zero calls` / `calls we could not count` are different
facts, and only the middle one is a measurement.
"""
from __future__ import annotations

import pytest

from resource_explorer.observability import llm_usage


class TestScoping:
    def test_recording_outside_a_scope_is_a_no_op(self):
        """No scope means nobody asked for a measurement. Recording into a
        process-wide default would produce a total attributable to nothing."""
        assert llm_usage.current() is None
        llm_usage.record(10, 5, "m")          # must not raise
        llm_usage.record_uncounted("m")
        assert llm_usage.current() is None

    def test_a_scope_with_no_calls_is_a_real_zero(self):
        with llm_usage.usage_scope() as u:
            pass
        assert u.calls == 0 and u.total_tokens == 0
        assert u.complete, "a run that made no LLM calls is a complete answer, not a partial one"

    def test_the_scope_is_removed_on_exit(self):
        with llm_usage.usage_scope():
            assert llm_usage.current() is not None
        assert llm_usage.current() is None

    def test_the_scope_is_removed_even_when_the_body_raises(self):
        with pytest.raises(RuntimeError):
            with llm_usage.usage_scope():
                raise RuntimeError("boom")
        assert llm_usage.current() is None, (
            "a failed run leaves its scope in force, so the next run's tokens "
            "accumulate into it"
        )

    def test_nested_scopes_fold_into_the_enclosing_one(self):
        """Wrapping a sub-step must not subtract from the run containing it."""
        with llm_usage.usage_scope() as outer:
            llm_usage.record(10, 5, "a")
            with llm_usage.usage_scope() as inner:
                llm_usage.record(100, 50, "b")
                llm_usage.record_uncounted("b")
            assert inner.total_tokens == 150
        assert outer.prompt_tokens == 110
        assert outer.completion_tokens == 55
        assert outer.calls == 3
        assert outer.uncounted == 1
        assert outer.models == {"a", "b"}


class TestAZeroSaysWhichZeroItIs:
    def test_a_counted_call_is_complete(self):
        with llm_usage.usage_scope() as u:
            llm_usage.record(12, 2, "llama3.1:8b")
        assert (u.prompt_tokens, u.completion_tokens, u.total_tokens) == (12, 2, 14)
        assert u.complete and u.uncounted == 0

    def test_an_uncounted_call_is_not_a_zero(self):
        """The failure this exists to prevent: a streamed call reported as
        having cost nothing, indistinguishable from no call at all."""
        with llm_usage.usage_scope() as u:
            llm_usage.record_uncounted("llama3.1:8b")
        assert u.calls == 1
        assert u.total_tokens == 0
        assert not u.complete, (
            "a call whose usage could not be read is reporting as a complete "
            "measurement of zero tokens"
        )

    @pytest.mark.parametrize("prompt,completion", [(None, 5), (10, None), (None, None)])
    def test_a_half_missing_usage_is_uncounted_not_zero(self, prompt, completion):
        """A backend that omits either half has not told us the cost. Adding
        the half we got would produce a number that looks like a measurement."""
        with llm_usage.usage_scope() as u:
            llm_usage.record(prompt, completion, "m")
        assert u.calls == 1 and u.uncounted == 1
        assert u.total_tokens == 0
        assert not u.complete

    def test_the_flat_form_never_offers_a_misleading_denominator(self):
        with llm_usage.usage_scope() as u:
            llm_usage.record(10, 5, "m")
            llm_usage.record_uncounted("m")
        d = u.as_dict()
        assert d["llm_calls"] == 2
        assert d["llm_counted_calls"] == 1
        assert d["llm_uncounted_calls"] == 1
        assert d["llm_usage_complete"] is False
        assert d["llm_total_tokens"] == 15, "the total is a floor over the counted calls"


class TestEveryBackendIsWired:
    """Derived over the backends rather than naming them, so a fourth backend
    added without accounting fails on arrival instead of reporting zero."""

    def _backends(self):
        import inspect
        from resource_explorer import llm_client
        return [
            obj for _n, obj in inspect.getmembers(llm_client, inspect.isclass)
            if hasattr(obj, "complete") and hasattr(obj, "stream")
            and obj.__module__ == llm_client.__name__
            and not getattr(obj, "_is_protocol", False)
        ]

    def test_there_are_backends_to_check(self):
        assert self._backends(), "found no LLM backends — the derivation broke, not the code"

    @pytest.mark.parametrize("method", ["complete", "stream"])
    def test_every_backend_accounts_for_every_call(self, method):
        import inspect
        missing = []
        for backend in self._backends():
            src = inspect.getsource(getattr(backend, method))
            if "llm_usage.record" not in src:
                missing.append(f"{backend.__name__}.{method}")
        assert not missing, (
            f"these LLM entry points make a call and record nothing, so their "
            f"tokens vanish and the scope's total silently under-reports: "
            f"{missing}"
        )

    def test_streaming_is_declared_uncounted_rather_than_forgotten(self):
        """Streaming genuinely is not instrumented yet (three backend-specific
        shapes, one needing a request change). The requirement is that it says
        so — `record_uncounted`, not silence."""
        import inspect
        wrong = []
        for backend in self._backends():
            src = inspect.getsource(getattr(backend, "stream"))
            if "record_uncounted" not in src:
                wrong.append(backend.__name__)
        assert not wrong, (
            f"{wrong} stream without recording an uncounted call, so a streamed "
            f"run reports zero tokens as though it were a measurement"
        )


class TestAgainstTheRealOllamaResponseShape:
    def test_the_field_names_match_what_ollama_returns(self):
        """Guards the names, which are Ollama's and not the OpenAI ones.
        Measured live 2026-09-09: prompt_eval_count=12, eval_count=2."""
        import inspect
        from resource_explorer import llm_client
        src = inspect.getsource(llm_client.OllamaBackend.complete)
        assert "prompt_eval_count" in src and "eval_count" in src, (
            "OllamaBackend is reading OpenAI's field names; Ollama reports "
            "prompt_eval_count / eval_count and the counts will always be None"
        )

    def test_a_response_without_counts_records_uncounted(self):
        """An older Ollama, or a response that omits the fields, must not read
        as a free call."""
        from resource_explorer import llm_client

        class _Client:
            def chat(self, **_kw):
                return {"message": {"content": "hi"}}   # no *_count keys

        b = object.__new__(llm_client.OllamaBackend)
        b._client, b._model, b._temperature, b._num_ctx = _Client(), "m", 0.0, 8192
        with llm_usage.usage_scope() as u:
            assert b.complete("x") == "hi"
        assert u.calls == 1 and u.uncounted == 1 and not u.complete

    def test_a_response_with_counts_is_recorded(self):
        from resource_explorer import llm_client

        class _Client:
            def chat(self, **_kw):
                return {"message": {"content": "ping"},
                        "prompt_eval_count": 12, "eval_count": 2}

        b = object.__new__(llm_client.OllamaBackend)
        b._client, b._model, b._temperature, b._num_ctx = _Client(), "llama3.1:8b", 0.0, 8192
        with llm_usage.usage_scope() as u:
            assert b.complete("x") == "ping"
        assert (u.prompt_tokens, u.completion_tokens) == (12, 2)
        assert u.complete and u.models == {"llama3.1:8b"}


class TestTheScopesAreActuallyOpened:
    """A counter nobody scopes records nothing — the 'configured but never
    read' failure this codebase has hit repeatedly. These pin the two openers
    so the accounting cannot go inert without a test saying so."""

    def test_the_run_queue_scopes_the_handler(self):
        import inspect
        from resource_explorer import run_queue
        src = inspect.getsource(run_queue)
        assert "llm_usage.usage_scope()" in src, (
            "run_queue executes handlers without opening a usage scope, so an "
            "analysis run's tokens are recorded against nothing"
        )

    def test_the_rag_path_scopes_its_route(self):
        import inspect
        from resource_explorer import rag_system
        src = inspect.getsource(rag_system.RAGSystem.query)
        assert "usage_scope()" in src, (
            "RAGSystem.query does not scope its LLM calls — the chat path is "
            "where most of RE's LLM work happens and it would count zero"
        )

    def test_the_rag_path_reads_usage_before_spawning_its_tracking_thread(self):
        """`_track` runs on a bare threading.Thread, which does NOT inherit
        ContextVars. Reading the scope from inside it finds nothing and reports
        every query as free. The read must happen in `query` itself."""
        import inspect
        from resource_explorer import rag_system
        import re
        src = inspect.getsource(rag_system.RAGSystem.query)
        # Comments stripped FIRST. The method explains this very hazard in a
        # comment containing the words "a bare threading.Thread", and the first
        # version of this test matched that prose instead of the call — the same
        # read-prose-as-code trap `_top_level_functions` in
        # test_frontend_render_modes.py already strips for.
        src = re.sub(r"#.*$", "", src, flags=re.M)
        # `usage.as_dict`, not `usage.` — the latter also matches inside
        # `llm_usage.usage_scope()`, so the check passed with the read moved
        # after the thread. Both faults found by sabotage, not by reading.
        assert "usage.as_dict()" in src, (
            "RAGSystem.query no longer reads the accumulated usage at all")
        read = src.index("usage.as_dict()")
        thread = src.index("threading.Thread", src.index("usage_scope()"))
        assert read < thread, (
            "RAGSystem.query reads the usage scope after handing off to a bare "
            "threading.Thread; a plain Thread does not inherit ContextVars, so "
            "the totals would be lost"
        )

    def test_track_does_not_read_the_scope_itself(self):
        import inspect
        from resource_explorer import rag_system
        src = inspect.getsource(rag_system.RAGSystem._track)
        assert "llm_usage.current()" not in src and "usage_scope" not in src, (
            "_track runs on a bare thread and must not read the usage "
            "ContextVar — it will always be None there"
        )


class TestScopeSurvivesTheWaysWorkIsDispatched:
    def test_asyncio_to_thread_inherits_the_scope(self):
        """The dispatch RE actually uses for sync-bridged work — contrast with
        the bare Thread above."""
        import asyncio

        async def go():
            with llm_usage.usage_scope() as u:
                await asyncio.to_thread(llm_usage.record, 7, 3, "m")
            return u

        u = asyncio.run(go())
        assert u.total_tokens == 10, (
            "asyncio.to_thread lost the usage scope; it copies the context and "
            "should not have"
        )

    def test_a_bare_thread_does_not_and_that_is_why_the_read_is_synchronous(self):
        """Pins the trap itself, so the reasoning above stays checkable rather
        than being a comment someone later 'simplifies' away."""
        import threading

        with llm_usage.usage_scope() as u:
            t = threading.Thread(target=llm_usage.record, args=(7, 3, "m"))
            t.start()
            t.join()
        assert u.calls == 0, (
            "a bare threading.Thread now inherits ContextVars — if this fails, "
            "the synchronous-read requirement in RAGSystem.query can be relaxed"
        )
