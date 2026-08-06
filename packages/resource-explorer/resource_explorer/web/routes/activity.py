"""Activity log API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from resource_explorer.registry import ProjectRegistry

router = APIRouter()


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


@router.get("/")
def list_activity(
    entity_type: str | None = Query(None),
    intent: str | None = Query(None),
    operation: str | None = Query(None),
    status: str | None = Query(None),
    since: str | None = Query(None),
    limit: int = Query(200, le=1000),
) -> list[dict]:
    return _registry().list_activity(
        entity_type=entity_type,
        intent=intent,
        operation=operation,
        status=status,
        since=since,
        limit=limit,
    )


@router.get("/rfas")
def list_rfas(
    entity_type: str | None = Query(None),
    entity_slug: str | None = Query(None),
    limit: int = Query(500, le=2000),
) -> list[dict]:
    """Return all RequestForAction annotations across all activity log entries."""
    entries = _registry().list_activity(entity_type=entity_type, entity_slug=entity_slug, limit=limit)
    rfas = []
    for entry in entries:
        for ann in (entry.get("annotations") or []):
            if "RequestForAction" in (ann.get("annotation_type") or ""):
                rfas.append({
                    "entry_id": entry["id"],
                    "ts": entry["ts"],
                    "entity_type": entry.get("entity_type", ""),
                    "entity_slug": entry.get("entity_slug", ""),
                    "entity_name": entry.get("entity_name", ""),
                    "annotation_type": ann.get("annotation_type", ""),
                    "analysis_name": ann.get("analysis_name", ""),
                    "count": ann.get("count", 1),
                    "summary": ann.get("summary", ""),
                    "status": ann.get("status", "local"),
                })
    return rfas


@router.get("/{entry_id}")
def get_activity_entry(entry_id: str) -> dict:
    entry = _registry().get_activity(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Activity entry not found")
    return entry
