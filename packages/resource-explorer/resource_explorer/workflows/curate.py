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


#: What the verdict row says when promotion left zones to Egeria (nothing configured). The two
#: halves are the whole claim: RE put the element in NO zone, and a read-back found none.
ZONES_LEFT_TO_EGERIA_WORDS = "accepted · zones left to Egeria · everyone visible"


def _zone_words(zones: list[str]) -> str:
    return ZONES_LEFT_TO_EGERIA_WORDS if not zones else f"accepted · zone {', '.join(zones)}"


def promote_to_publish_zones(guid: str) -> dict:
    """Move an accepted element out of RE's draft zone. The Egeria-visible effect of "accept".

    **Configured-only (project owner, 2026-10-07).** The zone an accepted element moves into is
    `egeria_identity.configured_publish_zones()` and nothing else: there is no default zone.

    * a zone IS configured: one `add_zone_membership` call replaces the draft zone with exactly
      the configured zone(s) (never briefly in both); the row reads "accepted · zone <name>".
    * NOTHING configured: RE writes no zone at all and CLEARS its own draft `ZoneMembership`
      (the documented clear call), so the element is readable by everyone Egeria lets read it;
      the row reads "accepted · zones left to Egeria · everyone visible". "Cleared" is said only
      after a read of the element's classifications found no `ZoneMembership` on it. Materialization
      stamps `[draft_zone()]` (or the private zones for a private investigation), never the
      private zone for a public resource, so accept has to clear it or the element stays in the
      draft zone the service identity cannot read from.

    Best-effort and reported: the verdict is already saved and real, exactly as materialization
    is, so a failed promotion is a line in the response rather than a rolled-back decision.
    """
    from resource_explorer.egeria_identity import (
        ZoneReadError,
        clear_zone_membership,
        configured_publish_zones,
        current_zones,
        draft_zones,
        private_zone,
        read_zones,
        set_zone_membership,
    )

    zones = configured_publish_zones()
    if not guid:
        return {"status": "skipped", "reason": "no Egeria element to promote", "zones": zones,
                "words": "accepted · no Egeria element to promote"}

    if not zones:
        # Nothing configured: read FIRST, strictly. `[]` from this reader is "Egeria answered, no
        # ZoneMembership"; an unreadable answer raises and is reported, never read as "nothing to do".
        try:
            before = read_zones(guid)
        except ZoneReadError as exc:
            return {"status": "error", "guid": guid, "zones": [], "error": str(exc),
                    "words": f"accepted · zones not changed · {exc}"}
        if private_zone() in before:
            return _private_skip(guid, before)
        if not before:
            return {"status": "already_unzoned", "guid": guid, "zones": [], "from_zones": [],
                    "words": ZONES_LEFT_TO_EGERIA_WORDS}
        if before != draft_zones():
            # Not RE's own stamp: the element may be one RE adopted (found by qualifiedName) that
            # someone else placed in a zone. Clear ONLY RE's draft zone; never strip another zone.
            return {"status": "left_as_is", "guid": guid, "zones": before, "from_zones": before,
                    "words": f"zones left as they are · {', '.join(before)} · not RE's draft zone"}
        if not clear_zone_membership(guid):
            return {"status": "error", "guid": guid, "zones": [], "from_zones": before,
                    "error": "Egeria did not accept clearing the ZoneMembership",
                    "words": "accepted · zones not changed · Egeria did not accept clearing the draft zone"}
        try:
            after = read_zones(guid)
        except ZoneReadError as exc:
            return {"status": "error", "guid": guid, "zones": [], "from_zones": before,
                    "error": str(exc), "words": f"accepted · could not confirm the zone was cleared · {exc}"}
        if after:
            return {"status": "error", "guid": guid, "zones": after, "from_zones": before,
                    "error": f"the zones read back as {after}, not cleared",
                    "words": f"accepted · still in zone {', '.join(after)} · the clear did not take"}
        return {"status": "promoted", "guid": guid, "zones": [], "from_zones": before,
                "words": ZONES_LEFT_TO_EGERIA_WORDS}

    # **A no-op promotion is an error in Egeria, not a nothing.** Its security connector refuses a
    # zone change whose before and after are equal (observed live 2026-09-04,
    # OMAG-SERVER-SECURITY-403-005 ... from [egeria-runtime] to [egeria-runtime]). Re-accepting an
    # already-accepted element is an ordinary thing to do, so checking first is not an
    # optimisation: without it, "this was already promoted" reads as a permissions failure.
    already = current_zones(guid)
    if already and set(already) == set(zones):
        return {"status": "already_promoted", "guid": guid, "zones": zones, "words": _zone_words(zones)}

    # **Never promote a private element into the publish zones.** Accepting a finding is a
    # curation decision about quality; it is not a decision to make somebody's personal
    # investigation public. Keyed on the zone RE itself applies, which is what Egeria enforces.
    if private_zone() in (already or []):
        return _private_skip(guid, already)

    # **Never remove a zone RE did not stamp.** `add_zone_membership` REPLACES the classification, so
    # writing just the configured zones would drop a foreign zone someone put on an element RE adopted.
    # The write is the configured zones UNIONED with the foreign ones (RE's draft zone goes; nothing
    # else does). Chosen over "leave it and say so" because accept still has to make the element
    # visible in the configured zone, and the union costs the foreign zone nothing.
    foreign = [z for z in (already or []) if z not in {*draft_zones(), private_zone()}]
    zones = list(dict.fromkeys([*foreign, *zones]))
    ok = set_zone_membership(guid, zones)
    if not ok:
        return {"status": "error", "guid": guid, "zones": zones, "from_zones": already,
                "words": "accepted · zones not changed · Egeria did not accept the zone change",
                "error": "Egeria did not accept the ZoneMembership change"}
    # The success words are said only after the zones are READ BACK (they are stored as proof).
    try:
        after = read_zones(guid)
    except ZoneReadError as exc:
        return {"status": "error", "guid": guid, "zones": zones, "from_zones": already, "error": str(exc),
                "words": f"accepted · could not confirm the zone was set · {exc}"}
    if set(after) != set(zones):
        return {"status": "error", "guid": guid, "zones": after, "from_zones": already,
                "error": f"the zones read back as {after}, not {zones}",
                "words": f"accepted · zone not set · read back as {', '.join(after) or 'no zone'}"}
    return {"status": "promoted", "guid": guid, "zones": zones, "from_zones": already, "words": _zone_words(zones)}


