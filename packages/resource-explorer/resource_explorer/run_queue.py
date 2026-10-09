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
and why the empty `requested_by` bucket is exempt from it — since 2026-09-04
that bucket holds only the worker's own service-account work, so the exemption
is narrow and the fairness rule finally applies to real people.

**Attribution.** A claimed row is executed inside `_run_as_requester`, which
publishes `requested_by` as the caller so anything the run writes to Egeria is
owned by the person who asked for it. The row deliberately carries no Egeria
token — see that function for why, and for what the resulting gap is.

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
from contextlib import contextmanager
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
    """Who a run is attributed to: the signed-in caller, or `""`.

    This was the plan's own hook and it has now been taken (2026-09-04, plan
    §4): it reads RE's one identity ContextVar, set by the web
    `_identity_middleware`, by the A2A middleware, and by the CLI's
    `cli.session.activate()`. So a run enqueued from a browser, from an agent
    or from a terminal all carry the same user id with no per-call-site
    threading — which is exactly why this was a function and not a literal.

    `""` now means one thing only: **the worker's own service-account work**,
    plus a genuinely signed-out invocation. `registry.claim_next_run()` still
    exempts that bucket from the per-user fairness rule, and that exemption is
    now narrow rather than universal — see that method.
    """
    from resource_explorer.a2a_auth import caller

    identity = caller()
    if identity is None or identity.auth_source == "anonymous":
        return ""
    return identity.user_id or ""


@dataclass(frozen=True)
class RunOutcome:
    state: str  # "succeeded" | "failed"
    error: str = ""

    def __post_init__(self) -> None:
        # One place for EVERY handler: an error text can carry a connection string or token from
        # somebody else's exception, and this is what finish_run stores and the UI shows.
        from resource_explorer.secret_redaction import scrub_text

        object.__setattr__(self, "error", scrub_text(self.error))


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
        publish=target.get("publish"),
        # Default "repo" for a row enqueued before `entity_type` was added to
        # `WorkLists.enqueue_batch`'s target dict — unchanged behaviour for
        # any row already queued.
        entity_type=target.get("entity_type", "repo"),
    )
    return RunOutcome(
        state="succeeded" if result.status == "ok" else "failed",
        error=result.error or "",
    )


