"""Query endpoint — POST a question, get a response."""
from __future__ import annotations

import hashlib
import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter()

# ── session store ──────────────────────────────────────────────────────────────
# Maps session_id → (ConversationAgent, last_used_timestamp)
# Capped at 50 sessions; idle sessions expire after 30 minutes.
_SESSION_TTL = 1800  # seconds
_SESSION_MAX = 50
_sessions: dict[str, tuple] = {}


def _get_or_create_session(session_id: str, resource_slug: str | None):
    """Return a ConversationAgent for this session, creating one if needed."""
    from resource_explorer.agents.conversation_agent import ConversationAgent

    now = time.monotonic()

    # Evict expired sessions
    expired = [sid for sid, (_, ts) in _sessions.items() if now - ts > _SESSION_TTL]
    for sid in expired:
        del _sessions[sid]

    # Evict oldest when at capacity
    if len(_sessions) >= _SESSION_MAX and session_id not in _sessions:
        oldest = min(_sessions, key=lambda sid: _sessions[sid][1])
        del _sessions[oldest]

    if session_id not in _sessions:
        agent = ConversationAgent(resource_slug=resource_slug)
        # Hydrate memory from persisted history so context survives restarts
        try:
            from resource_explorer.registry import ProjectRegistry
            turns = ProjectRegistry().load_turns(session_id)
            if turns:
                agent.load_history(turns)
        except Exception:
            pass
        _sessions[session_id] = (agent, now)
    else:
        agent, _ = _sessions[session_id]
        _sessions[session_id] = (agent, now)
        if resource_slug:
            agent.resource_slug = resource_slug

    return agent


def _persist_turn(session_id: str, query: str, response: str, resource_slug: str | None) -> None:
    try:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
        registry.append_turn(session_id, "user", query, resource_slug)
        registry.append_turn(session_id, "assistant", response, resource_slug)
    except Exception:
        pass


class QueryRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    query: str
    # alias keeps the JSON wire key as `project_slug` while the Python
    # vocabulary moves to `resource_slug`. A Pydantic field name IS the
    # wire key, so this is the one place the identifier rename and the
    # API contract are the same edit. index.html still sends the old
    # key; drop the alias when the wire format moves too.
    resource_slug: str | None = Field(default=None, alias="project_slug")
    database_slug: str | None = None  # NEW: for database-scoped queries
    session_id: str | None = None  # browser-generated UUID for cross-turn memory


class QueryResponse(BaseModel):
    response: str
    intent: str
    query_hash: str
    cached: bool = False
    chart: dict | None = None  # Plotly figure JSON when intent warrants a chart


class FeedbackRequest(BaseModel):
    query_hash: str
    vote: int  # +1 or -1


def _pick_chart(query: str, intent: str, resource_slug: str) -> dict | None:
    """Return a Plotly figure as a JSON-serialisable dict, or None."""
    if not resource_slug:
        return None
    if intent not in ("statistical", "health", "comparison"):
        return None
    try:
        from resource_explorer.dashboard import graphs
        q = query.lower()

        if intent == "comparison":
            # Extract slugs from the query for a cross-project stats chart
            from resource_explorer.agents.compare_agent import CompareAgent
            slugs = CompareAgent()._infer_all_project_slugs(query)
            if len(slugs) >= 2:
                fig = graphs.compare_stats_plotly(slugs)
            else:
                return None

        elif intent == "health":
            fig = graphs.health_radar_plotly(resource_slug)

        elif any(w in q for w in ("committer", "contributor", "who commit", "who contribut", "top commit")):
            fig = graphs.top_committers_plotly(resource_slug)
            if fig is None:
                return None  # no data — don't show an empty chart

        elif any(w in q for w in ("star", "popular", "growth")):
            fig = graphs.stars_over_time_plotly(resource_slug)

        elif any(w in q for w in ("language", "breakdown", "written in", "code in")):
            fig = graphs.language_breakdown_plotly(resource_slug)

        elif any(w in q for w in ("week", "weekly", "per week", "week-by-week")):
            fig = graphs.weekly_commits_plotly(resource_slug)

        elif any(w in q for w in ("file", "files", "file type", "file count", "how many file")):
            fig = graphs.file_types_plotly(resource_slug)

        elif any(w in q for w in ("commit", "activity", "history", "how many commit")):
            fig = graphs.commits_over_time_plotly(resource_slug)

        else:
            return None

        return json.loads(fig.to_json())
    except Exception:
        return None


