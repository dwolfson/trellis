"""FastAPI application — query and project management web interface."""
from __future__ import annotations


import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from resource_explorer.web.routes import activity, aliases, compile_context as compile_context_routes, analyses, automate, bootstrap as bootstrap_routes, context, curate, databases, db_servers as db_servers_routes, diagrams, discovery, egeria, feedback, investigations, logs as logs_routes, prefect_status, project_context, outbox, projects, query, repair, schedules, stats, webhook, filesystems, survey_definitions


log = logging.getLogger(__name__)


def _embed_worker_enabled() -> bool:
    """Whether this web process also runs the worker role in-process.

    Read from the environment/config rather than passed in, because with
    `--workers N` uvicorn re-imports this module in each child process —
    a value the CLI held in a local would never reach them.
    `resource-explorer web` sets EXPLORER_EMBED_WORKER explicitly from
    its --embed-worker/--no-embed-worker flag; the default is True so
    `make dev`, an existing .env, and a bare
    `uvicorn resource_explorer.web.app:app` all keep the behaviour they
    had when the loops were started from this lifespan directly.
    """
    raw = os.environ.get("EXPLORER_EMBED_WORKER")
    if raw is not None:
        return raw.strip().lower() not in ("0", "false", "no", "off", "")
    try:
        from resource_explorer.config import get_config

        return bool(get_config().runtime.embed_worker)
    except Exception:
        return True


async def _lifespan(app: FastAPI):
    """Serve HTTP. Start background loops only when asked to embed one.

    Until 2026-09-04 this function started five things itself — the
    scheduler, the bootstrap monitor, the Egeria resync scanner, a
    survey-definition cache warm, and a one-shot orphaned-run
    reconciliation — which made the web server the only way to run any
    of them, and made N uvicorn workers mean N copies of each. They live
    in resource_explorer/worker.py now (docs/runtime-architecture-plan.md
    §2); this lifespan starts a thread only if EXPLORER_EMBED_WORKER says
    to, and even then leader election decides whether that thread's loops
    actually fire. See docs/process-model.md.
    """
    worker_stop = None
    if _embed_worker_enabled():
        from resource_explorer.worker import start_embedded_worker

        _thread, worker_stop = start_embedded_worker()
        log.info("embedded worker role started in this web process")
    else:
        log.info(
            "no embedded worker in this web process (EXPLORER_EMBED_WORKER "
            "disabled) — background loops require `resource-explorer worker`"
        )
    yield
    if worker_stop is not None:
        worker_stop.set()


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