def _handle_database_analysis_run(target: dict, result_ref: str) -> RunOutcome:
    """The database equivalent of `_handle_analysis_run` above — added
    because `run_single_database_analysis` (web/routes/databases.py) used to
    run its survey step(s) synchronously inside the request and return a
    response with no `activity_id` at all, so `/next`'s `pollActivity()`
    (which every "Run" action on a database's Questions checklist goes
    through) hit `GET /api/activity/undefined` and reported "Activity entry
    not found" for a run that had, in fact, already completed. See
    `workflows.analysis.execute_and_record_database_analysis`'s docstring for
    why this is a distinct handler/dataclass from the repo path rather than a
    reuse of `_handle_analysis_run` — database analysis runs do not
    auto-publish to Egeria the way repo's do."""
    from resource_explorer.workflows.analysis import execute_and_record_database_analysis

    result = execute_and_record_database_analysis(
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


def _handle_curate_commit(target: dict, result_ref: str) -> RunOutcome:
    """Catalogue →. Every step writes its outcome to the curation record;
    the run fails only if a step did (the record says which)."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.workflows.curate_commit import execute_curation

    rec = execute_curation(ProjectRegistry(), target["curation_id"])
    failed = [s["name"] for s in rec.get("steps", []) if s.get("state") == "failed"]
    return RunOutcome(state="failed" if failed else "succeeded",
                      error=("failed: " + ", ".join(failed)) if failed else "")


def _handle_catalogue_commit(target: dict, result_ref: str) -> RunOutcome:
    """Catalogue → for a database. Every step writes its outcome to the curation
    record; the run fails only if a step did (the record says which)."""
    from resource_explorer.catalogue_commit import execute_commit, run_with_loop
    from resource_explorer.registry import ProjectRegistry

    # pyegeria's sync wrappers need an event loop on the executing thread
    rec = run_with_loop(execute_commit, ProjectRegistry(), target["curation_id"])
    failed = [s["name"] for s in rec.get("steps", []) if s.get("state") == "failed"]
    return RunOutcome(state="failed" if failed else "succeeded",
                      error=("failed: " + ", ".join(failed)) if failed else "")


def _handle_materialize_components(target: dict, result_ref: str) -> RunOutcome:
    """Accepted components become Egeria SolutionComponents, one at a time,
    after a branch verdict, then each is promoted out of RE's draft zone (the configured-only zone
    rule). Run with an event loop on this thread, like its sibling `_handle_curate_commit`: pyegeria's
    sync wrappers need one and a worker thread has none. The run fails if a materialization did OR a
    promotion did; the summary says which, separately."""
    from resource_explorer.catalogue_commit import run_with_loop

    return run_with_loop(_materialize_components, target)


def _materialize_components(target: dict) -> RunOutcome:
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.workflows.curate import (
        NODE_PROMOTION_COMPONENT,
        materialize_component_if_accepted,
        promote_to_publish_zones,
        record_promotion,
    )

    from resource_explorer.secret_redaction import scrub_text

    registry = ProjectRegistry()
    slug = target["slug"]
    failed, promo_failed, done = [], [], 0
    for path in target.get("paths") or []:
        try:
            res = materialize_component_if_accepted(registry, "repo", slug, path, "accepted")
            if res and res.get("status") == "error":
                failed.append(scrub_text(f"{path}: {res.get('error')}"))
                continue
            guid = (res or {}).get("guid", "")
            if guid:
                promotion = promote_to_publish_zones(guid)
                record_promotion(registry, slug, path, NODE_PROMOTION_COMPONENT, promotion)
                if promotion.get("status") == "error":
                    promo_failed.append(scrub_text(f"{path}: {promotion.get('error') or promotion.get('words')}"))
                    continue
            done += 1                      # counted only once the whole accept (element and zone) landed
        except Exception as exc:
            failed.append(scrub_text(f"{path}: {type(exc).__name__}: {exc}"))
    if not failed and not promo_failed:
        return RunOutcome(state="succeeded")
    parts = [f"{done} materialised"]
    if failed:
        parts.append("materialization failed: " + "; ".join(failed))
    if promo_failed:
        parts.append("promotion failed: " + "; ".join(promo_failed))
    return RunOutcome(state="failed", error=" · ".join(parts)[:1500])


def _handle_publish_architecture(target: dict, result_ref: str) -> RunOutcome:
    """Publish for a repository's architecture: the accepted components, then the accepted blueprints, are
    written to Egeria (architecture_publish.run_publish). Run with an event loop on this thread, like its
    sibling `_handle_materialize_components`. The run fails when any item failed or was only partly written;
    the per-item results are the proof rows the run wrote."""
    from resource_explorer.catalogue_commit import run_with_loop

    return run_with_loop(_publish_architecture, target, result_ref)


def _publish_architecture(target: dict, result_ref: str) -> RunOutcome:
    from resource_explorer.architecture_publish import FAILED, PARTIAL, run_publish
    from resource_explorer.registry import ProjectRegistry

    results = run_publish(ProjectRegistry(), target["slug"], target, result_ref)
    bad = [r for r in results if r["status"] in (FAILED, PARTIAL)]
    if not bad:
        return RunOutcome(state="succeeded")
    return RunOutcome(state="failed", error=" · ".join(
        f"{r['name']}: {r['status']} · {r['words']}" for r in bad)[:1500])


HANDLERS: dict[str, Callable[[dict, str], RunOutcome]] = {
    "curate_commit": _handle_curate_commit,
    "catalogue_commit": _handle_catalogue_commit,
    "materialize_components": _handle_materialize_components,
    "publish_architecture": _handle_publish_architecture,
    "analysis_run": _handle_analysis_run,
    "database_analysis_run": _handle_database_analysis_run,
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


# ── who a run acts as (Brief I, owner's scope update 2026-10-09) ────────────

#: A person's direct actions that are queued: they run AS that person. The person's Egeria
#: bearer token is handed to the run in memory at enqueue (`enqueue_as_caller`) and never
#: persisted, logged or written to an activity row. Missing (restart, another process) or
#: expired: the run fails with "your Egeria sign-in expired; sign in again" and is never run as
#: the daemon. Every other kind (surveys, analyses, scheduled work) runs as
#: `Daemon(RUN_QUEUE, requested_by)`, Ownership stamped as the requester, as before.
CALLER_RUN_KINDS = frozenset({"publish_architecture", "curate_commit", "catalogue_commit",
                              "materialize_components"})


#: How long a handed-over token may wait for its run; a token lives about an hour anyway.
CALLER_TOKEN_TTL_SECONDS = 2 * 60 * 60

CLI_NO_SIGN_IN = "Publish from the web UI; the CLI has no sign-in"


class _CallerTokenHandoff:
    """run id -> (user id, Egeria bearer token, put-at). Process-local and in memory only."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_run: dict[str, tuple[str, str, float]] = {}

    def put(self, run_id: str, user_id: str, token: str) -> None:
        import time as _time

        with self._lock:
            self._by_run[run_id] = (user_id, token, _time.time())

    def take(self, run_id: str) -> "tuple[str, str] | None":
        with self._lock:
            got = self._by_run.pop(run_id, None)
        return (got[0], got[1]) if got else None

    def drop(self, run_id: str) -> bool:
        with self._lock:
            return self._by_run.pop(run_id, None) is not None

    def ids(self) -> list[str]:
        with self._lock:
            return list(self._by_run)

    def has(self, run_id: str) -> bool:
        with self._lock:
            return run_id in self._by_run

    def expired_ids(self, ttl: float = CALLER_TOKEN_TTL_SECONDS) -> list[str]:
        import time as _time

        cutoff = _time.time() - ttl
        with self._lock:
            return [r for r, (_, _, at) in self._by_run.items() if at < cutoff]

    def clear(self) -> None:
        with self._lock:
            self._by_run.clear()

    def __repr__(self) -> str:          # never the tokens, even by accident
        with self._lock:
            return f"<_CallerTokenHandoff runs={len(self._by_run)}>"


