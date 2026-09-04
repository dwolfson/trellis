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

import asyncio
import json
import re
from functools import partial
from pathlib import Path
from typing import Any, Dict, List, Optional

from datetime import datetime

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel

def _extended_feedback_path() -> Path:
    """Path to the extended-feedback JSONL log, under the resolved writable
    advisor data root (ADVISOR_DATA_PATH) rather than a bare relative
    ``data/`` path — see advisor.config.resolve_advisor_data_root()."""
    from advisor.config import resolve_advisor_data_root
    return resolve_advisor_data_root() / "feedback" / "feedback_extended.jsonl"


_STATIC = Path(__file__).parent / "static"
_SPEC_FILES = [
    Path(__file__).parent.parent / "configdata" / "report_specs" / "plain_spec_question_specs_batch1.json",
    Path(__file__).parent.parent / "configdata" / "report_specs" / "report_specs_annotated.json",
]

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

# ── lazy RAG system ────────────────────────────────────────────────────────────

_rag = None


def _get_rag():
    global _rag
    if _rag is None:
        from advisor.rag_system import get_rag_system
        _rag = get_rag_system()
    return _rag


@app.on_event("startup")
async def _startup():
    """Ensure pgvector collection tables exist, then pre-warm the MCP agent
    in the background so the first report click is fast."""
    import asyncio
    import threading

    try:
        from advisor.vector_store_pg import PgVectorStore
        PgVectorStore().provision_schema()
    except Exception as exc:
        logger.warning(f"pgvector schema provisioning failed (queries needing missing collections will error): {exc}")

    def _warm():
        try:
            from advisor.report_pipeline import get_report_pipeline
            get_report_pipeline()._ensure_agent()
            logger.info("MCP agent pre-warmed on startup")
        except Exception as exc:
            logger.warning(f"MCP pre-warm failed (reports will initialize on first use): {exc}")

    threading.Thread(target=_warm, daemon=True).start()


@app.on_event("shutdown")
async def _shutdown():
    """
    Terminate the MCP agent's subprocess(es) so they don't outlive this
    process. Without this, every uvicorn --reload restart during development
    orphans the MCP server subprocess instead of killing it — confirmed live
    2026-07-10: ~50 orphaned mcp_server.py processes had accumulated over two
    weeks of iterative development, one per reload, with no shutdown handler
    ever calling shutdown_mcp_agent() to reap them.
    """
    try:
        from advisor.mcp_agent import shutdown_mcp_agent
        await shutdown_mcp_agent()
        logger.info("MCP agent shut down cleanly")
    except Exception as exc:
        logger.warning(f"MCP agent shutdown failed: {exc}")


# ── request / response models ──────────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str
    session_id: Optional[str] = None
    output_format: Optional[str] = None    # "LIST"|"TABLE"|"MERMAID"|"MD"|"JSON"|"DICT" — overrides auto-detect
    intent_override: Optional[str] = None  # "explanation" | "code_search" | "report" | "command" | "debugging"
    search_string: Optional[str] = None    # filter string for report queries (default "*")
    perspective: Optional[str] = None      # user role: "developer" | "data_engineer" | "data_steward" | "governance_officer"
    page_size: Optional[int] = None        # max graph nodes per report query (None → advisor.yaml default)
    draft_id: Optional[str] = None         # active planning session draft ID
    context: Optional[Dict[str, Any]] = None  # authoritative conversation context {task, draft_id, phase, ...}


class FeedbackRequest(BaseModel):
    query: str
    query_type: str
    vote: int                           # 1 = positive, 0 = neutral/partially correct, -1 = negative
    perspective: Optional[str] = None
    routing_agent: Optional[str] = None
    response_text: Optional[str] = None   # actual response shown to user
    intent_override: Optional[str] = None  # intent selector value from UI ("auto", "explain", etc.)


# ── intent → badge metadata ────────────────────────────────────────────────────

_INTENT_META: Dict[str, Dict[str, str]] = {
    "report":       {"label": "Report",      "color": "#f97316"},
    "command":      {"label": "Act",         "color": "#a855f7"},
    "explanation":  {"label": "Explain",     "color": "#3b82f6"},
    "comparison":   {"label": "Explain",     "color": "#3b82f6"},
    "best_practice":{"label": "Explain",     "color": "#3b82f6"},
    "code_search":  {"label": "Show me",     "color": "#10b981"},
    "example":      {"label": "Show me",     "color": "#10b981"},
    "relationship": {"label": "Reference",   "color": "#14b8a6"},
    "debugging":    {"label": "Troubleshoot","color": "#eab308"},
    "quantitative": {"label": "Reference",   "color": "#14b8a6"},
    "clarification":{"label": "Clarify",     "color": "#f59e0b"},
    "plan":              {"label": "Plan",        "color": "#8b5cf6"},
    "act_report_result": {"label": "Act",         "color": "#a855f7"},
    "create":            {"label": "Create",      "color": "#8b5cf6"},
    "create_disambiguation": {"label": "Create",  "color": "#8b5cf6"},
    "plan_clarification":{"label": "Planning",    "color": "#a78bfa"},
    "plan_executed":     {"label": "Executed",    "color": "#22c55e"},
    "general":      {"label": "Explain",     "color": "#3b82f6"},
    "code_intel":   {"label": "Inspect", "color": "#ec4899"},
    "code_help":    {"label": "Show me",     "color": "#10b981"},
}


def _intent_meta(query_type: str) -> Dict[str, str]:
    return _INTENT_META.get(query_type, {"label": query_type.title(), "color": "#64748b"})


# ── report catalog helpers ─────────────────────────────────────────────────────

