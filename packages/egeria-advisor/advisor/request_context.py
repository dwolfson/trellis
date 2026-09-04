"""
Request-scoped identity — closes the gap flagged in a4ef5ec's commit message:
the chat/elicitation-driven creation path (rag_system.py → plan_elicitor.py /
report_spec_elicitor.py → agents/governance_plan_agent.py /
agents/report_spec_agent.py) calls the no-args manager singletons
(`get_doc_manager()`, `get_draft_manager()`, `get_report_draft_manager()`,
`get_report_spec_doc_manager()`) several call-frames away from the FastAPI
`Request`, so threading `user_id` through every intervening function
signature would touch a large, unrelated call graph. A `contextvars.ContextVar`
carries the signed-in identity across that gap instead: `advisor.web.app`'s
`_user_context_middleware` sets it once per request from
`advisor.auth.get_current_user(request)`, and any code running under that
request — no matter how many plain-function calls deep — can read it back via
`current_user()`/`current_user_id()`.

Contract:
  * Anonymous requests (no/invalid token, or auth disabled) resolve to
    `current_user_id() is None` → callers fall back to the shared namespace,
    exactly as before this module existed.
  * An explicit `user_id` argument at a call site always wins — this module
    only supplies a *default* for the "no argument given" case, via the
    `UNSET` sentinel (plain `None` is a valid, meaningful explicit value:
    "anonymous, use the shared namespace" — see `resolve_user_id`'s
    docstring for why `None` can't double as "not given").
  * The ContextVar is reset after every request (even one that raises) so no
    identity leaks from one request into the next — asyncio.Task boundaries
    isolate concurrent requests from each other regardless, but the
    middleware still resets explicitly for clarity and for the CLI's
    synchronous `using_user()` context manager below, which runs in a single
    thread/task with no such isolation.
"""
from __future__ import annotations

import contextvars
from typing import Any, Dict, Optional


class _Unset:
    """Sentinel distinguishing "caller did not pass this argument" from
    "caller explicitly passed None" — plain `None` is itself a meaningful
    value here (anonymous → shared namespace), so it cannot double as the
    "not given" marker the way it usually would."""

    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return "UNSET"


#: Import this to spell a manager-factory / method default as "inherit from
#: the ambient request context", e.g. `def get_draft_manager(user_id=UNSET)`.
UNSET: Any = _Unset()

_current_user_var: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar(
    "advisor_current_user", default=None
)


def set_current_user(user_id: Optional[str], role: Optional[str] = None) -> contextvars.Token:
    """Set the ambient identity for the current context (request or CLI
    invocation). `user_id=None` records "anonymous" explicitly (still
    resolves to the shared namespace via `resolve_user_id`) rather than
    leaving the ContextVar at its own default, so `current_user()` can tell
    "a request ran, and it was anonymous" from "no request/middleware ran at
    all" if that distinction ever matters. Returns a Token for
    `reset_current_user()`."""
    return _current_user_var.set({"user_id": user_id, "role": role})


def reset_current_user(token: contextvars.Token) -> None:
    """Undo one `set_current_user()` call. Always call this in a `finally`
    block (see the middleware / `using_user()` below) so a request that
    raises can't leak its identity into whatever runs next on the same
    thread/task."""
    _current_user_var.reset(token)


def current_user() -> Optional[Dict[str, Any]]:
    """`{"user_id": ..., "role": ...}` for the request/CLI invocation
    currently in flight, or None if nothing has called `set_current_user()`
    in this context (e.g. a background job, or code running outside any
    request — not the same as an authenticated-but-anonymous request, which
    is `{"user_id": None, "role": None}`)."""
    return _current_user_var.get()


def current_user_id() -> Optional[str]:
    """Convenience accessor: the signed-in user_id, or None (anonymous, or
    no ambient context at all — both fall back to the shared namespace)."""
    user = _current_user_var.get()
    return user.get("user_id") if user else None


def current_role() -> Optional[str]:
    user = _current_user_var.get()
    return user.get("role") if user else None


def resolve_user_id(explicit: Any = UNSET) -> Optional[str]:
    """The value a manager factory / method should use for its `user_id`
    parameter: `explicit` when the caller passed one (including `None` —
    that's the caller *deliberately* choosing the shared namespace, e.g. an
    anonymous web request's already-computed `user_id = None`), otherwise
    whatever `current_user_id()` reports for the ambient request/CLI
    context (itself None when anonymous or when there is no ambient
    context — same net effect, shared namespace, just by a different
    route)."""
    if explicit is not UNSET:
        return explicit
    return current_user_id()


class using_user:
    """Context manager for non-request callers (the CLI) that want the same
    "ambient identity" mechanism without a FastAPI request: `with
    using_user(user_id):` sets the ContextVar for the duration of the
    `with` block and resets it afterwards (even on exception), so any
    manager factory called inside picks it up exactly like a web request
    would."""

    def __init__(self, user_id: Optional[str], role: Optional[str] = None) -> None:
        self._user_id = user_id
        self._role = role
        self._token: Optional[contextvars.Token] = None

    def __enter__(self) -> None:
        self._token = set_current_user(self._user_id, self._role)

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._token is not None:
            reset_current_user(self._token)