_caller_tokens = _CallerTokenHandoff()

_MARKER: "tuple[int, str] | None" = None


def process_marker() -> str:
    """This process, as the owner marker of its callers' queued runs: host, pid and process
    start time (pids are reused). Cached per pid, so a fork computes its own."""
    global _MARKER
    import json as _json

    if _MARKER is None or _MARKER[0] != os.getpid():
        from resource_explorer.run_reconciler import process_identity

        _MARKER = (os.getpid(), _json.dumps(
            {"caller_runs_of": {"host": socket.gethostname(), **process_identity()}}, sort_keys=True))
    return _MARKER[1]


def enqueue_as_caller(registry, kind: str, target: dict, **kwargs) -> str:
    """Enqueue a person's own action and hand their Egeria token to it, in memory.

    `Caller()` is read FIRST, so no caller or an expired sign-in is a 401 before anything is
    queued. The token is put in this process's map BEFORE the row exists, and the row is marked
    as owned by this process (`runner`), so only this process's caller-run executor claims it.
    `requested_by` defaults to the caller's id."""
    import uuid

    from resource_explorer.egeria_clients import Caller

    if kind not in CALLER_RUN_KINDS:
        raise ValueError(f"{kind!r} is not a caller run kind")
    caller = Caller()
    kwargs.setdefault("requested_by", caller.user_id)
    run_id = kwargs.pop("run_id", None) or str(uuid.uuid4())
    _caller_tokens.put(run_id, caller.user_id, caller.token)
    try:
        return registry.enqueue_run(kind, target, run_id=run_id, owner=process_marker(), **kwargs)
    except BaseException:
        _caller_tokens.drop(run_id)
        raise


def drop_caller_token(run_id: str) -> bool:
    """Forget a run's handed-over token (it was cancelled, or failed before it was claimed)."""
    return _caller_tokens.drop(run_id)


