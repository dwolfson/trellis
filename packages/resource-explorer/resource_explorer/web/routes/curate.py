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

from resource_explorer.auth import get_current_user
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


def _require_author(request: Request, action: str) -> str:
    """The signed-in user id, or 401. EVERY write route for tags, resource
    feedback and curator notes calls this first (a test fails if one doesn't).

    The author comes from the session, never from the request body: the write
    models have no `author` field, and pydantic drops unknown keys. Mirrors
    `routes/journal.py` and the report acts: anonymous is refused rather than
    recorded as nobody's. Resolved here, in the request thread, and passed to
    the registry as an explicit argument — never read from a ContextVar inside
    a bare `threading.Thread`, which would drop the caller and write ''.
    """
    user = get_current_user(request)
    author = (user or {}).get("user_id") or (user or {}).get("sub") or (user or {}).get("username") or ""
    if not author:
        raise HTTPException(
            status_code=401,
            detail=f"Sign in to {action} — a tag, rating or note needs an author.",
        )
    return author


def _registry() -> ProjectRegistry:
    return ProjectRegistry()


# The materialization workflows moved to resource_explorer/workflows/curate.py
# in step 2b (plan §3: web-only code sitting above the already-core
# ComponentMaterializer/BlueprintMaterializer). The routes below are thin: they
# validate, record the verdict, and merge whatever the workflow reports.
from resource_explorer.workflows.curate import (  # noqa: E402
    CurationDenied,
    find_candidate_blueprint as _find_candidate_blueprint,
    materialize_blueprint_if_accepted as _materialize_blueprint_if_accepted,
    materialize_component_if_accepted as _materialize_if_accepted,
    owner_of as _owner_of,
    NODE_PROMOTION_BLUEPRINT,
    NODE_PROMOTION_COMPONENT,
    promote_to_publish_zones as _promote_to_publish_zones,
    record_promotion as _record_promotion,
    require_curation_rights as _require_curation_rights,
    slug_to_scope_map as _slug_to_scope_map,
)


def _authorize_curation(registry: ProjectRegistry, entity_type: str, slug: str,
                        scope_locator: str) -> None:
    """403 unless the caller owns this element or holds a curator role.

    The decision itself lives in `workflows/curate` so the CLI and the A2A
    surface inherit it (plan §4: "enforced at the workflow layer so the CLI
    and A2A honour it too"); this function is only the HTTP shape of the
    same answer.
    """
    try:
        _require_curation_rights(_owner_of(registry, entity_type, slug, scope_locator))
    except CurationDenied as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


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


@router.get("/tags-detail/{entity_type}/{slug}")
def list_tags_detail(entity_type: str, slug: str) -> list[dict]:
    """Tags with who added them: [{tag, created_at, author, authored,
    author_label}]. `author` is None for rows from before authors were
    recorded (`authored` false, `author_label` the words to show)."""
    return _registry().list_resource_tags_with_authors(entity_type, slug)


@router.post("/tags/{entity_type}/{slug}")
def add_tag(entity_type: str, slug: str, body: TagCreate, request: Request) -> dict:
    author = _require_author(request, "add a tag")
    tag = body.tag.strip().lower()
    if not tag:
        raise HTTPException(status_code=400, detail="tag must not be empty")
    _registry().add_resource_tag(entity_type, slug, tag, author=author)
    return {"status": "success", "tag": tag, "author": author}


@router.delete("/tags/{entity_type}/{slug}/{tag}")
def remove_tag(entity_type: str, slug: str, tag: str, request: Request) -> dict:
    author = _require_author(request, "remove a tag")
    reg = _registry()
    reg.remove_resource_tag(entity_type, slug, tag)
    # A removal leaves no row to carry an author, so who removed it is
    # recorded in the activity log.
    import uuid
    from datetime import datetime, timezone
    from resource_explorer.registry import ActivityEntry
    reg.write_activity(ActivityEntry(
        id=str(uuid.uuid4()), ts=datetime.now(timezone.utc).isoformat(),
        operation="curate_tag_removed", intent="enrichment",
        entity_type=entity_type, entity_slug=slug,
        summary=f"tag {tag!r} removed by {author}",
        annotations=[{"tag": tag, "removed_by": author}],
    ))
    return {"status": "success", "removed_by": author}


