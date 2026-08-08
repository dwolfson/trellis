"""
Generic dispatch loop for executing a Survey Definition's RE-side steps.

Fetches a Survey Definition from Egeria (via SurveyDefinitionReader), walks its
ordered steps, and for each step tagged executes_at="resource-explorer" dispatches
to the matching local surveyor via a per-resource-type ResourceTypeAdapter. Steps
tagged for another engine (e.g. "egeria", "airflow") are skipped — that's someone
else's responsibility to run.

This module has no resource-type-specific logic itself; each resource type
(database, repo, filesystem) registers its own small adapter — see
resource_explorer/surveyors/database/survey_definition_adapter.py,
resource_explorer/surveyors/repo_survey_definition_adapter.py, and
resource_explorer/surveyors/filesystem/survey_definition_adapter.py.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

log = logging.getLogger(__name__)


class SurveyDefinitionExecutorError(RuntimeError):
    """Raised for executor-level errors (unknown entity type, ambiguous/missing
    Survey Definition, technology-type mismatch) — distinct from per-step failures,
    which are accumulated in the result's "errors" list instead of raised."""


@dataclass
class ResourceTypeAdapter:
    entity_type: str
    technology_type: str
    re_analysis_steps: dict  # re_analysis_step -> Callable(entity, registry, **kwargs) -> dict
    get_entity: Callable  # (registry, slug) -> entity | None
    publish: Callable  # (entity, step_outputs: list[dict], surveyed_at: str, registry) -> str (report_guid)
    # re_analysis_step -> {"description": str, "annotation_types": list[str]} — lets
    # UI/API callers explain what a step actually does/produces before running it,
    # without needing a live Egeria round-trip (RE already knows this about its own
    # steps). Optional: steps that exist in re_analysis_steps but have no entry
    # here just won't get a description/annotation-type hint shown.
    re_analysis_step_info: dict = field(default_factory=dict)
    # executes_at value (e.g. "egeria") -> Callable(entity, registry, step, **kwargs)
    # -> dict. For steps NOT tagged "resource-explorer" that this resource type can
    # still actively do something about — e.g. triggering Egeria's own native
    # survey engine for an "egeria"-tagged step, rather than only ever skipping it.
    # Optional: engines with no handler here are still just skipped/logged, same
    # as before this existed.
    other_engine_handlers: dict = field(default_factory=dict)
    # Egeria's own real Technology Type display name (e.g. "PostgreSQL Relational
    # Database") — deliberately separate from `technology_type` above, which is
    # only the free-text string RE's own authored Survey Definitions happen to be
    # tagged with via additionalProperties.supported_technology_type. The two are
    # NOT guaranteed to match (confirmed live 2026-07-08: our own authored
    # "SimplePostgresSurvey" uses "PostgreSQL Database", which isn't a real
    # registered Technology Type at all). This field is used to query Egeria's
    # real Technology Type catalog (EgeriaTechTypeCatalog) for what a native
    # survey step actually produces. Optional: leave blank if unknown.
    egeria_technology_type_name: str = ""


_ADAPTERS: dict = {}


def register_adapter(adapter: ResourceTypeAdapter) -> None:
    """Register a ResourceTypeAdapter for its entity_type. Called once at import
    time by each resource type's survey_definition_adapter module."""
    _ADAPTERS[adapter.entity_type] = adapter


def get_adapter(entity_type: str) -> ResourceTypeAdapter:
    # Import adapters lazily so this module doesn't force-import every resource
    # type's Egeria-coupled surveyor code just to construct an executor.
    if entity_type not in _ADAPTERS:
        if entity_type == "database":
            import resource_explorer.surveyors.database.survey_definition_adapter  # noqa: F401
        elif entity_type == "repo":
            import resource_explorer.surveyors.repo_survey_definition_adapter  # noqa: F401
        elif entity_type == "filesystem":
            import resource_explorer.surveyors.filesystem.survey_definition_adapter  # noqa: F401
    adapter = _ADAPTERS.get(entity_type)
    if adapter is None:
        raise SurveyDefinitionExecutorError(
            f"No Survey Definition adapter registered for entity_type={entity_type!r}. "
            f"Known types: {sorted(_ADAPTERS)}"
        )
    return adapter


