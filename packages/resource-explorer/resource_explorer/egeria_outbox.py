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
from typing import Callable

log = logging.getLogger(__name__)

#: Rows attempted per drain pass. A blueprint publish is ~14,000 rows
#: (measured 2026-08-31), so a pass is deliberately bounded — the scheduler
#: loop comes back every 15 minutes and an unbounded pass would hold one
#: iteration open for the whole backlog.
DRAIN_BATCH = 200


class OutboxApplyError(RuntimeError):
    """One element could not be written. Carries no retry policy of its own —
    the caller decides, via `mark_outbox_failed`, whether this becomes another
    attempt or a dead letter."""


def apply_element(row: dict, discovery, find_element_guid: Callable[[str], str]) -> str:
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
    return creator(discovery, payload) or ""


def _create_annotation(discovery, payload: dict) -> str:
    result = discovery.create_annotation(body=payload)
    return _guid_of(result)


def _guid_of(result) -> str:
    """pyegeria create_* calls variously return a GUID string, a dict, or
    nothing useful. An empty string is not an error here — the row is still
    marked done, and a later retry would find the element by qualifiedName."""
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        return result.get("guid") or result.get("elementGUID") or ""
    return ""


#: element_kind -> creator. Only `annotation` is wired today, because the repo
#: publisher is the only path Phase 2 needs (design §6 step 4) and enqueueing
#: from the publishers is that step, not this one. An unregistered kind raises
#: rather than silently succeeding — a row that reports 'done' without writing
#: anything is precisely the confident-wrong-answer failure this whole
#: subsystem exists to remove.
_CREATORS: dict[str, Callable[[object, dict], str]] = {
    "annotation": _create_annotation,
}


def drain_outbox(registry, discovery=None, find_element_guid=None, *, limit: int = DRAIN_BATCH) -> dict:
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
        rows = registry.claim_due_outbox_elements(limit=limit)
    except Exception:
        log.exception("Outbox drain: could not read due rows")
        return summary
    if not rows:
        return summary
    summary["claimed"] = len(rows)

    if discovery is None or find_element_guid is None:
        try:
            discovery, find_element_guid = _default_clients()
        except Exception:
            # No platform reachable. Leave every row exactly as it is —
            # pending work is not failed work, and burning an attempt on
            # "Egeria was down" is how a transient outage dead-letters a
            # perfectly good write.
            log.warning("Outbox drain: no Egeria client available, leaving %d rows pending",
                        len(rows))
            summary["skipped"] = len(rows)
            return summary

    for row in rows:
        try:
            guid = apply_element(row, discovery, find_element_guid)
        except Exception as exc:
            status = registry.mark_outbox_failed(row["id"], f"{type(exc).__name__}: {exc}")
            summary["dead" if status == "dead" else "failed"] += 1
            log_at = log.error if status == "dead" else log.warning
            log_at("Outbox row %s (%s %s) -> %s: %s",
                   row["id"], row["element_kind"], row["qualified_name"], status, exc)
            continue
        registry.mark_outbox_done(row["id"], guid)
        summary["done"] += 1

    if summary["dead"]:
        log.error("Outbox drain: %d row(s) dead-lettered and need a human — "
                  "see registry.list_dead_outbox_elements()", summary["dead"])
    return summary


def _default_clients():
    """The repo publisher's own connected clients — one client path, not a
    second one to keep in step with it."""
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher

    publisher = EgeriaPublisher()
    return publisher._discovery, publisher._find_element_guid