def sweep_caller_runs(registry, *, now: "float | None" = None) -> list[str]:
    """Fail the queued caller runs that can no longer run, and drop their tokens. Returns ids.

    * this process holds a token past `CALLER_TOKEN_TTL_SECONDS` — dropped, run failed;
    * a queued row owned by a process on THIS host that is gone — failed (its token died with it);
    * a queued row owned here whose token is missing — failed.
    Every failure carries "your Egeria sign-in expired; sign in again"."""
    import json as _json

    from resource_explorer.egeria_clients import EXPIRED_SENTENCE
    from resource_explorer.run_reconciler import _is_alive

    failed = []
    # A token whose run is no longer queued (cancelled elsewhere, e.g. from the CLI, or failed)
    # has nothing left to serve: drop it.
    for run_id in _caller_tokens.ids():
        row = registry.get_run(run_id)
        if row is None or row.get("state") != "queued":
            _caller_tokens.drop(run_id)
    for run_id in _caller_tokens.expired_ids():
        _caller_tokens.drop(run_id)
        if registry.fail_queued_run(run_id, EXPIRED_SENTENCE):
            failed.append(run_id)
    mine = process_marker()
    for row in registry.queued_owned_runs():
        if row.get("kind") not in CALLER_RUN_KINDS:
            continue
        if row.get("runner") == mine:
            dead = not _caller_tokens.has(row["id"])
        else:
            try:
                owner = (_json.loads(row.get("runner") or "{}") or {}).get("caller_runs_of") or {}
            except (TypeError, ValueError):
                owner = {}
            dead = owner.get("host") == socket.gethostname() and _is_alive(owner) is False
        if dead and registry.fail_queued_run(row["id"], EXPIRED_SENTENCE):
            _caller_tokens.drop(row["id"])
            failed.append(row["id"])
    for run_id in failed:
        log.warning("caller run %s failed before it was claimed: no live sign-in held for it", run_id)
        row = registry.get_run(run_id) or {}
        try:
            target = _json.loads(row.get("target") or "{}")
        except (TypeError, ValueError):
            target = {}
        _close_activity(registry, row.get("result_ref") or "", row.get("kind") or "", target,
                        RunOutcome(state="failed", error=EXPIRED_SENTENCE))
    return failed


@contextmanager
def _run_as_requester(row: dict):
    """Execute a claimed row as the identity its kind calls for.

    * A caller kind (`CALLER_RUN_KINDS`) runs as the person, on the token handed over at enqueue.
      The caller of this context manager has already checked the token is there and live.
    * Any other kind runs as `Daemon(RUN_QUEUE, requested_by)`: the daemon authenticates and
      `Ownership` is stamped with `requested_by` (the interim shape `egeria_identity`'s module
      docstring explains: no token survives a long queue). `current_caller` still names the
      requester (token-less), because the registry's user scoping reads it.
    """
    from resource_explorer.a2a_auth import CallerIdentity, current_caller
    from resource_explorer.egeria_clients import Daemon, DaemonReason, acting_as, client_scope

    handed = row.get("_caller_token")
    if handed is not None:
        user_id, token = handed
        reset = current_caller.set(CallerIdentity(user_id=user_id, egeria_token=token,
                                                  auth_source="run-handoff", role="user"))
        try:
            with client_scope():
                yield
        finally:
            current_caller.reset(reset)
        return

    requester = (row.get("requested_by") or "").strip()
    reset = current_caller.set(
        CallerIdentity(user_id=requester, egeria_token=None, auth_source="queued-run", role="user")
        if requester else None)
    try:
        with acting_as(Daemon(DaemonReason.RUN_QUEUE, requested_by=requester or None)):
            yield
    finally:
        current_caller.reset(reset)


def _take_caller_token(run_id: str) -> "tuple[str, str] | None":
    """The handed-over token for a caller run, dropped from memory as it is taken; None when it is
    missing or already expired (both mean: sign in again)."""
    handed = _caller_tokens.take(run_id)
    if handed is None:
        return None
    from trellis_auth.auth import egeria_token_expiry
    import time as _time

    exp = egeria_token_expiry(handed[1])
    if exp is not None and exp <= _time.time():
        return None
    return handed


def _first_sentence(text: str, limit: int = 240) -> str:
    text = " ".join(str(text or "").split())
    for i, ch in enumerate(text):
        if ch == "." and (i + 1 == len(text) or text[i + 1] == " "):
            text = text[:i]
            break
    return text[:limit]


