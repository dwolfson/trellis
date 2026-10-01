"""Prefect Flow and Task definitions for Resource Explorer distributed surveying."""
from __future__ import annotations

import logging
import os
import json
from typing import Any
from prefect import flow, task
from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors import step_cost_observer
from resource_explorer.surveyors.survey_definition_executor import get_adapter

log = logging.getLogger(__name__)


@task(name="Run Surveyor Step")
def run_surveyor_step_task(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a single surveyor analysis step inside a Prefect task."""
    registry = ProjectRegistry()
    adapter = get_adapter(entity_type)
    if not adapter:
        raise ValueError(f"No resource type adapter registered for '{entity_type}'")

    entity = adapter.get_entity(registry, slug)
    if not entity:
        raise ValueError(f"Entity '{slug}' of type '{entity_type}' not found in registry")

    # Dynamic routing for pre-integrated workflow quality analyzers
    if step_name == "soda_data_quality":
        if entity_type != "database":
            raise ValueError("soda_data_quality is only supported for entity_type='database'")
        return run_soda_scan_task(
            db_type=entity.db_type,
            host=entity.host,
            port=entity.port,
            database_name=entity.database_name,
            db_user=entity.db_user,
            db_password=entity.db_password,
            sodacl_yaml=runner_kwargs.get("sodacl_yaml", ""),
        )
    elif step_name == "great_expectations_validation":
        if entity_type != "database":
            raise ValueError("great_expectations_validation is only supported for entity_type='database'")
        return run_gx_validation_task(
            db_type=entity.db_type,
            host=entity.host,
            port=entity.port,
            database_name=entity.database_name,
            db_user=entity.db_user,
            db_password=entity.db_password,
            table_name=runner_kwargs.get("table_name", ""),
            expectation_suite=runner_kwargs.get("expectation_suite", {}),
        )

    runner = adapter.re_analysis_steps.get(step_name)
    if not runner:
        raise ValueError(f"Analysis step '{step_name}' not supported for type '{entity_type}'")

    # Run the surveyor step callback
    result = runner(entity, registry, **runner_kwargs)
    return result or {}


@task(name="Soda Core Quality Scan")
def run_soda_scan_task(
    db_type: str,
    host: str,
    port: int,
    database_name: str,
    db_user: str,
    db_password: str,
    sodacl_yaml: str,
) -> dict[str, Any]:
    """Run Soda Core data quality checks on the target PostgreSQL database."""
    from soda.scan import Scan

    # Construct the configuration dictionary for the database
    config_yaml = f"""
data_source postgres:
  type: postgres
  host: {host}
  port: {port}
  username: {db_user}
  password: {db_password}
  database: {database_name}
  schema: public
"""

    scan = Scan()
    scan.set_data_source_name("postgres")
    scan.add_configuration_yaml_str(config_yaml)
    scan.add_sodacl_yaml_str(sodacl_yaml)

    # Execute the scan
    exit_code = scan.execute()
    results = scan.get_scan_results()

    return {
        "exit_code": exit_code,
        "results": results,
        "has_failures": scan.has_check_failures(),
        "has_warnings": scan.has_check_warnings(),
    }


@task(name="Great Expectations Validation")
def run_gx_validation_task(
    db_type: str,
    host: str,
    port: int,
    database_name: str,
    db_user: str,
    db_password: str,
    table_name: str,
    expectation_suite: dict[str, Any],
) -> dict[str, Any]:
    """Run Great Expectations validation checkpoints on a specific database table."""
    import pandas as pd
    import sqlalchemy
    import great_expectations as gx

    # Build connection string
    conn_str = f"postgresql://{db_user}:{db_password}@{host}:{port}/{database_name}"
    engine = sqlalchemy.create_engine(conn_str)

    # Read a sample batch of data
    df = pd.read_sql(f"SELECT * FROM {table_name} LIMIT 10000", engine)

    # Get GX context
    context = gx.get_context(mode="ephemeral")

    # Define an expectation suite
    suite_name = f"{table_name}_suite"
    suite = context.data_assistant.create_expectation_suite(suite_name) if hasattr(context, "data_assistant") else context.add_expectation_suite(suite_name)

    # In Great Expectations, we can convert expectation suite dict representation
    # and validate the Pandas DataFrame
    from great_expectations.dataset import PandasDataset
    dataset = PandasDataset(df, expectation_suite=expectation_suite)
    results = dataset.validate()

    return {
        "success": results.success,
        "statistics": results.statistics,
        "results": results.to_json_dict(),
    }


@flow(name="RE Survey Flow", persist_result=True)
def re_survey_flow(
    entity_type: str,
    slug: str,
    step_name: str,
    runner_kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Prefect orchestration flow managing surveyor step runs."""
    return run_surveyor_step_task(
        entity_type=entity_type,
        slug=slug,
        step_name=step_name,
        runner_kwargs=runner_kwargs,
    )


# ── whole-survey orchestration ──────────────────────────────────────────────
#
# `re_survey_flow` above runs ONE step. It is a task wrapped in a flow, which
# is why RE ended up sequencing surveys itself: with only a per-step entry
# point, the only place a step order could live was RE's own `while` loop in
# survey_definition_executor.
#
# This flow takes the whole plan. Prefect resolves the order from the task
# dependencies rather than RE walking a list, which is the point — RE should
# delegate workflow execution, not perform it.


def _step_info_for(entity_type: str, step_key: str):
    """This step's declared cost tiers, from the SAME step registry the local
    loop reads (`SurveyDefinitionExecutor._step_info`) — looked up fresh here
    rather than threaded through Prefect's task graph, since `StepInfo` isn't
    JSON-serialisable and the plan already carries only plain dicts
    (`serialise()`). None on any failure — `step_cost_observer.observe`
    already treats a blank declared tier as nothing to disagree with."""
    try:
        from resource_explorer.surveyors.survey_definition_executor import get_adapter

        adapter = get_adapter(entity_type)
        provider = getattr(adapter, "step_registry", None)
        return (provider() or {}).get(step_key) if provider else None
    except Exception as exc:  # pragma: no cover - registry-provider guard
        log.debug("could not read step registry for %s/%s: %s", entity_type, step_key, exc)
        return None


def _record_step_cost(entity_type: str, slug: str, obs, output, surveyed_at: str) -> None:
    """§E, 2026-09-27: give a Prefect-orchestrated step the same `step_runs`
    row the local dispatch loop has always written for it
    (`SurveyDefinitionExecutor._record_cost`). Before this,
    `step_cost_observer.record` was only ever called from that module's own
    local dispatch loop, so a WHOLE definition run via `_run_via_prefect`
    produced no `step_runs` rows at all, silently — the brief's own gate
    ("the Analysis-tier `step_runs` rows must appear") would have failed on
    a SUCCESSFUL Prefect run exactly as it failed on the bare error §E
    otherwise fixes. Best-effort and never fatal: the step's real output has
    already been returned by the time this runs, so losing the cost row is
    strictly better than losing the step's actual result over an
    observability side-channel.
    """
    if not surveyed_at:
        return
    try:
        from resource_explorer.registry import ProjectRegistry

        annotations = (output or {}).get("annotations") if isinstance(output, dict) else None
        obs.annotations, obs.outcomes = step_cost_observer.describe_work(annotations)
        obs.disagreement = step_cost_observer._disagreement(obs)
        step_cost_observer.record(ProjectRegistry(), slug, obs, surveyed_at,
                                  entity_type=entity_type)
    except Exception as exc:  # pragma: no cover - best-effort observability only
        log.debug("could not record step cost for %s/%s: %s", slug, obs.step_key, exc)


@task(name="Run Planned Step")
def run_planned_step_task(
    entity_type: str,
    slug: str,
    step_key: str,
    qualified_name: str,
    runner_kwargs: dict[str, Any],
    upstream: list[dict[str, Any]],
    guarded_by: dict[str, str],
    satisfied_by_stored: dict[str, Any] | None = None,
    surveyed_at: str = "",
) -> dict[str, Any]:
    """One planned step, plus the guard decision for its incoming edges.

    `upstream` is the results of everything this step depends on. Prefect
    resolves those futures before this task starts, which is what makes the
    ordering Prefect's rather than RE's.

    A conditional edge is honoured here rather than in the planner: the
    planner is pure and cannot know what guard a step emitted. A step whose
    guards are not satisfied is reported "skipped" — never "ok", which would
    make a branch not taken indistinguishable from one that ran.

    `satisfied_by_stored` (§E, 2026-09-27) is `survey_execution_plan.
    PlannedStep.satisfied_by_stored` — the preconditions this step needed
    that the planner found already met by a fresh stored result rather than
    by a producer in this run. Carried through to the report entry unchanged
    so the provenance ("schema inventory from 20:59:29") reaches the same
    place a person or the UI pane reads the rest of the step's outcome.

    `surveyed_at`, when given, is this run's shared timestamp — see
    `_record_step_cost` for why an ACTUAL step run through here otherwise
    left no `step_runs` row at all.
    """
    by_key = {u.get("step_key"): u for u in upstream if isinstance(u, dict)}
    for upstream_key, required in (guarded_by or {}).items():
        produced = (by_key.get(upstream_key) or {}).get("guard")
        if produced != required:
            return {"step_key": step_key, "step": qualified_name, "status": "skipped",
                    "engine": "prefect", "guard": None,
                    "detail": (f"guard {required!r} required from {upstream_key} "
                               f"but it produced {produced!r}")}

    # An upstream that failed must stop this branch. Running on regardless
    # would produce a result derived from a step that did not happen.
    failed = [k for k, u in by_key.items() if u.get("status") == "error"]
    if failed:
        return {"step_key": step_key, "step": qualified_name, "status": "skipped",
                "engine": "prefect", "guard": None,
                "detail": f"upstream step(s) failed: {', '.join(sorted(failed))}"}

    info = _step_info_for(entity_type, step_key)
    try:
        with step_cost_observer.observe(
            step_key, getattr(info, "fetch_cost", ""), getattr(info, "compute_cost", ""),
            executor="prefect", source="prefect",
        ) as observed:
            output = run_surveyor_step_task.fn(
                entity_type=entity_type, slug=slug, step_name=step_key,
                runner_kwargs=runner_kwargs,
            )
    except Exception as exc:
        return {"step_key": step_key, "step": qualified_name, "status": "error",
                "engine": "prefect", "guard": None, "detail": str(exc)}

    fr_id = None
    if observed:
        # Dispatch honesty completeness (2026-09-28,
        # PREFECT-DISPATCH-HONESTY-IMPLEMENTED.md): this
        # function only ever reaches this line by genuinely executing as a
        # Prefect task inside a running flow (no REST-dispatch-then-fallback
        # branch like run_prefect_step has), so `executor="prefect"` above is
        # always trustworthy here — this just fills in the id for the same
        # "checkable against Prefect's own API" reason the per-step path's
        # flow_run_id carries one.
        try:
            from prefect.runtime import flow_run as _flow_run_ctx

            fr_id = _flow_run_ctx.id
        except Exception:  # pragma: no cover - defensive, never fatal
            fr_id = None
        if fr_id:
            observed[0].flow_run_id = str(fr_id)
        _record_step_cost(entity_type, slug, observed[0], output, surveyed_at)

    # Whole-definition Prefect default (2026-09-28,
    # PREFECT-DEFAULT-WHOLE-DEFINITION-IMPLEMENTED.md): carry the flow_run_id
    # into the step's own report entry too, not just onto the step_runs row —
    # `SurveyDefinitionExecutor._run_via_prefect` strips "output" but keeps
    # every other key, so this is how the whole-definition caller (and, via
    # steps_report, the /next pane's status line) learns which real Prefect
    # flow_run this run created, checkable against Prefect's own API rather
    # than merely asserted.
    result = {"step_key": step_key, "step": qualified_name, "status": "ok",
              "engine": "prefect", "guard": (output or {}).get("guard"),
              "flow_run_id": str(fr_id) if fr_id else "",
              "output": output}
    if satisfied_by_stored:
        result["satisfied_by_stored"] = dict(satisfied_by_stored)
    return result


@flow(name="RE Survey Definition Flow")
def re_survey_definition_flow(
    entity_type: str,
    slug: str,
    plan: list[dict[str, Any]],
    runner_kwargs: dict[str, Any] | None = None,
    surveyed_at: str = "",
) -> list[dict[str, Any]]:
    """Run a whole Survey Definition, ordered by Prefect.

    `plan` is the serialised ExecutionPlan — a list of
    {step_key, qualified_name, depends_on, guarded_by} in topological order, so
    every dependency has already been submitted when its dependents are.

    `surveyed_at` (§E, 2026-09-27): this run's shared timestamp, the same one
    `SurveyDefinitionExecutor.run()`'s local loop stamps across its own
    steps — passed through to every planned step so `step_cost_observer.
    record` (`run_planned_step_task`) writes this run's `step_runs` rows
    under it, exactly as the local loop already does for its own steps.
    """
    runner_kwargs = runner_kwargs or {}
    futures: dict[str, Any] = {}
    for entry in plan:
        key = entry["step_key"]
        upstream = [futures[d] for d in entry.get("depends_on", []) if d in futures]
        futures[key] = run_planned_step_task.submit(
            entity_type=entity_type, slug=slug, step_key=key,
            qualified_name=entry.get("qualified_name", ""),
            runner_kwargs=runner_kwargs,
            upstream=upstream,
            guarded_by=entry.get("guarded_by", {}) or {},
            satisfied_by_stored=entry.get("satisfied_by_stored", {}) or {},
            surveyed_at=surveyed_at,
        )
    # Resolved in plan order so the report reads in the order authored, not the
    # order Prefect happened to finish them in.
    return [futures[e["step_key"]].result() for e in plan]
