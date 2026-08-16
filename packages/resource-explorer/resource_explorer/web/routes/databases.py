"""Database management endpoints — list, get, register, survey, remove."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter()


class DatabaseSummary(BaseModel):
    """Summary information for a database entity."""
    slug: str
    display_name: str
    db_type: str
    host: str
    port: int
    database_name: str
    description: str
    status: str
    last_surveyed_at: str
    schema_count: int | None
    table_count: int | None
    column_count: int | None
    server_slug: str = ""       # FK to db_servers; empty for standalone databases
    egeria_asset_guid: str = "" # DB element GUID in Egeria; "" = not yet cataloged
    last_survey_source: str = ""# "local" | "egeria" | "egeria-published" from latest survey
    db_user: str = ""           # stored username (no password exposed)
    egeria_host: str = ""
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    group_slug: str = ""


class DatabaseRegistration(BaseModel):
    """Request body for registering a new database."""
    slug: str
    display_name: str
    db_type: str
    host: str
    port: int
    database_name: str
    connection_ref: str = ""
    description: str = ""
    # Optional stored credentials
    db_user: str = ""
    db_password: str = ""
    # Egeria-visible hostname for the DB (e.g. host.docker.internal when DB is in Docker)
    egeria_host: str = ""
    # Optional stored Egeria connection details
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    group_slug: str = ""


class SurveyRequest(BaseModel):
    """Request body for triggering a database survey."""
    username: str = ""  # DB username — falls back to stored db_user if blank
    password: str = ""  # DB password — falls back to stored db_password if blank
    use_egeria: bool = False
    force_custom: bool = False
    egeria_url: str | None = None
    egeria_server: str | None = None
    secrets_path: str | None = None
    refresh: bool = True


class SurveyResult(BaseModel):
    """Result of a database survey operation."""
    status: str  # "ok" | "error" | "pending"
    slug: str
    message: str = ""
    error: str | None = None
    source: str | None = None  # "egeria" | "custom"
    schema_count: int | None = None
    table_count: int | None = None
    column_count: int | None = None


class EgeriaSurveyReportRow(BaseModel):
    """A SurveyReport as it actually exists in Egeria right now (live read) —
    distinct from the locally-cached rows returned by /surveys, since a
    Survey Definition's "egeria" step triggers an async native survey whose
    report doesn't appear in the local registry at all."""
    guid: str
    qualified_name: str
    display_name: str
    surveyed_at: str
    annotation_count: int
    schema_count: int
    table_count: int
    column_count: int
    description: str


class EgeriaAnnotationItem(BaseModel):
    guid: str
    annotation_type: str
    summary: str
    confidence: int | None
    analysis_step: str
    explanation: str
    expression: str
    json_properties: dict


def _to_summary(db) -> DatabaseSummary:
    """Convert DatabaseEntity to DatabaseSummary."""
    # Get latest survey data if available
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    surveys = registry.get_database_surveys(db.slug)
    latest = surveys[0] if surveys else None
    
    return DatabaseSummary(
        slug=db.slug,
        display_name=db.display_name,
        db_type=db.db_type,
        host=db.host,
        port=db.port,
        database_name=db.database_name,
        description=db.description,
        status=db.status.value,
        last_surveyed_at=db.last_surveyed_at or "",
        schema_count=latest.get("schema_count") if latest else None,
        table_count=latest.get("table_count") if latest else None,
        column_count=latest.get("column_count") if latest else None,
        server_slug=getattr(db, "server_slug", "") or "",
        egeria_asset_guid=getattr(db, "egeria_asset_guid", "") or "",
        last_survey_source=latest.get("source", "") if latest else "",
        db_user=db.db_user or "",
        egeria_host=db.egeria_host or "",
        egeria_url=db.egeria_url or "",
        egeria_server=db.egeria_server or "",
        egeria_user=db.egeria_user or "",
        group_slug=getattr(db, "group_slug", "") or "",
    )


@router.get("/", response_model=list[DatabaseSummary])
async def list_databases(db_type: str | None = None) -> list[DatabaseSummary]:
    """List all registered databases, optionally filtered by type."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    databases = registry.list_databases(db_type=db_type)
    return [_to_summary(db) for db in databases]


@router.get("/{slug}", response_model=DatabaseSummary)
async def get_database(slug: str) -> DatabaseSummary:
    """Get details for a specific database."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
    return _to_summary(database)


