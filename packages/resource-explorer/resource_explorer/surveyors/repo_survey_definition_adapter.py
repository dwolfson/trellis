"""
Survey Definition adapter for Git repositories.

Registers a ResourceTypeAdapter (entity_type="repo") with
resource_explorer.surveyors.survey_definition_executor. Unlike the database
case, repo surveys are already composed of 10 independent sub-surveyor units
(resource_explorer.surveyors.sub_surveyors) — each one is exposed here as its
own re_analysis_step key, the most granular and natural fit for Survey
Definition steps. Publishing reuses the existing EgeriaPublisher.publish
unmodified — it's already narrow (no native-survey side effect).

Each step key delegates to SurveyOrchestrator.run(steps=[key]) rather than
instantiating its own surveyor closure — SurveyOrchestrator's own
{step_key: surveyor} map (survey_orchestrator.py) is the single source of
truth for what each key means and how its surveyor is constructed. This used
to duplicate that mapping here via independent closures; two lists of the
same ten surveyors that had to be kept in sync by hand. The scheduler's
per-analysis-id dispatch (scheduler.py's _run_repo_survey) reuses the same
SurveyOrchestrator.run(steps=...) entry point.
"""
from __future__ import annotations

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)


def _run_step(step_key: str, **orchestrator_kwargs):
    def runner(project, registry, **_) -> dict:
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        orch = SurveyOrchestrator(registry, **orchestrator_kwargs)
        result = orch.run(project.slug, steps=[step_key])
        return {"annotations": result.annotations}

    return runner


def _build_re_analysis_steps() -> dict:
    return {
        "repo_file_structure": _run_step("repo_file_structure"),
        "repo_file_size": _run_step("repo_file_size"),
        "repo_language": _run_step("repo_language"),
        "repo_health": _run_step("repo_health"),
        "repo_dependency": _run_step("repo_dependency"),
        "repo_documentation": _run_step("repo_documentation"),
        "repo_security": _run_step("repo_security"),
        "repo_api_structure": _run_step("repo_api_structure"),
        "repo_data_profiling": _run_step("repo_data_profiling", data_path=None),
        "repo_file_classification": _run_step(
            "repo_file_classification", pyegeria_client=None, force_refresh=False
        ),
    }


_RE_ANALYSIS_STEP_INFO = {
    "repo_file_structure": {
        "description": "File counts, per-language breakdown, and top-level directory structure.",
        "annotation_types": ["ResourceMeasureAnnotation"],
    },
    "repo_file_size": {
        "description": "Per-file sizes, total footprint, size-by-type, top-10 largest files.",
        "annotation_types": ["ResourceMeasureAnnotation", "RequestForActionAnnotation"],
    },
    "repo_language": {
        "description": "Primary/secondary language and coarse project-type classification.",
        "annotation_types": ["ClassificationAnnotation"],
    },
    "repo_health": {
        "description": "Activity, community, release-cadence, and freshness scoring from GitHub stats.",
        "annotation_types": ["QualityScoreAnnotation"],
    },
    "repo_dependency": {
        "description": "Package dependencies per ecosystem (PyPI/npm/Maven).",
        "annotation_types": ["DataClassAnnotation", "ResourceMeasureAnnotation"],
    },
    "repo_documentation": {
        "description": "Presence of README/CHANGELOG/CONTRIBUTING/SECURITY and overall doc-quality label.",
        "annotation_types": ["ClassificationAnnotation"],
    },
    "repo_security": {
        "description": "Presence of SECURITY.md, CI config, LICENSE — flags gaps as RFAs.",
        "annotation_types": ["ClassificationAnnotation", "RequestForActionAnnotation"],
    },
    "repo_api_structure": {
        "description": "Public API surface (functions/classes/methods) per language.",
        "annotation_types": ["SchemaAnalysisAnnotation", "ResourceMeasureAnnotation"],
    },
    "repo_data_profiling": {
        "description": "Inventories data files and profiles their schema (rows/columns/dtypes/nulls).",
        "annotation_types": ["ResourceMeasureAnnotation", "SchemaAnalysisAnnotation", "RequestForActionAnnotation"],
    },
    "repo_file_classification": {
        "description": "Classifies every file by type using filename/extension mapping (Egeria-enrichable).",
        "annotation_types": ["ClassificationAnnotation", "ResourceMeasureAnnotation"],
    },
}


def _get_project_entity(registry, slug: str):
    return registry.get(slug)


def _publish(project, step_outputs: list, surveyed_at: str, registry) -> str:
    from resource_explorer.surveyors.egeria_publisher import EgeriaPublisher
    from resource_explorer.surveyors.survey_report import SurveyResult

    result = SurveyResult(
        project_slug=project.slug,
        project_display_name=project.display_name,
        github_url=project.github_url,
    )
    for output in step_outputs:
        for ann in output.get("annotations", []):
            result.add(ann)

    publisher = EgeriaPublisher(registry=registry)
    return publisher.publish(result)


_ADAPTER = ResourceTypeAdapter(
    entity_type="repo",
    technology_type="Git Repository",
    re_analysis_steps=_build_re_analysis_steps(),
    get_entity=_get_project_entity,
    publish=_publish,
    re_analysis_step_info=_RE_ANALYSIS_STEP_INFO,
)

register_adapter(_ADAPTER)
