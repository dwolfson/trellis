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

from resource_explorer.surveyors.survey_report import (
    annotation_qualified_name, assert_unique_qualified_names)

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
    #: MetadataExpert — the only client that can create a bare relationship
    #: between two already-existing GUIDs (annotation-linking-plan Phase 2).
    #: DataDiscovery has no create/attach endpoint for AnnotationExtension.
    metadata_expert: object | None = None

    def require(self, name: str):
        client = getattr(self, name, None)
        if client is None:
            raise OutboxApplyError(
                f"This element needs the {name!r} client, which the drain was not given"
            )
        return client

#: Rows attempted per drain pass. A proposal publish is up to ~2,100 rows
#: (largest run observed 2026-08-31), so a pass is deliberately bounded — the
#: scheduler loop comes back every 15 minutes and an unbounded pass would hold
#: one iteration open for the whole backlog.
DRAIN_BATCH = 200


class OutboxApplyError(RuntimeError):
    """One element could not be written. Carries no retry policy of its own —
    the caller decides, via `mark_outbox_failed`, whether this becomes another
    attempt or a dead letter."""


#: Egeria's signature for "this qualifiedName is already taken".
#:
#: Matched on the message rather than a status code because the client
#: surfaces it as a SERVER_ERROR_500 wrapping a relatedHTTPCode of 409 — the
#: outer code says nothing useful, and the inner one is only in the text.
#: Both the error id and the phrase are required, so a message that merely
#: mentions a 409 in passing does not qualify.
_DUPLICATE_NAME_MARKERS = ("OMAG-COMMON-409-001", "is not available for use")


def _is_duplicate_qualified_name(exc: Exception) -> bool:
    text = str(exc)
    return all(m in text for m in _DUPLICATE_NAME_MARKERS)


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
    try:
        return creator(clients, payload) or ""
    except Exception as exc:
        if not _is_duplicate_qualified_name(exc):
            raise
        # Egeria says this qualifiedName is taken, which is proof the element
        # exists — so the create is not a failure, it is a late discovery
        # that step 2 should have made. Treating it as a failure is what
        # produced an exception storm on 2026-09-01: rows retrying a write
        # that had already succeeded, forever, because a 409 counted the same
        # as a network error.
        #
        # Look again rather than assuming: the first lookup missed it, and
        # the honest question is whether it can be found at all.
        try:
            found = find_element_guid(qualified_name)
        except Exception:
            found = ""
        if found:
            log.info("Outbox row %s: %s already existed (GUID %s) — adopted after a "
                     "duplicate-name rejection the pre-create lookup missed",
                     row.get("id"), qualified_name, found)
            return found
        # Egeria will not create it and we cannot find it. That is a real
        # inconsistency and must not be silently marked done: the row would
        # claim success with no GUID to show for it. Raised with its own
        # wording so it is distinguishable from an ordinary write failure.
        raise OutboxApplyError(
            f"Egeria rejected {qualified_name!r} as a duplicate qualifiedName but "
            f"the element cannot be found by that name — it exists to Egeria and "
            f"is invisible to our lookup, so no GUID can be recorded."
        ) from exc


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


def _create_annotation_link(clients: "OutboxClients", payload: dict) -> str:
    """Create one `AnnotationExtension` relationship between two annotations
    already created in the same publish run (annotation-linking-plan Phase 2,
    Tier 1: `data_profiler.py`/`dependency.py`'s per-file/per-ecosystem
    evidence linked to their aggregate).

    Idempotency: deliberately NO lookup-then-create, and no pre-check via
    `get_all_related_elements` either — unlike the MULTI_LINK branch the plan
    sketched before measurement. `AnnotationExtension` was measured live
    2026-09-01 (docs/annotation-linking-plan.md, Phase 0) as UNI_LINK: two
    identical creates against the same ordered pair returned the SAME
    relationship GUID, and two independent reads (`get_annotation_extensions`
    AND `get_all_related_elements`) each showed exactly one relationship.
    Create-blind is therefore safe and matches the precedent already used for
    `CollectionMembership`/`ResourceList` below — a retry (or a re-publish of
    the same run) converges on the single relationship Egeria already holds
    rather than accumulating duplicates. Re-measure before relying on this for
    any OTHER relationship type, including `AnnotationReview` (Phase 3, not
    measured, not covered by this).

    Direction: `metadataElement1GUID` is the SUMMARY, `metadataElement2GUID`
    is the EVIDENCE. Phase 0's measurement confirmed no reversal happens and
    that `get_annotation_extensions(X)`/`get_all_related_elements(X)` both
    return whatever is at end 2 when X is end 1 — so `get_annotation_
    extensions(summary_guid)` is the natural "what backs this summary" query
    for a consumer walking the catalog, which is the whole point of Tier 1.
    """
    body = {
        "class": "NewRelatedElementsRequestBody",
        "typeName": "AnnotationExtension",
        "metadataElement1GUID": payload["summary_guid"],
        "metadataElement2GUID": payload["evidence_guid"],
    }
    return _guid_of(clients.require("metadata_expert").create_related_elements(body=body))


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
    "annotation_link": _create_annotation_link,
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
            # Hand the claims back. These rows are claimed at this point, and
            # an outage must leave them exactly as they were — not parked in
            # 'running' until the lease expires.
            registry.release_outbox_claim([r["id"] for r in rows])
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
    publisher._connect()
    return (
        OutboxClients(discovery=publisher._discovery, metadata_expert=publisher._metadata_expert),
        publisher._find_element_guid,
    )


