"""Tags become public Egeria InformalTags; RE groups become Folio collections (Brief T, 2026-10-10).

The project owner, 2026-10-10, verbatim: "tags should be public", "Use Folio", "Yes, removing a tag removes it
in Egeria".

What goes to Egeria, and through what:

    a tag on a resource in Egeria   -> a public InformalTag (found by name, created only when absent) linked to
                                       the resource's asset by AttachedTag      outbox kind `informal_tag_link`
    removing that tag in RE         -> the AttachedTag link is removed          outbox kind `informal_tag_detach`
    the resource's RE group         -> a Folio `Folio::RE::group::<slug>` (found by qualifiedName, created only
                                       when absent) with the asset as a member  outbox kind `group_folio_membership`
    leaving or changing the group   -> that membership is removed               `group_folio_membership_detach`

**Never a delete of an InformalTag or a Folio element.** Removing a tag only removes its link to the asset;
deleting an RE group only removes memberships (and reports the Folio). Deleting either element would be a delete
under the ISSUE-117 block, and the owner deletes those by hand. Nothing in this module calls `delete_tag`,
`delete_collection` or any other element delete, and a test fails if it does.

"Public" here: Egeria 6's InformalTag carries no public/private flag. `InformalTagProperties` adds nothing to
`ReferenceableProperties` (frameworks/openmetadata/properties/feedback/InformalTagProperties.java:32), and a
"private" tag is only `findMyTags`' filter on the creator (handlers/InformalTagHandler.java:267-290). Every tag is
therefore readable by anyone who can read it; what makes RE's tags shared rather than per-person is that RE finds
an existing tag BY NAME before it creates one, and creates with a name-based qualifiedName
(`InformalTag::<tag>`) rather than pyegeria's per-user, timestamped default (`make_feedback_qn`).

**One source of truth (section 5b rule 1).** `curation_plan` is the only function that decides what each tag and
the group should be in Egeria and what state each is in; the Findable band reads it (GET), and `sync_curation`
enqueues exactly the actions it names. After a fully successful sync the plan has nothing left to do.

**The state is read from persisted outbox rows**, never from what a click assumed: "in Egeria" means a `done`
link row for this asset, "unlinked" a `done` detach row, and so on. Rows for an asset GUID that is no longer the
resource's (an Egeria wipe and re-publish) are history and are ignored: they are never detached, since that
element is gone.

**Unlinks are destructive outbox kinds** (`egeria_outbox.DESTRUCTIVE_OUTBOX_KINDS`): a failed or lapsed unlink is
dead on its first failure, never re-sent by the drain, and never re-sent by a later sync either. The band shows
"failed · <reason>" with a retry a person presses (`retry_item`), which queues a NEW row.

**Identity (Brief I).** A sync inside a person's request drains inline as that person (`current_principal()`, the
Caller). Rows carry the requester in `by`, so the background loop (a Daemon drain) applies a left-over row as
`Daemon(OUTBOX, requested_by=<by>)`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field

log = logging.getLogger(__name__)

TAG_LINK = "informal_tag_link"
TAG_DETACH = "informal_tag_detach"
GROUP_LINK = "group_folio_membership"
GROUP_DETACH = "group_folio_membership_detach"
KINDS = (TAG_LINK, TAG_DETACH, GROUP_LINK, GROUP_DETACH)
_LINK_OF = {"tag": TAG_LINK, "group": GROUP_LINK}
_DETACH_OF = {"tag": TAG_DETACH, "group": GROUP_DETACH}

#: Item states (the band draws a glyph and the word for each; `reason` follows "failed ·").
IN_EGERIA = "in_egeria"
NOT_YET = "not_yet"            # the resource is not in Egeria, so the tag or group stays in RE for now
NOT_SENT = "not_sent"          # RE and the queued work disagree: the next sync sends it
PENDING = "pending"            # queued or being sent
RETRYING = "retrying"          # a non-destructive link failed and the drain will try again
FAILED = "failed"              # dead: needs a person (retry)
UNLINKED = "unlinked"          # the link was removed in Egeria
STATE_WORDS = {
    IN_EGERIA: "in Egeria",
    NOT_YET: "not yet (resource not in Egeria)",
    NOT_SENT: "not sent yet",
    PENDING: "pending",
    RETRYING: "pending · retrying",
    FAILED: "failed",
    UNLINKED: "unlinked",
}

#: The Egeria operations each action needs, as Egeria's access connector checks them
#: (OpenMetadataAccessSecurityConnector.java, egeria-v6/egeria): a tag link is feedback,
#: `validateUserForElementAddFeedback` :1696-1730 (ADD_FEEDBACK on the tagged element); a tag unlink is
#: `validateUserForElementDeleteFeedback` :1748-1770 (DELETE_FEEDBACK); a membership is an attach/detach of the
#: member (`validateUserForElementAttach` :1582-1620, ATTACH; DETACH for the removal). Every action is also an
#: UPDATE_PROPERTIES of the resource (Brief T: "UPDATE_PROPERTIES on the resource's element").
ADD_FEEDBACK_OPERATION = "ADD_FEEDBACK"
DELETE_FEEDBACK_OPERATION = "DELETE_FEEDBACK"
DETACH_OPERATION = "DETACH"
_OPERATIONS = {
    ("tag", "link"): ADD_FEEDBACK_OPERATION,
    ("tag", "unlink"): DELETE_FEEDBACK_OPERATION,
    ("group", "link"): "ATTACH",
    ("group", "unlink"): DETACH_OPERATION,
}

_UNSENT_CANCEL_NOTE = "superseded by a later change in RE before it was sent"


def tag_qualified_name(tag: str) -> str:
    """The qualifiedName RE creates a public InformalTag with. Name-based so every RE user converges on one."""
    return f"InformalTag::{tag}"


def folio_qualified_name(group_slug: str) -> str:
    return f"Folio::RE::group::{group_slug}"


def tag_link_key(tag: str, element_guid: str) -> str:
    """The outbox identity key of one tag on one asset (a relationship has no qualifiedName of its own)."""
    return f"AttachedTag::{element_guid}::{tag}"


def group_link_key(group_slug: str, element_guid: str) -> str:
    return f"CollectionMembership::{folio_qualified_name(group_slug)}::{element_guid}"


def operations_for(kind: str, action: str) -> tuple[str, ...]:
    """What `curation_access` checks before RE records (or sends) one change."""
    return ("UPDATE_PROPERTIES", _OPERATIONS[(kind, action)])


# ── what RE wants ─────────────────────────────────────────────────────────────────────────────────────────

def _entity(registry, entity_type: str, slug: str):
    if entity_type == "repo":
        return registry.get(slug)
    if entity_type == "database":
        return registry.get_database(slug, allow_unreadable=True)
    if entity_type == "filesystem":
        return registry.get_filesystem(slug)
    return None


def current_group(registry, entity_type: str, slug: str) -> str:
    return str(getattr(_entity(registry, entity_type, slug), "group_slug", "") or "")


def element_guid(registry, entity_type: str, slug: str) -> str:
    """The resource's own asset GUID from RE's cache, "" when it is not in Egeria."""
    from resource_explorer.workflows.curate import element_guid_for

    return element_guid_for(registry, entity_type, slug, "")


# ── the plan: one function decides state and action ──────────────────────────────────────────────────────

@dataclass
class CurationItem:
    kind: str                 # "tag" | "group"
    name: str                 # the tag, or the group slug
    label: str                # what the band shows (the group's display name)
    key: str                  # the outbox qualified_name ("" when the resource is not in Egeria)
    desired: bool             # RE has this tag / this is the resource's group
    state: str
    reason: str = ""
    action: str = ""          # "" | "link" | "unlink": what a sync will queue
    cancel_ids: list = field(default_factory=list)   # unsent rows a sync retires first
    row_id: int | None = None
    retry: bool = False       # dead: a person may press retry (a NEW row)
    retry_action: str = ""    # "link" | "unlink"
    egeria_guid: str = ""     # the tag's / Folio's GUID, from the newest done link row

    @property
    def word(self) -> str:
        return STATE_WORDS.get(self.state, self.state)

    def as_dict(self) -> dict:
        d = asdict(self)
        d["word"] = self.word
        return d


def _payload(row: dict) -> dict:
    try:
        p = json.loads(row.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return {}
    return p if isinstance(p, dict) else {}


def _evaluate(kind: str, desired: bool, rows: list[dict]) -> dict | None:
    """State, action and cancellations for one key from its rows (newest first, retired rows excluded).

    Returns None when there is nothing to show (never linked, and not wanted)."""
    link, detach = _LINK_OF[kind], _DETACH_OF[kind]
    if desired:
        # A removal that was never sent is superseded by the re-add.
        cancel = [r["id"] for r in rows if r["element_kind"] == detach and r["status"] == "pending"
                  and int(r.get("attempts") or 0) == 0]
    else:
        # A link that was never applied (pending, or failed and backing off) is retired rather than raced by an
        # unlink: a failed link retried after the unlink would leave the tag on in Egeria.
        cancel = [r["id"] for r in rows if r["element_kind"] == link and r["status"] in ("pending", "failed")]
    live = [r for r in rows if r["id"] not in cancel]
    newest = live[0] if live else None
    out = {"cancel_ids": cancel, "row_id": newest["id"] if newest else None, "action": "",
           "reason": "", "retry": False, "retry_action": ""}
    if desired:
        if newest is None or newest["element_kind"] == detach:
            return {**out, "state": NOT_SENT, "action": "link"}
        status = newest["status"]
        if cancel:
            return {**out, "state": NOT_SENT}
        if status == "done":
            return {**out, "state": IN_EGERIA}
        if status in ("pending", "running"):
            return {**out, "state": PENDING}
        if status == "failed":
            return {**out, "state": RETRYING, "reason": newest.get("last_error") or ""}
        return {**out, "state": FAILED, "reason": newest.get("last_error") or "", "retry": True,
                "retry_action": "link"}
    if newest is None:
        return {**out, "state": NOT_SENT} if cancel else None
    if newest["element_kind"] == link:
        if newest["status"] in ("done", "running"):
            return {**out, "state": NOT_SENT, "action": "unlink"}
        return {**out, "state": NOT_SENT} if cancel else None         # a dead link never landed
    status = newest["status"]
    if cancel:
        return {**out, "state": NOT_SENT}
    if status == "done":
        return {**out, "state": UNLINKED}
    if status in ("pending", "running"):
        return {**out, "state": PENDING, "reason": "unlink"}
    return {**out, "state": FAILED, "reason": newest.get("last_error") or "", "retry": True,
            "retry_action": "unlink"}


def _done_link_guid(rows: list[dict], link_kind: str) -> str:
    for r in rows:
        if r["element_kind"] == link_kind and r["status"] == "done" and r.get("egeria_guid"):
            return str(r["egeria_guid"])
    return ""


def curation_plan(registry, entity_type: str, slug: str, *, asset_guid: str | None = None) -> dict:
    """THE decision: per tag and per group, what it is in Egeria and what a sync would do.

    `asset_guid` overrides RE's cached GUID (a publish hook that has just created the asset). Read-only."""
    guid = (asset_guid if asset_guid is not None else element_guid(registry, entity_type, slug)) or ""
    tags = list(registry.list_resource_tags(entity_type, slug))
    group = current_group(registry, entity_type, slug)
    items: list[CurationItem] = []

    def label_of(group_slug: str) -> str:
        try:
            g = registry.get_group(group_slug)
        except Exception:
            g = None
        return (getattr(g, "display_name", "") or group_slug) if g else group_slug

    if not guid:
        items += [CurationItem("tag", t, t, "", True, NOT_YET) for t in tags]
        if group:
            items.append(CurationItem("group", group, label_of(group), "", True, NOT_YET))
        return {"entity_type": entity_type, "slug": slug, "element_guid": "", "in_egeria": False,
                "items": items}

    by_key: dict[tuple[str, str], list[dict]] = {}
    for r in registry.list_outbox_rows_for_kinds(entity_type, slug, KINDS):
        if r["status"] in ("cancelled", "superseded"):
            continue
        p = _payload(r)
        if (p.get("element_guid") or "") != guid:
            continue                      # history for an asset that is no longer this resource's
        kind = "tag" if r["element_kind"] in (TAG_LINK, TAG_DETACH) else "group"
        name = p.get("tag") if kind == "tag" else p.get("group_slug")
        if name:
            by_key.setdefault((kind, name), []).append(r)

    wanted = [("tag", t) for t in tags] + ([("group", group)] if group else [])
    seen = set(wanted)
    others = sorted(k for k in by_key if k not in seen)
    for kind, name in wanted + others:
        rows = by_key.get((kind, name), [])
        ev = _evaluate(kind, (kind, name) in seen, rows)
        if ev is None:
            continue
        key = tag_link_key(name, guid) if kind == "tag" else group_link_key(name, guid)
        items.append(CurationItem(
            kind=kind, name=name, label=name if kind == "tag" else label_of(name), key=key,
            desired=(kind, name) in seen, egeria_guid=_done_link_guid(rows, _LINK_OF[kind]), **ev))
    return {"entity_type": entity_type, "slug": slug, "element_guid": guid, "in_egeria": True, "items": items}


