"""Publish an investigation's unpublished members to Egeria (owner, 2026-10-13).

Found live on `privacy-proof-2026-10-13`: 14 repositories in scope, Publish then Relink members, and still "not
linked". Link-status said why for every one ("not in Egeria yet — no asset GUID"): Publish on an investigation
publishes its Project, never its members, and Relink correctly sends nothing for a member with no asset. Nothing
on the page offered the way forward. This is that way forward, built only from paths that already exist:

* **What counts as unpublished** is `egeria_investigation_publisher.member_asset_guid`, the same question relink
  and link-status ask, so the plan cannot name a member link-status calls published or the reverse.
* **The plan and the press are one function** (`member_publish_plan`): the confirmation shows exactly the list the
  press then sends, and the press re-asks it rather than trusting what the page sent.
* **Each member is published by RE's existing per-repository publish**, `repo_publish.publish_report` (the
  Publish band's own press, `POST /api/egeria/{slug}/publish-report`): the kept survey, whole, read back by its
  GUID, with a proof row. It never surveys. Zones are the publisher's own rule: `EgeriaPublisher.publish` asks
  `ProjectRegistry.private_owner_for_entity` and zones a private investigation's member `[private zone, owner]`
  (and refuses when that zone is not enforced). Nothing here chooses a zone.
* **As the signed-in caller**, who for a private investigation must be its owner (the route refuses anyone else
  before anything is planned or sent). The batch thread runs in a copy of the request's context, so the caller
  travels with it (a bare thread would drop it).
* **Per-member results come from proof rows.** A published member is "published" only when the publish wrote a
  `report_published` / `report_sent` proof row; every other outcome (not permitted, no kept survey, failed, already
  published) is its own activity row under the investigation, with its words. One failure never stops the rest.
* **A cap**: at most `MEMBER_PUBLISH_CAP` members a press, one at a time; the rest are named as waiting for the
  next press. There was no cap on any bulk publish before this.
* **What is sent is what was confirmed**: the press carries the plan's `slugs`; a plan that no longer matches is
  `PlanChanged` (409, "the list changed, confirm again") and nothing is sent.
* **Bounded**: each member waits at most `MEMBER_TIMEOUT_SECONDS` (its words say it timed out and may still finish);
  a lost sign-in stops the batch and the rest read "not reached · sign in again". The in-memory lock is released
  whatever happens, and a batch whose process went away reads "not reached".

Relink is NOT chained: publishing and linking are two writes with two checks, and every existing flow keeps them
apart (promote links what exists; relink is its own press). The result offers [Relink members] next.
"""
from __future__ import annotations

import contextvars
import json
import logging
import threading
import uuid
from datetime import UTC, datetime

log = logging.getLogger(__name__)

#: At most this many members are published by one press; the rest wait, named, for the next press.
MEMBER_PUBLISH_CAP = 50

#: The `detail` keys that mark this module's activity rows (batch row and per-member rows).
BATCH_KEY = "member_publish_batch"
MEMBER_KEY = "member_publish"

PUBLISHED = "published"
SENT = "sent"
NOT_PERMITTED = "not_permitted"
NOT_PUBLISHED = "not_published"
FAILED = "failed"
SKIPPED = "skipped"

_running: dict[str, str] = {}             # investigation slug -> the batch id publishing its members now
_lock = threading.Lock()


class BatchRunning(RuntimeError):
    """A members publish for this investigation is already running (a second press is refused, not queued)."""


class PlanChanged(RuntimeError):
    """The press named a list that is not the one the plan gives now: nothing is sent; confirm again."""


#: How long one member's publish may take before the batch stops waiting for it and goes on (a pyegeria call that
#: hangs must not hold the investigation's lock until a restart). The member's own publish may still finish.
MEMBER_TIMEOUT_SECONDS = 600

