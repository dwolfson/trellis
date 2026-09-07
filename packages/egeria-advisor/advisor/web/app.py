"""
Egeria Advisor Web UI — FastAPI application.

Endpoints:
  GET  /                  → index.html
  POST /api/query         → run a query, return result dict
  GET  /api/reports       → report spec catalog grouped by topic
  GET  /api/status        → system / MCP connection status
  POST /api/feedback      → record 👍 / 👎 on a response
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

# Cross-cutting helpers used by more than one route group live in
# advisor.web.shared (TC-5, BACKLOG.md) — imported, not redefined, so
# `advisor.web.app.<name>` keeps resolving for existing external lazy
# imports (advisor.rag_system imports `_intent_meta` this way).
from advisor.web.shared import (
    _STATIC,
    _intent_meta,  # noqa: F401 -- unused in this module, kept importable: advisor.rag_system imports it from here
    _BROWSER_FORMATS,
    _catalog_formats,
    _load_report_catalog,
)


def _cors_origin_regex() -> str:
    """
    localhost is always allowed (local dev). ADVISOR_EXTRA_CORS_ORIGINS (.env,
    comma-separated) adds extra exact origins — e.g. a Portal embedding this
    Advisor from a different origin. Same-origin browser access (the SPA served
    from the same host:port as the API) never needs this.
    """
    from advisor.config import settings
    patterns = [r"https?://localhost(:\d+)?"]
    extra = [o.strip() for o in settings.advisor_extra_cors_origins.split(",") if o.strip()]
    patterns.extend(re.escape(origin) for origin in extra)
    return "|".join(f"({p})" for p in patterns)


app = FastAPI(title="Egeria Advisor", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=_cors_origin_regex(),
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)
app.mount("/static", StaticFiles(directory=_STATIC), name="static")


def _install_login_required_middleware() -> None:
    """Install `trellis_auth.LoginRequiredMiddleware` — the shared login policy.

    **Ordering matters and is the reason this is a function rather than two
    inline lines.** Starlette applies `add_middleware` in reverse order: the
    *last* one added is the *outermost*. `_user_context_middleware` below is
    registered by its decorator at import time, after this call, so it ends up
    outside this one — which is what we want spelled out explicitly, because
    the requirement reads the other way round in prose ("install the login gate
    ahead of the user-context middleware", i.e. it must run *before* a handler
    does, not before the context middleware in the stack).

    The user-context middleware being outermost is harmless and slightly
    useful: it sets the ContextVar from whatever token is present and resets it
    in `finally`, so even a request this gate rejects leaves no identity behind.
    Nothing downstream of a 401 ever runs, so no handler can act on a
    half-authenticated context.

    Registered before the CORS middleware would be wrong in the other
    direction — a cross-origin 401 must still carry its CORS headers or the
    browser reports an opaque network error instead of "please sign in". CORS
    is added above, therefore ends up outside this, therefore decorates the
    401. That is the arrangement, and `test_login_required_middleware.py`
    pins it.
    """
    from trellis_auth import LoginRequiredMiddleware
    from advisor.auth import _base_config, get_policy

    app.add_middleware(
        LoginRequiredMiddleware,
        config=_base_config(),
        policy=get_policy(),
    )


_install_login_required_middleware()


@app.middleware("http")
async def _user_context_middleware(request: Request, call_next):
    """
    Sets advisor.request_context's per-request ContextVar from this
    request's JWT (via advisor.auth.get_current_user), for every request —
    so any code reached from a route handler, no matter how many plain
    function calls deep (rag_system → plan_elicitor/report_spec_elicitor →
    the agents, in particular — see request_context.py's module docstring),
    can recover the signed-in user's identity without it being threaded
    through every intervening signature. Reset in `finally` so a handler
    that raises can't leak identity into whatever runs next.

    Mirrors the `user_id = None if not user or user.get("anonymous") else
    user.get("user_id") or user.get("sub")` extraction every namespaced
    route already does explicitly (those explicit computations still win —
    this only supplies the ambient default for code that doesn't have a
    `Request` to ask).
    """
    from advisor.auth import get_current_user
    from advisor.request_context import set_current_user, reset_current_user

    user = None
    try:
        user = get_current_user(request)
    except Exception:  # pragma: no cover - get_current_user itself never raises; defensive only
        logger.debug("_user_context_middleware: get_current_user failed", exc_info=True)
    user_id = None if not user or user.get("anonymous") else (user.get("user_id") or user.get("sub"))
    role = (user or {}).get("role")
    token = set_current_user(user_id, role)
    try:
        return await call_next(request)
    finally:
        reset_current_user(token)


from advisor.web.admin import router as _admin_router
app.include_router(_admin_router)

from advisor.web.auth import router as _auth_router
app.include_router(_auth_router)

from advisor.web.feedback import router as _feedback_router
app.include_router(_feedback_router)

from advisor.web.query import router as _query_router
app.include_router(_query_router)

from advisor.web.plan_templates import router as _plan_templates_router
app.include_router(_plan_templates_router)

from advisor.web.sessions import router as _sessions_router
app.include_router(_sessions_router)

from advisor.web.templates import router as _templates_router
app.include_router(_templates_router)

from advisor.web.drafts import router as _drafts_router
app.include_router(_drafts_router)

from advisor.web.plans import router as _plans_router
app.include_router(_plans_router)

# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/reports")
async def list_reports(include_dre: bool = False) -> Dict[str, Any]:
    """Return the report spec catalog grouped by topic."""
    catalog = _load_report_catalog(include_dre=include_dre)
    total = sum(len(v) for v in catalog.values())
    formats = _catalog_formats(catalog)
    return {
        "catalog": catalog,
        "formats": formats,
        "format_labels": dict(_BROWSER_FORMATS),
        "total": total,
        "include_dre": include_dre,
    }


@app.get("/api/status")
async def system_status() -> Dict[str, Any]:
    """Return connection status for Egeria MCP servers."""
    mcp_status: List[Dict[str, Any]] = []
    try:
        cfg_path = Path(__file__).parent.parent / "configdata" / "mcp_servers.json"
        if cfg_path.exists():
            cfg = json.loads(cfg_path.read_text())
            for name, srv in cfg.get("mcpServers", {}).items():
                if name.startswith("_"):
                    continue
                mcp_status.append({
                    "name": name,
                    "enabled": srv.get("enabled", True),
                    "transport": srv.get("transport", "stdio"),
                    "description": srv.get("description", ""),
                })
    except Exception as exc:
        logger.warning(f"Status check failed: {exc}")

    return {"mcp_servers": mcp_status, "rag": "ok"}


# ── Report Spec Document / Draft endpoints ──────────────────────────────────────

@app.get("/api/reports/docs")
async def list_report_docs(request: Request) -> Dict[str, Any]:
    """Return inbox, outbox, and trash report spec document lists, annotated
    with active draft IDs. Namespace-scoped like GET /api/plans."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.report_draft import list_visible_report_drafts
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_report_spec_doc_manager()
    inbox = dm.list_inbox(requester_user_id=user_id, requester_role=role)
    outbox = dm.list_outbox(requester_user_id=user_id, requester_role=role)
    trash = dm.list_trash(requester_user_id=user_id, requester_role=role)

    # Build doc_id -> draft_id map for active report drafts
    doc_to_draft: Dict[str, str] = {}
    for d in list_visible_report_drafts(user_id=user_id, role=role):
        if d.get("doc_id") and d.get("phase") in ("generate", "refine"):
            doc_to_draft[d["doc_id"]] = d["draft_id"]

    for entry in inbox:
        entry["draft_id"] = doc_to_draft.get(entry.get("doc_id"))

    return {"inbox": inbox, "outbox": outbox, "trash": trash}


@app.get("/api/reports/docs/{doc_id}")
async def get_report_doc(request: Request, doc_id: str) -> Dict[str, Any]:
    """Return the content of a report spec document by doc_id (inbox, outbox, or trash).

    Ownership-checked like GET /api/plans/{doc_id}.
    """
    from fastapi import HTTPException
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_report_spec_doc_manager()
    content = dm.load(doc_id, include_trash=True, requester_user_id=user_id,
                       requester_role=role, enforce_ownership=True)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Report spec {doc_id!r} not found")
    folder = dm.folder_of(doc_id) or "outbox"
    return {"doc_id": doc_id, "content": content, "folder": folder}


@app.get("/api/reports/docs/{doc_id}/export")
async def export_report_doc(doc_id: str) -> Response:
    """Download the full current content of a report spec document (inbox or outbox)."""
    from fastapi import HTTPException
    from advisor.report_spec_docs import get_report_spec_doc_manager
    dm = get_report_spec_doc_manager()
    content = dm.load(doc_id, include_trash=True)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Report spec {doc_id!r} not found")
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.md"'},
    )


