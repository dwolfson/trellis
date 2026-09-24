"""The two derived metrics that test the funnel's premise (design §17.2).

The funnel's whole argument is that early stages are cheaper than later ones.
It has been asserted in several documents and measured once
(`docs/funnel-cost-measured.md`), on one axis — seconds — which is the axis the
argument is not really about. These two read the vector instead.

**Cost per question answered**, per step and per survey definition. "A Scouting
definition that answers five questions for 2 s and 0 API calls, and an Analysis
definition that answers twelve for 90 s and 340 calls, are both fine; the same
Analysis definition answering three is the one to look at." So the metric is
per-axis and its denominator is yield, not runs.

**Tier ratio per resource**: a cheap tier's cost as a fraction of an expensive
one's, on each axis. Where it is not small, a step is mis-tiered or
under-declared — the disagreement check generalised from "did it open a
connection" to every axis.

**Functions over `step_runs`, not a dashboard.** §17.3's Admin panel is
explicitly designer round 2, "after the vector has a few weeks of rows in it".
These compute the numbers that panel will show, so the panel is a rendering
problem when it arrives and the arithmetic is already pinned by tests.

**Absence is a result here too, and it is the easy thing to get wrong.**
Dividing a cost by a yield of zero is the shape this codebase keeps removing:
`None` for "cannot be computed" is returned everywhere the denominator is
absent, never `0.0` and never `inf`, and `questions_answered == -1` ("never
determined") is excluded from the denominator rather than counted as none.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

#: The axes a cost-per-question is worth computing on. `wall_ms` is what the
#: user waits; `cpu_ms` is what tier placement claims; `api_calls` is the
#: scarce resource for repositories; `bytes_fetched` and `egeria_calls` are
#: load somebody else pays for.
AXES = ("wall_ms", "cpu_ms", "bytes_fetched", "api_calls", "egeria_calls",
        "llm_tokens_in", "llm_tokens_out")


@dataclass
class CostPerQuestion:
    """One step's (or definition's) cost against what it answered."""
    key: str
    runs: int = 0
    questions: int = 0
    totals: dict = field(default_factory=dict)
    #: axis -> cost per question, or None when `questions` is 0/unknown.
    per_question: dict = field(default_factory=dict)
    #: True when at least one contributing run could not say how many
    #: questions it answered. The per-question figures are then computed over
    #: the runs that could, and a reader must not read them as covering all
    #: of them.
    partial: bool = False

    def as_dict(self) -> dict:
        return {"key": self.key, "runs": self.runs, "questions": self.questions,
                "totals": dict(self.totals), "per_question": dict(self.per_question),
                "partial": self.partial}


def _axis(metrics: dict, axis: str) -> float:
    value = metrics.get(axis)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0.0
    # -1 is this vector's "not captured" marker on several axes. Summing it
    # would make an unmeasured run look like a refund.
    return float(value) if value >= 0 else 0.0


def cost_per_question(rows, group_by: str = "step_key") -> dict[str, CostPerQuestion]:
    """{group key: CostPerQuestion} over `registry.query_step_runs()` rows.

    `group_by` is any column on the row — `step_key` for §17.3's "per step"
    view, `slug` for per resource. A survey definition's own cost is a query
    over its steps rather than a second measurement (§17.2's storage note), so
    a caller wanting that passes the rows for that definition's steps.
    """
    out: dict[str, CostPerQuestion] = {}
    for row in rows or ():
        key = str(row.get(group_by) or "")
        metrics = row.get("metrics") or {}
        entry = out.setdefault(key, CostPerQuestion(key))
        entry.runs += 1
        answered = metrics.get("questions_answered")
        if not isinstance(answered, int) or answered < 0:
            entry.partial = True
        else:
            entry.questions += answered
        for axis in AXES:
            entry.totals[axis] = entry.totals.get(axis, 0.0) + _axis(metrics, axis)
    for entry in out.values():
        for axis in AXES:
            total = entry.totals.get(axis, 0.0)
            # None, not 0.0 and not inf: a step that answered nothing has no
            # cost-per-question, and "was not cheap at any price" is a
            # sentence a reader writes, not a number this returns.
            entry.per_question[axis] = (
                round(total / entry.questions, 4) if entry.questions else None)
    return out


@dataclass
class TierRatio:
    """One resource's cheap-tier cost as a fraction of its expensive-tier cost."""
    slug: str
    cheap_tier: str
    expensive_tier: str
    #: axis -> ratio, or None when the expensive tier contributed nothing on
    #: that axis (dividing by it would invent a number).
    ratios: dict = field(default_factory=dict)
    cheap_totals: dict = field(default_factory=dict)
    expensive_totals: dict = field(default_factory=dict)
    cheap_runs: int = 0
    expensive_runs: int = 0

    @property
    def measurable(self) -> bool:
        """Whether this ratio rests on runs of BOTH tiers.

        A resource surveyed only at one tier has no ratio, and reporting 0.0
        (or 1.0) for it would put the funnel's best-looking number on the
        resources that never tested it.
        """
        return bool(self.cheap_runs and self.expensive_runs)

    def as_dict(self) -> dict:
        return {"slug": self.slug, "cheap_tier": self.cheap_tier,
                "expensive_tier": self.expensive_tier,
                "ratios": dict(self.ratios), "measurable": self.measurable,
                "cheap_runs": self.cheap_runs, "expensive_runs": self.expensive_runs,
                "cheap_totals": dict(self.cheap_totals),
                "expensive_totals": dict(self.expensive_totals)}


def tier_ratio(rows, tier_of, cheap_tier: str = "scouting",
               expensive_tier: str = "analysis") -> dict[str, TierRatio]:
    """{slug: TierRatio}, per resource, on every axis.

    `tier_of` maps a `step_key` to a tier name — the caller supplies it
    because the mapping is a property of the analysis catalog (and of which
    survey definition a step ran under), not of `step_runs`. Passing a dict's
    `.get` is the usual form.

    A step whose tier is unknown is EXCLUDED from both sides rather than
    guessed into one, which would move the ratio in a direction nothing
    measured.
    """
    out: dict[str, TierRatio] = {}
    for row in rows or ():
        tier = tier_of(str(row.get("step_key") or ""))
        if tier not in (cheap_tier, expensive_tier):
            continue
        slug = str(row.get("slug") or "")
        entry = out.setdefault(slug, TierRatio(slug, cheap_tier, expensive_tier))
        metrics = row.get("metrics") or {}
        totals = entry.cheap_totals if tier == cheap_tier else entry.expensive_totals
        if tier == cheap_tier:
            entry.cheap_runs += 1
        else:
            entry.expensive_runs += 1
        for axis in AXES:
            totals[axis] = totals.get(axis, 0.0) + _axis(metrics, axis)
    for entry in out.values():
        for axis in AXES:
            denominator = entry.expensive_totals.get(axis, 0.0)
            entry.ratios[axis] = (
                round(entry.cheap_totals.get(axis, 0.0) / denominator, 4)
                if entry.measurable and denominator else None)
    return out
