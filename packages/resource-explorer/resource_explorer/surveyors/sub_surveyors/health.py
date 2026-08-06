"""Sub-surveyor: Project Health → QualityScoreAnnotation."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, QualityScoreAnnotation

log = logging.getLogger(__name__)

STEP = "HealthAssessment"


class HealthSurveyor(BaseSurveyor):
    """
    Derives community health scores from GitHub stats in project_stats and
    recent commit activity from project_commits.

    Scores are normalised 0–100:
      activity_score   — commit frequency over 30/90/365d windows
      community_score  — stars, forks, contributor count
      release_score    — how regularly releases ship
      freshness_score  — days since last push / last commit
    """

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            with self.registry._conn() as conn:
                stats_row = conn.execute(
                    "SELECT stars, forks, contributors_count, commits_30d, commits_90d, "
                    "commits_365d, releases_count, avg_release_interval_days, last_pushed_at, "
                    "repo_created_at "
                    "FROM project_stats WHERE project_slug = ? ORDER BY id DESC LIMIT 1",
                    (slug,),
                ).fetchone()

                last_commit_row = conn.execute(
                    "SELECT committed_at FROM project_commits "
                    "WHERE project_slug = ? ORDER BY committed_at DESC LIMIT 1",
                    (slug,),
                ).fetchone()

            if not stats_row:
                self._warn(results, "No stats row found — run 'refresh' to populate stats.")
                return results

            s = dict(stats_row)
            stars = s.get("stars") or 0
            forks = s.get("forks") or 0
            contributors = s.get("contributors_count") or 0
            commits_30d = s.get("commits_30d") or 0
            commits_90d = s.get("commits_90d") or 0
            commits_365d = s.get("commits_365d") or 0
            releases = s.get("releases_count") or 0
            release_interval = s.get("avg_release_interval_days") or 0

            # ── freshness: days since last push ──────────────────────────────
            days_since_push = None
            last_pushed = s.get("last_pushed_at") or ""
            if last_pushed:
                try:
                    pushed_dt = datetime.fromisoformat(last_pushed.replace("Z", "+00:00"))
                    days_since_push = (datetime.now(timezone.utc) - pushed_dt).days
                except ValueError:
                    pass

            if days_since_push is None and last_commit_row:
                try:
                    committed_dt = datetime.fromisoformat(
                        last_commit_row["committed_at"].replace("Z", "+00:00")
                    )
                    days_since_push = (datetime.now(timezone.utc) - committed_dt).days
                except ValueError:
                    pass

            # ── score calculations ────────────────────────────────────────────
            activity_score = min(100, (commits_30d * 3) + (commits_90d // 2) + (commits_365d // 10))
            community_score = min(100, int((stars / 100) * 20 + (forks / 20) * 20 + min(contributors, 50) * 1.2))
            release_score = (
                min(100, max(0, 100 - release_interval)) if releases > 0 and release_interval > 0 else 0
            )
            freshness_score = (
                max(0, 100 - (days_since_push * 2)) if days_since_push is not None else 50
            )

            quality_scores = {
                "activity": float(activity_score),
                "community": float(community_score),
                "release_cadence": float(release_score),
                "freshness": float(freshness_score),
            }
            overall = sum(quality_scores.values()) / len(quality_scores)

            results.append(
                QualityScoreAnnotation(
                    summary=(
                        f"Overall health score: {overall:.0f}/100 "
                        f"(activity={activity_score}, community={community_score}, "
                        f"releases={release_score}, freshness={freshness_score})"
                    ),
                    analysis_step=STEP,
                    quality_scores=quality_scores,
                    confidence=80,
                    json_properties={
                        "stars": stars,
                        "forks": forks,
                        "contributors": contributors,
                        "commits_30d": commits_30d,
                        "commits_90d": commits_90d,
                        "commits_365d": commits_365d,
                        "releases_count": releases,
                        "avg_release_interval_days": release_interval,
                        "days_since_last_push": days_since_push,
                    },
                )
            )

        except Exception as exc:
            log.exception("HealthSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
