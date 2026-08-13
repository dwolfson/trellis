"""Sub-surveyor: Project maturity/lifecycle stage (project age) →
ClassificationAnnotation.

Assessment expansion Part 2 (docs/discovery-automate-project-context-plan.md).
Deliberately narrow: HealthSurveyor (repo_health) already computes activity/
community/release-cadence/freshness scoring from GitHub stats — this does
NOT re-derive any of that (checked before writing this, see repo_health's
own module docstring). The one genuinely new signal not computed anywhere
today is project age/lifecycle stage — repo_created_at is fetched by
StatsFetcher and stored in project_stats, but nothing reads it (confirmed:
HealthSurveyor's own SELECT includes it but never references it in scoring
or json_properties).

Grounded in CHAOSS's lifecycle/evolution framing (a project's age is one of
its "Evolution" category metrics) — informed by, not a full implementation
of, CHAOSS's metric model. See
docs/discovery-automate-project-context-plan.md's "Standards & prior art"
section.

No trend_reader, matching license_classification's precedent — project age
trends monotonically upward by construction (every day older), so a "value
over time" chart has no analytical value; the only thing worth tracking is
tier transitions, which are rare/discrete events, not a chart.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "MaturityAssessment"

# Lifecycle-stage tiers, in ascending order of project age. Boundaries are a
# reasonable, documented starting point (not a CHAOSS-published threshold —
# CHAOSS defines the metric, not a specific tier cutoff), easy to revisit.
_TIERS = (
    (180, "nascent"),
    (730, "emerging"),       # ~2 years
    (1825, "established"),   # ~5 years
)
_TIER_LABELS = {
    "nascent": "Nascent (< 6 months old)",
    "emerging": "Emerging (6 months – 2 years old)",
    "established": "Established (2–5 years old)",
    "mature": "Mature (5+ years old)",
    "unknown": "Unknown (no creation date available)",
}


def _classify_age(age_days: int) -> str:
    for threshold, tier in _TIERS:
        if age_days < threshold:
            return tier
    return "mature"


class MaturitySurveyor(BaseSurveyor):
    """Reads project_stats.repo_created_at (already fetched by StatsFetcher,
    no new API call) and classifies project age into a lifecycle-stage
    tier. Produces exactly one finding, same "single current-state
    classification" shape as LicenseClassifierSurveyor."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug
            stats = self.registry.get_latest_project_stats(slug) or {}
            created_at = stats.get("repo_created_at") or ""

            age_days: int | None = None
            if created_at:
                try:
                    created_dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - created_dt).days
                except ValueError:
                    age_days = None

            if age_days is None:
                tier = "unknown"
                summary = _TIER_LABELS[tier]
            else:
                tier = _classify_age(age_days)
                years = age_days / 365.25
                summary = f"{years:.1f} years old — {_TIER_LABELS[tier]}"

            confidence = 90 if age_days is not None else 40

            results.append(
                ClassificationAnnotation(
                    summary=summary,
                    analysis_step=STEP,
                    candidate_classifications=[tier],
                    confidence=confidence,
                    json_properties={"repo_created_at": created_at, "age_days": age_days, "maturity_tier": tier},
                )
            )

            try:
                self.registry.upsert_finding(
                    slug, "maturity",
                    [{
                        "check_name": "project_maturity", "label": tier, "summary": summary,
                        "confidence": confidence, "detail": {"repo_created_at": created_at, "age_days": age_days},
                    }],
                    surveyed_at=datetime.now(timezone.utc).isoformat(),
                )
            except Exception as exc:
                log.warning("Could not persist maturity classification for %s: %s", slug, exc)

        except Exception as exc:
            log.exception("MaturitySurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
