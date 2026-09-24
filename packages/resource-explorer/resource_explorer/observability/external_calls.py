"""Per-run external-call accounting — requests, bytes, and who they went to.

Design §17.2's `bytes_fetched`, `api_calls` and `egeria_calls`. The same
ContextVar-scope shape as `acquisition` and `llm_usage` beside it, for the same
reason those give: a counter read off a shared client is a process-wide total
that races any concurrent run, while a scope attributes each call to the run
that made it. One pattern, now three users of it.

**Why `api_calls` is not the same as `wall_ms`.** For repositories the scarce
resource is the GitHub rate budget, not seconds — a step can be fast and still
be the reason the next twenty steps get 403s. Nothing has ever counted them.

**Why `egeria_calls` is separate from `api_calls`.** Load on the Egeria
platform is somebody else's cost, and §17.3's "native vs local" view exists to
compare a native survey's platform load against RE's — which needs the two
counted apart, not summed.

**Where the counting happens.** One wrapper on `requests.Session.send`,
installed on first use and never removed, exactly as `step_cost_observer`
already does for `socket.socket.connect`. That single seam covers every HTTP
client in this package: the GitHub client, OSV, the CII badge registry,
`SurveyDefinitionReader`, and pyegeria (which is `requests`-based). Host
classification is what separates them — an Egeria call is one whose host:port
matches the configured platform or view server.

**The same asymmetry `step_cost_observer` states about socket counting applies
here and is not hidden:** under concurrent surveys in one process a call can be
attributed to the wrong scope. ContextVars make that much rarer than the module
global sockets use — a ContextVar is per-task/per-thread-of-execution, so a
concurrent survey in another thread has its own scope — but a background thread
spawned INSIDE a step does not inherit the scope (the ContextVar-identity note
in the Backlog), so its calls are not counted at all. An undercount, which is
the direction that fails safe for a "this step is expensive" alarm and the
wrong one for a "this step is free" claim. `complete` says which.

**Bytes are what arrived, not what was paid for.** `Content-Length` when the
response carries one, else the decoded body's length, else nothing — a
streamed response consumed after `send` returns is invisible here. Git's own
transfer is recorded separately, at `SourceCache.put`, from the size of what
landed on disk: a treeless clone's on-disk size is not its wire size, and
`kinds_fetched` on the acquisition scope already says which artifacts were
really fetched.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ExternalCalls:
    """What one measurement scope saw leave the process."""

    #: External HTTP requests that were NOT to the Egeria platform.
    api_calls: int = 0
    #: Requests to the configured Egeria platform / view server.
    egeria_calls: int = 0
    #: Bytes that arrived over the network into RE, HTTP and git together.
    bytes_fetched: int = 0
    #: api_calls broken down by host — §17.2 asks for "external API requests
    #: **by host**", because one host's rate budget is not another's.
    by_host: dict[str, int] = field(default_factory=dict)
    #: False when at least one call could not be sized (no Content-Length and
    #: a body this hook could not read). `bytes_fetched` is then a floor, and
    #: a reader must not treat it as a total.
    bytes_complete: bool = True

    def as_dict(self) -> dict:
        return {
            "api_calls": self.api_calls,
            "egeria_calls": self.egeria_calls,
            "bytes_fetched": self.bytes_fetched,
            "bytes_complete": self.bytes_complete,
            "api_calls_by_host": dict(sorted(self.by_host.items())),
        }


_current: ContextVar[ExternalCalls | None] = ContextVar("re_external_calls", default=None)
_patch_lock = threading.Lock()
_patched = False


def current() -> ExternalCalls | None:
    return _current.get()


@contextmanager
def call_scope() -> Iterator[ExternalCalls]:
    """Attribute external calls made in this block. Nests: an inner scope
    folds into the enclosing one on exit, so measuring a prerequisite step
    inside a survey never subtracts from the survey's own totals."""
    install()
    outer = _current.get()
    scope = ExternalCalls()
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
        if outer is not None:
            outer.api_calls += scope.api_calls
            outer.egeria_calls += scope.egeria_calls
            outer.bytes_fetched += scope.bytes_fetched
            outer.bytes_complete = outer.bytes_complete and scope.bytes_complete
            for host, n in scope.by_host.items():
                outer.by_host[host] = outer.by_host.get(host, 0) + n


