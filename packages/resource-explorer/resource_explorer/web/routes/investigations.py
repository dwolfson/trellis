"""Investigations — the framing step ahead of Scouting.

`docs/investigation-framing-design.md` §1: an Investigation is one body of work,
"the thing the new tab creates and the context everything else runs inside."

Deliberately NOT a ninth intent. CLAUDE.md rule 17 fixes the eight canonical
intent labels, and this is not another kind of work done *to* a resource — it is
the frame the other eight run inside. It therefore sits at header level with
Activity and Admin, not in `#intent-nav`.

Local-first: an investigation exists with a nullable `egeria_project_guid`, so
all three of §1's starting modes (bind an existing Egeria Project, create a new
one, or stay purely local) produce ONE local row. Promotion is a fill-in, not a
migration.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()  # prefix/tags applied in web/app.py, matching every other route module


class InvestigationCreate(BaseModel):
    display_name: str
    description: str = ""
    purposes: list[str] = Field(default_factory=list)
    egeria_project_guid: str = ""
    egeria_project_qualified_name: str = ""


class MemberSpec(BaseModel):
    entity_type: str
    entity_slug: str
    resource_use: str = ""
    state: str = "in-scope"


class EgeriaProjectBinding(BaseModel):
    """The same context shape the publish path already speaks, so folding the
    session-wide control into the investigation teaches nothing downstream a
    new vocabulary."""
    status: str = "unset"
    egeria_project_guid: str = ""
    egeria_project_qualified_name: str = ""
    free_text_name: str = ""


class MembersUpdate(BaseModel):
    members: list[MemberSpec] = Field(default_factory=list)


def _registry():
    from resource_explorer.registry import ProjectRegistry
    return ProjectRegistry()


@router.get("/purposes")
async def list_purposes() -> dict:
    """The Purpose vocabulary, served rather than hardcoded in the SPA.

    These are `ProjectCharter.purposes` (design §2) — not a new RE vocabulary —
    and the same eight values all 41 catalog questions are tagged with, so the
    UI cannot drift from what ranking will actually key on.
    """
    from resource_explorer.registry import ProjectRegistry
    return {"purposes": list(ProjectRegistry.VALID_PURPOSES)}


@router.get("/")
async def list_investigations(include_closed: bool = False) -> list[dict]:
    return _registry().list_investigations(include_closed=include_closed)


@router.post("/")
async def create_investigation(req: InvestigationCreate) -> dict:
    if not req.display_name.strip():
        raise HTTPException(status_code=400, detail="display_name is required")
    try:
        return _registry().create_investigation(
            req.display_name.strip(), description=req.description,
            purposes=req.purposes,
            egeria_project_guid=req.egeria_project_guid,
            egeria_project_qualified_name=req.egeria_project_qualified_name,
        )
    except ValueError as exc:
        # An unrecognised purpose is a 400, not a silent drop — a purpose that
        # does not exist would rank nothing and look like an empty result.
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/{slug}")
async def get_investigation(slug: str) -> dict:
    inv = _registry().get_investigation(slug)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return inv


@router.get("/{slug}/members")
async def get_members(slug: str) -> list[dict]:
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.list_investigation_members(slug)


@router.put("/{slug}/members")
async def set_members(slug: str, req: MembersUpdate) -> list[dict]:
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.set_investigation_members(slug, [m.model_dump() for m in req.members])


@router.post("/{slug}/close")
async def close_investigation(slug: str) -> dict:
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.close_investigation(slug)


@router.put("/{slug}/egeria-project")
async def bind_egeria_project(slug: str, req: EgeriaProjectBinding) -> dict:
    """Bind (or clear) this investigation's Egeria Project.

    §1 makes binding to an Egeria Project one of the three ways to START an
    investigation — so it belongs here rather than as a parallel session-wide
    setting. Two controls answering "which project does this work belong to"
    is two answers to one question.
    """
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.set_investigation_egeria_project(slug, req.model_dump())
