"""Sub-surveyor: an OpenSSF-Scorecard-shaped assessment, over data already held.

Answers "how does it measure up on the FOSS scorecard?" without collecting
anything new. Every check below reads `project_stats` or findings another
analysis already wrote — the same read-only-at-survey-time relationship
CiQualitySurveyor has with its own findings.

**The one place this deliberately departs from OpenSSF Scorecard.** Scorecard
awards a low score to a check it could not evaluate, so "this project has no
branch protection" and "we could not see whether it has branch protection"
both land as a bad number, and the aggregate silently mixes them. That is the
failure this codebase keeps removing, so here an unevaluable check reports
`not_established` and is EXCLUDED from the score, and the coverage is reported
alongside it: a 9.1 scored over 6 of 13 checks is a different claim from a 9.1
scored over 13, and the reader gets to see which they have.

Consequently the score is not comparable with a published OpenSSF score. It is
not trying to be — it is trying to be true about what was measured.

Checks are declared in CHECKS, one entry each, so adding one is a function and
a row rather than an edit in several places.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from dataclasses import dataclass
from typing import Callable

from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, QualityScoreAnnotation

log = logging.getLogger(__name__)

STEP = "FossScorecard"

#: What a check concluded. `unknown` is the important one — it means the check
#: could not be evaluated from what we hold, and it never contributes to the
#: score in either direction.
PASS = "pass"
FAIL = "fail"
PARTIAL = "partial"
UNKNOWN = "unknown"

#: Points a state contributes, on OpenSSF's 0–10 per-check scale. `unknown` has
#: no entry at all: it is not a zero, it is an absence, and giving it a number
#: here is exactly how the two get confused.
_POINTS = {PASS: 10.0, PARTIAL: 5.0, FAIL: 0.0}


@dataclass
class Check:
    id: str
    title: str
    #: (stats, findings_by_kind) -> (state, detail_str)
    evaluate: Callable
    #: What would make this evaluable, when it is not. Shown to the reader, so
    #: "unknown" is actionable rather than merely honest.
    needs: str = ""


def _stat(stats: dict, key, default=None):
    v = stats.get(key)
    return default if v in (None, "") else v


def _c_maintained(stats, findings) -> tuple:
    if _stat(stats, "archived"):
        return FAIL, "Repository is archived."
    c90 = _stat(stats, "commits_90d", 0) or 0
    c30 = _stat(stats, "commits_30d", 0) or 0
    if c90 >= 30:
        return PASS, f"{c90} commit(s) in the last 90 days."
    if c90 > 0 or c30 > 0:
        return PARTIAL, f"Only {c90} commit(s) in 90 days — active but slow."
    return FAIL, "No commits recorded in the last 90 days."


def _c_license(stats, findings) -> tuple:
    spdx = (_stat(stats, "license_spdx_id", "") or "").strip()
    name = (_stat(stats, "license", "") or "").strip()
    if spdx and spdx.upper() != "NOASSERTION":
        return PASS, f"{spdx}"
    if name:
        # GitHub found a LICENSE file it could not identify. Not nothing, but
        # not a usable licence declaration either.
        return PARTIAL, f"A licence file exists but was not identified ({name})."
    return FAIL, "No licence detected."


def _c_ci_tests(stats, findings) -> tuple:
    rows = findings.get("ci_quality") or []
    if not rows:
        return UNKNOWN, "The CI quality analysis has not run for this resource."
    by_name = {r.get("check_name"): (r.get("label") or "").lower() for r in rows}
    runs_tests = by_name.get("ci_runs_tests", "")
    if runs_tests in ("yes", "true", "pass", "present"):
        return PASS, "CI runs tests."
    if by_name:
        return FAIL, f"CI present but no test execution detected ({', '.join(sorted(by_name))})."
    return UNKNOWN, "No CI findings recorded."


def _c_security_policy(stats, findings) -> tuple:
    for kind in ("security_scan", "security_features"):
        for r in findings.get(kind) or []:
            if "polic" in (r.get("check_name") or "").lower():
                label = (r.get("label") or "").lower()
                good = label in ("pass", "present", "yes", "true")
                return (PASS if good else FAIL), r.get("summary") or label
    return UNKNOWN, "Neither security analysis has run for this resource."


def _c_releases(stats, findings) -> tuple:
    count = _stat(stats, "releases_count", 0) or 0
    if count <= 0:
        return FAIL, "No releases published."
    interval = _stat(stats, "avg_release_interval_days")
    detail = f"{count} release(s)"
    if interval:
        detail += f", roughly every {interval} day(s)"
    return PASS, detail + "."


def _c_contributors(stats, findings) -> tuple:
    n = _stat(stats, "contributors_count", 0) or 0
    if n >= 10:
        return PASS, f"{n} contributors."
    if n >= 3:
        return PARTIAL, f"{n} contributors — a small group."
    if n > 0:
        # Bus factor. Reported as a real finding rather than an unknown: we
        # measured it, and the number is the concern.
        return FAIL, f"Only {n} contributor(s) — single-maintainer risk."
    return UNKNOWN, "Contributor count was not collected."


def _c_code_review(stats, findings) -> tuple:
    return UNKNOWN, "Requires pull-request review history."


def _c_branch_protection(stats, findings) -> tuple:
    return UNKNOWN, "Requires the branch-protection API, which needs admin scope."


def _c_signed_releases(stats, findings) -> tuple:
    return UNKNOWN, "Requires release asset signatures."


def _c_vulnerabilities(stats, findings) -> tuple:
    rows = findings.get("cve_scan") or []
    if not rows:
        return UNKNOWN, "No vulnerability scan has run — see the CVE analysis."
    open_cves = [r for r in rows if (r.get("label") or "").lower() not in ("clean", "none")]
    if open_cves:
        return FAIL, f"{len(open_cves)} dependency advisory match(es)."
    return PASS, "No advisories matched the recorded dependencies."


def _c_dependency_update(stats, findings) -> tuple:
    return UNKNOWN, "Requires detecting a dependency-update bot config."


def _c_sast(stats, findings) -> tuple:
    raw = _stat(stats, "security_and_analysis_json", "") or ""
    try:
        parsed = json.loads(raw) if isinstance(raw, str) else (raw or {})
    except (TypeError, ValueError):
        parsed = {}
    if not parsed:
        return UNKNOWN, "GitHub's security-and-analysis settings were empty or not collected."
    enabled = [k for k, v in parsed.items()
               if isinstance(v, dict) and v.get("status") == "enabled"]
    if enabled:
        return PASS, f"Enabled: {', '.join(sorted(enabled))}."
    return FAIL, "No GitHub security analysis features are enabled."


CHECKS: list = [
    Check("maintained", "Maintained", _c_maintained),
    Check("license", "License", _c_license),
    Check("ci_tests", "CI-Tests", _c_ci_tests,
          needs="Run the CI quality analysis (repo_ci_quality)."),
    Check("security_policy", "Security-Policy", _c_security_policy,
          needs="Run the security hygiene analysis (repo_security)."),
    Check("releases", "Packaging", _c_releases),
    Check("contributors", "Contributors", _c_contributors),
    Check("sast", "SAST", _c_sast),
    Check("vulnerabilities", "Vulnerabilities", _c_vulnerabilities,
          needs="Run a dependency advisory scan against the recorded dependencies."),
    Check("code_review", "Code-Review", _c_code_review,
          needs="Pull-request review history, which is not collected."),
    Check("branch_protection", "Branch-Protection", _c_branch_protection,
          needs="The branch-protection API, which needs admin scope on the repo."),
    Check("signed_releases", "Signed-Releases", _c_signed_releases,
          needs="Release asset signatures, which are not collected."),
    Check("dependency_update", "Dependency-Update-Tool", _c_dependency_update,
          needs="Detection of a dependency-update bot configuration."),
]


def score(results: list) -> dict:
    """Aggregate, over EVALUATED checks only.

    Unknown checks are excluded rather than zeroed, and `coverage` says how
    many were evaluated — a 9.1 over 6 of 12 checks is a different claim from
    a 9.1 over 12, and collapsing them is what makes a published scorecard
    number hard to trust.
    """
    # `label` carries the state -- upsert_finding's contract is
    # check_name/label/summary, so the state rides in `label` and not in a
    # field of its own.
    scored = [r for r in results if r.get("label") in _POINTS]
    total = sum(_POINTS[r["label"]] for r in scored)
    return {
        "score": round(total / len(scored), 1) if scored else None,
        "checks_evaluated": len(scored),
        "checks_total": len(results),
        "checks_unknown": len(results) - len(scored),
        "comparable_to_openssf": False,
    }


class FossScorecardSurveyor(BaseSurveyor):
    """OpenSSF-Scorecard-shaped checks over already-collected data."""

    def __init__(self, project, registry, surveyed_at: str | None = None) -> None:
        super().__init__(project, registry)
        # One timestamp per orchestrator run, so this batch groups with the
        # rest of its survey rather than landing milliseconds apart.
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        out: list[Annotation] = []
        try:
            slug = self.project.slug
            stats = self.registry.get_latest_project_stats(slug) or {}
            findings = {
                kind: (self.registry.query_findings(slug, kind) or [])
                for kind in ("ci_quality", "security_scan", "security_features", "cve_scan")
            }

            results = []
            for check in CHECKS:
                try:
                    state, detail = check.evaluate(stats, findings)
                except Exception as exc:   # one bad check must not lose the rest
                    log.debug("scorecard check %s failed: %s", check.id, exc)
                    state, detail = UNKNOWN, f"Check errored ({type(exc).__name__})."
                results.append({
                    "check_name": check.id, "label": state,
                    "summary": detail,
                    "confidence": 100 if state != UNKNOWN else 0,
                    "detail": {"title": check.title, "state": state,
                               "needs": check.needs if state == UNKNOWN else ""},
                })

            agg = score(results)
            self.registry.upsert_finding(slug, "foss_scorecard", results,
                                         surveyed_at=self._surveyed_at)
            if agg["score"] is not None:
                self.registry.upsert_metric(
                    slug, "foss_scorecard",
                    {"score": agg["score"],
                     "checks_evaluated": float(agg["checks_evaluated"]),
                     "checks_unknown": float(agg["checks_unknown"])},
                    detail=agg, surveyed_at=self._surveyed_at,
                )

            summary = (
                f"FOSS scorecard {agg['score']}/10 over "
                f"{agg['checks_evaluated']} of {agg['checks_total']} checks"
                if agg["score"] is not None else
                "No scorecard check could be evaluated from the data held"
            )
            out.append(QualityScoreAnnotation(
                summary=summary + (
                    f"; {agg['checks_unknown']} not evaluable"
                    if agg["checks_unknown"] else ""
                ),
                analysis_step=STEP,
                # Only the real score. `checks_evaluated`/`checks_unknown` are
                # counts, not quality dimensions, and putting them here would
                # make them read as scores in every consumer of this dict.
                quality_scores=({"foss_scorecard": float(agg["score"])}
                                if agg["score"] is not None else {}),
                confidence=80,
                json_properties={
                    **agg,
                    "checks": {r["check_name"]: r["label"] for r in results},
                },
            ))
        except Exception as exc:
            log.exception("FossScorecardSurveyor failed for %s", self.project.slug)
            self._warn(out, str(exc))
        return out