_TOPIC_PATTERNS: List[tuple] = [
    (re.compile(r"glossar", re.I),           "Glossary"),
    (re.compile(r"collection|folder|namespace|results.set", re.I), "Collections"),
    (re.compile(r"governance.zone|governance.basics|governance.def|governance.polic|governance.control|governance.process", re.I), "Governance"),
    (re.compile(r"data.dict|data.spec|data.struct|data.field|data.class|data.grain|data.value|data.lens", re.I), "Data Structures"),
    (re.compile(r"digital.product|digital.subscript|digital.catalog", re.I), "Digital Products"),
    (re.compile(r"agreement|license|terms.and|regulation|certification", re.I), "Agreements & Compliance"),
    (re.compile(r"project|campaign|task", re.I),  "Projects"),
    (re.compile(r"actor|org.chart|user|team|my.user", re.I), "People & Organisations"),
    (re.compile(r"asset|tech.type|catalog.target", re.I), "Assets"),
    (re.compile(r"solution|information.supply|blueprint", re.I), "Solution Architecture"),
    (re.compile(r"external|related.media|cited", re.I), "External References"),
    (re.compile(r"comment|tag|rating|like", re.I), "Collaboration"),
    (re.compile(r"security|threat|access.control", re.I), "Security"),
]

_DEFAULT_TOPIC = "General"


def _topic_for(name: str) -> str:
    for pat, topic in _TOPIC_PATTERNS:
        if pat.search(name):
            return topic
    return _DEFAULT_TOPIC


def _is_dre(name: str) -> bool:
    return "-dre-" in name.lower()


# Canonical, ordered set of browser-renderable output formats. `value` is the
# token sent to pyegeria (via the fmt:'<value>' query tag); `label` is shown in
# the picker. A spec's declared `formats[].types` are intersected with this set
# (and `ALL` expands to all of it) to build a spec-aware dropdown.
_BROWSER_FORMATS: List[tuple] = [
    ("LIST",    "List — compact Markdown table"),
    ("TABLE",   "Table — structured data table"),
    ("REPORT",  "Report — full narrative (Mermaid, graphs)"),
    ("FORM",    "Form — Dr.Egeria editable form"),
    ("MERMAID", "Diagram — Mermaid graph"),
    ("HTML",    "HTML — rendered page"),
    ("MD",      "Markdown — simple"),
    ("DICT",    "Dict — materialized properties"),
    ("JSON",    "JSON — raw Egeria response"),
]
_BROWSER_FORMAT_VALUES = [v for v, _ in _BROWSER_FORMATS]


