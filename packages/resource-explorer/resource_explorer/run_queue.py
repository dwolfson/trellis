"""The Postgres run queue — enqueue from anywhere, execute in the worker.

`docs/runtime-architecture-plan.md` §2, step 2b. Until this existed, a `web`
request that started a survey spawned a `threading.Thread` and returned. Three
consequences, all of them observed rather than theorised:

* The run lived in whichever uvicorn process happened to serve the request, so
  `--workers N` spread long-running work across processes by luck of routing.
* A `--no-embed-worker` web process — supposedly "HTTP only" — was still where
  every survey actually executed, which is the plan's own rule for the `web`
  role being violated by the `web` role.
* The only record of ownership was a pid buried in an `activity_log` row's
  `detail`, judged *after the fact* by `run_reconciler.py`. A claim taken
  before the work starts is the same question asked in time to be useful.

**What did not change: the frontend contract.** A route still creates its
`activity_log` row up front, still returns `{"status": "started",
"activity_id": ...}`, and the browser still polls `GET /api/activity/{id}` and
reads the run's result out of that entry's `detail`. The queue row carries that
activity id in `result_ref`; the worker writes the terminal activity status
through the very same `execute_and_record_*` functions the route's background
thread used to call. From the UI's point of view the only difference is which
process did the work.

**Claiming.** `registry.claim_next_run()` selects and marks in one transaction,
with `FOR UPDATE SKIP LOCKED` on Postgres so a second claimer skips a locked
row rather than blocking on it. See that method for the per-user fairness rule
and why the empty `requested_by` bucket is exempt from it today.

**Heartbeating.** A run's heartbeat is written every
`HEARTBEAT_INTERVAL_SECONDS` by a small companion thread, not by the executing
thread itself — the executing thread is, by construction, inside a survey that
may not return for sixteen minutes, so it cannot also be the thing that proves
it is alive. The companion thread's own liveness is the process's liveness,
which is exactly what reconciliation tests.

**Reconciliation** stays in `run_reconciler.py` and stays pid-based. A missed
heartbeat makes a row a *candidate*; only a provably-dead owning process makes
it a failure. A worker paused by a slow Egeria call is late, not gone.
"""
from __future__ import annotations

import logging
import os
import socket
import threading
from collections.abc import Callable
from dataclasses import dataclass

log = logging.getLogger(__name__)

#: How often a running row's heartbeat is refreshed.
HEARTBEAT_INTERVAL_SECONDS = 30

#: How long a claimed row may go without a heartbeat before reconciliation will
#: even look at it. Three intervals, so one slow tick and one missed tick are
#: both survivable without anyone being declared dead.
STALE_AFTER_INTERVALS = 3

#: How long the claim loop waits when the queue is empty. Short enough that a
#: click feels immediate; long enough that an idle dev box is not issuing a
#: query a second.
POLL_INTERVAL_SECONDS = 2.0


def worker_identity() -> str:
    """The `claimed_by` value: `hostname:pid`.

    Human-readable on purpose — it is what an operator reads in `runs list` and
    in the worker's own log line. It is NOT what reconciliation tests: pids are
    reused, so liveness is judged from the `runner` column's
    `run_reconciler.process_identity()` (pid plus process start time) instead.
    """
    return f"{socket.gethostname()}:{os.getpid()}"


def queue_consumption_enabled() -> bool:
    """Whether this process may CLAIM rows. Enqueueing is never affected.

    An operational flag first — a worker started to hold the background loops
    while a queue drain is deliberately paused (mid-migration, or while an
    Egeria platform is down and every claim would burn a retry) is a real thing
    to want, and there was no way to ask for it.

    It also stops the test suite from draining the shared registry's live queue.
    That is not hypothetical: `tests/test_process_roles.py` calls `run_worker()`
    for real, several sessions share one Postgres, and a claim loop started
    inside a unit test would happily pick up another session's queued survey and
    run it. `tests/conftest.py` sets this off for the whole session; the queue's
    own tests turn it back on for exactly the run they are asserting about.
    """
    raw = os.environ.get("EXPLORER_RUN_QUEUE_ENABLED")
    if raw is None:
        return True
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def requested_by() -> str:
    """Who a run is attributed to. `""` until RE adopts trellis-auth.

    A function rather than a literal at every call site so that adopting auth is
    one edit here plus wiring the request's identity through, not a hunt for
    every `requested_by=""`. Until then every row lands in the unattributed
    bucket, which `registry.claim_next_run()` deliberately exempts from the
    per-user fairness rule — see that method.
    """
    return ""


@dataclass(frozen=True)
class RunOutcome:
    state: str  # "succeeded" | "failed"
    error: str = ""


