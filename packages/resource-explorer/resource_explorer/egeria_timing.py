"""Time one Egeria API call, and record it — the instrumentation the layer-2
catalogue-depth offer needs (owner's ruling, 2026-09-15) and nothing before it
did: every measured price in this codebase so far (`RunCost`, `DepthOffer`) is
per ANALYSIS RUN, never per individual write or query.

Two things the owner named specifically, both honoured here rather than
averaged away:

- **Writes and queries are different cost populations.** An insert/update and
  a lookup do not belong in one median — `kind` keeps them apart at the
  point of recording, not as an afterthought when reading.
- **A query's cost is sensitive to its own parameters** — graph depth, page
  size. `params` travels with the row so a reader can bucket by them
  (`registry.read_egeria_call_timing_stats(..., param_filter=...)`) instead of
  mixing a depth-1 lookup with a depth-5 graph walk into one number.

Usage — wraps the call, never changes its behaviour or its exceptions:

    with time_egeria_call(registry, "create_solution_component", "write"):
        guid = self._solution_architect.create_solution_component(body)

    with time_egeria_call(registry, "find_assets", "query",
                          params={"graph_query_depth": depth}):
        results = self._asset_maker.find_assets(..., graph_query_depth=depth)

Best-effort by the same convention every other bookkeeping site in this
codebase follows (see `egeria_publisher.py`'s `_publish_homepage_reference`
docstring for the argument made in full): a failure to RECORD the timing must
never raise past the real Egeria call it is timing, and must never suppress
that call's own exception either — only the recording step is guarded.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)


@contextmanager
def time_egeria_call(registry: "ProjectRegistry | None", call_name: str, kind: str,
                     params: dict | None = None):
    """`kind` is `"write"` or `"query"`. `registry=None` (a registry-less
    publisher, same optional-registry convention this codebase uses
    throughout) makes this a no-op timer — still yields, records nothing."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        if registry is not None:
            try:
                registry.record_egeria_call_timing(call_name, kind, time.monotonic() - t0, params)
            except Exception as exc:
                log.debug("Could not record Egeria call timing for %s: %s", call_name, exc)