def plan_as_dict(plan: dict) -> dict:
    return {**plan, "items": [i.as_dict() for i in plan["items"]],
            "to_send": sum(1 for i in plan["items"] if i.action or i.cancel_ids)}


# ── the write: queue what the plan names, then drain it as the caller ─────────────────────────────────────

def run_id_for(entity_type: str, slug: str) -> str:
    return f"Curation::{entity_type}::{slug}"


def _requester(registry, entity_type: str, slug: str, item: CurationItem, by: str) -> str:
    """Who asked: the person pressing, else (a publish hook with nobody signed in) who last decided it in RE."""
    if by:
        return by
    try:
        if item.kind == "tag":
            for t in registry.list_resource_tags_with_authors(entity_type, slug):
                if t.get("tag") == item.name:
                    return str(t.get("author") or "")
        changes = registry.list_group_changes(entity_type, slug)
        return str(changes[-1].get("author") or "") if changes else ""
    except Exception:
        return ""


def _enqueue(registry, entity_type: str, slug: str, item: CurationItem, action: str, guid: str, by: str,
             display: dict) -> int:
    kind = item.kind
    element_kind = _LINK_OF[kind] if action == "link" else _DETACH_OF[kind]
    payload = {"entity_type": entity_type, "entity_slug": slug, "element_guid": guid, "by": by}
    if kind == "tag":
        payload["tag"] = item.name
        if action == "unlink" and item.egeria_guid:
            payload["tag_guid"] = item.egeria_guid
    else:
        payload.update(group_slug=item.name, folio_qualified_name=folio_qualified_name(item.name),
                       display_name=display.get("display_name") or item.name,
                       description=display.get("description") or "")
        if action == "unlink" and item.egeria_guid:
            payload["folio_guid"] = item.egeria_guid
    return registry.enqueue_outbox_element(entity_type, slug, element_kind, item.key, payload,
                                           run_id=run_id_for(entity_type, slug))


