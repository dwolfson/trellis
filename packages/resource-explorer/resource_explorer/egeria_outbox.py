"""Draining the Egeria outbox — the apply side of egeria_outbox rows.

`docs/outbox-publishing-design.md` §5. The registry owns the rows; this module
owns turning one into an Egeria element, and the retry policy around that.

**Why this exists.** Publishing to Egeria has no transaction, no rollback, no
resume and no retry. `annotation_props.publish_annotations()` logs a failed
annotation and continues, so a SurveyReport is reported published even when
every annotation beneath it failed to write; every call site catches, logs and
records `published: False`, leaving whatever already landed in place; and if
the process dies mid-publish, `run_reconciler` marks the row `interrupted` and
stops, correctly, because it knows the run stopped but not that it failed.
Nothing finishes the job. This does.

**The shape is `rfa_actions`', deliberately.** Local-authoritative write,
best-effort remote sync, periodic reconcile — already shipping in this codebase
and driven by the same scheduler loop. What it does NOT inherit are that
precedent's three named gaps: no backoff, no max-attempts, no dead-letter.

**Idempotency is by qualifiedName, not by catching a duplicate error.** Egeria
identifies an element by GUID, and qualifiedName should also be unique, so the
supported way not to re-create something is to search for it first — which is
what `_find_or_create_asset` and `publish_annotations` already do. Building on
a duplicate-create *failing* would rest on an error path, and would misread any
other failure as "already applied".
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Callable

log = logging.getLogger(__name__)


@dataclass
class OutboxClients:
    """The Egeria clients an apply step may need.

    A bundle rather than a single `discovery` argument because element kinds
    reach different managers: annotations go through `DataDiscovery`, while an
    investigation's collection memberships and ResourceList go through
    `CollectionManager`. Passing one client and hoping it has the right method
    would fail at the worst moment — inside a retry, on a row that had already
    been recorded as pending work.

    Fields are optional so a caller wires only what its kinds need; a creator
    asking for a client that is None raises, which the drain treats as any
    other failed attempt.
    """

    discovery: object | None = None
    collection_manager: object | None = None

    def require(self, name: str):
        client = getattr(self, name, None)
        if client is None:
            raise OutboxApplyError(
                f"This element needs the {name!r} client, which the drain was not given"
            )
        return client

#: Rows attempted per drain pass. A blueprint publish is ~14,000 rows
#: (measured 2026-08-31), so a pass is deliberately bounded — the scheduler
#: loop comes back every 15 minutes and an unbounded pass would hold one
#: iteration open for the whole backlog.
DRAIN_BATCH = 200


class OutboxApplyError(RuntimeError):
    """One element could not be written. Carries no retry policy of its own —
    the caller decides, via `mark_outbox_failed`, whether this becomes another
    attempt or a dead letter."""


def apply_element(row: dict, clients: "OutboxClients", find_element_guid: Callable[[str], str]) -> str:
    """Write one outbox row to Egeria and return the element's GUID.

    Lookup-then-create, in that order, always:

    1. If the row already recorded `egeria_guid`, it landed on a previous
       attempt and nothing is written. The GUID is Egeria's primary identity.
    2. Otherwise search by `qualified_name`. A hit means Egeria wrote the
       element but we crashed before recording it — adopt the GUID rather than
       creating a second one with the same qualifiedName.
    3. Only then create.

    Step 2 is the whole reason `qualified_name` is NOT NULL on the table.
    """
    existing = (row.get("egeria_guid") or "").strip()
    if existing:
        log.debug("Outbox row %s already recorded GUID %s — nothing to write",
                  row.get("id"), existing)
        return existing

    qualified_name = row["qualified_name"]
    try:
        found = find_element_guid(qualified_name)
    except Exception as exc:  # defensive — real _find_element_guid never raises
        log.debug("Outbox lookup failed for %s (will attempt create): %s", qualified_name, exc)
        found = ""
    if found:
        log.info("Outbox row %s: %s already exists (GUID %s) — adopting, not re-creating",
                 row.get("id"), qualified_name, found)
        return found

    try:
        payload = json.loads(row["payload_json"])
    except (TypeError, ValueError) as exc:
        # Unparseable payload will never parse on a later attempt either, so
        # it is raised like any other failure and left to burn through its
        # attempts into 'dead' rather than being special-cased into an
        # immediate kill: one code path to reason about, and the row stays
        # visible in the same place as every other stuck write.
        raise OutboxApplyError(f"payload_json is not valid JSON: {exc}") from exc

    kind = row["element_kind"]
    creator = _CREATORS.get(kind)
    if creator is None:
        raise OutboxApplyError(
            f"No creator registered for element_kind {kind!r}. "
            f"Known kinds: {sorted(_CREATORS)}"
        )
    return creator(clients, payload) or ""


def _create_annotation(clients: "OutboxClients", payload: dict) -> str:
    return _guid_of(clients.require("discovery").create_annotation(body=payload))


def _create_collection_membership(clients: "OutboxClients", payload: dict) -> str:
    """Attach one element to a Collection.

    Idempotency here is NOT lookup-then-create: a CollectionMembership has no
    qualifiedName of its own to search for. It comes from the operation being
    an upsert — `CollectionMembership` was measured live (2026-08-25) as
    uni-link, so `add_to_collection` returns None and adding the same element
    twice leaves one member. Replay is therefore safe by the relationship's
    own semantics.

    That measurement is load-bearing, and the return value IS the test: a
    multi-link relationship would silently accumulate one duplicate per retry
    with no error anywhere. Re-measure if pyegeria changes these signatures.
    """
    cm = clients.require("collection_manager")
    cm.add_to_collection(payload["collection_guid"], payload["member_guid"])
    return ""


def _create_resource_list(clients: "OutboxClients", payload: dict) -> str:
    """Attach a Collection to its parent Project (ResourceList).

    Same basis as membership above: `ResourceList` via `attach_collection` was
    measured uni-link on the same date — returns None, and attaching the same
    Collection twice leaves one attachment.
    """
    cm = clients.require("collection_manager")
    cm.attach_collection(payload["parent_guid"], payload["collection_guid"])
    return ""


def _guid_of(result) -> str:
    """pyegeria create_* calls variously return a GUID string, a dict, or
    nothing useful. An empty string is not an error here — the row is still
    marked done, and a later retry would find the element by qualifiedName."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("guid") or result.get("elementGUID") or ""
    return ""


