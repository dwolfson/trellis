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


class RfaDismissRequest(BaseModel):
    """`reason` is validated by the registry against its own vocabulary
    (not_applicable / wont_do) rather than re-declared here — one list, so a
    third reason added later cannot be accepted by the route and then
    rejected by the store, or vice versa."""
    reason: str
    note: str = ""
    dismissed_by: str = ""


class RfaDismissalClearRequest(BaseModel):
    cleared_by: str = ""


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
    # Dismissed RFAs are returned like every other one, carrying `dismissed`
    # and the dismissal record — NEVER filtered out here. Dan asked for
    # "suppress with visibility": the drawer collapses them behind an
    # explicit "N suppressed" toggle, which it can only do if it is told
    # they exist. A server-side filter would make a suppressed finding
    # indistinguishable from one that never occurred, which is precisely the
    # absence-as-answer shape this codebase keeps getting bitten by.
    dismissals = registry.active_rfa_dismissals()
    rfas = []
    for entry in entries:
        for idx, ann in enumerate(entry.get("annotations") or []):
            if "RequestForAction" in (ann.get("annotation_type") or ""):
                # One row per REQUEST, not one per group.
                #
                # survey_report.summarise_annotations groups by
                # (step, annotation_type) — right for a compact activity
                # preview, wrong here. Three distinct requests from
                # SecurityHygieneCheck (no SECURITY.md, no CI config, no
                # licence) share both keys, so this used to emit ONE row
                # carrying count=3 and the first one's text: "Security
                # HygieneCheck 3 / No SECURITY.md found", with the other two
                # unreachable. That is Dan's original report, and the reason
                # the group now carries `items`.
                #
                # The sub-index is appended to rfa_id so each request keeps a
                # stable identity for PATCH and for dismissal. A group with
                # no items (an entry written before this change) still
                # yields its single row, so old entries do not vanish.
                members = ann.get("items") or [None]
                for sub, member in enumerate(members):
                    _emit_rfa(rfas, entry, ann, idx, sub, member,
                              len(members), overrides, dismissals, registry)
    return rfas


def _emit_rfa(rfas, entry, ann, idx, sub, member, n_members,
              overrides, dismissals, registry) -> None:
    """One RFA row. `member` is this request's own text when the group
    carried per-item detail, None when it did not."""
    rfa_id = f"{entry['id']}::{idx}" if n_members == 1 else f"{entry['id']}::{idx}::{sub}"
    override = overrides.get(rfa_id)
    # Content key, not rfa_id: a dismissal has to keep matching
    # across future survey runs, which mint new entry ids (see
    # the rfa_dismissals DDL in registry.py).
    dismissal_key = registry.rfa_dismissal_key(
        entry.get("entity_type", ""),
        entry.get("entity_slug", ""),
        ann.get("analysis_name", ""),
        # This request's OWN summary, not the group's first. Keying on the
        # group would make one dismissal suppress every sibling: marking
        # "No CI configuration detected" not-applicable would silently hide
        # "No SECURITY.md found" too.
        (member or ann).get("summary", "") or ann.get("summary", ""),
    )
    dismissal = dismissals.get(dismissal_key)
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
        "count": 1 if n_members > 1 else ann.get("count", 1),
        "summary": (member or ann).get("summary", "") or ann.get("summary", ""),
        # Carried from the annotation the summary came from
        # (survey_orchestrator.py's by_step grouping) — the
        # drawer showed only `summary` before this, and with ten
        # "SecurityHygieneCheck" RFAs sharing near-identical
        # summaries, that read as ten identical, unexplained
        # items. `explanation` says why it matters;
        # `action_requested`/`action_target_name` say what to do
        # and to what — RequestForActionAnnotation always carries
        # them (security_hygiene.py, file_size.py, etc.), they
        # just were never forwarded past the activity log.
        "explanation": (member or ann).get("explanation", ""),
        "action_requested": (member or ann).get("action_requested", ""),
        "action_target_name": (member or ann).get("action_target_name", ""),
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
        # Suppression state (docs/rfa-dismissals.md). `dismissal`
        # carries the whole record — reason, note, who, when —
        # so the drawer can say what was decided and by whom
        # rather than just hiding the row.
        "dismissal_key": dismissal_key,
        "dismissed": dismissal is not None,
        "dismissal": dismissal,
    })
    return rfas


@router.get("/rfas/dismissals")
def list_rfa_dismissals(include_cleared: bool = Query(False)) -> list[dict]:
    """Every recorded dismissal, newest first — the review surface behind
    Dan's "a future admin setting that allows you to reset or clear some of
    these decisions". `include_cleared=true` adds the ones already reversed,
    which stay in the table as history rather than being deleted."""
    return _registry().list_rfa_dismissals(include_cleared=include_cleared)


@router.post("/rfas/{rfa_id}/dismiss")
def dismiss_rfa(rfa_id: str, body: RfaDismissRequest) -> dict:
    """Suppress a finding as not-applicable / won't-do.

    Takes an `rfa_id` because that is what the drawer has in hand, but
    records against the finding's CONTENT (entity + analysis + summary),
    resolved here from the activity entry the id points at. That asymmetry
    is deliberate and is the whole point: the user dismisses the row in
    front of them, and the same finding stays dismissed when the next survey
    run produces it again under a new id."""
    registry = _registry()
    try:
        entry_id, idx_str = rfa_id.rsplit("::", 1)
        idx = int(idx_str)
    except ValueError:
        raise HTTPException(status_code=400, detail="Malformed rfa_id — expected '{entry_id}::{annotation_index}'")

    entry = registry.get_activity(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No activity entry {entry_id}")
    annotations = entry.get("annotations") or []
    if idx >= len(annotations):
        raise HTTPException(
            status_code=404,
            detail=f"Activity entry {entry_id} has no annotation at index {idx}",
        )
    ann = annotations[idx]

    try:
        row = registry.dismiss_rfa(
            entity_type=entry.get("entity_type", ""),
            entity_slug=entry.get("entity_slug", ""),
            analysis_name=ann.get("analysis_name", ""),
            summary_key=ann.get("summary", ""),
            reason=body.reason,
            note=body.note,
            created_by=body.dismissed_by,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "success", "id": rfa_id, "dismissal": row}


@router.post("/rfas/dismissals/{dismissal_id}/clear")
def clear_rfa_dismissal(dismissal_id: str, body: RfaDismissalClearRequest) -> dict:
    """Reverse a dismissal. The row survives with cleared_at/cleared_by set,
    so "we decided this was not applicable, then changed our mind" stays
    readable — an undelete would lose both halves of that."""
    row = _registry().clear_rfa_dismissal(dismissal_id, cleared_by=body.cleared_by)
    if row is None:
        raise HTTPException(status_code=404, detail=f"No dismissal {dismissal_id}")
    return {"status": "success", "dismissal": row}


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
