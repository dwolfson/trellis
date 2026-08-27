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
    project_classification: str = "StudyProject"
    egeria_project_guid: str = ""
    egeria_project_qualified_name: str = ""


class InvestigationUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    purposes: list[str] | None = None


class EgeriaProjectBinding(BaseModel):
    """The same context shape the publish path already speaks, so folding the
    session-wide control into the investigation teaches nothing downstream a
    new vocabulary."""
    status: str = "unset"
    egeria_project_guid: str = ""
    egeria_project_qualified_name: str = ""
    free_text_name: str = ""


class MemberAdd(BaseModel):
    entity_type: str
    entity_slug: str
    membership_rationale: str = ""
    state: str = "in-scope"


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
            project_classification=req.project_classification,
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
    """What is in scope for this investigation.

    Flattened deliberately: storage is the two-hop Egeria shape (Project
    --ResourceList--> WorkingSet --CollectionMembership--> resource), but every
    caller only wants "what is in scope", so they should not have to walk it.
    """
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.list_investigation_members(slug)


@router.post("/{slug}/members")
async def add_member(slug: str, req: MemberAdd) -> list[dict]:
    """Add one resource to this investigation's working set.

    The working set is created lazily here rather than at investigation
    creation, so a brand-new investigation genuinely has none — which is what
    makes the empty sidebar an honest prompt to go and scout rather than an
    empty shell that looks broken.
    """
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    ws = reg.get_or_create_working_set(slug)
    reg.add_working_set_member(
        ws["slug"], req.entity_type, req.entity_slug,
        membership_rationale=req.membership_rationale, state=req.state,
    )
    return reg.list_investigation_members(slug)


@router.delete("/{slug}/members/{entity_type}/{entity_slug}")
async def remove_member(slug: str, entity_type: str, entity_slug: str) -> list[dict]:
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    ws_slug = reg.investigation_working_set_slug(slug)
    if ws_slug:
        reg.remove_working_set_member(ws_slug, entity_type, entity_slug)
    return reg.list_investigation_members(slug)


@router.post("/{slug}/close")
async def close_investigation(slug: str) -> dict:
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.close_investigation(slug)


@router.post("/{slug}/suspend")
async def suspend_investigation(slug: str) -> dict:
    """Pause without unbinding — see INVESTIGATION_STATUSES for why this is a
    different word from `closed` rather than the same action under a nicer name."""
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.set_investigation_status(slug, "suspended")


@router.post("/{slug}/reopen")
async def reopen_investigation(slug: str) -> dict:
    """The route that did not exist: `close` had no way back except a direct
    SQL update, which is what turned one accidental click into a data-recovery
    incident. Works from either `closed` or `suspended` — both land on `open`."""
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.set_investigation_status(slug, "open")


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
    result = reg.set_investigation_egeria_project(slug, req.model_dump())

    # Binding to an existing Project is one of the two ways to end up with one,
    # and both need the same thing next: somewhere in Egeria for the membership
    # to live. Without this, binding produced a Project with no working-set
    # Collection and the membership had nowhere to go — a gap promotion did not
    # have, purely because it happened to create both.
    #
    # Best-effort and off the event loop: a working set that cannot be created
    # right now must not fail the binding itself, which is a local decision and
    # already valid. ensure_working_set is idempotent, so the next attempt
    # completes it rather than duplicating.
    if req.status == "linked" and req.egeria_project_guid:
        import asyncio

        from resource_explorer.surveyors.egeria_investigation_publisher import (
            EgeriaInvestigationPublisher,
        )

        ws = await asyncio.to_thread(
            EgeriaInvestigationPublisher(reg).ensure_working_set, slug
        )
        result["working_set"] = {
            "collection_guid": ws.collection_guid,
            "resource_list_linked": ws.resource_list_linked,
            "errors": ws.errors,
        }
    return result


@router.post("/{slug}/promote")
async def promote_to_egeria(slug: str) -> dict:
    """Create the Egeria side of this investigation — Project, working-set
    Collection, ResourceList and CollectionMembership.

    The local record was shaped for this from the start, so it is a replay
    rather than a migration. Partial success is a real outcome and is reported
    as such: a member whose repo has never been published has no asset GUID to
    link, and inventing one would be worse than saying so.
    """
    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    reg = _registry()
    inv = reg.get_investigation(slug)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")

    # In a thread, not inline. pyegeria's synchronous methods drive their own
    # event loop internally, so calling them from inside FastAPI's running loop
    # raises "this event loop is already running" — which a CLI test never sees,
    # because there is no loop running there. Same asyncio.to_thread treatment
    # every other long-running route here already uses (run_survey,
    # refresh_project).
    import asyncio

    result = await asyncio.to_thread(EgeriaInvestigationPublisher(reg).promote, slug)
    if result.project_guid:
        # Record the binding even on partial success — the Project genuinely
        # exists now, and leaving the local row unbound would orphan it.
        reg.set_investigation_egeria_project(slug, {
            "status": "linked",
            "egeria_project_guid": result.project_guid,
            "egeria_project_qualified_name": result.project_qualified_name,
        })
    return result.as_dict()


