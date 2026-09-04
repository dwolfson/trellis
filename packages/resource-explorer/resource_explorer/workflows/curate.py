"""Curate — materializing an accepted verdict into real Egeria elements.

Moved out of `web/routes/curate.py` (`_materialize_if_accepted` at :294,
`_find_candidate_blueprint` at :427, `_materialize_blueprint_if_accepted` at
:449, and the `_slug_to_scope_map` helper both depend on) in step 2b. The plan
(§3) lists this as web-only-today code sitting *above* a core class: the
`ComponentMaterializer` and `BlueprintMaterializer` were already core; only the
decision of when to invoke them, and the assembly of what to pass, lived in a
route module.

Nothing here raises for a materialization failure. The verdict is already saved
and real regardless of whether Egeria was reachable a moment ago, so a failure
comes back as `{"status": "error", "error": ...}` in the field the caller merges
into its response — the same non-fatal-but-visible shape
`EgeriaPublisher.publish()`'s `annotation_types_warning` uses.
"""
from __future__ import annotations

import logging

from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)


class CurationDenied(PermissionError):
    """The caller may not curate this element. Surfaces as HTTP 403.

    A distinct exception rather than a boolean so the enforcement lives at the
    workflow layer and every entry point inherits it — the plan's isolation
    matrix says authorization is "enforced at the workflow layer so the CLI and
    A2A honour it too", and a boolean returned to a route is a boolean the next
    route forgets to check.
    """


#: JWT `role` claims that grant curation beyond what one owns.
#:
#: The plan's model is a `GovernanceRole` with `PersonRoleAppointment`, read
#: from Egeria. **This is the bridge, not the destination**, and the plan says
#: so in as many words: "the Portal `role` claim is the bridge until
#: appointments are read from Egeria". Reading it here rather than inventing a
#: trellis-side curator table is the point — when appointments land, this
#: constant is what gets replaced, and nothing else moves.
CURATOR_ROLES = frozenset({"curator", "admin"})


def may_curate(owner: str) -> tuple[bool, str]:
    """`(allowed, why_not)` for the current caller curating an element owned by `owner`.

    Three cases, in the order the plan states them:

    1. **The owner.** "Ownership is curation by default" — the person who
       discovered, surveyed and catalogued a resource may accept, reject,
       promote and delete it with no separate grant. There is no global
       curator role for one's own resources.
    2. **A role appointee.** A `curator` or `admin` role claim curates across
       resources it does not own.
    3. **Everyone else** — denied.

    An element with **no recorded owner** is treated as belonging to the
    shared/legacy bucket and is curatable by any signed-in user. That is
    deliberate and is the migration story: every verdict recorded before this
    change has no owner, and locking all of them behind a role nobody has been
    appointed to would make the existing corpus uncurateable overnight.

    Not signed in is always denied, whoever owns what.
    """
    from resource_explorer.a2a_auth import caller

    identity = caller()
    if identity is None or identity.auth_source == "anonymous":
        return False, (
            "Authentication required to curate. Sign in (POST /api/auth/login) "
            "or run `resource-explorer login`."
        )
    if not owner:
        return True, ""
    if identity.user_id == owner:
        return True, ""
    if (identity.role or "").lower() in CURATOR_ROLES:
        return True, ""
    return False, (
        f"This element is owned by {owner!r}. Curating someone else's element "
        f"requires a curator or admin role; you are signed in as "
        f"{identity.user_id!r} with role {identity.role!r}."
    )


def require_curation_rights(owner: str) -> None:
    """`may_curate`, raised. The form every call site should use."""
    allowed, why_not = may_curate(owner)
    if not allowed:
        raise CurationDenied(why_not)


