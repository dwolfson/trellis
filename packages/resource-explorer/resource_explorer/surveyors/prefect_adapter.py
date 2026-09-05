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
from prefect.client import get_client
from resource_explorer.config import get_config
from resource_explorer.prefect.flows import run_surveyor_step_task

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
) -> dict[str, Any]:
    """Trigger a flow run via Prefect REST API and wait for it to complete."""
    config = get_config()
    deployment_name = "RE Survey Flow/re-survey-step-deployment"

    async with get_client() as client:
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
                return result or {}
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
    """
    config = get_config()

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

                return run_sync(
                    lambda: asyncio.run(
                        _run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
                )
            else:
                return asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
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
