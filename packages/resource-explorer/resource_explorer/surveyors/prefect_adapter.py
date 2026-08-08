"""Prefect Client Adapter — dispatches flow runs to the Prefect API or runs them locally."""
from __future__ import annotations

import asyncio
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
    """Dispatch step execution to Prefect (either via API client or locally in-process)."""
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
                # Run synchronously inside existing event loop
                import asyncio
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor() as executor:
                    future = executor.submit(
                        lambda: asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
                    )
                    return future.result()
            else:
                return asyncio.run(_run_prefect_step_api(entity_type, slug, step_name, runner_kwargs))
        except Exception as e:
            # Fall back to local execution if the API server is unreachable/throws
            import logging
            logging.warning(f"Prefect API dispatch failed, falling back to local flow execution: {e}")

    # Fallback/Local Run: run flow directly in-process
    # This still records the flow and task runs locally if Prefect is configured.
    return re_survey_flow(
        entity_type=entity_type,
        slug=slug,
        step_name=step_name,
        runner_kwargs=runner_kwargs,
    )
