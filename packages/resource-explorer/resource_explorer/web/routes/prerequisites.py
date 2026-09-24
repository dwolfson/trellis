"""Accepting a prerequisite proposal (design §17.1).

A proposal is the half of §17.1 where the budget does NOT cover what the
answer needs — a chain that crosses into a more expensive tier, needs a
download or clone, needs credentials the executor cannot resolve, or is
answered by a person. The design's whole safety argument is that the budget
is the consent, so the chain cannot simply run: somebody has to say yes.

**Two endpoints, and the split is the point.** `/plan` asks what a step would
need WITHOUT running anything, so the UI can show "answering this needs X
first — estimated 40s, one download; run it?" before the user commits. `/run`
is the yes: it runs the named steps through the ordinary executor, which
observes their cost and writes their `step_runs` rows exactly as any other
run does, so an accepted proposal is not a second, unmeasured code path.

**`/run` names the steps, not the demanding step.** The client sends back the
plan it was shown. That is deliberate — a proposal the user saw and a proposal
recomputed at accept time can differ (another run may have satisfied part of
the chain meanwhile), and running something the user was not shown is the
failure mode consent exists to prevent. Steps that are no longer needed are
reported as such rather than re-run, because the resolver is consulted again
inside the executor either way.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

router = APIRouter()


class PlanRequest(BaseModel):
    entity_type: str = "database"
    slug: str
    step_key: str


class CapabilityRfaRequest(BaseModel):
    """§7.1's third choice at the gate: "raise the RFA"."""
    entity_type: str = "database"
    slug: str
    #: The step the capability shortfall blocked. Naming it is the entire
    #: difference between this RFA and the standing one the
    #: `credential_capability` probe raises — see
    #: `credential_capability.capability_rfa`.
    step_key: str


class RunRequest(BaseModel):
    entity_type: str = "database"
    slug: str
    #: The steps the user was actually shown, in the order they were shown.
    steps: list[str] = Field(default_factory=list)
    #: The step that demanded them — recorded as `demanded_by` on each
    #: producer's `step_runs` row, so an accepted proposal's cost is
    #: attributable to the question that caused it.
    demanded_by: str = ""
    #: §7.1's first choice — the user was shown a capability shortfall and
    #: chose "run it anyway and say so". Sent back the same way `steps` is,
    #: and for the same reason: the server must run what the user was shown,
    #: and a re-resolve at accept time would otherwise re-raise the shortfall
    #: and skip the step. It suppresses only the capability axis; a cost-tier
    #: reason in the same proposal is not consented by it, because the
    #: proposal's producers are named in `steps` and running them IS that
    #: consent.
    capability_consented: bool = False


def _registry():
    from resource_explorer.registry import ProjectRegistry

    return ProjectRegistry()


def _credentials_for(entity) -> dict:
    """Runner kwargs carrying the resource's stored credentials, if it has any.

    Mirrors `routes/databases.py::run_single_database_analysis`, which reads
    `db_user`/`db_password` off the registered `DatabaseEntity` for exactly
    the same reason: the step handlers take them as `db_user`/`db_pwd`, and
    nothing else resolves them.

    Empty for a resource type that stores none (repositories, filesystems) —
    their steps take no credentials, so an empty dict is the correct answer
    rather than a missing one.
    """
    user = getattr(entity, "db_user", "") or ""
    password = getattr(entity, "db_password", "") or ""
    if not (user or password):
        return {}
    return {"db_user": user, "db_pwd": password}


@router.post("/plan")
async def plan_prerequisites(req: PlanRequest) -> dict:
    """What `step_key` needs before it can answer. Runs nothing."""
    from resource_explorer.surveyors import prerequisite_resolver
    from resource_explorer.surveyors.survey_definition_executor import get_adapter

    registry = _registry()
    try:
        adapter = get_adapter(req.entity_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entity = adapter.get_entity(registry, req.slug)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"{req.entity_type} '{req.slug}' not found in the registry")
    provider = getattr(adapter, "step_registry", None)
    if provider is None:
        # Not an error and not an empty plan: this resource type has declared
        # no step costs or preconditions at all, so no claim can be made about
        # what its steps need. Rendering that as "nothing needed" would be the
        # absence-as-answer failure in a new place.
        return {"status": "not_declared", "step_key": req.step_key,
                "detail": f"the {req.entity_type} adapter declares no step registry, "
                          "so prerequisites cannot be resolved for it"}
    try:
        resolution = prerequisite_resolver.resolve(
            registry, entity, req.step_key, provider() or {})
    except prerequisite_resolver.PrerequisiteCycleError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return resolution.as_plan()