def _spec_supported_formats(name: str) -> List[str]:
    """Return the browser-renderable output formats a spec supports, in canonical
    order. Reads the in-process pyegeria registry; `ALL` expands to every browser
    format. Falls back to a safe default if the spec/registry is unavailable."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        fs = get_report_registry().get(name)
        if fs is None:
            return list(_BROWSER_FORMAT_VALUES)
        declared = {
            t.upper()
            for fmt in (getattr(fs, "formats", []) or [])
            for t in (getattr(fmt, "types", []) or [])
        }
        if "ALL" in declared:
            return list(_BROWSER_FORMAT_VALUES)
        supported = [v for v in _BROWSER_FORMAT_VALUES if v in declared]
        # Always offer at least DICT so the report is runnable from the picker.
        return supported or ["DICT"]
    except Exception as exc:
        logger.debug(f"_spec_supported_formats({name}) failed: {exc}")
        return list(_BROWSER_FORMAT_VALUES)


def _catalog_formats(catalog: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """Build {spec_name: [supported formats]} for every spec in the catalog."""
    formats: Dict[str, List[str]] = {}
    for names in catalog.values():
        for name in names:
            formats[name] = _spec_supported_formats(name)
    return formats


def _is_runnable_spec(name: str) -> bool:
    """Return True if the spec has an action (can be executed standalone)."""
    try:
        from pyegeria.view.base_report_formats import get_report_registry
        spec = get_report_registry().get(name)
        if spec is None:
            return True  # unknown to registry — assume runnable, let executor decide
        return getattr(spec, "action", None) is not None
    except Exception:
        return True  # registry unavailable — assume runnable


def _load_report_catalog(include_dre: bool = False) -> Dict[str, List[str]]:
    """Return {topic: [spec_name, ...]}, runnable specs only.

    Primary source is pyegeria's own in-process report registry
    (get_report_registry(), which already combines built-ins, generated,
    config-loaded, and runtime-registered specs) — report specs are not all
    produced by the dr-egeria-command-sync JSON pipeline, so the catalog must
    not be JSON-file-only. The bundled JSON files below still supplement this
    for any name the registry doesn't (yet) know about, and are read fresh on
    every call, so a live-updated JSON file needs no server restart either.
    """
    catalog: Dict[str, List[str]] = {}
    seen: set = set()

    def _add(name: str) -> None:
        if name in seen:
            return
        seen.add(name)
        if not include_dre and _is_dre(name):
            return
        if not _is_runnable_spec(name):
            return
        topic = _topic_for(name)
        catalog.setdefault(topic, []).append(name)

    try:
        from pyegeria.view.base_report_formats import get_report_registry
        for name in get_report_registry().keys():
            _add(name)
    except Exception as exc:
        logger.debug(f"_load_report_catalog: pyegeria registry unavailable — {exc}")

    for path in _SPEC_FILES:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text())
            for name in data:
                _add(name)
        except Exception as exc:
            logger.warning(f"Failed to load {path}: {exc}")

    # Sort within each topic
    for topic in catalog:
        catalog[topic].sort()
    return dict(sorted(catalog.items()))


# ── routes ─────────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


# ── Auth endpoints ─────────────────────────────────────────────────────────────

class LoginRequest(BaseModel):
    username: str
    password: str


class PortalTokenRequest(BaseModel):
    portal_token: str


@app.post("/api/auth/login")
async def auth_login(req: LoginRequest) -> Dict[str, Any]:
    """Exchange Egeria credentials for a session JWT.

    The password is used exactly once, here, to obtain an Egeria bearer token;
    it is never stored and never signed into the JWT (contract change
    2026-09-04 — see advisor/auth.py and docs/runtime-architecture-plan.md §4).
    """
    from advisor.auth import login_with_password, create_access_token
    if not req.username or not req.password:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="username and password required")
    egeria_token = await asyncio.get_event_loop().run_in_executor(
        None, login_with_password, req.username, req.password
    )
    if not egeria_token:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Invalid credentials or Egeria is unreachable.")
    token = create_access_token(user_id=req.username, egeria_token=egeria_token)
    return {"access_token": token, "token_type": "bearer", "egeria_user": req.username}


@app.post("/api/auth/portal")
async def auth_portal(req: PortalTokenRequest) -> Dict[str, Any]:
    """Exchange a Portal-issued short-lived token for a local session JWT.

    The Portal has already logged the user into Egeria and its JWT carries the
    resulting bearer token: {sub, role, display_name, egeria_token, exp}. We
    validate that under the shared secret and re-sign it as our own session —
    no Egeria round-trip on this path beyond the optional cheap validation
    below, and no password anywhere.
    """
    from advisor.auth import exchange_portal_token, create_access_token, validate_egeria_token
    payload = exchange_portal_token(req.portal_token)
    egeria_user = payload.get("sub", "")
    egeria_token = payload.get("egeria_token", "")

    # Optional liveness check: the token was minted by someone else, so confirm
    # it still works before wrapping a session around it. Deliberately NOT a
    # gate — a briefly unreachable Egeria degrades SSO to "signed in, live
    # features will fail on use", which is what a self-minted token does too.
    ok = await asyncio.get_event_loop().run_in_executor(
        None, validate_egeria_token, egeria_token
    )
    if not ok:
        logger.warning(
            f"auth: Portal token for {egeria_user!r} did not validate against Egeria; "
            "issuing the session anyway (live calls may 401)"
        )

    token = create_access_token(
        user_id=egeria_user,
        egeria_token=egeria_token,
        role=payload.get("role", "user"),
        display_name=payload.get("display_name") or egeria_user,
    )
    return {"access_token": token, "token_type": "bearer", "egeria_user": egeria_user}


@app.get("/api/auth/me")
async def auth_me(request: Request) -> Dict[str, Any]:
    """Return info about the currently authenticated user."""
    from advisor.auth import get_current_user
    user = get_current_user(request)
    if user is None:
        return {"authenticated": False}
    user_id = user.get("user_id") or user.get("sub", "")
    return {
        "authenticated": True,
        "user_id": user_id,
        # `egeria_user` kept as a response key for the existing UI; since
        # 2026-09-04 the JWT identifies the user by `sub`/`user_id` and carries
        # their Egeria bearer token rather than a separate egeria_user/password
        # pair, so the two are the same identity.
        "egeria_user": user_id,
        "role": user.get("role", "user"),
        "display_name": user.get("display_name") or user_id,
    }


@app.post("/api/auth/logout")
async def auth_logout() -> Dict[str, str]:
    """Client-side logout — server has no session state to clear."""
    return {"status": "ok"}


@app.get("/api/auth/defaults")
async def auth_defaults() -> Dict[str, Any]:
    """Return the configured default Egeria username, for login-form prefill
    convenience on this local, single-user tool. Deliberately does NOT return
    the password — this is an unauthenticated endpoint, and returning a
    plaintext password from it would let anyone who can reach the server
    retrieve it before ever logging in."""
    from advisor.config import settings
    return {"username": settings.egeria_user}


@app.get("/api/auth/policy")
async def auth_policy() -> Dict[str, Any]:
    """The active login policy, so the SPA can decide how to present the form.

    Public, deliberately: the browser needs this *before* it holds a token, and
    it discloses nothing an unauthenticated caller cannot already learn by
    making one request and reading the 401. With `login_required` true the SPA
    shows a non-dismissible login overlay instead of starting up into a page
    whose every panel is a failed fetch.
    """
    from advisor.auth import get_policy
    policy = get_policy()
    return {
        "login_required": policy.require_login and not policy.anonymous_read,
        "anonymous_read": policy.anonymous_read,
    }


@app.post("/api/query")
async def query_endpoint(request: Request, req: QueryRequest) -> Dict[str, Any]:
    """Process a natural-language query and return the response dict."""
    from advisor.auth import get_current_user, get_egeria_credentials
    current_user = get_current_user(request)
    egeria_authenticated = current_user is not None
    egeria_credentials = get_egeria_credentials(request)

    user_query = req.query.strip()
    # Append search filter tag so the report pipeline can extract it
    if req.search_string and req.search_string.strip() not in ("", "*"):
        user_query += f" filter:'{req.search_string.strip()}'"
    # Append output format tag when explicitly set (e.g. from the report modal dropdown)
    if req.output_format:
        user_query += f" fmt:'{req.output_format.strip()}'"

    try:
        rag = _get_rag()
        # Run the blocking RAG query in a thread-pool executor so FastAPI's
        # event loop is not blocked during MCP / LLM calls.  Inside the
        # executor thread, asyncio.get_event_loop().is_running() is False, so
        # _run_async() inside the pipeline uses asyncio.run() directly —
        # cleaner than the nested-thread approach used when called on-loop.
        loop = asyncio.get_event_loop()
        user_id = current_user.get("sub") if current_user else None
        result = await loop.run_in_executor(
            None,
            partial(
                rag.query,
                user_query=user_query,
                include_context=True,
                track_metrics=True,
                query_type_override=req.intent_override or None,
                perspective=req.perspective or None,
                page_size=req.page_size or None,
                draft_id=req.draft_id or None,
                context=req.context or None,
                egeria_authenticated=egeria_authenticated,
                session_id=req.session_id or None,
                user_id=user_id,
                egeria_credentials=egeria_credentials,
            ),
        )
    except Exception as exc:
        logger.error(f"Query failed: {exc}")
        result = {
            "query": req.query,
            "response": f"Sorry, an error occurred: {exc}",
            "query_type": "general",
            "routing_agent": "error",
            "sources": [],
            "num_sources": 0,
            "retrieval_time": 0.0,
            "generation_time": 0.0,
            "avg_relevance_score": 0.0,
            "context_length": 0,
        }

    query_type = result.get("query_type", "general")
    result["intent"] = _intent_meta(query_type)
    return result


@app.post("/api/query/stream")
async def query_stream_endpoint(request: Request, req: QueryRequest) -> StreamingResponse:
    """
    Streaming variant of /api/query — returns Server-Sent Events.

    Event sequence:
      data: {"type":"start","query":"..."}
      data: {"type":"token","text":"..."}   (repeated, only for LLM-generation paths)
      data: {"type":"done","result":{...}}
      data: [DONE]
    """
    from advisor.auth import get_current_user, get_egeria_credentials
    current_user = get_current_user(request)
    egeria_authenticated = current_user is not None
    egeria_credentials = get_egeria_credentials(request)

    user_query = req.query.strip()
    if req.search_string and req.search_string.strip() not in ("", "*"):
        user_query += f" filter:'{req.search_string.strip()}'"
    if req.output_format:
        user_query += f" fmt:'{req.output_format.strip()}'"

    loop = asyncio.get_event_loop()
    rag  = _get_rag()

    async def event_gen():
        # Bridge sync generator → async generator via asyncio.Queue so the
        # event loop stays unblocked while the worker thread produces tokens.
        q: asyncio.Queue[Optional[str]] = asyncio.Queue(maxsize=256)

        user_id = current_user.get("sub") if current_user else None
        def producer() -> None:
            try:
                for chunk in rag.query_stream(
                    user_query=user_query,
                    include_context=True,
                    query_type_override=req.intent_override or None,
                    perspective=req.perspective or None,
                    page_size=req.page_size or None,
                    draft_id=req.draft_id or None,
                    context=req.context or None,
                    egeria_authenticated=egeria_authenticated,
                    session_id=req.session_id or None,
                    user_id=user_id,
                    egeria_credentials=egeria_credentials,
                ):
                    loop.call_soon_threadsafe(q.put_nowait, chunk)
            except Exception as exc:
                logger.error(f"query_stream producer error: {exc}", exc_info=True)
                err = json.dumps({"type": "error", "message": str(exc)})
                loop.call_soon_threadsafe(q.put_nowait, f"data: {err}\n\n")
            finally:
                loop.call_soon_threadsafe(q.put_nowait, None)  # sentinel

        import concurrent.futures
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        future = loop.run_in_executor(executor, producer)

        while True:
            item = await q.get()
            if item is None:
                break
            yield item

        await future
        executor.shutdown(wait=False)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering
        },
    )


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


@app.post("/api/plans/import")
async def import_plan(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Import an externally-written Dr.Egeria/LGCI markdown document as a new
    managed plan in inbox. Detects whether the content is already LGCI-structured
    or a bare Dr.Egeria command file and wraps the latter automatically.

    Written into the signed-in user's namespace (docs/runtime-architecture-plan.md
    §4); an anonymous request keeps today's shared namespace.
    """
    from advisor.governance_docs import get_doc_manager
    from advisor.auth import get_current_user
    from fastapi import HTTPException
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    title = (body.get("title") or "").strip() or None
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    dm = get_doc_manager()
    try:
        doc_id = dm.import_document(content, title=title, user_id=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"status": "ok", "doc_id": doc_id, "folder": "inbox"}


