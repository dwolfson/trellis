"""Background scheduler — executes due analyses in a daemon thread.

Schedules are configured via POST /api/schedules/{entity_type}/{slug} and stored
in the resource_schedules SQLite table. This module starts a single daemon thread
that wakes every _CHECK_INTERVAL_SECONDS, finds analyses whose next_run has passed,
runs them, and advances their next_run timestamp.

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
        try:
            _execute(entity_type, entity_slug, analysis_id, registry)
            registry.update_schedule_after_run(entity_type, entity_slug, analysis_id)
            log.info("Scheduler: completed %s/%s/%s", entity_type, entity_slug, analysis_id)
        except Exception:
            log.exception(
                "Scheduler: failed %s/%s/%s", entity_type, entity_slug, analysis_id
            )


def _execute(
    entity_type: str, entity_slug: str, analysis_id: str, registry
) -> None:
    if entity_type == "repo":
        _run_repo_survey(entity_slug, registry)
    elif entity_type == "database":
        _run_db_survey(entity_slug, registry)
    else:
        log.warning("Scheduler: unknown entity_type '%s' — skipping", entity_type)


def _run_repo_survey(slug: str, registry) -> None:
    project = registry.get(slug)
    if not project:
        log.warning("Scheduler: repo '%s' not found — skipping", slug)
        return
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

    orch = SurveyOrchestrator(registry)
    result = orch.run(slug)
    if result.errors:
        log.warning("Scheduler: repo survey '%s' completed with errors: %s", slug, result.errors)


def _run_db_survey(slug: str, registry) -> None:
    db = registry.get_database(slug)
    if not db:
        log.warning("Scheduler: database '%s' not found — skipping", slug)
        return
    # Use stored credentials from config/env; pass empty dict so DatabaseSurveyor
    # falls back to its own credential resolution (env vars / config).
    from resource_explorer.surveyors.database.database_surveyor import run_database_survey

    run_database_survey(slug, credentials={}, registry=registry)
