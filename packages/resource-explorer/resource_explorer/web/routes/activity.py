"""Activity log API routes."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)

router = APIRouter()

RFA_STATUSES = {"open", "deferred", "reassigned", "completed"}

# docs/rfa-egeria-todo-followup.md — RE's own friendly verbs stay the wire
# contract this route (and the frontend drawer) speak; internally, from
# this map onward, everything is Egeria's real ToDoProperties.activityStatus
# vocabulary (pyegeria/core/_globals.py's ACTIVITY_STATUS) — one
# translation seam, at this boundary, not scattered across the stack.
_STATUS_TO_ACTIVITY_STATUS = {
    "open": "REQUESTED",
    "deferred": "WAITING",
    "reassigned": "REQUESTED",  # reassignment is an actor change, orthogonal to lifecycle status
    "completed": "COMPLETED",
}


class RfaActionUpdateRequest(BaseModel):
    status: str
    assignee: str = ""
    defer_until: str = ""
    resolution_note: str = ""


class RfaNoteRequest(BaseModel):
    notes: str


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
    """Return all RequestForAction annotations across all activity log entries.

    Each RFA gets a stable `id` (f"{entry_id}::{annotation_index}", minted
    positionally the same way every time this flattens the same entry's
    annotations) and has any locally-recorded response action
    (see PATCH /rfas/{rfa_id}) overlaid onto it: `rfa_status` (defaults to
    "open" if nothing's been recorded yet), `assignee`, `defer_until`,
    `resolution_note`, `action_updated_at`. `status` (Egeria/local
    provenance, e.g. "local") is unrelated and untouched — don't confuse
    the two."""
    registry = _registry()
    entries = registry.list_activity(entity_type=entity_type, entity_slug=entity_slug, limit=limit)
    overrides = registry.list_rfa_action_overrides()
    rfas = []
    for entry in entries:
        for idx, ann in enumerate(entry.get("annotations") or []):
            if "RequestForAction" in (ann.get("annotation_type") or ""):
                rfa_id = f"{entry['id']}::{idx}"
                override = overrides.get(rfa_id)
                rfas.append({
                    "id": rfa_id,
                    "entry_id": entry["id"],
                    "annotation_index": idx,
                    "ts": entry["ts"],
                    "entity_type": entry.get("entity_type", ""),
                    "entity_slug": entry.get("entity_slug", ""),
                    "entity_name": entry.get("entity_name", ""),
                    "annotation_type": ann.get("annotation_type", ""),
                    "analysis_name": ann.get("analysis_name", ""),
                    "count": ann.get("count", 1),
                    "summary": ann.get("summary", ""),
                    "status": ann.get("status", "local"),
                    "rfa_status": override["rfa_status"] if override else "open",
                    "assignee": override["assignee"] if override else "",
                    "defer_until": override["defer_until"] if override else "",
                    "resolution_note": override["resolution_note"] if override else "",
                    "notes": (override.get("notes") if override else "") or "",
                    "action_updated_at": override["updated_at"] if override else "",
                    # Egeria ToDo sync state (docs/rfa-egeria-todo-followup.md)
                    # — "" guid means never synced yet (or no response action
                    # taken at all); sync_error non-empty means the last
                    # attempt failed and scheduler.py's reconciliation pass
                    # will retry it.
                    "egeria_todo_guid": override["egeria_todo_guid"] if override else "",
                    "synced_at": override["synced_at"] if override else "",
                    "sync_error": override["sync_error"] if override else "",
                })
    return rfas


@router.patch("/rfas/{rfa_id}")
def update_rfa_action(rfa_id: str, body: RfaActionUpdateRequest) -> dict:
    """Record a response action (defer / reassign / complete / reopen) against
    an RFA. The local write (rfa_actions) is authoritative for this response
    regardless of Egeria's reachability — a real Egeria ToDo sync is then
    attempted, same request, non-blocking of this result (docs/rfa-egeria-
    todo-followup.md's "Sync mechanics"); a failed sync never fails this
    call, it just leaves the row for scheduler.py's reconciliation pass to
    retry."""
    if body.status not in RFA_STATUSES:
        raise HTTPException(status_code=400, detail=f"status must be one of {sorted(RFA_STATUSES)}")
    try:
        entry_id, idx_str = rfa_id.rsplit("::", 1)
        annotation_index = int(idx_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed rfa_id — expected '{entry_id}::{annotation_index}'")

    registry = _registry()
    if registry.get_activity(entry_id) is None:
        raise HTTPException(status_code=404, detail="No activity entry backs this RFA id")

    registry.upsert_rfa_action(
        rfa_id=rfa_id,
        entry_id=entry_id,
        annotation_index=annotation_index,
        status=body.status,
        activity_status=_STATUS_TO_ACTIVITY_STATUS[body.status],
        assignee=body.assignee,
        defer_until=body.defer_until,
        resolution_note=body.resolution_note,
    )

    try:
        from resource_explorer.rfa_egeria_sync import sync_rfa_action

        row = registry.get_rfa_action(rfa_id)
        if row is not None:
            sync_rfa_action(registry, row)
    except Exception as exc:
        # Belt-and-suspenders — sync_rfa_action itself never raises, but an
        # import/registry-lookup failure here still must not fail the
        # user's action (same non-blocking guarantee).
        log.warning("RFA Egeria sync skipped for %s: %s", rfa_id, exc)

    return {"status": "success", "id": rfa_id, "rfa_status": body.status}


@router.patch("/rfas/{rfa_id}/notes")
def update_rfa_note(rfa_id: str, body: RfaNoteRequest) -> dict:
    """Record free-text notes against an RFA, independent of any
    Defer/Reassign/Complete action. Real bug fixed 2026-08-16: the drawer's
    "Record answer" button previously never called this (or any) backend
    endpoint — it only wrote to a purely client-side, in-memory log, so
    nothing survived a page reload."""
    try:
        entry_id, idx_str = rfa_id.rsplit("::", 1)
        annotation_index = int(idx_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed rfa_id — expected '{entry_id}::{annotation_index}'")

    registry = _registry()
    if registry.get_activity(entry_id) is None:
        raise HTTPException(status_code=404, detail="No activity entry backs this RFA id")

    registry.upsert_rfa_note(rfa_id=rfa_id, entry_id=entry_id, annotation_index=annotation_index, notes=body.notes)

    try:
        from resource_explorer.rfa_egeria_sync import sync_rfa_note

        row = registry.get_rfa_action(rfa_id)
        if row is not None:
            sync_rfa_note(registry, row)
    except Exception as exc:
        # Non-blocking, same guarantee as the status route — a failed (or
        # not-yet-possible, no ToDo yet) note sync never fails this call.
        log.warning("RFA note Egeria sync skipped for %s: %s", rfa_id, exc)

    return {"status": "success", "id": rfa_id, "notes": body.notes}


@router.get("/{entry_id}")
def get_activity_entry(entry_id: str) -> dict:
    entry = _registry().get_activity(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="Activity entry not found")
    return entry
