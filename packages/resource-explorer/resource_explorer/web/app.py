"""FastAPI application — query and project management web interface."""
from __future__ import annotations

from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from resource_explorer.bootstrap import start_scheduler as start_bootstrap_monitor, stop_scheduler as stop_bootstrap_monitor
from resource_explorer.egeria_resync import start_scheduler as start_resync_scheduler, stop_scheduler as stop_resync_scheduler
from resource_explorer.scheduler import start_scheduler
from resource_explorer.web.routes import activity, aliases, compile_context as compile_context_routes, analyses, automate, bootstrap as bootstrap_routes, context, curate, databases, db_servers as db_servers_routes, diagrams, discovery, egeria, feedback, investigations, logs as logs_routes, prefect_status, project_context, outbox, projects, query, repair, schedules, stats, webhook, filesystems, survey_definitions


log = logging.getLogger(__name__)


def _reconcile_orphaned_runs() -> None:
    try:
        from resource_explorer.run_reconciler import reconcile

        result = reconcile()
        if result["resolved"]:
            log.info("reconciled %s orphaned run(s) at startup; %s left alone",
                     result["resolved"], result["left_alone"])
    except Exception as exc:
        # Startup must not fail because bookkeeping did.
        log.warning("orphaned-run reconciliation skipped: %s", exc)


@asynccontextmanager
def _warm_survey_definition_cache() -> None:
    """Resolve question GUIDs in the background, so the first click does not.

    survey_definition_reader's caches are in-process dicts that die with the
    process, so after every restart the FIRST person to open a survey phase pays
    to resolve that phase's questions against Egeria. Measured 2026-09-01: every
    phase 0.1-0.2s warm, and Dan reported a cold phase at over ten seconds —
    with the timings looking random precisely because phases with disjoint
    question sets each pay separately.

    83381f1 made that cold path 6.8x faster by resolving through a thread pool
    rather than in series. It stopped the round trips queueing; it did not stop
    them happening. This moves them off the interactive path entirely.

    In a DAEMON THREAD, never awaited: startup must not wait on Egeria, which
    may legitimately not be up yet — the platform often starts after this
    process. The thread's own failures are swallowed by warm_question_guid_cache,
    which is best-effort by construction; if the warm does not happen, the first
    request resolves exactly as it does today. This changes WHEN the lookup
    happens, never WHAT it concludes.
    """
    import threading

    def _run() -> None:
        try:
            from resource_explorer.surveyors.survey_definition_reader import (
                SurveyDefinitionReader,
            )

            SurveyDefinitionReader().warm_question_guid_cache()
        except Exception as exc:  # never let an optimisation take the server down
            log.debug("survey-definition cache warm skipped: %s", exc)

    threading.Thread(target=_run, name="survey-cache-warm", daemon=True).start()


async def _lifespan(app: FastAPI):
    # A Survey Definition run lives in a daemon thread in THIS process, so a
    # restart kills it with no chance to write a terminal status and its
    # activity row claims "running" for ever. Anything left running by a
    # process that is provably gone is resolved here, at the one moment we can
    # be certain those threads are not coming back. Never raises and never
    # blocks: it fails safe, leaving alone anything it cannot judge.
    #
    # Supersedes an earlier, less careful version of this same idea
    # (ProjectRegistry.reconcile_orphaned_running_activity(), briefly on this
    # branch) that treated every 'running' row as orphaned on any startup —
    # wrong given multiple RE processes routinely share one database; it
    # would have falsely killed a peer's still-live run. Removed in favor of
    # this ownership-based (pid + process-start-time) version.
    _reconcile_orphaned_runs()
    start_scheduler()
    # Detect + repair Dr.Egeria definitions wiped by an Egeria reset. Runs one
    # check immediately (covers a restart alongside the reset) then periodically
    # (covers the common dev case where only the Egeria container is recycled
    # while this process keeps running). Never blocks startup: the initial check
    # happens inside the monitor thread, and it fails open when Egeria is
    # unreachable — see resource_explorer/bootstrap.py.
    start_bootstrap_monitor()
    # Detect + clear stale Egeria pointers (asset GUIDs, orphan publish claims,
    # investigation/context GUIDs) left behind by a repository-store wipe —
    # the registry-side counterpart to start_bootstrap_monitor()'s Dr.Egeria-
    # definition healing above. Same never-block/never-die-on-exception
    # discipline; deliberately only the SAFE_SCHEDULED_STEPS subset — anything
    # needing a human decision (Project bindings) or expensive (archive
    # downloads) stays manual, via Admin > Egeria Alignment. See
    # resource_explorer/egeria_resync.py.
    start_resync_scheduler()
    _warm_survey_definition_cache()
    yield
    stop_bootstrap_monitor()
    stop_resync_scheduler()


