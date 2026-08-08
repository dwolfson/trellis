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


# qualified_name of the "Repo Coarse Scout" Survey Definition (a
# GovernanceActionProcess authored in Egeria via Dr.Egeria, chaining just
# repo_health + repo_language — both API-only, no clone needed). Referenced
# explicitly by web/routes/projects.py's scouting-scan endpoint rather than
# relying on technology_type auto-resolution, so it stays unambiguous even
# once a second ("deep") repo Survey Definition also exists — see the
# Scouting/Analysis/Assessment boundary plan. Authored once, out-of-band;
# this constant is the single place code and the Egeria-side element must
# agree on the name.
REPO_COARSE_SCOUT_SURVEY_DEFINITION_QN = "GovActionProcess::RepoCoarseScout"


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


# analysis_catalog "repo_analyses" id -> SurveyOrchestrator step key(s) it
# maps to (same step-key vocabulary as re_analysis_steps above). Public —
# consumed by both scheduler.py (per-analysis-id scheduled dispatch) and
# web/routes/projects.py's per-card "Run just this one analysis" endpoint;
# moved here (rather than staying scheduler-private) once it got a second
# real consumer, so there's one source of truth for the mapping.
#
# "language_file_classification" is the one genuinely ambiguous entry — its
# catalog description ("file types, languages, and project structure") and
# annotation_types span what three separate sub-surveyors emit, so all three
# are bundled here rather than guessing at just one. repo_file_size has no
# catalog entry at all (never independently schedulable/runnable today) so
# it isn't listed — it stays bundled only in a full, steps=None survey.
# egeria_publish is intentionally absent — it's an explicit write action,
# not a survey step; both scheduler.py and the analysis-run route special-
# case entries with action=="publish" before ever consulting this map.
REPO_ANALYSIS_STEP_MAP: dict[str, list[str]] = {
    "language_file_classification": ["repo_language", "repo_file_classification", "repo_file_structure"],
    "repository_health": ["repo_health"],
    "dependency_analysis": ["repo_dependency"],
    "security_scan": ["repo_security"],
    "documentation_coverage": ["repo_documentation"],
    "data_file_profiling": ["repo_data_profiling"],
    "api_structure": ["repo_api_structure"],
}


# analysis_id -> (results_reader, trend_reader) — Phase B. Only the 5
# analysis-catalog entries actually shown under Analysis/Assessment (per
# their intent tags — language_file_classification/repository_health are
# scouting-tagged, no results view). Each results_reader(registry, slug) ->
# dict of latest structured results; each trend_reader(registry, slug) ->
# list[{"surveyed_at": str, "value": number, ...}] for the trend chart.
def _dependency_results(registry, slug: str) -> dict:
    deps = registry.query_dependencies(slug)
    by_ecosystem: dict[str, list] = {}
    for d in deps:
        by_ecosystem.setdefault(d["ecosystem"] or "other", []).append(d)
    return {"by_ecosystem": by_ecosystem, "total": len(deps)}


def _dependency_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_dependencies"]}
        for r in registry.query_dependencies_history(slug)
    ]


def _data_profile_results(registry, slug: str) -> dict:
    profiles = registry.get_data_profiles(slug)
    return {"profiles": profiles, "total": len(profiles)}


def _data_profile_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["total_files"]}
        for r in registry.query_data_profile_history(slug)
    ]


def _security_results(registry, slug: str) -> dict:
    findings = registry.query_security_findings(slug)
    return {"findings": findings, "gap_count": sum(1 for f in findings if f["status"] == "gap")}


def _security_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["gap_count"], "total_checks": r["total_checks"]}
        for r in registry.query_security_findings_history(slug)
    ]


def _documentation_results(registry, slug: str) -> dict:
    return {"findings": registry.query_documentation_findings(slug)}


def _documentation_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["quality_rank"], "label": r["quality"]}
        for r in registry.query_documentation_findings_history(slug)
    ]


def _api_structure_results(registry, slug: str) -> dict:
    # Always-current live read (project_code_symbols/project_code_relationships
    # are repopulated at ingestion, not survey time) — no "latest results"
    # snapshot table needed, see D5.
    with registry._conn() as conn:
        rows = conn.execute(
            "SELECT language, kind, COUNT(*) as c FROM project_code_symbols "
            "WHERE project_slug = ? GROUP BY language, kind",
            (slug,),
        ).fetchall()
    by_language: dict[str, dict[str, int]] = {}
    for r in rows:
        by_language.setdefault(r["language"], {})[r["kind"]] = r["c"]
    relationships = registry.get_code_relationships(slug)
    return {"by_language": by_language, "relationship_count": len(relationships)}


def _api_structure_trend(registry, slug: str) -> list[dict]:
    return [
        {"surveyed_at": r["surveyed_at"], "value": r["symbol_count"]}
        for r in registry.query_api_structure_history(slug)
    ]


REPO_ANALYSIS_RESULTS_MAP: dict[str, tuple] = {
    "dependency_analysis": (_dependency_results, _dependency_trend),
    "data_file_profiling": (_data_profile_results, _data_profile_trend),
    "security_scan": (_security_results, _security_trend),
    "documentation_coverage": (_documentation_results, _documentation_trend),
    "api_structure": (_api_structure_results, _api_structure_trend),
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