# SEAM (not implemented, by owner ruling 2026-10-01): tags and journal entries
# may later be published to Egeria (InformalTag / note log) when the resource is
# already catalogued. Nothing in this module writes to Egeria; the future hook
# is `_publish_curation_to_egeria` below, deliberately a no-op.
def _publish_curation_to_egeria(entity_type: str, slug: str, kind: str, payload: dict) -> None:
    """Placeholder for the later Egeria publish of a tag or journal entry."""
    return None


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
def add_feedback(entity_type: str, slug: str, body: FeedbackCreate, request: Request) -> dict:
    author = _require_author(request, "leave feedback")
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="message must not be empty")
    if body.rating is not None and not (1 <= body.rating <= 5):
        raise HTTPException(status_code=400, detail="rating must be between 1 and 5")
    return _registry().add_resource_feedback(entity_type, slug, body.rating, body.category, body.message,
                                           author=author)


# ── Curator notes ────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    note: str


@router.get("/notes/{entity_type}/{slug}")
def list_notes(entity_type: str, slug: str) -> list[dict]:
    return _registry().list_curator_notes(entity_type, slug)


@router.post("/notes/{entity_type}/{slug}")
def add_note(entity_type: str, slug: str, body: NoteCreate, request: Request) -> dict:
    author = _require_author(request, "add a note")
    if not body.note.strip():
        raise HTTPException(status_code=400, detail="note must not be empty")
    return _registry().add_curator_note(entity_type, slug, body.note, author=author)