#: Most annotations one publish will queue. Beyond this the run is capped and
#: the remainder is REPORTED, never silently dropped.
#:
#: Chosen from measured runs, 2026-09-02:
#:
#:     largest legitimate run     522  (data_prep_kit — 357 per-file
#:                                      SchemaAnalysisAnnotations plus
#:                                      classifications and measures)
#:     next legitimate            184, 134, 129, 127, 115 ...
#:     pathological             8,980  (pre-fix Committed Secrets, egeria_python_git)
#:                             48,583  (the same scan, full finding count)
#:
#: 2000 sits roughly 4x above anything legitimate that has been observed and
#: an order of magnitude below the failure it exists for. It is a safety net
#: against a rule regression or a pathological repo, NOT a policy about how
#: many annotations an analysis should emit — a surveyor whose normal output
#: approaches this should be emitting a summary with linked evidence instead.
_MAX_ANNOTATIONS_PER_RUN = 2000

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

    assert_unique_qualified_names(qualified_name_prefix, annotations)

    total = len(annotations)
    capped = annotations[:_MAX_ANNOTATIONS_PER_RUN]
    if total > _MAX_ANNOTATIONS_PER_RUN:
        # Loud, and at warning level: a silently truncated publish looks
        # exactly like a complete one. The caller reports the shortfall to
        # the user by comparing len(row_ids) against len(annotations) — see
        # egeria_publisher.publish()'s cap_warning.
        log.warning(
            "Outbox enqueue capped for %s/%s: %d annotations produced, %d queued, "
            "%d NOT published. This is a safety net against a rule regression or "
            "a pathological resource; if it is legitimate output, the analysis "
            "should emit a summary with linked evidence instead of one annotation "
            "per finding.",
            entity_type, entity_slug, total, _MAX_ANNOTATIONS_PER_RUN,
            total - _MAX_ANNOTATIONS_PER_RUN,
        )

    row_ids: list[int] = []
    # enumerate over the CAPPED list but keep each annotation's ORIGINAL
    # index: qualified_name is f"{prefix}::{i}" and that string is the
    # retry-convergence identity. Renumbering after a cap would mint a
    # different qualifiedName for the same annotation on a re-run, so a
    # replay would create a second element instead of converging on the one
    # already written — the exact duplication the prefix contract exists to
    # prevent.
    #
    # Taking the FIRST n also matters: surveyors emit summary-then-detail
    # (secret_scan's ruleset-freshness and scan-summary annotations are
    # indices 0 and 1, with per-match findings after), so a head cap keeps
    # the annotations that describe the run and drops repetitive detail. A
    # surveyor emitting detail first would lose its summary — which is why
    # the cap is logged at warning rather than quietly applied.
    for i, ann in enumerate(capped):
        qualified_name = annotation_qualified_name(qualified_name_prefix, i, ann)
        body = build_annotation_body(ann, qualified_name, report_guid)
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "annotation", qualified_name, body, run_id=run_id,
        ))
    return row_ids


def enqueue_annotation_links(
    registry, entity_type: str, entity_slug: str, links: list[dict], *, run_id: str = "",
) -> list[int]:
    """Record one outbox row per same-run `AnnotationExtension` link.
    Returns the row ids, in order. annotation-linking-plan Phase 2, Tier 1.

    `links` are dicts with `summary_guid`/`evidence_guid` — both real Egeria
    GUIDs already, because Tier 1 only links annotations created in THIS same
    publish (both ends exist by the time this is called; see `_create_
    annotation_link`'s docstring for direction). The caller (`egeria_
    publisher.py::_create_annotations`) is responsible for filtering out any
    pair where either GUID is missing (a failed create) BEFORE calling this —
    enqueuing a link to a GUID that does not exist would just fail loudly
    later for a reason this module cannot diagnose.

    The qualifiedName is synthetic, same basis as `enqueue_resource_list`/
    `enqueue_collection_members` below: `AnnotationExtension` has no
    qualifiedName of its own, so this string exists purely as the outbox's
    idempotency key. Replay safety comes from the relationship being uni-link
    (see `_create_annotation_link`), not from this key resolving to anything
    searchable in Egeria.
    """
    row_ids: list[int] = []
    for link in links:
        summary_guid = link["summary_guid"]
        evidence_guid = link["evidence_guid"]
        qualified_name = f"AnnotationExtension::{summary_guid}::{evidence_guid}"
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "annotation_link", qualified_name,
            {"summary_guid": summary_guid, "evidence_guid": evidence_guid},
            run_id=run_id,
        ))
    return row_ids


