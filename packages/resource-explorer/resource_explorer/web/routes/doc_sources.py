"""Documentation sources API — Enrichment stage, slice 1 ("Declare and
probe") of `docs/design-notes/BRIEF-DATABASE-DOCUMENTATION-SOURCES.md`.

A person declares a URL pointing at documentation for a database or
filesystem — a wiki page, a data dictionary, a runbook — RE probes it
read-only and reports one of `reachable`/`needs_sign_in`/`not_found`/
`blocked` (`doc_source_probe.py`, mirroring `credential_capability`'s
posture and vocabulary), and when the resource is published each source
becomes an `ExternalReference` on its Egeria asset (`doc_source_egeria.py`,
reusing `egeria_publisher.py`'s `_publish_homepage_reference` pattern).

Only `database` and `filesystem` entity types are wired — the brief allows
scoping filesystem out for time ("prioritize database first... note
explicitly... if scoped out") but it turned out to need no extra code
beyond the entity resolver below, since `FileSystemEntity` carries the same
`egeria_url`/`egeria_server`/`egeria_user`/`egeria_password`/
`egeria_asset_guid`/`display_name` shape `DatabaseEntity` does — so both are
built together in this slice rather than filesystem being deferred.
Ingest/re-ingest actions (slice 2, `doc_source_ingestion`) are NOT wired
here; the frontend renders them as visibly disabled ("ingest — coming
soon") rather than omitting the affordance, so slice 2 has a known place to
attach rather than inventing UI from scratch.
"""
from __future__ import annotations

import logging
import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer.doc_source_egeria import (
    publish_doc_source,
    read_back_doc_sources,
    resolve_entity_for_doc_source,
)
from resource_explorer.doc_source_probe import probe as run_probe
from resource_explorer.egeria_linkage import describe_publish_status
from resource_explorer.egeria_outbox import (
    drain_outbox_row,
    enqueue_doc_source_publish,
    enqueue_doc_source_unpublish,
)
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)
router = APIRouter()

_ENTITY_TABLES = ("database", "filesystem")


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


def _attempt_outbox_row_immediately(element_id: int) -> None:
    """Fire a scoped `drain_outbox_row` for one just-enqueued row, off the
    request thread — Egeria publish-state fix round 3 (2026-09-29). Design's
    spec is "publish at once (best effort), falling back to the existing
    15-minute retry loop only if that immediate attempt fails" — not "queue
    it and wait up to 15 minutes for the scheduler's next pass", which is
    what round 2 actually shipped.

    Runs on its own daemon thread (same fire-and-forget shape
    `worker.py`/`rag_system.py` already use elsewhere in this codebase) so
    the HTTP response to the add/remove request is never blocked on an
    Egeria round trip. Builds its OWN `ProjectRegistry()` rather than
    capturing the caller's — connections are not shared across threads
    anywhere else in this codebase either. `drain_outbox` itself never
    raises (it converts every failure into `mark_outbox_failed`/dead-letter
    bookkeeping on the row), so this thread cannot crash the process; a
    failure here just leaves the row exactly where the normal 15-minute
    scheduler drain (`scheduler.py`) would find it and retry it, which is
    the intended fallback, not a bug in this path.
    """
    def _run() -> None:
        try:
            drain_outbox_row(_registry(), element_id)
        except Exception:
            # Defense in depth only — drain_outbox_row/drain_outbox already
            # catch everything and route failures onto the row itself via
            # mark_outbox_failed, so reaching this is not expected. Logged,
            # not swallowed silently, and never propagated: this thread has
            # no caller left to propagate to by the time it runs.
            log.exception("doc sources: immediate outbox attempt failed for row %s", element_id)

    threading.Thread(target=_run, name=f"doc-source-outbox-{element_id}", daemon=True).start()