def _activity_words(registry, kind: str, target: dict, outcome: "RunOutcome") -> tuple[str, str]:
    """(status, one sentence) for the activity entry of a run that just ended.

    Says what happened. A failed commit names the step that failed and Egeria's/our own first sentence
    about why, read from the curation record the handler already filled in.
    """
    slug = str(target.get("slug") or "") if isinstance(target, dict) else ""
    ok = outcome.state == "succeeded"
    status = "ok" if ok else "error"
    if kind in ("curate_commit", "catalogue_commit"):
        label = "Cataloging" if not ok else "Cataloged"
        failed = []
        steps = []
        cid = target.get("curation_id") if isinstance(target, dict) else None
        if cid:
            from resource_explorer.curate_plan import Curations
            rec = Curations(registry).get(cid) or {}
            steps = rec.get("steps") or []
            failed = [s for s in steps if s.get("state") == "failed"]
        if ok:
            done = sum(1 for s in steps if s.get("state") == "done")
            return status, f"{label} {slug or 'the resource'}: {done} step(s) done."
        if failed:
            first = failed[0]
            why = _first_sentence(first.get("detail") or outcome.error or "no reason recorded")
            more = f" (and {len(failed) - 1} more step(s) failed)" if len(failed) > 1 else ""
            return status, f"{label} {slug or 'the resource'} failed at step {first.get('name')}: {why}{more}."
        return status, f"{label} {slug or 'the resource'} failed: {_first_sentence(outcome.error) or 'no reason recorded'}."
    if kind == "materialize_components":
        n = len(target.get("paths") or []) if isinstance(target, dict) else 0
        if ok:
            return status, f"Materialised {n} accepted component(s) of {slug or 'the resource'}."
        return status, f"Materialising {n} accepted component(s) of {slug or 'the resource'} failed: {_first_sentence(outcome.error, 400) or 'no reason recorded'}."
    if kind == "publish_architecture":
        n = (len(target.get("paths") or []) + len(target.get("blueprints") or [])) if isinstance(target, dict) else 0
        if ok:
            return status, f"Published {n} accepted item(s) of {slug or 'the resource'}."
        return status, f"Publishing {n} accepted item(s) of {slug or 'the resource'} failed: {_first_sentence(outcome.error, 400) or 'no reason recorded'}."
    if ok:
        return status, f"{kind.replace('_', ' ')} finished."
    return status, f"{kind.replace('_', ' ')} failed: {_first_sentence(outcome.error) or 'no reason recorded'}."


def _close_activity(registry, result_ref: str, kind: str, target: dict, outcome: "RunOutcome") -> None:
    """Every exit of a run writes the final status on its activity entry (the entry the route opened as
    'running' and handed over as `result_ref`). A no-op when the handler already closed it. Not wrapped:
    if the registry cannot be written the caller must see that, not a row quietly left 'running'."""
    if not result_ref:
        return
    status, summary = _activity_words(registry, kind, target, outcome)
    registry.close_activity_if_running(result_ref, status, summary)


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
        outcome = RunOutcome(state="failed", error=error)
        _close_activity(registry, result_ref, kind, target, outcome)
        return outcome

    handed = None
    if kind in CALLER_RUN_KINDS:
        handed = _take_caller_token(run_id)
        if handed is None:
            # Never the daemon for a person's own action (Brief I). The token lived in the
            # enqueuing process's memory only: a restart, another process, or an hour drops it.
            from resource_explorer.egeria_clients import EXPIRED_SENTENCE

            log.warning("run %s (%s): no live sign-in handed over — failing, not running as the daemon",
                        run_id, kind)
            registry.finish_run(run_id, "failed", error=EXPIRED_SENTENCE)
            outcome = RunOutcome(state="failed", error=EXPIRED_SENTENCE)
            _close_activity(registry, result_ref, kind, target, outcome)
            return outcome

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
        from resource_explorer.observability import acquisition, llm_usage

        with _Heartbeat(registry, run_id), \
                _run_as_requester({**row, "_caller_token": handed} if handed else row), \
                llm_usage.usage_scope() as usage, \
                acquisition.acquisition_scope() as acquired:
            outcome = handler(target, result_ref)
    except Exception as exc:  # pragma: no cover — a handler is expected to catch its own
        # Scrubbed by shape before it is logged or stored: a handler's exception can carry a connection
        # string or token, and this catch-all writes the traceback, the run row and the outcome.
        import traceback
        from resource_explorer.secret_redaction import scrub_text

        log.error("run %s (%s) crashed\n%s", run_id, kind, scrub_text(traceback.format_exc()))
        crash = scrub_text(f"{type(exc).__name__}: {exc}")
        registry.finish_run(run_id, "failed", error=crash)
        outcome = RunOutcome(state="failed", error=crash)
        _close_activity(registry, result_ref, kind, target, outcome)
        return outcome

    # LLM cost for this run, recorded OUTSIDE the try above on purpose: the
    # handler has already succeeded by here, and a metrics sink must not be able
    # to turn that into a failed run. `usage` is still in scope — the `with`
    # closed, the name did not — and is read here in the worker rather than from
    # a callback, since the scope is a ContextVar only code running under it can
    # see. `log_run_usage` swallows its own errors too; this is belt and braces
    # because the cost of being wrong is a run reported failed after doing its
    # work.
    # Logged whenever EITHER has something to say. A run that made no LLM call
    # but fetched a 200MB zipball is the expensive case §1 cares most about, and
    # gating on `usage.calls` alone would have dropped it entirely.
    if usage.calls or acquired.lookups:
        snapshot = usage.as_dict()
        acquired_snapshot = acquired.as_dict()
        log.info("run %s (%s) cost: %s %s", run_id, kind, snapshot, acquired_snapshot)
        # No try/except here on purpose. log_run_usage cannot raise — its whole
        # body is guarded — and wrapping it would make execute_run itself a
        # broad-except/log-only site in a function that returns a RunOutcome,
        # which is exactly what tests/test_no_silent_success.py flags. The
        # protection belongs in the sink, not at every call site.
        from resource_explorer.observability.mlflow_tracking import log_run_usage

        log_run_usage(run_id, kind, snapshot, acquisition=acquired_snapshot,
                      slug=str(target.get("slug") or "") if isinstance(target, dict) else "",
                      analysis_id=str(target.get("analysis_id") or "") if isinstance(target, dict) else "")

    registry.finish_run(run_id, outcome.state, error=outcome.error)
    _close_activity(registry, result_ref, kind, target, outcome)
    log.info("run finished: id=%s kind=%s state=%s", run_id, kind, outcome.state)
    return outcome


