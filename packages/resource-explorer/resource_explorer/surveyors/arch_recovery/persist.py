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

from resource_explorer.step_outcome import PARTIAL, RECOVERED, StepOutcome

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
    # A files-less component (compose-derived, §8.2b's add-on and shared-infra
    # tiers, which own no first-party code) has no path prefix to use, so the
    # join key falls back to its slug.
    #
    # It must NOT fall back to `identity.deployment_context`, which an earlier
    # version did: that is the compose file's directory and is therefore SHARED
    # by every service declared in that file. Measured, it collapsed 58 distinct
    # compose-service components onto 10 join keys, and every reader — including
    # the shipped results view — kept one container per compose file and silently
    # discarded the rest. T1 deployment recall fell from 18/27 to 2/27 (spike
    # README findings 45-46).
    #
    # The slug is the right fallback because it is already unique and already
    # carries the deployment context that §8.2 requires for exactly this reason
    # ("egeria-quickstart::quickstart-pyegeria-web") — reusing that guarantee
    # rather than inventing a second one.
    return component.slug or component.identity.value


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
    run_scope: str = "",
    ports: list[dict] | None = None,
    wires: list[dict] | None = None,
    extra_metrics: dict[str, dict[str, float]] | None = None,
    outcome: StepOutcome | None = None,
) -> dict[str, str]:
    """Write one survey run's IR into the generic findings/metrics tables.

    Returns {component_slug: scope_locator} so a caller can attach further
    per-component metrics (e.g. import/co-change cohesion) after the fact
    without recomputing scope locators.

    extra_metrics: optional {scope_locator: {metric_name: value}} written
    alongside the standard confidence/evidence_count metrics — this is how
    repo_arch_coupling attaches import_cohesion/cochange_cohesion without
    this module needing to know about coupling-specific signals.

    outcome: caller-supplied StepOutcome, overriding the scoped/recovered
    default below. Only the caller knows whether this run's zero (if it was
    one) is trustworthy — repo_arch_detect and repo_arch_coupling have
    different known-positive checks (README findings 57/58), and this
    module has no opinion on either. Passed through unconditionally when
    given: a caller-supplied `unverified` for an unsupported language is a
    stronger, more specific statement than the generic `scoped_run`
    `partial` this function would otherwise compute, so it always wins.
    """
    # `run_scope` is the scope the RUN was narrowed to (D5/D6), which is a
    # different thing from a component's own `scope_locator` even though both
    # are paths and both live in the same column.
    #
    # They collide exactly: run `repo_arch_detect` scoped to `packages/foo` and
    # the component found there also keys on `packages/foo`. Because nothing
    # recorded which meaning a row carried, a SCOPED run — which by definition
    # saw only part of the repo, so its component set is necessarily incomplete
    # — wrote rows indistinguishable from a whole-repo run's. A reader merging
    # them presents a partial architecture as the whole architecture, with no
    # signal that anything is missing.
    #
    # Stamping it on every row is the minimum honest fix and needs no schema
    # change. The distinction it restores is "is this result complete?", which
    # no consumer could previously ask.
    # The shared outcome vocabulary (resource_explorer/step_outcome.py), rather
    # than a local `partial` boolean. Two spellings of one fact is the family of
    # bug this whole area has been fixing all session, so the local one goes.
    #
    # `run_scope` stays its OWN key rather than being folded into `cause`: the
    # outcome set is small and shared so it can be queried across steps, while
    # the scope is a value only this step knows how to interpret.
    if outcome is None:
        outcome = (
            StepOutcome(PARTIAL, cause="scoped_run", detail={"run_scope": run_scope})
            if run_scope else StepOutcome(RECOVERED)
        )
    outcome_row = outcome.as_row()
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
                    "run_scope": run_scope, **outcome_row,
                    "files": c.files, "blueprint": c.blueprint,
                    "proposed_by": c.proposed_by, "perspective": c.perspective,
                    "confidence_level": c.confidence_level,
                    # Granularity is not precision (approach-portfolio-model.md
                    # §2a) — the hierarchy is stored, not collapsed to one
                    # level, so a consumer can project (projection.py) rather
                    # than the generator having chosen a depth for them.
                    "parent_slug": c.parent_slug, "depth": c.depth,
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
    #
    # This is also THE place a component-less run's outcome is recorded
    # (README finding 57). Every other row above is written per-component, so
    # zero components means zero of them — this row is the one thing
    # persist_ir writes unconditionally regardless of len(components), which
    # makes it the only reliable place for a caller's `unverified` (or any
    # other outcome) to land when there is nothing else to attach it to. The
    # alternative — a synthetic zero-confidence Component just to carry the
    # outcome — would fabricate a row in the "component" check_name that
    # every reader (and the ground-truth comparison) treats as a real
    # candidate, which is worse than the bug being fixed.
    registry.upsert_metric(
        slug, KIND, {f"{run_label}_component_count": float(len(components))},
        detail={"run_scope": run_scope, **outcome_row},
        surveyed_at=surveyed_at, scope_locator="",
    )

    if ports or wires:
        name_to_scope = {c.name: slug_to_scope.get(c.slug, "") for c in components}
        _persist_interfaces(registry, slug, surveyed_at, ports or [], wires or [],
                            name_to_scope)

    return slug_to_scope


def _persist_interfaces(registry, slug: str, surveyed_at: str,
                        ports: list[dict], wires: list[dict],
                        name_to_scope: dict[str, str]) -> None:
    """Ports and wires as findings (design §5.5f, §3.2/§3.3).

    **Ports** are a property of one component, so they key on that component's
    `scope_locator` like every other component-scoped finding.

    **Wires are edges**, which the component-keyed finding shape does not
    naturally fit — and rather than invent a shape for a view that does not
    exist yet, each wire is attributed to its **source** component. That is not
    an arbitrary tie-break: a compose `depends_on` is *declared by* the
    depending service, so the source is where the evidence actually lives. The
    target travels in `detail`, so an edge list is recoverable without having
    committed to an edge table before anyone knows what reads it.
    """
    findings: list[dict] = []
    for p in ports:
        findings.append({
            "check_name": f"port:{p.get('name')}",
            "label": p.get("direction") or "Unknown",
            "summary": f"{p.get('component')} — {p.get('detail', '')}",
            "confidence": 70,
            "detail": {"component": p.get("component"), "port": p.get("name"),
                       "direction": p.get("direction"), "protocol": p.get("protocol", ""),
                       "evidence": p.get("evidence"), "kind": "port"},
        })
    for w in wires:
        findings.append({
            "check_name": f"wire:{w.get('target')}",
            "label": w.get("integrationStyle") or "declared-dependency",
            "summary": w.get("label") or f"{w.get('source')} -> {w.get('target')}",
            "confidence": 70,
            "detail": {"source": w.get("source"), "target": w.get("target"),
                       "protocol": w.get("protocol", ""), "oneWay": w.get("oneWay"),
                       "integrationStyle": w.get("integrationStyle", ""),
                       "frequency": w.get("frequency", ""),
                       "dataExchanged": w.get("dataExchanged", ""),
                       "evidence": w.get("evidence"), "kind": "wire"},
        })
    if not findings:
        return
    registry.upsert_finding(slug, "architecture_interfaces", findings,
                            surveyed_at=surveyed_at)