#: Proof rows for a promotion (`catalogue_commit_proofs`, no new table). A row is written AFTER the
#: promotion read the element's zones, and carries the words the verdict row shows, so the screen
#: reads a row and never re-derives the sentence from the branch the code took.
P_PROMOTION = "promotion"
NODE_PROMOTION_COMPONENT = "component_promotion"
NODE_PROMOTION_BLUEPRINT = "blueprint_promotion"


def record_promotion(registry: ProjectRegistry, slug: str, scope: str, node_kind: str,
                     promotion: dict | None, recorded_by: str = "") -> None:
    """Append the proof row for one promotion (`scope` is the component's scope_locator or the
    blueprint's `<perspective>::<cluster>` key). Nothing is recorded for a promotion that was
    never attempted."""
    if not promotion:
        return
    registry.append_catalogue_commit_proof(
        slug, proof=P_PROMOTION, node_kind=node_kind, table_name=scope,
        element_guid=promotion.get("guid", ""), recorded_by=recorded_by,
        detail={"status": promotion.get("status", ""), "words": promotion.get("words", ""),
                "zones": promotion.get("zones", []), "from_zones": promotion.get("from_zones", []),
                "error": promotion.get("error", "")})


def promotion_by_scope(registry: ProjectRegistry, slug: str, node_kind: str) -> dict[str, dict]:
    """{scope: latest promotion row} for a resource: `{words, status, read_at}`. The words are what
    the verdict row shows; absent means no promotion has been recorded for that scope."""
    out: dict[str, dict] = {}
    for p in registry.list_catalogue_commit_proofs(slug):
        if p["proof"] == P_PROMOTION and p["node_kind"] == node_kind:
            d = p.get("detail") or {}
            out[p["table_name"]] = {"words": d.get("words", ""), "status": d.get("status", ""),
                                    "read_at": p["read_at"]}
    return out


