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

A step tagged executes_at="egeria-adaptive" is a third, separate
other_engine_handlers entry: the folded-in HybridDatabaseSurveyor strategy
selector (cache-or-run an existing Egeria survey, else local-scan-then-
publish, else trigger Egeria's native survey with catalog-on-demand, else
degrade to a local-only custom survey) — see `_run_egeria_adaptive` below and
docs/design-notes/EXECUTION-MODES-HYBRID-CLARIFICATION.md. Unlike the plain
"egeria" handler above, this one MAY catalog an uncataloged database.
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


def _run_egeria_adaptive(
    db_entity, registry, step,
    db_user: str = "", db_pwd: str = "", refresh: bool = False,
    platform_url: str | None = None, view_server: str | None = None,
    secrets_path: str | None = None, force_custom: bool = False,
    **_,
) -> dict:
    """Strategy selector for a step tagged executes_at="egeria-adaptive".

    Folds in the capabilities of `HybridDatabaseSurveyor`
    (surveyors/database/hybrid_database_surveyor.py) — the default web/CLI
    database-survey path before this build — as a legal `executes_at` value,
    per docs/design-notes/EXECUTION-MODES-HYBRID-CLARIFICATION.md (which
    renames the original plan's `egeria-hybrid` to `egeria-adaptive`, since
    "hybrid" already means something else in this codebase — a single Survey
    Definition whose steps run on a mix of engines).

    Unlike the plain executes_at="egeria" handler above
    (`_trigger_egeria_native_survey`), which deliberately refuses to run
    against an uncataloged database, this handler is allowed to catalog the
    asset on demand — that is one of the three capabilities being folded in,
    not a bug to fix. The other two: reusing an existing Egeria survey
    instead of re-running one (cache-or-run), and reporting which engine's
    numbers the result actually is (`source`: "egeria" / "egeria-custom" /
    "custom" / "error" — never a silent empty success).

    CLAUDE.md rule 15 (originally written against `HybridDatabaseSurveyor`,
    now against this handler): when Egeria's native survey is triggered, the
    local scan runs immediately afterward, because Egeria's native survey is
    async and returns no schema data right away — see
    `HybridDatabaseSurveyor._run_egeria_survey`, which this delegates to.

    Delegates to `HybridDatabaseSurveyor.survey()` rather than
    reimplementing its strategy logic here: `tests/
    test_execution_modes_path_c_hybrid.py` characterizes that class's
    behavior by mocking its own private instance attributes
    (`_check_egeria_available`, `_egeria_surveyor`) directly, so the actual
    decision logic has to keep living on that class for those tests to keep
    meaning anything — rewriting `HybridDatabaseSurveyor` itself into a shim
    that calls back into THIS handler would sever that mocking path and
    require rewriting the characterization tests it exists to protect. The
    web/CLI call sites move to executes_at="egeria-adaptive" (this handler);
    `HybridDatabaseSurveyor` itself is not deleted — see
    docs/Backlog.md for the fast-follow to properly retire it once nothing
    but this handler and its own tests reference it.
    """
    from resource_explorer.surveyors.database.hybrid_database_surveyor import (
        HybridDatabaseSurveyor,
    )

    credentials = {"user": db_user, "password": db_pwd} if (db_user or db_pwd) else None
    surveyor = HybridDatabaseSurveyor(
        registry=registry, platform_url=platform_url, view_server=view_server,
    )
    result = surveyor.survey(
        db_entity.slug, credentials=credentials, refresh=refresh,
        secrets_path=secrets_path, force_custom=force_custom,
    )
    result.setdefault("status", "error" if result.get("source") == "error" else "ok")

    # HybridDatabaseSurveyor.survey() already does its own Egeria write when
    # source == "egeria-custom" (publish_local_survey, called inside
    # _run_egeria_survey) — this handler must not cause a SECOND write. The
    # generic per-Survey-Definition publish step at the end of
    # SurveyDefinitionExecutor._execute() (adapter.publish(), gated on the
    # entity having an assigned Egeria project) looks for "schema_info" /
    # "statistics" keys on ANY step's output to decide what to publish — the
    # same keys HybridDatabaseSurveyor's result carries at the top level for
    # its historic web/CLI response shape. Left there, this handler's own
    # already-published result would be picked up and re-published via a
    # DIFFERENT method (publish_step_annotations) a second time. Relocated
    # under "result" instead: still present for a caller that wants the full
    # shape (e.g. a web route reconstructing its historic response body),
    # invisible to that generic key scan.
    schema_info = result.pop("schema_info", None)
    statistics = result.pop("statistics", None)
    if schema_info is not None or statistics is not None:
        nested = result.setdefault("result", {})
        if schema_info is not None:
            nested["schema_info"] = schema_info
        if statistics is not None:
            nested["statistics"] = statistics
    return result


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
    other_engine_handlers={
        "egeria": _trigger_egeria_native_survey,
        "egeria-adaptive": _run_egeria_adaptive,
    },
    egeria_technology_type_name="PostgreSQL Relational Database",
)

register_adapter(_ADAPTER)