def owner_of(registry: ProjectRegistry, entity_type: str, slug: str,
             scope_locator: str) -> str:
    """Who owns the element behind this verdict, as RE recorded it.

    Read from RE's own verdict/materialization trail rather than from Egeria's
    `Ownership` classification, deliberately: the authorization decision must
    be answerable when Egeria is unreachable, and it must be answerable for a
    proposal that has not been materialized into Egeria at all yet. Egeria's
    classification is the record of ownership *for the catalogue*; this is the
    same fact as RE knows it, written at the same moment by the same publish.

    Reads the **latest** verdict's `decided_by`, which is the person who last
    curated this element — and, because recording a verdict already requires
    passing this same check, the only ways to become that person are to have
    been the owner, to hold a curator role, or to have been the first to touch
    an element nobody owned. The first-toucher case is the plan's own rule
    working as intended: "the user who discovers, surveys and catalogs a
    resource is its owner, and ownership carries the right to curate it."

    `""` when nothing recorded an owner — the shared/legacy bucket, see
    `may_curate`.
    """
    try:
        verdicts = registry.get_component_verdicts(entity_type, slug) or {}
    except Exception:  # pragma: no cover - a registry failure is its own error
        return ""
    row = verdicts.get(scope_locator) or {}
    return str(row.get("decided_by") or "")


def promote_to_publish_zones(guid: str) -> dict:
    """Move an accepted element out of the draft zone. The Egeria-visible effect of "accept".

    Plan §4: "promotion into the deployment's normal `publishZones` on
    acceptance, so 'curate' has a zone transition as its Egeria-visible
    effect". One `add_zone_membership` call replaces the classification's
    property outright, so the element is never briefly in both.

    Best-effort and reported: the verdict is already saved and real, exactly as
    materialization is, so a failed promotion is a line in the response rather
    than a rolled-back decision.
    """
    from resource_explorer.egeria_identity import (
        current_zones,
        publish_zones,
        set_zone_membership,
    )

    zones = publish_zones()
    if not guid:
        return {"status": "skipped", "reason": "no Egeria element to promote", "zones": zones}

    # **A no-op promotion is an error in Egeria, not a nothing.** Its security
    # connector refuses a zone change whose before and after are equal —
    # observed live 2026-09-04:
    #
    #     OMAG-SERVER-SECURITY-403-005 User erinoverview is not authorized to
    #     change the zone membership for element ... from [egeria-runtime] to
    #     [egeria-runtime]
    #
    # Re-accepting an already-accepted element is an ordinary thing to do, so
    # checking first is not an optimisation: without it, "this was already
    # promoted" is reported to the user as a permissions failure.
    already = current_zones(guid)
    if already and set(already) == set(zones):
        return {"status": "already_promoted", "guid": guid, "zones": zones}

    ok = set_zone_membership(guid, zones)
    return {
        "status": "promoted" if ok else "error",
        "guid": guid,
        "zones": zones,
        "from_zones": already,
        **({} if ok else {"error": "Egeria did not accept the ZoneMembership change"}),
    }


