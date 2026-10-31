"""D1-b: the database-level press. Add the content pack's schemas to RE's database element (design §10, §12).

DESIGN-ADOPT-BY-ENDPOINT-D1-2026-10-30.md. The owner (2026-10-31, coordinator relay): "yes, database level is what I
meant - go". One press adds one DataSetContent relationship from RE's database element to each other-family schema
at the same endpoint that is not yet its member: for coco_pharma, c990f349 and the pack's 22 schemas, 26 members
after. Only adding: no property of the pack's elements changes and nothing is deleted.

The rules this module keeps:

- **Re-read right before writing.** The plan the person saw is not trusted: the endpoint is resolved again (no
  cache) and RE's database element's links are read again, so a schema already a member, from a second press, a
  retry or anyone else, is skipped and a link is never doubled (DataSetContent is multi-link: Egeria would accept a
  second one).
- **The relationship type and its ends are read**, off the links RE's database already has to its own schemas
  (`endpoint_identity.database_row`): never guessed. Without both, nothing is written.
- **One press per database at a time** (`PressBusy`).
- **Read back by relationship.** pyegeria's `link_data_set_content` returns no GUID, so after the writes the
  database's links are read once more: a link is "added" only when that read shows it, with its relationship GUID.
- **One proof row** (`reanchor_database_link`) lists every relationship added, by GUID, with the undo: each one can be
  removed alone with `AssetMaker.detach_data_set_content_relationship(<relationship GUID>)`, which detaches that one
  relationship and nothing else (docs/design-notes/D1B-DATABASE-LINK-PRESS-UNDO.md).
- **Partial failure names the schemas** that failed, in Egeria's words, and never says "failed" for the whole press
  when some links were added.
"""
from __future__ import annotations

import logging
import threading
from datetime import UTC, datetime

from resource_explorer import endpoint_identity as ei
from resource_explorer.catalogue_gateway import GatewayError

log = logging.getLogger(__name__)

PROOF_KIND = "reanchor_database_link"
UNDO_CALL = "AssetMaker.detach_data_set_content_relationship"
UNDO_NOTE = (f"to undo, remove each relationship listed here by its GUID with {UNDO_CALL}(<relationship GUID>): "
             "it detaches that one DataSetContent and nothing else (the pack's schemas and RE's database stay)")

ADDED, PARTLY, NOTHING_ADDED, NOTHING_TO_ADD = "added", "partly_added", "nothing_added", "nothing_to_add"


class PressRefused(Exception):
    """The press cannot go ahead; nothing was written. `status` is the HTTP status the route answers with."""

    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.message, self.status = message, status


class PressBusy(PressRefused):
    def __init__(self):
        super().__init__("a press for this database is already running · wait for it, then read Egeria again", 409)


_running: set[str] = set()
_running_lock = threading.Lock()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _links_to(gateway, database_guid: str, link_type: str, schema_end: int) -> dict[str, list[str]]:
    """schema GUID -> the relationship GUIDs of `link_type` between RE's database and it, with the schema at the
    end the plan read. Raises GatewayError when the read cannot be made."""
    out: dict[str, list[str]] = {}
    for r in gateway.relationships(database_guid):
        if r.type_name == link_type and r.other_type == ei.SCHEMA_TYPE and \
                r.other_at_end1 is (schema_end == 1):
            out.setdefault(r.other_guid, []).append(r.guid)
    return out


def press_words(state: str, *, added: list[dict], failed: list[dict], unverified: list[dict], to_add: int,
                members_after: int | None, database_guid: str, link_type: str) -> str:
    db = database_guid[:8]
    tail = f" · read back: {members_after} members" if members_after is not None else " · not read back"
    if state == NOTHING_TO_ADD:
        return f"nothing to add · every other-family schema is already a {link_type} member of {db}{tail}"
    parts = []
    if added:
        parts.append(f"added {len(added)} of {to_add} schema{'s' if to_add != 1 else ''} to {db} ({link_type})")
    if failed:
        parts.append(f"{len(failed)} not added: " + "; ".join(f"{f['schema']} ({f['error']})" for f in failed))
    if unverified:
        parts.append(f"{len(unverified)} sent but not seen on the read-back: "
                     + ", ".join(u["schema"] for u in unverified))
    head = "nothing added · " if state == NOTHING_ADDED else ""
    return head + " · ".join(parts) + tail


def press(registry, gateway, db_entity, *, by: str) -> dict:
    """Run the press for one database; returns {state, words, added, failed, unverified, skipped_present, plan}.
    Raises PressRefused (nothing written) when there is no database-level row, its type or ends were not read, or a
    press for this database is running."""
    slug = db_entity.slug
    with _running_lock:
        if slug in _running:
            raise PressBusy()
        _running.add(slug)
    try:
        return _press(registry, gateway, db_entity, by=by)
    finally:
        with _running_lock:
            _running.discard(slug)


