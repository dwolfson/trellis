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
