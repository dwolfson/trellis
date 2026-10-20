"""The journal — resource_explorer/journal.py, over HTTP."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resource_explorer.auth import get_current_user
from resource_explorer.journal import Journal

router = APIRouter()

#: An investigation's journal is the same table keyed by this entity type. Its entries stay in RE until the
#: investigation is promoted (it has no Egeria Project to hold a Note until then).
INVESTIGATION = "investigation"


def _check_investigation(entity_type: str, slug: str) -> None:
    """An investigation journal exists only for an investigation the caller may see. `get_investigation` answers
    None for both "no such slug" and "not yours" on purpose, so a private investigation's journal is a 404 to
    everyone else, never a 403 that would confirm it exists."""
    if entity_type != INVESTIGATION:
        return
    from resource_explorer.registry import ProjectRegistry

    if not ProjectRegistry().get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")


class JournalWrite(BaseModel):
    body: str
    suggest_to: list[str] = Field(default_factory=list)
    compile_id: str | None = None


@router.get("/{entity_type}/{slug}")
def list_entries(entity_type: str, slug: str) -> dict:
    _check_investigation(entity_type, slug)
    j = Journal()
    return {"entries": j.entries(entity_type, slug), "suggested_to": j.suggested_targets(entity_type, slug)}


@router.post("/{entity_type}/{slug}")
def write_entry(entity_type: str, slug: str, write: JournalWrite, request: Request) -> dict:
    """Append one entry. The author is the signed-in user, stamped here;
    anonymous is refused rather than recorded as nobody's, and the payload
    carries no author field to forge."""
    user = get_current_user(request)
    author = (user or {}).get("user_id") or (user or {}).get("sub") or (user or {}).get("username") or ""
    if not author:
        raise HTTPException(status_code=401, detail="Sign in to write in the journal — an entry needs an author.")
    _check_investigation(entity_type, slug)
    if entity_type == INVESTIGATION and write.suggest_to:
        # Suggestion routes a RESOURCE to an audience's work list; an investigation is not a work-list member.
        raise HTTPException(status_code=422, detail="An investigation's journal entry cannot be suggested to an audience.")
    try:
        return Journal().write(entity_type, slug, author=author, body=write.body, suggest_to=write.suggest_to,
                               compile_id=write.compile_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