@router.patch("/{slug}")
async def update_investigation(slug: str, req: InvestigationUpdate) -> dict:
    """Rename or re-describe. The slug is an identifier and never changes —
    members, the Egeria binding and inherited context rows all reference it."""
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    try:
        return reg.update_investigation(
            slug, display_name=req.display_name, description=req.description,
            purposes=req.purposes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/{slug}/relink-members")
async def relink_members(slug: str) -> dict:
    """Re-attach this investigation's in-scope resources to its Egeria working set.

    promote() links members once and then refuses to run again, so members that
    had no asset GUID at promotion time — all of them, if the investigation was
    promoted before its repos were published — had no way to be linked
    afterwards. Idempotent: CollectionMembership is uni-link, so re-attaching an
    already-attached member is an upsert.
    """
    import asyncio

    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    res = await asyncio.to_thread(
        EgeriaInvestigationPublisher(reg).relink_members, slug
    )
    return res.as_dict()


@router.post("/{slug}/sync-egeria")
async def sync_egeria_project(slug: str) -> dict:
    """Push this investigation's name/description to its Egeria Project.

    Separate from PATCH deliberately: renaming is a local edit and must not fail
    because Egeria is unreachable. But leaving the two permanently disagreeing
    about the same body of work is the drift this frame exists to prevent, so
    the sync is offered explicitly rather than skipped.
    """
    import asyncio

    from resource_explorer.surveyors.egeria_investigation_publisher import (
        EgeriaInvestigationPublisher,
    )

    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    res = await asyncio.to_thread(
        EgeriaInvestigationPublisher(reg).sync_project_properties, slug
    )
    return res.as_dict()


@router.get("/{slug}/dispositions")
async def get_dispositions(slug: str) -> dict:
    """{disposition: [members]} for this investigation.

    Derived from WorkingSet membership rather than stored separately — a
    resource's disposition within an investigation IS which WorkingSet it sits
    in, so there is only one place it can disagree with itself: none.
    """
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    return reg.investigation_dispositions(slug)


@router.post("/{slug}/dispositions/{entity_type}/{entity_slug}")
async def set_disposition(slug: str, entity_type: str, entity_slug: str,
                          disposition: str = "", rationale: str = "") -> dict:
    """Set (or clear) a resource's disposition within this investigation.

    Clearing leaves it in the Folio — in scope, unjudged — rather than removing
    it, because "we have not decided yet" is a real state and losing the
    resource would be the wrong way to express it.
    """
    reg = _registry()
    if not reg.get_investigation(slug):
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")
    if disposition and disposition != "undecided" and disposition not in reg.WORKING_SET_DISPOSITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"unknown disposition '{disposition}'; valid: {list(reg.WORKING_SET_DISPOSITIONS)}",
        )
    return reg.set_investigation_disposition(slug, entity_type, entity_slug,
                                             disposition, rationale=rationale)


@router.get("/{slug}/next-steps")
async def next_steps(slug: str) -> dict:
    """What this investigation still lacks, as offers rather than a form.

    The creation form asks only what §1 says an investigation IS — a name, why
    it exists, and how it relates to Egeria. Everything else is surfaced here,
    where the absence already is: an investigation with no resources says so and
    points at Scouting; one with no Egeria binding offers to make one.

    Deliberately phrased as offers. A scheduled run has nobody to ask and must
    not block; an interactive session can act on the same list. Neither is
    prompted, and an unanswered offer is a standing offer, not an open question.
    """
    reg = _registry()
    inv = reg.get_investigation(slug)
    if not inv:
        raise HTTPException(status_code=404, detail=f"Investigation '{slug}' not found")

    steps: list[dict] = []
    if not inv.get("purposes"):
        steps.append({
            "id": "declare_purpose",
            "title": "No purpose declared",
            "detail": "Purpose is why this work exists — it ranks what gets proposed. "
                      "Without it nothing can be ordered by relevance.",
            "action": "edit",
        })
    if not inv.get("member_count"):
        steps.append({
            "id": "add_resources",
            "title": "Nothing in scope yet",
            "detail": "Find resources in Scouting and add them to the working set. "
                      "An investigation with no resources cannot survey anything.",
            "action": "scouting",
        })
    else:
        # The remainder, not merely "has anyone judged anything". Keying on the
        # latter let ONE judged resource out of nineteen report the whole
        # investigation as judged — and the summary line above this list then
        # said "Nothing outstanding", which was false while 14 sat unjudged.
        judged = {
            (m["entity_type"], m["entity_slug"])
            for members in reg.investigation_dispositions(slug).values()
            for m in members
        }
        unjudged = [
            m for m in reg.list_investigation_members(slug)
            if (m["entity_type"], m["entity_slug"]) not in judged
        ]
        if unjudged:
            none_yet = not judged
            steps.append({
                "id": "set_dispositions",
                "title": "Nothing judged yet" if none_yet
                         else f"{len(unjudged)} resource(s) not judged yet",
                "detail": (f"{inv['member_count']} resource(s) in scope, none marked. "
                           if none_yet else
                           f"{len(judged)} of {inv['member_count']} resource(s) in scope carry a "
                           f"disposition; {len(unjudged)} do not. ")
                          + "Dispositions are how this investigation says which ones matter.",
                "action": "disposition",
            })
    if inv.get("egeria_project_status") != "linked":
        steps.append({
            "id": "bind_egeria",
            "title": "Local only — not in Egeria",
            "detail": "Bind to an existing Egeria Project or create one. Resources in "
                      "scope then inherit that binding instead of each needing its own.",
            "action": "egeria",
        })
    return {"investigation": slug, "steps": steps, "complete": not steps}