def _group_display(registry, group_slug: str) -> dict:
    try:
        g = registry.get_group(group_slug)
    except Exception:
        g = None
    return {"display_name": getattr(g, "display_name", "") or group_slug,
            "description": getattr(g, "description", "") or
            f"Resources grouped as {getattr(g, 'display_name', '') or group_slug} in Resource Explorer."}


def _caller_user() -> str:
    try:
        from resource_explorer.a2a_auth import caller

        c = caller()
    except Exception:
        return ""
    return (getattr(c, "user_id", "") or "") if c is not None else ""


def plan_operations(plan: dict) -> tuple[str, ...]:
    ops: list[str] = []
    for i in plan["items"]:
        if i.action:
            for op in operations_for(i.kind, i.action):
                if op not in ops:
                    ops.append(op)
    return tuple(ops)


def sync_curation(registry, entity_type: str, slug: str, *, by: str = "", asset_guid: str | None = None,
                  check_access: bool = True, drain: bool = True, identity=None) -> dict:
    """Queue what `curation_plan` says is not yet in Egeria (links and unlinks), retire unsent rows it supersedes,
    then drain this resource's curation rows inline. Returns the plan as re-read afterwards, with `refused` when
    curation access said no (nothing is queued then) and `drain` (the drain summary).

    Never raises for an Egeria failure: the rows carry it. `check_access` is the Brief Z decision for the
    operations the queued actions perform; a publish hook passes False (the tags were checked when they were
    added, and the inline drain acts as the person who pressed Publish, so Egeria checks them itself)."""
    by = by or _caller_user()
    plan = curation_plan(registry, entity_type, slug, asset_guid=asset_guid)
    result: dict = {"refused": "", "queued": [], "cancelled": [], "drain": {}}
    actionable = [i for i in plan["items"] if i.action or i.cancel_ids]
    if not actionable:
        return {**plan_as_dict(plan), **result}
    if check_access and any(i.action for i in actionable):
        from resource_explorer.workflows.curate import curation_access

        d = curation_access(registry, entity_type, slug, "", operations=plan_operations(plan))
        if not d.allowed:
            result["refused"] = d.reason
            return {**plan_as_dict(plan), **result}
    guid = plan["element_guid"]
    for item in actionable:
        for cid in item.cancel_ids:
            if registry.cancel_outbox_row(cid, _UNSENT_CANCEL_NOTE):
                result["cancelled"].append(cid)
        if item.action:
            display = _group_display(registry, item.name) if item.kind == "group" else {}
            result["queued"].append(_enqueue(registry, entity_type, slug, item, item.action, guid,
                                             _requester(registry, entity_type, slug, item, by), display))
    if drain and result["queued"]:
        result["drain"] = _drain(registry, entity_type, slug, len(result["queued"]), identity)
    after = curation_plan(registry, entity_type, slug, asset_guid=asset_guid)
    return {**plan_as_dict(after), **result}


