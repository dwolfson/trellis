"""Runs all sub-surveyors for a project and assembles a SurveyResult."""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime

from resource_explorer.activity_logger import log_survey
from resource_explorer.registry import ProjectRegistry
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

    def run(self, project_slug: str, steps: list[str] | None = None) -> SurveyResult:
        """Survey a single project and return the assembled SurveyResult.

        steps : optional list of step keys (same vocabulary as
            repo_survey_definition_adapter.py's re_analysis_steps — e.g.
            "repo_health", "repo_api_structure") to run only those
            sub-surveyors instead of the full set. None (default) runs
            every sub-surveyor, exactly as before this parameter existed.
        """
        project = self._registry.get(project_slug)
        if project is None:
            raise ValueError(f"Project '{project_slug}' not found in registry.")

        surveyed_at_dt = datetime.utcnow()
        # Shared run-timestamp, passed into the surveyors that persist
        # structured findings at survey time (Phase B, D1) — lets one
        # orchestrator run's writes across those tables be correlated,
        # instead of each independently stamping datetime.utcnow() seconds
        # apart. Dependency/DataProfiler persistence isn't threaded here —
        # those write at ingest/refresh time via IngestionPipeline, a
        # separate code path this orchestrator doesn't touch.
        surveyed_at = surveyed_at_dt.isoformat()

        result = SurveyResult(
            project_slug=project.slug,
            project_display_name=project.display_name,
            github_url=project.github_url,
            surveyed_at=surveyed_at_dt,
        )

        # Derived from STEP_REGISTRY (analysis-kind extensibility redesign) —
        # a plain (project, registry) construction is the default; the two
        # surveyors needing genuine per-instance orchestrator context
        # (FileClassifier's Egeria-refresh client, DataProfiler's clone
        # path) are the only explicit special cases, kept small and
        # commented rather than forcing a fully generic instance-attr-
        # injection mechanism for just these two. StepInfo.accepts_surveyed_at
        # marks the surveyors that persist structured findings/metrics and
        # need the shared per-run timestamp threaded in.
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY

        all_surveyors = {}
        for step_key, info in STEP_REGISTRY.items():
            if step_key == "repo_file_classification":
                kwargs = {
                    "pyegeria_client": self._pyegeria_client,
                    "force_refresh": self._force_refresh,
                }
            elif step_key == "repo_data_profiling":
                kwargs = {"local_path": self._data_path}
            else:
                kwargs = {}
            if info.accepts_surveyed_at:
                kwargs["surveyed_at"] = surveyed_at
            all_surveyors[step_key] = info.surveyor_cls(project, self._registry, **kwargs)

        if steps is None:
            surveyors = list(all_surveyors.values())
        else:
            surveyors = [all_surveyors[key] for key in steps if key in all_surveyors]

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

        # Any survey counts as "surveyed" — coarse scan or deep, full or
        # step-filtered — so this is unconditional, unlike the self-logging
        # below which only applies to a full (steps=None) run.
        try:
            self._registry.update_project_surveyed_at(project.slug)
        except Exception as exc:
            log.warning("Could not update last_surveyed_at for %s: %s", project.slug, exc)

        # Self-logging only applies to a full survey. A step-filtered (partial)
        # run is always driven by a caller that writes its own, more specific
        # activity-log entry (e.g. scheduler.py's per-analysis-id dispatch, or
        # repo_survey_definition_adapter.py's Survey Definition executor) —
        # logging here too would double-log every such run.
        if steps is None:
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
