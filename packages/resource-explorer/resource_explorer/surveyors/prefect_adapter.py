"""Prefect Client Adapter — dispatches flow runs to the Prefect API or runs them locally."""
from __future__ import annotations

import os

# Belt-and-braces guard against the ephemeral-server leak found 2026-09-04
# (see PrefectConfig.enabled's docstring in config.py): 13 orphaned
# `prefect.server.api.server:create_app` subprocess servers, days old,
# reparented to launchd. Root cause is Prefect's own client, not RE's
# fallback logic — `prefect.client.get_client()` starts an ephemeral
# in-process subprocess server whenever PREFECT_SERVER_EPHEMERAL_ENABLED is
# true and no PREFECT_API_URL is reachable, and nothing shuts that
# subprocess down. Prefect's shipped default profile (profiles.toml,
# `active = "ephemeral"`) sets PREFECT_SERVER_EPHEMERAL_ENABLED=true unless
# an operator's own ~/.prefect/profiles.toml overrides it — so this must be
# forced in-process, not just left to PrefectConfig.enabled defaulting to
# False.
#
# Verified against the installed Prefect version (3.8.1):
# prefect/settings/models/server/ephemeral.py — field `enabled`, env alias
# `PREFECT_SERVER_EPHEMERAL_ENABLED` (also accepts the older
# `PREFECT_SERVER_ALLOW_EPHEMERAL_MODE` spelling) — defaults to False in the
# settings model itself, but the shipped "ephemeral" profile overrides that
# default via profiles.toml, and env vars take priority over profile
# settings in Prefect's settings-source order (see
# prefect/settings/base.py's settings_customise_sources — env sources are
# checked before ProfileSettingsTomlLoader). setdefault() so an operator who
# deliberately wants ephemeral-server behavior can still override it via
# their own environment.
#
# Must run before `import prefect` (below) — Prefect reads its settings at
# import/first-use time.
os.environ.setdefault("PREFECT_SERVER_EPHEMERAL_ENABLED", "false")

import asyncio
import logging
from typing import Any
from prefect.client.orchestration import PrefectClient
from resource_explorer.config import get_config
from resource_explorer.prefect.flows import run_surveyor_step_task

log = logging.getLogger(__name__)


def re_prefect_client() -> PrefectClient:
    """The one place `resource_explorer` constructs a Prefect client.

    Every module that needs to talk to Prefect's REST API must call this
    instead of `prefect.client.get_client()` / `prefect.client.orchestration.
    get_client()` directly — ratcheted by
    `tests/test_no_ambient_prefect_client.py`.

    Why this exists (found live, 2026-09-28): `get_client()`, on the
    installed Prefect version (3.8.1), takes no `api=` argument at all —
    it resolves the server address itself, from `PREFECT_API_URL.value()`,
    which reads `prefect.context`'s own settings machinery. That is exactly
    the ambient/frozen-at-import mechanism `tests/conftest.py`'s
    `ephemeral_prefect` fixture already warns about for a DIFFERENT reason
    (an env var set after Prefect's first import cannot reach it) — but the
    practical failure mode observed here needed no import-ordering edge
    case to trigger: a live web-server process had `PREFECT_API_URL`
    correctly set in its OS environment, and `get_client()` still raised
    `ValueError: No Prefect API URL provided`, because nothing in this
    process had ever pointed Prefect's OWN settings resolution at it — only
    RE's own `config.prefect.api_url` (`resource_explorer/config.py`) had
    it, and `get_client()` never reads that.

    `run_prefect_step`'s broad `except Exception` (deliberately broad — see
    its own docstring) caught that `ValueError` exactly like a genuinely
    unreachable server and fell back to running the step locally — while
    `step_runs.executor` was already written as `'prefect'`, entered before
    dispatch even attempted (see `survey_definition_executor.py`). Every
    `step_runs` row labelled `executor='prefect'` from a process that never
    had this fixed was therefore not trustworthy evidence that anything ran
    through Prefect at all.

    `PrefectClient` itself (unlike the `get_client()` helper wrapped around
    it) takes `api` as a required positional argument and does nothing with
    ambient settings for it — so this reads RE's own configured URL and
    hands it straight to the constructor, with no dependency on Prefect's
    settings context having seen it at any point.
    """
    config = get_config()
    return PrefectClient(config.prefect.api_url)


async def _check_prefect_reachable_async() -> tuple[bool, str]:
    """(reachable, detail) — never raises. `detail` is the resolved API URL
    on success, or the exception text on failure."""
    config = get_config()
    try:
        async with re_prefect_client() as client:
            await client.api_healthcheck()
        return True, config.prefect.api_url
    except Exception as exc:
        return False, str(exc)


