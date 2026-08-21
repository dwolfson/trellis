"""Shared IR -> registry persistence for the two architecture-recovery
survey steps (repo_arch_detect, repo_arch_coupling — Phase 1 plan §4.2).

Design doc §5.4/§6.0: no new table. Evidence goes to
`project_analysis_findings` with `kind="architecture_recovery"`; a
component-scoped measure goes to `project_analysis_metrics` under the same
kind. `scope_locator` is the join key in both, and it IS the component — a
component's path prefix (§6.0), derived here from its `files` glob (or, for
a files-less deployment/compose component, its declared deployment
context) rather than its `slug`, which is a detector-qualified identifier
and not itself a path.

Both survey steps call `persist_ir()` independently (they run as separate
StepInfo entries, possibly at different times — see
ProjectRegistry.query_findings_all_runs' docstring for why that matters).
There is no cross-step merge here the way scripts/arch-spike/detect.py's
`_merge_agreeing()` does it for a single combined run: instead, two
components that land on the SAME scope_locator naturally accumulate
multiple "component" and evidence rows over time, and the results reader
(repo_survey_definition_adapter.py's `_architecture_recovery_results`)
reads them back together. That is a deliberate simplification, not an
oversight — see the port's write-up for the trade.
"""
from __future__ import annotations

from .ir import Component, Evidence

KIND = "architecture_recovery"


def scope_locator_for(component: Component) -> str:
    """A component's path prefix (design doc §6.0) — the join key.

    Preferred source is the component's own `files` glob, since that is
    what the component actually claims. Only a files-less component (a
    compose-derived deployment-perspective component — §8.2b's add-on/
    shared-infra tier, which owns no first-party code of its own) falls
    back to its declared deployment context, and failing that its bare
    identity value or slug.
    """
    files = component.files or []
    if files:
        g = files[0]
        for suffix in ("/**", "/*"):
            if g.endswith(suffix):
                stripped = g[: -len(suffix)]
                return stripped
        return "" if g == "**" else g
    ctx = component.identity.deployment_context
    if ctx:
        return ctx
    return component.identity.value or component.slug


def detector_family(detector: str) -> str:
    """Coarse "which approach" family for a detector id, e.g.
    "manifest:python" -> "manifest", "ast-grep:fastapi-app-construction" ->
    "code marker", "coupling:cohesive" -> "coupling (cohesive)". This is the
    "which approach proposed each" grouping Phase 1 plan §4.4 asks for.
    """
    prefix = detector.split(":", 1)[0]
    if prefix == "manifest":
        return "manifest"
    if prefix in ("dockerfile", "compose"):
        return "deployment"
    if prefix == "ast-grep":
        return "code marker"
    if prefix == "coupling":
        shape = detector.split(":", 1)[1] if ":" in detector else ""
        return f"coupling ({shape})" if shape else "coupling"
    return prefix or "unknown"


def persist_ir(
    registry,
    slug: str,
    components: list[Component],
    evidence: list[Evidence],
    surveyed_at: str,
    *,
    run_label: str = "run",
    extra_metrics: dict[str, dict[str, float]] | None = None,
) -> dict[str, str]:
    """Write one survey run's IR into the generic findings/metrics tables.

    Returns {component_slug: scope_locator} so a caller can attach further
    per-component metrics (e.g. import/co-change cohesion) after the fact
    without recomputing scope locators.

    extra_metrics: optional {scope_locator: {metric_name: value}} written
    alongside the standard confidence/evidence_count metrics — this is how
    repo_arch_coupling attaches import_cohesion/cochange_cohesion without
    this module needing to know about coupling-specific signals.
    """
    slug_to_scope: dict[str, str] = {c.slug: scope_locator_for(c) for c in components}

    for c in components:
        loc = slug_to_scope[c.slug]
        registry.upsert_finding(
            slug, KIND,
            [{
                "check_name": "component",
                "label": c.type or "Unclassified",
                "summary": f"{c.name} ({c.type or 'untyped'})",
                "confidence": c.confidence,
                "detail": {
                    "name": c.name, "slug": c.slug, "type": c.type,
                    "identity": {
                        "method": c.identity.method, "value": c.identity.value,
                        "deployment_context": c.identity.deployment_context,
                    },
                    "files": c.files, "blueprint": c.blueprint,
                    "proposed_by": c.proposed_by, "perspective": c.perspective,
                    "confidence_level": c.confidence_level,
                },
            }],
            surveyed_at=surveyed_at, scope_locator=loc,
        )
        metrics = {"confidence": float(c.confidence)}
        if extra_metrics and loc in extra_metrics:
            metrics.update(extra_metrics[loc])
        registry.upsert_metric(slug, KIND, metrics, surveyed_at=surveyed_at, scope_locator=loc)

    # Evidence rows: one per Evidence record, joined to its component via
    # subject_slug -> scope_locator. An Evidence record whose subject isn't
    # among this run's components (shouldn't happen — every Evidence in
    # this port is emitted alongside its Component) is skipped rather than
    # written with an empty/wrong scope_locator.
    by_scope: dict[str, int] = {}
    for e in evidence:
        loc = slug_to_scope.get(e.subject_slug)
        if loc is None:
            continue
        by_scope[loc] = by_scope.get(loc, 0) + 1
        registry.upsert_finding(
            slug, KIND,
            [{
                "check_name": e.assertion[:200],
                "label": detector_family(e.detector),
                "summary": f"{e.detector}: {e.assertion}",
                "confidence": e.confidence,
                "detail": {
                    "detector": e.detector,
                    "confidence_level": e.confidence_level,
                    "locations": [
                        {"path": loc_.path, "line": loc_.line, "excerpt": loc_.excerpt}
                        for loc_ in e.locations
                    ],
                },
            }],
            surveyed_at=surveyed_at, scope_locator=loc,
        )

    for loc, n in by_scope.items():
        registry.upsert_metric(
            slug, KIND, {"evidence_count": float(n)},
            surveyed_at=surveyed_at, scope_locator=loc,
        )

    # A run-summary row, scope_locator="" (whole-resource — same convention
    # every other kind uses for its own summary), so the results view has a
    # trend to read via the ordinary query_metrics_history path.
    # metric_name is prefixed with run_label ("detect"/"coupling") rather
    # than shared, because repo_arch_detect and repo_arch_coupling are two
    # independent StepInfo entries that are not guaranteed to run in the
    # same SurveyOrchestrator batch (and therefore not guaranteed to share
    # one surveyed_at) — a shared metric_name would let one step's count
    # silently overwrite the other's in query_metrics' "latest wins" read.
    registry.upsert_metric(
        slug, KIND, {f"{run_label}_component_count": float(len(components))},
        surveyed_at=surveyed_at, scope_locator="",
    )

    return slug_to_scope
