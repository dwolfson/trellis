"""Sub-surveyor: Discovery-tier repo conventions (security policy content,
build automation, deployment/Docker evidence, catalog self-description,
documentation breadth) → ClassificationAnnotation per check.

Assessment expansion Part 2 (docs/discovery-automate-project-context-plan.md).
Read-only at survey time — same relationship CiQualitySurveyor has with
project_analysis_findings: the actual file-tree scan happens once, at
ingestion or "Refresh & profile" time (IngestionPipeline._parse_repo_
conventions(), reusing RepoConventionsParser — see that module's docstring
for the standards these checks are grounded in), since that's the one
place the zipball is already being downloaded.
"""
from __future__ import annotations

import logging

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "RepoConventionsCheck"


class RepoConventionsSurveyor(BaseSurveyor):
    """Reads project_analysis_findings(kind="repo_conventions") — written by
    IngestionPipeline._parse_repo_conventions() at ingestion/profile-refresh
    time — and re-emits it as annotations. No re-parsing here; see module
    docstring."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug
            findings = self.registry.query_findings(slug, "repo_conventions")
            for f in findings:
                results.append(
                    ClassificationAnnotation(
                        summary=f.get("summary", ""),
                        analysis_step=STEP,
                        candidate_classifications=[f["label"]],
                        confidence=f.get("confidence", 80),
                        json_properties={"check_name": f["check_name"]},
                    )
                )
        except Exception as exc:
            log.exception("RepoConventionsSurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
