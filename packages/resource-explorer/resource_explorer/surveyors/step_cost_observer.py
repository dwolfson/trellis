"""What a step actually cost, against what it declared.

Three cost mis-declarations turned up in one week, and no test could have
caught any of them because every one was a *declaration* that disagreed with
*behaviour*:

  * `repo_classification` declared `fetch_cost="none"` and called the GitHub
    API — ~10 minutes per repo against a tier whose defining property is zero
    fetch (CLAUDE.md rule 17). It was found by noticing a corpus run had done
    3 repos in 10 minutes, not by any check.
  * `repo_manifest_parse` declared `compute_cost="medium"` and measures like
    `repo_file_inventory`, which is `low` — so `max_compute_cost="low"` runs
    excluded it from the very tier it was added to serve.
  * A timing was reported for `resolve_doc_locations()` when the thing that
    runs is `build_report()` — out by 8x, in the flattering direction.

The common cause is that a cost tier is a guess made when a step is authored
and nothing measures it afterwards. `tests/test_analysis_catalog_reader.py`'s
zero-fetch guard checks `requires_resources`, not `fetch_cost`, and a step can
satisfy it while opening sockets — a guard that can be satisfied by declaring
one thing and doing another is not a guard.

**This reports; it never corrects.** Auto-updating a declaration from an
observation would have silently absorbed the `repo_classification` bug: a step
that suddenly starts fetching is sometimes a regression worth seeing, not a
label worth rewriting. Observed and declared are recorded side by side and the
disagreement is surfaced; deciding which is wrong is a person's job, because
sometimes it is the code.

**A first observation is loud on purpose.** For a step nobody has ever
measured, "no disagreement recorded" and "never checked" are the same silence —
the shape of most of what went wrong this week.

Socket counting is deliberately crude: `socket.socket.connect` is wrapped for
the duration of a step. Under concurrent surveys in one process the count can
attribute another thread's connection to this step, so a NON-ZERO count on a
step declared zero-fetch is a prompt to look, not a proof. A zero count is the
trustworthy direction, and that asymmetry is stated rather than hidden.
"""
from __future__ import annotations

import logging
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass

log = logging.getLogger(__name__)

KIND = "step_cost"

#: Wall-clock ceilings for each declared compute tier, in seconds. Derived from
#: measurements rather than chosen: repo_file_inventory 0.2-0.3s and
#: repo_manifest_parse 0.0-0.6s are both `low`; repo_classification's ~25s
#: median and the arch coupling passes are the medium/high end. Generous on
#: purpose — this exists to catch order-of-magnitude errors, not to police
#: seconds, and a noisy check gets switched off.
_COMPUTE_CEILING = {"low": 5.0, "medium": 60.0, "high": float("inf")}

_counter_lock = threading.Lock()
_connect_count = 0
_patched = False
_real_connect = socket.socket.connect


def _counting_connect(self, address):  # noqa: ANN001
    global _connect_count
    with _counter_lock:
        _connect_count += 1
    return _real_connect(self, address)


@dataclass
class Observation:
    step_key: str
    elapsed: float
    connects: int
    declared_fetch: str
    declared_compute: str
    #: What the step actually produced — WITHOUT this, a duration is
    #: uninterpretable. repo_data_profiling measured 0.0s median across 21
    #: repos, and a step that correctly found nothing and a step that never
    #: reached its input produce exactly that same number. Duration alone
    #: cannot separate "fast because there was nothing to do" from "fast
    #: because it did nothing", which is the absence-looks-like-zero shape
    #: relocated into the measuring instrument.
    annotations: int = -1          # -1 = not captured
    #: The step's own StepOutcome labels, when it emits them (step_outcome.py).
    #: `no_signal` means it looked and there was nothing; `unverified` means it
    #: could not look. That is exactly the distinction a duration cannot make.
    outcomes: tuple[str, ...] = ()
    #: Empty when observation and declaration agree.
    disagreement: str = ""

    @property
    def interpretable(self) -> bool:
        """Can this timing be reasoned about at all?

        A fast run says nothing about a cost tier unless we know the step had
        real work to do. `unverified` is the giveaway that it did not.
        """
        if "unverified" in self.outcomes:
            return False
        return self.annotations != 0

    @property
    def agrees(self) -> bool:
        return not self.disagreement