def _private_skip(guid: str, in_zones: list[str]) -> dict:
    return {
        "status": "skipped",
        "reason": ("this element belongs to a private investigation; accepting a "
                   "finding does not make it public. Reclassify the investigation "
                   "to share it."),
        "guid": guid,
        "zones": in_zones,
        "words": "accepted · stays private · reclassify the investigation to share it",
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
    # What the component represents is in its displayName (never its qualifiedName), derived from the
    # evidence class. A repository-derived component that maps to an element Egeria's content pack defines
    # ADOPTS it: no second component, no rename (the pack's name is the pack's).
    from resource_explorer.blueprint_shape import content_pack_name_for_image, display_name, represents_kind
    pack_name = content_pack_name_for_image(detail.get("image") or "")
    refused = ""
    if pack_name:
        from resource_explorer.surveyors.arch_recovery.blueprint_materializer import BlueprintMaterializer
        pack = BlueprintMaterializer(registry=registry).find_content_pack_component(pack_name)
        refused = pack.get("refused") if isinstance(pack, dict) else ""
        if refused:
            pack = None
        if pack:
            registry.record_materialized_component(
                entity_type, slug, scope_locator, pack["qualified_name"], pack["guid"])
            return {"status": "adopted_content_pack", "guid": pack["guid"],
                    "qualified_name": pack["qualified_name"], "matched_by_image": detail["image"],
                    "words": f"{pack_name} · adopted from the content pack · matched by image {detail['image']}"}
    try:
        made = ComponentMaterializer(registry=registry).materialize(
            entity_type, slug, scope_locator,
            name=display_name(detail.get("name", scope_locator), represents_kind(detail)),
            component_type=detail.get("type") or "",
            perspective=detail.get("perspective", ""),
            confidence=latest.get("confidence", 0),
        )
        if refused and isinstance(made, dict):
            made["content_pack_refused"] = refused       # said, not silently skipped
        return made
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
                                       perspective: str, cluster_name: str, verdict: str,
                                       shape: str = "", identifier: str = "") -> dict | None:
    """Same non-fatal-but-visible shape as materialize_component_if_accepted above —
    the verdict itself is already saved and real regardless of whether this
    succeeds. Only 'accepted' triggers a write; only entity_type='repo' is
    wired (architecture_recovery/clustering's only kind today).

    Partial progress is real progress (Decision 2/step 4 of the plan): an
    unmaterialized member or child is reported, not treated as a reason to
    enqueue nothing.

    **The blueprint is written in ONE of two shapes, never a mix** (project owner, 2026-10-08;
    `blueprint_shape.py`, DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md 6a):

    * container (the default, when the cluster's root is a real component): the root is the ONLY blueprint
      member and each other member is its sub-component by `SolutionComposition`; Egeria draws the
      encapsulation.
    * contents (the root is merely a grouping): the children are the members, no root element.

    `shape` ("container" | "contents" | "") is a person's flip before the write; "" takes the default.
    The plan, with the words that name the shape and why, comes back as `result["shape"]` and is stored
    as a `shape` proof row. Egeria draws the diagram: RE writes only components, compositions and
    memberships.
    """
    if verdict != "accepted" or entity_type != "repo":
        return None
    cluster = find_candidate_blueprint(registry, slug, perspective, cluster_name)
    if cluster is None:
        return {"status": "error",
               "error": "no candidate_blueprint finding for this (perspective, cluster_name) "
                        "to materialize"}

    from dataclasses import replace

    from resource_explorer.blueprint_shape import (
        CONTAINER,
        SHAPES,
        component_nodes,
        distinct_name,
        find_root,
        plan_shape,
    )
    from resource_explorer.surveyors.arch_recovery.blueprint_materializer import (
        BlueprintIdentifierNeeded,
        BlueprintMaterializationError,
        BlueprintMaterializer,
    )
    from resource_explorer.surveyors.arch_recovery.materializer import ComponentMaterializer
    materializer = BlueprintMaterializer(registry=registry)
    from resource_explorer.blueprint_kinds import (
        blueprint_display_name,
        repo_label,
    )
    from resource_explorer.surveyors.repo_survey_definition_adapter import _candidate_blueprints_results

    requested = shape if shape in SHAPES else ""
    nodes_by_slug = component_nodes(registry, slug)
    member_slugs = cluster.get("members") or []
    # A member the recovery has no component finding for still counts (by its slug); it just carries no
    # evidence class, so it can never be mistaken for a real-component root.
    from resource_explorer.blueprint_shape import Node
    known = [nodes_by_slug.get(s) or Node(slug=s, name=s) for s in member_slugs]

    project = registry.get(slug)
    roots = [b for b in _candidate_blueprints_results(registry, slug)
             if b["perspective"] == perspective and not b.get("parent")]
    sole_root = len(roots) == 1 and roots[0]["cluster_name"] == cluster_name
    # A blueprint's name is the KIND and the repository and never equals a member's name (6a rule 1).
    # ...and says what its members represent when they are all of one kind (container definitions, code
    # modules): displayName only, the qualifiedName never carries it.
    from resource_explorer.blueprint_shape import blueprint_suffix_name
    from resource_explorer.blueprint_shape import display_name as suffixed_name
    display_name = distinct_name(
        blueprint_suffix_name(
            blueprint_display_name(repo_label(slug, getattr(project, "display_name", "") or ""), perspective,
                                   cluster.get("name", cluster_name), sole_root=sole_root,
                                   identifier=identifier.strip()),
            [n.kind for n in known]),
        [n.name for n in known] + [suffixed_name(n.name, n.kind) for n in known])
    try:
        result = materializer.materialize_blueprint_element(
            entity_type, slug, perspective, cluster_name,
            # The KIND is in the name (owner, 2026-10-07): "Egeria Deployment Blueprint".
            display_name=display_name,
            oversized=bool(cluster.get("oversized")),
            # Identity is kind + repository (architect's ruling, 2026-10-08): the root cluster's name is not in
            # it. A person's `identifier` is needed only for a second blueprint of the kind.
            identifier=identifier,
            live_clusters={b["cluster_name"] for b in _candidate_blueprints_results(registry, slug)
                           if b["perspective"] == perspective},
            # A blueprint a person deleted in Egeria must not be trusted from RE's cache.
            verify_cached=True,
        )
    except BlueprintIdentifierNeeded as exc:
        return {"status": "error", "error": str(exc), "needs_identifier": True}
    except BlueprintMaterializationError as exc:
        return {"status": "error", "error": str(exc)}

    blueprint_guid = result["guid"]
    slug_to_scope = {s: n.scope for s, n in nodes_by_slug.items()}
    member_guids, unmaterialized_members = materializer.resolve_member_guids(
        registry, entity_type, slug, member_slugs, slug_to_scope,
    )
    # Components that exist in Egeria but this registry never recorded are ADOPTED by qualifiedName.
    findable = [s for s in unmaterialized_members if s in slug_to_scope]
    if findable:
        adopted = materializer.adopt_unmaterialized_members(
            registry, entity_type, slug, findable, slug_to_scope)
        member_guids = {**member_guids, **adopted}
        unmaterialized_members = [s for s in unmaterialized_members if s not in adopted]
        skipped = getattr(materializer, "adoption_skipped", None)
        adoption_skipped = dict(skipped) if isinstance(skipped, dict) else {}
    else:
        adoption_skipped = {}
    child_guids, unmaterialized_children = materializer.resolve_child_blueprint_guids(
        registry, entity_type, slug, perspective, cluster.get("children") or [],
    )

    # The root may be an element Egeria's content pack already defines: adopt it rather than leave the
    # container unwritten, and let it count as a real component (the one test, 6a).
    qn_override: dict[str, str] = {}
    adopted_words: list[str] = []
    content_pack_refused: list[str] = []
    nodes = [replace(n, guid=member_guids.get(n.slug, "")) for n in known]
    root = find_root(cluster.get("name", cluster_name), nodes, cluster.get("composed_into", ""))
    if root is not None and not root.guid and not root.structural:
        pack = materializer.find_content_pack_component(root.name)
        if isinstance(pack, dict) and pack.get("refused"):
            content_pack_refused.append(pack["refused"])
            pack = None
        if pack:
            qn_override[root.slug] = pack["qualified_name"]
            matched = f"image {root.image}" if root.image else "name"
            adopted_words.append(f"{pack.get('name') or root.name} · adopted from the content pack · matched by {matched}")
            nodes = [replace(n, guid=pack["guid"], content_pack=True) if n.slug == root.slug else n
                     for n in nodes]
            unmaterialized_members = [s for s in unmaterialized_members if s != root.slug]
    plan = plan_shape(cluster.get("name", cluster_name), nodes, requested=requested,
                      composed_into=cluster.get("composed_into", ""))

    def qn_of(node) -> str:
        return qn_override.get(node.slug) or ComponentMaterializer.qualified_name_for(
            entity_type, slug, node.scope)

    scope_key = f"{perspective}::{cluster_name}"
    member_guid_list: list[str] = []
    composition_results: list[dict] = []
    composition_error = ""
    if plan.shape == CONTAINER:
        # Only the container is a member. With no element for it there is no membership at all: falling
        # back to the children would silently be the other shape.
        if plan.root.guid:
            member_guid_list = [plan.root.guid]
            children = [(c.guid, qn_of(c)) for _, c in plan.compositions if c.guid]
            try:
                composition_results = materializer.link_sub_components(
                    plan.root.guid, qn_of(plan.root), children)
                if not isinstance(composition_results, list):
                    raise TypeError("link_sub_components returned no rows")
            except Exception as exc:
                # Anything unexpected (a Pyegeria exception, a KeyError from a changed answer shape) must
                # not strand a blueprint with no memberships and no proofs: say so, and carry on.
                composition_error = f"{type(exc).__name__}: {str(exc)[:200]}"
                log.warning("composition step failed for %s: %s", scope_key, composition_error)
                composition_results = [
                    {"key": f"SolutionComposition::{qn_of(plan.root)}::{cqn}", "container_guid": plan.root.guid,
                     "child_guid": cg, "status": "error", "read_back": False, "error": composition_error}
                    for cg, cqn in children]
        elif plan.root.slug not in unmaterialized_members:
            unmaterialized_members = [*unmaterialized_members, plan.root.slug]
    else:
        member_guid_list = [n.guid for n in plan.members if n.guid]

    # Direct members left by an EARLIER run (the old blueprint): reported, never removed.
    extra_members: list[str] = []
    extra_read = False
    existing = materializer.blueprint_member_guids(blueprint_guid)
    if isinstance(existing, (set, frozenset)):
        extra_read = True
        if plan.shape == CONTAINER:
            extra_members = sorted(existing & {c.guid for _, c in plan.compositions if c.guid})
        elif plan.root is not None and plan.root.guid in existing:
            extra_members = [plan.root.guid]

    from resource_explorer.egeria_outbox import enqueue_blueprint_members
    all_member_guids = member_guid_list + list(child_guids.values())
    row_ids = enqueue_blueprint_members(registry, entity_type, slug, blueprint_guid, all_member_guids)

    written = plan.shape != CONTAINER or bool(plan.root and plan.root.guid)
    _record_shape_proofs(registry, slug, scope_key, blueprint_guid, plan, composition_results,
                         written=written, extra_members=extra_members)

    result["shape"] = plan.to_dict()
    result["compositions"] = composition_results
    result["extra_members"] = extra_members
    result["extra_members_read"] = extra_read
    if extra_members:
        n = len(extra_members)
        result["extra_members_words"] = (
            f"{n} {'child is' if n == 1 else 'children are'} also direct member{'' if n == 1 else 's'} "
            f"from an earlier run: a steward can detach {'it' if n == 1 else 'them'} in Egeria Explorer")
    if adoption_skipped:
        result["adoption_skipped"] = adoption_skipped
    if content_pack_refused:
        result["content_pack_refused"] = content_pack_refused
    if adopted_words:
        result["adopted_from_content_pack"] = adopted_words
    if composition_error:
        result["composition_error"] = composition_error
    result["enqueued_membership_rows"] = len(row_ids)
    if unmaterialized_members:
        result["unmaterialized_members"] = unmaterialized_members
    if unmaterialized_children:
        result["unmaterialized_children"] = unmaterialized_children
    unfinished = [c for c in composition_results if c["status"] in ("unconfirmed", "error", "unread")]
    unproven = result.get("status") == "adopted_unproven"
    if unmaterialized_members or unmaterialized_children or composition_error or unfinished:
        result["status"] = "partial"
    if unproven:                       # the re-key proof row could not be written: the pane CAN show it
        result["adopted_unproven"] = True
    return result


