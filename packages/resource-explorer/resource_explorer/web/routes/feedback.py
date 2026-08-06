"""Product/UI feedback endpoints — public submission, admin-only triage.

Route path is deliberately /api/feedback, not /api/demo-feedback (the
Portal source's path) — RE has no "demo" concept, so keeping that prefix
would be misleading, not a faithful port.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from resource_explorer.config import get_config
from resource_explorer.feedback_store import (
    FeedbackEntry,
    FeedbackStore,
    VALID_CATEGORIES,
    VALID_TRIAGE_STATUSES,
)
from resource_explorer.web.admin_auth import is_admin_request

router = APIRouter()


class FeedbackSubmission(BaseModel):
    session_id: str = ""
    page: str = ""
    element_guid: str = ""
    rating: int | None = None
    category: str = ""
    message: str = ""
    email: str = ""
    wants_response: bool = False
    consent_to_contact: bool = False
    build_version: str = ""
    user_agent: str = ""
    viewport: str = ""
    locale: str = ""


class TriageUpdate(BaseModel):
    triage_status: str


def _require_admin(request: Request) -> None:
    cfg = get_config().feedback
    if not is_admin_request(request, cfg):
        raise HTTPException(status_code=403, detail="Admin credential required")


@router.post("")
async def submit_feedback(payload: FeedbackSubmission) -> dict:
    if payload.rating is not None and not (1 <= payload.rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be 1-5")
    if payload.category and payload.category not in VALID_CATEGORIES:
        raise HTTPException(status_code=400, detail=f"Invalid category: {payload.category!r}")

    store = FeedbackStore()
    entry = FeedbackEntry(
        session_id=payload.session_id,
        page=payload.page,
        element_guid=payload.element_guid,
        rating=payload.rating,
        category=payload.category,
        message=payload.message,
        email=payload.email,
        wants_response=payload.wants_response,
        consent_to_contact=payload.consent_to_contact,
        build_version=payload.build_version,
        user_agent=payload.user_agent,
        viewport=payload.viewport,
        locale=payload.locale,
    )
    store.add(entry)
    return {"status": "ok"}


@router.get("")
async def list_feedback(
    request: Request, triage_status: str | None = None, limit: int = 200
) -> list[dict]:
    _require_admin(request)
    if triage_status is not None and triage_status not in VALID_TRIAGE_STATUSES:
        raise HTTPException(status_code=400, detail=f"Invalid triage_status: {triage_status!r}")
    store = FeedbackStore()
    return store.list(triage_status=triage_status, limit=limit)


@router.get("/stats")
async def feedback_stats(request: Request) -> dict:
    _require_admin(request)
    store = FeedbackStore()
    return store.stats()


@router.patch("/{feedback_id}")
async def triage_feedback(feedback_id: str, payload: TriageUpdate, request: Request) -> dict:
    _require_admin(request)
    if payload.triage_status not in VALID_TRIAGE_STATUSES:
        raise HTTPException(
            status_code=400, detail=f"Invalid triage_status: {payload.triage_status!r}"
        )
    store = FeedbackStore()
    updated = store.update_triage_status(feedback_id, payload.triage_status)
    if updated is None:
        raise HTTPException(status_code=404, detail="Feedback record not found")
    return updated