def record_bytes(n: int) -> None:
    """Bytes that arrived by a route this module does not wrap — `git` via
    `SourceCache.put`, chiefly. A no-op with no scope open, like every other
    recorder here: nobody asked."""
    scope = _current.get()
    if scope is not None and n > 0:
        scope.bytes_fetched += int(n)


def record_call(host: str, *, egeria: bool = False, byte_count: int | None = None) -> None:
    scope = _current.get()
    if scope is None:
        return
    if egeria:
        scope.egeria_calls += 1
    else:
        scope.api_calls += 1
        scope.by_host[host] = scope.by_host.get(host, 0) + 1
    if byte_count is None:
        scope.bytes_complete = False
    else:
        scope.bytes_fetched += int(byte_count)


def _egeria_hosts() -> set[str]:
    """Hosts that count as the platform. Read from config at call time, and
    an empty set when config cannot be read — every call then lands in
    `api_calls`, which over-counts the API budget rather than silently
    crediting an Egeria round trip to nobody."""
    hosts: set[str] = set()
    try:
        from urllib.parse import urlparse

        from resource_explorer.config import get_config

        cfg = get_config()
        for attr in ("platform_url", "view_server_url", "url"):
            value = getattr(getattr(cfg, "egeria", None), attr, "")
            if value:
                parsed = urlparse(value)
                if parsed.netloc:
                    hosts.add(parsed.netloc)
    except (ImportError, AttributeError, ValueError, TypeError) as exc:
        # Narrow on purpose. An unreadable config means every call lands in
        # `api_calls`, which OVER-counts the API budget rather than crediting
        # an Egeria round trip to nobody — a safe direction. Anything wider
        # than these four would also swallow a real bug in the attribution
        # itself, which is not safe in any direction.
        log.debug("could not read Egeria hosts for call attribution: %s", exc)
    return hosts


def _response_bytes(response) -> int | None:
    length = (getattr(response, "headers", None) or {}).get("Content-Length")
    if length is not None:
        try:
            return int(length)
        except (TypeError, ValueError):
            pass
    # `_content is False` is requests' own "not read yet" sentinel — a
    # streamed response. Reading it here would consume the caller's stream,
    # so the honest answer is "unknown", not "zero".
    content = getattr(response, "_content", False)
    if isinstance(content, (bytes, bytearray)):
        return len(content)
    return None


def install() -> None:
    """Wrap `requests.Session.send` once, for the life of the process.

    Idempotent and never uninstalled, matching `step_cost_observer`'s socket
    patch: a wrapper removed while another thread is inside it is a far worse
    problem than one that stays. With no scope open the wrapper is two
    attribute reads and a call.
    """
    global _patched
    with _patch_lock:
        if _patched:
            return
        try:
            import requests
        except Exception as exc:  # pragma: no cover - requests is a hard dep
            log.debug("requests unavailable; external calls will not be counted: %s", exc)
            _patched = True
            return

        real_send = requests.Session.send

        def counting_send(self, request, **kwargs):  # noqa: ANN001
            response = real_send(self, request, **kwargs)
            if _current.get() is not None:
                try:
                    from urllib.parse import urlparse

                    host = urlparse(getattr(request, "url", "") or "").netloc
                    record_call(host, egeria=host in _egeria_hosts(),
                                byte_count=_response_bytes(response))
                except Exception as exc:  # pragma: no cover - never fail a request
                    # Broad, because an instrumentation bug must never break
                    # somebody's HTTP request — but NOT silent: the scope is
                    # marked incomplete, so `bytes_fetched` is read as a floor
                    # and the caller can tell an un-accounted call from a
                    # free one.
                    scope = _current.get()
                    if scope is not None:
                        scope.bytes_complete = False
                    log.debug("could not account for an HTTP call: %s", exc)
            return response

        requests.Session.send = counting_send  # type: ignore[method-assign]
        _patched = True
