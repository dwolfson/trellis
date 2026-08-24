"""Prefect Client Adapter — dispatches flow runs to the Prefect API or runs them locally."""
from __future__ import annotations

import asyncio
import logging
import nest_asyncio
from typing import Any
from prefect.client import get_client
from resource_explorer.config import get_config
from resource_explorer.prefect.flows import re_survey_flow

# Enable nested event loops if running inside another async loop (e.g. Uvicorn/FastAPI)
nest_asyncio.apply()


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

        # 2. Trigger the flow run
        flow_run = await client.create_flow_run_from_deployment(
            deployment_id=deployment.id,
            parameters={
                "entity_type": entity_type,
                "slug": slug,
                "step_name": step_name,
                "runner_kwargs": runner_kwargs,
            },
        )

        # 3. Poll for the flow run to complete
        while True:
            run = await client.read_flow_run(flow_run.id)
            state = run.state
            if state.is_completed():
                # Fetch result
                result = await client.resolve_value(state.data)
                return result or {}
            elif state.is_failed():
                raise RuntimeError(
                    f"Prefect flow run '{flow_run.id}' failed: {state.message}"
                )
            elif state.is_cancelled():
                raise RuntimeError(f"Prefect flow run '{flow_run.id}' was cancelled.")

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
                # cannot nest, so hand the coroutine to a worker thread with its own loop.
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
                    )
                    return future.result()
            else:
                return asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
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

    # Fallback/Local Run: run flow directly in-process
    # This still records the flow and task runs locally if Prefect is configured.
    return re_survey_flow(
        entity_type=entity_type,
        slug=slug,
        step_name=step_name,
        runner_kwargs=runner_kwargs,
    )
