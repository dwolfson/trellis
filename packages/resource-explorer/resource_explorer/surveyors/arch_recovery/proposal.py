"""Phase 2 — publish the architecture proposal as annotations.

`docs/architecture-recovery-report-then-curate.md` §5 replaces the original
Phase 2 ("Egeria projection at Draft") with:

> **RE reports what the analysis believes. A curator decides whether it becomes
> real.**

So this module turns stored recovery findings into *observations*, never into
structural elements. A `SolutionComponent` is an assertion about the world; an
Annotation is what one dated act of analysis believed. Publishing components
directly would claim a confidence the analysis does not have — and would make
re-derivation clobber curation, which §7.2 of the design calls its single
biggest risk. Under report-then-curate that risk does not need solving, because
the curated elements are ones RE never writes.

**What gets published, and why it is not simply "one annotation per component"**
(settled with Dan, 2026-08-31). Recovery stores the *whole* candidate hierarchy
— 466 components on `egeria_git`'s latest run, 2,092 at the largest observed —
because granularity is not precision and a generator should not choose a depth.
But §3 of report-then-curate requires the proposal be **legible before it
exists**: a curator declines a blueprint *because the fit is not good enough*,
and cannot judge that from two thousand annotations. So:

  - one annotation per component **at projection depth 1** (~35 on egeria_git),
    each carrying identity, type, confidence, provenance and evidence count;
  - one **structural** annotation whose payload holds the complete unprojected
    hierarchy plus ports and wires, so nothing computed is lost;
  - one **candidate clusters** annotation — the blueprint proposals, which are
    explicitly allowed to offer more than one clustering for a curator to
    choose between (§2b);
  - one **summary** annotation carrying census, counts and `analyzerVersion`.

Legible and lossless, which "publish everything" and "publish only a summary"
each give up one half of.

Nothing here writes to Egeria. It returns annotations; `SurveyOrchestrator`
collects them and `EgeriaPublisher` publishes them through the outbox, so a
proposal publishes wholly or is retried — §6 of report-then-curate is blunt that
"a proposal that publishes half its annotations misrepresents the analysis."
"""
from __future__ import annotations

import json
from typing import Any, Callable

from resource_explorer.surveyors.survey_report import (
    Annotation,
    ClassificationAnnotation,
    ResourceMeasureAnnotation,
)

STEP = "repo_arch_proposal"

#: This step emits four distinguishable kinds of result, so each sets its own
#: `annotation_type_name`. Left unset, all four would derive the same per-step
#: name from the registry and blur together in Egeria — a curator reading the
#: report could not tell a proposed component from the structural payload.
TYPE_COMPONENT = "Proposed Solution Component"
TYPE_STRUCTURE = "Proposed Architecture Structure"
TYPE_CLUSTERS = "Candidate Blueprint Clusters"
TYPE_SUMMARY = "Architecture Proposal Summary"

#: The depth per-component annotations are published at. Matches
#: projection.DEFAULT_PROJECTION_DEPTH rather than restating it — the reason a
#: UI projects and the reason a curator's review projects are the same reason.
PROPOSAL_DEPTH = 1

#: DEFAULT number of components named individually — a default, not a ceiling
#: (Dan, 2026-08-31). Discovering dozens of components usually means the result
#: is not interesting enough to catalog, so the default is deliberately modest;
#: but if someone wants all 878 of egeria_git's components in Egeria, that is
#: their call to make and not this module's to refuse. Pass `max_named=None`
#: for no limit, or any integer to raise or lower it.
#:
#: Whatever the limit, the structural annotation still carries every component,
#: and the summary reports how many were not named — a cap that hides its own
#: existence would read as "these are all the components there are".
DEFAULT_MAX_NAMED_COMPONENTS = 200

#: Back-compat alias. Kept because the constant was published under this name
#: before it became a default.
MAX_NAMED_COMPONENTS = DEFAULT_MAX_NAMED_COMPONENTS


