"""DepthOffer — the /next pane's offer to run never-run analysis/assessment
tier analyses, priced with the measured/declared/unknown split.

Designer's spec (2026-09-13, "DepthOffer"): when a verdict of
`investigating`/`tracking` is recorded — and for `recommended`/`using` only
when the repo has never been measured; never for `abandoned`/`ignored` — the
/next pane shows the analyses at the analysis and assessment tiers that have
NEVER run on this resource, priced via `estimate_run_cost`, and offers "Run
these in background · Choose which · Not now". This module builds that offer
(`build_depth_offer`) and records its outcome on the verdict
(`record_depth_offer` — see registry.py, since the write lands on
`repo_disposition_history`).

Kept pure and registry-only (no FastAPI import) so it's unit-testable without
the app, same reasoning as `workflows/analysis.py`'s split from
`web/routes/projects.py` — the route stays a thin adapter.
"""
from __future__ import annotations

from resource_explorer.workflows.analysis import RunCost, _humanise_duration, estimate_run_cost

#: The three outcomes the designer's shape allows for the depth-offer POST.
#: `accepted`/`chose` both mean "ran something"; `declined` means the pane's
#: "Not now". Exported so the route and its tests share one vocabulary
#: instead of two copies that could drift.
DEPTH_OFFER_OUTCOMES = {"declined", "accepted", "chose"}

#: The two tiers this offer ever considers — assessment and analysis. Not
#: "perspective" or any other AnalysisCatalogEntry axis.
_OFFER_TIERS = {"assessment", "analysis"}


def run_cost_as_dict(cost: RunCost) -> dict:
    """`RunCost` as the plain dict both the depth-offer entries and the
    standalone GET /api/analyses/{analysis_id}/cost route return — factored
    out so the two can never drift apart (they call this same function)."""
    return {
        "seconds": cost.seconds,
        "steps_seconds": cost.steps_seconds,
        "publish_seconds": cost.publish_seconds,
        "basis": cost.basis,
        "runs": cost.runs,
        "split_runs": cost.split_runs,
        "via": cost.via,
        "sentence": cost.sentence(),
    }


#: Every resource_type analysis_catalog_reader knows about — kept here
#: rather than imported from that module (which has no such constant) so
#: `find_cost_for_analysis` can search all of them without hardcoding "repo"
#: the way the depth-offer proper (a repo-only offer, per the design) does.
_ALL_RESOURCE_TYPES = ("repo", "database", "filesystem")


def find_cost_for_analysis(registry, analysis_id: str) -> dict | None:
    """The `cost` dict for `analysis_id`, resolved across every resource
    type the local catalog knows about (repo/database/filesystem) — backs
    GET /api/analyses/{analysis_id}/cost, which 404s only when the id is in
    none of them. Local-catalog only (`include_egeria_live=False`), same
    choice `build_depth_offer` makes and for the same reason: a cost lookup
    should not depend on a live Egeria call succeeding.

    Returns None (never raises) for an unknown id — the route's own
    business, this function's job is just "found it or didn't"."""
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    for resource_type in _ALL_RESOURCE_TYPES:
        for entry in get_analyses(resource_type, include_egeria_live=False):
            if entry.get("id") == analysis_id:
                cost = estimate_run_cost(registry, analysis_id, resource_type=resource_type)
                return run_cost_as_dict(cost)
    return None


def _offerable_repo_analyses() -> list[dict]:
    """Catalog entries at the assessment/analysis tiers that a re-run could
    actually dispatch: not `action: "publish"`, and not anything
    `run_single_analysis`'s own gate (`_resolve_analysis_plan`) would reject
    for having no mapped survey step(s). Local-catalog only
    (`include_egeria_live=False`) — same choice `resolve_analysis_plan` and
    the scheduler already make, so this offer can never name an id the run
    route would then 400 on."""
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
    from resource_explorer.workflows.analysis import resolve_analysis_plan

    out = []
    for entry in get_analyses("repo", include_egeria_live=False):
        if entry.get("intent") not in _OFFER_TIERS:
            continue
        if entry.get("action") == "publish":
            continue
        is_ingest, steps = resolve_analysis_plan(entry["id"])
        if not is_ingest and not steps:
            continue
        out.append(entry)
    return out