@router.post("/register", response_model=DatabaseSummary)
async def register_database(req: DatabaseRegistration) -> DatabaseSummary:
    """Register a new database."""
    from resource_explorer.registry import DatabaseEntity, ProjectRegistry, ProjectStatus
    
    registry = ProjectRegistry()
    
    # Check if slug already exists
    existing = registry.get_database(req.slug)
    if existing:
        raise HTTPException(status_code=400, detail=f"Database '{req.slug}' already exists")
    
    # Create database entity
    database = DatabaseEntity(
        slug=req.slug,
        display_name=req.display_name,
        db_type=req.db_type,
        host=req.host,
        port=req.port,
        database_name=req.database_name,
        connection_ref=req.connection_ref,
        description=req.description,
        status=ProjectStatus.ACTIVE,
        last_surveyed_at="",
        db_user=req.db_user,
        db_password=req.db_password,
        egeria_host=req.egeria_host,
        egeria_url=req.egeria_url,
        egeria_server=req.egeria_server,
        egeria_user=req.egeria_user,
        egeria_password=req.egeria_password,
        group_slug=req.group_slug,
    )
    
    # Register in registry
    registry.register_database(database)
    
    return _to_summary(database)


@router.post("/{slug}/survey", response_model=SurveyResult)
async def survey_database(slug: str, req: SurveyRequest) -> SurveyResult:
    """Trigger a database survey (hybrid mode by default)."""
    from resource_explorer.registry import ProjectRegistry, ProjectStatus
    
    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
    
    # Update status to surveying
    registry.update_database_status(slug, ProjectStatus.INDEXING, "")
    
    # Resolve credentials — request overrides stored values
    resolved_user = req.username or database.db_user
    resolved_pwd  = req.password or database.db_password
    if not resolved_user or not resolved_pwd:
        raise HTTPException(
            status_code=400,
            detail="Database credentials are required. Either supply username/password in the request or store them at registration.",
        )
    credentials = {"user": resolved_user, "password": resolved_pwd}

    def _extract_counts(raw: dict) -> tuple[int | None, int | None, int | None]:
        """Pull schema/table/column counts from the surveyor result dict."""
        schema_info = raw.get("schema_info", {})
        sc = len(schema_info.get("schemas", [])) or raw.get("schema_count")
        tc = schema_info.get("total_tables") or raw.get("table_count")
        cc = schema_info.get("total_columns") or raw.get("column_count")
        return sc, tc, cc

    def _do_survey() -> dict[str, Any]:
        """Run survey in thread — raises on fatal connection errors."""
        if req.force_custom or not req.use_egeria:
            from resource_explorer.surveyors.database.database_surveyor import run_database_survey
            result = run_database_survey(
                db_slug=slug,
                credentials=credentials,
                registry=registry,
            )
            sc, tc, cc = _extract_counts(result)
            return {"source": "custom", "schema_count": sc, "table_count": tc, "column_count": cc,
                    "errors": result.get("errors", [])}
        else:
            from resource_explorer.surveyors.database.hybrid_database_surveyor import run_hybrid_survey
            result = run_hybrid_survey(
                db_slug=slug,
                credentials=credentials,
                registry=registry,
                force_custom=False,
                platform_url=req.egeria_url,
                view_server=req.egeria_server,
                secrets_path=req.secrets_path,
                refresh=req.refresh,
            )
            sc, tc, cc = _extract_counts(result)
            return {"source": result.get("source", "hybrid"),
                    "schema_count": sc, "table_count": tc, "column_count": cc,
                    "errors": result.get("errors", [])}

    try:
        result = await asyncio.to_thread(_do_survey)
        registry.update_database_status(slug, ProjectStatus.ACTIVE, "")

        sc, tc, cc = result.get("schema_count"), result.get("table_count"), result.get("column_count")
        src = result.get("source", "local")
        non_fatal_errors = result.get("errors", [])
        counts_str = ", ".join(filter(None, [
            f"{sc} schema(s)" if sc else "",
            f"{tc} table(s)" if tc else "",
            f"{cc} column(s)" if cc else "",
        ]))

        # Write activity log entry
        try:
            from resource_explorer.activity_logger import log_survey
            log_survey(
                registry,
                entity_type="database",
                entity_slug=slug,
                entity_name=database.display_name,
                entity_location=f"{database.host}:{database.port}/{database.database_name}",
                intent="assessment",
                status="ok",
                summary=f"Survey complete — {counts_str or 'done'} ({src})",
                detail="; ".join(non_fatal_errors) if non_fatal_errors else "",
                annotations=[{"analysis_name": "Schema Inventory", "annotation_type": "SchemaAnalysisAnnotation",
                               "count": tc or 0, "status": "local", "summary": counts_str}],
            )
        except Exception:
            pass

        return SurveyResult(
            status="ok",
            slug=slug,
            message=f"Survey completed using {src} surveyor" + (
                f" ({len(non_fatal_errors)} non-fatal error(s))" if non_fatal_errors else ""
            ),
            source=src,
            schema_count=sc,
            table_count=tc,
            column_count=cc,
        )
    except Exception as exc:
        err_str = str(exc)
        # Write error to activity log
        try:
            from resource_explorer.activity_logger import log_survey
            log_survey(
                registry,
                entity_type="database",
                entity_slug=slug,
                entity_name=database.display_name,
                entity_location=f"{database.host}:{database.port}/{database.database_name}",
                intent="assessment",
                status="error",
                summary=f"Survey failed: {err_str[:200]}",
                detail=err_str,
            )
        except Exception:
            pass
        return SurveyResult(status="error", slug=slug, error=err_str)