def _resolve_entity(registry: ProjectRegistry, entity_type: str, slug: str):
    if entity_type not in _ENTITY_TABLES:
        raise HTTPException(status_code=400,
                             detail=f"documentation sources are not supported for entity_type={entity_type!r}")
    entity = resolve_entity_for_doc_source(registry, entity_type, slug)
    if not entity:
        raise HTTPException(status_code=404, detail=f"{entity_type} '{slug}' not found")
    return entity


def _publish_status(registry: ProjectRegistry, entity_type: str, slug: str, guid: str) -> dict:
    return describe_publish_status(registry, entity_type, slug, guid or "")


def _sync_egeria_read_back(registry: ProjectRegistry, entity_type: str, slug: str, entity) -> None:
    """Best-effort: fold any ExternalReference Egeria has for this asset
    that RE's own `doc_sources` table doesn't know about yet into it — "a
    source declared in Egeria by someone else appears here too" (the
    brief). Never raises; a failed read-back just means the list below is
    local-only for this call, same as when the resource has never been
    published."""
    guid = entity.egeria_asset_guid or ""
    status = _publish_status(registry, entity_type, slug, guid)
    if not status["is_published"]:
        return
    try:
        remote = read_back_doc_sources(
            guid, view_server=entity.egeria_server, platform_url=entity.egeria_url,
            user_id=entity.egeria_user, user_password=entity.egeria_password,
        )
    except Exception as exc:
        log.debug("doc sources: read-back skipped for %s/%s: %s", entity_type, slug, exc)
        return
    known_guids = {r["egeria_external_ref_guid"] for r in registry.list_doc_sources(entity_type, slug)
                   if r["egeria_external_ref_guid"]}
    known_urls = {r["url"] for r in registry.list_doc_sources(entity_type, slug)}
    for ref in remote:
        if ref["ref_guid"] in known_guids or ref["url"] in known_urls:
            continue
        registry.upsert_doc_source_from_egeria(
            entity_type, slug, url=ref["url"], ref_guid=ref["ref_guid"], label=ref.get("label", ""),
        )


class DocSourceCreate(BaseModel):
    url: str
    label: str = ""
    source_type: str = "other"


class DocSourceOut(BaseModel):
    id: str
    entity_type: str
    entity_slug: str
    url: str
    label: str
    source_type: str
    added_at: str
    added_by: str = ""
    origin: str = "local"
    probe_state: str = ""
    probe_status_code: int | None = None
    probe_ms: int | None = None
    probe_title: str = ""
    probe_byte_count: int | None = None
    probe_error: str = ""
    probed_at: str = ""
    egeria_external_ref_guid: str = ""
    # Egeria publish-state fix (2026-09-29) — exactly one of four states, never
    # empty: "catalogued" / "publishing" / "publish_failed" / "local_only".
    # See _compute_egeria_state's docstring for what each means and how it's
    # derived; find-absence-as-answer is exactly the bug this replaces (an
    # empty publish_note that meant four different things indistinguishably).
    egeria_state: str = "local_only"
    egeria_state_detail: str = ""


class DocSourcesResponse(BaseModel):
    sources: list[DocSourceOut]
    published: bool
    publish_note: str = ""
    # Per-row rollup for the block header ("N declared · X in Egeria · Y
    # local") — computed here rather than re-derived in JS from `sources`,
    # so the one place that knows the four states' meaning is also the one
    # place that counts them.
    in_egeria_count: int = 0
    local_count: int = 0


def _out(row: dict) -> DocSourceOut:
    return DocSourceOut(**{k: row.get(k) for k in DocSourceOut.model_fields
                            if k not in ("egeria_state", "egeria_state_detail")})