def _has_run(analysis_id: str, last_run: dict) -> bool:
    """Has `analysis_id` ever run — including "its data exists because its
    SOURCE ran," for a derived analysis like `architecture_diagram` that
    owns no steps of its own and is purely a read-time VIEW over
    `architecture_recovery`'s stored findings (see that AnalysisKind's own
    comment). `assess_freshness` widens its candidate set the same way, for
    the same reason: `get_analysis_last_run` only credits a derived
    analysis's OWN run onto its source (so the source's freshness reflects a
    diagram run), never the reverse — so checking the derived id alone would
    call the diagram never-run the day after the recovery that backs it."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        repo_analysis_derived_sources,
    )

    ids = [analysis_id, *repo_analysis_derived_sources(analysis_id)]
    return any(i in last_run for i in ids)


def build_depth_offer(registry, slug: str) -> dict:
    """The GET /api/projects/{slug}/depth-offer payload — see this module's
    docstring and the designer's spec for the exact shape.

    Raises `LookupError` for an unknown slug, mirroring the sibling routes'
    404 (caught and translated in the route, kept out of this pure function
    so it stays FastAPI-free)."""
    project = registry.get(slug)
    if not project:
        raise LookupError(f"Project {slug!r} not found")

    candidates = _offerable_repo_analyses()
    last_run = registry.get_analysis_last_run("repo", slug)
    last_run.pop("__unattributed_surveys__", None)

    measured_before = any(_has_run(entry["id"], last_run) for entry in candidates)
    never_run = [entry for entry in candidates if not _has_run(entry["id"], last_run)]

    analyses = []
    for entry in never_run:
        cost = estimate_run_cost(registry, entry["id"], resource_type="repo")
        analyses.append({
            "analysis_id": entry["id"],
            "tier": entry["intent"],
            "display_name": entry["name"],
            "cost": run_cost_as_dict(cost),
        })

    total = _build_total(analyses)
    return {
        "slug": slug,
        "measured_before": measured_before,
        "analyses": analyses,
        "total": total,
    }


def _build_total(analyses: list[dict]) -> dict:
    if not analyses:
        return {
            "seconds": 0, "steps_seconds": 0, "publish_seconds": 0,
            "basis": "measured", "counted": [], "excluded": [],
            "sentence": "Nothing to offer — every analysis at these tiers has run here.",
        }

    counted_ids: list[str] = []
    excluded: list[dict] = []
    seconds_total = 0.0
    steps_vals: list[float] = []
    publish_vals: list[float] = []

    for entry in analyses:
        cost = entry["cost"]
        if cost["basis"] == "measured":
            counted_ids.append(entry["analysis_id"])
            seconds_total += cost["seconds"] or 0.0
            if cost["steps_seconds"] is not None:
                steps_vals.append(cost["steps_seconds"])
            if cost["publish_seconds"] is not None:
                publish_vals.append(cost["publish_seconds"])
        else:
            excluded.append({"analysis_id": entry["analysis_id"], "basis": cost["basis"]})

    if not counted_ids:
        declared_n = sum(1 for e in excluded if e["basis"] == "declared")
        unknown_n = sum(1 for e in excluded if e["basis"] == "unknown")
        return {
            "seconds": None, "steps_seconds": None, "publish_seconds": None,
            "basis": "measured", "counted": [], "excluded": excluded,
            "sentence": f"Nothing here is priced yet — {declared_n} declared, {unknown_n} unknown.",
        }

    steps_total = sum(steps_vals) if steps_vals else None
    publish_total = sum(publish_vals) if publish_vals else None
    sentence = f"{_humanise_duration(seconds_total)} in all across {len(counted_ids)}"
    if excluded:
        sentence += f"; {', '.join(e['analysis_id'] for e in excluded)} not priced."
    else:
        sentence += "."

    return {
        "seconds": seconds_total, "steps_seconds": steps_total,
        "publish_seconds": publish_total, "basis": "measured",
        "counted": counted_ids, "excluded": excluded, "sentence": sentence,
    }
