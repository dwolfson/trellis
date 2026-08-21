"""Automate — Part 4 of docs/discovery-automate-project-context-plan.md,
the 8th canonical intent. Local-first subscriptions: RE's own scheduler.py
does detection (comparing an analysis_id's latest two runs), RFA does
delivery. See notification_subscriptions' own table docstring in
registry.py for why this doesn't create real Egeria NotificationType
elements yet.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

router = APIRouter()


class SubscriptionData(BaseModel):
    id: int
    entity_type: str
    entity_slug: str
    analysis_id: str
    label: str = ""
    active: bool
    created_at: str
    last_checked_at: str = ""
    last_notified_at: str = ""
    notification_count: int = 0
    egeria_notification_type_guid: str = ""
    egeria_notification_type_qualified_name: str = ""
    # Whether an enabled, recurring schedule exists for this exact
    # (entity, analysis_id). Detection only ever runs off a scheduled
    # completion, so a subscription without one can never fire — see
    # scheduler._check_subscriptions. Carried on every row because the warning
    # has to be visible whenever the subscription is, not only at the moment it
    # was created.
    has_schedule: bool = True

    @classmethod
    def from_row(cls, row: dict, has_schedule: bool = True) -> "SubscriptionData":
        return cls(**{**row, "active": bool(row["active"]), "has_schedule": has_schedule})


def _scheduled_pairs(registry) -> set[tuple[str, str, str]]:
    """(entity_type, entity_slug, analysis_id) that have a live recurring schedule.

    "manual" counts as no schedule: it never recurs, so nothing ever completes on
    a cadence for detection to compare against.
    """
    return {
        (s.get("entity_type", ""), s.get("entity_slug", ""), s.get("analysis_id", ""))
        for s in registry.list_all_schedules()
        if s.get("enabled") and (s.get("schedule") or "manual") != "manual"
    }


class CreateSubscriptionRequest(BaseModel):
    entity_type: str
    entity_slug: str
    analysis_id: str
    label: str = ""


@router.get("/subscriptions", response_model=list[SubscriptionData])
def list_subscriptions(
    entity_type: str | None = None,
    entity_slug: str | None = None,
    analysis_id: str | None = None,
    active_only: bool = False,
) -> list[SubscriptionData]:
    registry = ProjectRegistry()
    rows = registry.list_subscriptions(
        entity_type=entity_type, entity_slug=entity_slug, analysis_id=analysis_id, active_only=active_only,
    )
    scheduled = _scheduled_pairs(registry)
    return [
        SubscriptionData.from_row(
            r, (r["entity_type"], r["entity_slug"], r["analysis_id"]) in scheduled)
        for r in rows
    ]


@router.post("/subscriptions", response_model=SubscriptionData)
def create_subscription(req: CreateSubscriptionRequest) -> SubscriptionData:
    registry = ProjectRegistry()
    if req.entity_type == "repo" and not registry.get(req.entity_slug):
        raise HTTPException(status_code=404, detail=f"Repo '{req.entity_slug}' not found")
    row = registry.create_subscription(req.entity_type, req.entity_slug, req.analysis_id, req.label)
    return SubscriptionData.from_row(
        row, (req.entity_type, req.entity_slug, req.analysis_id) in _scheduled_pairs(registry))


@router.post("/subscriptions/{subscription_id}/activate", response_model=SubscriptionData)
def activate_subscription(subscription_id: int) -> SubscriptionData:
    registry = ProjectRegistry()
    if not registry.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    registry.set_subscription_active(subscription_id, True)
    row = registry.get_subscription(subscription_id)
    return SubscriptionData.from_row(
        row, (row["entity_type"], row["entity_slug"], row["analysis_id"]) in _scheduled_pairs(registry))


@router.post("/subscriptions/{subscription_id}/deactivate", response_model=SubscriptionData)
def deactivate_subscription(subscription_id: int) -> SubscriptionData:
    registry = ProjectRegistry()
    if not registry.get_subscription(subscription_id):
        raise HTTPException(status_code=404, detail="Subscription not found")
    registry.set_subscription_active(subscription_id, False)
    row = registry.get_subscription(subscription_id)
    return SubscriptionData.from_row(
        row, (row["entity_type"], row["entity_slug"], row["analysis_id"]) in _scheduled_pairs(registry))