@router.post("/", response_model=QueryResponse)
async def ask(request: QueryRequest) -> QueryResponse:
    from resource_explorer.query_processor import QueryProcessor
    intent = QueryProcessor().classify(request.query)
    query_hash = hashlib.sha256(request.query.encode()).hexdigest()[:16]

    if request.session_id:
        agent = _get_or_create_session(request.session_id, request.resource_slug)
        response = agent.handle(request.query, resource_slug=request.resource_slug)
        _persist_turn(request.session_id, request.query, response, request.resource_slug)
    else:
        from resource_explorer.rag_system import RAGSystem
        response = RAGSystem().query(request.query, resource_slug=request.resource_slug)

    chart = _pick_chart(request.query, intent.value, request.resource_slug or "")
    return QueryResponse(
        response=response,
        intent=intent.value,
        query_hash=query_hash,
        chart=chart,
    )


@router.post("/stream")
async def stream(request: QueryRequest) -> StreamingResponse:
    """
    SSE streaming variant of /api/query/.

    Yields newline-delimited JSON events:
      {"t":"chunk","v":"<text>"}   — one or more text chunks
      {"t":"done","intent":"...","hash":"...","chart":...}  — terminal event
    """
    import asyncio

    def _sse(obj: dict) -> str:
        return f"data: {json.dumps(obj)}\n\n"

    async def _generate() -> AsyncIterator[str]:
        loop = asyncio.get_event_loop()

        queue: asyncio.Queue = asyncio.Queue()

        def _producer() -> None:
            try:
                if request.session_id:
                    from resource_explorer.query_processor import QueryProcessor
                    intent = QueryProcessor().classify(request.query).value
                    agent = _get_or_create_session(request.session_id, request.resource_slug)
                    text = agent.handle(request.query, resource_slug=request.resource_slug)
                    _persist_turn(request.session_id, request.query, text, request.resource_slug)
                    loop.call_soon_threadsafe(queue.put_nowait, text)
                    loop.call_soon_threadsafe(queue.put_nowait, {"_done": True, "intent": intent, "hash": hashlib.sha256(request.query.encode()).hexdigest()[:16], "cached": False})
                else:
                    from resource_explorer.rag_system import RAGSystem
                    rag = RAGSystem()
                    for item in rag.stream(request.query, resource_slug=request.resource_slug):
                        loop.call_soon_threadsafe(queue.put_nowait, item)
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        import threading
        threading.Thread(target=_producer, daemon=True).start()

        while True:
            item = await queue.get()
            if item is None:
                break
            if isinstance(item, dict) and item.get("_done"):
                # Build the done event, attach chart if relevant
                chart = _pick_chart(
                    request.query, item.get("intent", ""), request.resource_slug or ""
                )
                intent_val = item.get("intent", "")
                done: dict = {
                    "t": "done",
                    "intent": intent_val,
                    "hash": item.get("hash", ""),
                    "cached": item.get("cached", False),
                    "chart": chart,
                }
                # Structured symbol table for code_inventory queries
                if intent_val == "code_inventory" and request.resource_slug:
                    done["symbol_table"] = _code_inventory_table(request.query, request.resource_slug)
                # Side-by-side symbol comparison for comparison queries about API surface
                if intent_val == "comparison":
                    done["compare_symbols"] = _compare_symbols_table(request.query)
                # Suggest an alias when no project was resolved but a fuzzy match exists
                if not request.resource_slug:
                    alias_hint = _fuzzy_alias_suggestion(request.query)
                    if alias_hint:
                        done["alias_suggestion"] = alias_hint
                yield _sse(done)
            else:
                yield _sse({"t": "chunk", "v": str(item)})

    return StreamingResponse(_generate(), media_type="text/event-stream")


@router.post("/feedback")
async def feedback(request: FeedbackRequest) -> dict:
    from resource_explorer.observability.metrics_collector import MetricsCollector
    MetricsCollector().record_feedback(request.query_hash, request.vote)
    return {"recorded": True}


