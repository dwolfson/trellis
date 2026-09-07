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
from typing import Any, Dict, List

from fastapi import FastAPI, Request
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

from advisor.web.reports import router as _reports_router
app.include_router(_reports_router)

# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


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


@app.get("/api/actions")
async def list_actions() -> Dict[str, Any]:
    """Return all known Dr.Egeria commands grouped by family.

    Used by the Plan Editor command picker modal to populate the command catalog.
    Each entry: {name, family, aliases, in_catalog}
    """
    from advisor.command_keyword_index import get_command_keyword_index
    return {"families": get_command_keyword_index().all_commands()}


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

