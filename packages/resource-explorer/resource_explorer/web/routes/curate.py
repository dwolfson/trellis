"""Curate API — tags, resource-level feedback, and curator notes.

Curate is about making a resource easier to find and more trustworthy to
reuse (search tags, feedback, curator commentary) — distinct from
Enrichment (context.py), which is about recording facts about the
resource itself (environment, ownership, sensitivity, ...).

Digital-product evaluation, sample-dataset creation, and quality-issue
remediation are explicitly NOT covered here yet — they're real, separate
design questions (data model, workflow) that haven't been scoped, not an
oversight. See docs/curate-followups.md.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer.registry import ProjectRegistry

router = APIRouter()


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


# ── Tags ─────────────────────────────────────────────────────────────────────

class TagCreate(BaseModel):
    tag: str


@router.get("/tags")
def list_all_tags() -> list[dict]:
    """Distinct tags across all resources, with usage counts — backs
    autocomplete and browse-by-tag."""
    return _registry().list_all_tags()


# NOTE: /tags/{tag}/resources is declared before /tags/{entity_type}/{slug}
# deliberately — both are 2-segment paths under /tags, and Starlette matches
# routes in declaration order, so a route declared after an equally-shaped
# path-param route is unreachable (the same class of bug already documented
# in analyses.py's /perspectives route).
@router.get("/tags/{tag}/resources")
def resources_by_tag(tag: str) -> list[dict]:
    return _registry().list_resources_by_tag(tag)


@router.get("/tags/{entity_type}/{slug}")
def list_tags(entity_type: str, slug: str) -> list[str]:
    return _registry().list_resource_tags(entity_type, slug)


@router.post("/tags/{entity_type}/{slug}")
def add_tag(entity_type: str, slug: str, body: TagCreate) -> dict:
    tag = body.tag.strip().lower()
    if not tag:
        raise HTTPException(status_code=400, detail="tag must not be empty")
    _registry().add_resource_tag(entity_type, slug, tag)
    return {"status": "success", "tag": tag}


@router.delete("/tags/{entity_type}/{slug}/{tag}")
def remove_tag(entity_type: str, slug: str, tag: str) -> dict:
    _registry().remove_resource_tag(entity_type, slug, tag)
    return {"status": "success"}


# ── Feedback ─────────────────────────────────────────────────────────────────

class FeedbackCreate(BaseModel):
    rating: int | None = None
    category: str = ""
    message: str


@router.get("/feedback/{entity_type}/{slug}")
def list_feedback(entity_type: str, slug: str) -> list[dict]:
    return _registry().list_resource_feedback(entity_type, slug)


@router.post("/feedback/{entity_type}/{slug}")
def add_feedback(entity_type: str, slug: str, body: FeedbackCreate) -> dict:
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
    return _registry().add_resource_feedback(entity_type, slug, body.rating, body.category, body.message)


# ── Curator notes ────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    note: str


@router.get("/notes/{entity_type}/{slug}")
def list_notes(entity_type: str, slug: str) -> list[dict]:
    return _registry().list_curator_notes(entity_type, slug)


@router.post("/notes/{entity_type}/{slug}")
def add_note(entity_type: str, slug: str, body: NoteCreate) -> dict:
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="note must not be empty")
    return _registry().add_curator_note(entity_type, slug, body.note)


@router.delete("/notes/{note_id}")
def delete_note(note_id: str) -> dict:
    if not _registry().delete_curator_note(note_id):
        raise HTTPException(status_code=404, detail="Note not found")
    return {"status": "success"}


# ── Architecture component verdicts ─────────────────────────────────────────
#
# First slice of docs/Backlog.md "take architecture results into Curate":
# accept / reject / retype a single proposed component (§4.1a's proposal
# framing, §3.3b/§3.4's Confidence/ContentStatus axis — not a new
# vocabulary). scope_locator is the same join key architecture_recovery
# findings use (a component's path prefix); the results reader
# (_architecture_recovery_results) merges the latest verdict onto each
# component it returns.

class ComponentVerdictCreate(BaseModel):
    scope_locator: str
    verdict: str  # "accepted" | "rejected" | "retyped"
    retyped_to: str = ""  # required (and only meaningful) when verdict="retyped"
    note: str = ""


@router.get("/component-verdicts/{entity_type}/{slug}")
def list_component_verdicts(entity_type: str, slug: str) -> dict[str, dict]:
    """{scope_locator: latest verdict} for every component this resource has
    a curator verdict on — the same shape merged onto each component by
    _architecture_recovery_results."""
    return _registry().get_component_verdicts(entity_type, slug)


def _materialize_if_accepted(registry: ProjectRegistry, entity_type: str, slug: str,
                              scope_locator: str, verdict: str) -> dict | None:
    """docs/architecture-recovery-report-then-curate.md — acting on the
    decision, not just recording it. Only 'accepted' triggers a real Egeria
    write (see materializer.py's module docstring for the full scope). Only
    wired for entity_type='repo' today, the only kind architecture_recovery
    runs against — a database/filesystem proposal kind would need its own
    materializer, not this one reused past what it was built for.

    Returns None when nothing was attempted (wrong verdict, wrong entity
    type, or the component's own finding row is gone — e.g. withdrawn since
    the review surface last loaded). Never raises: a materialization
    failure is reported in the field the caller merges into the response,
    the same non-fatal-but-visible shape as EgeriaPublisher.publish()'s
    annotation_types_warning, since the verdict itself is already saved and
    real regardless of whether Egeria was reachable just now.
    """
    if verdict != "accepted" or entity_type != "repo":
        return None
    rows = [r for r in registry.query_findings_all_runs(slug, "architecture_recovery", scope_locator)
            if r["check_name"] == "component"]
    if not rows:
        return {"status": "error", "error": "no component finding at this scope to materialize"}
    latest = max(rows, key=lambda r: r["surveyed_at"])
    import json as _json
    detail = _json.loads(latest.get("detail_json") or "{}") if latest.get("detail_json") else {}
    from resource_explorer.surveyors.arch_recovery.materializer import (
        ComponentMaterializer, MaterializationError,
    )
    try:
        return ComponentMaterializer(registry=registry).materialize(
            entity_type, slug, scope_locator,
            name=detail.get("name", scope_locator),
            component_type=detail.get("type") or "",
            perspective=detail.get("perspective", ""),
            confidence=latest.get("confidence", 0),
        )
    except MaterializationError as exc:
        return {"status": "error", "error": str(exc)}


@router.post("/component-verdicts/{entity_type}/{slug}")
def add_component_verdict(entity_type: str, slug: str, body: ComponentVerdictCreate) -> dict:
    if not body.scope_locator.strip():
        raise HTTPException(status_code=400, detail="scope_locator must not be empty")
    if body.verdict not in ProjectRegistry.COMPONENT_VERDICTS:
        raise HTTPException(
            status_code=400,
            detail=f"verdict must be one of {sorted(ProjectRegistry.COMPONENT_VERDICTS)}, got {body.verdict!r}",
        )
    if body.verdict == "retyped" and not body.retyped_to.strip():
        raise HTTPException(status_code=400, detail="retyped_to is required when verdict='retyped'")
    registry = _registry()
    verdict = registry.record_component_verdict(
        entity_type, slug, body.scope_locator, body.verdict, body.retyped_to, body.note,
    )
    materialization = _materialize_if_accepted(
        registry, entity_type, slug, body.scope_locator, body.verdict,
    )
    if materialization is not None:
        verdict["materialization"] = materialization
    return verdict


@router.get("/component-verdicts/{entity_type}/{slug}/history")
def component_verdict_history(entity_type: str, slug: str, scope_locator: str) -> list[dict]:
    """Full verdict trail for one component, newest first — scope_locator as
    a query param (not a path segment) since it's a path prefix and routinely
    contains slashes."""
    return _registry().list_component_verdict_history(entity_type, slug, scope_locator)
