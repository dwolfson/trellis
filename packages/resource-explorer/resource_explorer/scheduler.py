"""Background scheduler — executes due analyses in a daemon thread.

Schedules are configured via POST /api/schedules/{entity_type}/{slug} and stored
in the resource_schedules SQLite table. This module starts a single daemon thread
that wakes every _CHECK_INTERVAL_SECONDS, finds analyses whose next_run has passed,
runs them, and advances their next_run timestamp.

Every run — success or failure — writes a real ActivityEntry (via
activity_logger.log_survey) and records the outcome on the schedule row itself
(resource_schedules.last_run_status/last_run_activity_id). Previously this only
logged to Python's own logger, invisible from the UI — a real gap against
CLAUDE.md rule 16 ("Activity log entries must be written for ALL operations"),
not a deliberate omission. This is what backs the Admin Schedules overview's
"watch for successful completions, look for errors that need follow-up" use.

Supported entity_type values: 'repo', 'database'

Dispatch by analysis_id, not just entity_type: a scheduled analysis_id might be
(a) a local analysis_catalog entry — runs RE's own scan, as before; (b) a
local analysis_catalog entry flagged egeria_registration.native_process_ref
(currently just database's 'egeria_db_survey') — initiates Egeria's own
native re-survey of an already-cataloged resource via
EgeriaDatabaseSurveyor.trigger_survey_by_guid(), passing this schedule's
next_run as Egeria's own start_time so its engine host (not RE's poll loop)
owns the precise timing; (c) a local analysis_catalog entry that's neither of
the above (currently repo's 'egeria_publish' and database's equivalent) —
writes NEW things into Egeria (registers + publishes), deliberately excluded
from scheduling, which needs explicit operator intent, not a cadence; or (d)
not in the local catalog at all — a Discovery Survey Definition's
qualified_name, dispatched through the same run_survey_definition() executor
the manual Discovery "Run" button uses (database only — see _run_repo_survey
below for why repo has no equivalent case). Previously (b)/(c)/(d) were never
distinguished from (a) — every scheduled database analysis silently ran the
generic local scan regardless of which one was actually selected, a real gap
found while wiring this up, not by design.

Repo dispatch, separately: previously _run_repo_survey always ran the full
SurveyOrchestrator (all 10 sub-surveyors) regardless of which analysis_id was
scheduled — repo's own version of the (a)-only gap above, fixed the same way:
repo_survey_definition_adapter.REPO_ANALYSIS_STEP_MAP resolves a scheduled
analysis_id to the specific SurveyOrchestrator step key(s) to run via
SurveyOrchestrator.run(steps=...) — public there, not scheduler-private,
since web/routes/projects.py's per-card "Run just this one analysis" is a
second real consumer of the same mapping.
Repo has no (b)/(d) equivalent — no repo analysis_catalog entry is flagged
for native re-survey dispatch, and analysis_catalog_reader.py's live-Egeria
merge only ever applies to 'database' — so a repo analysis_id is always
either a local catalog entry (dispatch by step map) or 'egeria_publish' /
unrecognized (excluded/error, matching (c) above).

One more repo-only case: action:"ingest" (currently just 'rag_ingestion' —
"Refresh & Re-ingest," pgvector re-embedding via IncrementalIndexer). Unlike
action:"publish" this IS schedulable — it's a local re-index, not a new
write into Egeria's catalog of record — so it gets its own dispatch branch
in _run_repo_survey rather than going through REPO_ANALYSIS_STEP_MAP (it
isn't a SurveyOrchestrator step at all).
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 900  # 15 minutes
_started = False
_lock = threading.Lock()


def start_scheduler() -> None:
    """Start the background scheduler daemon thread (idempotent)."""
    global _started
    with _lock:
        if _started:
            return
        _started = True
    t = threading.Thread(
        target=_scheduler_loop,
        daemon=True,
        name="resource-explorer-scheduler",
    )
    t.start()
    log.info("Background scheduler started (check interval: %ds)", _CHECK_INTERVAL_SECONDS)


def _scheduler_loop() -> None:
    while True:
        time.sleep(_CHECK_INTERVAL_SECONDS)
        try:
            _run_due()
        except Exception:
            log.exception("Scheduler iteration failed")


def _run_due() -> None:
    from resource_explorer.activity_logger import log_survey
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    due = registry.get_due_schedules()
    if not due:
        return
    log.info("Scheduler: %d analysis(es) due", len(due))
    for sched in due:
        entity_type = sched["entity_type"]
        entity_slug = sched["entity_slug"]
        analysis_id = sched["analysis_id"]
        next_run = sched.get("next_run", "")
        analysis_name = _analysis_display_name(entity_type, analysis_id)
        try:
            entity_name, entity_location, errors = _execute(entity_type, entity_slug, analysis_id, registry, next_run)
            status = "error" if errors else "ok"
            detail = "; ".join(errors) if errors else ""
        except Exception as exc:
            log.exception("Scheduler: failed %s/%s/%s", entity_type, entity_slug, analysis_id)
            entity_name, entity_location, status, detail = entity_slug, "", "error", str(exc)

        summary = f"Scheduled run of '{analysis_name}' " + ("completed with errors" if status == "error" else "completed successfully")
        try:
            activity_id = log_survey(
                registry=registry,
                entity_type=entity_type,
                entity_slug=entity_slug,
                entity_name=entity_name,
                entity_location=entity_location,
                intent="scouting",
                status=status,
                summary=summary,
                detail=detail,
            )
        except Exception:
            log.exception("Scheduler: failed to write activity log entry for %s/%s/%s", entity_type, entity_slug, analysis_id)
            activity_id = ""

        try:
            registry.update_schedule_after_run(entity_type, entity_slug, analysis_id, status=status, activity_id=activity_id)
        except Exception:
            log.exception("Scheduler: failed to update schedule bookkeeping for %s/%s/%s", entity_type, entity_slug, analysis_id)

        log.info("Scheduler: %s %s/%s/%s", status, entity_type, entity_slug, analysis_id)


def _analysis_display_name(entity_type: str, analysis_id: str) -> str:
    """Best-effort human-readable name for the summary line — falls back to
    the raw id (e.g. a Discovery Survey Definition's qualified_name, which
    isn't in the local analysis_catalog) if no catalog entry matches."""
    try:
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        for a in get_analyses(entity_type, include_egeria_live=False):
            if a["id"] == analysis_id:
                return a["name"]
    except Exception:
        pass
    return analysis_id


def _catalog_entry(entity_type: str, analysis_id: str) -> dict | None:
    """The local analysis_catalog entry for this id, or None if analysis_id
    isn't in the catalog at all (e.g. a Discovery Survey Definition's
    qualified_name, which is never a catalog entry)."""
    try:
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        for a in get_analyses(entity_type, include_egeria_live=False):
            if a["id"] == analysis_id:
                return a
    except Exception:
        pass
    return None


def _execute(
    entity_type: str, entity_slug: str, analysis_id: str, registry, next_run: str = ""
) -> tuple[str, str, list[str]]:
    """Returns (entity_name, entity_location, errors) — errors is [] on a
    clean run. Only truly unexpected failures propagate to the caller.

    Dispatch — see module docstring for the (a)/(b)/(c)/(d) breakdown
    (database) and the repo-specific paragraph beneath it.
    """
    if entity_type == "repo":
        return _run_repo_survey(entity_slug, analysis_id, registry)
    elif entity_type == "database":
        return _run_db_survey(entity_slug, analysis_id, registry, next_run)
    else:
        return (entity_slug, "", [f"Unknown entity_type '{entity_type}'"])


def _run_repo_survey(slug: str, analysis_id: str, registry) -> tuple[str, str, list[str]]:
    project = registry.get(slug)
    if not project:
        return (slug, "", [f"Repo '{slug}' not found — schedule may be stale"])

    entry = _catalog_entry("repo", analysis_id)
    if entry is None:
        # Repo scheduling has no live-Egeria-merge equivalent to database's
        # case (d) — every valid repo analysis_id comes from the local
        # catalog, so "not found" means the catalog entry was since removed,
        # not a Discovery Survey Definition reference. Report it as stale
        # rather than silently falling back to a full survey, which would
        # hide exactly the kind of staleness this dispatch exists to surface.
        return (project.display_name, project.github_url, [
            f"Analysis '{analysis_id}' not found in the current analysis catalog — schedule may be stale."
        ])

    if entry.get("action") == "publish":
        return (project.display_name, project.github_url, [
            f"'{entry['name']}' writes new data into Egeria (action: publish) — excluded from "
            "scheduled runs by design. Run it manually when you intend that write."
        ])

    if entry.get("action") == "ingest":
        # rag_ingestion re-embeds content into pgvector via IncrementalIndexer,
        # not a SurveyOrchestrator step — unlike "publish" this IS schedulable
        # (it's a local re-index, not a new write into Egeria's catalog of
        # record), so it gets its own dispatch branch rather than the
        # step-map lookup below.
        from resource_explorer.ingestion.incremental import IncrementalIndexer
        from resource_explorer.query_cache import QueryCache

        try:
            IncrementalIndexer().refresh(project)
            QueryCache().invalidate_project(slug)
        except Exception as exc:
            return (project.display_name, project.github_url, [str(exc)])
        return (project.display_name, project.github_url, [])

    if entry.get("action") == "profile":
        # repo_profile_refresh downloads the zipball once and refreshes
        # project_file_inventory/project_data_profiles (local-only, not a
        # SurveyOrchestrator step) — schedulable like "ingest", not excluded
        # like "publish". Auto-chains the language_file_classification survey
        # against the freshly refreshed inventory, matching the interactive
        # Profile tab's own behavior (POST .../profile-scan) — a scheduled
        # refresh should produce the same displayed result an on-demand one
        # does, not a data-only update nothing ever reads.
        from resource_explorer.ingestion.pipeline import IngestionPipeline
        from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP
        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        try:
            IngestionPipeline().refresh_profile(
                project.slug, project.github_url, project.collections or [],
                subproject_path=project.subproject_path or None,
                include_symbols=False,
            )
        except Exception as exc:
            return (project.display_name, project.github_url, [str(exc)])

        registry.update_project_profiled_at(slug)

        errors = []
        try:
            classify_result = SurveyOrchestrator(registry).run(
                slug, steps=REPO_ANALYSIS_STEP_MAP["language_file_classification"],
            )
            errors = list(classify_result.errors) if classify_result.errors else []
        except Exception as exc:
            errors = [f"classification failed: {exc}"]
        return (project.display_name, project.github_url, errors)

    from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_STEP_MAP

    steps = REPO_ANALYSIS_STEP_MAP.get(analysis_id)
    if not steps:
        return (project.display_name, project.github_url, [
            f"Analysis '{analysis_id}' has no mapped survey step(s) — internal configuration gap."
        ])

    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    orch = SurveyOrchestrator(registry)
    result = orch.run(slug, steps=steps)
    errors = list(result.errors) if result.errors else []
    return (project.display_name, project.github_url, errors)


def _run_db_survey(slug: str, analysis_id: str, registry, next_run: str = "") -> tuple[str, str, list[str]]:
    db = registry.get_database(slug)
    if not db:
        return (slug, "", [f"Database '{slug}' not found — schedule may be stale"])

    entry = _catalog_entry("database", analysis_id)
    egeria_reg = (entry or {}).get("egeria_registration") or {}

    if entry is not None and not egeria_reg.get("native_process_ref"):
        # In the catalog, but not flagged for native re-survey dispatch —
        # currently means a 'publish'-action entry (writes NEW things into
        # Egeria, e.g. registering an asset) rather than a survey. Those need
        # explicit operator intent, not a cadence — see module docstring (c).
        if entry.get("action") == "publish":
            return (db.display_name, db.host, [
                f"'{entry['name']}' writes new data into Egeria (action: publish) — excluded from "
                "scheduled runs by design. Run it manually when you intend that write."
            ])
        return _run_local_db_survey(db, registry, analysis_id)

    if entry is not None and egeria_reg.get("native_process_ref"):
        # (b) Egeria-native re-survey of an already-cataloged database.
        return _run_egeria_native_db_survey(db, next_run)

    # (d) Not in the local catalog at all — a Discovery Survey Definition's
    # qualified_name. No start_time support here yet: run_survey_definition()
    # is a multi-step, multi-engine dispatch loop, not a single initiate call
    # — plumbing start_time through it is real, separate work, not done here.
    return _run_survey_definition(db, analysis_id, registry)


def _run_local_db_survey(db, registry, analysis_id: str = "") -> tuple[str, str, list[str]]:
    # Same credential resolution as the manual survey route
    # (web/routes/databases.py) — stored db_user/db_password at registration,
    # nothing else. There is no separate env-var/config fallback inside
    # database_connection() (it does a raw credentials["user"]/["password"]
    # lookup) — a prior version of this comment claimed one existed and
    # didn't, which is exactly why this crashed with a bare KeyError instead
    # of a clear message.
    if not db.db_user or not db.db_password:
        return (db.display_name, db.host, [
            "No stored database credentials for this schedule — register the "
            "database with db_user/db_password, or run its survey manually "
            "with credentials, before scheduling it."
        ])

    from resource_explorer.surveyors.database.database_surveyor import (
        DATABASE_ANALYSIS_STEP_MAP,
        run_database_survey,
    )

    # Database per-card dispatch fix (D6 prerequisite) — only run the
    # step(s) this specific analysis_id needs, not every local check every
    # time. analysis_id="" (or an unmapped id) falls back to steps=None
    # (the full survey), matching this function's exact prior behavior for
    # any caller that doesn't have an analysis_id in hand.
    steps = DATABASE_ANALYSIS_STEP_MAP.get(analysis_id)

    errors: list[str] = []
    try:
        run_database_survey(
            db.slug, credentials={"user": db.db_user, "password": db.db_password},
            registry=registry, steps=steps,
        )
    except Exception as exc:
        errors.append(str(exc))
    return (db.display_name, db.host, errors)


def _run_egeria_native_db_survey(db, next_run: str) -> tuple[str, str, list[str]]:
    if not db.egeria_asset_guid:
        return (db.display_name, db.host, [
            "Database is not yet cataloged in Egeria (no stored egeria_asset_guid) — "
            "catalog/publish it first (Scouting's survey report or Curate), or run this "
            "survey manually, before scheduling the native re-survey."
        ])

    from datetime import datetime

    start_time = None
    if next_run:
        try:
            start_time = datetime.fromisoformat(next_run)
        except ValueError:
            pass  # fall back to firing immediately rather than failing the whole run over this

    from resource_explorer.surveyors.database.egeria_database_surveyor import (
        EgeriaDatabaseSurveyor,
        EgeriaDatabaseSurveyorError,
    )

    surveyor = EgeriaDatabaseSurveyor()
    try:
        surveyor.trigger_survey_by_guid(db.egeria_asset_guid, start_time=start_time)
    except EgeriaDatabaseSurveyorError as exc:
        return (db.display_name, db.host, [str(exc)])
    return (db.display_name, db.host, [])


def _run_survey_definition(db, analysis_id: str, registry) -> tuple[str, str, list[str]]:
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import SurveyDefinitionReaderError

    try:
        result = run_survey_definition(
            "database", db.slug, registry=registry,
            survey_definition_ref=analysis_id, db_user=db.db_user, db_pwd=db.db_password,
        )
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        return (db.display_name, db.host, [str(exc)])
    errors = list(result.get("errors") or [])
    return (db.display_name, db.host, errors)