async def alog_prefect_reachability_at_startup() -> None:
    """Async twin of `log_prefect_reachability_at_startup`, for a caller
    that already owns a running event loop (the web role's FastAPI
    `lifespan`) and cannot call `asyncio.run` itself. Same behaviour,
    same log lines — see that function's docstring for why this exists at
    all."""
    config = get_config()
    if not config.prefect.enabled:
        log.info("Prefect dispatch disabled (PREFECT_ENABLED=false) — startup check skipped")
        return
    try:
        ok, detail = await _check_prefect_reachable_async()
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        log.warning("Prefect startup reachability check itself failed: %s", exc)
        return
    if ok:
        log.info("Prefect API reachable at %s", detail)
    else:
        log.warning(
            "Prefect API NOT reachable at %s (%s) — steps declaring "
            "executes_at: prefect will silently fall back to local "
            "execution until this is fixed; step_runs.executor will "
            "correctly say 'local' with a dispatch_failed reason (see "
            "docs/design-notes/PREFECT-DISPATCH-HONESTY-IMPLEMENTED.md), "
            "but nothing will actually run through Prefect",
            config.prefect.api_url, detail,
        )


def check_prefect_reachable_sync() -> tuple[bool, str]:
    """Synchronous (reachable, detail) wrapper around
    `_check_prefect_reachable_async`, for the per-run whole-definition
    default gate (2026-09-28, PREFECT-DEFAULT-WHOLE-DEFINITION-IMPLEMENTED.md):
    `SurveyDefinitionExecutor._execute` calls this once, before deciding
    whether to attempt `_run_via_prefect`, so a default (`engine_override is
    None`) run that has no Prefect server to reach skips straight to the
    local loop with an honest reason recorded — never a silent whole-
    definition fallback like the one `run_prefect_step`'s own per-step
    fallback already avoids (see PREFECT-DISPATCH-HONESTY-IMPLEMENTED.md).

    Same nested-event-loop handling as `run_prefect_step`: hands the
    coroutine to the shared bounded pool (`concurrency.run_sync`) when
    already inside a running loop (a FastAPI request thread), otherwise
    calls `asyncio.run` directly. Never raises — an exception here answers
    "not reachable", same as `_check_prefect_reachable_async` itself.
    """
    try:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            from resource_explorer.concurrency import run_sync

            return run_sync(lambda: asyncio.run(_check_prefect_reachable_async()))
        return asyncio.run(_check_prefect_reachable_async())
    except Exception as exc:  # pragma: no cover - defensive, see docstring
        return False, str(exc)


def log_prefect_reachability_at_startup() -> None:
    """A startup check for the web/worker roles: log, on the first page of
    the process's own log, whether the Prefect server RE is actually
    configured to use is reachable — not merely whether `prefect.enabled`
    is true.

    Exists because the 2026-09-28 silent-dispatch bug (see
    `re_prefect_client`'s own docstring and
    `docs/design-notes/PREFECT-DISPATCH-HONESTY-IMPLEMENTED.md`) was
    invisible on the log's first page: nothing failed loudly at process
    start, `step_runs.executor` still said `'prefect'`, and the only trace
    was a per-step WARNING inside `run_prefect_step`'s fallback, discovered
    by tracing a traceback back through two modules. A wrong or unreachable
    `PREFECT_API_URL` should be visible the moment the process starts,
    the same way the draft-zone/private-zone bootstrap
    (`worker.py::_ensure_draft_zone`) already logs its own outcome —
    not something that requires reasoning backward from a `step_runs`
    row months later.

    Skips the check entirely when `prefect.enabled` is False: an
    intentionally Prefect-less deployment (CLAUDE.md's own documented
    fallback) should not log a warning about a server nobody asked it to
    reach.

    Never raises — a Prefect outage at startup must not block the web or
    worker role from serving; `run_prefect_step`'s own per-step fallback
    already handles that case, this only makes it visible sooner.

    Synchronous wrapper (`asyncio.run`) around `alog_prefect_reachability_
    at_startup` for a caller with no event loop of its own (`worker.py`'s
    `run_worker`, called from a plain thread) — `web/app.py`'s async
    `lifespan` calls the async version directly instead, since it already
    owns a running loop and `asyncio.run` cannot nest inside one.
    """
    asyncio.run(alog_prefect_reachability_at_startup())

