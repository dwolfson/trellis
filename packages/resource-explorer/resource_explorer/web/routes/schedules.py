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


@router.get("/{entity_type}/{slug}")
def get_schedules(entity_type: str, slug: str) -> list[dict]:
    """Return all schedules configured for a resource."""
    return ProjectRegistry().get_schedules(entity_type, slug)


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
