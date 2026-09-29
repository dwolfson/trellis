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

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer.doc_source_egeria import (
    publish_doc_source,
    read_back_doc_sources,
    unpublish_doc_source,
)
from resource_explorer.doc_source_probe import probe as run_probe
from resource_explorer.egeria_linkage import describe_publish_status
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)
router = APIRouter()

_ENTITY_TABLES = ("database", "filesystem")


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


def _resolve_entity(registry: ProjectRegistry, entity_type: str, slug: str):
    if entity_type == "database":
        entity = registry.get_database(slug)
    elif entity_type == "filesystem":
        entity = registry.get_filesystem(slug)
    else:
        raise HTTPException(status_code=400,
                             detail=f"documentation sources are not supported for entity_type={entity_type!r}")
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


class DocSourcesResponse(BaseModel):
    sources: list[DocSourceOut]
    published: bool
    publish_note: str = ""


def _out(row: dict) -> DocSourceOut:
    return DocSourceOut(**{k: row.get(k) for k in DocSourceOut.model_fields})


@router.get("/{entity_type}/{slug}", response_model=DocSourcesResponse)
def list_doc_sources(entity_type: str, slug: str) -> DocSourcesResponse:
    registry = _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    _sync_egeria_read_back(registry, entity_type, slug, entity)
    status = _publish_status(registry, entity_type, slug, entity.egeria_asset_guid or "")
    rows = registry.list_doc_sources(entity_type, slug)
    return DocSourcesResponse(
        sources=[_out(r) for r in rows], published=status["is_published"], publish_note=status["note"],
    )


@router.post("/{entity_type}/{slug}", response_model=DocSourceOut)
def add_doc_source(entity_type: str, slug: str, body: DocSourceCreate) -> DocSourceOut:
    registry = _registry()
    _resolve_entity(registry, entity_type, slug)
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
    return _out(row)


@router.post("/{entity_type}/{slug}/{source_id}/recheck", response_model=DocSourceOut)
def recheck_doc_source(entity_type: str, slug: str, source_id: str) -> DocSourceOut:
    registry = _registry()
    _resolve_entity(registry, entity_type, slug)
    row = registry.get_doc_source(entity_type, slug, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="documentation source not found")
    result = run_probe(row["url"])
    row = registry.record_doc_source_probe(
        entity_type, slug, source_id, state=result.state, status_code=result.status_code,
        elapsed_ms=result.elapsed_ms, title=result.title, byte_count=result.byte_count,
        error=result.error,
    )
    return _out(row)


@router.delete("/{entity_type}/{slug}/{source_id}")
def remove_doc_source(entity_type: str, slug: str, source_id: str) -> dict:
    registry = _registry()
    entity = _resolve_entity(registry, entity_type, slug)
    row = registry.remove_doc_source(entity_type, slug, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="documentation source not found")
    # Removal deletes the source row AND the ExternalReference it created —
    # only that one (the brief's "Removal" rule). Best-effort: the local
    # row is already gone by the time this runs, so an Egeria failure here
    # is reported but does not resurrect the row.
    egeria_error = ""
    if row.get("egeria_external_ref_guid"):
        result = unpublish_doc_source(
            row["egeria_external_ref_guid"], entity.egeria_asset_guid or "",
            view_server=entity.egeria_server, platform_url=entity.egeria_url,
            user_id=entity.egeria_user, user_password=entity.egeria_password,
        )
        if not result["ok"]:
            egeria_error = result["error"]
    return {"removed": True, "id": source_id, "egeria_error": egeria_error}


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
