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
        # design §5.1's capability declaration, surfaced so a caller of this
        # step (e.g. a future postgres_operations step, or the UI) can tell
        # "this engine cannot report X" from "X was measured as empty"
        # without re-opening a connection of its own.
        "engine_capabilities": result.get("engine_capabilities", {}),
    }


def _run_postgres_operations(db_entity, registry, db_user: str = "", db_pwd: str = "", **_) -> dict:
    """postgres_operations (Phase 1 slice 8, design §5.5/§5.7): privilege_audit,
    db_activity_signals, db_resilience, db_external_dependencies. Runs
    DatabaseSurveyor.survey(steps=["operations"]) — "schema" runs alongside
    unconditionally (DatabaseSurveyor's own invariant), "statistics"/"views"
    do not, so this step stays at the "api / low" cost design §5.7
    describes rather than paying for the full survey.
    """
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    surveyor = DatabaseSurveyor(db_entity, {"user": db_user, "password": db_pwd}, registry)
    result = surveyor.survey(steps=["operations"])
    return {
        "schema_info": result.get("schema_info", {}),
        "operations": result.get("operations", {}),
    }


def _run_db_derived(db_entity, registry, **_) -> dict:
    """db_derived (Phase 1 slice 9, design §5.3/§5.7): the ZERO-FETCH step —
    classification, relationship graph, grain, fingerprint, structural
    conventions checks, change rates and a proposed DataScope, all derived
    from rows RE already stored.

    Note the signature: no `db_user`/`db_pwd`. Unlike every other handler in
    this module it never constructs a `DatabaseSurveyor` and never opens a
    connection, so credentials are not merely unused here — there is nothing
    to give them to. That is the design §5.7 cost line ("none / low") made
    literal, and it is why this step can answer for a database whose
    credentials are gone or whose server is down.
    """
    from resource_explorer.surveyors.database.db_derived import run_db_derived

    result = run_db_derived(registry, db_entity.slug)
    return {
        "derived": result.get("derived", {}),
        "read_snapshot": result.get("read_snapshot"),
    }


def _run_postgres_column_profile(
    db_entity, registry, db_user: str = "", db_pwd: str = "",
    sampling: dict | None = None, read_egeria_catalog: bool = True, **_,
) -> dict:
    """postgres_column_profile (Phase 1 slice 10, design §5.4/§5.7/§5.8):
    bounded value sampling, `data_class_match`, `reference_data_match`.

    The only step in the database family that reads actual table data — design
    §5.7 prices it "api_heavy / medium" — so it runs only when a Survey
    Definition asks for it, never as part of a default survey.

    `sampling` is §5.8's configuration, resolved at the run scope: any of
    `strategy`, `max_rows`, `max_bytes`, `max_values`, `seed`, `time_budget`,
    `strata_column`. Omitted, the step's default is `random` with
    `TABLESAMPLE`, seeded per resource so two runs differ only when the data
    did.

    `read_egeria_catalog` reads the platform's Data Classes and Valid Value
    Sets up front. When it is off, or the read fails, every column's verdict
    is `no_candidates` rather than "no match" — a run that never asked the
    platform what exists has established nothing about whether a column
    matches something, and the two must not render alike.
    """
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    from resource_explorer.surveyors.database.egeria_reference_catalog import (
        ReferenceCatalog,
        build_reference_clients,
        load_reference_catalog,
    )

    catalog: ReferenceCatalog | None = None
    catalog_error = ""
    if read_egeria_catalog:
        try:
            designer, ref_manager = build_reference_clients()
            catalog = load_reference_catalog(designer, ref_manager)
        except Exception as exc:
            # Non-fatal, and deliberately NOT swallowed into an empty
            # catalogue. The failure becomes a `ReferenceCatalog` that is
            # explicitly unavailable and carries the reason, so it reaches
            # three observable places rather than only a log line: every
            # column's verdict (`no_candidates`, never "no match"), the
            # confidence-0 annotation that names the failure, and this step's
            # own `reference_catalog_error` output field, which a caller can
            # branch on.
            catalog_error = str(exc)
            log.warning(
                "Could not read Egeria's Data Classes / Valid Value Sets for "
                "%s — every column's match verdict will be 'no_candidates': %s",
                db_entity.slug, exc,
            )
            catalog = ReferenceCatalog(
                available=False,
                unavailable_reason=(
                    f"the Egeria platform's Data Classes and Valid Value Sets "
                    f"could not be read: {exc}"
                ),
            )

    surveyor = DatabaseSurveyor(db_entity, {"user": db_user, "password": db_pwd}, registry)
    result = surveyor.survey(
        steps=["column_profile"], sampling_overrides=sampling, reference_catalog=catalog,
    )
    return {
        "schema_info": result.get("schema_info", {}),
        "column_profile": result.get("column_profile", {}),
        # "" when the catalogue read succeeded or was not attempted; the
        # failure's message otherwise. A caller that only looks at the step's
        # status would otherwise see an ordinary success.
        "reference_catalog_error": catalog_error,
    }