@app.get("/api/plans")
async def list_plans(request: Request) -> Dict[str, Any]:
    """Return inbox, outbox, and trash plan document lists, annotated with active draft IDs.

    A signed-in user sees the shared namespace plus their own; a curator
    role (admin/curator) sees every namespace. Anonymous sees shared only.
    """
    from advisor.governance_docs import get_doc_manager
    from advisor.governance_draft import list_visible_drafts
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_doc_manager()
    inbox = dm.list_inbox(requester_user_id=user_id, requester_role=role)
    outbox = dm.list_outbox(requester_user_id=user_id, requester_role=role)
    trash = dm.list_trash(requester_user_id=user_id, requester_role=role)

    # Build doc_id → draft_id map for plans that have an active refine/generate draft
    doc_to_draft: Dict[str, str] = {}
    for d in list_visible_drafts(user_id=user_id, role=role):
        if d.get("doc_id") and d.get("phase") in ("generate", "refine", "template_offer"):
            doc_to_draft[d["doc_id"]] = d["draft_id"]

    for entry in inbox:
        entry["draft_id"] = doc_to_draft.get(entry.get("doc_id"))

    return {"inbox": inbox, "outbox": outbox, "trash": trash}


@app.get("/api/plans/{doc_id}")
async def get_plan(request: Request, doc_id: str) -> Dict[str, Any]:
    """Return the content of a plan document by doc_id (inbox, outbox, or trash).

    Ownership-checked: a namespaced plan belonging to another user comes
    back as 404 (never 403) unless the requester is a curator.
    """
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_doc_manager()
    content = dm.load(doc_id, include_trash=True, requester_user_id=user_id,
                       requester_role=role, enforce_ownership=True)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    folder = dm.folder_of(doc_id) or "outbox"
    return {"doc_id": doc_id, "content": content, "folder": folder}


