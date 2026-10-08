"""Egeria-native surveys: list, run, read back.

`BRIEF-NATIVE-EGERIA-SURVEY-LAUNCH.md` is the brief and the
gate. Prefect is not in this path: a run here is a direct pyegeria submission
whose proof lives on `step_runs` (see `native_survey_run.py`).

Every Egeria call happens off the event loop via `asyncio.to_thread`, which
COPIES the request's context (a bare `threading.Thread` would not -- reference:
ContextVar identity in threads). Even so, the caller is read here, once, in the
request, and passed down explicitly: nothing below this file reads a ContextVar.
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from resource_explorer import native_survey_run as nsr
from resource_explorer.registry import ProjectRegistry

log = logging.getLogger(__name__)
router = APIRouter()

_ENTITY_TYPES = ("database", "filesystem")


class RunRequest(BaseModel):
    process_qualified_name: str


def _port() -> nsr.EgeriaSurveyPort:
    """Indirection so tests can substitute a fake Egeria."""
    from resource_explorer import catalog_and_survey as cas

    return cas.PyegeriaRegistrationPort()


def _technology_type(entity_type: str) -> str:
    from resource_explorer.surveyors.survey_definition_executor import get_adapter

    return get_adapter(entity_type).egeria_technology_type_name


def _check(entity_type: str, slug: str, registry: ProjectRegistry) -> str:
    if entity_type not in _ENTITY_TYPES:
        raise HTTPException(status_code=404,
                            detail=f"No native Egeria surveys for entity type {entity_type!r}")
    if nsr._resource_entity(registry, entity_type, slug) is None:
        raise HTTPException(status_code=404, detail=f"{entity_type} {slug!r} not found")
    return _technology_type(entity_type)


@router.get("/{entity_type}/{slug}")
async def list_native_surveys(entity_type: str, slug: str) -> dict:
    """The native surveys for this resource, each with what RE can do about it
    and its derived state. Registry-only: no Egeria call."""
    registry = ProjectRegistry()
    tech = _check(entity_type, slug, registry)
    rows = await asyncio.to_thread(nsr.native_survey_rows, registry, entity_type, slug, tech)
    return {"technology_type": tech, "surveys": rows}


@router.post("/{entity_type}/{slug}/run")
async def run_native_survey(entity_type: str, slug: str, body: RunRequest) -> dict:
    """Submit one native survey to Egeria and prove the dispatch by reading the
    engine action back. Returns as soon as Egeria has accepted it -- a native
    survey can take many minutes, so completion is `refresh`'s job."""
    from resource_explorer.run_queue import requested_by

    registry = ProjectRegistry()
    tech = _check(entity_type, slug, registry)
    submitted_by = requested_by()      # read HERE, in the request, then passed down

    def _do() -> dict:
        with nsr.port_session(_port()) as port:
            return nsr.submit_native_survey(
                registry, port, entity_type, slug, body.process_qualified_name,
                technology_type=tech, submitted_by=submitted_by)

    try:
        state = await asyncio.to_thread(_do)
    except nsr.NativeSurveyBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except nsr.NativeSurveyCannotRun as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except nsr.NativeSurveyError as exc:
        _log_activity(registry, entity_type, slug, body.process_qualified_name,
                      status="error", summary=f"Egeria did not accept the survey: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))

    _log_activity(
        registry, entity_type, slug, body.process_qualified_name, status="triggered",
        summary=(f"Submitted Egeria survey {body.process_qualified_name} on {slug}: "
                 f"engine action {state['engine_action_guid']}"),
        detail={"engine_action_guid": state["engine_action_guid"],
                "submitted_by": submitted_by})
    return {"run": state, "surveys": await asyncio.to_thread(
        nsr.native_survey_rows, registry, entity_type, slug, tech)}


@router.post("/{entity_type}/{slug}/check")
async def check_native_survey_pointers(entity_type: str, slug: str) -> dict:
    """Read the stored Egeria pointers (the database asset, the server) back from Egeria and return the
    rows with what that read established. One read per stored pointer; nothing is written. A pointer is
    reported gone only when Egeria answered that no such element exists -- a failed read is 'unreadable'."""
    from resource_explorer import catalog_and_survey as cas

    registry = ProjectRegistry()
    tech = _check(entity_type, slug, registry)

    def _do() -> dict:
        entity = nsr._resource_entity(registry, entity_type, slug)
        stored = bool((getattr(entity, "egeria_asset_guid", "") or "").strip()) or bool(
            entity is not None and hasattr(entity, "db_type") and cas.server_pointer(registry, entity))
        if not stored:
            pointers = {"database": "none", "server": "none", "error": ""}
        else:
            with nsr.port_session(_port()) as port:
                pointers = cas.check_pointers(registry, port, entity_type, slug)
        return {"technology_type": tech, "pointers": pointers,
                "surveys": nsr.native_survey_rows(registry, entity_type, slug, tech, pointers=pointers)}

    return await asyncio.to_thread(_do)


class RegisterRequest(BaseModel):
    #: The person's explicit "start again": submit a second database process even though an earlier one
    #: has not resolved. Never implied.
    start_again: bool = False


@router.post("/{entity_type}/{slug}/register")
async def register_with_egeria(entity_type: str, slug: str, body: RegisterRequest = RegisterRequest()) -> dict:
    """The one press that WRITES to Egeria here: register this database's SERVER (adopting it if it is
    already there), submit Egeria's server survey, and have Egeria's own process create the database.
    Optional -- nothing else in RE needs it. See `catalog_and_survey.py` for each write and read-back."""
    from resource_explorer import catalog_and_survey as cas
    from resource_explorer.run_queue import requested_by

    registry = ProjectRegistry()
    tech = _check(entity_type, slug, registry)
    submitted_by = requested_by()       # read HERE, in the request, then passed down
    proc = cas._process_for(entity_type, tech, nsr.KIND_CATALOG_AND_SURVEY)
    process_qn = proc.qualified_name if proc else ""

    def _do() -> dict:
        with nsr.port_session(_port()) as port:
            return cas.register_with_egeria(registry, port, entity_type, slug,
                                            technology_type=tech, submitted_by=submitted_by,
                                            start_again=body.start_again)

    try:
        result = await asyncio.to_thread(_do)
    except nsr.NativeSurveyBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except nsr.NativeSurveyCannotRun as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except nsr.NativeSurveyError as exc:
        _log_activity(registry, entity_type, slug, process_qn, status="error",
                      summary=f"Egeria did not accept the registration: {exc}")
        raise HTTPException(status_code=502, detail=str(exc))

    _log_activity(
        registry, entity_type, slug, process_qn, status="triggered",
        summary=(f"Registered {slug}'s server with Egeria ({result['server'].get('how')}, "
                 f"server {result['server'].get('guid')}); database: {result['database'].get('how')}"),
        detail={"server": result["server"], "database": result["database"],
                "secrets_file_reprojected": bool(result["projected"]["written"]),
                "start_again": body.start_again, "submitted_by": submitted_by})
    return {"registered": result, "surveys": await asyncio.to_thread(
        nsr.native_survey_rows, registry, entity_type, slug, tech)}


@router.post("/{entity_type}/{slug}/refresh")
async def refresh_native_surveys(entity_type: str, slug: str) -> dict:
    """Read back every in-flight native survey on this resource, read-only,
    and return the rows as they now stand. The UI polls this while anything is
    in flight; with nothing in flight it is a registry read and no Egeria call."""
    registry = ProjectRegistry()
    tech = _check(entity_type, slug, registry)

    def _do() -> list[dict]:
        # Nothing in flight -> no port is even built (no Egeria client, no
        # event loop): the poll target must be free when there is nothing to poll.
        if any(r["in_flight"] for r in nsr.native_survey_rows(registry, entity_type, slug, tech)):
            with nsr.port_session(_port()) as port:
                nsr.refresh_resource(registry, port, entity_type, slug)
        return nsr.native_survey_rows(registry, entity_type, slug, tech)

    return {"technology_type": tech, "surveys": await asyncio.to_thread(_do)}


@router.get("/{entity_type}/{slug}/reports/{report_guid}")
async def native_survey_report(entity_type: str, slug: str, report_guid: str) -> dict:
    """The annotations RE read from one survey report, with the report's time.
    Served from RE's own store (no Egeria call), and only for a report that one
    of this resource's runs actually read in."""
    registry = ProjectRegistry()
    _check(entity_type, slug, registry)

    def _do() -> dict:
        runs = [r for r in registry.list_native_survey_runs(entity_type, slug)
                if r.get("survey_report_guid") == report_guid]
        if not runs:
            return {}
        run = runs[0]
        annotations = registry.query_native_survey_annotations(report_guid)
        # This is RE's own stored copy, read from Egeria at some time. The read time is the stored
        # annotations' own `read_at` (the run's report read time when they carry none). If the
        # `egeria_reset` marker is LATER than that read, Egeria has been reset since: the screen says so,
        # once. Nothing is asked of Egeria, and the annotations and their order are exactly what was stored.
        from resource_explorer.catalogue_commit import _ts, egeria_reset_at, reset_since_read
        copy_read_at = max((a.get("read_at") or "" for a in annotations), key=_ts, default="") \
            or (run.get("report_read_at") or "")
        reset_at = egeria_reset_at(registry, slug)
        return {
            "report_guid": report_guid,
            "report_at": run.get("survey_report_at") or "",
            "read_at": run.get("report_read_at") or "",
            "stored_copy_read_at": copy_read_at,
            "egeria_reset_at": reset_at,
            "reset_since": reset_since_read(copy_read_at, reset_at),
            "engine_action_guid": run.get("engine_action_guid") or "",
            "annotations": annotations,
        }

    report = await asyncio.to_thread(_do)
    if not report:
        raise HTTPException(status_code=404,
                            detail="No such report has been read into RE for this resource")
    return report


def _log_activity(registry, entity_type, slug, process_qn, *, status, summary, detail=None) -> None:
    """CLAUDE.md rule 16: every operation writes an activity entry. Best-effort:
    a failure to log must not turn an accepted submission into an error."""
    try:
        from resource_explorer.activity_logger import log_survey

        log_survey(registry, entity_type=entity_type, entity_slug=slug, entity_name=slug,
                   entity_location="", intent="discovery", status=status, summary=summary,
                   detail=json.dumps(detail or {"process": process_qn}))
    except Exception as exc:  # noqa: BLE001
        log.warning("could not write the activity entry for native survey %s: %s", process_qn, exc)