class AnalysisRunResult(BaseModel):
    status: str  # "ok" | "error"
    slug: str
    analysis_id: str
    message: str = ""
    error: str | None = None


@router.post("/{slug}/analyses/{analysis_id}/run", response_model=AnalysisRunResult)
async def run_single_database_analysis(slug: str, analysis_id: str) -> AnalysisRunResult:
    """Runs only the DatabaseSurveyor step(s) one named local database
    analysis needs, not the whole schema+statistics+views survey every
    time — the per-card "Run" action in Analysis/Assessment (database
    per-card dispatch fix, D6 prerequisite, repo-scope-narrowing-funnel
    plan). Egeria-native entries (egeria_db_survey) and Discovery Survey
    Definitions are not handled here — those already have their own
    dedicated dispatch paths (trigger_survey_by_guid / run_survey_definition
    via scheduler.py's _run_db_survey); this route is local-survey-only,
    mirroring scheduler.py's _run_local_db_survey."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.database.database_surveyor import (
        DATABASE_ANALYSIS_STEP_MAP,
        run_database_survey,
    )

    registry = ProjectRegistry()
    db = registry.get_database(slug)
    if not db:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")

    if analysis_id not in DATABASE_ANALYSIS_STEP_MAP:
        raise HTTPException(
            status_code=400,
            detail=f"Analysis '{analysis_id}' has no local survey step(s) mapped — "
                   "either it's Egeria-native/publish (use the appropriate dedicated "
                   "action instead) or an unknown id.",
        )

    if not db.db_user or not db.db_password:
        raise HTTPException(
            status_code=400,
            detail="No stored database credentials — register the database with "
                   "db_user/db_password, or run a full survey with credentials, first.",
        )

    steps = DATABASE_ANALYSIS_STEP_MAP[analysis_id]

    def _run():
        return run_database_survey(
            slug, credentials={"user": db.db_user, "password": db.db_password},
            registry=registry, steps=steps,
        )

    try:
        result = await asyncio.to_thread(_run)
    except Exception as exc:
        return AnalysisRunResult(status="error", slug=slug, analysis_id=analysis_id, error=str(exc))

    non_fatal = result.get("errors") or []
    return AnalysisRunResult(
        status="ok", slug=slug, analysis_id=analysis_id,
        message=f"{len(result.get('annotations', []))} annotation(s)." + (
            f" ({len(non_fatal)} non-fatal error(s))" if non_fatal else ""
        ),
    )


@router.delete("/{slug}")
async def remove_database(slug: str) -> dict:
    """Remove a database from the registry."""
    from resource_explorer.registry import ProjectRegistry
    
    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
    
    registry.remove_database(slug)
    return {"removed": slug}


@router.get("/{slug}/surveys")
async def get_database_surveys(slug: str) -> list[dict]:
    """Get survey history for a database."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")

    return registry.get_database_surveys(slug)