def _drain(registry, entity_type: str, slug: str, n: int, identity) -> dict:
    from resource_explorer.egeria_outbox import drain_outbox

    try:
        return drain_outbox(registry, run_id=run_id_for(entity_type, slug), limit=max(n, 1) + 20,
                            identity=identity)
    except Exception as exc:          # drain_outbox never raises; belt and braces for the request path
        log.warning("Curation sync drain for %s %s did not run: %s", entity_type, slug, exc)
        return {"error": str(exc)}


class RetryRefused(ValueError):
    """The item named has nothing a person can retry (it is not dead)."""


def retry_item(registry, entity_type: str, slug: str, kind: str, name: str, *, by: str = "",
               check_access: bool = True, identity=None) -> dict:
    """A person's retry of one dead link or unlink: a NEW row (a destructive row is never revived), drained
    inline. Raises `RetryRefused` when the item is not dead, `CurationDenied` (workflows.curate) when access
    says no."""
    by = by or _caller_user()
    plan = curation_plan(registry, entity_type, slug)
    item = next((i for i in plan["items"] if i.kind == kind and i.name == name), None)
    if item is None or not item.retry:
        raise RetryRefused(f"{kind} {name!r} has no failed write to retry")
    if check_access:
        from resource_explorer.workflows.curate import CurationDenied, curation_access

        d = curation_access(registry, entity_type, slug, "", operations=operations_for(kind, item.retry_action))
        if not d.allowed:
            raise CurationDenied(d.reason)
    display = _group_display(registry, name) if kind == "group" else {}
    row_id = _enqueue(registry, entity_type, slug, item, item.retry_action, plan["element_guid"], by, display)
    summary = _drain(registry, entity_type, slug, 1, identity)
    return {**plan_as_dict(curation_plan(registry, entity_type, slug)), "queued": [row_id], "drain": summary,
            "refused": "", "cancelled": []}


