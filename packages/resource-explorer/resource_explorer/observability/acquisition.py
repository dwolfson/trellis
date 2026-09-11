"""Per-run source-acquisition accounting — did this run fetch, or reuse?

The cheap half of the funnel-cost spec's §6. That section asks for *bytes
fetched* to separate "slow because it waited" from "expensive because it
thought", and names caching as **the single biggest confounder** in its §1 cost
ladder. Counting bytes is the expensive answer; the confounder itself is settled
by one bit — *was this run cold?* — and `SourceCache` already knows.

The numbers behind that are not hypothetical. `CLAUDE.md` rule 17 records
acquisition measured at **22.64s cold against 1.28s warm**, and one repo's full
route going 110.5s → 30s → 14.4s as caching landed. A tier median that mixes
those two populations is not a measurement of the tier, it is a measurement of
how many of its runs happened to be first.

**Why not just read `SourceCache.hits`.** It has counted hits and misses since
it was written and nothing has ever read them — and it could not answer this
anyway: the cache is deliberately shared across `SurveyOrchestrator.run()` calls
(rule 17), so those attributes are process-wide totals. Sampling them either
side of a run would race any concurrent run sharing the instance. A ContextVar
scope attributes each lookup to the run that made it, the same way
`llm_usage` does for tokens — one pattern, not two.

**Three states, not two**, as everywhere else here:

* no scope open              -- nobody asked. Recording is a no-op.
* scope open, 0 lookups      -- this run never consulted the cache. A database
                                survey does no source acquisition at all, and
                                that is NOT the same as "everything was warm".
* scope open, lookups > 0    -- `cold` iff anything missed, because one miss
                                means a real download happened.
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field


@dataclass
class Acquisition:
    """What one measurement scope saw of the source cache."""

    hits: int = 0
    misses: int = 0
    #: Artifact kinds that had to be fetched (`zipball_root`, `git_clone_root`).
    #: A run cold on the clone but warm on the zipball is a different cost from
    #: one cold on both, and the totals alone cannot say which.
    kinds_fetched: set[str] = field(default_factory=set)

    @property
    def lookups(self) -> int:
        return self.hits + self.misses

    @property
    def state(self) -> str:
        """`cold` / `warm` / `not-consulted` — the three states above, as the
        one string a reader filters on."""
        if not self.lookups:
            return "not-consulted"
        return "cold" if self.misses else "warm"

    def as_dict(self) -> dict:
        return {
            "source_cache_hits": self.hits,
            "source_cache_misses": self.misses,
            "source_cache_lookups": self.lookups,
            # A param, not a metric: it is what a cost query FILTERS on, and
            # averaging "cold" across runs is meaningless. Carries
            # `not-consulted` rather than defaulting to "warm", which would
            # quietly put every database survey in the cheap bucket.
            "source_acquisition": self.state,
            "source_kinds_fetched": sorted(self.kinds_fetched),
        }


_current: ContextVar[Acquisition | None] = ContextVar("re_acquisition", default=None)


def current() -> Acquisition | None:
    return _current.get()


@contextmanager
def acquisition_scope() -> Iterator[Acquisition]:
    """Attribute source-cache lookups to this block. Nests: an inner scope
    folds into the enclosing one on exit, so scoping a sub-step never subtracts
    from the run containing it."""
    outer = _current.get()
    scope = Acquisition()
    token = _current.set(scope)
    try:
        yield scope
    finally:
        _current.reset(token)
        if outer is not None:
            outer.hits += scope.hits
            outer.misses += scope.misses
            outer.kinds_fetched |= scope.kinds_fetched


def record_hit(kind: str = "") -> None:
    scope = _current.get()
    if scope is not None:
        scope.hits += 1


def record_miss(kind: str = "") -> None:
    """A miss means the artifact was not cached, so a real fetch follows — this
    is the bit that separates a cold run from a warm one."""
    scope = _current.get()
    if scope is not None:
        scope.misses += 1
        if kind:
            scope.kinds_fetched.add(kind)