def materialize_component_if_accepted(registry: ProjectRegistry, entity_type: str, slug: str,
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
        ComponentMaterializer,
        MaterializationError,
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


def slug_to_scope_map(registry: ProjectRegistry, slug: str) -> dict[str, str]:
    """component slug -> scope_locator, for every currently-live
    architecture_recovery component finding. Deliberately its own copy of
    _architecture_recovery_results' identical loop
    (repo_survey_definition_adapter.py) rather than a shared import — same
    reasoning ComponentMaterializer._find_element_guid gives for not
    sharing with EgeriaPublisher: a small, self-contained piece of logic
    duplicated once is safer here than a new cross-module coupling for one
    caller. This is THE fix for the plan's own named identity-mismatch
    trap: clustering keys a blueprint's members by component slug; verdicts
    and materialization are keyed by scope_locator. Looking a slug up
    directly in get_materialized_component()/get_component_verdicts()
    without going through this map first silently finds nothing for every
    member."""
    import json as _json
    out: dict[str, str] = {}
    for scope in registry.query_finding_scopes(slug, "architecture_recovery", check_name="component"):
        rows = [r for r in registry.query_findings_all_runs(slug, "architecture_recovery", scope)
                if r["check_name"] == "component"]
        if not rows:
            continue
        latest = max(rows, key=lambda r: r["surveyed_at"])
        detail = _json.loads(latest.get("detail_json") or "{}") if latest.get("detail_json") else {}
        if detail.get("slug"):
            out[detail["slug"]] = scope
    return out


def find_candidate_blueprint(registry: ProjectRegistry, slug: str,
                              perspective: str, cluster_name: str) -> dict | None:
    """The latest candidate_blueprint finding for (perspective, cluster_name),
    or None if it's gone (e.g. re-clustered since the review surface last
    loaded). clustering.py's findings all share scope_locator="" — every
    cluster for a repo is disambiguated by label/detail.name within that one
    scope, per the plan's own Context section."""
    import json as _json

    from resource_explorer.surveyors.arch_recovery.persist import BLUEPRINT_KIND
    rows = [r for r in registry.query_findings(slug, BLUEPRINT_KIND, "")
            if r["check_name"] == "candidate_blueprint"]
    matches = []
    for r in rows:
        detail = _json.loads(r.get("detail_json") or "{}") if r.get("detail_json") else {}
        if detail.get("perspective") == perspective and detail.get("name") == cluster_name:
            matches.append((r, detail))
    if not matches:
        return None
    r, detail = max(matches, key=lambda pair: pair[0]["surveyed_at"])
    return detail


def materialize_blueprint_if_accepted(registry: ProjectRegistry, entity_type: str, slug: str,
                                       perspective: str, cluster_name: str, verdict: str) -> dict | None:
    """Same non-fatal-but-visible shape as materialize_component_if_accepted above —
    the verdict itself is already saved and real regardless of whether this
    succeeds. Only 'accepted' triggers a write; only entity_type='repo' is
    wired (architecture_recovery/clustering's only kind today).

    Partial progress is real progress (Decision 2/step 4 of the plan): an
    unmaterialized member or child is reported, not treated as a reason to
    enqueue nothing.
    """
    if verdict != "accepted" or entity_type != "repo":
        return None
    cluster = find_candidate_blueprint(registry, slug, perspective, cluster_name)
    if cluster is None:
        return {"status": "error",
               "error": "no candidate_blueprint finding for this (perspective, cluster_name) "
                        "to materialize"}

    from resource_explorer.surveyors.arch_recovery.blueprint_materializer import (
        BlueprintMaterializationError,
        BlueprintMaterializer,
    )
    materializer = BlueprintMaterializer(registry=registry)
    try:
        result = materializer.materialize_blueprint_element(
            entity_type, slug, perspective, cluster_name,
            display_name=cluster.get("name", cluster_name),
            oversized=bool(cluster.get("oversized")),
        )
    except BlueprintMaterializationError as exc:
        return {"status": "error", "error": str(exc)}

    blueprint_guid = result["guid"]
    slug_to_scope = slug_to_scope_map(registry, slug)
    member_guids, unmaterialized_members = materializer.resolve_member_guids(
        registry, entity_type, slug, cluster.get("members") or [], slug_to_scope,
    )
    child_guids, unmaterialized_children = materializer.resolve_child_blueprint_guids(
        registry, entity_type, slug, perspective, cluster.get("children") or [],
    )

    from resource_explorer.egeria_outbox import enqueue_blueprint_members
    all_member_guids = list(member_guids.values()) + list(child_guids.values())
    row_ids = enqueue_blueprint_members(registry, entity_type, slug, blueprint_guid, all_member_guids)

    result["enqueued_membership_rows"] = len(row_ids)
    if unmaterialized_members:
        result["unmaterialized_members"] = unmaterialized_members
    if unmaterialized_children:
        result["unmaterialized_children"] = unmaterialized_children
    if unmaterialized_members or unmaterialized_children:
        result["status"] = "partial"
    return result