#: element_kind -> creator. An unregistered kind raises rather than silently
#: succeeding — a row that reports 'done' without writing anything is precisely
#: the confident-wrong-answer failure this whole subsystem exists to remove.
#:
#: `asset` and `report` are deliberately absent: the repo publisher creates
#: both synchronously because `publish()` returns the report GUID and callers
#: record it, and the investigation publisher does the same with the Project
#: and Collection GUIDs. Only the plural, per-element writes are queued.
_CREATORS: dict[str, Callable[["OutboxClients", dict], str]] = {
    "annotation": _create_annotation,
    "collection_membership": _create_collection_membership,
    "resource_list": _create_resource_list,
}


def drain_outbox(registry, clients: "OutboxClients | None" = None, find_element_guid=None, *,
                 limit: int = DRAIN_BATCH, run_id: str | None = None) -> dict:
    """One drain pass. Returns a summary dict; never raises.

    Called from `scheduler.py`'s existing loop, once per iteration — the same
    loop that already drives `reconcile_rfa_actions()`, rather than starting a
    second runtime. It runs everywhere publishes originate, which is what the
    design means by putting the layer under the publishers rather than under
    either survey-launch path.

    `discovery` and `find_element_guid` are injected so this is testable
    without a live platform, and are resolved lazily from the repo publisher
    when not supplied — that publisher already owns a connected client and a
    proven `_find_element_guid`.
    """
    summary = {"claimed": 0, "done": 0, "failed": 0, "dead": 0, "skipped": 0}
    try:
        rows = registry.claim_due_outbox_elements(limit=limit, run_id=run_id)
    except Exception:
        log.exception("Outbox drain: could not read due rows")
        return summary
    if not rows:
        return summary
    summary["claimed"] = len(rows)

    if clients is None or find_element_guid is None:
        try:
            clients, find_element_guid = _default_clients()
        except Exception:
            # No platform reachable. Leave every row exactly as it is —
            # pending work is not failed work, and burning an attempt on
            # "Egeria was down" is how a transient outage dead-letters a
            # perfectly good write.
            log.warning("Outbox drain: no Egeria client available, leaving %d rows pending",
                        len(rows))
            summary["skipped"] = len(rows)
            return summary

    troubled_runs: dict[str, str] = {}
    for row in rows:
        try:
            guid = apply_element(row, clients, find_element_guid)
        except Exception as exc:
            status = registry.mark_outbox_failed(row["id"], f"{type(exc).__name__}: {exc}")
            summary["dead" if status == "dead" else "failed"] += 1
            troubled_runs[row.get("run_id") or ""] = row.get("entity_slug") or ""
            log_at = log.error if status == "dead" else log.warning
            log_at("Outbox row %s (%s %s) -> %s: %s",
                   row["id"], row["element_kind"], row["qualified_name"], status, exc)
            continue
        registry.mark_outbox_done(row["id"], guid)
        summary["done"] += 1

    if summary["dead"]:
        log.error("Outbox drain: %d row(s) dead-lettered and need a human — "
                  "see registry.list_dead_outbox_elements()", summary["dead"])
    # Logging is not a surface here — see record_drain_outcome's docstring.
    record_drain_outcome(registry, summary, troubled_runs=troubled_runs)
    return summary


def _default_clients():
    """The repo publisher's own connected clients — one client path, not a
    second one to keep in step with it."""
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    publisher = EgeriaPublisher()
    return OutboxClients(discovery=publisher._discovery), publisher._find_element_guid


