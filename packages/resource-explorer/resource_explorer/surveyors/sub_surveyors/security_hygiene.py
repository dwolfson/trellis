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


class SecurityHygieneSurveyor(BaseSurveyor):
    """
    Checks indexed file paths for the presence of security, CI, and license
    artifacts.  Emits RequestForAction for each gap found, and
    ClassificationAnnotation for each artifact present.

    Renamed from "SecuritySurveyor" — that name implied real security
    scanning (secrets, CVEs, SAST), but this only ever checked 3 hygiene
    artifacts (SECURITY.md, CI config, license presence), matching its own
    STEP = "SecurityHygieneCheck". The rename frees "security" as a family
    name for future analyses that do real scanning (secret detection,
    dependency-vulnerability/CVE checks, SAST, branch-protection audits) —
    see repo_survey_definition_adapter.py's ANALYSIS_KINDS registry,
    `family="security"`. Identifiers (analysis_catalog id "security_scan",
    step key "repo_security") deliberately did NOT change — only the
    Python class/file name, to avoid breaking existing schedules/data.
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
            # D2(c) (docs/repo-survey-catalog-completion-plan.md): a
            # confirmed duplicate of file_structure.py's identical query,
            # now the named registry accessor.
            paths = self.registry.get_code_symbol_file_paths(self.project.slug)

            # Normalise paths for prefix/name matching
            paths = [p.replace("\\", "/") for p in paths]
            filenames = {p.rsplit("/", 1)[-1] for p in paths}

            # Also check project_stats for license field — via the named
            # registry accessor (D2(c), docs/repo-survey-catalog-completion-
            # plan.md), not a hand-rolled query — this and health.py were a
            # confirmed duplicate of the same "latest project_stats row"
            # pattern.
            stats_row = self.registry.get_latest_project_stats(self.project.slug)
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
                # Generic findings table (analysis-kind extensibility
                # redesign) — "status" (pass/gap) here becomes "label" in
                # the generic schema, since other finding kinds (e.g.
                # documentation) use "label" for a different kind of value.
                self.registry.upsert_finding(
                    self.project.slug, "security_hygiene",
                    [
                        {"check_name": f["check_name"], "label": f["status"],
                         "summary": f["summary"], "detail": f.get("detail")}
                        for f in findings
                    ],
                    surveyed_at=self._surveyed_at,
                )
            except Exception as exc:
                log.warning("Could not persist security hygiene findings for %s: %s", self.project.slug, exc)

        except Exception as exc:
            log.exception("SecurityHygieneSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