# ── the claim loop ───────────────────────────────────────────────────────────


def claim_and_execute_once(registry=None, *, kinds: list[str] | None = None,
                           owner: str = "") -> dict | None:
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
    row = registry.claim_next_run(identity, process_identity(), kinds=kinds, owner=owner)
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
                import traceback
                from resource_explorer.secret_redaction import scrub_text

                log.error("run-queue tick failed; continuing\n%s", scrub_text(traceback.format_exc()))
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


class CallerRunExecutor:
    """Every web process runs one (Brief I, round 2), embedded worker or not: it claims ONLY the
    queued caller runs this process owns (it holds their tokens in memory) and runs them one at
    a time; a separate worker never claims them (`claim_next_run(owner="")` skips owned rows).
    Each pass also sweeps caller runs that can no longer run (`sweep_caller_runs`)."""

    def __init__(self, *, poll_interval: float = 1.0, sweep_every: float = 60.0):
        self.poll_interval = poll_interval
        self.sweep_every = sweep_every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def run_once(self, registry=None) -> "dict | None":
        from resource_explorer.registry import ProjectRegistry

        registry = registry or ProjectRegistry()
        return claim_and_execute_once(registry, kinds=sorted(CALLER_RUN_KINDS), owner=process_marker())

    def _loop(self) -> None:
        import time as _time

        last_sweep = 0.0
        while not self._stop.is_set():
            claimed = None
            try:
                from resource_explorer.registry import ProjectRegistry

                registry = ProjectRegistry()
                if _time.monotonic() - last_sweep >= self.sweep_every:
                    sweep_caller_runs(registry)
                    last_sweep = _time.monotonic()
                claimed = self.run_once(registry)
            except Exception:
                import traceback
                from resource_explorer.secret_redaction import scrub_text

                log.error("caller-run executor tick failed; continuing\n%s", scrub_text(traceback.format_exc()))
            if claimed is None and self._stop.wait(self.poll_interval):
                return

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="re-caller-runs", daemon=True)
        self._thread.start()
        log.info("caller-run executor started: owner=%s", worker_identity())

    def stop(self) -> None:
        self._stop.set()
        self._thread = None


_caller_executor = CallerRunExecutor()


def start_caller_run_executor() -> None:
    _caller_executor.start()


def stop_caller_run_executor() -> None:
    _caller_executor.stop()


#: The worker role's single instance, so `worker.py` can start and stop it the
#: same way it starts and stops the leader-elected loops.
_runner = QueueRunner()


def start_queue_runner() -> None:
    _runner.start()


def stop_queue_runner() -> None:
    _runner.stop()