@router.get("/{slug}/egeria-surveys", response_model=list[EgeriaSurveyReportRow])
async def get_database_egeria_surveys(slug: str) -> list[EgeriaSurveyReportRow]:
    """List SurveyReports that actually exist in Egeria right now for this database
    (a live read, not the local registry cache) — includes reports produced by
    Egeria's own native async survey engine, which the local /surveys endpoint
    never sees."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.database.egeria_database_surveyor import (
        EgeriaDatabaseSurveyor,
        EgeriaDatabaseSurveyorError,
    )

    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")
    if not database.egeria_asset_guid:
        return []  # not yet cataloged in Egeria — nothing to walk from

    surveyor = EgeriaDatabaseSurveyor()
    try:
        reports = await asyncio.to_thread(surveyor.get_survey_reports_by_guid, database.egeria_asset_guid)
    except EgeriaDatabaseSurveyorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaSurveyReportRow(**r) for r in reports]


@router.get("/{slug}/egeria-surveys/{report_guid}/annotations", response_model=list[EgeriaAnnotationItem])
async def get_database_egeria_annotations(slug: str, report_guid: str) -> list[EgeriaAnnotationItem]:
    """Fetch all annotations for a specific live Egeria SurveyReport, by the
    report's own GUID — works regardless of which engine (RE or Egeria's native
    survey) produced the report, since it walks the real ReportedAnnotation
    relationship rather than guessing a naming convention."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.database.egeria_database_surveyor import (
        EgeriaDatabaseSurveyor,
        EgeriaDatabaseSurveyorError,
    )

    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")

    surveyor = EgeriaDatabaseSurveyor()
    try:
        annotations = await asyncio.to_thread(surveyor.get_annotations_by_report_guid, report_guid)
    except EgeriaDatabaseSurveyorError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return [EgeriaAnnotationItem(**a) for a in annotations]


class PublishRequest(BaseModel):
    """Request body for publishing a database survey to Egeria.

    All fields are optional — stored values on the DatabaseEntity are used as defaults.
    Pass fields only to override stored values for a single call.
    """
    egeria_url: str | None = None
    egeria_server: str | None = None
    egeria_user: str | None = None
    egeria_password: str | None = None
    db_user: str = ""
    db_pwd: str = ""


class PublishResult(BaseModel):
    """Result of publishing a database survey to Egeria."""
    status: str
    slug: str
    server_guid: str | None = None     # Egeria PostgreSQL server element GUID
    asset_guid: str | None = None      # Egeria database element GUID
    report_guid: str | None = None     # Egeria survey action GUID
    annotation_count: int | None = None
    server_display_name: str | None = None
    database_display_name: str | None = None
    error: str | None = None


