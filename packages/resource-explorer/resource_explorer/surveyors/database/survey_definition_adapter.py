"""
Survey Definition adapter for PostgreSQL databases.

Registers a ResourceTypeAdapter (entity_type="database") with
resource_explorer.surveyors.survey_definition_executor, wiring the
"postgres_schema_and_stats" re_analysis_step to the existing DatabaseSurveyor,
and publishing results via EgeriaDatabaseSurveyor.publish_step_annotations (the
narrow publish path — does not catalog or trigger a native Egeria survey).

A step tagged executes_at="egeria" is handled separately, via
other_engine_handlers: it actively triggers Egeria's own native PostgreSQL
survey (EgeriaDatabaseSurveyor.trigger_survey_by_guid), waits for it to reach
a terminal status, and reads back its real result — rather than being
silently skipped (unlike auto-cataloging, which publish_step_annotations
deliberately avoids). See egeria_async_survey_result.py for the poll/resolve/
convert machinery this shares with the filesystem adapter, and
docs/design-notes/EGERIA-ASYNC-RESULT-RETRIEVAL-IMPLEMENTED.md for the
report-attribution design.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from resource_explorer.surveyors.survey_definition_executor import (
    ResourceTypeAdapter,
    register_adapter,
)

log = logging.getLogger(__name__)


def _run_postgres_schema_and_stats(db_entity, registry, db_user: str = "", db_pwd: str = "", **_) -> dict:
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    surveyor = DatabaseSurveyor(db_entity, {"user": db_user, "password": db_pwd}, registry)
    result = surveyor.survey()
    return {
        "schema_info": result.get("schema_info", {}),
        "statistics": result.get("statistics", {}),
    }


def _run_postgres_sql_analysis(db_entity, registry, db_user: str = "", db_pwd: str = "", **_) -> dict:
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    surveyor = DatabaseSurveyor(db_entity, {"user": db_user, "password": db_pwd}, registry)
    result = surveyor.survey()
    return {
        "schema_info": result.get("schema_info", {}),
        "statistics": result.get("statistics", {}),
        "views": result.get("views", []),
    }


def _get_database_entity(registry, slug: str):
    return registry.get_database(slug)


def _trigger_egeria_native_survey(db_entity, registry, step, **_) -> dict:
    """Trigger Egeria's own native PostgreSQL database survey for a step tagged
    executes_at="egeria", then wait for it to reach a terminal status and read
    back its real result. Requires the database to already be cataloged in
    Egeria (has a stored asset guid) — this does not catalog it as a side
    effect.

    Synchronous by necessity: the caller (survey_definition_executor's
    other_engine_handlers dispatch) needs a real status/output to report, and
    there is no cheaper way to get one than to poll. See
    egeria_async_survey_result.poll_trigger_and_retrieve_annotations for the
    poll-then-resolve-then-convert logic, shared with the filesystem adapter's
    identical function below.

    Raises on timeout (EgeriaEngineActionTimeoutError) or on an unresolvable
    report attribution (SurveyReportAttributionError) — both propagate to the
    executor's own per-step except clause, which reports them as a specific
    error rather than a silent "triggered" success.
    """
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor
    from resource_explorer.surveyors.egeria_async_survey_result import (
        poll_trigger_and_retrieve_annotations,
    )

    db_guid = db_entity.egeria_asset_guid
    if not db_guid:
        raise RuntimeError(
            f"Database '{db_entity.slug}' has no stored Egeria asset guid — "
            "cannot trigger Egeria's native survey for an uncataloged database."
        )
    surveyor = EgeriaDatabaseSurveyor()
    triggered_at = datetime.now(timezone.utc)
    engine_action_guid = surveyor.trigger_survey_by_guid(db_guid)
    log.info(
        "Triggered Egeria native survey for database %r: engine_action_guid=%s",
        db_entity.slug, engine_action_guid,
    )
    result = poll_trigger_and_retrieve_annotations(
        surveyor=surveyor,
        engine_action_guid=engine_action_guid,
        resource_guid=db_guid,
        triggered_at=triggered_at,
        analysis_step=step.re_analysis_step,
    )
    return {"status": "ok", **result}


def _publish(entity, step_outputs: list, surveyed_at: str, registry) -> str:
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor

    schema_info: dict = {}
    statistics: dict = {}
    views: list = []
    for output in step_outputs:
        schema_info = output.get("schema_info") or schema_info
        statistics = output.get("statistics") or statistics
        views = output.get("views") or views

    surveyor = EgeriaDatabaseSurveyor()
    result = surveyor.publish_step_annotations(entity, schema_info, statistics, surveyed_at, registry, views=views)
    return result.get("report_guid", "")


_ADAPTER = ResourceTypeAdapter(
    entity_type="database",
    technology_type="PostgreSQL Database",
    re_analysis_steps={
        "postgres_schema_and_stats": _run_postgres_schema_and_stats,
        "sql_analysis": _run_postgres_sql_analysis,
    },
    get_entity=_get_database_entity,
    publish=_publish,
    re_analysis_step_info={
        "postgres_schema_and_stats": {
            "description": "Schema, table, and column inventory plus row-count/size statistics.",
            "annotation_types": ["SchemaAnalysisAnnotation", "ResourceMeasureAnnotation"],
        },
        "sql_analysis": {
            "description": "SQL views parsed dependencies, static column-level lineage and complexity scores.",
            "annotation_types": [
                "SchemaAnalysisAnnotation",
                "RelationshipAnnotation",
                "QualityScoreAnnotation",
                "RequestForAction",
                "DataClassAnnotation",
            ],
        },
    },
    other_engine_handlers={"egeria": _trigger_egeria_native_survey},
    egeria_technology_type_name="PostgreSQL Relational Database",
)

register_adapter(_ADAPTER)