# ── the handlers, one per kind ───────────────────────────────────────────────
#
# Each takes the row's decoded `target` dict plus the `result_ref` (the
# activity_log id the UI polls) and returns a RunOutcome. They are thin on
# purpose: every one of them delegates to a workflows/ function that the route
# and the CLI also call, so "what a run does" has exactly one definition.


def _handle_analysis_run(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.workflows.analysis import execute_and_record_analysis

    result = execute_and_record_analysis(
        target["slug"], target["analysis_id"], result_ref,
    )
    return RunOutcome(
        state="succeeded" if result.status == "ok" else "failed",
        error=result.error or "",
    )


def _handle_stage_batch(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.workflows.analysis import (
        execute_and_record_stage_batch,
        resolve_stage_step_keys,
    )

    step_keys = target.get("step_keys")
    if not step_keys:
        # Re-derived rather than required: a batch enqueued from the CLI names
        # a stage, not a step list, and the catalog is the authority on what
        # the stage contains at the moment it runs.
        step_keys, _ = resolve_stage_step_keys(target["stage"])
    result = execute_and_record_stage_batch(
        target["slug"], target["stage"], step_keys, result_ref,
    )
    return RunOutcome(
        state="succeeded" if result.status == "ok" else "failed",
        error="; ".join(result.errors) if result.status == "error" else "",
    )


def _handle_scouting_scan(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.workflows.scouting import execute_and_record_scouting_scan

    result = execute_and_record_scouting_scan(target["slug"], result_ref)
    return RunOutcome(
        state="succeeded" if result.status == "ok" else "failed",
        error=result.error or "",
    )


def _handle_survey_definition_run(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.workflows.survey_definition import (
        SurveyDefinitionRunParams,
        execute_and_record_definition,
    )

    params = SurveyDefinitionRunParams.from_dict(target.get("params") or {})
    result = execute_and_record_definition(
        target["entity_type"], target["slug"], params, result_ref,
    )
    return RunOutcome(
        state="succeeded" if result.status == "ok" else "failed",
        error="; ".join(result.errors) if result.errors else "",
    )


def _handle_discovery_expand(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.workflows.discovery import expand_org

    expansion = expand_org(target["org"])
    if expansion.error:
        return RunOutcome(state="failed", error=expansion.error)
    return RunOutcome(state="succeeded")


HANDLERS: dict[str, Callable[[dict, str], RunOutcome]] = {
    "analysis_run": _handle_analysis_run,
    "stage_batch": _handle_stage_batch,
    "scouting_scan": _handle_scouting_scan,
    "survey_definition_run": _handle_survey_definition_run,
    "discovery_expand": _handle_discovery_expand,
}


# ── executing one claimed row ────────────────────────────────────────────────


class _Heartbeat:
    """Refresh one run's heartbeat until the work finishes.

    A daemon thread rather than a timer on the executing thread, because the
    executing thread is inside the survey and cannot come back to tick. It
    stops on its own when `registry.heartbeat_run` reports the row is no longer
    active — which is how it learns the row was reconciled or cancelled out
    from under it instead of writing heartbeats onto a terminal row for ever.
    """

    def __init__(self, registry, run_id: str, interval: float = HEARTBEAT_INTERVAL_SECONDS):
        self._registry = registry
        self._run_id = run_id
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._loop, name=f"re-run-heartbeat-{run_id[:8]}", daemon=True,
        )

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                if not self._registry.heartbeat_run(self._run_id):
                    log.info("run %s is no longer active; heartbeat stopping", self._run_id)
                    return
            except Exception as exc:  # a lost heartbeat must not kill the run
                log.warning("heartbeat for run %s failed: %s", self._run_id, exc)

    def __enter__(self) -> _Heartbeat:
        self._thread.start()
        return self

    def __exit__(self, *exc_info) -> None:
        self._stop.set()


def execute_run(row: dict, registry=None) -> RunOutcome:
    """Run one claimed row to a terminal state and record it.

    Every failure path writes a terminal state. The one way a run can end
    without doing so is the process dying — which is precisely what
    reconciliation exists for, and why the heartbeat is written at all.
    """
    import json

    from resource_explorer.registry import ProjectRegistry

    registry = registry or ProjectRegistry()
    run_id = row["id"]
    kind = row["kind"]
    result_ref = row.get("result_ref") or ""
    try:
        target = json.loads(row.get("target") or "{}")
    except (TypeError, ValueError):
        target = {}

    handler = HANDLERS.get(kind)
    if handler is None:
        # Loud and terminal, not left queued: a kind with no handler is a
        # deployment mistake, and a row that sits queued for ever looks
        # identical to a queue nobody is draining.
        error = f"no handler registered for run kind {kind!r}"
        log.error("run %s: %s", run_id, error)
        registry.finish_run(run_id, "failed", error=error)
        return RunOutcome(state="failed", error=error)

    registry.mark_run_running(run_id)
    if result_ref:
        # Stamp THIS process onto the activity entry, now that it is genuinely
        # the owner. The enqueuing web process deliberately does not — see
        # registry.set_activity_runner. This is also what fixes the
        # process-model's Finding F5: a queued scouting scan now records
        # ownership the same way an analysis run does, so run_reconciler's
        # pid-liveness path applies to it instead of the six-hour age heuristic.
        #
        # Not wrapped in a best-effort try/except, deliberately, and for the
        # same reason `mark_run_running` above is not: if this write fails the
        # registry is unreachable, and the run's very next acts are to heartbeat
        # and to write findings to that same registry. Swallowing the failure
        # would buy a run that proceeds without an owner recorded — precisely
        # the state reconciliation cannot judge — instead of one that fails
        # immediately and visibly.
        from resource_explorer.run_reconciler import process_identity

        registry.set_activity_runner(result_ref, process_identity())
    log.info("run started: id=%s kind=%s claimed_by=%s target=%s",
             run_id, kind, row.get("claimed_by"), target)
    try:
        with _Heartbeat(registry, run_id):
            outcome = handler(target, result_ref)
    except Exception as exc:  # pragma: no cover — a handler is expected to catch its own
        log.exception("run %s (%s) crashed", run_id, kind)
        registry.finish_run(run_id, "failed", error=f"{type(exc).__name__}: {exc}")
        return RunOutcome(state="failed", error=str(exc))

    registry.finish_run(run_id, outcome.state, error=outcome.error)
    log.info("run finished: id=%s kind=%s state=%s", run_id, kind, outcome.state)
    return outcome


# ── the claim loop ───────────────────────────────────────────────────────────


def claim_and_execute_once(registry=None, *, kinds: list[str] | None = None) -> dict | None:
    """Claim at most one row and run it. Returns the row, or None if the queue
    had nothing this worker was allowed to take.

    Exposed on its own because it is the whole of the queue's behaviour in one
    call — the loop below is just this in a `while`, and a test that wants to
    assert the embedded worker executes a queued row does not need a loop.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.run_reconciler import process_identity

    registry = registry or ProjectRegistry()
    identity = worker_identity()
    row = registry.claim_next_run(identity, process_identity(), kinds=kinds)
    if row is None:
        return None
    log.info("run claimed: id=%s kind=%s claimed_by=%s", row["id"], row["kind"], identity)
    execute_run(row, registry)
    return row


class QueueRunner:
    """The worker role's queue loop, in the shape `worker.py` starts things.

    Not leader-elected, deliberately, and this is the one place in the worker
    role where that is true. The three background loops take an advisory lock
    because two processes firing the same schedule is duplicated work; the
    queue is the opposite — `SKIP LOCKED` means every extra consumer is extra
    throughput, and electing one leader would throw that away and make the
    queue as slow as its single leader.
    """

    def __init__(self, *, poll_interval: float = POLL_INTERVAL_SECONDS,
                 kinds: list[str] | None = None):
        self.poll_interval = poll_interval
        self.kinds = kinds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def _loop(self) -> None:
        from resource_explorer.concurrency import run_sync
        from resource_explorer.registry import ProjectRegistry

        registry = ProjectRegistry()
        while not self._stop.is_set():
            try:
                # Through the shared bounded pool (step 2a's concurrency.py),
                # not a thread of its own: a run is exactly the kind of
                # blocking sync-pyegeria work that pool exists to bound, and a
                # queue that spawned an unbounded thread per row would
                # reintroduce the problem step 2a removed. `run_sync` runs the
                # callable inline when it is already on a pool thread, so this
                # cannot deadlock against itself.
                claimed = run_sync(lambda: claim_and_execute_once(kinds=self.kinds))
            except Exception:
                log.exception("run-queue tick failed; continuing")
                claimed = None
            if claimed is None:
                if self._stop.wait(self.poll_interval):
                    return
            # A row was executed — loop straight round rather than sleeping, so
            # a burst of queued work drains at the speed of the work.

    def start(self) -> None:
        if self._thread is not None:
            return
        if not queue_consumption_enabled():
            log.info("run-queue loop not started: EXPLORER_RUN_QUEUE_ENABLED is off")
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, name="re-worker-run-queue", daemon=True,
        )
        self._thread.start()
        log.info("run-queue loop started: poll=%ss identity=%s kinds=%s",
                 self.poll_interval, worker_identity(), self.kinds or "all")

    def stop(self) -> None:
        self._stop.set()
        self._thread = None
        log.info("run-queue loop stopped")


#: The worker role's single instance, so `worker.py` can start and stop it the
#: same way it starts and stops the leader-elected loops.
_runner = QueueRunner()


def start_queue_runner() -> None:
    _runner.start()


def stop_queue_runner() -> None:
    _runner.stop()
