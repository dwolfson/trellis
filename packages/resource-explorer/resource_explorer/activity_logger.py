"""Convenience helpers for writing activity log entries."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from resource_explorer.registry import ActivityEntry

if TYPE_CHECKING:
    from resource_explorer.registry import ProjectRegistry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_survey(
    registry: "ProjectRegistry",
    entity_type: str,
    entity_slug: str,
    entity_name: str,
    entity_location: str,
    intent: str,
    status: str,
    summary: str,
    detail: str = "",
    items: list[dict] | None = None,
    annotations: list[dict] | None = None,
) -> str:
    entry_id = str(uuid.uuid4())
    registry.write_activity(ActivityEntry(
        id=entry_id,
        ts=_now(),
        operation="survey",
        intent=intent,
        entity_type=entity_type,
        entity_slug=entity_slug,
        entity_name=entity_name,
        entity_location=entity_location,
        status=status,
        summary=summary,
        detail=detail,
        items=items or [],
        annotations=annotations or [],
    ))
    return entry_id


def log_catalog(
    registry: "ProjectRegistry",
    entity_type: str,
    entity_slug: str,
    entity_name: str,
    entity_location: str,
    status: str,
    summary: str,
    detail: str = "",
    items: list[dict] | None = None,
) -> str:
    entry_id = str(uuid.uuid4())
    registry.write_activity(ActivityEntry(
        id=entry_id,
        ts=_now(),
        operation="catalog",
        intent="assessment",
        entity_type=entity_type,
        entity_slug=entity_slug,
        entity_name=entity_name,
        entity_location=entity_location,
        status=status,
        summary=summary,
        detail=detail,
        items=items or [],
        annotations=[],
    ))
    return entry_id


def log_rfa(
    registry: "ProjectRegistry",
    entity_type: str,
    entity_slug: str,
    entity_name: str,
    status: str,
    summary: str,
    detail: str = "",
    analysis_name: str = "",
) -> str:
    """Write an RFA and make sure it actually reaches the RFA drawer.

    The drawer is fed by GET /api/activity/rfas, which flattens activity entries
    and keeps only *annotations* whose annotation_type contains
    "RequestForAction". It does not look at operation="rfa" at all. This function
    wrote the entry with an empty annotations list, so every RFA it produced was
    invisible there — the entry existed in the activity log, and the surface
    built to act on it never showed it.

    That affected all three callers: Automate's change notifications
    (scheduler.py), Enrichment's context requests (web/routes/context.py), and
    Egeria linkage divergences (egeria_linkage.py). Each is a request for a human
    action that no human was shown.

    The annotation carries the same summary as the entry rather than a different
    one: the drawer reads the annotation's, the activity log reads the entry's,
    and two texts drifting apart for one event would be worse than the
    duplication.
    """
    entry_id = str(uuid.uuid4())
    registry.write_activity(ActivityEntry(
        id=entry_id,
        ts=_now(),
        operation="rfa",
        intent="enrichment",
        entity_type=entity_type,
        entity_slug=entity_slug,
        entity_name=entity_name,
        entity_location="",
        status=status,
        summary=summary,
        detail=detail,
        annotations=[{
            # The exact type string GET /api/activity/rfas substring-matches on,
            # and the same one EgeriaPublisher uses for a published RFA.
            "annotation_type": "RequestForActionAnnotation",
            "analysis_name": analysis_name or "Request for action",
            "count": 1,
            "summary": summary,
            "status": status,
        }],
    ))
    return entry_id


def log_scout(
    registry: "ProjectRegistry",
    entity_type: str,
    entity_slug: str,
    entity_name: str,
    entity_location: str,
    status: str,
    summary: str,
    detail: str = "",
) -> str:
    entry_id = str(uuid.uuid4())
    registry.write_activity(ActivityEntry(
        id=entry_id,
        ts=_now(),
        operation="scout",
        intent="scouting",
        entity_type=entity_type,
        entity_slug=entity_slug,
        entity_name=entity_name,
        entity_location=entity_location,
        status=status,
        summary=summary,
        detail=detail,
    ))
    return entry_id
