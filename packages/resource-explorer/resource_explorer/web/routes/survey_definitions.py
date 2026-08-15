"""Survey Definition endpoints — list candidate Survey Definitions for a resource's
Technology Type (with full step/scope detail), and run one.

Thin web wrapper around resource_explorer.surveyors.survey_definition_reader /
survey_definition_executor — those modules already do all the real work (Egeria
reads, local execution, publishing); this file only adapts them to HTTP.
"""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

log = logging.getLogger(__name__)
router = APIRouter()

# D3 (docs/survey-question-context-plan.md): module-level singleton, not
# constructed fresh per request — EgeriaTechTypeCatalog's own docstring
# already says "callers should share one instance rather than refetch per
# request" (workspace-wide catalog metadata, doesn't change often); the
# route just wasn't following that until now, so its internal cache never
# actually persisted across requests.
_tech_type_catalog = None


def _get_tech_type_catalog():
    global _tech_type_catalog
    if _tech_type_catalog is None:
        from resource_explorer.surveyors.egeria_tech_type_catalog import EgeriaTechTypeCatalog

        _tech_type_catalog = EgeriaTechTypeCatalog()
    return _tech_type_catalog


class SurveyDefinitionRunRequest(BaseModel):
    """Request body for running a specific Survey Definition against a resource."""
    survey_definition_ref: str  # a candidate's qualified_name, from the candidates list
    refresh_definition: bool = False
    db_user: str = ""
    db_pwd: str = ""
    egeria_url: str = ""
    egeria_server: str = ""


def _map_reader_executor_errors(exc: Exception) -> HTTPException:
    from resource_explorer.surveyors.survey_definition_executor import SurveyDefinitionExecutorError
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    if isinstance(exc, (SurveyDefinitionExecutorError, SurveyDefinitionReaderError)):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@router.get("/{entity_type}/{slug}/candidates")
async def list_candidates(
    entity_type: str, slug: str,
    survey_kind: str | None = Query(
        None,
        description="Filter to Survey Definitions tagged with this survey_kind "
                    "(e.g. 'discovery') — omit to see every Survey Definition for "
                    "the resource's Technology Type regardless of kind, matching "
                    "the pre-survey_kind behavior.",
    ),
    phase: str | None = Query(
        None,
        description="D2 (docs/survey-question-context-plan.md) + D7 "
                    "(docs/unified-survey-execution-model-plan.md): scope the "
                    "candidate lookup to Questions tagged with this funnel-stage "
                    "(the CSV's single 'Funnel Stage' field, collapsed from the "
                    "earlier separate Asked At/Answered At columns 2026-08-14). "
                    "Per D7, each intent's own UI should pass its own stage here "
                    "as the primary filter — omitting it falls back to using every "
                    "cataloged repo Question regardless of stage, still scoped "
                    "over the full scan otherwise.",
    ),
    perspectives: list[str] | None = Query(
        None, description="Further narrow the Question set by perspective, same OR semantics as elsewhere.",
    ),
) -> dict:
    """List Survey Definitions Egeria has for this resource's Technology Type,
    each with full step detail (not just a name) so a human can judge scope
    before running one."""

    def _do() -> dict:
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        from resource_explorer.surveyors.survey_definition_executor import get_adapter
        from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReader

        adapter = get_adapter(entity_type)
        reader = SurveyDefinitionReader()

        # D2: try the scoped ScopedBy lookup by default — phase/perspectives
        # only narrow which cataloged Questions get considered, they aren't
        # required to attempt scoping at all (fixed live, see the phase=
        # param docstring above for the incident this closes).
        questions = [
            q["question"] for q in get_questions(resource_type=entity_type, phase=phase, perspectives=perspectives)
        ]
        thin_candidates: list = []
        if questions:
            thin_candidates = reader.find_candidate_process_guids_by_questions(
                questions, adapter.technology_type, survey_kind=survey_kind,
            )
        if not thin_candidates:
            # No cataloged Questions for this resource type, none resolved to
            # a real Egeria GUID yet, or none are scoped to any matching
            # Survey Definition — fall back to the full scan rather than
            # silently show an empty list (D2's own decision: the full-scan
            # path stays an explicit fallback, not removed).
            thin_candidates = reader.find_candidate_process_guids(adapter.technology_type, survey_kind=survey_kind)

        # Real Egeria-documented "what does a native step actually produce" info,
        # keyed by Egeria's own Technology Type name (deliberately not the same
        # string as adapter.technology_type — see ResourceTypeAdapter docstring).
        # Best-effort: if Egeria is unreachable or the tech type isn't found, this
        # is just an empty list and non-RE steps fall back to the static text.
        produced_annotation_types: list[dict] = []
        if adapter.egeria_technology_type_name:
            try:
                produced_annotation_types = _get_tech_type_catalog().get_produced_annotation_types(
                    adapter.egeria_technology_type_name
                )
            except Exception as exc:
                log.debug("get_produced_annotation_types(%r) failed: %s", adapter.egeria_technology_type_name, exc)

        detailed = []
        for c in thin_candidates:
            try:
                survey_def = reader.fetch(c["guid"])
            except Exception as exc:
                # Don't let one malformed/unsupported (e.g. branching) Survey
                # Definition hide the rest of the list — surface it as an
                # errored candidate instead.
                detailed.append({**c, "description": "", "error": str(exc), "steps": []})
                continue

            steps = []
            for s in survey_def.steps:
                step_info: dict = {
                    "qualified_name": s.qualified_name,
                    "display_name": s.display_name,
                    "description": s.description,
                    "executes_at": s.executes_at,
                    "re_analysis_step": s.re_analysis_step,
                }
                if s.executes_at == "resource-explorer":
                    info = adapter.re_analysis_step_info.get(s.re_analysis_step, {})
                    step_info["annotation_types"] = info.get("annotation_types", [])
                    if not step_info["description"] and info.get("description"):
                        step_info["description"] = info["description"]
                elif produced_annotation_types:
                    # Technology-Type-level info, not verified to be scoped to this
                    # exact step — Egeria's catalog doesn't link a specific
                    # GovernanceActionProcessStep to a specific producedAnnotationType
                    # entry, so this shows everything the native engine for this
                    # Technology Type is documented to produce.
                    step_info["egeria_produced_annotation_types"] = produced_annotation_types
                steps.append(step_info)

            detailed.append({
                **c, "description": survey_def.description, "error": None, "steps": steps,
                "survey_kind": survey_def.survey_kind,
            })

        # Native Egeria processes for this Technology Type (config/technology_
        # type_processes.yaml), shown as informational only — NOT merged into
        # `detailed`/candidates, since only "survey_existing" processes are
        # currently safe/wired to run from RE (via other_engine_handlers);
        # "catalog_and_survey" needs template placeholder params RE doesn't
        # collect yet, and "delete" processes must never be offered as
        # runnable at all. See technology_type_processes.py's KIND_* constants.
        native_processes: list[dict] = []
        if adapter.egeria_technology_type_name:
            from resource_explorer.surveyors.technology_type_processes import (
                KIND_DELETE,
                get_native_processes,
            )
            native_processes = [
                {
                    "qualified_name": p.qualified_name,
                    "display_name": p.display_name,
                    "kind": p.kind,
                    "description": p.description,
                }
                for p in get_native_processes(entity_type, adapter.egeria_technology_type_name)
                if p.kind != KIND_DELETE
            ]

        return {
            "technology_type": adapter.technology_type,
            "candidates": detailed,
            "egeria_native_processes": native_processes,
        }

    try:
        return await asyncio.to_thread(_do)
    except Exception as exc:
        raise _map_reader_executor_errors(exc)