@contextmanager
def observe(step_key: str, declared_fetch: str, declared_compute: str):
    """Time a step and count the connections it opens, then compare.

    Yields a one-element list that receives the Observation on exit, so a
    caller can read the result without the context manager having to return
    two things.
    """
    global _connect_count, _patched
    out: list[Observation] = []
    with _counter_lock:
        start_count = _connect_count
        first = not _patched
        if first:
            socket.socket.connect = _counting_connect  # type: ignore[method-assign]
            _patched = True
    t0 = time.perf_counter()
    try:
        yield out
    finally:
        elapsed = time.perf_counter() - t0
        with _counter_lock:
            connects = _connect_count - start_count
        obs = Observation(step_key, elapsed, connects, declared_fetch, declared_compute)
        obs.disagreement = _disagreement(obs)
        out.append(obs)
        if obs.disagreement:
            log.warning("step cost: %s — %s", step_key, obs.disagreement)


def _disagreement(obs: Observation) -> str:
    """The disagreement between what was declared and what happened, if any.

    Only unambiguous cases. A step declared zero-fetch that opened a connection
    is not arguable; a step slower than its tier's generous ceiling is worth a
    look. Being FASTER than declared is reported too — repo_manifest_parse's
    over-declaration excluded it from the cheap tier it was built for, so
    over-declaring is not the harmless direction it sounds like.
    """
    bits = []
    if obs.declared_fetch == "none" and obs.connects > 0:
        bits.append(
            f"declares fetch_cost='none' but opened {obs.connects} connection(s) — "
            "zero-fetch is the defining property of the Discovery tier, and a "
            "max_fetch_cost='none' run currently believes this step is free"
        )
    # The compute ceiling only applies to a step that made NO connections.
    #
    # Caught by running this against repo_classification: it took 20.1s and got
    # flagged for declaring compute_cost='low', when ~all of that was waiting on
    # five GitHub round trips. Wall clock is a fair proxy for compute only when
    # nothing was fetched; for a fetching step it measures the network and says
    # nothing about the declaration. Emitting that disagreement would have been
    # a false alarm on an honest declaration — and a check that cries wolf is a
    # check that gets switched off, which this module's own docstring warns
    # about. Separating fetch time from compute time properly needs
    # instrumentation inside each step; until then this abstains rather than
    # guesses.
    # An uninterpretable timing is not evidence about a declaration. A step
    # that reported `unverified`, or produced nothing at all, was not exercised
    # — flagging its speed would be reading a number taken while the thing
    # being measured was not happening.
    if not obs.interpretable:
        return "; ".join(bits)
    ceiling = _COMPUTE_CEILING.get(obs.declared_compute, float("inf"))
    if obs.connects == 0 and obs.elapsed > ceiling:
        bits.append(
            f"declares compute_cost='{obs.declared_compute}' (ceiling {ceiling:.0f}s) "
            f"but took {obs.elapsed:.1f}s with no connections, so that is compute"
        )
    elif obs.declared_compute in ("medium", "high") and obs.elapsed < 1.0 and obs.connects == 0:
        bits.append(
            f"declares compute_cost='{obs.declared_compute}' but took {obs.elapsed:.2f}s with "
            "no connections — over-declaring excludes a step from the cheap tiers it "
            "may have been built to serve"
        )
    return "; ".join(bits)


#: record() outcomes. A caller can branch on these; a log line alone cannot be
#: branched on, and "the metric was never written" would otherwise look exactly
#: like "the step was never slow" — which is the failure this whole module
#: exists to catch, so the observer swallowing its own write silently would be
#: the joke writing itself.
RECORDED = "recorded"
FIRST = "first"
NOT_RECORDED = "not_recorded"


