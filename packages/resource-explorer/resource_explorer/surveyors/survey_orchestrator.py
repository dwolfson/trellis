"""Runs all sub-surveyors for a project and assembles a SurveyResult."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from resource_explorer.activity_logger import log_survey
from resource_explorer.registry import ProjectRegistry
from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import FileClassifierSurveyor
from resource_explorer.surveyors.sub_surveyors import (
    ApiStructureSurveyor,
    DataProfilerSurveyor,
    DependencySurveyor,
    DocumentationSurveyor,
    FileSizeSurveyor,
    FileStructureSurveyor,
    HealthSurveyor,
    LanguageSurveyor,
    SecuritySurveyor,
)
from resource_explorer.surveyors.survey_report import SurveyResult

log = logging.getLogger(__name__)


class SurveyOrchestrator:
    """
    Runs all sub-surveyors in sequence and returns a SurveyResult.

    Parameters
    ----------
    registry        : open ProjectRegistry
    pyegeria_client : optional — passed to FileClassifierSurveyor for cache refresh
    force_refresh   : force FileTypeCache refresh even if not stale
    """

    def __init__(
        self,
        registry: ProjectRegistry,
        pyegeria_client=None,
        force_refresh: bool = False,
        data_path: str | None = None,
    ) -> None:
        self._registry = registry
        self._pyegeria_client = pyegeria_client
        self._force_refresh = force_refresh
        self._data_path = data_path  # local clone path for DataProfilerSurveyor Tier 2

    def run(self, project_slug: str) -> SurveyResult:
        """Survey a single project and return the assembled SurveyResult."""
        project = self._registry.get(project_slug)
        if project is None:
            raise ValueError(f"Project '{project_slug}' not found in registry.")

        result = SurveyResult(
            project_slug=project.slug,
            project_display_name=project.display_name,
            github_url=project.github_url,
            surveyed_at=datetime.utcnow(),
        )

        surveyors = [
            FileClassifierSurveyor(
                project,
                self._registry,
                pyegeria_client=self._pyegeria_client,
                force_refresh=self._force_refresh,
            ),
            FileStructureSurveyor(project, self._registry),
            FileSizeSurveyor(project, self._registry),
            DataProfilerSurveyor(project, self._registry, local_path=self._data_path),
            LanguageSurveyor(project, self._registry),
            HealthSurveyor(project, self._registry),
            DependencySurveyor(project, self._registry),
            DocumentationSurveyor(project, self._registry),
            SecuritySurveyor(project, self._registry),
            ApiStructureSurveyor(project, self._registry),
        ]

        for surveyor in surveyors:
            log.info("Running %s for %s …", surveyor.step_name, project.slug)
            try:
                annotations = surveyor.run()
                for ann in annotations:
                    result.add(ann)
                log.info("  → %d annotation(s)", len(annotations))
            except Exception as exc:
                msg = f"{surveyor.step_name} raised unexpectedly: {exc}"
                log.exception(msg)
                result.add_error(msg)

        log.info(
            "Survey complete for %s: %d annotation(s), %d error(s)",
            project.slug,
            len(result.annotations),
            len(result.errors),
        )

        # Group annotations by analysis_step+type for a compact activity log entry
        by_step: dict[str, dict] = defaultdict(lambda: {"annotation_type": "", "count": 0, "summary": ""})
        for a in result.annotations:
            step = getattr(a, "analysis_step", None) or a.annotation_type.value
            by_step[step]["annotation_type"] = a.annotation_type.value
            by_step[step]["count"] += 1
            if not by_step[step]["summary"]:
                by_step[step]["summary"] = (a.summary or "")[:200]
        ann_summary = [
            {"analysis_name": step, "annotation_type": v["annotation_type"],
             "count": v["count"], "status": "local", "summary": v["summary"]}
            for step, v in list(by_step.items())[:20]
        ]

        try:
            log_survey(
                self._registry,
                entity_type="repo",
                entity_slug=project.slug,
                entity_name=project.display_name,
                entity_location=project.github_url,
                intent="assessment",
                status="error" if result.errors else "ok",
                summary=f"{len(result.annotations)} annotation(s), {len(result.errors)} error(s)",
                detail="; ".join(result.errors) if result.errors else "",
                annotations=ann_summary,
            )
        except Exception as exc:
            log.warning("Could not write activity log entry: %s", exc)

        return result