@router.post("/{entity_type}/{slug}/run")
async def run_survey_definition_route(entity_type: str, slug: str, body: SurveyDefinitionRunRequest) -> dict:
    """Execute a Survey Definition against a registered resource."""

    def _do() -> dict:
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.surveyors.survey_definition_executor import run_survey_definition

        registry = ProjectRegistry()
        return run_survey_definition(
            entity_type,
            slug,
            registry=registry,
            survey_definition_ref=body.survey_definition_ref,
            refresh_definition=body.refresh_definition,
            db_user=body.db_user,
            db_pwd=body.db_pwd,
        )

    try:
        result = await asyncio.to_thread(_do)
    except Exception as exc:
        raise _map_reader_executor_errors(exc)

    report_guid = result.get("egeria_report_guid", "")
    if report_guid:
        from resource_explorer.config import get_config
        portal_url = get_config().egeria.portal_url.rstrip("/")
        result["egeria_portal_report_url"] = f"{portal_url}/tech-catalog?guid={report_guid}"

    try:
        from resource_explorer.activity_logger import log_survey
        from resource_explorer.registry import ProjectRegistry

        registry = ProjectRegistry()
        errors = result.get("errors", [])
        report_guid = result.get("egeria_report_guid", "")
        steps_summary = "; ".join(f"{s['step']}: {s['status']}" for s in result.get("steps", []))

        items = []
        if report_guid:
            items.append({
                "kind": "SurveyReport",
                "display_name": f"Survey Definition run ({result.get('process_qualified_name', '')})",
                "qualified_name": "",
                "guid": report_guid,
                "location": "",
            })

        log_survey(
            registry,
            entity_type=entity_type,
            entity_slug=slug,
            entity_name=slug,
            entity_location="",
            intent="assessment",
            status="error" if errors else "ok",
            summary=f"Survey Definition run ({result.get('process_qualified_name', '')})",
            detail="\n".join(filter(None, [steps_summary, "; ".join(errors)])),
            items=items,
        )
    except Exception:
        pass

    return result
