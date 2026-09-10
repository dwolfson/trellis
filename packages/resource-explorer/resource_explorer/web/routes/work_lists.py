"""Work lists and batch runs — the API half of the `/next` Scouting slice.

The one backend change the slice needed: **a batch enqueue** (a set of
resources plus an analysis, N rows in `runs`, a set id back) and **a read for
progress by set id**. Everything else in the slice is client work on top of
these.

Publishing to Egeria is its own endpoint and is never a side effect of
creating or editing a list — see `work_lists.WorkLists.publish`.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from resource_explorer.work_lists import WorkLists

log = logging.getLogger(__name__)
router = APIRouter()


def _requested_by() -> str:
    """The signed-in caller, for run attribution and per-user fairness."""
    try:
        from resource_explorer.a2a_auth import caller

        identity = caller()
        return getattr(identity, "user_id", "") or ""
    except Exception:
        return ""


class WorkListCreate(BaseModel):
    display_name: str
    entity_slugs: list[str] = Field(default_factory=list)
    description: str = ""
    entity_type: str = "repo"
    investigation: str = ""
    rationale: str = ""


class MemberUpdate(BaseModel):
    entity_slug: str
    rationale: str = ""
    confidence: int | None = None


class PromoteRequest(BaseModel):
    survivors: list[str]
    display_name: str = ""
    rationale: str = ""


class BatchRunRequest(BaseModel):
    analysis_id: str
    #: Omit to run across the work list's own members. Given explicitly, this
    #: wins — the caller may be running over a filtered subset of the list.
    entity_slugs: list[str] | None = None
    work_list_slug: str = ""


@router.get("/")
async def list_work_lists(investigation: str = "") -> list[dict]:
    return WorkLists().list_all(investigation=investigation)


@router.post("/")
async def create_work_list(body: WorkListCreate) -> dict:
    if not body.display_name.strip():
        raise HTTPException(status_code=400, detail="display_name is required")
    return WorkLists().create(
        body.display_name.strip(), body.entity_slugs,
        description=body.description, entity_type=body.entity_type,
        investigation=body.investigation, created_by=_requested_by(),
        rationale=body.rationale,
    )


# ── Batch runs ──────────────────────────────────────────────────────────
#
# Declared BEFORE the `/{slug}` routes deliberately, matching the
# convention in `analyses.py`: a literal path segment must be registered
# ahead of a single-segment path parameter, or `/runs/...` is liable to
# be captured as a work-list slug the moment either route grows a shape
# that overlaps.


@router.post("/runs/batch")
async def enqueue_batch(body: BatchRunRequest) -> dict:
    """Run one analysis across a set of resources, concurrently.

    Returns a `set_id` to watch. One `runs` row per resource, so one
    resource failing is one row failing — the rest still run, which is the
    whole point of doing this as a set rather than a loop in the browser.
    """
    wls = WorkLists()
    slugs = body.entity_slugs
    if slugs is None:
        if not body.work_list_slug:
            raise HTTPException(
                status_code=400,
                detail="give entity_slugs, or a work_list_slug to run across")
        wl = wls.get(body.work_list_slug)
        if not wl:
            raise HTTPException(
                status_code=404, detail=f"work list {body.work_list_slug!r} not found")
        slugs = [m["entity_slug"] for m in wl["members"]]
    if not slugs:
        raise HTTPException(status_code=400, detail="nothing to run — the set is empty")

    # Validate the analysis BEFORE queueing anything, so an unknown id is one
    # 400 rather than N rows that each fail a minute later in another process.
    from resource_explorer.workflows.analysis import resolve_analysis_plan

    try:
        resolve_analysis_plan(body.analysis_id)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown analysis {body.analysis_id!r}: {exc}") from exc

    return wls.enqueue_batch(
        body.analysis_id, slugs,
        work_list_slug=body.work_list_slug, requested_by=_requested_by())


@router.get("/runs/sets/{set_id}")
async def batch_progress(set_id: str) -> dict:
    """Which runs in this set are queued, running, done or failed.

    Derived from the `runs` rows on every read. A run row that has gone
    missing reports `unknown` rather than being counted as finished — an
    unobserved run is not a successful one.
    """
    progress = WorkLists().batch_progress(set_id)
    if progress is None:
        raise HTTPException(status_code=404, detail=f"run set {set_id!r} not found")
    return progress


@router.get("/{slug}")
async def get_work_list(slug: str) -> dict:
    wl = WorkLists().get(slug)
    if not wl:
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")
    return wl


@router.delete("/{slug}")
async def delete_work_list(slug: str) -> dict:
    """Remove the list locally. Any Egeria Collection it published stays."""
    wl = WorkLists().get(slug)
    if not wl:
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")
    WorkLists().delete(slug)
    return {"removed": slug,
            "egeria_collection_kept": bool(wl.get("egeria_guid")),
            "egeria_guid": wl.get("egeria_guid", "")}


@router.post("/{slug}/members")
async def set_member(slug: str, body: MemberUpdate) -> dict:
    wls = WorkLists()
    if not wls.get(slug):
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")
    wls.set_member(slug, body.entity_slug,
                   rationale=body.rationale, confidence=body.confidence)
    return wls.get(slug)


@router.delete("/{slug}/members/{entity_slug}")
async def remove_member(slug: str, entity_slug: str) -> dict:
    wls = WorkLists()
    if not wls.get(slug):
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")
    wls.remove_member(slug, entity_slug)
    return wls.get(slug)


@router.post("/{slug}/promote")
async def promote(slug: str, body: PromoteRequest) -> dict:
    """The survivors become a new, narrower list that records its parent."""
    try:
        return WorkLists().promote(
            slug, body.survivors, display_name=body.display_name,
            rationale=body.rationale, created_by=_requested_by())
    except KeyError:
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")


@router.post("/{slug}/publish")
async def publish(slug: str) -> dict:
    """Publish to Egeria as a `WorkingSet` Collection.

    Explicit, never automatic. The Collection is created synchronously (its
    GUID is needed to attach anything); the memberships are queued to the
    outbox and applied by whichever worker drains it, each carrying its
    `membershipRationale`.
    """
    try:
        return WorkLists().publish(slug)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"work list {slug!r} not found")
    except Exception as exc:
        log.exception("publishing work list %s failed", slug)
        raise HTTPException(status_code=502,
                            detail=f"{type(exc).__name__}: {exc}") from exc
