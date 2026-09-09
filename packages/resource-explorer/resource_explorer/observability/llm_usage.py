"""Token accounting for LLM calls — the counter `docs/Backlog.md`'s funnel-cost
spec (§6) asked for, at the one chokepoint every backend shares.

**Why here and not in Phoenix.** Phoenix is running and does capture token
counts, but `BeeAIInstrumentor` instruments BeeAI and nothing else. Measured
2026-09-09, same process, same prompt, same model, Phoenix instrumented for
both: a `BeeAI OllamaChatModel.run()` produced one span carrying
`prompt=17 completion=2 total=19`; a `get_llm().complete()` produced **no span
at all**. `llm_client` is where the chat path (`rag_system.py`) and ten agent
call sites actually live, so tracing alone would have measured the minority of
RE's LLM work — and, because several of those `llm_client` calls are the
agents' `fallback_prompt` path, the minority biased toward runs that succeeded.

**Why a ContextVar.** Same reasoning as `a2a_auth.current_caller`, which this
deliberately mirrors: an asyncio task inherits the context it was created in and
`asyncio.to_thread` copies it, so both the async and sync-bridged call sites
accumulate into the scope their caller opened. A bare `threading.Thread` does
NOT inherit it — see the ContextVar-identity note in the Backlog — which is
exactly why `uncounted` exists below rather than the total silently reading low.

**The honesty requirement, which is the whole point of the design.** A zero here
must say which kind of zero it is. Three states, not two:

* no scope open        -- nobody asked for a measurement. Recording is a no-op.
* scope open, 0 calls  -- this run made no LLM calls. A real, reportable zero.
* scope open, N calls,
  `uncounted` > 0      -- calls happened whose usage we could not read. NOT a
                          zero; `total_tokens` is a floor, not a measurement.

Streaming is the live source of `uncounted`. `LLMBackend.stream()` is not
instrumented: Ollama reports the counts only on the final `done` chunk (which
the current loop yields as empty content and drops), OpenAI does not send usage
at all unless the request passes `stream_options={"include_usage": True}`, and
Anthropic delivers it through `message_start`/`message_delta` events. Three
different shapes, one of them needing a request change — deliberately a separate
piece of work. Until it lands, a streamed call increments `uncounted` so it
cannot be mistaken for a call that cost nothing.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class LlmUsage:
    """What one measurement scope accumulated."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    #: Calls that happened but reported no usage — streaming today, and any
    #: backend response that omits the fields. The reason `total_tokens` is a
    #: floor whenever this is non-zero.
    uncounted: int = 0
    #: Model ids seen, so a total spanning two models is visibly not one price.
    models: set[str] = field(default_factory=set)

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def complete(self) -> bool:
        """Is `total_tokens` the whole story for this scope?"""
        return self.uncounted == 0

    def as_dict(self) -> dict:
        """Flat form for an activity_log detail or an MLflow metric set.

        `counted_calls` rather than a bare `calls` so a reader cannot divide by
        the wrong denominator when some calls are uncounted.
        """
        return {
            "llm_calls": self.calls,
            "llm_counted_calls": self.calls - self.uncounted,
            "llm_uncounted_calls": self.uncounted,
            "llm_prompt_tokens": self.prompt_tokens,
            "llm_completion_tokens": self.completion_tokens,
            "llm_total_tokens": self.total_tokens,
            "llm_usage_complete": self.complete,
            "llm_models": sorted(self.models),
        }


#: None means "nobody is measuring" — recording is then a no-op, which is a
#: third state and not a zero. Never default this to a live accumulator: a
#: process-wide total nobody scoped is attributable to nothing.
_current: ContextVar[LlmUsage | None] = ContextVar("re_llm_usage", default=None)


def current() -> LlmUsage | None:
    """The scope in force, or None when nothing is being measured."""
    return _current.get()


@contextmanager
def usage_scope() -> Iterator[LlmUsage]:
    """Accumulate LLM usage for the duration of the block.

    Nests: an inner scope collects its own subtotal and, on exit, folds it into
    the enclosing one, so wrapping a sub-step never subtracts from the run that
    contains it.
    """
    outer = _current.get()
    scope = LlmUsage()
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
        if outer is not None:
            outer.calls += scope.calls
            outer.prompt_tokens += scope.prompt_tokens
            outer.completion_tokens += scope.completion_tokens
            outer.uncounted += scope.uncounted
            outer.models |= scope.models


def record(prompt_tokens: int | None, completion_tokens: int | None,
           model: str = "") -> None:
    """One LLM call whose usage was readable.

    A backend that returns None (or omits the field) for either half is recorded
    as UNCOUNTED, not as zero: "the response carried no usage" and "this call
    cost nothing" are different facts and only one of them is ever true.
    """
    scope = _current.get()
    if scope is None:
        return
    scope.calls += 1
    if model:
        scope.models.add(model)
    if prompt_tokens is None or completion_tokens is None:
        scope.uncounted += 1
        return
    scope.prompt_tokens += int(prompt_tokens)
    scope.completion_tokens += int(completion_tokens)


def record_uncounted(model: str = "") -> None:
    """One LLM call that happened and whose usage we could not read — today,
    every streamed call. Keeps it out of the token total and visible in the
    count, so the total reads as a floor rather than as the answer."""
    scope = _current.get()
    if scope is None:
        return
    scope.calls += 1
    scope.uncounted += 1
    if model:
        scope.models.add(model)