PLAN_CHANGED_WORDS = "the list changed, confirm again"
SIGN_IN_AGAIN = "sign in again"
NOT_REACHED = "not_reached"
COULD_NOT_TELL = "could_not_tell"


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _member(m: dict) -> dict:
    return {"entity_type": m.get("entity_type") or "", "entity_slug": m.get("entity_slug") or ""}


def _names(members: list[dict]) -> str:
    return ", ".join(m["entity_slug"] for m in members)


def member_publish_plan(registry, slug: str, cap: int | None = None) -> dict:
    """THE list: which of this investigation's members a press of [Publish the N unpublished members] publishes.

    The confirmation shows it and the press runs it (the press calls this again, never the page's copy).
    `publish` is the first `cap` repositories with no asset GUID (`member_asset_guid`), in scope order;
    `waiting` the rest of them; `already_published` those with one; `not_publishable` members of a kind this
    press does not publish, with the reason. `slugs` is the list the confirmation names and the press must send
    back unchanged (`PlanChanged` otherwise)."""
    cap = MEMBER_PUBLISH_CAP if cap is None else cap
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        KIND_NOT_LINKED_REASON, LINKABLE_MEMBER_TYPES, member_asset_guid,
    )

    unpublished, already, other = [], [], []
    for m in registry.list_investigation_members(slug):
        if (m.get("state") or "in-scope") == "excluded":
            continue
        row = _member(m)
        if row["entity_type"] not in LINKABLE_MEMBER_TYPES:
            other.append({**row, "reason": KIND_NOT_LINKED_REASON})
        elif member_asset_guid(registry, row["entity_type"], row["entity_slug"]):
            already.append(row)
        else:
            unpublished.append(row)
    publish, waiting = unpublished[:cap], unpublished[cap:]
    n = len(publish)
    if n:
        words = f"will publish {n} repo{'' if n == 1 else 's'}: {_names(publish)}"
        if waiting:
            words += (f" · {len(waiting)} more wait{'s' if len(waiting) == 1 else ''} for the next press"
                      f" (at most {cap} a press)")
    else:
        words = "nothing to publish · every repository in scope is already in Egeria"
    return {"slug": slug, "cap": cap, "count": n, "words": words, "publish": publish, "waiting": waiting,
            "slugs": [m["entity_slug"] for m in publish],
            "already_published": already, "not_publishable": other,
            "running": _running.get(slug, "")}


# ── one member, through the existing publish ─────────────────────────────────────────────────────────────

class SignInLost(RuntimeError):
    """The presser's sign-in is gone (no caller, or the token expired): the batch stops; nothing more is sent."""


def _newest_report_proof(registry, member_slug: str, after_id: int) -> dict | None:
    from resource_explorer import repo_publish as rp
    from resource_explorer.catalogue_commit import P_READ_FAILED, P_REPORT

    rows = [p for p in registry.list_catalogue_commit_proofs(member_slug)
            if p["node_kind"] == rp.NODE_REPORT and p["id"] > after_id
            and p["proof"] in (P_REPORT, rp.P_SENT, P_READ_FAILED)]
    return rows[-1] if rows else None


def _last_proof_id(registry, member_slug: str) -> int:
    rows = registry.list_catalogue_commit_proofs(member_slug)
    return max((p["id"] for p in rows), default=0)


def _require_sign_in() -> None:
    """Raise `SignInLost` when the caller this batch runs as can no longer act (asked before every member)."""
    from resource_explorer.egeria_clients import Caller

    try:
        Caller()
    except PermissionError as exc:          # NoCallerIdentity / CallerTokenExpired
        raise SignInLost(str(exc) or type(exc).__name__) from exc