def _code_inventory_table(query: str, resource_slug: str) -> dict | None:
    """
    Build a structured symbol table payload for code_inventory done events.
    Extracts kind hint from query, returns top 30 matching symbols.
    """
    import re
    import sqlite3
    try:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
        slug = registry._normalize_slug(resource_slug)

        q = query.lower()
        kind = "all"
        for k in ("class", "method", "function", "interface", "enum"):
            if k in q:
                kind = k
                break

        # Pattern hint: word after "named", "called", or after "show.*<kind>"
        pattern = ""
        m = re.search(r'(?:named?|called?)\s+(\w+)', q)
        if m:
            pattern = m.group(1)

        conn = sqlite3.connect(registry.db_path)
        conn.row_factory = sqlite3.Row
        filters = ["project_slug = ?"]
        params: list = [slug]
        if kind != "all":
            filters.append("kind = ?")
            params.append(kind)
        if pattern:
            filters.append("name LIKE ?")
            params.append(f"%{pattern}%")
        where = " AND ".join(filters)
        rows = conn.execute(
            f"SELECT kind, name, qualified_name, signature, docstring, file_path, start_line "  # noqa: S608
            f"FROM project_code_symbols WHERE {where} ORDER BY file_path, start_line LIMIT 30",
            params,
        ).fetchall()
        total = conn.execute(
            f"SELECT COUNT(*) FROM project_code_symbols WHERE {where}",  # noqa: S608
            params,
        ).fetchone()[0]
        conn.close()

        if not rows:
            return None
        return {
            "kind": kind,
            "project": slug,
            "total": total,
            "items": [
                {
                    "kind": r["kind"],
                    "name": r["qualified_name"],
                    "signature": r["signature"] or "",
                    "doc": (r["docstring"] or "")[:80],
                    "file": r["file_path"],
                    "line": r["start_line"],
                }
                for r in rows
            ],
        }
    except Exception:
        return None


def _compare_symbols_table(query: str) -> dict | None:
    """
    Build a side-by-side symbol comparison payload when the comparison query
    is about API surface, classes, or methods. Returns None if fewer than two
    projects have symbol data or the query isn't about code structure.
    """
    import re
    import sqlite3

    _SYMBOL_KEYWORDS = ("class", "method", "function", "interface", "api surface", "symbol", "public")
    q = query.lower()
    if not any(w in q for w in _SYMBOL_KEYWORDS):
        return None

    kind = "all"
    for k in ("class", "method", "function", "interface"):
        if k in q:
            kind = k
            break

    try:
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.agents.compare_agent import CompareAgent

        registry = ProjectRegistry()
        slugs = CompareAgent()._infer_all_project_slugs(query)
        if len(slugs) < 2:
            return None

        conn = sqlite3.connect(registry.db_path)
        conn.row_factory = sqlite3.Row

        sides = []
        for slug in slugs[:2]:
            filters = ["project_slug = ?"]
            params: list = [slug]
            if kind != "all":
                filters.append("kind = ?")
                params.append(kind)
            where = " AND ".join(filters)

            counts_rows = conn.execute(
                f"SELECT kind, COUNT(*) as cnt FROM project_code_symbols WHERE {where} GROUP BY kind",  # noqa: S608
                params,
            ).fetchall()
            counts = {r["kind"]: r["cnt"] for r in counts_rows}

            items_rows = conn.execute(
                f"SELECT kind, qualified_name, signature, docstring, file_path, start_line "  # noqa: S608
                f"FROM project_code_symbols WHERE {where} ORDER BY kind, file_path, start_line LIMIT 20",
                params,
            ).fetchall()
            total = conn.execute(
                f"SELECT COUNT(*) FROM project_code_symbols WHERE {where}",  # noqa: S608
                params,
            ).fetchone()[0]

            sides.append({
                "slug": slug,
                "total": total,
                "counts": counts,
                "items": [
                    {
                        "kind": r["kind"],
                        "name": r["qualified_name"],
                        "signature": r["signature"] or "",
                        "doc": (r["docstring"] or "")[:80],
                        "file": r["file_path"],
                        "line": r["start_line"],
                    }
                    for r in items_rows
                ],
            })

        conn.close()

        if not any(s["total"] > 0 for s in sides):
            return None

        return {"kind": kind, "sides": sides}
    except Exception:
        return None


def _fuzzy_alias_suggestion(query: str) -> dict | None:
    """
    Return {term, candidate_slug, candidate_name} if a fuzzy match exists for the query
    but is not already an exact slug/alias match. Returns None otherwise.
    """
    try:
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.agents.base import BaseExplorerAgent

        registry = ProjectRegistry()
        # Skip if query already resolves exactly
        class _Probe(BaseExplorerAgent):
            def system_prompt(self): return ""
            def tools(self): return []
            def handle(self, *a, **kw): return ""
        if _Probe()._infer_project_slug(query):
            return None
        result = registry.fuzzy_candidate(query)
        if not result:
            return None
        term, slug = result
        project = registry.get(slug)
        return {
            "term": term,
            "candidate_slug": slug,
            "candidate_name": project.display_name if project else slug,
        }
    except Exception:
        return None