def _step_ever_measured(registry, step_key: str) -> bool:
    """Has this step been measured for ANY resource before now?

    Reads the metrics table directly rather than via query_metrics_history,
    which is per-slug by design — the question here is about the step.
    """
    metric = f"{step_key}_elapsed"
    with registry._conn() as conn:
        row = conn.execute(
            "SELECT 1 FROM project_analysis_metrics "
            "WHERE kind = ? AND metric_name = ? LIMIT 1",
            (KIND, metric),
        ).fetchone()
    return row is not None


def describe_work(annotations) -> tuple[int, tuple[str, ...]]:
    """What a step produced, as the observer needs it: how many annotations,
    and any StepOutcome labels they carry.

    Read from the annotations the orchestrator already holds, so no step has to
    cooperate for its timing to become interpretable — a step that has not
    adopted the outcome vocabulary still contributes its count.
    """
    outcomes = []
    for ann in annotations or ():
        props = getattr(ann, "json_properties", None) or {}
        outcome = props.get("outcome")
        if outcome:
            outcomes.append(outcome)
    return len(annotations or ()), tuple(sorted(set(outcomes)))


def record(registry, slug: str, obs: Observation, surveyed_at: str | None = None) -> str:
    """Persist one observation. Returns FIRST when this is the first ever for
    this step, RECORDED normally, NOT_RECORDED when persistence failed.

    For a step nobody has measured, "no disagreement" and "never checked" are
    the same silence — and that silence is the shape of most of what this
    module exists to catch. Which is exactly why the failure path returns a
    distinguishable value rather than only logging: an observer whose own
    writes fail quietly stops being evidence and starts being decoration.
    """
    first = False
    history_read = True
    try:
        # Across ALL resources, not just this one. Scoped per-slug it fired for
        # every repo in a corpus run — 189 "FIRST" lines in 21 repos, on track
        # for ~540 — and a check that shouts on every row is one that gets
        # switched off, which this module's own docstring warns about. "Nobody
        # has ever measured this step" is a fact about the step, not about a
        # repo, so it should be said once.
        first = not _step_ever_measured(registry, obs.step_key)
    except Exception as exc:
        # first stays False, so a genuinely-first observation would be reported
        # as routine — the caller needs to know the difference.
        history_read = False
        log.warning("could not read step-cost history for %s: %s", obs.step_key, exc)
    try:
        registry.upsert_metric(
            slug, KIND,
            {f"{obs.step_key}_elapsed": round(obs.elapsed, 3),
             f"{obs.step_key}_connects": float(obs.connects)},
            detail={"step": obs.step_key,
                    "declared_fetch": obs.declared_fetch,
                    "declared_compute": obs.declared_compute,
                    "observed_connects": obs.connects,
                    "observed_elapsed": round(obs.elapsed, 3),
                    "observed_annotations": obs.annotations,
                    "observed_outcomes": list(obs.outcomes),
                    "interpretable": obs.interpretable,
                    "disagreement": obs.disagreement,
                    "first_observation": first},
            surveyed_at=surveyed_at,
        )
    except Exception as exc:
        # Never fail a survey over its own instrumentation — but say so in the
        # return value, not only in a log line nobody is reading.
        log.warning("could not record step cost for %s: %s", obs.step_key, exc)
        return NOT_RECORDED
    if not history_read:
        return NOT_RECORDED
    if first:
        log.warning(
            "step cost: FIRST measurement of %s — %.1fs, %d connection(s), "
            "declared fetch=%s compute=%s%s",
            obs.step_key, obs.elapsed, obs.connects,
            obs.declared_fetch, obs.declared_compute,
            f" — {obs.disagreement}" if obs.disagreement else " (agrees)",
        )
    return FIRST if first else RECORDED