@router.post("/{slug}/publish", response_model=PublishResult)
async def publish_database_survey(slug: str, req: PublishRequest = PublishRequest()) -> PublishResult:
    """Publish the latest local database survey to Egeria."""
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    database = registry.get_database(slug)
    if not database:
        raise HTTPException(status_code=404, detail=f"Database '{slug}' not found")

    surveys = registry.get_database_surveys(slug)
    if not surveys:
        raise HTTPException(status_code=404, detail=f"No survey data for '{slug}' — run a survey first")

    def _do_publish() -> dict[str, Any]:
        import asyncio as _aio
        import json as _json
        from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor
        # pyegeria sync wrappers call asyncio.get_event_loop() — set one for this thread
        loop = _aio.new_event_loop()
        _aio.set_event_loop(loop)

        # Resolve: request overrides > stored values > env vars (inside EgeriaDatabaseSurveyor)
        resolved_db_user = req.db_user or database.db_user
        resolved_db_pwd  = req.db_pwd  or database.db_password

        if not resolved_db_user or not resolved_db_pwd:
            raise ValueError(
                "Database credentials are required to catalog in Egeria. "
                "Store them at registration or supply db_user/db_pwd in the request."
            )

        surveyor = EgeriaDatabaseSurveyor(
            platform_url=req.egeria_url or database.egeria_url or None,
            view_server=req.egeria_server or database.egeria_server or None,
            user_id=req.egeria_user or database.egeria_user or None,
            user_password=req.egeria_password or database.egeria_password or None,
        )

        latest = surveys[0]
        survey_data = _json.loads(latest.get("survey_data", "{}"))
        schema_info = survey_data.get("schema_info", {})
        statistics  = survey_data.get("statistics", {})

        try:
            result = surveyor.publish_local_survey(
                db_entity=database,
                schema_info=schema_info,
                schema_count=latest.get("schema_count", 0),
                table_count=latest.get("table_count", 0),
                column_count=latest.get("column_count", 0),
                surveyed_at=latest.get("surveyed_at", ""),
                registry=registry,
                db_user=resolved_db_user,
                db_pwd=resolved_db_pwd,
                statistics=statistics,
            )
        finally:
            loop.close()
            _aio.set_event_loop(None)
        return result

    try:
        result = await asyncio.to_thread(_do_publish)
        egeria_host = database.egeria_host or database.host
        server_dn = f"{egeria_host}:{database.port}"
        try:
            from resource_explorer.activity_logger import log_catalog
            log_catalog(
                registry,
                entity_type="database",
                entity_slug=slug,
                entity_name=database.display_name,
                entity_location=f"{database.host}:{database.port}/{database.database_name}",
                status="ok",
                summary=f"Cataloged in Egeria: {database.database_name} on {server_dn}",
                items=[
                    {"kind": "PostgreSQLServer", "display_name": server_dn,
                     "qualified_name": f"PostgreSQLServer::{server_dn}",
                     "guid": result.get("server_guid", ""), "location": ""},
                    {"kind": "PostgreSQLDatabase", "display_name": database.database_name,
                     "qualified_name": f"PostgreSQLDatabase::{database.database_name}",
                     "guid": result.get("asset_guid", ""), "location": ""},
                ],
            )
        except Exception:
            pass
        return PublishResult(
            status="ok",
            slug=slug,
            server_guid=result.get("server_guid"),
            asset_guid=result.get("asset_guid"),
            report_guid=result.get("report_guid"),
            annotation_count=result.get("annotation_count"),
            server_display_name=server_dn,
            database_display_name=database.database_name,
        )
    except Exception as exc:
        err_str = str(exc)
        try:
            from resource_explorer.activity_logger import log_catalog
            log_catalog(
                registry,
                entity_type="database",
                entity_slug=slug,
                entity_name=database.display_name,
                entity_location=f"{database.host}:{database.port}/{database.database_name}",
                status="error",
                summary=f"Egeria catalog failed: {err_str[:200]}",
                detail=err_str,
            )
        except Exception:
            pass
        return PublishResult(status="error", slug=slug, error=err_str)


@router.get("/{slug}/diff")
async def get_database_diff(slug: str) -> dict:
    """Compare the two most recent database survey runs.

    Returns empty dict when fewer than two runs exist.
    """
    import json as _json
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    surveys = registry.get_database_surveys(slug)
    if len(surveys) < 2:
        return {}

    curr = surveys[0]
    prev = surveys[1]

    def _table_set(survey: dict) -> set[str]:
        try:
            data = _json.loads(survey.get("survey_data") or "{}")
            schemas = data.get("schema_info", data).get("schemas", [])
            return {f"{s['name']}.{t['name']}"
                    for s in schemas for t in s.get("tables", [])}
        except Exception:
            return set()

    curr_tables = _table_set(curr)
    prev_tables = _table_set(prev)

    return {
        "prev_date":       prev["surveyed_at"],
        "curr_date":       curr["surveyed_at"],
        "deltas": {
            "schemas": (curr.get("schema_count") or 0) - (prev.get("schema_count") or 0),
            "tables":  (curr.get("table_count")  or 0) - (prev.get("table_count")  or 0),
            "columns": (curr.get("column_count") or 0) - (prev.get("column_count") or 0),
        },
        "new_tables":     sorted(curr_tables - prev_tables),
        "removed_tables": sorted(prev_tables - curr_tables),
    }