def _press(registry, gateway, db_entity, *, by: str) -> dict:
    slug = db_entity.slug
    res = ei.resolve(gateway, db_entity)                      # never the cache: the plan is re-read now
    if res.get("error"):
        raise PressRefused(f"could not read Egeria for this database's endpoint · nothing written · {res['error']}",
                           503)
    plan = ei.reanchor_plan(gateway, db_entity, res, rule_proofs=registry.latest_quality_rule_proofs(slug))
    row = (plan or {}).get("database_row")
    if not row:
        raise PressRefused("no database-level row in the plan · nothing to press · nothing written")
    if plan.get("read_error"):
        raise PressRefused(f"RE's database element could not be read · nothing written · {plan['read_error']}", 503)
    link_type, schema_end = row["link_type"], row.get("schema_end")
    if link_type == ei.NOT_READ or schema_end not in (1, 2):
        raise PressRefused(f"{row['words']} · nothing written")
    database_guid = row["re_guid"]
    try:
        before = _links_to(gateway, database_guid, link_type, schema_end)
    except GatewayError as exc:
        raise PressRefused(f"RE's database element's links could not be read · nothing written · {exc}", 503) from exc
    todo = [x for x in row["to_add"] if x["guid"] not in before]
    skipped = [x for x in row["to_add"] if x["guid"] in before]
    if not todo:
        detail = {"database_guid": database_guid, "link_type": link_type, "schema_end": schema_end,
                  "added": [], "failed": [], "unverified": [], "skipped_present": skipped, "members_after": len(before)}
        words = press_words(NOTHING_TO_ADD, added=[], failed=[], unverified=[], to_add=0,
                            members_after=len(before), database_guid=database_guid, link_type=link_type)
        log.info("reanchor_press slug=%s nothing to add · %s", slug, words)
        ei.record_resolution(registry, gateway, db_entity, by=by)
        return {"state": NOTHING_TO_ADD, "words": words, **detail}
    log.info("reanchor_press slug=%s database=%s type=%s schema_end=%d to_add=%d by=%s", slug, database_guid,
             link_type, schema_end, len(todo), by)
    sent, failed = [], []
    for x in todo:
        data_set, content = (x["guid"], database_guid) if schema_end == 1 else (database_guid, x["guid"])
        try:
            gateway.link_data_set_content(data_set, content)
            sent.append(x)
        except GatewayError as exc:
            failed.append({**x, "error": str(exc)[:300]})
    try:
        after = _links_to(gateway, database_guid, link_type, schema_end)
        read_back = True
    except GatewayError as exc:
        after, read_back = {}, False
        log.warning("reanchor_press slug=%s read-back failed: %s", slug, exc)
    added, unverified = [], []
    for x in sent:
        new = [g for g in after.get(x["guid"], []) if g not in before.get(x["guid"], [])]
        if read_back and new:
            added.append({**x, "relationship_guid": new[0], "relationship_guids": new})
        else:
            unverified.append(x)
    members_after = len(after) if read_back else None
    state = ADDED if added and not failed and not unverified else PARTLY if added else NOTHING_ADDED
    words = press_words(state, added=added, failed=failed, unverified=unverified, to_add=len(todo),
                        members_after=members_after, database_guid=database_guid, link_type=link_type)
    detail = {"database_guid": database_guid, "link_type": link_type, "schema_end": schema_end, "added": added,
              "failed": failed, "unverified": unverified, "skipped_present": skipped, "members_before": len(before),
              "members_after": members_after, "words": words, "undo": UNDO_NOTE, "pressed_at": _now()}
    registry.append_catalogue_commit_proof(slug, proof=PROOF_KIND, node_kind="database", element_guid=database_guid,
                                           recorded_by=by, detail=detail)
    for a in added:
        log.info("reanchor_press slug=%s added relationship=%s schema=%s (%s) · undo: %s(%s)", slug,
                 a["relationship_guid"], a["guid"], a["schema"], UNDO_CALL, a["relationship_guid"])
    log.info("reanchor_press slug=%s state=%s · %s", slug, state, words)
    # Contents reads the plan from the newest endpoint row: read it again so the page shows the result at once.
    ei.record_resolution(registry, gateway, db_entity, by=by)
    return {"state": state, **detail}


def latest_press(registry, slug: str) -> dict | None:
    """The newest press's proof row detail (with its time), for Contents and for an undo."""
    rows = [p for p in registry.list_catalogue_commit_proofs(slug) if p["proof"] == PROOF_KIND]
    if not rows:
        return None
    last = rows[-1]
    return {**(last.get("detail") or {}), "at": last["read_at"], "by": last.get("recorded_by") or ""}
