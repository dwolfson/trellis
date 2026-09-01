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

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from resource_explorer.feedback_store import FeedbackStore
from resource_explorer.registry import ProjectRegistry

from resource_explorer.config import get_config
from resource_explorer.web.admin_auth import is_admin_request


def _require_admin(request: Request) -> None:
    """Gate an admin listing, matching routes/feedback.py's `_require_admin`.

    Added 2026-09-01 to close a real drift: this module's `/feedback` listing
    and `routes/feedback.py`'s were two implementations of one feature against
    two endpoints with two auth postures — one gated, one not — and on
    2026-09-01 the ungated one was widened to serve the page-level store as
    well. `admin_auth.is_admin_request` is fail-closed AND an admin token is
    configured here, so the gate was real and being bypassed rather than
    aspirational.

    `docs/admin-surface-options.md` names fixing this drift as the prerequisite
    before any further admin extraction: the one place RE already split a
    surface produced duplicated logic and divergent auth, which is an argument
    against repeating the split at larger scale until it is repaired.

    It also stops being optional once RE reaches the open demo environment
    (`docs/Backlog.md`, "Auth posture ..."), where the difference between a
    gated and an ungated feedback listing is the difference between a form and
    a mailing list.
    """
    if not is_admin_request(request, get_config().feedback):
        raise HTTPException(status_code=403, detail="Admin credential required")


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



#: Fields the page-level feedback store records that this route must NOT serve.
#:
#: `/api/feedback` (routes/feedback.py) gates on `admin_auth.is_admin_request`,
#: which is fail-closed by design — its docstring says it exists "only to gate
#: the feedback-triage admin endpoints", written to invert an Egeria Workspaces
#: bug where the equivalent check failed OPEN.
#:
#: **This route has no such gate**, and on 2026-09-01 it was widened to serve the
#: page-level store so the Admin pane would stop showing an empty list. That fix
#: was right and its scope was not: it routed data the gated endpoint protects
#: through an ungated one. Nothing was exposed in practice — no row carries an
#: email today — but the store has `wants_response` and `consent_to_contact`
#: columns, so emails are expected, and the next one would have been served to
#: anyone who could reach the port.
#:
#: Stripping is the INTERIM fix, agreed with Dan: it closes the exposure now
#: without emptying the pane, which gating would do until the frontend sends
#: `X-Admin-Token`. Gating this route properly is the real fix and is still
#: outstanding — when it lands, this stripping becomes redundant rather than
#: wrong, and the gated route can serve the full row.
#:
#: `message`, `rating`, `category`, `page`, `triage_status` and `created_at`
#: stay: they are the feedback itself, which is the point of the pane.
_CONTACT_FIELDS = ("email", "session_id", "user_agent", "viewport", "locale")


def _without_contact_fields(row: dict) -> dict:
    """A page-feedback row with contact/identifying fields removed.

    Removes the keys rather than blanking them. A blank `email` is
    indistinguishable from a row whose author left none — the absence-looks-like
    -a-value shape this codebase keeps removing — and a caller that sees no key
    at all cannot mistake it for a measured empty.
    """
    return {k: v for k, v in row.items() if k not in _CONTACT_FIELDS}

@router.get("/feedback")
def list_all_feedback(
    request: Request,
    limit: int = 200, entity_type: str = "", category: str = "", source: str = ""
) -> dict:
    """Every feedback item in one place, for Admin — from BOTH stores.

    There are two independent feedback systems, and until 2026-09-01 this
    route only read one of them:

      * `resource_feedback` (`ProjectRegistry.add_resource_feedback`, this
        module's `add_feedback` below) — per-resource, written from a
        resource's Curate tab.
      * `feedback` (`resource_explorer/feedback_store.py`) — the page-level
        widget reachable from anywhere in the app.

    A page-level submission and a per-resource one look, from the person who
    wrote it, exactly the same: feedback that was left and never showed up
    here. It was never dropped — the pane just never read the store it landed
    in. Diagnosed 2026-08-31 (Dan: "I added feedback on a page and it never
    makes it to the feedback pane of Admin").

    This combines both into one list rather than merging them: the two tables
    have genuinely different shapes (session/page/consent fields on one side,
    entity_type/slug on the other), and a real merge is a separate, deliberate
    task (see docs/Backlog.md) — not something to fold in as a side effect of
    fixing visibility. Each row carries `source: "page" | "resource"` so the
    two stay distinguishable until that task exists, and `source` is itself a
    filter for the same reason `entity_type`/`category` are.

    Declared before the /{entity_type}/{slug} route below only for readability;
    they cannot collide, since that one needs two path segments.

    Returns per-source counts (not a combined total, which would hide a store
    that is genuinely empty) alongside the rows, and `filtered` because an
    empty list is ambiguous on its own — "nobody has left feedback" and "your
    filter excluded everything" look identical, and only one of those is a
    fact worth stating plainly.
    """
    _require_admin(request)

    reg = _registry()
    resource_rows = reg.list_all_resource_feedback(
        limit=limit, entity_type=entity_type, category=category)
    resource_counts = reg.count_all_resource_feedback()

    page_store = FeedbackStore()
    # entity_type has no meaning for page-level feedback — it was never
    # recorded against a resource at all. A filter on it must exclude every
    # page row, not silently ignore the filter and show them regardless.
    page_rows = [] if entity_type else page_store.list(category=category or None, limit=limit)
    page_stats = page_store.stats()

    combined = [dict(r, source="resource") for r in resource_rows]
    # Full rows now. `_without_contact_fields` was the INTERIM fix while this
    # route was ungated (cb99d72); with the gate in place, stripping would leave
    # two equally-gated views of one store disagreeing about what it contains —
    # which is the drift this change exists to end. The helper is kept and
    # tested, since an ungated caller may exist again.
    combined += [dict(r, source="page") for r in page_rows]
    if source:
        combined = [r for r in combined if r["source"] == source]
    combined.sort(key=lambda r: r.get("created_at") or "", reverse=True)

    return {
        "feedback": combined[:limit],
        "counts": {
            "resource": resource_counts,
            "page": {"total": page_stats["total"]},
        },
        "filtered": bool(entity_type or category or source),
    }


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
