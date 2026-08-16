"""RFA -> Egeria ToDo sync (docs/rfa-egeria-todo-followup.md).

The RFA drawer's defer/reassign/complete/reopen actions write a local
`rfa_actions` row first (authoritative for the API response, never blocked
on Egeria's reachability) and then attempt to create/update a real Egeria
`ToDo` behind it — same non-blocking try/except/log shape as
`egeria_publisher.py`'s activity-log write, since a failed Egeria call must
never fail the user's local action.

Unlike the activity log (a pure audit trail that can afford "log and
forget"), RFA/ToDo state is live workflow truth both systems must agree on
— `scheduler.py`'s background loop runs `reconcile_rfa_actions()` every
iteration to retry failed writes and pull in changes made by other Egeria
clients, closing the gap a one-shot sync attempt alone would leave.

Real, standing limitation (docs/rfa-egeria-todo-followup.md open question
#1, not solved here): RE has no per-user identity yet, so `reassign_action`
(which needs a real actor GUID) is never called — `assignee` stays a local
free-text field only until that's solved. Also not attempted: linking the
ToDo to the RFA's own Egeria Annotation element via `add_action_target` —
today's local RFAs are flattened from `activity_log` rows and don't
reliably carry a real Egeria annotation GUID to link against.
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# Same standard pyegeria env vars / defaults egeria_publisher.py uses —
# kept in sync deliberately (one Egeria connection story across this
# codebase), not re-derived independently.
_DEFAULT_PLATFORM_URL = "https://localhost:9443"
_DEFAULT_VIEW_SERVER = "qs-view-server"
_DEFAULT_USER = "erinoverview"
_DEFAULT_PASSWORD = "secret"


def _egeria_connection_kwargs() -> tuple[str, str, str, str]:
    platform_url = os.getenv("EGERIA_PLATFORM_URL", _DEFAULT_PLATFORM_URL)
    view_server = os.getenv("EGERIA_VIEW_SERVER", _DEFAULT_VIEW_SERVER)
    user_id = os.getenv("EGERIA_USER", _DEFAULT_USER)
    user_password = os.getenv("EGERIA_USER_PASSWORD", _DEFAULT_PASSWORD)
    return view_server, platform_url, user_id, user_password


def _get_clients():
    """Construct (MyProfile, MetadataExpert) clients, bearer-tokened —
    MyProfile subclasses AssetMaker (pyegeria/omvs/my_profile.py), so it
    already has create_my_todo/get_my_to_dos AND assign_action/
    reassign_action/add_action_target in one client; MetadataExpert is the
    separate generic property-update surface (update_metadata_element_
    properties) neither ToDo-specific class exposes a dedicated method for."""
    from pyegeria import MetadataExpert, MyProfile

    view_server, platform_url, user_id, user_password = _egeria_connection_kwargs()
    my_profile = MyProfile(view_server, platform_url, user_id, user_password)
    my_profile.create_egeria_bearer_token(user_id, user_password)
    metadata_expert = MetadataExpert(view_server, platform_url, user_id, user_password)
    metadata_expert.create_egeria_bearer_token(user_id, user_password)
    return my_profile, metadata_expert


def _primitive_value(type_name: str, value) -> dict:
    return {"class": "PrimitiveTypePropertyValue", "typeName": type_name, "primitiveValue": value}


def _enum_value(type_name: str, symbolic_name: str) -> dict:
    return {"class": "EnumTypePropertyValue", "typeName": type_name, "symbolicName": symbolic_name}


def _date_to_epoch_millis(date_str: str) -> int | None:
    """Egeria date-typed properties (dueTime/startTime/requestedTime) are
    epoch-millisecond integers on the wire — confirmed live 2026-08-16 via
    a real GET (requestedTime came back as e.g. 1786905548706), NOT ISO
    date strings. Accepts a bare date (YYYY-MM-DD, what the drawer's
    <input type="date"> sends) or a full ISO datetime; returns None on
    anything unparseable rather than raising, so a malformed date degrades
    to "field omitted," not a whole sync failure."""
    from datetime import datetime, timezone

    try:
        dt = datetime.fromisoformat(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp() * 1000)
    except ValueError:
        return None


def sync_rfa_action(registry, rfa_row: dict) -> None:
    """Attempt to create (first time) or update (subsequent) the Egeria
    ToDo behind one rfa_actions row. Never raises — every failure is caught,
    logged, and recorded via registry.mark_rfa_sync_error so the write-
    direction reconciliation pass can retry it later.

    Real bug found and fixed during live verification (2026-08-16): the
    update path previously sent a `{"class": "ToDoProperties",
    "activityStatus": "WAITING", ...}` body — that shape only works for
    create_my_todo()'s own convenience wrapper (which does its own
    server-side property construction from those exact kwargs).
    update_metadata_element_properties() is the fully generic
    metadata-element endpoint — its real wire contract (confirmed via
    _async_update_metadata_element_properties()'s own docstring, and via a
    live round-trip that silently no-opped against the wrong shape) is
    `properties: {"class": "ElementProperties", "propertyValueMap": {...}}`
    with each value individually typed (EnumTypePropertyValue for
    activityStatus, PrimitiveTypePropertyValue for priority, date-typed
    PrimitiveTypePropertyValue — an epoch-millis int, not an ISO string —
    for dueTime/startTime). The previous shape was accepted (no HTTP
    error) and silently changed nothing — worth remembering: a 200 from
    this endpoint is not proof the update actually landed.
    """
    rfa_id = rfa_row.get("id", "")
    try:
        my_profile, metadata_expert = _get_clients()
        todo_guid = rfa_row.get("egeria_todo_guid") or ""

        if not todo_guid:
            todo_guid = my_profile.create_my_todo(
                todo_name=f"RFA: {rfa_id}",
                activity_status=rfa_row.get("activity_status") or "REQUESTED",
                description=rfa_row.get("resolution_note") or "",
                priority=rfa_row.get("priority") or 0,
            )
        else:
            property_value_map = {
                "activityStatus": _enum_value("ActivityStatus", rfa_row.get("activity_status") or "REQUESTED"),
                "priority": _primitive_value("int", rfa_row.get("priority") or 0),
            }
            # dueTime/startTime only meaningful when actually set (omitting
            # them, not sending an empty/zero value, avoids clearing a real
            # due date on the Egeria side that this sync didn't intend to
            # touch) — skipped entirely (not sent as null) when unparseable.
            if rfa_row.get("due_time"):
                millis = _date_to_epoch_millis(rfa_row["due_time"])
                if millis is not None:
                    property_value_map["dueTime"] = _primitive_value("date", millis)
            if rfa_row.get("start_time"):
                millis = _date_to_epoch_millis(rfa_row["start_time"])
                if millis is not None:
                    property_value_map["startTime"] = _primitive_value("date", millis)

            body = {
                "class": "UpdatePropertiesRequestBody",
                "properties": {
                    "class": "ElementProperties",
                    "propertyValueMap": property_value_map,
                },
                "replaceProperties": False,
            }
            metadata_expert.update_metadata_element_properties(todo_guid, body)

        registry.mark_rfa_synced(rfa_id, todo_guid)
    except Exception as exc:
        log.warning("Could not sync RFA %s to Egeria: %s", rfa_id, exc)
        try:
            registry.mark_rfa_sync_error(rfa_id, str(exc))
        except Exception:
            log.exception("Could not even record RFA sync error for %s", rfa_id)


def sync_rfa_note(registry, rfa_row: dict) -> None:
    """Push this RFA's current notes text to Egeria as an ActivityEntry,
    linked to the RFA's own ToDo — per direct decision (2026-08-16), only
    attempted once the ToDo already exists (egeria_todo_guid set); a note
    added before any status action has nothing to link against yet, and
    picks up automatically on the next reconciliation pass once one exists.
    Never raises — same non-blocking try/except/log shape as
    sync_rfa_action.

    One ActivityEntry per distinct note text (never edited in place) —
    matches docs/rfa-egeria-todo-followup.md's "Related, broader idea"
    section: status-change-style logging is naturally append-only, and
    sidesteps update_note's known-broken server-side behavior (egeria-python
    PYEGERIA_ISSUES.md ISSUE-30) entirely rather than working around it.
    notes_synced_value is the dedup key — an unchanged note is never
    re-pushed as a duplicate entry.
    """
    rfa_id = rfa_row.get("id", "")
    todo_guid = rfa_row.get("egeria_todo_guid") or ""
    notes = rfa_row.get("notes") or ""
    if not todo_guid or not notes or notes == (rfa_row.get("notes_synced_value") or ""):
        return
    try:
        my_profile, _ = _get_clients()
        notelog_guid = rfa_row.get("egeria_notelog_guid") or ""
        if not notelog_guid:
            notelog_guid = my_profile.create_note_log(
                element_guid=todo_guid,
                display_name=f"RFA notes: {rfa_id}",
                description="Notes recorded against this RFA from Resource Explorer.",
            )
            registry.mark_rfa_notelog(rfa_id, notelog_guid)

        my_profile.create_note(
            notelog_guid,
            associated_element=todo_guid,
            body={
                "class": "NoteProperties",
                "typeName": "ActivityEntry",
                "qualifiedName": my_profile.make_feedback_qn("ActivityEntry", todo_guid),
                "description": notes,
            },
        )
        registry.mark_rfa_note_synced(rfa_id, notes)
    except Exception as exc:
        log.warning("Could not sync RFA note %s to Egeria: %s", rfa_id, exc)
        try:
            registry.mark_rfa_note_sync_error(rfa_id, str(exc))
        except Exception:
            log.exception("Could not even record RFA note sync error for %s", rfa_id)


# ToDos in one of these states are still "open" from RE's point of view —
# used to bound the read-direction reconciliation pull below. Deliberately
# excludes ABANDONED/CANCELLED/INVALID/OTHER (Egeria's own ACTIVITY_STATUS
# vocabulary, pyegeria/core/_globals.py) — a ToDo another client moved into
# one of those isn't something this pass currently reconciles back in,
# since RE's local vocabulary has no equivalent to distinguish them from a
# plain "completed".
_OPEN_ACTIVITY_STATUSES = ["REQUESTED", "APPROVED", "WAITING", "ACTIVATING", "IN_PROGRESS", "PAUSED", "FOR_INFO"]


def _extract_todo_fields(raw: dict) -> dict | None:
    """Defensively pull {guid, activity_status, due_time, start_time,
    priority} out of one element of get_my_to_dos()'s JSON output. The
    exact nested shape (properties vs. top-level, elementHeader.guid vs.
    guid) hasn't been live-confirmed against a real Egeria response as of
    this writing — this tries the plausible shapes and returns None (skip,
    don't crash the reconciliation pass) rather than guessing wrong."""
    try:
        header = raw.get("elementHeader") or {}
        guid = header.get("guid") or raw.get("guid") or ""
        if not guid:
            return None
        props = raw.get("properties") or raw
        return {
            "guid": guid,
            "activity_status": props.get("activityStatus", ""),
            "due_time": props.get("dueTime") or "",
            "start_time": props.get("startTime") or "",
            "priority": props.get("priority") or 0,
        }
    except Exception:
        return None


def reconcile_rfa_actions(registry) -> None:
    """One reconciliation pass, both directions (sync mechanics, point 3):

    - Write direction: retry every row that's never synced or whose last
      sync attempt failed.
    - Read direction: pull the caller's open ToDos and, for every already-
      linked local row whose remote state differs, overwrite the local
      fields with what Egeria has — catching changes made by another
      Egeria client, not just RE's own drawer.

    Called from scheduler.py's background loop, once per iteration —
    reuses that existing loop rather than starting a second one (sync
    mechanics, point 3's own framing). Never raises — every real failure
    (a single row's sync, or the bulk pull itself) is caught and logged so
    one bad row/one Egeria hiccup doesn't stop the rest of the pass or the
    scheduler iteration it's part of.
    """
    try:
        for row in registry.list_unsynced_rfa_actions():
            sync_rfa_action(registry, row)
    except Exception:
        log.exception("RFA reconciliation: write-direction retry pass failed")

    try:
        for row in registry.list_unsynced_rfa_notes():
            sync_rfa_note(registry, row)
    except Exception:
        log.exception("RFA reconciliation: note write-direction retry pass failed")

    try:
        synced = registry.list_synced_rfa_actions()
        if not synced:
            return
        my_profile, _ = _get_clients()
        remote_todos = my_profile.get_my_to_dos(activity_status_list=_OPEN_ACTIVITY_STATUSES)
        if not isinstance(remote_todos, list):
            log.warning("RFA reconciliation: get_my_to_dos returned %s, expected a list", type(remote_todos))
            return

        remote_by_guid: dict[str, dict] = {}
        for raw in remote_todos:
            fields = _extract_todo_fields(raw)
            if fields:
                remote_by_guid[fields["guid"]] = fields

        for local in synced:
            remote = remote_by_guid.get(local["egeria_todo_guid"])
            if remote is None:
                continue  # not in the "still open" set — a closed/cancelled/etc. ToDo; leave local as-is
            changed = (
                remote["activity_status"] != local.get("activity_status")
                or remote["due_time"] != (local.get("due_time") or "")
                or remote["start_time"] != (local.get("start_time") or "")
                or remote["priority"] != (local.get("priority") or 0)
            )
            if changed:
                try:
                    registry.update_rfa_from_remote(
                        local["id"], remote["activity_status"],
                        remote["due_time"], remote["start_time"], remote["priority"],
                    )
                except Exception:
                    log.exception("RFA reconciliation: could not apply remote update for %s", local["id"])
    except Exception:
        log.exception("RFA reconciliation: read-direction pull failed")