class SurveyDefinitionExecutor:
    def __init__(self, registry, reader: SurveyDefinitionReader | None = None) -> None:
        self.registry = registry
        self.reader = reader or SurveyDefinitionReader()

    def run(
        self,
        entity_type: str,
        slug: str,
        technology_type: str | None = None,
        survey_definition_ref: str | None = None,
        refresh_definition: bool = False,
        **runner_kwargs: Any,
    ) -> dict:
        surveyed_at = datetime.utcnow().isoformat()
        adapter = get_adapter(entity_type)
        tech_type = technology_type or adapter.technology_type

        entity = adapter.get_entity(self.registry, slug)
        if entity is None:
            raise SurveyDefinitionExecutorError(
                f"{entity_type} '{slug}' not found in registry"
            )

        process_guid, process_qn = self._resolve_process_guid(
            entity_type, slug, tech_type, survey_definition_ref, refresh_definition
        )

        survey_def = self.reader.fetch(process_guid)
        if (
            survey_def.supported_technology_type
            and survey_def.supported_technology_type != tech_type
        ):
            raise SurveyDefinitionExecutorError(
                f"Survey Definition '{survey_def.qualified_name}' declares "
                f"supported_technology_type={survey_def.supported_technology_type!r}, "
                f"which does not match the requested {tech_type!r}"
            )

        if not survey_def.steps:
            raise SurveyDefinitionExecutorError(
                f"Survey Definition '{survey_def.qualified_name}' (guid={process_guid}) "
                "was fetched successfully but resolved to zero steps. Either it genuinely "
                "has no steps linked via Link First/Next Process Step, or the graph's "
                "first-step relationship wasn't recognized by SurveyDefinitionReader — "
                "this is the one part of the reader not yet validated against a live "
                "server (see docs/survey-definitions.md, Current Limitations)."
            )

        steps_report: list = []
        step_outputs: list = []
        errors: list = []

        for step in survey_def.steps:
            from resource_explorer.config import get_config
            from resource_explorer.surveyors.prefect_adapter import run_prefect_step

            use_prefect = False
            if step.executes_at == "prefect" or step.re_analysis_step in ("soda_data_quality", "great_expectations_validation"):
                use_prefect = True
            elif step.executes_at == "resource-explorer":
                try:
                    config = get_config()
                    if config.prefect.enabled:
                        use_prefect = True
                except Exception:
                    pass

            if use_prefect:
                try:
                    output = run_prefect_step(entity_type, entity.slug, step.re_analysis_step, runner_kwargs)
                    step_outputs.append(output)
                    steps_report.append({"step": step.qualified_name, "status": "ok", "engine": "prefect"})
                except Exception as exc:
                    msg = f"Prefect step '{step.re_analysis_step}' failed: {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error", "engine": "prefect"})
            elif step.executes_at == "resource-explorer":
                runner = adapter.re_analysis_steps.get(step.re_analysis_step)
                if runner is None:
                    msg = (
                        f"Unknown re_analysis_step '{step.re_analysis_step}' in step "
                        f"{step.qualified_name} — {entity_type} adapter only knows: "
                        f"{sorted(adapter.re_analysis_steps)}"
                    )
                    log.error(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "unknown_step"})
                    continue
                try:
                    output = runner(entity, self.registry, **runner_kwargs)
                    step_outputs.append(output)
                    steps_report.append({"step": step.qualified_name, "status": "ok"})
                except Exception as exc:
                    msg = f"RE step '{step.re_analysis_step}' failed: {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error"})
            elif step.executes_at in adapter.other_engine_handlers:
                handler = adapter.other_engine_handlers[step.executes_at]
                try:
                    outcome = handler(entity, self.registry, step, **runner_kwargs)
                    steps_report.append({
                        "step": step.qualified_name,
                        "status": "triggered",
                        **({"detail": outcome} if isinstance(outcome, dict) else {}),
                    })
                except Exception as exc:
                    msg = f"Failed to trigger {step.executes_at} for step '{step.qualified_name}': {exc}"
                    log.exception(msg)
                    errors.append(msg)
                    steps_report.append({"step": step.qualified_name, "status": "error"})
            elif step.executes_at == "egeria":
                log.info(
                    "Skipping step %s: executes_at=egeria, no trigger handler registered "
                    "for this resource type (Egeria's own responsibility)",
                    step.qualified_name,
                )
                steps_report.append({"step": step.qualified_name, "status": "skipped_egeria"})
            else:
                msg = (
                    f"Skipping step {step.qualified_name}: unrecognized executes_at="
                    f"{step.executes_at!r} (only 'resource-explorer' and 'egeria' are "
                    "understood today)"
                )
                log.warning(msg)
                errors.append(msg)
                steps_report.append({"step": step.qualified_name, "status": "unrecognized_engine"})

        report_guid = ""
        if step_outputs:
            try:
                report_guid = adapter.publish(entity, step_outputs, surveyed_at, self.registry)
            except Exception as exc:
                msg = f"Failed to publish results to Egeria: {exc}"
                log.exception(msg)
                errors.append(msg)

        return {
            "source": "survey-definition",
            "entity_type": entity_type,
            "slug": slug,
            "process_guid": process_guid,
            "process_qualified_name": process_qn,
            "surveyed_at": surveyed_at,
            "steps": steps_report,
            "errors": errors,
            "egeria_report_guid": report_guid,
        }

    def _resolve_process_guid(
        self,
        entity_type: str,
        slug: str,
        technology_type: str,
        survey_definition_ref: str | None,
        refresh_definition: bool,
    ) -> tuple:
        if survey_definition_ref:
            guid = self.reader.find_process_guid_by_name(survey_definition_ref)
            if not guid:
                raise SurveyDefinitionExecutorError(
                    f"No Survey Definition found matching '{survey_definition_ref}'"
                )
            self.registry.set_survey_definition_guid(
                entity_type, slug, technology_type, guid, survey_definition_ref
            )
            return guid, survey_definition_ref

        if not refresh_definition:
            cached = self.registry.get_survey_definition_guid(entity_type, slug, technology_type)
            if cached:
                return cached["process_guid"], cached["process_qualified_name"]

        candidates = self.reader.find_candidate_process_guids(technology_type)
        if not candidates:
            raise SurveyDefinitionExecutorError(
                f"No Survey Definition found in Egeria for technology type "
                f"'{technology_type}'. Author one first (see "
                "docs/egeria-collaboration-and-survey-model.md section 6.3)."
            )
        if len(candidates) > 1:
            names = ", ".join(c["qualified_name"] for c in candidates)
            raise SurveyDefinitionExecutorError(
                f"Multiple Survey Definitions found for technology type "
                f"'{technology_type}': {names}. Disambiguate with --survey-definition."
            )

        chosen = candidates[0]
        self.registry.set_survey_definition_guid(
            entity_type, slug, technology_type, chosen["guid"], chosen["qualified_name"]
        )
        return chosen["guid"], chosen["qualified_name"]


def run_survey_definition(entity_type: str, slug: str, registry=None, **kwargs: Any) -> dict:
    """Convenience function mirroring run_hybrid_survey's shape."""
    if registry is None:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
    executor = SurveyDefinitionExecutor(registry)
    return executor.run(entity_type, slug, **kwargs)