def publish_pending_curation(registry, entity_type: str, slug: str, asset_guid: str) -> dict:
    """The publish hook: a resource that has just been published (its asset GUID is `asset_guid`) sends the
    tags and group it kept while it was not in Egeria. Best-effort; never raises."""
    if not asset_guid:
        return {}
    try:
        return sync_curation(registry, entity_type, slug, asset_guid=asset_guid, check_access=False)
    except Exception as exc:
        log.warning("Could not send tags/group for %s %s to Egeria: %s", entity_type, slug, exc)
        return {"error": str(exc)}


def group_deleted_report(group_slug: str) -> dict:
    """What a group delete says about Egeria: the Folio stays, and the owner deletes it by hand."""
    return {"folio_qualified_name": folio_qualified_name(group_slug), "left_in_egeria": True,
            "words": ("The Folio stays in Egeria: RE never deletes it. Members' memberships are removed; "
                      "the owner deletes the Folio by hand.")}


# ── the Egeria side: creators the outbox drain calls (egeria_outbox._CREATORS) ─────────────────────────────

def _elements(result) -> list[dict]:
    """pyegeria's JSON find/get answers a list of elements, or a string ("No elements found") for none."""
    return [e for e in result if isinstance(e, dict)] if isinstance(result, list) else []


def _guid(el: dict) -> str:
    return str((el.get("elementHeader") or {}).get("guid") or el.get("guid") or "")


def _props(el: dict) -> dict:
    p = el.get("properties")
    return p if isinstance(p, dict) else {}


def find_informal_tag(fb, tag: str) -> str:
    """The GUID of the InformalTag named `tag`, or "". `get_tags_by_name` is an exact match on displayName
    (InformalTagHandler.getTagsByName :208-228). When several carry the name, RE's own qualifiedName wins, then the
    lowest GUID, so every caller picks the same one."""
    hits = [e for e in _elements(fb.get_tags_by_name(tag))
            if str(_props(e).get("displayName") or _props(e).get("name") or "").strip().lower() == tag.lower()
            and _guid(e)]
    if not hits:
        return ""
    ours = [e for e in hits if _props(e).get("qualifiedName") == tag_qualified_name(tag)]
    return _guid(sorted(ours or hits, key=_guid)[0])


