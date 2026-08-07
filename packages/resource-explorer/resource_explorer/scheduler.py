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
Supported analysis actions: anything in configdata/analysis_catalog.yaml (read via
resource_explorer.surveyors.analysis_catalog_reader) whose action is 'survey'.
'publish' (Egeria write-back) is intentionally excluded from scheduled runs — those
require a live Egeria connection and explicit operator intent.
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
        analysis_name = _analysis_display_name(entity_type, analysis_id)
        try:
            entity_name, entity_location, errors = _execute(entity_type, entity_slug, analysis_id, registry)
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


def _execute(
    entity_type: str, entity_slug: str, analysis_id: str, registry
) -> tuple[str, str, list[str]]:
    """Returns (entity_name, entity_location, errors) — errors is [] on a
    clean run. Only truly unexpected failures propagate to the caller."""
    if entity_type == "repo":
        return _run_repo_survey(entity_slug, registry)
    elif entity_type == "database":
        return _run_db_survey(entity_slug, registry)
    else:
        return (entity_slug, "", [f"Unknown entity_type '{entity_type}'"])


def _run_repo_survey(slug: str, registry) -> tuple[str, str, list[str]]:
    project = registry.get(slug)
    if not project:
        return (slug, "", [f"Repo '{slug}' not found — schedule may be stale"])
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    orch = SurveyOrchestrator(registry)
    result = orch.run(slug)
    errors = list(result.errors) if result.errors else []
    return (project.display_name, project.github_url, errors)


def _run_db_survey(slug: str, registry) -> tuple[str, str, list[str]]:
    db = registry.get_database(slug)
    if not db:
        return (slug, "", [f"Database '{slug}' not found — schedule may be stale"])
    # Use stored credentials from config/env; pass empty dict so DatabaseSurveyor
    # falls back to its own credential resolution (env vars / config).
    from resource_explorer.surveyors.database.database_surveyor import run_database_survey

    errors: list[str] = []
    try:
        run_database_survey(slug, credentials={}, registry=registry)
    except Exception as exc:
        errors.append(str(exc))
    return (db.display_name, db.host, errors)