def _publish_one(registry, member: dict, author: str) -> dict:
    """Publish one member with `repo_publish.publish_report` and say what happened: {outcome, words, proof_id}.
    Raises `SignInLost` when the presser can no longer act."""
    from resource_explorer import repo_publish as rp
    from resource_explorer.catalogue_commit import P_READ_FAILED
    from resource_explorer.surveyors.egeria_investigation_publisher import member_asset_guid
    from resource_explorer.workflows.curate import resource_access

    et, s = member["entity_type"], member["entity_slug"]
    # The plan was read before the batch started; another press may have published it since.
    if member_asset_guid(registry, et, s):
        return {"outcome": SKIPPED, "words": "already published"}
    _require_sign_in()
    # The same check the per-repository publish route makes first (`authorize_resource_write(..., "publish")`).
    try:
        d = resource_access(registry, et, s, "publish")
    except Exception as exc:  # noqa: BLE001 - an unexpected failure is a refusal with its reason, never a pass
        return {"outcome": NOT_PERMITTED, "words": f"could not check access ({type(exc).__name__}: {exc})"[:300]}
    if not d.allowed:
        return {"outcome": NOT_PERMITTED, "words": str(d.reason)[:300]}
    before = _last_proof_id(registry, s)
    try:
        out = rp.publish_report(registry, s, author)
    except rp.AlreadyRunning as exc:
        return {"outcome": SKIPPED, "words": str(exc)}
    except PermissionError as exc:          # the sign-in went away mid-publish
        raise SignInLost(str(exc) or type(exc).__name__) from exc
    except Exception as exc:  # noqa: BLE001 - one member's failure is its own row; the rest still publish
        log.warning("investigation member publish: %s failed: %s", s, exc)
        return {"outcome": FAILED, "words": f"{type(exc).__name__}: {exc}"[:300]}
    if out.get("gate"):
        # No kept survey, or no project answer: nothing was sent for the report; the sentence says why.
        return {"outcome": NOT_PUBLISHED, "words": str(out.get("sentence") or out["gate"])[:300]}
    proof = _newest_report_proof(registry, s, before)
    if proof is None:
        return {"outcome": FAILED, "words": "the publish returned, but wrote no proof row"}
    if proof["proof"] == P_READ_FAILED:
        # A failed publish, including a private report whose zones could not be confirmed: never "published".
        detail = proof.get("detail") or {}
        return {"outcome": FAILED, "words": str(detail.get("error") or out.get("error")
                                                or "Egeria refused the publish")[:300],
                "proof_id": proof["id"]}
    if out.get("ok") is False:
        return {"outcome": FAILED, "words": str(out.get("error") or "the publish said it failed")[:300],
                "proof_id": proof["id"]}
    return {"outcome": PUBLISHED if proof["proof"] != rp.P_SENT else SENT, "words": "", "proof_id": proof["id"]}


def _publish_one_bounded(registry, member: dict, author: str) -> dict:
    """`_publish_one` in its own thread (with this context), waited for at most `MEMBER_TIMEOUT_SECONDS`. A member
    that hangs is reported with its words and the batch goes on; its publish may still finish in the background."""
    box: dict = {}

    def work():
        import asyncio

        # pyegeria's sync wrappers want an event loop in the thread that calls them (the legacy publish route
        # does the same).
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            box["r"] = _publish_one(registry, member, author)
        except BaseException as exc:  # noqa: BLE001 - handed back to the batch thread below
            box["exc"] = exc
        finally:
            loop.close()
            asyncio.set_event_loop(None)

    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(work,), name=f"member-publish-{member['entity_slug']}", daemon=True)
    t.start()
    t.join(MEMBER_TIMEOUT_SECONDS)
    if t.is_alive():
        return {"outcome": FAILED,
                "words": (f"timed out after {MEMBER_TIMEOUT_SECONDS}s · it may still finish in Egeria; "
                          "press again later to see")}
    if "exc" in box:
        raise box["exc"]
    return box["r"]


# ── the batch ───────────────────────────────────────────────────────────────────────────────────────────

_SUCCESS = (PUBLISHED, SENT, SKIPPED)