P_SHAPE = "shape"
P_COMPOSITION = "composition"
NODE_BLUEPRINT_SHAPE = "blueprint_shape"


def _record_shape_proofs(registry: ProjectRegistry, slug: str, scope_key: str, blueprint_guid: str,
                         plan, compositions: list[dict], *, written: bool = True,
                         extra_members: list[str] | None = None) -> None:
    """Proof rows (`catalogue_commit_proofs`, no new table): one for the shape that was chosen and why,
    and one per composition. Each composition row says whether a read by GUID really backed it
    (`read_back`), never a blanket True. The shape row names the shape as written: a container whose root
    has no element says so instead of claiming the shape. A failed proof write never undoes the Egeria
    write; it is logged."""
    shape_said = plan.shape if written else f"{plan.shape} (not written: root has no GUID)"
    try:
        registry.append_catalogue_commit_proof(
            slug, proof=P_SHAPE, node_kind=NODE_BLUEPRINT_SHAPE, table_name=scope_key,
            element_guid=blueprint_guid,
            detail={"shape": shape_said, "written": written, "default_shape": plan.default_shape,
                    "why": plan.why, "words": plan.words, "flipped": plan.flipped,
                    "flip_refused": plan.flip_refused, "root": plan.root.name if plan.root else "",
                    "extra_members": list(extra_members or [])})
        for c in compositions:
            registry.append_catalogue_commit_proof(
                slug, proof=P_COMPOSITION, node_kind=NODE_BLUEPRINT_SHAPE, table_name=scope_key,
                element_guid=c["container_guid"], target_guid=c["child_guid"], qualified_name=c["key"],
                detail={"status": c["status"], "read_back": bool(c.get("read_back")),
                        "error": c.get("error", ""), "note": c.get("note", "")})
    except Exception as exc:                      # the Egeria write stands; the proof is what failed
        log.warning("could not record the shape proofs for %s: %s", scope_key, exc)