def _results_reader() -> Callable[..., dict]:
    """Imported lazily: `repo_survey_definition_adapter` imports this package
    (for `projection`), so a module-level import here would be circular."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        _architecture_recovery_results,
    )

    return _architecture_recovery_results


def build_proposal_annotations(
    registry, slug: str, *, results_reader: Callable[..., dict] | None = None,
    max_named: int | None = DEFAULT_MAX_NAMED_COMPONENTS,
) -> list[Annotation]:
    """The proposal for `slug`, as annotations. Empty when nothing was derived.

    Reads persisted findings rather than re-deriving: the IR docstring calls
    re-derivation and re-publication separable operations, and this is the
    separation being used. A proposal can therefore be republished — after an
    outage, or once a curator asks for it — without paying for the analysis
    again, and it publishes exactly what the analysis actually concluded rather
    than what a fresh run would conclude now.
    """
    read = results_reader or _results_reader()
    projected = read(registry, slug, PROPOSAL_DEPTH) or {}
    full = read(registry, slug, None) or {}

    named = [c for c in (projected.get("components") or []) if not c.get("structural")]
    every = full.get("components") or []
    if not every:
        return []

    to_name = named if max_named is None else named[:max_named]
    annotations: list[Annotation] = [_component_annotation(c) for c in to_name]

    annotations.append(_structural_annotation(every, full))
    clusters = _cluster_annotation(registry, slug)
    if clusters is not None:
        annotations.append(clusters)
    annotations.append(_summary_annotation(named, every, full, len(to_name), max_named))
    return annotations


def _component_annotation(component: dict[str, Any]) -> Annotation:
    """One proposed component, as a classification the curator can weigh.

    `ClassificationAnnotation` rather than a measure: the claim being made is
    "this looks like a Software Service", which is a classification with a
    confidence, not a measurement. The candidate list carries the proposed type
    when there is one — a component with no type is a real state (nothing
    matched the 13-value vocabulary) and is reported as such rather than
    defaulted into a plausible-looking guess.
    """
    proposed_by = component.get("proposed_by") or []
    ctype = component.get("type") or ""
    return ClassificationAnnotation(
        check_name="proposed_component",
        item_key=component['path'],
        summary=(
            f"Proposed component: {component.get('name') or component['path']}"
            + (f" — {ctype}" if ctype else " — type not determined")
        ),
        analysis_step=STEP,
        annotation_type_name=TYPE_COMPONENT,
        candidate_classifications=[ctype] if ctype else [],
        confidence=int(component.get("confidence") or 0),
        explanation=(
            f"path={component['path']}; "
            f"perspective={component.get('perspective') or 'unknown'}; "
            f"proposed_by={', '.join(proposed_by) if proposed_by else 'unattributed'}; "
            f"evidence={len(component.get('evidence') or [])} item(s); "
            f"depth={component.get('depth', 0)}"
            + (f"; parent={component['parent_path']}" if component.get("parent_path") else "")
            + ". Proposed by analysis — not an assertion that this component exists."
        ),
    )


def _structural_annotation(every: list[dict], full: dict) -> Annotation:
    """The complete hierarchy, ports and wires, as one payload.

    This is what keeps the projected view lossless. Structural nodes are kept
    and flagged rather than dropped: `scope_hierarchy.py` refuses to emit
    derived ancestors as components because "a derived parent is a structural
    node, never a component — emitting them as ordinary components would invent
    evidence", and report-then-curate §3 requires a grouping node render as a
    grouping node. Erasing them here would undo both.
    """
    hierarchy = [
        {
            "path": c["path"],
            "parent": c.get("parent_path") or "",
            "depth": c.get("depth", 0),
            "name": c.get("name") or c["path"],
            "type": c.get("type") or "",
            "confidence": c.get("confidence") or 0,
            "structural": bool(c.get("structural")),
            "perspective": c.get("perspective") or "",
            "proposed_by": c.get("proposed_by") or [],
        }
        for c in every
    ]
    ports, wires = _ports_and_wires(full)
    structural_count = sum(1 for h in hierarchy if h["structural"])
    return ResourceMeasureAnnotation(
        check_name="proposed_hierarchy",
        summary=(
            f"Full proposed hierarchy: {len(hierarchy) - structural_count} component(s), "
            f"{structural_count} grouping node(s), {len(ports)} port(s), {len(wires)} wire(s)"
        ),
        analysis_step=STEP,
        annotation_type_name=TYPE_STRUCTURE,
        resource_properties={
            "hierarchy_json": json.dumps(hierarchy, separators=(",", ":")),
            "ports_json": json.dumps(ports, separators=(",", ":")),
            "wires_json": json.dumps(wires, separators=(",", ":")),
            "component_count": len(hierarchy) - structural_count,
            "structural_node_count": structural_count,
        },
        confidence=100,   # a faithful record of what was derived, not a claim about the system
        explanation=(
            "The unprojected hierarchy behind the individually-named components. "
            "Grouping nodes are flagged `structural` and carry no type or confidence — "
            "they are derived ancestors, not recovered components."
        ),
    )


def _ports_and_wires(full: dict) -> tuple[list[dict], list[dict]]:
    """Pull ports and wires out of the reader's `interfaces` groups.

    NOT `full["ports"]` / `full["wires"]`. The IR has those as top-level lists,
    but `_architecture_recovery_results` does not surface them under those
    names — it returns an `interfaces` list, each entry holding `components`
    (each with its own `ports`) and `wires`. The first version of this module
    read the IR's names against the reader's result, got `[]` from both, and
    published "0 port(s), 0 wire(s)" for a repo with 31 ports and 30 wires
    recorded. Silently reporting zero for data that exists is the exact failure
    the surrounding design is built to avoid, so this is deliberately explicit
    about where it reads from.
    """
    ports: list[dict] = []
    wires: list[dict] = []
    for group in full.get("interfaces") or []:
        if not isinstance(group, dict):
            continue
        for component in group.get("components") or []:
            for port in component.get("ports") or []:
                ports.append({"component": component.get("name", ""), **(
                    port if isinstance(port, dict) else {"port": port})})
        for wire in group.get("wires") or []:
            if isinstance(wire, dict):
                wires.append(wire)
    return ports, wires


def _cluster_annotation(registry, slug: str) -> Annotation | None:
    """Candidate blueprint clusters, if any were proposed.

    Deliberately plural and deliberately not chosen between: §2b of
    report-then-curate makes the point that a monorepo may hold several
    blueprints, that "what proposes the clusters" is new work, and that a
    proposal is *allowed* to offer more than one candidate clustering for the
    curator to pick — which is a far easier problem than getting it right
    unattended, and is only available because nothing is written directly.
    """
    try:
        scopes = registry.query_finding_scopes(slug, "architecture_blueprints")
    except Exception:
        return None
    if not scopes:
        return None
    return ResourceMeasureAnnotation(
        check_name="blueprint_clusters",
        summary=f"{len(scopes)} candidate blueprint cluster(s) proposed",
        analysis_step=STEP,
        annotation_type_name=TYPE_CLUSTERS,
        resource_properties={
            "candidate_clusters": len(scopes),
            "cluster_scopes_json": json.dumps(sorted(scopes)[:500], separators=(",", ":")),
        },
        confidence=50,
        explanation=(
            "Candidate clusterings, offered for a curator to choose between rather than "
            "resolved to one. A repo is a storage boundary, not a solution boundary — "
            "one repo may hold several blueprints, or contribute to one that spans repos."
        ),
    )


def _summary_annotation(
    named: list[dict], every: list[dict], full: dict, named_count: int,
    max_named: int | None,
) -> Annotation:
    """Counts, census and analyzerVersion.

    `analyzerVersion` is load-bearing and not decoration: §6.2 of the design —
    without it, a metric that moves between two runs is ambiguous, because you
    cannot tell whether the code changed or the detector improved.
    """
    from .ir import ANALYZER, ANALYZER_VERSION

    truncated = max(0, len(named) - named_count)
    return ResourceMeasureAnnotation(
        check_name="architecture_proposal",
        summary=(
            f"Architecture proposal: {named_count} component(s) named "
            f"individually of {len(every)} derived"
            + (f"; {truncated} not named (limit {max_named} — raise it to name them all)"
               if truncated else "")
        ),
        analysis_step=STEP,
        annotation_type_name=TYPE_SUMMARY,
        resource_properties={
            "components_named": named_count,
            "components_derived": len(every),
            "components_not_named": truncated,
            "name_limit": max_named if max_named is not None else "none",
            "projection_depth": PROPOSAL_DEPTH,
            "analyzerName": ANALYZER,
            "analyzerVersion": ANALYZER_VERSION,
            "partial": bool(full.get("partial")),
            "scoped": bool(full.get("scoped")),
        },
        confidence=100,
        explanation=(
            "A proposal, not an assertion: nothing structural exists in Egeria until a "
            "curator materialises it. Components are named at projection depth "
            f"{PROPOSAL_DEPTH}; the full hierarchy is in the structural annotation "
            "alongside this one."
        ),
    )
