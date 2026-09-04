"""The `worker` process role — owner of every always-on background loop.

Before 2026-09-04 all of this started inside the FastAPI lifespan
(``web/app.py``), which meant there was no way to run the loops without
a web server and no way to run a web server without them. With N uvicorn
workers they would have run N times. ``docs/runtime-architecture-plan.md``
§2 makes the loops a **role**; this module is that role, and
``web/app.py`` now starts nothing of its own.

What it owns (docs/process-model.md §1.1 for the current-state detail):

* the scheduler loop — which, per that document's Finding F1, is not
  only "run due analyses": the Egeria **outbox drain** and **RFA
  reconciliation** happen inside the same 15-minute tick, in the same
  thread. They move here as part of the scheduler's move, not as
  independently-scheduled units.
* the bootstrap monitor — heals Dr.Egeria definitions wiped by an
  Egeria reset, every 10 minutes.
* the Egeria resync scanner — clears stale Egeria pointers left by a
  repository-store wipe, every 10 minutes.
* orphaned-run reconciliation — one-shot at startup.
* the survey-definition cache warm — one-shot, best-effort.

Leadership
----------
Each of the three loops is gated on its own ``pg_try_advisory_lock``
(``leader_election.py``). A process that does not win a loop's key logs
``standby`` and retries at that loop's own interval, so leadership
transfers on its own when the holder exits — no failover machinery, and
no cleanup: Postgres drops a session's advisory locks when the
connection goes.

The two one-shots are deliberately **not** gated:

* orphaned-run reconciliation judges ownership per row (pid liveness
  plus process start time, ``run_reconciler.py``), so it is already safe
  to run in every process and would be *less* correct if only a leader
  ran it.
* the cache warm repopulates a **process-local** dict
  (``survey_definition_reader``'s module-level caches). Gating it would
  warm exactly one process's cache and leave the others cold, which is
  the opposite of what it is for.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Callable

from resource_explorer.leader_election import (
    LOCK_BOOTSTRAP,
    LOCK_EGERIA_RESYNC,
    LOCK_SCHEDULER,
    LeaderLock,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class LoopSpec:
    """One leader-elected background loop."""

    name: str
    lock_name: str
    interval_seconds: int
    start: Callable[[], None]
    stop: Callable[[], None]


def _scheduler_spec() -> LoopSpec:
    from resource_explorer import scheduler

    return LoopSpec(
        name="scheduler",
        lock_name=LOCK_SCHEDULER,
        interval_seconds=scheduler._CHECK_INTERVAL_SECONDS,
        start=scheduler.start_scheduler,
        stop=scheduler.stop_scheduler,
    )


def _bootstrap_spec() -> LoopSpec:
    from resource_explorer import bootstrap

    return LoopSpec(
        name="bootstrap-monitor",
        lock_name=LOCK_BOOTSTRAP,
        interval_seconds=bootstrap.CHECK_INTERVAL_SECONDS,
        start=bootstrap.start_scheduler,
        stop=bootstrap.stop_scheduler,
    )


def _resync_spec() -> LoopSpec:
    from resource_explorer import egeria_resync

    return LoopSpec(
        name="egeria-resync",
        lock_name=LOCK_EGERIA_RESYNC,
        interval_seconds=egeria_resync.CHECK_INTERVAL_SECONDS,
        start=egeria_resync.start_scheduler,
        stop=egeria_resync.stop_scheduler,
    )


def loop_specs() -> list[LoopSpec]:
    """The three leader-elected loops, imported lazily so that importing
    this module does not drag in Egeria clients or the registry."""
    return [_scheduler_spec(), _bootstrap_spec(), _resync_spec()]


# ── one-shots ───────────────────────────────────────────────────────────

def _reconcile_orphaned_runs() -> None:
    """Resolve activity rows left 'running' by a process that is provably
    gone. Ownership-based (pid + process start time), so it never touches
    a live peer's run — see run_reconciler.py's docstring."""
    try:
        from resource_explorer.run_reconciler import reconcile

        result = reconcile()
        if result["resolved"]:
            log.info(
                "reconciled %s orphaned run(s) at startup; %s left alone",
                result["resolved"], result["left_alone"],
            )
    except Exception as exc:
        # Startup must not fail because bookkeeping did.
        log.warning("orphaned-run reconciliation skipped: %s", exc)


#: How often the worker re-checks the run queue for rows whose claimer died.
#: Well inside the stale window (3 × 30s) so a dead claim is noticed within
#: about two minutes rather than at the next process restart, which is when the
#: activity-log reconciliation runs.
_QUEUE_RECONCILE_INTERVAL_SECONDS = 60


def _reconcile_stale_queue_runs(*, ignore_heartbeat: bool = False) -> None:
    """Fail `runs` rows whose claiming process is provably gone.

    Ungated for the same reason `_reconcile_orphaned_runs` is: the judgement is
    per row and pid-based, so it is already safe in every process, and electing
    a leader for it would make it slower without making it safer.

    Runs on its own short interval rather than once at startup, because a queue
    row that a dead worker holds blocks that user's fairness slot — the
    activity-log equivalent blocks nothing, which is why a startup-only sweep
    was enough there and is not enough here.

    `ignore_heartbeat` is passed at worker startup. The heartbeat cutoff exists
    so the periodic sweep does not test liveness for every active row every
    minute; it is not part of the judgement. A pid that is provably gone is
    gone whether or not it wrote a heartbeat ten seconds before it died — and
    at startup a full sweep costs one query, so waiting three intervals to
    notice a claim the previous process left behind would be a delay bought
    with nothing.
    """
    try:
        from resource_explorer.run_reconciler import reconcile_runs

        result = reconcile_runs(ignore_heartbeat=ignore_heartbeat)
        if result["resolved"]:
            log.info(
                "reconciled %s stale queue run(s); %s left alone",
                result["resolved"], result["left_alone"],
            )
    except Exception as exc:
        log.warning("queue-run reconciliation skipped: %s", exc)


#: Deliberately NOT a LoopSpec. `loop_specs()` is the list of *leader-elected*
#: loops — the advisory keys in docs/process-model.md §1.1 are pinned by
#: tests/test_process_roles.py, and putting an ungated loop in that list would
#: make "which loops need an election" and "which loops the worker runs" the
#: same question when they are not. Same reasoning as the two one-shots.
_queue_reconcile_stop = threading.Event()
_queue_reconcile_thread: threading.Thread | None = None


def _start_queue_reconcile_loop() -> None:
    global _queue_reconcile_thread

    def _loop() -> None:
        while not _queue_reconcile_stop.wait(_QUEUE_RECONCILE_INTERVAL_SECONDS):
            _reconcile_stale_queue_runs()

    _queue_reconcile_stop.clear()
    _queue_reconcile_thread = threading.Thread(
        target=_loop, name="re-queue-reconcile", daemon=True,
    )
    _queue_reconcile_thread.start()


def _stop_queue_reconcile_loop() -> None:
    global _queue_reconcile_thread

    _queue_reconcile_stop.set()
    _queue_reconcile_thread = None


def _warm_survey_definition_cache() -> None:
    """Pre-resolve Survey-Definition question GUIDs so the first UI click
    does not pay the Egeria round trip.

    In its own daemon thread, never joined: startup must not wait on
    Egeria, which may legitimately not be up yet — the platform often
    starts after this process. Failures are swallowed by
    warm_question_guid_cache, which is best-effort by construction; if
    the warm does not happen, the first request resolves exactly as it
    does today. This changes WHEN the lookup happens, never WHAT it
    concludes.
    """

    def _run() -> None:
        try:
            from resource_explorer.surveyors.survey_definition_reader import (
                SurveyDefinitionReader,
            )

            SurveyDefinitionReader().warm_question_guid_cache()
        except Exception as exc:  # never let an optimisation take a process down
            log.debug("survey-definition cache warm skipped: %s", exc)

    threading.Thread(target=_run, name="survey-cache-warm", daemon=True).start()


# ── the leader-gated supervisor ─────────────────────────────────────────

def _supervise(spec: LoopSpec, stop_event: threading.Event, embedded: bool) -> None:
    """Win the loop's lock, start it, hold leadership until asked to stop.

    A process that loses the election does not give up: it retries at the
    loop's own interval, so when the current leader exits this one takes
    over on its next tick without anyone coordinating the handover.
    """
    lock = LeaderLock(spec.lock_name)
    started = False
    try:
        while not stop_event.is_set():
            if lock.acquire():
                log.info(
                    "worker loop started: name=%s interval=%ss leader=true "
                    "advisory_key=%s embedded=%s",
                    spec.name, spec.interval_seconds, lock.key, embedded,
                )
                spec.start()
                started = True
                stop_event.wait()
                break
            log.info(
                "worker loop standby: name=%s interval=%ss leader=false "
                "advisory_key=%s embedded=%s (another process holds this "
                "lock; retrying every %ss)",
                spec.name, spec.interval_seconds, lock.key, embedded,
                spec.interval_seconds,
            )
            if stop_event.wait(spec.interval_seconds):
                break
    finally:
        if started:
            try:
                spec.stop()
            except Exception:
                log.exception("worker loop %s did not stop cleanly", spec.name)
        lock.release()


def run_worker(
    embedded: bool = False,
    stop_event: threading.Event | None = None,
    shutdown_timeout: float = 15.0,
) -> None:
    """Run the worker role.

    Blocks until ``stop_event`` is set. Call it in the foreground
    (``resource-explorer worker``) or, with ``embedded=True``, from a
    daemon thread inside a web process (``--embed-worker``) — the two
    differ only in what they log and who owns the stop event, because
    leader election, not the caller, is what decides which process's
    loops actually fire.
    """
    stop_event = stop_event if stop_event is not None else threading.Event()

    from resource_explorer.config import get_llm_tier_config

    get_llm_tier_config()  # logs the resolved tier/model/num_ctx/budget once

    log.info(
        "worker role starting (embedded=%s): %s leader-elected loop(s) "
        "plus orphaned-run reconciliation and survey-definition cache warm",
        embedded, len(loop_specs()),
    )

    _reconcile_orphaned_runs()
    _warm_survey_definition_cache()

    # The run queue. NOT leader-elected and NOT a LoopSpec, deliberately: the
    # three loops above take an advisory lock because two processes firing the
    # same schedule is duplicated work, whereas every extra queue consumer is
    # extra throughput — `SKIP LOCKED` is what makes that safe, and electing a
    # single leader would make the queue exactly as fast as its leader.
    from resource_explorer.run_queue import start_queue_runner, stop_queue_runner

    _reconcile_stale_queue_runs(ignore_heartbeat=True)
    start_queue_runner()
    _start_queue_reconcile_loop()

    supervisors: list[threading.Thread] = []
    for spec in loop_specs():
        t = threading.Thread(
            target=_supervise,
            args=(spec, stop_event, embedded),
            name=f"re-worker-{spec.name}",
            daemon=True,
        )
        t.start()
        supervisors.append(t)

    try:
        stop_event.wait()
    finally:
        stop_event.set()
        stop_queue_runner()
        _stop_queue_reconcile_loop()
        # Bounded: a supervisor blocked on an Egeria call must not be
        # able to hold the process open past its shutdown budget. The
        # threads are daemons, so anything still running dies with the
        # process — the join is to give a clean stop its chance, not to
        # depend on it.
        deadline_each = max(0.1, shutdown_timeout / max(1, len(supervisors)))
        for t in supervisors:
            t.join(timeout=deadline_each)
        still = [t.name for t in supervisors if t.is_alive()]
        if still:
            log.warning(
                "worker shutdown bound (%ss) reached with %s still running; "
                "they are daemon threads and go with the process",
                shutdown_timeout, ", ".join(still),
            )
        else:
            log.info("worker role stopped cleanly")
        # Drop the shared pool LAST and explicitly, not via atexit: the
        # interpreter's own shutdown joins pool workers before any atexit
        # handler of ours runs, so a worker stuck in pyegeria holds the
        # process open past every bound above. Verified live 2026-09-04 —
        # see concurrency.py's "Abandoned workers" section.
        from resource_explorer.concurrency import shutdown as _pool_shutdown

        _pool_shutdown(wait=False)


def start_embedded_worker() -> tuple[threading.Thread, threading.Event]:
    """Run the worker role in a daemon thread inside this process.

    Used by the FastAPI lifespan under ``--embed-worker``. Returns the
    thread and its stop event so the lifespan can stop it on shutdown.
    """
    stop_event = threading.Event()
    thread = threading.Thread(
        target=run_worker,
        kwargs={"embedded": True, "stop_event": stop_event},
        name="re-embedded-worker",
        daemon=True,
    )
    thread.start()
    return thread, stop_event
