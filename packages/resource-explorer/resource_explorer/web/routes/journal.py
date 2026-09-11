"""The journal — resource_explorer/journal.py, over HTTP."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from resource_explorer.auth import get_current_user
from resource_explorer.journal import Journal

router = APIRouter()


class JournalWrite(BaseModel):
    body: str
    suggest_to: list[str] = Field(default_factory=list)


@router.get("/{entity_type}/{slug}")
def list_entries(entity_type: str, slug: str) -> dict:
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
    try:
        return Journal().write(entity_type, slug, author=author, body=write.body, suggest_to=write.suggest_to)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
