"""The gaps collection — findings about the ANALYSIS, owned by the project.

SPEC-ACTIONABLE-AND-HONEST.md §3: "A finding about the analysis belongs in a
gaps list the project owns." Two shapes land here, and only these two —
everything else about the repository names a `destination` instead (see
destinations.py):

    not_measurable   a check that ran (or could have) and could not be
                      established for this resource — result_status's
                      NOT_ESTABLISHED / "not_established" label.
    disagreement      two measures point different ways for the same
                      underlying question (today: community_support's
                      participation vs. chaoss_metrics' authorship
                      concentration — facts.py's `measures_disagree`, the
                      "existing disagreement computation" this reuses rather
                      than re-deriving).

`collect_gaps` is pure — it reads the same sources the page reads
(project_analysis_findings via query_findings, and the resource-state facts
in facts.py) and returns gap dicts. It never writes. `record_gaps_for` is the
one caller that turns that into persistence, upserting through
ProjectRegistry.upsert_gap — called from FactLayer.facts() (see that
module), the one choke point every consumer of "what is known about this
resource" already goes through, so the collection is current whenever the
page is without a second scheduler loop.
"""
from __future__ import annotations

import logging

from resource_explorer.destinations import analyses_with_checks
from resource_explorer.surveyors.result_status import NOT_ESTABLISHED

log = logging.getLogger(__name__)

NOT_MEASURABLE = "not_measurable"
DISAGREEMENT = "disagreement"


def _not_measurable_gaps(registry, slug: str) -> list[dict]:
    """One gap per (analysis, check) whose latest finding row is labelled
    `not_established` — "ran, but this analysis cannot be credited with the
    result" (result_status.py). Scoped to check_registry.yaml's `analyses`
    section (the per-check ones query_findings can resolve a check_name
    against); `whole_analysis_only` ids have no check-level rows to read this
    way — a NOT_ESTABLISHED whole-analysis Fact is visible through
    FactLayer.fact() instead, not duplicated here."""
    out = []
    for analysis_id, spec in analyses_with_checks().items():
        kind = spec.get("findings_kind", analysis_id)
        rows = registry.query_findings(slug, kind) or []
        by_check = {r["check_name"]: r for r in rows}
        for check_name in spec.get("checks", []):
            row = by_check.get(check_name)
            if row and (row.get("label") or "") == NOT_ESTABLISHED:
                out.append({
                    "analysis_id": analysis_id,
                    "gap_kind": NOT_MEASURABLE,
                    "check_name": check_name,
                    "sentence": row.get("summary") or (
                        f"{check_name} could not be established for this "
                        f"resource by {analysis_id}."
                    ),
                    "evidence": {
                        "check_name": check_name, "label": row.get("label"),
                        "confidence": row.get("confidence"),
                    },
                })
    return out


def _disagreement_gaps(registry, slug: str) -> list[dict]:
    """One gap per resource-state resolver whose value carries
    `measures_disagree` — facts.py's own disagreement computation
    (`_r_community`, ~line 329), read rather than re-derived so this can never
    disagree with the card the user is looking at."""
    from resource_explorer.facts import RESOURCE_STATE_SOURCES

    project = registry.get(slug)
    if project is None:
        return []
    out = []
    for question, (resolver, subject) in RESOURCE_STATE_SOURCES.items():
        try:
            value, _state = resolver(registry, project)
        except Exception as exc:
            # A resolver failing to run is not itself a disagreement — it is
            # the kind of "could not check" the not_measurable half already
            # covers at the check level. Logged and skipped rather than
            # raised, because one resolver's failure must not stop every
            # other resolver in this loop from being checked.
            log.debug("gap resolver %s failed for %s: %s", subject, slug, exc)
            continue
        note = (value or {}).get("measures_disagree")
        if not note:
            continue
        out.append({
            "analysis_id": subject,
            "gap_kind": DISAGREEMENT,
            "check_name": subject,
            "sentence": note,
            "evidence": {"question": question, "value": value},
        })
    return out


def collect_gaps(registry, slug: str) -> list[dict]:
    """Every gap about the analysis, for one resource. Pure — no write.

    Each dict: {analysis_id, gap_kind, check_name, sentence, evidence}."""
    return _not_measurable_gaps(registry, slug) + _disagreement_gaps(registry, slug)


def record_gaps_for(registry, slug: str) -> list[dict]:
    """Collect and upsert — the write-side counterpart, called from the one
    choke point (FactLayer.facts()) so the collection is current whenever the
    page is. Returns what was collected (before persistence, which cannot
    fail on a duplicate — upsert_gap is idempotent by construction)."""
    gaps = collect_gaps(registry, slug)
    for g in gaps:
        registry.upsert_gap(
            slug, g["analysis_id"], g["gap_kind"], g["check_name"],
            g["sentence"], evidence=g.get("evidence"),
        )
    return gaps


def gaps_summary(registry, slug: str) -> dict:
    """The shape GET /api/projects/{slug}/gaps returns: every stored gap for
    this project, plus counts and `measures_total` per analysis so "3 of 11"
    is a real fraction rather than a bare numerator (§3's one-line collapse).

    Reads STORED gaps (registry.list_gaps), not a fresh collect_gaps() —
    the route is a read of what the choke point already recorded, matching
    every other "read what was persisted" route in this codebase; a route
    that re-collected on every call would duplicate the analysis work
    FactLayer.facts() already did for the same page load."""
    from resource_explorer.destinations import checks_per_analysis

    rows = registry.list_gaps(slug)
    open_rows = [r for r in rows if not r.get("resolved_at")]
    counts = {
        NOT_MEASURABLE: sum(1 for r in open_rows if r["gap_kind"] == NOT_MEASURABLE),
        DISAGREEMENT: sum(1 for r in open_rows if r["gap_kind"] == DISAGREEMENT),
        "total": len(open_rows),
    }
    by_analysis: dict[str, int] = {}
    for r in open_rows:
        by_analysis[r["analysis_id"]] = by_analysis.get(r["analysis_id"], 0) + 1
    return {
        "slug": slug,
        "gaps": rows,
        "counts": counts,
        "by_analysis": by_analysis,
        "measures_total": checks_per_analysis(),
    }