@app.get("/api/plans/{doc_id}/export")
async def export_plan(doc_id: str) -> Response:
    """Download the full current content of a plan document (inbox or outbox)."""
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    content = dm.load(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    return Response(
        content=content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}.md"'},
    )


@app.get("/api/plans/{doc_id}/report-export")
async def export_plan_report(doc_id: str) -> Response:
    """
    Download just the report content (Mermaid diagrams, result tables) extracted
    from an executed plan's Dr.Egeria output — shareable independent of the plan
    that produced it.
    """
    from fastapi import HTTPException
    from advisor.governance_docs import get_doc_manager, DocumentManager
    from advisor.agents.outcome_reporter import _extract_report_sections

    dm = get_doc_manager()
    content = dm.load_outbox(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found in outbox")

    # The raw Dr.Egeria output lives inside the collapsible "## Dr.Egeria Execution
    # Output" section appended by GovernancePlanAgent.execute() — pull it out.
    m = re.search(
        r'<summary>.*?</summary>\n\n(.*?)\n\n</details>',
        content, re.DOTALL,
    )
    raw_output = m.group(1) if m else content
    report_md = _extract_report_sections(raw_output)
    if not report_md:
        raise HTTPException(
            status_code=404,
            detail="No extractable report content (Mermaid diagram or result table) found in this plan's output",
        )

    title = DocumentManager._extract_title(content)
    final = (
        f"# {title} — Report\n\n"
        f"*Generated from plan `{doc_id}` on {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
        f"{report_md}\n"
    )
    return Response(
        content=final,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="{doc_id}_report.md"'},
    )


@app.put("/api/plans/{doc_id}")
async def save_plan(request: Request, doc_id: str, body: Dict[str, Any]) -> Dict[str, str]:
    """Save updated plan content to inbox (with automatic version backup)."""
    from fastapi import HTTPException
    from advisor.auth import get_current_user
    from advisor.governance_docs import get_doc_manager
    content = body.get("content", "")
    if not content:
        raise HTTPException(status_code=400, detail="content required")
    user = get_current_user(request)
    edited_by = (user or {}).get("sub")
    dm = get_doc_manager()
    ok = dm.update(doc_id, content, edited_by=edited_by)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found in inbox")
    return {"status": "ok"}


@app.post("/api/plans/{doc_id}/execute")
async def execute_plan(request: Request, doc_id: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Execute an inbox plan directly (first execution). Direct REST call —
    deliberately not routed through chat text — since "execute the plan X"
    sent as a chat message can be intercepted by context-based routing
    (e.g. an open Plan Canvas session) and mistakenly treated as a plan-
    modification instruction instead of an execute command. See BACKLOG.md.
    For outbox (already-executed) plans, use retry/rerun instead.

    Optional body.draft_id: if this plan originated from a draft, its doc_id
    gets updated to the new outbox id after execution — otherwise a later
    "resume draft" hands back a doc_id that no longer exists anywhere.

    Requires login — this performs live writes against Egeria and must be
    attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    draft_id = (body or {}).get("draft_id") or None
    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(agent.execute, doc_id, draft_id=draft_id, egeria_credentials=egeria_credentials)
    )
    return result


@app.post("/api/plans/{doc_id}/validate")
async def validate_plan(request: Request, doc_id: str) -> Dict[str, Any]:
    """Run Dr.Egeria validate directive on the plan's command section.

    Requires login — see execute_plan.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(agent.validate, doc_id, egeria_credentials=egeria_credentials)
    )
    return result


@app.post("/api/plans/{doc_id}/retry")
async def retry_plan(request: Request, doc_id: str) -> Dict[str, Any]:
    """Move a failed outbox plan back to inbox and re-execute it immediately.

    Requires login — see execute_plan.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, partial(agent.retry, doc_id, egeria_credentials=egeria_credentials)
    )
    return result


@app.post("/api/plans/{doc_id}/rerun")
async def rerun_plan(request: Request, doc_id: str) -> Dict[str, Any]:
    """
    Re-execute an outbox plan directly, in place — no inbox detour.
    Appends a new "## Outcome (Run N)" section to the same outbox document.

    Requires login — see execute_plan.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from advisor.agents.governance_plan_agent import get_governance_plan_agent
    agent = get_governance_plan_agent()
    result = await asyncio.get_event_loop().run_in_executor(
        None, lambda: agent.execute(doc_id, source_folder="outbox", egeria_credentials=egeria_credentials)
    )
    return result


@app.post("/api/plans/{doc_id}/recover")
async def recover_plan(doc_id: str) -> Dict[str, Any]:
    """Move an outbox plan back to inbox for editing (does NOT re-execute)."""
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    inbox_doc_id = dm.move_to_inbox(doc_id)
    if not inbox_doc_id:
        from fastapi import HTTPException
        raise HTTPException(status_code=409, detail=f"Could not recover {doc_id!r} — it may not be in the outbox, or inbox already has a copy.")
    return {"status": "ok", "doc_id": inbox_doc_id, "folder": "inbox"}


@app.get("/api/plans/{doc_id}/versions")
async def list_plan_versions(doc_id: str) -> Dict[str, Any]:
    """List available versions for a plan document."""
    from advisor.governance_docs import get_doc_manager
    dm = get_doc_manager()
    versions = dm.list_versions(doc_id)
    return {"doc_id": doc_id, "versions": versions}


@app.post("/api/plans/{doc_id}/versions/{version_file:path}/restore")
async def restore_plan_version(doc_id: str, version_file: str) -> Dict[str, Any]:
    """Restore a specific version of a plan to inbox."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.restore_version(doc_id, version_file)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Version {version_file!r} not found")
    return {"status": "ok", "doc_id": doc_id, "restored_from": version_file}