@router.delete("/notes/{note_id}")
def delete_note(note_id: str, request: Request) -> dict:
    """Delete a LEGACY unsigned note. Notes are append-only like the journal:
    a signed note is refused (409), amended by adding a later note instead."""
    _require_author(request, "delete a note")
    reg = _registry()
    note = reg.get_curator_note(note_id)
    if note is None:
        raise HTTPException(status_code=404, detail="Note not found")
    if note["authored"]:
        raise HTTPException(
            status_code=409,
            detail="A signed note cannot be deleted — notes are append-only. "
                   "Add a later note to amend it.",
        )
    if not reg.delete_curator_note(note_id):
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
    _architecture_recovery_results.

    Filters out verdict_target='blueprint' rows (added 2026-09-03, Phase B):
    get_component_verdicts' own docstring says it returns both mixed and
    leaves filtering to the caller — this route's name and its one existing
    consumer (_architecture_recovery_results, keyed by scope_locator) both
    promise component verdicts specifically, so a blueprint verdict's key
    (f"{perspective}::{cluster_name}") appearing here would be a surprising,
    if practically harmless, leak. Mirrors list_blueprint_verdicts' own
    client-side filter in the other direction.
    """
    all_verdicts = _registry().get_component_verdicts(entity_type, slug)
    return {k: v for k, v in all_verdicts.items() if v.get("verdict_target") != "blueprint"}


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
    _authorize_curation(registry, entity_type, slug, body.scope_locator)
    verdict = registry.record_component_verdict(
        entity_type, slug, body.scope_locator, body.verdict, body.retyped_to, body.note,
    )
    materialization = _materialize_if_accepted(
        registry, entity_type, slug, body.scope_locator, body.verdict,
    )
    if materialization is not None:
        verdict["materialization"] = materialization
        # Accepting is what moves an element out of the draft zone — the
        # zone transition IS the Egeria-visible effect of curation (plan §4).
        # Reported alongside the verdict, never gating it.
        guid = materialization.get("guid", "")
        if body.verdict == "accepted" and guid:
            verdict["promotion"] = _promote_to_publish_zones(guid)
            _record_promotion(registry, slug, body.scope_locator, NODE_PROMOTION_COMPONENT, verdict["promotion"])
    return verdict


@router.get("/component-verdicts/{entity_type}/{slug}/history")
def component_verdict_history(entity_type: str, slug: str, scope_locator: str) -> list[dict]:
    """Full verdict trail for one component, newest first — scope_locator as
    a query param (not a path segment) since it's a path prefix and routinely
    contains slashes."""
    return _registry().list_component_verdict_history(entity_type, slug, scope_locator)


# ── Blueprint verdicts ──────────────────────────────────────────────────────
#
# docs/blueprint-materialization-plan.md — the same report-then-curate shape
# as component verdicts above, one level up: a candidate_blueprint finding
# (a clustering.py proposal, not yet a real Egeria element) is what a
# curator accepts or rejects. Reuses architecture_component_verdicts (see
# the plan's Decision 3) rather than a parallel table — verdict_target
# distinguishes the two, and scope_locator is repurposed to hold
# f"{perspective}::{cluster_name}" since a blueprint has none of its own.
#
# Wires are deliberately NOT enqueued here (project-owner decision,
# 2026-09-03, after Phase A.5's live measurement confirmed
# SolutionLinkingWire duplicates on retry) — a materialized blueprint
# attaches its member components and child blueprints but renders without
# its wire diagram until that's built as its own follow-up.

class BlueprintVerdictCreate(BaseModel):
    perspective: str
    cluster_name: str
    verdict: str  # "accepted" | "rejected"
    note: str = ""
    # A person's flip of the blueprint's shape before the write ("container" | "contents"); empty takes
    # the default the plan names (blueprint_shape.py).
    shape: str = ""


@router.get("/blueprint-verdicts/{entity_type}/{slug}")
def list_blueprint_verdicts(entity_type: str, slug: str) -> dict[str, dict]:
    """{f"{perspective}::{cluster_name}": latest verdict} — filters
    list_component_verdicts' full result to verdict_target='blueprint'
    client-side, per the plan's Decision 3 (one table, not a second query
    parameter for what is currently one filter)."""
    all_verdicts = _registry().get_component_verdicts(entity_type, slug)
    return {k: v for k, v in all_verdicts.items() if v.get("verdict_target") == "blueprint"}


@router.post("/blueprint-verdicts/{entity_type}/{slug}")
def add_blueprint_verdict(entity_type: str, slug: str, body: BlueprintVerdictCreate) -> dict:
    if not body.perspective.strip() or not body.cluster_name.strip():
        raise HTTPException(status_code=400, detail="perspective and cluster_name must not be empty")
    if body.verdict not in ProjectRegistry.BLUEPRINT_VERDICTS:
        raise HTTPException(
            status_code=400,
            detail=f"verdict must be one of {sorted(ProjectRegistry.BLUEPRINT_VERDICTS)}, got {body.verdict!r}",
        )
    from resource_explorer.blueprint_shape import SHAPES
    if body.shape and body.shape not in SHAPES:
        raise HTTPException(status_code=400, detail=f"shape must be one of {list(SHAPES)}, got {body.shape!r}")
    registry = _registry()
    scope_locator = f"{body.perspective}::{body.cluster_name}"
    _authorize_curation(registry, entity_type, slug, scope_locator)
    verdict = registry.record_component_verdict(
        entity_type, slug, scope_locator, body.verdict, "", body.note,
        verdict_target="blueprint",
    )
    materialization = _materialize_blueprint_if_accepted(
        registry, entity_type, slug, body.perspective, body.cluster_name, body.verdict,
        **({"shape": body.shape} if body.shape else {}),
    )
    if materialization is not None:
        verdict["materialization"] = materialization
        guid = materialization.get("guid", "")
        if body.verdict == "accepted" and guid:
            verdict["promotion"] = _promote_to_publish_zones(guid)
            _record_promotion(registry, slug, scope_locator, NODE_PROMOTION_BLUEPRINT, verdict["promotion"])
    return verdict
