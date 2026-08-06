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
) -> str:
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
