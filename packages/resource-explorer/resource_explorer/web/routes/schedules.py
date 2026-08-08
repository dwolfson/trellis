"""Resource schedule API — store and retrieve analysis schedules per resource."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

router = APIRouter()

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
    return ProjectRegistry().list_all_schedules()


@router.get("/{entity_type}/{slug}")
def get_schedules(entity_type: str, slug: str) -> list[dict]:
    """Return all schedules configured for a resource."""
    return ProjectRegistry().get_schedules(entity_type, slug)


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
    return {"status": "ok", "entity_type": entity_type, "entity_slug": slug,
            "analysis_id": entry.analysis_id, "schedule": entry.schedule, "enabled": entry.enabled}
