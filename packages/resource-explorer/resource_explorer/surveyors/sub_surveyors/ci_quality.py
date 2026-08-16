"""Sub-surveyor: CI quality (does CI actually run tests/lint/build, not just
exist) → ClassificationAnnotation.

Assessment expansion plan B4. Real gap: SecurityHygieneSurveyor's "ci_config"
check only asks "does a CI config file exist" (presence) — this asks whether
it runs anything meaningful, via a heuristic keyword scan of workflow YAML
content (CiWorkflowParser, ingestion/ci_workflow_parser.py).

Read-only at survey time, same relationship DependencySurveyor has with
project_dependencies — the actual content parsing happens once, at ingestion
or "Refresh & profile" time (IngestionPipeline._parse_ci_workflows()), since
that's the one place the zipball is already being downloaded; re-downloading
it again here just to re-derive the same findings would be wasteful. "Run →"
on this card re-emits the most recently parsed findings rather than
re-scanning — the same, already-established precedent as dependency_analysis.
"""
from __future__ import annotations

import logging

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.base_surveyor import BaseSurveyor
from resource_explorer.surveyors.survey_report import Annotation, ClassificationAnnotation

log = logging.getLogger(__name__)

STEP = "CiQualityCheck"


class CiQualitySurveyor(BaseSurveyor):
    """Reads project_analysis_findings(kind="ci_quality") — written by
    IngestionPipeline._parse_ci_workflows() at ingestion/profile-refresh
    time — and re-emits it as annotations. No re-parsing here; see module
    docstring for why."""

    @property
    def step_name(self) -> str:
        return STEP

    def run(self) -> list[Annotation]:
        results: list[Annotation] = []
        try:
            slug = self.project.slug
            findings = self.registry.query_findings(slug, "ci_quality")
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
            log.exception("CiQualitySurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