def _compute_egeria_state(registry: ProjectRegistry, entity_type: str, slug: str,
                           row: dict, is_published: bool) -> tuple[str, str]:
    """The one place that decides which of the four states a row is in, and
    the only place `doc_source_publish` rows get (re-)queued from a read.

    1. `catalogued` — the row already carries a real `egeria_external_ref_
       guid`. Detail is the GUID itself (the brief's "surfaced somewhere
       accessible" — the frontend puts it in a `title` attribute).
    2. `local_only` — the resource itself isn't published yet. Same rule as
       before this fix (`egeria_linkage.describe_publish_status`), unchanged.
    3. `publishing` — the resource IS published, no ref guid yet, and an
       outbox row for this source is `pending`/`running`.
    4. `publish_failed` — same, but the outbox row is `failed` (still being
       retried) or `dead` (retries exhausted — worded the same way per the
       fixed four-state vocabulary; a `dead` row is the rarer case, needs a
       human via the RFA `record_drain_outcome` already raises, and is not
       given a fifth wording of its own).

    Self-heals the gap this fix exists for: if the resource is published,
    the row has no ref guid, and NO outbox row is tracking it at all — a
    source declared before this fix landed, or a narrow race between
    "declare" and "this resource's publish landing" — one is queued right
    here rather than the row sitting unexplained forever. Idempotent: once
    queued, the next call finds the row and stops re-queuing.
    """
    ref_guid = row.get("egeria_external_ref_guid") or ""
    if ref_guid:
        return "catalogued", ref_guid
    if not is_published:
        return "local_only", ""
    outbox_row = registry.get_doc_source_outbox_row(entity_type, slug, row["id"])
    if outbox_row is None:
        element_id = enqueue_doc_source_publish(registry, entity_type, slug, row["id"], row["url"])
        _attempt_outbox_row_immediately(element_id)
        return "publishing", ""
    status = outbox_row.get("status")
    if status in ("failed", "dead"):
        return "publish_failed", outbox_row.get("last_error") or "unknown error"
    # 'pending' / 'running' / a 'done' row whose write-back hasn't been read
    # in THIS call yet (see _create_doc_source_publish — write-back happens
    # inside the same drain pass that marks the row done, so this is a rare,
    # self-correcting race, not a steady state).
    return "publishing", ""


@router.get("/{entity_type}/{slug}", response_model=DocSourcesResponse)
def list_doc_sources(entity_type: str, slug: str) -> DocSourcesResponse:
    registry = _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    _sync_egeria_read_back(registry, entity_type, slug, entity)
    status = _publish_status(registry, entity_type, slug, entity.egeria_asset_guid or "")
    rows = registry.list_doc_sources(entity_type, slug)
    outs = []
    in_egeria = 0
    for r in rows:
        state, detail = _compute_egeria_state(registry, entity_type, slug, r, status["is_published"])
        out = _out(r)
        out.egeria_state = state
        out.egeria_state_detail = detail
        if state == "catalogued":
            in_egeria += 1
        outs.append(out)
    return DocSourcesResponse(
        sources=outs, published=status["is_published"], publish_note=status["note"],
        in_egeria_count=in_egeria, local_count=len(outs) - in_egeria,
    )


@router.post("/{entity_type}/{slug}", response_model=DocSourceOut)
def add_doc_source(entity_type: str, slug: str, body: DocSourceCreate) -> DocSourceOut:
    registry = _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    url = body.url.strip()
    if not url or not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url must be an http(s) URL")

    row = registry.add_doc_source(entity_type, slug, url, label=body.label,
                                   source_type=body.source_type)
    # Probe immediately on add (the brief's step 2) — synchronous, so the
    # response already carries the state; the gate's "within five seconds"
    # is this call's own latency, not a follow-up poll.
    result = run_probe(url)
    row = registry.record_doc_source_probe(
        entity_type, slug, row["id"], state=result.state, status_code=result.status_code,
        elapsed_ms=result.elapsed_ms, title=result.title, byte_count=result.byte_count,
        error=result.error,
    )
    try:
        from resource_explorer.activity_logger import log_catalog

        log_catalog(
            registry, entity_type=entity_type, entity_slug=slug,
            entity_name=slug, entity_location=url, status="ok",
            summary=f"Declared documentation source: {body.label or url} ({result.state})",
        )
    except Exception:
        pass
    # Egeria publish-state fix: if the resource is ALREADY published, queue
    # this source's Egeria publish right now — _compute_egeria_state's
    # self-heal branch does the enqueue (no outbox row exists yet for a
    # brand-new source), so the response already carries "publishing" rather
    # than a silent local-only gap that would only close on the resource's
    # next full re-publish.
    status = _publish_status(registry, entity_type, slug, entity.egeria_asset_guid or "")
    state, detail = _compute_egeria_state(registry, entity_type, slug, row, status["is_published"])
    out = _out(row)
    out.egeria_state = state
    out.egeria_state_detail = detail
    return out