@router.post("/capability-rfa")
async def raise_capability_rfa(req: CapabilityRfaRequest) -> dict:
    """Raise the launcher's own RFA for a capability-blocked step.

    §7.1 lists three choices at the gate. This is the third; the first ("run
    partially and say so") is the ordinary `/run` path with the demanding step
    named, and the second ("pick another visible connection") is deliberately
    not built — it needs the multi-connection model that is separately gated
    on the project owner's ruling, and a button that cannot do anything is
    worse than an absent one.

    Re-resolves rather than trusting the request body for the shortfall: the
    client says WHICH step it was blocked on, and the server establishes
    whether it is still blocked and by how much. An RFA is a durable claim
    about a grant, and posting one from a stale client-side number would put
    a wrong fraction in front of a database owner.
    """
    from resource_explorer.activity_logger import log_rfa
    from resource_explorer.surveyors import credential_capability
    from resource_explorer.surveyors.survey_definition_executor import get_adapter

    registry = _registry()
    try:
        adapter = get_adapter(req.entity_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    entity = adapter.get_entity(registry, req.slug)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"{req.entity_type} '{req.slug}' not found in the registry")
    provider = getattr(adapter, "step_registry", None)
    info = (provider() or {}).get(req.step_key) if provider else None
    if info is None:
        raise HTTPException(
            status_code=400,
            detail=f"the {req.entity_type} adapter has no step {req.step_key!r}")

    probe = credential_capability.stored_probe(registry, entity)
    assessment = credential_capability.assess(
        getattr(info, "requires_capability", "") or "", probe)
    if not assessment.blocks:
        # Not an error and not a silent no-op: the honest answer is that
        # there is nothing to ask for, and the three reasons differ enough
        # that collapsing them would mislead.
        return {
            "status": "not_raised",
            "step_key": req.step_key,
            "capability": assessment.as_dict(),
            "detail": (
                "this step declares no capability requirement"
                if not assessment.requirement else
                "no capability probe has run for this resource, so no "
                "shortfall has been measured to ask about"
                if not assessment.known else
                "the connected credential already satisfies this step's "
                "requirement"),
        }

    payload = credential_capability.capability_rfa(
        req.slug, getattr(entity, "display_name", "") or req.slug,
        req.step_key, assessment)
    entry_id = log_rfa(registry, **payload)
    return {"status": "ok", "rfa_id": entry_id, "step_key": req.step_key,
            "capability": assessment.as_dict(), "summary": payload["summary"]}


@router.post("/run")
async def run_prerequisites(req: RunRequest) -> dict:
    """Run the proposed steps. This is the user's yes."""
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutor,
        get_adapter,
    )

    if not req.steps:
        raise HTTPException(status_code=400, detail="no steps named")
    registry = _registry()
    try:
        adapter = get_adapter(req.entity_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    unknown = [s for s in req.steps if s not in adapter.re_analysis_steps]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"the {req.entity_type} adapter has no runner for: {sorted(unknown)}")

    entity = adapter.get_entity(registry, req.slug)
    if entity is None:
        raise HTTPException(
            status_code=404,
            detail=f"{req.entity_type} '{req.slug}' not found in the registry")
    # Credentials come from the registered resource, never from the request
    # body. Found by running this route against a real database: without
    # them, `postgres_schema_and_stats` reached `database_connection` with
    # empty user/password and raised — an accepted proposal that could not
    # possibly succeed. The auto-run path inside the executor never showed
    # this, because there the producer inherits the demanding step's own
    # `runner_kwargs`, which already carry credentials; this route starts a
    # run with none.
    runner_kwargs = _credentials_for(entity)
    executor = SurveyDefinitionExecutor(registry)

    def _run() -> list[dict]:
        out = []
        for step_key in req.steps:
            try:
                out.append(executor.run_synthetic_step(
                    req.entity_type, req.slug, step_key,
                    executes_at="resource-explorer",
                    demanded_by=req.demanded_by,
                    capability_consented=req.capability_consented,
                    **runner_kwargs,
                    # Locally, explicitly. The user accepted a specific
                    # estimate, and Prefect's own per-step overhead is real
                    # and still unmeasured (CLAUDE.md's Prefect note) — so
                    # routing an accepted proposal through it would spend
                    # more than was quoted. It also keeps the run inside the
                    # observer, so the next estimate is a measurement rather
                    # than a tier default.
                    engine_override="resource-explorer"))
            except Exception as exc:
                # One step failing does not abandon the rest: the user
                # accepted a chain, and a partial result with a named failure
                # is more useful than a single error for the whole thing.
                log.exception("prerequisite step %s failed", step_key)
                out.append({"slug": req.slug, "steps": [
                    {"re_analysis_step": step_key, "status": "error",
                     "detail": str(exc)}]})
        return out

    results = await asyncio.to_thread(_run)
    errors = [e for r in results for e in (r.get("errors") or [])]
    return {
        "status": "error" if errors else "ok",
        "slug": req.slug,
        "demanded_by": req.demanded_by,
        "steps": req.steps,
        "results": results,
        "errors": errors,
    }