@app.post("/api/plans/{doc_id}/fork")
async def fork_plan(doc_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Create a new, independent plan seeded from doc_id (or a specific version
    of it). Known objects (Qualified Name + GUID) from the source's Command
    Results table are carried forward as a reference appendix.
    """
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    version_file = body.get("version_file") or None
    dm = get_doc_manager()
    try:
        new_doc_id = dm.fork(doc_id, title, version_file=version_file)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "doc_id": new_doc_id, "forked_from": doc_id}


@app.post("/api/plans/{doc_id}/save-as")
async def save_plan_as(doc_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save doc_id's current content (or a specific prior version) as a new,
    independent plan — the specification only, no history (unlike fork,
    which carries forward a Known Objects appendix and lineage note).
    """
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    title = (body.get("title") or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="title required")
    version_file = body.get("version_file") or None
    dm = get_doc_manager()
    try:
        new_doc_id = dm.save_as(doc_id, title, version_file=version_file)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"status": "ok", "doc_id": new_doc_id}


@app.post("/api/plans/{doc_id}/save-as-template")
async def save_plan_as_template(doc_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save any existing plan document (inbox or outbox) as a named, reusable
    template — a starting point for new plans, not itself executable.
    Outcome/execution history is stripped first.
    """
    from advisor.governance_docs import get_doc_manager, strip_outcome_sections
    from advisor.plan_templates import get_template_manager
    from fastapi import HTTPException
    name = (body.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name required")
    dm = get_doc_manager()
    content = dm.load(doc_id, include_trash=True)
    if not content:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    content = strip_outcome_sections(content)
    stem = get_template_manager().save(name, content)
    return {"status": "ok", "template": stem}


@app.delete("/api/plans/{doc_id}")
async def delete_plan(request: Request, doc_id: str) -> Dict[str, Any]:
    """Move a plan document from inbox or outbox to trash (saves a version first). Reversible.

    Ownership-checked: 404 (not 403) for a namespaced plan that isn't the
    requester's own, unless the requester is a curator.
    """
    from advisor.governance_docs import get_doc_manager
    from advisor.auth import get_current_user
    from fastapi import HTTPException
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    dm = get_doc_manager()
    visible = dm.load(doc_id, requester_user_id=user_id, requester_role=role, enforce_ownership=True)
    if visible is None:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    ok = dm.delete(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not found")
    return {"status": "trashed", "doc_id": doc_id}


@app.post("/api/plans/{doc_id}/restore-trash")
async def restore_plan_from_trash(doc_id: str) -> Dict[str, Any]:
    """Restore a plan document from trash back to inbox."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.restore_from_trash(doc_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Plan {doc_id!r} not in trash, or already exists in inbox",
        )
    return {"status": "restored", "doc_id": doc_id}


@app.delete("/api/plans/{doc_id}/purge")
async def purge_plan(doc_id: str) -> Dict[str, Any]:
    """Permanently delete a plan document from trash. Version history is preserved."""
    from advisor.governance_docs import get_doc_manager
    from fastapi import HTTPException
    dm = get_doc_manager()
    ok = dm.purge(doc_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"Plan {doc_id!r} not in trash")
    return {"status": "purged", "doc_id": doc_id}


@app.get("/api/drafts")
async def list_drafts(request: Request) -> Dict[str, Any]:
    """Return active planning session drafts visible to the requester:
    shared + their own namespace, or every namespace for a curator role."""
    from advisor.governance_draft import list_visible_drafts
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    return {"drafts": list_visible_drafts(user_id=user_id, role=role)}


@app.get("/api/drafts/{draft_id}")
async def get_draft(request: Request, draft_id: str) -> Dict[str, Any]:
    """Return a single draft spec by ID (for the Plan Canvas).

    Self-heals doc_id via resolve_live_doc_id() before returning — every
    frontend consumer of this endpoint (Plan Canvas's open(), the Active
    Drafts sidebar) gets a repaired pointer automatically, with no
    frontend-side staleness handling required.

    Ownership-checked: 404 (not 403) for a draft in another user's
    namespace, unless the requester is a curator.
    """
    from fastapi import HTTPException
    from advisor.governance_draft import resolve_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id!r} not found")
    dm, spec = resolved
    resolved_doc_id = dm.resolve_live_doc_id(draft_id, spec=spec)
    if resolved_doc_id != spec.get("doc_id"):
        spec["doc_id"] = resolved_doc_id
    return spec