def enqueue_annotations(
    registry, entity_type: str, entity_slug: str, annotations: list,
    report_guid: str, qualified_name_prefix: str, *, run_id: str = "",
) -> list[int]:
    """Record one outbox row per annotation. Returns the row ids, in order.

    This is the write half of write-then-publish. The rows are durable before
    anything is sent, so the per-process hole closes: a crash after this
    returns leaves work the drain will finish, where previously it left
    nothing at all.

    `qualified_name_prefix` carries this run's own timestamp and the caller
    owns its format entirely — the same contract `publish_annotations` has.
    That is what makes a retry replay a byte-identical qualifiedName instead
    of minting a new identity, so the replay converges on the element already
    written rather than duplicating it.

    No `depends_on_id`: the caller creates the SurveyReport synchronously and
    passes its GUID, so the dependency these rows have is already satisfied
    before they exist. Ordering matters when the report is itself queued —
    which is what step 4's later publishers will need, and why the column is
    there now.
    """
    from resource_explorer.surveyors.annotation_props import build_annotation_body

    row_ids: list[int] = []
    for i, ann in enumerate(annotations):
        qualified_name = f"{qualified_name_prefix}::{i}"
        body = build_annotation_body(ann, qualified_name, report_guid)
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "annotation", qualified_name, body, run_id=run_id,
        ))
    return row_ids


def enqueue_collection_members(
    registry, entity_slug: str, collection_guid: str,
    members: list[dict], *, run_id: str = "",
) -> list[int]:
    """Record one row per investigation member to attach. Returns row ids.

    `members` are dicts with `member_guid` and, for the record, the member's
    own `entity_type`/`entity_slug`. Members with no asset GUID must be
    filtered out BEFORE calling this — a member whose repo was never published
    has nothing to attach, which is a reportable fact about the investigation,
    not a failed write to retry.

    The qualifiedName is synthetic. A CollectionMembership has no qualifiedName
    of its own, so this string exists purely as the outbox's identity key —
    stable across retries of the same run, and never searched for in Egeria.
    Replay safety comes from the relationship being uni-link instead (see
    `_create_collection_membership`).
    """
    row_ids: list[int] = []
    for m in members:
        member_slug = m.get("entity_slug", "")
        qualified_name = f"CollectionMembership::{collection_guid}::{m['member_guid']}"
        row_ids.append(registry.enqueue_outbox_element(
            "investigation", entity_slug, "collection_membership", qualified_name,
            {"collection_guid": collection_guid, "member_guid": m["member_guid"],
             "member_entity_type": m.get("entity_type", ""), "member_entity_slug": member_slug},
            run_id=run_id,
        ))
    return row_ids


def record_drain_outcome(
    registry, summary: dict, entity_type: str = "", entity_slug: str = "",
    troubled_runs: dict[str, str] | None = None,
) -> None:
    """Put a drain's failures where a person will actually see them.

    Logging alone does not surface anything here: nothing in this package
    configures logging and `uvicorn.run()` is called without a log_config, so
    application records fall through to Python's lastResort handler — WARNING
    and above reach the server's stderr with no timestamp or logger name, and
    INFO is discarded outright. A dead-lettered publish that only logged would
    be invisible in the UI, in any file, and in the activity trail.

    So anything worse than "everything worked" is written to the activity log,
    which the Activity tab already reads. A clean pass writes nothing — an
    entry per quarter-hour tick saying "nothing was wrong" is how a log stops
    being read.
    """
    if not summary.get("failed") and not summary.get("dead"):
        return
    from resource_explorer.activity_logger import log_catalog

    dead, failed = summary.get("dead", 0), summary.get("failed", 0)
    status = "error" if dead else "warning"
    parts = []
    if dead:
        parts.append(f"{dead} element(s) dead-lettered after exhausting retries")
    if failed:
        parts.append(f"{failed} element(s) failed and will retry")
    # The entry is a SUMMARY and says so; the record itself is the outbox rows.
    # `items` carries the pointer the Activity tab turns into a link into
    # Admin → Publish Queue, filtered to the affected run — so "3 elements
    # dead-lettered" is one click from *which* three, their qualifiedNames,
    # their attempt counts and what Egeria actually said. Putting that detail
    # in the entry text instead would make the activity log the log, which it
    # is not: it is an audit trail of operations, one line each.
    runs = troubled_runs or {}
    items = [
        {"kind": "publish_queue", "name": run_id or "(unattributed)",
         "link": "admin-outbox", "run_id": run_id, "entity_slug": slug}
        for run_id, slug in sorted(runs.items())
    ] or [{"kind": "publish_queue", "name": "all pending elements",
           "link": "admin-outbox", "run_id": "", "entity_slug": ""}]
    try:
        log_catalog(
            registry, entity_type or "repo", entity_slug or "", "", "",
            status=status,
            summary="Egeria publish incomplete — " + "; ".join(parts),
            detail=(
                f"Outbox drain: {summary}. "
                "Full per-element record — qualifiedName, attempts, and Egeria's own "
                "error for each — is in Admin → Publish Queue. Dead-lettered rows will "
                "not be retried without intervention; they can be re-queued there."
            ),
            items=items,
        )
    except Exception:
        # The activity write is the visibility mechanism, not the work. If it
        # fails, the rows themselves are still correct and still retryable.
        log.exception("Outbox drain: could not record outcome to the activity log")