def _run_postgres_nested_columns(
    db_entity, registry, db_user: str = "", db_pwd: str = "",
    sampling: dict | None = None, **_,
) -> dict:
    """postgres_nested_columns (Phase 1 slice 11, design §5.4/§5.7): bounded
    JSON/JSONB/XML value sampling and nested-schema inference.

    Gated on slice 10 ("shares the inference core", per the coordinator
    brief) — this reuses `postgres_column_profile`'s exact sampling
    machinery (`sampling.py`, `column_profile_step.sample_column_values`/
    `SamplingBudget`) and `column_matching.type_family` to find the JSON/XML
    columns in the first place. The actual "given these values, what's the
    schema" logic lives in `nested_schema_inference.py`, which imports
    neither pyegeria nor psycopg2 so it can be reused by §6's
    `nested_schema_profile` (files/folders, Phase 2, not this slice).

    Like `postgres_column_profile`, this is the only other step in the
    database family that reads actual table data (design §5.7: "api_heavy /
    medium") — it runs only when a Survey Definition asks for it, never as
    part of a default survey. `sampling` is the same §5.8 configuration
    surface, resolved at the run scope.
    """
    from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor

    surveyor = DatabaseSurveyor(db_entity, {"user": db_user, "password": db_pwd}, registry)
    result = surveyor.survey(steps=["nested_columns"], sampling_overrides=sampling)
    return {
        "schema_info": result.get("schema_info", {}),
        "nested_columns": result.get("nested_columns", {}),
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
    operations: dict = {}
    for output in step_outputs:
        schema_info = output.get("schema_info") or schema_info
        statistics = output.get("statistics") or statistics
        views = output.get("views") or views
        operations = output.get("operations") or operations

    surveyor = EgeriaDatabaseSurveyor()
    result = surveyor.publish_step_annotations(
        entity, schema_info, statistics, surveyed_at, registry,
        views=views, operations=operations,
    )
    return result.get("report_guid", "")


_ADAPTER = ResourceTypeAdapter(
    entity_type="database",
    technology_type="PostgreSQL Database",
    re_analysis_steps={
        "postgres_schema_and_stats": _run_postgres_schema_and_stats,
        "postgres_operations": _run_postgres_operations,
        "db_derived": _run_db_derived,
        "postgres_column_profile": _run_postgres_column_profile,
        "postgres_nested_columns": _run_postgres_nested_columns,
        "sql_analysis": _run_postgres_sql_analysis,
    },
    get_entity=_get_database_entity,
    publish=_publish,
    re_analysis_step_info={
        "postgres_schema_and_stats": {
            "description": (
                "Schema, table, and column inventory plus row-count/size statistics, "
                "pg_stats column profiling, pg_stat_user_tables tuple counters/scan "
                "activity, and index usage/unused-index detection."
            ),
            "annotation_types": [
                "SchemaAnalysisAnnotation",
                "ResourceMeasureAnnotation",
                "RequestForAction",
            ],
        },
        "postgres_operations": {
            "description": (
                "Folds privilege_audit (roles/grants/default ACLs, RFA on PUBLIC "
                "grants), db_activity_signals (database-wide activity roll-up), "
                "db_resilience (replication/WAL archiving/backup-tool/clustering "
                "signals — a MIXED analysis, design §5.5) and db_external_dependencies "
                "(extensions/FDWs/publications) into one step (design §5.7)."
            ),
            "annotation_types": [
                "ResourceMeasureAnnotation",
                "ResourcePhysicalStatusAnnotation",
                "SchemaAnalysisAnnotation",
                "RequestForAction",
            ],
        },
        "db_derived": {
            "description": (
                "Zero-fetch derivation over already-stored rows (design §5.3, "
                "§5.7): db_classification (what kind of database this is), "
                "db_relationship_graph (FK graph, or a bag of tables), "
                "grain_determination (one row per what, per table), "
                "db_fingerprint (copy/subset of a database we already know), "
                "schema_conventions (no PK, no comment, naming), "
                "db_change_rates (tuple-counter deltas between snapshots) and "
                "a proposed DataScope. Opens no connection to the database or "
                "to Egeria."
            ),
            "annotation_types": [
                "ClassificationAnnotation",
                "SchemaAnalysisAnnotation",
                "DataGrainAnnotation",
                "FingerprintAnnotation",
                "ResourceMeasureAnnotation",
            ],
        },
        "postgres_column_profile": {
            "description": (
                "Bounded value sampling (design §5.8: catalog_stats_only / head / "
                "random via TABLESAMPLE SYSTEM|BERNOULLI / systematic / stratified / "
                "full, with max_rows, max_bytes, max_values, a per-resource seed and "
                "a time budget), then data_class_match (column name + type + "
                "value-pattern conformance against every Egeria DataClass) and "
                "reference_data_match (low-cardinality distinct values against every "
                "ValidValueSet). Unmatched-but-patterned columns are proposed as new "
                "DataClasses / ValidValueSets with contentStatus: DRAFT, linked to "
                "their evidence via AssociatedAnnotation; a partial reference-data "
                "match raises an RFA naming the unmatched values. Every threshold is "
                "stated against the sample that produced it."
            ),
            "annotation_types": [
                "ResourceMeasureAnnotation",
                "DataClassAnnotation",
                "RelationshipAnnotation",
                "RequestForAction",
            ],
        },
        "postgres_nested_columns": {
            "description": (
                "Bounded value sampling of JSONB/JSON/XML columns (design §5.8's "
                "same configuration surface as postgres_column_profile, "
                "purpose='matching'), then nested-schema inference: JSON key "
                "presence frequency, observed-type consistency and nesting "
                "depth; XML root-element and element/attribute name frequency. "
                "Produces a SchemaAnalysisAnnotation per column carrying the "
                "inferred schema — including for a column where every sampled "
                "value was a JSON scalar or unparseable XML, which is a real "
                "finding (design §5.4), not an absence. Shares its inference "
                "core with the (not-yet-built) filesystem nested_schema_profile."
            ),
            "annotation_types": [
                "ResourceMeasureAnnotation",
                "SchemaAnalysisAnnotation",
            ],
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


#: analysis_id -> the re_analysis_step key(s) that produce it — the database
#: equivalent of repo_survey_definition_adapter.REPO_ANALYSIS_STEP_MAP, added
#: for ProjectRegistry.get_analysis_last_run()'s database attribution (see
#: docs/Backlog.md, "Database/filesystem Analyses cards never showed a last-
#: run/published badge"). Unlike REPO_ANALYSIS_STEP_MAP, this is NOT a
#: partition of the step-key space in the other direction: a single coarse
#: re_analysis_step here (e.g. "db_derived") is itself the SOURCE of several
#: analysis_catalog.yaml entries, so several analysis_ids legitimately map to
#: the SAME step key — that fan-out is intentional, not a collision, and
#: ProjectRegistry inverts this generically (step_key -> list[analysis_id])
#: rather than assuming a single owner per step the way repo's inversion does.
#: Every analysis_id here owns exactly one step key of its own, so
#: `last_run_partial` is never true for a database analysis today.
#:
#: Built directly from _ADAPTER.re_analysis_step_info's own descriptions
#: above, which name these analysis_catalog ids explicitly (e.g.
#: "db_derived"'s docstring literally lists db_classification,
#: db_relationship_graph, grain_determination, db_fingerprint,
#: schema_conventions and db_change_rates by name) — not a guess.
#:
#: Two known gaps, deliberately left open rather than guessed at:
#: * "sql_analysis" has no analysis_catalog.yaml entry at all (no card
#:   depends on it), so it is omitted here on purpose.
#: * "egeria_db_survey" is triggered via `other_engine_handlers["egeria"]`,
#:   not `re_analysis_steps` — docs/survey-definitions.md says
#:   `re_analysis_step` is meaningful "for executes_at: resource-explorer
#:   steps only", so whether a live Survey Definition's egeria-triggered
#:   GovActionProcessStep actually carries
#:   `re_analysis_step: egeria_db_survey` in Egeria is unconfirmed — nothing
#:   in this codebase enforces it. Mapped here on the reasonable convention
#:   that an author would name it after its own analysis_catalog id; if a
#:   live definition uses something else, this entry silently fails to
#:   attribute (falls into `__unattributed_surveys__`, never a wrong
#:   attribution) until corrected.
DATABASE_ANALYSIS_STEP_MAP: dict[str, list[str]] = {
    "schema_inventory": ["postgres_schema_and_stats"],
    "row_count_snapshot": ["postgres_schema_and_stats"],
    "privilege_audit": ["postgres_operations"],
    "db_activity_signals": ["postgres_operations"],
    "db_resilience": ["postgres_operations"],
    "db_external_dependencies": ["postgres_operations"],
    "db_classification": ["db_derived"],
    "db_relationship_graph": ["db_derived"],
    "grain_determination": ["db_derived"],
    "db_fingerprint": ["db_derived"],
    "schema_conventions": ["db_derived"],
    "db_change_rates": ["db_derived"],
    "data_class_match": ["postgres_column_profile"],
    "reference_data_match": ["postgres_column_profile"],
    "nested_column_profile": ["postgres_nested_columns"],
    "egeria_db_survey": ["egeria_db_survey"],
}