def _write_row(registry, row_id: str, inv: dict, status: str, summary: str, detail: dict) -> None:
    from resource_explorer.registry import ActivityEntry

    registry.write_activity(ActivityEntry(
        id=row_id, ts=_now(), operation="publish", intent="enrichment", entity_type="investigation",
        entity_slug=inv.get("slug") or "", entity_name=inv.get("display_name") or "", status=status,
        summary=summary, detail=json.dumps(detail), items=[]))


def _record(registry, inv: dict, batch_id: str, m: dict, r: dict) -> None:
    words = r.get("words") or ""
    try:
        _write_row(registry, str(uuid.uuid4()), inv, "ok" if r["outcome"] in _SUCCESS else "error",
                   f"{m['entity_slug']}: {r['outcome'].replace('_', ' ')}" + (f" · {words}" if words else ""),
                   {MEMBER_KEY: batch_id, **m, **r})
    except Exception:  # the row is the record; losing one is logged (and reads "could not tell"), the batch goes on
        log.exception("could not record member publish result for %s", m["entity_slug"])


def _run(registry, inv: dict, batch_id: str, members: list[dict], author: str, waiting: list[dict]) -> None:
    outcomes: list[str] = []
    stopped = ""
    try:
        for i, m in enumerate(members):
            try:
                r = _publish_one_bounded(registry, m, author)
            except SignInLost as exc:
                # Nothing more can be sent as this person: the rest are not reached, and say why.
                stopped = f"{SIGN_IN_AGAIN} ({exc})"[:300]
                for rest in members[i:]:
                    _record(registry, inv, batch_id, rest, {"outcome": NOT_REACHED, "words": stopped})
                break
            except Exception as exc:  # noqa: BLE001 - never let one member end the batch
                r = {"outcome": FAILED, "words": f"{type(exc).__name__}: {exc}"[:300]}
            outcomes.append(r["outcome"])
            _record(registry, inv, batch_id, m, r)
    finally:
        tried = len(outcomes)
        ok = bool(outcomes) and all(o in _SUCCESS for o in outcomes) and tried == len(members)
        summary = f"finished: {tried} of {len(members)} tried" + (f" · stopped: {stopped}" if stopped else "")
        try:
            _write_row(registry, batch_id, inv, "ok" if ok else "error", summary,
                       {BATCH_KEY: batch_id, "members": members, "waiting": waiting, "by": author,
                        "finished": True})
        except Exception:
            log.exception("could not close member publish batch %s", batch_id)
        with _lock:
            if _running.get(inv.get("slug") or "") == batch_id:
                _running.pop(inv.get("slug") or "", None)


def start_member_publish(registry, inv: dict, author: str, *, confirmed: list[str] | None = None,
                         background: bool = True) -> dict:
    """Plan (the same function the confirmation showed), check the press names exactly that list (`confirmed`, the
    slugs the confirmation showed; `PlanChanged` otherwise), record the batch, and publish its members one at a time
    in a background thread that carries the caller's context. Returns the batch's first progress read."""
    slug = inv["slug"]
    plan = member_publish_plan(registry, slug)
    members = plan["publish"]
    if confirmed is None or list(confirmed) != plan["slugs"]:
        raise PlanChanged(PLAN_CHANGED_WORDS)
    batch_id = f"mp-{uuid.uuid4().hex[:12]}"
    with _lock:
        if slug in _running:
            raise BatchRunning(f"a members publish for {slug} is already running")
        if members:
            _running[slug] = batch_id
    if not members:
        return {"batch_id": "", "plan": plan, **progress_of(registry, slug, "")}
    try:
        _write_row(registry, batch_id, inv, "running", plan["words"],
                   {BATCH_KEY: batch_id, "members": members, "waiting": plan["waiting"], "by": author,
                    "finished": False})
    except Exception:
        with _lock:
            _running.pop(slug, None)
        raise
    ctx = contextvars.copy_context()       # the signed-in caller travels with the batch
    if background:
        threading.Thread(target=ctx.run, args=(_run, registry, inv, batch_id, members, author, plan["waiting"]),
                         name=f"member-publish-{slug}", daemon=True).start()
    else:
        ctx.run(_run, registry, inv, batch_id, members, author, plan["waiting"])
    return {"batch_id": batch_id, "plan": plan, **progress_of(registry, slug, batch_id)}


