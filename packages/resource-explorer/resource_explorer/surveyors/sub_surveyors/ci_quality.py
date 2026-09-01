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
from resource_explorer.step_outcome import StepOutcome
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
            if not findings:
                # An empty result set produced NO annotations at all, so a run
                # that found nothing and a run that never happened were the
                # same silence — and this step reads what `manifest_parse`
                # persisted, so an empty set usually means that upstream step
                # has not run rather than that this repo has no conventions.
                # Saying so is what makes the absence attributable.
                return [ClassificationAnnotation(
                    summary=("No ci_quality findings are recorded for this resource — "
                             "run the dependency/manifest refresh first. This is not "
                             "a finding that the repo has none."),
                    analysis_step=STEP,
                    candidate_classifications=[],
                    confidence=0,
                    json_properties=StepOutcome(
                        "unverified",
                        cause="no ci_quality findings recorded").as_row(),
                )]
            for f in findings:
                results.append(
                    ClassificationAnnotation(
                        summary=f.get("summary", ""),
                        analysis_step=STEP,
                        candidate_classifications=[f["label"]],
                        confidence=f.get("confidence", 80),
                        json_properties={"check_name": f["check_name"],
                                         **StepOutcome(
                                             "recovered",
                                             detail={"findings": len(findings)}).as_row()},
                    )
                )
        except Exception as exc:
            log.exception("CiQualitySurveyor failed for %s", self.project.slug)
            self._warn(results, str(exc))

        return results