# `import nest_asyncio` + `nest_asyncio.apply()` used to sit here, described as
# "enable nested event loops if running inside another async loop (e.g.
# Uvicorn/FastAPI)". Removed 2026-09-04 with the shared-pool refactor, on two
# grounds:
#
# 1. It is not what makes this module work. Every sync/async bridge in RE now
#    hands the coroutine to a thread with its own fresh loop
#    (resource_explorer/concurrency.py), which needs no loop re-entrancy at all.
# 2. It was redundant regardless. pyegeria declares nest-asyncio as its own
#    dependency and applies it at package import
#    (pyegeria/view/mermaid_utilities.py:20, reached from pyegeria/__init__.py),
#    so the global patch is in effect for any process that touches pyegeria
#    whether or not this module is imported — meaning RE's copy never changed
#    the outcome, only who appeared to be responsible for it.
#
# The cross-loop hazard behind the 2026-09-03/04 incident lives in pyegeria's
# async-client construction and is NOT claimed fixed by this (see
# docs/process-model.md §1.3); this removes RE's own redundant global patch,
# nothing more.


class PrefectFlowRunCancelled(Exception):
    """A flow run was cancelled through Prefect (e.g. the Admin "⚡ Prefect"
    panel's Cancel button — see web/routes/prefect_status.py). Deliberately
    NOT caught by run_prefect_step's fallback-to-local except block: falling
    back would re-run the step's work anyway, just locally and outside
    Prefect's supervision — silently defeating the entire reason someone
    clicked Cancel. Found live 2026-08-26 testing the cancel endpoint: a
    cancelled run's RuntimeError was swallowed like any other API failure,
    the fallback ran the step again, and it just... finished — cancel had
    no actual effect. Every other failure (unreachable server, a real bug)
    should still fall back; only a genuine user-initiated cancellation
    should not."""