def _batch_rows(registry, slug: str) -> list[dict]:
    rows = []
    for row in registry.list_activity(entity_type="investigation", entity_slug=slug, operation="publish",
                                      limit=5000):
        try:
            detail = json.loads(row.get("detail") or "{}")
        except (TypeError, ValueError):
            continue
        if isinstance(detail, dict) and (BATCH_KEY in detail or MEMBER_KEY in detail):
            rows.append({**row, "_detail": detail})
    return rows


def latest_batch_id(registry, slug: str) -> str:
    for row in _batch_rows(registry, slug):                      # newest first
        if BATCH_KEY in row["_detail"]:
            return row["_detail"][BATCH_KEY]
    return ""


def progress_of(registry, slug: str, batch_id: str) -> dict:
    """Each planned member's state from the rows: published / sent · waiting for Egeria (a proof row by its id),
    not permitted · why, not published · why, failed · why, skipped · why, not reached · sign in again.
    A member with no row: while running, the next is "publishing" and the rest "waiting"; once the batch row says
    it finished, "could not tell" (its result row was lost); a batch that stopped without finishing (the process
    went away), "not reached"."""
    if not batch_id:
        return {"running": False, "members": [], "counts": {}, "words": []}
    rows = _batch_rows(registry, slug)
    batch = next((r for r in rows if r["_detail"].get(BATCH_KEY) == batch_id), None)
    if batch is None:
        return {"running": False, "members": [], "counts": {}, "words": [], "unknown": True}
    planned = batch["_detail"].get("members") or []
    finished = bool(batch["_detail"].get("finished"))
    results = {}
    for r in reversed(rows):                                      # oldest first: the newest row per member wins
        d = r["_detail"]
        if d.get(MEMBER_KEY) == batch_id:
            results[(d.get("entity_type"), d.get("entity_slug"))] = d
    running = _running.get(slug) == batch_id
    out, publishing_shown = [], False
    for m in planned:
        d = results.get((m["entity_type"], m["entity_slug"]))
        if d is None:
            if running:
                state = "waiting" if publishing_shown else "publishing"
                publishing_shown = True
                words = ""
            elif finished:
                state, words = COULD_NOT_TELL, "no result was recorded for this member"
            else:
                state, words = NOT_REACHED, "the batch stopped before this member"
            out.append({**m, "state": state, "words": words})
            continue
        state, words = d.get("outcome") or FAILED, d.get("words") or ""
        if state in (PUBLISHED, SENT):
            # Said only from a proof row that exists, read by its id.
            proof_id = d.get("proof_id")
            proofs = {p["id"]: p for p in registry.list_catalogue_commit_proofs(m["entity_slug"])}
            if proof_id not in proofs:
                state, words = COULD_NOT_TELL, "no proof row for this publish"
        out.append({**m, "state": state, "words": words})
    counts: dict[str, int] = {}
    for o in out:
        counts[o["state"]] = counts.get(o["state"], 0) + 1
    order = [(PUBLISHED, "published"), (SENT, "sent · waiting for Egeria"), (NOT_PERMITTED, "not permitted"),
             (NOT_PUBLISHED, "not published"), (FAILED, "failed"), (SKIPPED, "skipped"),
             (COULD_NOT_TELL, "could not tell"), ("publishing", "publishing"), ("waiting", "waiting"),
             (NOT_REACHED, "not reached")]
    words = [f"{counts[k]} {w}" for k, w in order if counts.get(k)]
    return {"batch_id": batch_id, "running": running, "members": out, "counts": counts, "words": words,
            "waiting_next_press": batch["_detail"].get("waiting") or [],
            "relink_next": bool(counts.get(PUBLISHED) or counts.get(SENT)) and not running}
