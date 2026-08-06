"""
Survey Definition adapter for Git repositories.

Registers a ResourceTypeAdapter (entity_type="repo") with
resource_explorer.surveyors.survey_definition_executor. Unlike the database
case, repo surveys are already composed of 10 independent sub-surveyor units
(resource_explorer.surveyors.sub_surveyors) — each one is exposed here as its
own re_analysis_step key, the most granular and natural fit for Survey
Definition steps. Publishing reuses the existing EgeriaPublisher.publish
unmodified — it's already narrow (no native-survey side effect).
"""
from __future__ import annotations

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)


def _run_sub_surveyor(surveyor_cls, **extra_ctor_kwargs):
    def runner(project, registry, **_) -> dict:
        surveyor = surveyor_cls(project, registry, **extra_ctor_kwargs)
        annotations = surveyor.run()
        return {"annotations": annotations}

    return runner


def _build_re_analysis_steps() -> dict:
    from resource_explorer.surveyors.sub_surveyors.file_structure import FileStructureSurveyor
    from resource_explorer.surveyors.sub_surveyors.file_size import FileSizeSurveyor
    from resource_explorer.surveyors.sub_surveyors.language import LanguageSurveyor
    from resource_explorer.surveyors.sub_surveyors.health import HealthSurveyor
    from resource_explorer.surveyors.sub_surveyors.dependency import DependencySurveyor
    from resource_explorer.surveyors.sub_surveyors.documentation import DocumentationSurveyor
    from resource_explorer.surveyors.sub_surveyors.security import SecuritySurveyor
    from resource_explorer.surveyors.sub_surveyors.api_structure import ApiStructureSurveyor
    from resource_explorer.surveyors.sub_surveyors.data_profiler import DataProfilerSurveyor
    from resource_explorer.surveyors.file_classifier.file_classifier_surveyor import (
        FileClassifierSurveyor,
    )

    return {
        "repo_file_structure": _run_sub_surveyor(FileStructureSurveyor),
        "repo_file_size": _run_sub_surveyor(FileSizeSurveyor),
        "repo_language": _run_sub_surveyor(LanguageSurveyor),
        "repo_health": _run_sub_surveyor(HealthSurveyor),
        "repo_dependency": _run_sub_surveyor(DependencySurveyor),
        "repo_documentation": _run_sub_surveyor(DocumentationSurveyor),
        "repo_security": _run_sub_surveyor(SecuritySurveyor),
        "repo_api_structure": _run_sub_surveyor(ApiStructureSurveyor),
        "repo_data_profiling": _run_sub_surveyor(DataProfilerSurveyor, local_path=None),
        "repo_file_classification": _run_sub_surveyor(
            FileClassifierSurveyor, pyegeria_client=None, force_refresh=False
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