@app.post("/api/reports/specs/import")
async def import_report_spec(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Import an externally-written Report Spec markdown document as a new
    managed spec in inbox. Mirrors POST /api/plans/import (namespaced to
    the signed-in user; anonymous keeps the shared namespace).
    """
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.auth import get_current_user
    from fastapi import HTTPException
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    title = (body.get("title") or "").strip() or None
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    dm = get_report_spec_doc_manager()
    try:
        doc_id = dm.import_document(content, title=title, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "doc_id": doc_id, "folder": "inbox"}


@app.put("/api/reports/docs/{doc_id}")
async def update_report_doc(doc_id: str, body: Dict[str, str]) -> Dict[str, Any]:
    """Update report spec document content (called by canvas or manual save)."""
    from fastapi import HTTPException
    from advisor.report_spec_docs import get_report_spec_doc_manager
    dm = get_report_spec_doc_manager()
    content = body.get("content", "")
    ok = dm.update(doc_id, content)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Report spec {doc_id!r} not found in inbox")
    return {"status": "ok"}


@app.post("/api/reports/docs/{doc_id}/execute")
async def execute_report_doc(
    request: Request,
    doc_id: str,
    body: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a report spec document and append run outcome.

    Requires login — this performs a live Egeria read and must be
    attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.report_spec_agent import get_report_spec_agent
    agent = get_report_spec_agent()
    body_data = body or {}
    fmt = body_data.get("output_format", "REPORT")
    params = body_data.get("params")
    dry_run = body_data.get("dry_run", False)
    return agent.execute(
        doc_id,
        dry_run=dry_run,
        output_format=fmt,
        custom_params=params,
        egeria_credentials=egeria_credentials,
    )


@app.post("/api/reports/specs/{doc_id}/archive")
async def archive_report_result(doc_id: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Save an execution result snapshot to the outbox without re-running the report."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    doc_manager = get_report_spec_doc_manager()
    body_data = body or {}
    content = body_data.get("content", "")
    from datetime import datetime
    ts_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    outcome_md = f"## Outcome\n\n**Status:** Completed\n**Saved At:** {ts_str}\n\n{content}\n"
    outbox_id = doc_manager.move_to_outbox(doc_id, outcome_md)
    if not outbox_id:
        return {"ok": False, "error": f"Could not save {doc_id} to outbox"}
    return {"ok": True, "outbox_id": outbox_id}


@app.post("/api/reports/docs/{doc_id}/retry")
async def retry_report_doc(request: Request, doc_id: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Move an executed report back to inbox and re-execute it.

    Requires login — see execute_report_doc.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.report_spec_agent import get_report_spec_agent
    agent = get_report_spec_agent()
    body_data = body or {}
    fmt = body_data.get("output_format", "REPORT")
    return agent.retry(doc_id, output_format=fmt, egeria_credentials=egeria_credentials)


@app.post("/api/reports/docs/{doc_id}/recover")
async def recover_report_doc(doc_id: str) -> Dict[str, Any]:
    """Move an executed report back to inbox (stripping outcomes) without re-running."""
    from advisor.agents.report_spec_agent import get_report_spec_agent
    agent = get_report_spec_agent()
    return agent.recover(doc_id)


@app.get("/api/reports/docs/{doc_id}/versions")
async def get_report_doc_versions(doc_id: str) -> List[Dict[str, str]]:
    """Return version history for a report spec document."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    return get_report_spec_doc_manager().list_versions(doc_id)


@app.post("/api/reports/docs/{doc_id}/versions/{version_file:path}/restore")
async def restore_report_doc_version(doc_id: str, version_file: str) -> Dict[str, str]:
    """Restore a version of a report spec document."""
    from fastapi import HTTPException
    from advisor.report_spec_docs import get_report_spec_doc_manager
    ok = get_report_spec_doc_manager().restore_version(doc_id, version_file)
    if not ok:
        raise HTTPException(status_code=400, detail="Failed to restore version")
    return {"status": "ok"}


@app.delete("/api/reports/docs/{doc_id}")
async def delete_report_doc(request: Request, doc_id: str) -> Dict[str, str]:
    """Soft delete a report spec document. Ownership-checked (see GET above)."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_report_spec_doc_manager()
    visible = dm.load(doc_id, requester_user_id=user_id, requester_role=role, enforce_ownership=True)
    if visible is None:
        return {"status": "not_found"}
    deleted = dm.delete(doc_id)
    return {"status": "ok" if deleted else "not_found"}


@app.post("/api/reports/docs/{doc_id}/restore-trash")
async def restore_report_doc_trash(doc_id: str) -> Dict[str, str]:
    """Restore a report spec document from trash."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    restored = get_report_spec_doc_manager().restore_from_trash(doc_id)
    return {"status": "ok" if restored else "not_found"}


@app.delete("/api/reports/docs/{doc_id}/purge")
async def purge_report_doc(doc_id: str) -> Dict[str, str]:
    """Permanently delete a report spec document from trash."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    purged = get_report_spec_doc_manager().purge(doc_id)
    return {"status": "ok" if purged else "not_found"}


@app.get("/api/reports/drafts")
async def list_report_drafts(request: Request) -> List[Dict[str, Any]]:
    """List active report drafts visible to the requester (see GET /api/drafts)."""
    from advisor.report_draft import list_visible_report_drafts
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    return list_visible_report_drafts(user_id=user_id, role=role)


@app.get("/api/reports/drafts/{draft_id}")
async def get_report_draft(request: Request, draft_id: str) -> Dict[str, Any]:
    """Get report spec draft details by draft_id. Ownership-checked (see GET /api/drafts/{id})."""
    from fastapi import HTTPException
    from advisor.report_draft import resolve_report_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_report_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Report draft {draft_id!r} not found")
    return resolved[1]


_SCHEMA_CACHE: Dict[str, Dict[str, Any]] = {}


async def discover_draft_schema_internal(
    draft_id: str, egeria_credentials: Optional[Dict[str, str]] = None
) -> List[Dict[str, str]]:
    """Internal helper to dynamically retrieve the schema for a draft report specification.

    Ownership-checked via the ambient request context (advisor.request_context):
    resolves draft_id across the shared root and every namespace exactly like
    the direct REST routes do, honouring the requester's own visibility
    (own namespace + shared, or every namespace for a curator role) — a
    draft namespaced to a different user is treated as not found here too.
    """
    from advisor.report_draft import resolve_report_draft
    from advisor.report_spec_parser import register_report_spec, parse_report_spec_markdown
    from advisor.agents.report_spec_elicitor import get_report_spec_elicitor
    from advisor.report_pipeline import get_report_pipeline
    from advisor.request_context import current_user
    from pyegeria.egeria_tech_client import EgeriaTech
    import time

    _requester = current_user() or {}
    resolved = resolve_report_draft(draft_id, user_id=_requester.get("user_id"), role=_requester.get("role"))
    draft = resolved[1] if resolved else None
    if not draft:
        logger.warning(f"Draft {draft_id} not found for schema discovery")
        return []

    # Check cache first
    import copy
    current_config = copy.deepcopy({
        "action_function": draft.get("action_function"),
        "target_type": draft.get("target_type"),
        "answers": draft.get("answers")
    })
    cached = _SCHEMA_CACHE.get(draft_id)
    if cached:
        time_elapsed = time.time() - cached["timestamp"]
        if time_elapsed < 3600 and cached["draft_config"] == current_config:
            logger.info(f"Returning cached schema for draft {draft_id}")
            return cached["schema_data"]

    try:
        elicitor = get_report_spec_elicitor()
        md_content = elicitor._generate_report_spec_md(draft)
        spec = parse_report_spec_markdown(md_content)
    except Exception as exc:
        logger.warning(f"Failed to parse draft spec in schema discovery: {exc}")
        return []

    pipeline = get_report_pipeline()
    try:
        conn = pipeline._read_pyegeria_connection(egeria_credentials=egeria_credentials)
    except Exception as exc:
        logger.error(f"Failed to read Egeria connection info: {exc}")
        return []

    from advisor.report_pipeline import _conn_is_complete
    if not _conn_is_complete(conn):
        logger.warning("Egeria connection is not fully configured; skipping schema discovery")
        return []

    temp_spec_id = f"temp_schema_{draft_id}"
    register_report_spec(temp_spec_id, spec)

    try:
        client = EgeriaTech(
            view_server=conn["view_server"],
            platform_url=conn["platform_url"],
            user_id=conn["user_id"],
            user_pwd=conn["user_pwd"]
        )
        from advisor.auth import apply_token
        apply_token(client, conn.get("token"))
        
        # Speculative Discovery: query Egeria using client at depth 5
        schema_data = client.get_report_spec_schema(
            report_spec_name=temp_spec_id,
            search_string="*",
            graph_query_depth=5,
            exclude_system_properties=True
        )
        # Store in cache
        _SCHEMA_CACHE[draft_id] = {
            "timestamp": time.time(),
            "draft_config": current_config,
            "schema_data": schema_data
        }
        return schema_data
    except Exception as e:
        logger.warning(f"Live schema discovery failed on Egeria server: {e}")
        return []


@app.get("/api/reports/drafts/{draft_id}/schema")
async def get_report_draft_schema(request: Request, draft_id: str) -> List[Dict[str, str]]:
    """Return the dynamically discovered schema attributes for a report draft.

    Requires login — this performs a live Egeria read and must be
    attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    return await discover_draft_schema_internal(draft_id, egeria_credentials=egeria_credentials)


@app.delete("/api/reports/drafts/{draft_id}")
async def delete_report_draft(request: Request, draft_id: str) -> Dict[str, str]:
    """Discard an active report spec draft. Ownership-checked (see GET /api/drafts/{id})."""
    from advisor.report_draft import resolve_report_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_report_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        return {"status": "not_found"}
    dm, _spec = resolved
    deleted = dm.delete(draft_id)
    return {"status": "ok" if deleted else "not_found"}


@app.post("/api/reports/drafts/builder")
async def create_report_builder_draft(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a blank report spec draft for builder canvas entry point.
    Namespaced to the signed-in user; anonymous keeps the shared namespace."""
    from advisor.report_draft import get_report_draft_manager
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    title = (body.get("title") or "Untitled Report").strip()
    dm = get_report_draft_manager(user_id)
    spec = dm.create(
        title=title,
        original_query=f"[builder] {title}",
        action_function="GlossaryManager.find_glossaries",
        target_type="Glossary",
        columns=[
            {"name": "Display Name", "key": "displayName", "format": False, "detail_spec": None, "formats": "ALL"},
            {"name": "GUID", "key": "guid", "format": True, "detail_spec": None, "formats": "ALL"}
        ],
        answers={
            "Heading": title,
            "Description": "Report built with Report Builder"
        }
    )
    spec["phase"] = "confirm_action"
    spec["phase_label"] = "Building report"
    spec["builder_mode"] = True
    dm.save(spec)
    return spec


@app.post("/api/reports/specs/edit-by-name")
async def edit_spec_by_name(body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Given a report_name (registered spec name), find the matching inbox doc and return
    an editable draft.  Returns {found, draft_id, doc_id} — found=False means the spec
    is built-in (not in the catalog inbox) and the client should offer "Save as spec" instead.
    """
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.report_draft import get_report_draft_manager
    from advisor.report_spec_parser import parse_report_spec_markdown

    report_name = (body.get("report_name") or "").strip()
    if not report_name:
        return {"found": False}

    dm_doc = get_report_spec_doc_manager()
    dm_draft = get_report_draft_manager()

    if report_name.startswith("draft_report_"):
        draft = dm_draft.load(report_name)
        if draft:
            return {"found": True, "draft_id": report_name, "doc_id": draft.get("doc_id")}

    # Search inbox for a spec whose doc_id or title matches report_name
    inbox = dm_doc.list_inbox()
    match = None
    name_lower = report_name.lower().replace("-", " ").replace("_", " ")
    for entry in inbox:
        doc_id = entry.get("doc_id", "")
        title  = (entry.get("title") or "").lower().replace("-", " ").replace("_", " ")
        if doc_id.lower() == name_lower or title == name_lower:
            match = entry
            break

    if not match:
        # Fuzzy: check if report_name appears as a substring of doc_id or title
        for entry in inbox:
            doc_id = entry.get("doc_id", "")
            title  = (entry.get("title") or "").lower()
            if name_lower in doc_id.lower() or name_lower in title:
                match = entry
                break

    if not match:
        return {"found": False}

    doc_id = match["doc_id"]

    # Check if a draft already exists for this doc_id
    for draft in dm_draft.list_drafts():
        if draft.get("doc_id") == doc_id:
            return {"found": True, "draft_id": draft["draft_id"], "doc_id": doc_id}

    # Create a draft from the inbox spec content
    raw = dm_doc.load(doc_id)
    if not raw:
        return {"found": False}

    try:
        parsed = parse_report_spec_markdown(raw)
    except Exception:
        return {"found": False}

    title = parsed.get("heading") or doc_id
    spec = dm_draft.create(
        title=title,
        original_query=f"[edit] {doc_id}",
        action_function=parsed.get("action", {}).get("function", ""),
        target_type=parsed.get("target_type", ""),
        columns=parsed.get("columns_raw", []),
    )
    spec["doc_id"] = doc_id
    spec["phase"] = "refine"
    spec["phase_label"] = "Editing spec"
    dm_draft.save(spec)
    return {"found": True, "draft_id": spec["draft_id"], "doc_id": doc_id}


@app.post("/api/reports/specs/{doc_id}/edit")
async def edit_spec_by_id(doc_id: str) -> Dict[str, Any]:
    """Open an editable draft directly from a catalog doc_id (no name lookup needed)."""
    from advisor.report_spec_docs import get_report_spec_doc_manager
    from advisor.report_draft import get_report_draft_manager
    from advisor.report_spec_parser import parse_report_spec_markdown

    dm_doc   = get_report_spec_doc_manager()
    dm_draft = get_report_draft_manager()

    if doc_id.startswith("draft_report_"):
        draft = dm_draft.load(doc_id)
        if draft:
            return {"found": True, "draft_id": doc_id, "doc_id": draft.get("doc_id")}

    # Return existing draft if one already tracks this doc_id
    for draft in dm_draft.list_drafts():
        if draft.get("doc_id") == doc_id:
            return {"found": True, "draft_id": draft["draft_id"], "doc_id": doc_id}

    raw = dm_doc.load(doc_id)
    if not raw:
        return {"found": False, "error": f"Spec {doc_id!r} not found in catalog"}

    try:
        parsed = parse_report_spec_markdown(raw)
    except Exception as exc:
        return {"found": False, "error": str(exc)}

    columns = []
    for fmt in (parsed.formats or []):
        for col in (fmt.attributes or []):
            columns.append({
                "name": col.name,
                "key": col.key or "",
                "format": col.format if col.format is not None else False,
                "detail_spec": col.detail_spec,
                "formats": "ALL",
            })

    perspectives = []
    questions = []
    if parsed.question_spec:
        for qs in parsed.question_spec:
            perspectives.extend(getattr(qs, "perspectives", []) or [])
            questions.extend(getattr(qs, "questions", []) or [])

    spec = dm_draft.create(
        title=parsed.heading or doc_id,
        original_query=f"[edit] {doc_id}",
        action_function=(parsed.action.function if parsed.action else ""),
        target_type=parsed.target_type or "",
        columns=columns,
        perspectives=perspectives,
        questions=questions,
    )
    spec["doc_id"]  = doc_id
    spec["answers"] = {"Heading": parsed.heading, "Description": parsed.description}
    if parsed.action and parsed.action.spec_params:
        sp = parsed.action.spec_params
        spec["content_filters"]   = {k: v for k, v in sp.items()
                                      if k in ("search_string", "metadata_element_type",
                                               "metadata_element_subtypes", "starts_with",
                                               "ends_with", "ignore_case",
                                               "limit_results_by_status", "governance_zone_filter",
                                               "anchor_type_name", "anchor_domain")}
        spec["shape_defaults"]    = {k: v for k, v in sp.items()
                                      if k in ("sequencing_property", "sequencing_order",
                                               "graph_query_depth", "max_mermaid_node_count",
                                               "skip_relationships", "include_only_relationships")}
        spec["performance_hints"] = {k: v for k, v in sp.items()
                                      if k in ("page_size", "start_from",
                                               "relationship_page_size",
                                               "as_of_time", "effective_time")}
    spec["phase"]       = "refine"
    spec["phase_label"] = "Editing spec"
    dm_draft.save(spec)
    return {"found": True, "draft_id": spec["draft_id"], "doc_id": doc_id}


@app.patch("/api/reports/drafts/{draft_id}/columns")
async def patch_report_draft_columns(request: Request, draft_id: str, body: Dict[str, Any]) -> Dict[str, str]:
    """Update columns and metadata in a report draft (called by Report Canvas edits).

    Ownership-checked: resolves draft_id across the shared root and every
    namespace via resolve_report_draft() — a draft namespaced to another
    user comes back as 404 (never 403) unless the requester is a curator,
    matching every other draft/document route.
    """
    from fastapi import HTTPException
    from advisor.report_draft import resolve_report_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_report_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id!r} not found")
    dm, spec = resolved
    
    if "columns" in body:
        spec["columns"] = body["columns"]
    if "answers" in body:
        spec["answers"].update(body["answers"])
    if "action_function" in body:
        spec["action_function"] = body["action_function"]
    if "target_type" in body:
        spec["target_type"] = body["target_type"]
    if "heading" in body:
        spec.setdefault("answers", {})["Heading"] = body["heading"]
    if "perspectives" in body:
        spec["perspectives"] = body["perspectives"]
    if "questions" in body:
        spec["questions"] = body["questions"]
    if "content_filters" in body:
        spec["content_filters"] = body["content_filters"]
    if "shape_defaults" in body:
        spec["shape_defaults"] = body["shape_defaults"]
    if "performance_hints" in body:
        spec["performance_hints"] = body["performance_hints"]
    dm.save(spec)

    # Sync changes back to the generated markdown RSD file if it exists
    doc_id = spec.get("doc_id")
    if doc_id:
        try:
            from advisor.report_spec_docs import get_report_spec_doc_manager
            from advisor.agents.report_spec_elicitor import get_report_spec_elicitor
            doc_manager = get_report_spec_doc_manager()
            elicitor = get_report_spec_elicitor()
            new_content = elicitor._generate_report_spec_md(spec)
            doc_manager.update(doc_id, new_content)
            logger.info(f"Updated report spec document {doc_id} to match canvas edits")
        except Exception as exc:
            logger.error(f"Failed to update report document {doc_id} on patch: {exc}", exc_info=True)

    return {"status": "ok"}


@app.get("/api/actions")
async def list_actions() -> Dict[str, Any]:
    """Return all known Dr.Egeria commands grouped by family.

    Used by the Plan Editor command picker modal to populate the command catalog.
    Each entry: {name, family, aliases, in_catalog}
    """
    from advisor.command_keyword_index import get_command_keyword_index
    return {"families": get_command_keyword_index().all_commands()}


@app.get("/api/templates/Column/fields")
async def get_column_fields(draft_id: Optional[str] = None) -> Dict[str, Any]:
    """Return the fields configuration for a Report Column card in the canvas."""
    valid_keys = []
    if draft_id:
        try:
            schema_data = await discover_draft_schema_internal(draft_id)
            valid_keys = [item["attribute_path"] for item in schema_data if "attribute_path" in item]
        except Exception as e:
            logger.warning(f"Failed to auto-populate Column Key valid_values: {e}")

    return {
        "fields": [
            {
                "name": "Name",
                "required": True,
                "description": "Column display name (e.g. Display Name)",
                "valid_values": []
            },
            {
                "name": "Key",
                "required": True,
                "description": "Egeria attribute property key (e.g. display_name)",
                "valid_values": valid_keys
            },
            {
                "name": "Apply formatting",
                "required": False,
                "description": "How to style this column's value (leave blank for plain text)",
                "valid_values": ["", "bulleted-list", "code", "date", "True"]
            },
            {
                "name": "Detail Spec",
                "required": False,
                "description": "Associated detail spec name for nested/drill-down reporting",
                "valid_values": []
            },
            {
                "name": "Output types",
                "required": False,
                "description": "Which output modes include this column",
                "valid_values": ["ALL", "REPORT", "LIST", "TABLE", "MERMAID", "DICT", "FORM", "JSON"],
                "multi_select": True
            }
        ]
    }


@app.get("/api/egeria/zones")
async def get_governance_zones(request: Request) -> Dict[str, Any]:
    """Return all governance zone names from the live Egeria instance.

    Requires login — this performs a live Egeria read and must be
    attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    try:
        from advisor.egeria_context import EgeriaContext
        zones = EgeriaContext(egeria_credentials=egeria_credentials).list_governance_zones()
        return {"zones": zones, "count": len(zones)}
    except Exception as exc:
        return {"zones": [], "count": 0, "error": str(exc)}


@app.get("/api/perspectives")
async def list_perspectives() -> Dict[str, Any]:
    """Return available perspectives (live from Egeria or CSV fallback)."""
    from advisor.perspective_manager import get_all
    return {"perspectives": get_all()}