@router.post("/{entity_type}/{slug}/{source_id}/recheck", response_model=DocSourceOut)
def recheck_doc_source(entity_type: str, slug: str, source_id: str) -> DocSourceOut:
    registry = _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    row = registry.get_doc_source(entity_type, slug, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="documentation source not found")
    result = run_probe(row["url"])
    row = registry.record_doc_source_probe(
        entity_type, slug, source_id, state=result.state, status_code=result.status_code,
        elapsed_ms=result.elapsed_ms, title=result.title, byte_count=result.byte_count,
        error=result.error,
    )
    status = _publish_status(registry, entity_type, slug, entity.egeria_asset_guid or "")
    state, detail = _compute_egeria_state(registry, entity_type, slug, row, status["is_published"])
    out = _out(row)
    out.egeria_state = state
    out.egeria_state_detail = detail
    return out


@router.delete("/{entity_type}/{slug}/{source_id}")
def remove_doc_source(entity_type: str, slug: str, source_id: str) -> dict:
    registry = _registry()
    _resolve_entity(registry, entity_type, slug)
    row = registry.remove_doc_source(entity_type, slug, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="documentation source not found")
    # Removal deletes the local row AND queues the Egeria-side detach+delete
    # of the ExternalReference it created — only that one (the brief's
    # "Removal" rule) — through the SAME outbox/retry mechanism the publish
    # side uses (Egeria publish-state fix, 2026-09-29), rather than the
    # previous one-shot synchronous attempt with no retry if Egeria was
    # unreachable at that exact moment. The local row is already gone by the
    # time this runs, so there is nothing left to roll back if the Egeria
    # side fails or is slow — that's what the outbox's retry is for.
    egeria_unpublish = "not_applicable"
    if row.get("egeria_external_ref_guid"):
        element_id = enqueue_doc_source_unpublish(
            registry, entity_type, slug, row["egeria_external_ref_guid"])
        _attempt_outbox_row_immediately(element_id)
        egeria_unpublish = "queued"
    return {"removed": True, "id": source_id, "egeria_unpublish": egeria_unpublish}


def publish_local_doc_sources(entity_type: str, slug: str, asset_guid: str, *,
                               registry: ProjectRegistry | None = None) -> list[dict]:
    """Publish every locally-declared source with no Egeria reference yet
    as an `ExternalReference` on `asset_guid`. Called from the
    database/filesystem publish routes right after a successful publish —
    see `web/routes/databases.py`'s `publish_database_survey`. Best-effort
    per source; returns the per-source results so the caller can log/report
    which ones failed without the publish itself failing over it.
    """
    registry = registry or _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    out = []
    for row in registry.list_doc_sources(entity_type, slug):
        if row.get("egeria_external_ref_guid"):
            out.append({"id": row["id"], "ok": True, "skipped": "already published"})
            continue
        result = publish_doc_source(
            row, asset_guid, view_server=entity.egeria_server, platform_url=entity.egeria_url,
            user_id=entity.egeria_user, user_password=entity.egeria_password,
            display_name=entity.display_name,
        )
        if result["ok"] and result["ref_guid"]:
            registry.set_doc_source_egeria_ref(entity_type, slug, row["id"],
                                                result["ref_guid"], result.get("link_guid", ""))
        out.append({"id": row["id"], **result})
    return out
