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
