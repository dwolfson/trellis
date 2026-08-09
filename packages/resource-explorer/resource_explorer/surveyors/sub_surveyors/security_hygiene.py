"""Sub-surveyor: Security Hygiene → RequestForActionAnnotation."""
from __future__ import annotations

import logging
from datetime import datetime

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import (
    Annotation,
    ClassificationAnnotation,
    RequestForActionAnnotation,
)

log = logging.getLogger(__name__)

STEP = "SecurityHygieneCheck"

# Files whose presence indicates good security hygiene
_SECURITY_FILES = {
    "SECURITY.md": "Security policy",
    "SECURITY.rst": "Security policy",
    ".github/SECURITY.md": "Security policy (GitHub)",
}

_CI_INDICATORS = {
    ".github/workflows": "GitHub Actions CI",
    ".travis.yml": "Travis CI",
    "Jenkinsfile": "Jenkins CI",
    ".circleci/config.yml": "CircleCI",
    ".gitlab-ci.yml": "GitLab CI",
    "azure-pipelines.yml": "Azure Pipelines",
}

_LICENSE_FILES = {"LICENSE", "LICENSE.md", "LICENSE.txt", "LICENSE.rst", "COPYING"}


class SecuritySurveyor(BaseSurveyor):
    """
    Checks indexed file paths for the presence of security, CI, and license
    artifacts.  Emits RequestForAction for each gap found, and
    ClassificationAnnotation for each artifact present.
    """

    def __init__(self, project: Project, registry: ProjectRegistry, surveyed_at: str | None = None) -> None:
        super().__init__(project, registry)
        # Shared run-timestamp from SurveyOrchestrator, so this run's
        # findings can be correlated with other surveyors' writes from the
        # same orchestrator.run() call (Phase B, D1) — defaults to a fresh
        # timestamp so this surveyor stays independently callable/testable.
        self._surveyed_at = surveyed_at or datetime.utcnow().isoformat()

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        findings: list[dict] = []
        try:
            with self.registry._conn() as conn:
                path_rows = conn.execute(
                    "SELECT DISTINCT file_path FROM project_code_symbols WHERE project_slug = ?",
                    (self.project.slug,),
                ).fetchall()

            # Normalise paths for prefix/name matching
            paths = [r["file_path"].replace("\\", "/") for r in path_rows]
            filenames = {p.rsplit("/", 1)[-1] for p in paths}

            # Also check project_stats for license field
            with self.registry._conn() as conn:
                stats_row = conn.execute(
                    "SELECT license FROM project_stats WHERE project_slug = ? ORDER BY id DESC LIMIT 1",
                    (self.project.slug,),
                ).fetchone()
            license_from_stats = (stats_row["license"] if stats_row else "") or ""

            # ── Security policy ───────────────────────────────────────────────
            has_security = any(
                fname in filenames or any(p.endswith(fname) for p in paths)
                for fname in _SECURITY_FILES
            )
            if has_security:
                results.append(
                    ClassificationAnnotation(
                        summary="Security policy file present",
                        analysis_step=STEP,
                        candidate_classifications=["HasSecurityPolicy"],
                        confidence=100,
                    )
                )
                findings.append({
                    "check_name": "security_policy", "status": "pass",
                    "summary": "Security policy file present",
                    "detail": {"candidate_classifications": ["HasSecurityPolicy"]},
                })
            else:
                results.append(
                    RequestForActionAnnotation(
                        summary="No SECURITY.md found",
                        analysis_step=STEP,
                        action_requested="Add a SECURITY.md file describing the vulnerability disclosure process",
                        action_target_name="SECURITY.md",
                        explanation="A security policy helps users report vulnerabilities responsibly.",
                        confidence=90,
                    )
                )
                findings.append({
                    "check_name": "security_policy", "status": "gap",
                    "summary": "No SECURITY.md found",
                    "detail": {
                        "action_requested": "Add a SECURITY.md file describing the vulnerability disclosure process",
                        "action_target_name": "SECURITY.md",
                    },
                })

            # ── CI configuration ──────────────────────────────────────────────
            has_ci = any(
                any(p == indicator or p.startswith(indicator + "/") for p in paths)
                for indicator in _CI_INDICATORS
            ) or any(ind_file in filenames for ind_file in _CI_INDICATORS)

            if has_ci:
                ci_found = [
                    label for indicator, label in _CI_INDICATORS.items()
                    if any(p == indicator or p.startswith(indicator + "/") for p in paths)
                    or indicator in filenames
                ]
                results.append(
                    ClassificationAnnotation(
                        summary=f"CI configuration present: {', '.join(ci_found)}",
                        analysis_step=STEP,
                        candidate_classifications=ci_found,
                        confidence=95,
                    )
                )
                findings.append({
                    "check_name": "ci_config", "status": "pass",
                    "summary": f"CI configuration present: {', '.join(ci_found)}",
                    "detail": {"candidate_classifications": ci_found},
                })
            else:
                results.append(
                    RequestForActionAnnotation(
                        summary="No CI configuration detected",
                        analysis_step=STEP,
                        action_requested="Add a CI configuration (e.g. GitHub Actions workflow)",
                        action_target_name=".github/workflows/",
                        explanation="Automated testing improves code quality and contributor confidence.",
                        confidence=85,
                    )
                )
                findings.append({
                    "check_name": "ci_config", "status": "gap",
                    "summary": "No CI configuration detected",
                    "detail": {
                        "action_requested": "Add a CI configuration (e.g. GitHub Actions workflow)",
                        "action_target_name": ".github/workflows/",
                    },
                })

            # ── License ───────────────────────────────────────────────────────
            has_license = bool(license_from_stats) or bool(filenames & _LICENSE_FILES)
            if has_license:
                license_label = license_from_stats or "Present (file detected)"
                results.append(
                    ClassificationAnnotation(
                        summary=f"License: {license_label}",
                        analysis_step=STEP,
                        candidate_classifications=[license_label],
                        confidence=100,
                    )
                )
                findings.append({
                    "check_name": "license", "status": "pass",
                    "summary": f"License: {license_label}",
                    "detail": {"candidate_classifications": [license_label]},
                })
            else:
                results.append(
                    RequestForActionAnnotation(
                        summary="No license file detected",
                        analysis_step=STEP,
                        action_requested="Add a LICENSE file to clarify terms of use",
                        action_target_name="LICENSE",
                        explanation="Projects without a license are legally all-rights-reserved by default.",
                        confidence=90,
                    )
                )
                findings.append({
                    "check_name": "license", "status": "gap",
                    "summary": "No license file detected",
                    "detail": {
                        "action_requested": "Add a LICENSE file to clarify terms of use",
                        "action_target_name": "LICENSE",
                    },
                })

            try:
                self.registry.upsert_security_findings(self.project.slug, findings, surveyed_at=self._surveyed_at)
            except Exception as exc:
                log.warning("Could not persist security findings for %s: %s", self.project.slug, exc)

        except Exception as exc:
            log.exception("SecuritySurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