@app.patch("/api/drafts/{draft_id}/commands")
async def patch_draft_commands(request: Request, draft_id: str, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update commands and answers in a draft (called by Plan Canvas on reorder/add/remove/edit).

    Runs the edited command list through validate_commands() with resort=False —
    warnings (dedup, superseded removal, missing-container insertion, etc.) are
    returned to the caller instead of being silently dropped. resort=False is
    required here specifically: this endpoint fires on every drag-reorder, and
    re-sorting by priority would silently undo a manual reorder.

    Ownership-checked like GET /api/drafts/{draft_id} above.
    """
    from fastapi import HTTPException
    from advisor.auth import get_current_user
    from advisor.governance_draft import resolve_draft
    from advisor.plan_validator import validate_commands
    user = get_current_user(request)
    edited_by = (user or {}).get("sub")
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        raise HTTPException(status_code=404, detail=f"Draft {draft_id!r} not found")
    dm, spec = resolved
    warnings: List[str] = []
    if "commands" in body:
        fixed_commands, spec["answers"], warnings = validate_commands(
            body["commands"], spec.get("answers", {}), resort=False
        )
        spec["commands_identified"] = fixed_commands
    if "answers" in body:
        spec["answers"] = body["answers"]
    dm.save(spec)

    # Sync edits to the generated markdown plan document if it exists.
    # resolve_live_doc_id self-heals a stale doc_id (e.g. after an execution
    # renamed the file) — without it, doc_manager.load() below would silently
    # return None and this whole sync would no-op, saving the draft's JSON
    # but never reaching the actual document, with no error surfaced anywhere.
    doc_id = dm.resolve_live_doc_id(draft_id, spec=spec)
    if doc_id:
        try:
            from advisor.governance_docs import get_doc_manager
            from advisor.agents.plan_elicitor import get_plan_elicitor

            doc_manager = get_doc_manager()
            current_content = doc_manager.load(doc_id)
            if current_content:
                # Update answers from commands_identified pre_filled to ensure they match canvas edits
                for cmd in spec["commands_identified"]:
                    answers_key = cmd.get("_answers_key") or cmd["action"]
                    if "pre_filled" in cmd:
                        spec.setdefault("answers", {})[answers_key] = dict(cmd["pre_filled"])

                elicitor = get_plan_elicitor()
                new_content = elicitor._rebuild_command_sequence(spec, current_content)
                synced_doc_id = dm.sync_document(draft_id, spec, new_content, edited_by=edited_by)
                if synced_doc_id:
                    logger.info(f"Regenerated and updated plan document {synced_doc_id} to match canvas edits")
                else:
                    logger.warning(f"Could not sync plan document for draft {draft_id!r} — doc_id unresolved")
            else:
                logger.warning(
                    f"Plan document {doc_id!r} for draft {draft_id!r} could not be loaded "
                    f"even after doc_id resolution — canvas edits were saved to the draft "
                    f"only, not the document."
                )
        except Exception as exc:
            logger.error(f"Failed to update plan document {doc_id} on patch: {exc}", exc_info=True)

    response: Dict[str, Any] = {"status": "ok"}
    if warnings:
        response["warnings"] = warnings
        response["commands"] = spec["commands_identified"]
    return response


@app.delete("/api/drafts/{draft_id}")
async def delete_draft(request: Request, draft_id: str) -> Dict[str, str]:
    """Discard a planning session draft. Ownership-checked (see GET above)."""
    from advisor.governance_draft import resolve_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    role = (user or {}).get("role")
    resolved = resolve_draft(draft_id, user_id=user_id, role=role)
    if resolved is None:
        return {"status": "not_found"}
    dm, _spec = resolved
    deleted = dm.delete(draft_id)
    return {"status": "ok" if deleted else "not_found"}


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


@app.post("/api/drafts/builder")
async def create_builder_draft(request: Request, body: Dict[str, Any]) -> Dict[str, Any]:
    """Create a new blank draft in builder mode (Plan Editor entry point).

    Body: {title: str, perspective?: str}
    Returns the draft spec with builder_mode=true and an empty command list.
    Namespaced to the signed-in user; anonymous keeps the shared namespace.
    """
    from advisor.governance_draft import create_builder_draft as _create_builder_draft
    from advisor.auth import get_current_user
    user = get_current_user(request)
    user_id = None if not user or user.get("anonymous") else user.get("user_id") or user.get("sub")
    title = (body.get("title") or "Untitled Plan").strip()
    perspective = body.get("perspective")
    return _create_builder_draft(title, perspective, user_id=user_id)


@app.get("/api/plan-templates")
async def list_plan_templates() -> Dict[str, Any]:
    """Return available plan templates."""
    from advisor.plan_templates import get_template_manager
    return {"templates": get_template_manager().list_templates()}


@app.delete("/api/plan-templates/{name}")
async def delete_plan_template(name: str) -> Dict[str, str]:
    """Delete a plan template by name."""
    from urllib.parse import unquote
    from advisor.plan_templates import get_template_manager
    deleted = get_template_manager().delete(unquote(name))
    return {"status": "ok" if deleted else "not_found"}


@app.get("/api/sessions")
async def list_sessions() -> Dict[str, Any]:
    """Return planning session transcript metadata (newest first)."""
    from advisor.session_logger import get_session_logger
    return {"sessions": get_session_logger().list_sessions()}


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Return the full transcript for a planning session."""
    from fastapi import HTTPException
    from advisor.session_logger import get_session_logger
    entries = get_session_logger().load_session(session_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "entries": entries}


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


@app.get("/api/templates/{command_name}/fields")
async def get_template_fields(request: Request, command_name: str, level: str = "basic") -> Dict[str, Any]:
    """Return template field metadata for a Dr.Egeria command at the given template level.

    Requires login — the valid-values enrichment below performs live Egeria reads
    and must be attributable to the signed-in user, not a shared service account.
    """
    from advisor.auth import require_egeria_user, get_egeria_credentials
    require_egeria_user(request)
    egeria_credentials = get_egeria_credentials(request)
    from urllib.parse import unquote
    from advisor.agents.tools import _templates_root, _normalise
    from advisor.agents.dr_egeria_agent import parse_template

    action = unquote(command_name)
    root   = _templates_root()
    if root is None:
        return {"fields": [], "level": level}

    level_dir = root / level
    if not level_dir.is_dir():
        level_dir = root / "basic"

    query_norm = _normalise(action)
    words      = [_normalise(w) for w in action.split() if len(w) > 3]

    best_score = 0
    best_file  = None
    for md_file in sorted(level_dir.rglob("*.md")):
        stem_norm = _normalise(md_file.stem)
        score = 0
        if query_norm == stem_norm:           score = 50
        elif query_norm in stem_norm:         score = 40
        elif stem_norm in query_norm:         score = 35
        elif words:
            hits = sum(1 for w in words if w in stem_norm)
            if hits == len(words):            score = 30
            elif hits > 0:                    score = 20 + hits
        if score > best_score:
            best_score = score
            best_file  = md_file

    if best_file is None or best_score == 0:
        return {"fields": [], "level": level}

    try:
        template = parse_template(str(best_file))
    except Exception:
        return {"fields": [], "level": level}

    # Enrich valid_values for known field patterns with live Egeria data
    zone_values: list[str] = []
    tech_type_values: list[str] = []
    for a in template["attributes"]:
        name_low = a["name"].lower()
        if not a.get("valid_values") and "zone" in name_low:
            if not zone_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    zone_values = EgeriaContext(egeria_credentials=egeria_credentials).list_governance_zones()
                except Exception:
                    pass
            if zone_values:
                a["valid_values"] = zone_values
        elif not a.get("valid_values") and "deployed implementation type" in name_low:
            if not tech_type_values:
                try:
                    from advisor.egeria_context import EgeriaContext
                    tech_type_values = EgeriaContext(egeria_credentials=egeria_credentials).list_technology_types()
                except Exception:
                    pass
            if tech_type_values:
                a["valid_values"] = tech_type_values

    return {
        "level": level,
        "fields": [
            {
                "name":               a["name"],
                "required":           a["required"],
                "type":               a["type"],
                "description":        a.get("description", ""),
                "valid_values":       a.get("valid_values", []),
                "default_value":      a.get("default_value", ""),
                "alternative_labels": a.get("alternative_labels", []),
            }
            for a in template["attributes"]
        ],
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


@app.post("/api/feedback")
async def record_feedback(req: FeedbackRequest) -> Dict[str, str]:
    """Record 👍/😐/👎 feedback."""
    try:
        from advisor.feedback_collector import get_feedback_collector
        fc = get_feedback_collector()
        if req.vote > 0:
            rating = "positive"
        elif req.vote == 0:
            rating = "neutral"
        else:
            rating = "negative"
        fc.record_feedback(
            query=req.query,
            query_type=req.query_type,
            collections_searched=[],
            response_length=len(req.response_text or ""),
            rating=rating,
            perspective=req.perspective or None,
            routing_agent=req.routing_agent or None,
            feedback_text=req.intent_override or None,  # repurpose for intent label until schema expanded
            user_comment=req.intent_override,
        )
        # Also write the full record including response_text to an extended JSONL
        try:
            import json as _json
            from advisor.config import ensure_writable_dir
            ext_path = _extended_feedback_path()
            ensure_writable_dir(ext_path.parent, "ADVISOR_DATA_PATH")
            from datetime import datetime as _dt
            record = {
                "timestamp": _dt.utcnow().isoformat(),
                "query": req.query,
                "query_type": req.query_type,
                "vote": req.vote,
                "rating": rating,
                "perspective": req.perspective,
                "intent_override": req.intent_override,
                "routing_agent": req.routing_agent,
                "response_text": req.response_text,
                "triage_status": "new",
                "analysis_comments": "",
            }
            with open(ext_path, "a") as f:
                f.write(_json.dumps(record) + "\n")
        except Exception as exc:
            logger.warning(f"Extended feedback write failed: {exc}")
    except Exception as exc:
        logger.warning(f"Feedback recording failed: {exc}")
    return {"status": "ok"}


@app.get("/api/perspectives")
async def list_perspectives() -> Dict[str, Any]:
    """Return available perspectives (live from Egeria or CSV fallback)."""
    from advisor.perspective_manager import get_all
    return {"perspectives": get_all()}


@app.get("/api/feedback/extended")
async def feedback_extended() -> Dict[str, Any]:
    """Return all extended feedback records (with response_text, triage_status, etc.)."""
    import json as _json
    path = _extended_feedback_path()
    records = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                records.append(_json.loads(line))
            except Exception:
                pass
    return {"records": records, "total": len(records)}


@app.patch("/api/feedback/extended/{idx}")
async def update_feedback_record(idx: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update triage_status or analysis_comments on a feedback record by line index."""
    import json as _json
    from fastapi import HTTPException
    path = _extended_feedback_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="No feedback records")
    lines = path.read_text().splitlines()
    if idx < 0 or idx >= len(lines):
        raise HTTPException(status_code=404, detail=f"Record {idx} not found")
    try:
        record = _json.loads(lines[idx])
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt record")
    allowed = {"triage_status", "analysis_comments"}
    for k, v in body.items():
        if k in allowed:
            record[k] = v
    lines[idx] = _json.dumps(record)
    path.write_text("\n".join(lines) + "\n")
    return {"status": "ok", "record": record}


@app.get("/api/feedback/analysis")
async def feedback_analysis() -> Dict[str, Any]:
    """Return feedback statistics plus gap analysis."""
    from advisor.feedback_collector import get_feedback_collector
    fc = get_feedback_collector()
    return {
        "stats": fc.get_feedback_stats(),
        "gaps": fc.get_gap_analysis(),
        "improvements": fc.get_routing_improvements(),
    }