def ensure_informal_tag(fb, tag: str) -> str:
    """Find the public tag by name; create it only when absent; never a second one."""
    from resource_explorer.egeria_outbox import OutboxApplyError, _guid_of, _is_duplicate_qualified_name

    found = find_informal_tag(fb, tag)
    if found:
        return found
    try:
        guid = _guid_of(fb.create_informal_tag(display_name=tag, qualified_name=tag_qualified_name(tag),
                                               description=f"Tag “{tag}” from Resource Explorer."))
    except Exception as exc:
        if not _is_duplicate_qualified_name(exc):
            raise
        guid = find_informal_tag(fb, tag)
    if not guid:
        raise OutboxApplyError(f"InformalTag {tag!r} was neither found nor created")
    return guid


def find_group_folio(cm, qualified_name: str) -> str:
    """The Folio with this qualifiedName (`get_collections_by_name` matches qualifiedName among its name
    properties, CollectionHandler.java:283), or ""."""
    hits = [e for e in _elements(cm.get_collections_by_name(qualified_name, metadata_element_type_name="Folio"))
            if _props(e).get("qualifiedName") == qualified_name and _guid(e)]
    return _guid(sorted(hits, key=_guid)[0]) if hits else ""


def ensure_group_folio(cm, payload: dict) -> str:
    from resource_explorer.egeria_outbox import OutboxApplyError, _guid_of, _is_duplicate_qualified_name
    from resource_explorer.surveyors.egeria_investigation_publisher import _create_typed_collection

    qn = payload.get("folio_qualified_name") or folio_qualified_name(payload["group_slug"])
    found = find_group_folio(cm, qn)
    if found:
        return found
    try:
        guid = _guid_of(_create_typed_collection(cm, "Folio", payload.get("display_name") or payload["group_slug"],
                                                 payload.get("description") or "", qualified_name=qn))
    except Exception as exc:
        if not _is_duplicate_qualified_name(exc):
            raise
        guid = find_group_folio(cm, qn)
    if not guid:
        raise OutboxApplyError(f"Folio {qn!r} was neither found nor created")
    return guid


def create_tag_link(clients, payload: dict) -> str:
    """Link the public tag to the asset; returns the tag's GUID (recorded on the row for a later unlink).

    AttachedTag is declared without `setMultiLink(true)` (OpenMetadataTypesArchive1_2.java:3908-3946), so it is a
    uni-link relationship and a repeated add converges on one link (read from source; not measured live)."""
    fb = clients.require("feedback")
    tag_guid = ensure_informal_tag(fb, payload["tag"])
    fb.add_tag_to_element(payload["element_guid"], tag_guid, is_public=True)
    return tag_guid


def create_tag_detach(clients, payload: dict) -> str:
    """Remove the tag's link from the asset. NEVER deletes the InformalTag itself (ISSUE-117: the owner deletes
    elements by hand). `removeTagFromElement` removes the AttachedTag relationship(s) between the two ends
    (InformalTagHandler.java:334-358). No tag of that name means no link to remove."""
    fb = clients.require("feedback")
    tag_guid = payload.get("tag_guid") or find_informal_tag(fb, payload["tag"])
    if not tag_guid:
        return ""
    fb.remove_tag_from_element(payload["element_guid"], tag_guid)
    return tag_guid


def create_group_membership(clients, payload: dict) -> str:
    """Make the asset a member of the group's Folio (found by qualifiedName or created); returns the Folio GUID.
    CollectionMembership is uni-link (measured 2026-08-25), so a repeat converges on one member."""
    cm = clients.require("collection_manager")
    folio_guid = ensure_group_folio(cm, payload)
    cm.add_to_collection(folio_guid, payload["element_guid"])
    return folio_guid


def create_group_membership_detach(clients, payload: dict) -> str:
    """Remove the asset from the group's Folio. NEVER deletes the Folio (ISSUE-117: by hand)."""
    cm = clients.require("collection_manager")
    folio_guid = payload.get("folio_guid") or find_group_folio(
        cm, payload.get("folio_qualified_name") or folio_qualified_name(payload["group_slug"]))
    if not folio_guid:
        return ""
    cm.remove_from_collection(folio_guid, payload["element_guid"])
    return folio_guid