def enqueue_resource_list(
    registry, entity_slug: str, parent_guid: str, collection_guid: str, *, run_id: str = "",
) -> int:
    """Record the Project -> Collection ResourceList attach as a queued write.

    Same basis as membership: `ResourceList` via `attach_collection` was measured
    uni-link (2026-08-25), returning None and leaving one attachment however many
    times it is called, so replay converges. The qualifiedName is synthetic — the
    relationship has none — and exists only as the outbox's identity key.

    This one element is queued rather than written directly because its failure
    was previously appended to `PromotionResult.errors` and then forgotten: the
    Project and Collection both existed, unlinked, and nothing ever tried again.
    """
    return registry.enqueue_outbox_element(
        "investigation", entity_slug, "resource_list",
        f"ResourceList::{parent_guid}::{collection_guid}",
        {"parent_guid": parent_guid, "collection_guid": collection_guid},
        run_id=run_id,
    )


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


def enqueue_blueprint_members(
    registry, entity_type: str, entity_slug: str, blueprint_guid: str,
    member_guids: list[str], *, run_id: str = "",
) -> list[int]:
    """One row per member (a `SolutionComponent` or a child `SolutionBlueprint`
    — both are ordinary `CollectionMembership` attachments to the blueprint's
    Collection) attached to a blueprint. docs/blueprint-materialization-plan.md
    Decision 5/Phase B.

    Reuses `element_kind="collection_membership"` unchanged — same creator,
    same idempotency basis as `enqueue_collection_members` above
    (`CollectionMembership` measured uni-link 2026-08-25; `add_to_collection`
    is a safe upsert regardless of which kind of Collection the blueprint
    is). Parallel in shape to `enqueue_collection_members`, not a call to it,
    because that function hardcodes `entity_type="investigation"` and this
    caller's entity is a repo (or whatever `entity_type` the blueprint's own
    resource is) — the member's own identity fields that function also
    records don't apply here, since a blueprint member is always this same
    resource's own component/child-blueprint, not a cross-resource reference.

    No `depends_on_id`: unlike annotation links, the blueprint GUID and every
    member GUID passed in are already resolved synchronously before this is
    called (Decision 5) — nothing here is still in flight.
    """
    row_ids: list[int] = []
    for member_guid in member_guids:
        qualified_name = f"CollectionMembership::{blueprint_guid}::{member_guid}"
        row_ids.append(registry.enqueue_outbox_element(
            entity_type, entity_slug, "collection_membership", qualified_name,
            {"collection_guid": blueprint_guid, "member_guid": member_guid},
            run_id=run_id,
        ))
    return row_ids


def record_drain_outcome(
    registry, summary: dict, entity_type: str = "", entity_slug: str = "",
    troubled_runs: dict[str, str] | None = None,
) -> None:
    """Put a drain's failures where a person will actually see them.

    A log line is not an actionable surface, even now that it is a visible one.
    When this was written nothing in the package configured logging, so INFO was
    discarded outright and WARNING reached only the server's stderr; that was
    fixed on 2026-08-31 by `observability/logging_setup.py`, which the outbox's
    own finding prompted. The conclusion is unchanged and the reason is now the
    better one: a stuck publish needs a place a person returns to and can act
    from, not a line in a stream nobody is watching at 3am. The activity log is
    that place, and a dead letter goes further and raises an RFA.

    So anything worse than "everything worked" is written to the activity log,
    which the Activity tab already reads. A clean pass writes nothing — an
    entry per quarter-hour tick saying "nothing was wrong" is how a log stops
    being read.
    """
    if not summary.get("failed") and not summary.get("dead"):
        return
    from resource_explorer.activity_logger import log_catalog, log_rfa

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
    detail = (
        f"Outbox drain: {summary}. "
        "Full per-element record — qualifiedName, attempts, and Egeria's own "
        "error for each — is in Admin → Publish Queue."
    )
    try:
        if dead:
            # A dead-lettered element will NEVER be retried on its own, so it is
            # a request for human action, not a status line — and it goes to the
            # RFA drawer, which is the surface people actually watch. One entry,
            # not two: log_rfa writes an activity entry as well, so also calling
            # log_catalog would double-report a single event.
            log_rfa(
                registry, entity_type or "repo", entity_slug or "", "",
                status="error",
                summary="Egeria publish stuck — " + "; ".join(parts),
                detail=detail + (
                    " These will not be retried without intervention; re-queue them "
                    "there once the underlying cause is fixed."
                ),
                analysis_name="Egeria publish queue",
                items=items,
            )
        else:
            # Retrying-but-not-yet-stuck is not something to ask a person to act
            # on — the scheduler is already handling it. It stays an audit line.
            log_catalog(
                registry, entity_type or "repo", entity_slug or "", "", "",
                status=status,
                summary="Egeria publish incomplete — " + "; ".join(parts),
                detail=detail,
                items=items,
            )
    except Exception:
        # The activity write is the visibility mechanism, not the work. If it
        # fails, the rows themselves are still correct and still retryable.
        log.exception("Outbox drain: could not record outcome to the activity log")
