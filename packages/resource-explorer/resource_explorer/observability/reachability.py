"""Is an optional observability backend actually there?

Both MLflow and Phoenix are optional, both default to `enabled=True` pointing at
a localhost port, and both degrade badly rather than quickly when nothing is
listening:

  * mlflow.set_experiment() retries six times with exponential backoff while
    holding mlflow's global _experiment_lock — minutes per call. This hung CI
    on 2026-08-24 until pytest-timeout named it.
  * An OTLP SimpleSpanProcessor exports synchronously on every span end.
    Measured against a dead collector: 7.89s for a single span, with retries —
    and that cost lands on the traced code path, once per span.

Neither shows up on a developer machine here, because MLflow really does run on
localhost:5025 and Phoenix on localhost:6006. That is the same local-vs-CI
divergence that produced the platform-split uvloop pin and the uncached
embedding model: things that work everywhere they are developed and nowhere
else.

So the rule for an optional backend is: check once, cheaply, and turn yourself
off if you are not wanted — never make everything around you slower to find out.
Same posture tests/conftest.py takes with _pgvector_reachable/_egeria_reachable.
"""
from __future__ import annotations

import socket
from urllib.parse import urlparse

#: endpoint -> reachable. Resolved once per process per endpoint; an optional
#: backend appearing mid-process is not worth re-probing for on every call.
_CACHE: dict[str, bool] = {}


def endpoint_reachable(url: str, timeout: float = 1.0) -> bool:
    """One cheap TCP connect, remembered. A file:// or path-only URL needs no
    server and is always reachable."""
    if url in _CACHE:
        return _CACHE[url]
    try:
        parsed = urlparse(url)
        if parsed.scheme in ("", "file") or not parsed.hostname:
            _CACHE[url] = True
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        with socket.create_connection((parsed.hostname, port), timeout=timeout):
            _CACHE[url] = True
    except Exception:
        _CACHE[url] = False
    return _CACHE[url]


def reset_cache() -> None:
    """For tests — the cache is deliberately process-lifetime otherwise."""
    _CACHE.clear()
