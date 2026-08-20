"""Resource schedule API — store and retrieve analysis schedules per resource."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

router = APIRouter()


def _cost_hint(entity_type: str, analysis_id: str) -> dict:
    """Cost tiers and the cadence they warrant, for one analysis.

    Repo-only: cost tiers live on repo StepInfo entries, and database/filesystem
    analyses have no equivalent yet. Returning empty rather than guessing keeps
    that absence visible instead of showing every database analysis as "daily,
    costs nothing".
    """
    if entity_type != "repo":
        return {}
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_STEP_MAP, analysis_cost, recommended_schedule,
    )
    if analysis_id not in REPO_ANALYSIS_STEP_MAP:
        return {}
    fetch, compute = analysis_cost(analysis_id)
    return {"fetch_cost": fetch, "compute_cost": compute,
            "recommended_schedule": recommended_schedule(analysis_id)}

_VALID_SCHEDULES = {"manual", "daily", "weekly", "monthly"}


class ScheduleEntry(BaseModel):
    analysis_id: str
    schedule: str = "manual"    # manual | daily | weekly | monthly
    enabled: bool = True


@router.get("/")
def list_all_schedules() -> list[dict]:
    """Every scheduled analysis across every resource — backs the Admin
    Schedules overview. Errors surface first; see
    ProjectRegistry.list_all_schedules()'s docstring."""
    return [{**r, **_cost_hint(r.get("entity_type", ""), r.get("analysis_id", ""))}
            for r in ProjectRegistry().list_all_schedules()]


@router.get("/{entity_type}/{slug}")
def get_schedules(entity_type: str, slug: str) -> list[dict]:
    """Return all schedules configured for a resource."""
    return [{**r, **_cost_hint(entity_type, r.get("analysis_id", ""))}
            for r in ProjectRegistry().get_schedules(entity_type, slug)]


@router.delete("/{entity_type}/{slug}/{analysis_id}")
def delete_schedule(entity_type: str, slug: str, analysis_id: str) -> dict:
    """Remove a schedule entirely (vs. disabling it) — useful for cleaning up
    stale schedules pointing at a resource that no longer exists."""
    from fastapi import HTTPException
    if not ProjectRegistry().delete_schedule(entity_type, slug, analysis_id):
        raise HTTPException(status_code=404, detail="Schedule not found")
    return {"status": "success"}


@router.post("/{entity_type}/{slug}")
def save_schedule(entity_type: str, slug: str, entry: ScheduleEntry) -> dict:
    """Create or update a schedule for a specific analysis on a resource."""
    if entry.schedule not in _VALID_SCHEDULES:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Invalid schedule '{entry.schedule}'; must be one of {sorted(_VALID_SCHEDULES)}")
    ProjectRegistry().save_schedule(
        entity_type=entity_type,
        entity_slug=slug,
        analysis_id=entry.analysis_id,
        schedule=entry.schedule,
        enabled=entry.enabled,
    )
    hint = _cost_hint(entity_type, entry.analysis_id)
    out = {"status": "ok", "entity_type": entity_type, "entity_slug": slug,
           "analysis_id": entry.analysis_id, "schedule": entry.schedule,
           "enabled": entry.enabled, **hint}

    # Advisory only — the schedule above is already saved. A ceiling that
    # refused would be wrong: wanting an expensive analysis more often than its
    # cost suggests is a legitimate choice, and the reasons for it are invisible
    # from here. Doing it unknowingly is the case worth catching.
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        schedule_is_more_frequent_than_recommended,
    )
    if hint and schedule_is_more_frequent_than_recommended(entry.analysis_id, entry.schedule):
        out["note"] = (
            f"This analysis is {hint['fetch_cost']}-fetch/{hint['compute_cost']}-compute; "
            f"{hint['recommended_schedule']} is usually often enough. "
            f"Running it {entry.schedule} is fine if you mean to."
        )
    return out
