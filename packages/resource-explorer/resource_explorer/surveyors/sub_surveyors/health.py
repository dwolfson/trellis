"""Sub-surveyor: Project Health → QualityScoreAnnotation."""
from __future__ import annotations

import json
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

    def __init__(self, project: Project, registry: ProjectRegistry, fast: bool = False) -> None:
        super().__init__(project, registry)
        # fast=True is Coarse Scout's own flag (StepInfo.accepts_fast,
        # repo_survey_definition_adapter.py) — skips StatsFetcher's N+1
        # per-commit diff-stats calls below. A confirmed real slowness bug,
        # not a hypothetical: several hundred sequential GitHub API calls
        # for an active repo's 90-day commit history, every single scan.
        self.fast = fast

    @property
    def step_name(self) -> str:
        return STEP

    @staticmethod
    def _parse_json(raw, default=None):
        if default is None:
            default = {}
        try:
            return json.loads(raw) if raw else default
        except (TypeError, ValueError):
            return default

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug

            # Refresh project_stats before reading it — previously this
            # surveyor only ever read whatever StatsFetcher wrote at
            # registration time (wizard.py/org_importer.py, never again),
            # so "Repository Health" silently scored stale stars/forks/
            # commit-activity data no matter how often it was run or
            # scheduled. Best-effort: a GitHub API hiccup here shouldn't
            # fail the whole health check — fall back to whatever's
            # already in project_stats, same as before this fix.
            try:
                from resource_explorer.github.stats_fetcher import StatsFetcher
                StatsFetcher().fetch(slug, fetch_diff_stats=not self.fast)
            except Exception:
                log.warning("HealthSurveyor: stats refresh failed for %s, using existing data", slug)

            # D2(c) (docs/repo-survey-catalog-completion-plan.md): use the
            # named registry accessor instead of hand-rolling this query —
            # was a confirmed duplicate of the same "latest project_stats
            # row" pattern security_hygiene.py's license check also wrote
            # independently. get_latest_project_stats() already does
            # SELECT * on the same table, a strict superset of the columns
            # this surveyor actually reads.
            s = self.registry.get_latest_project_stats(slug)

            with self.registry._conn() as conn:
                last_commit_row = conn.execute(
                    "SELECT committed_at FROM project_commits "
                    "WHERE project_slug = ? ORDER BY committed_at DESC LIMIT 1",
                    (slug,),
                ).fetchone()

            if not s:
                self._warn(results, "No stats row found — run 'refresh' to populate stats.")
                return results
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
                        # Everything else StatsFetcher persists — free (already
                        # on the Repository object) or cheap (deployments/
                        # environments) attributes not otherwise surfaced in
                        # the health score itself, included here so Egeria's
                        # catalog carries the full picture, not just the
                        # scored subset. See stats_fetcher.py.
                        "archived": bool(s.get("archived")),
                        "disabled": bool(s.get("disabled")),
                        "is_fork": bool(s.get("is_fork")),
                        "is_template": bool(s.get("is_template")),
                        "default_branch": s.get("default_branch") or "",
                        "has_issues": bool(s.get("has_issues")),
                        "has_wiki": bool(s.get("has_wiki")),
                        "has_discussions": bool(s.get("has_discussions")),
                        "has_projects": bool(s.get("has_projects")),
                        "has_pages": bool(s.get("has_pages")),
                        "network_count": s.get("network_count") or 0,
                        "subscribers_count": s.get("subscribers_count") or 0,
                        "visibility": s.get("visibility") or "",
                        "is_private": bool(s.get("is_private")),
                        "homepage": s.get("homepage") or "",
                        "mirror_url": s.get("mirror_url") or "",
                        "parent_full_name": s.get("parent_full_name") or "",
                        "allow_merge_commit": bool(s.get("allow_merge_commit")),
                        "allow_squash_merge": bool(s.get("allow_squash_merge")),
                        "allow_rebase_merge": bool(s.get("allow_rebase_merge")),
                        "allow_auto_merge": bool(s.get("allow_auto_merge")),
                        "allow_update_branch": bool(s.get("allow_update_branch")),
                        "delete_branch_on_merge": bool(s.get("delete_branch_on_merge")),
                        "security_and_analysis": self._parse_json(s.get("security_and_analysis_json")),
                        "environments": self._parse_json(s.get("environments_json"), default=[]),
                        "deployments_count": s.get("deployments_count") or 0,
                        "latest_deployment_at": s.get("latest_deployment_at") or "",
                        "latest_deployment_environment": s.get("latest_deployment_environment") or "",
                        "latest_deployment_ref": s.get("latest_deployment_ref") or "",
                    },
                )
            )

        except Exception as exc:
            log.exception("HealthSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