# Configure logging at import, so `uvicorn resource_explorer.web.app:app` run
# directly gets the same setup as `resource-explorer web`. Idempotent, so the
# CLI calling it first makes this a no-op rather than a second set of handlers.
from resource_explorer.observability.logging_setup import configure_logging as _configure_logging

_configure_logging()

app = FastAPI(
    title="Resource Explorer",
    description="Multi-agent RAG assistant for GitHub projects and databases",
    version="0.1.0",
    lifespan=_lifespan,
)

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

app.include_router(query.router, prefix="/api/query", tags=["query"])
app.include_router(projects.router, prefix="/api/projects", tags=["projects"])
app.include_router(databases.router, prefix="/api/databases", tags=["databases"])
app.include_router(filesystems.router, prefix="/api/filesystems", tags=["filesystems"])
app.include_router(stats.router, prefix="/api/stats", tags=["stats"])
app.include_router(aliases.router, prefix="/api/aliases", tags=["aliases"])
app.include_router(egeria.router, prefix="/api/egeria", tags=["egeria"])
app.include_router(db_servers_routes.router, prefix="/api/db-servers", tags=["db-servers"])
app.include_router(webhook.router, prefix="/api", tags=["webhook"])
app.include_router(activity.router, prefix="/api/activity", tags=["activity"])
app.include_router(bootstrap_routes.router, prefix="/api/bootstrap", tags=["bootstrap"])
app.include_router(analyses.router, prefix="/api/analyses", tags=["analyses"])
app.include_router(context.router, prefix="/api/context", tags=["context"])
app.include_router(compile_context_routes.router, prefix="/api/context", tags=["context-compile"])
app.include_router(project_context.router, prefix="/api/project-context", tags=["project-context"])
app.include_router(automate.router, prefix="/api/automate", tags=["automate"])
app.include_router(curate.router, prefix="/api/curate", tags=["curate"])
app.include_router(schedules.router, prefix="/api/schedules", tags=["schedules"])
app.include_router(prefect_status.router, prefix="/api/prefect", tags=["prefect"])
app.include_router(survey_definitions.router, prefix="/api/survey-definitions", tags=["survey-definitions"])
app.include_router(outbox.router, prefix="/api/outbox", tags=["outbox"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(discovery.router, prefix="/api/discovery", tags=["discovery"])
app.include_router(diagrams.router, prefix="/api/diagrams", tags=["diagrams"])
app.include_router(investigations.router, prefix="/api/investigations", tags=["investigations"])
app.include_router(repair.router, prefix="/api/admin/repair", tags=["repair"])
app.include_router(logs_routes.router, prefix="/api/logs", tags=["logs"])

_STATIC = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


@app.get("/health")
async def health() -> dict:
    """Pure liveness check — the process is up and answering HTTP, nothing
    more. Deliberately does NOT touch the database: returns 200 even when
    Postgres (and therefore almost every /api/ route) is unreachable, e.g.
    Docker not running after a reboot. Confirmed live — this genuinely
    happened and is exactly why /health/ready exists below: every /api/
    route 500'd while this kept returning 200, which is useless for
    detecting the actual problem. Frontend uses /health/ready instead."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready() -> JSONResponse:
    """Readiness check — actually exercises the registry's database
    connection, so it fails the same way real /api/ routes do rather than
    reporting healthy while they 500. Backs the frontend's startup +
    periodic connectivity banner (see index.html's checkBackendHealth())."""
    from resource_explorer.registry import ProjectRegistry

    try:
        registry = ProjectRegistry()
        with registry._conn() as conn:
            conn.execute("SELECT 1")
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unreachable", "detail": str(exc)},
        )
    return JSONResponse(content={"status": "ok", "database": "ok"})


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/admin/feedback")
async def admin_feedback() -> FileResponse:
    return FileResponse(_STATIC / "admin-feedback.html")
