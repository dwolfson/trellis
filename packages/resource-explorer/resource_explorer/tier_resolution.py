"""Which funnel tier did a recorded run belong to — asked of the catalog, not
of the row.

**The defect this exists for.** `activity_log.intent` is written at the moment
the row is created and never revisited, so it records what the catalog said on
that day. The catalog has since been retagged — twice, documented in `CLAUDE.md`
rule 17: three analyses moved `assessment` → `discovery` on 2026-08-20 on the
"does this collect, or does it reason over what is already collected" axis, and
`architecture_recovery` moved `discovery` → `analysis` on 2026-08-30 by a direct
decision. The column did not move with them.

Measured 2026-09-09, the two vocabularies no longer even overlap in shape:

    activity_log.intent          analysis_catalog.yaml intent
      assessment   891             assessment   ~14 analyses
      scouting     153             analysis      11
      discovery     72             discovery      7
      enrichment     5             scouting       6
      (no `analysis` rows at all)  curate         2

A tier analysis reading the column would have found **no `analysis` tier at
all** while 11 analyses declare it, and would have filed 891 rows — 79% of all
activity — under a label most of them no longer carry.

This is the codebase's own dominant bug class, in the data rather than the code:
a true statement about the mechanism (*what the catalog said then*) read as a
claim about the world (*what tier this work belongs to*).

**So resolve, do not read.** An `analysis_run` row names its `analysis_id`; a
`survey` row names its steps, and each step key belongs to exactly one analysis
(`REPO_ANALYSIS_STEP_MAP` partitions them). Either way the tier comes from the
catalog as it stands now.

**And say when you cannot.** A survey predating step recording carries no steps,
so which analyses it ran is unknowable — `get_analysis_last_run` already keeps a
reserved `__unattributed_surveys__` key for exactly this. Such a row is
`unattributable`, never silently dropped and never forced onto a tier: "we
cannot say which tier" and "no tier" are different facts and only one of them is
a measurement.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

log = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def current_tier_of_analysis() -> dict[str, str]:
    """{analysis_id: intent} as the catalog declares it TODAY.

    Cached because the catalog is a file read; `analysis_catalog_reader`'s own
    `clear_cache()` is the thing to call if it changes under a long-lived
    process, and this cache is cleared alongside it by `clear_cache()` below.
    """
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    out: dict[str, str] = {}
    for resource_type in ("repo", "database", "filesystem"):
        try:
            entries = get_analyses(resource_type, include_egeria_live=False)
        except Exception:       # a resource type with no catalog of its own
            # Recorded, not swallowed. A resource type whose catalog fails to
            # load silently contributes no tiers, and every row for it then
            # reads `unknown-analysis` — a whole resource type quietly missing
            # from a tier analysis, with nothing saying why.
            log.debug("no analysis catalog for resource type %r", resource_type,
                      exc_info=True)
            continue
        for entry in entries:
            intent = (entry.get("intent") or "").strip()
            if entry.get("id") and intent:
                out[entry["id"]] = intent
    return out


@lru_cache(maxsize=1)
def _step_key_owner() -> dict[str, str]:
    """{step_key: analysis_id} — the inverse of the OWNERSHIP map.

    Ownership, deliberately, not `REPO_ANALYSIS_SOURCE_STEPS`: this answers
    "whose work was this step", which is attribution, and the source map exists
    to answer the different question of what to run. Using the source map here
    would credit `architecture_diagram` for the recovery's steps again — the
    exact defect fixed on 2026-09-08.
    """
    from resource_explorer.surveyors.repo_survey_definition_adapter import (
        REPO_ANALYSIS_STEP_MAP,
    )

    return {key: analysis_id
            for analysis_id, keys in REPO_ANALYSIS_STEP_MAP.items()
            for key in keys}


def clear_cache() -> None:
    """Drop both caches — for tests, and for a process that reloads the
    catalog."""
    current_tier_of_analysis.cache_clear()
    _step_key_owner.cache_clear()


@dataclass(frozen=True)
class TierAttribution:
    """What tier(s) one activity_log row belongs to, and how confidently."""

    #: Current tiers, from the catalog. A survey spanning several analyses can
    #: legitimately touch more than one, which is why this is a set and not a
    #: value — collapsing it to "the" tier would be a choice disguised as a
    #: reading.
    tiers: frozenset[str] = frozenset()
    analyses: frozenset[str] = frozenset()
    #: "attributed" / "unattributable" / "unknown-analysis" / "not-a-run"
    state: str = "not-a-run"
    #: What the row itself claims, kept so drift is measurable rather than
    #: merely asserted.
    recorded_tier: str = ""

    @property
    def resolved(self) -> bool:
        return self.state == "attributed"

    @property
    def drifted(self) -> bool:
        """Does the row's own label disagree with the catalog's current one?

        Only meaningful for a row resolving to exactly one tier; a multi-tier
        survey has no single label to compare against, and calling that
        "drifted" would count the shape of the row as a disagreement.
        """
        return (self.resolved and len(self.tiers) == 1
                and bool(self.recorded_tier)
                and self.recorded_tier != next(iter(self.tiers)))


def tier_of_activity_row(operation: str, detail: dict,
                         recorded_intent: str = "") -> TierAttribution:
    """Resolve one `activity_log` row to its CURRENT tier(s).

    `detail` is the row's parsed `detail` JSON. Rows that are neither an
    `analysis_run` nor a `survey` are `not-a-run` — a `catalog` or `scout` row
    is real activity but is not a tier's work being done to a resource.
    """
    if not isinstance(detail, dict):
        detail = {}
    tiers_by_analysis = current_tier_of_analysis()

    if operation == "analysis_run":
        analysis_id = detail.get("analysis_id") or ""
        tier = tiers_by_analysis.get(analysis_id)
        if not analysis_id:
            return TierAttribution(state="unattributable",
                                   recorded_tier=recorded_intent)
        if not tier:
            # The id is recorded but the catalog no longer has it — a removed or
            # renamed analysis. Its tier is genuinely unknown, not absent.
            return TierAttribution(analyses=frozenset({analysis_id}),
                                   state="unknown-analysis",
                                   recorded_tier=recorded_intent)
        return TierAttribution(frozenset({tier}), frozenset({analysis_id}),
                               "attributed", recorded_intent)

    if operation == "survey":
        steps = detail.get("steps") or []
        if not steps:
            # Predates step recording. Which analyses ran is unknowable — NOT
            # none. Forcing it onto the recorded intent is exactly the read this
            # module exists to prevent.
            return TierAttribution(state="unattributable",
                                   recorded_tier=recorded_intent)
        owner = _step_key_owner()
        analyses = {owner[k] for k in
                    (str(s.get("step") or "").rsplit("::", 1)[-1] for s in steps)
                    if k in owner}
        tiers = {tiers_by_analysis[a] for a in analyses if a in tiers_by_analysis}
        if not tiers:
            return TierAttribution(frozenset(analyses), frozenset(analyses),
                                   "unknown-analysis", recorded_intent)
        return TierAttribution(frozenset(tiers), frozenset(analyses),
                               "attributed", recorded_intent)

    return TierAttribution(state="not-a-run", recorded_tier=recorded_intent)


@dataclass
class TierCoverage:
    """Totals over a set of rows — the denominator a tier analysis needs."""

    attributed: int = 0
    unattributable: int = 0
    unknown_analysis: int = 0
    not_a_run: int = 0
    drifted: int = 0
    rows_by_tier: dict[str, int] = field(default_factory=dict)
    recorded_vs_current: dict[tuple[str, str], int] = field(default_factory=dict)

    @property
    def considered(self) -> int:
        """Rows that are a tier's work being done — the honest denominator.
        Excludes `not-a-run`, includes the ones we could not attribute, because
        dropping those would inflate every percentage computed from this."""
        return self.attributed + self.unattributable + self.unknown_analysis

    def add(self, attribution: TierAttribution) -> None:
        if attribution.state == "attributed":
            self.attributed += 1
            for tier in attribution.tiers:
                self.rows_by_tier[tier] = self.rows_by_tier.get(tier, 0) + 1
            if attribution.drifted:
                self.drifted += 1
                key = (attribution.recorded_tier, next(iter(attribution.tiers)))
                self.recorded_vs_current[key] = self.recorded_vs_current.get(key, 0) + 1
        elif attribution.state == "unattributable":
            self.unattributable += 1
        elif attribution.state == "unknown-analysis":
            self.unknown_analysis += 1
        else:
            self.not_a_run += 1