async def _run_prefect_step_api(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Trigger a flow run via Prefect REST API and wait for it to complete.

    Returns (result, flow_run_id) -- the id is what makes a step_runs row
    saying executor='prefect' checkable against Prefect's own
    POST /api/flow_runs/filter rather than merely asserted (see
    docs/design-notes/PREFECT-DISPATCH-HONESTY-IMPLEMENTED.md's live gate).
    """
    config = get_config()
    deployment_name = "RE Survey Flow/re-survey-step-deployment"

    async with re_prefect_client() as client:
        # 1. Fetch the deployment ID
        try:
            deployment = await client.read_deployment_by_name(deployment_name)
        except Exception as e:
            raise RuntimeError(
                f"Prefect deployment '{deployment_name}' not found. "
                "Did you run 'resource-explorer prefect deploy'? Error: {e}"
            )

        # 2. Trigger the flow run — tagged so the admin "⚡ Prefect" panel can
        # group/filter flow-runs by the resource they belong to. Not the RE
        # activity_id (run_prefect_step doesn't have one in scope — threading
        # it through SurveyDefinitionExecutor.run()'s whole call chain is a
        # bigger change than this pass makes; slug+step is enough for "what's
        # running/stuck for resource X").
        flow_run = await client.create_flow_run_from_deployment(
            deployment_id=deployment.id,
            parameters={
                "entity_type": entity_type,
                "slug": slug,
                "step_name": step_name,
                "runner_kwargs": runner_kwargs,
            },
            tags=[f"entity_type:{entity_type}", f"slug:{slug}", f"step:{step_name}"],
        )
        flow_run_id = str(flow_run.id)

        # 3. Poll for the flow run to complete
        while True:
            run = await client.read_flow_run(flow_run.id)
            state = run.state
            if state.is_completed():
                # `PrefectClient.resolve_value` doesn't exist in Prefect 3.x — this
                # line has never successfully returned a result; the exception it
                # always raised was swallowed by run_prefect_step's broad `except`,
                # so the flow run completed for real (verified live against a local
                # server + worker 2026-08-26) but its result was silently discarded
                # and every call fell through to a second, duplicate local
                # execution. `State.result()`/`State.aresult()` is the real 3.8.x
                # API on this installed version — no `fetch` kwarg here (that's a
                # newer/older-version signature; this one auto-resolves).
                result = await state.result(raise_on_failure=True)
                return result or {}, flow_run_id
            elif state.is_failed():
                raise RuntimeError(
                    f"Prefect flow run '{flow_run.id}' failed: {state.message}"
                )
            elif state.is_cancelled():
                raise PrefectFlowRunCancelled(f"Prefect flow run '{flow_run.id}' was cancelled.")

            await asyncio.sleep(1.0)


def run_prefect_step(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
    *,
    dispatch_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch step execution to Prefect, via its API when enabled, else in-process.

    The API branch had never executed. It began with `asyncio.get_running_loop()`,
    while a redundant `import asyncio` further down the same function turned
    `asyncio` into a closure cell (the lambda below captures it) — so that first
    line did a LOAD_DEREF on a cell nothing had stored yet and raised
    UnboundLocalError. The broad `except` read that as "API unreachable", logged a
    warning and fell through to local execution. Every Prefect step has therefore
    always run in-process, and _run_prefect_step_api was dead code, while the log
    line said only that dispatch had "failed".

    The module already imports asyncio at the top; the inner import is gone.

    `dispatch_info`, when given, is filled in-place with the truth about what
    actually happened -- {"engine": "prefect"|"local", "flow_run_id": str,
    "dispatch_failed": str} -- so a caller can record step_runs.executor
    honestly instead of baking in 'prefect' the moment it entered this
    branch, which is what let a silently-failed dispatch (see
    re_prefect_client's own docstring for the exact bug: get_client()
    reading Prefect's ambient settings instead of RE's configured URL)
    masquerade as a real Prefect run for the entire life of this
    integration. Optional and additive -- every existing caller/test that
    ignores it sees the same return value as before.
    """
    config = get_config()

    def _fill(engine: str, flow_run_id: str = "", dispatch_failed: str = "") -> None:
        if dispatch_info is not None:
            dispatch_info["engine"] = engine
            dispatch_info["flow_run_id"] = flow_run_id
            dispatch_info["dispatch_failed"] = dispatch_failed

    # If Prefect is enabled, attempt to run via the API (distributed worker execution)
    if config.prefect.enabled:
        try:
            # Check if event loop is running
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # Already inside an event loop (a FastAPI request thread): asyncio.run
                # cannot nest, so hand the coroutine to a worker thread with its own
                # loop. This used to construct `ThreadPoolExecutor()` with NO
                # max_workers — the only one of the six bridge sites with no cap at
                # all. It now uses the one bounded shared pool per process
                # (resource_explorer/concurrency.py).
                from resource_explorer.concurrency import run_sync

                result, flow_run_id = run_sync(
                    lambda: asyncio.run(
                        _run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
                )
            else:
                result, flow_run_id = asyncio.run(
                    _run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
            _fill("prefect", flow_run_id=flow_run_id)
            return result
        except PrefectFlowRunCancelled:
            # Must NOT fall through to local execution — that would silently
            # redo the step's work outside Prefect, defeating the cancel.
            # Re-raise so the caller (and whatever activity_log entry is
            # tracking this) sees a real cancellation, not a quiet success.
            raise
        except Exception as e:
            # Falling back is right for an unreachable or failing Prefect server —
            # the work still gets done locally. But catching everything is what hid
            # the UnboundLocalError above for the entire life of this integration,
            # so log the exception type and traceback rather than just str(e): a
            # bug here is indistinguishable from a connection problem otherwise.
            logging.warning(
                "Prefect API dispatch failed (%s), falling back to local flow execution: %s",
                type(e).__name__, e, exc_info=True,
            )
            _fill("local", dispatch_failed=f"{type(e).__name__}: {e}")
    else:
        _fill("local", dispatch_failed="")

    # Fallback/Local Run: call the step's underlying function directly, NOT
    # through `re_survey_flow` (a Prefect `@flow`). Found 2026-09-04: invoking
    # the flow-wrapped version here still enters Prefect's flow engine, which
    # itself calls `get_client()` to record flow-run state — with no
    # PREFECT_API_URL configured, that used to succeed only because the
    # ephemeral-server fallback silently started a subprocess server (the
    # exact leak this module now guards against at import time). With that
    # guard in place, calling the `@flow` here would raise instead of running
    # locally — defeating the entire point of this fallback branch, which is
    # reached whenever Prefect is disabled OR unreachable and must keep
    # working with zero Prefect server, ephemeral or real.
    #
    # `run_surveyor_step_task.fn` is Prefect's own way to reach the
    # undecorated function (same pattern `run_planned_step_task` already uses
    # to call it from inside `re_survey_definition_flow` — see
    # prefect/flows.py) — this runs the step as a plain Python call, no
    # Prefect engine involved at all.
    return run_surveyor_step_task.fn(
        entity_type=entity_type,
        slug=slug,
        step_name=step_name,
        runner_kwargs=runner_kwargs,
    )
