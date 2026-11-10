"""
Feedback API routes for Egeria Advisor.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor,
slice 2). Follows `admin.py`'s/`auth.py`'s existing pattern: a bare
`APIRouter()` with full paths on each route (no `prefix=` at
`include_router` time). Depends on `advisor.web.shared` for
`FeedbackRequest` and `_extended_feedback_path` — the two pieces of
cross-cutting state these routes share with the rest of app.py.

Endpoints:
  POST  /api/feedback                 → record 👍/😐/👎 feedback (honest status; see the route)
  GET   /api/feedback/extended        → all extended feedback records
  PATCH /api/feedback/extended/{idx}  → update triage_status/analysis_comments
  GET   /api/feedback/analysis        → feedback stats + gap analysis
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from starlette.concurrency import run_in_threadpool

from advisor.web.shared import FeedbackRequest, _extended_feedback_path

router = APIRouter()


def _voter_id(request: Request) -> Optional[str]:
    """The signed-in user's id, or None when anonymous: the same extraction as the app's
    user-context middleware (a claim from EA's own validated session JWT, not a client field)."""
    from advisor.auth import get_current_user
    user = get_current_user(request)
    if not user or user.get("anonymous"):
        return None
    return user.get("user_id") or user.get("sub") or None


def _record_vote(req: FeedbackRequest, user_id: Optional[str]) -> Dict[str, Any]:
    """The synchronous work of one vote; run in a worker thread, never on the event loop.
    Raises FeedbackWriteError when the primary record was not written."""
    from advisor.feedback_collector import get_feedback_collector
    fc = get_feedback_collector()
    if req.vote > 0:
        rating = "positive"
    elif req.vote == 0:
        rating = "neutral"
    else:
        rating = "negative"
    primary = fc.record_vote(
        query=req.query,
        query_type=req.query_type,
        collections_searched=[],
        response_length=len(req.response_text or ""),
        rating=rating,
        perspective=req.perspective or None,
        routing_agent=req.routing_agent or None,
        # The intent selector is not something the user wrote: its own field, never user_comment.
        intent_override=req.intent_override or None,
        user_id=user_id,
    )
    # Secondary: the full record including response_text, for triage
    extended = "ok"
    try:
        from advisor.config import ensure_writable_dir
        ext_path = _extended_feedback_path()
        ensure_writable_dir(ext_path.parent, "ADVISOR_DATA_PATH")
        record = {
            "timestamp": datetime.utcnow().isoformat(),
            "user_id": user_id,
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
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        logger.warning(f"Extended feedback write failed: {exc}")
        extended = "error"
    return {"status": "ok", "secondary": {"extended": extended, "query_metrics": primary["query_metrics"]}}


@router.post("/api/feedback")
async def record_feedback(req: FeedbackRequest, request: Request) -> Dict[str, Any]:
    """Record 👍/😐/👎 feedback (Phase 0 S4 hotfix; Phase 2 replaces it with trellis-feedback).

    The work runs in a worker thread: the collector is synchronous, and running it on the event
    loop once blocked all of EA for ~4 minutes while MLflow retried a refused port. MLflow itself
    is queued in the background and never awaited.

    Honest status: {"status": "ok", "secondary": {"extended": ok|error, "query_metrics":
    ok|no_match|skipped|error}} only when the primary record (user_feedback.jsonl) was written;
    otherwise HTTP 500 "could not record your feedback: <reason>".
    """
    from advisor.feedback_collector import FeedbackWriteError
    user_id = _voter_id(request)
    try:
        return await run_in_threadpool(_record_vote, req, user_id)
    except FeedbackWriteError as exc:
        logger.error(f"Feedback not recorded: {exc}")
        raise HTTPException(status_code=500, detail=f"could not record your feedback: {exc}")
    except Exception as exc:  # the collector itself could not start (e.g. data dir not writable)
        logger.error(f"Feedback not recorded: {exc}")
        raise HTTPException(status_code=500,
                            detail=f"could not record your feedback: {type(exc).__name__}: {exc}")


@router.get("/api/feedback/extended")
def feedback_extended() -> Dict[str, Any]:
    """Return all extended feedback records (with response_text, triage_status, etc.)."""
    path = _extended_feedback_path()
    records = []
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                pass
    return {"records": records, "total": len(records)}


@router.patch("/api/feedback/extended/{idx}")
def update_feedback_record(idx: int, body: Dict[str, Any]) -> Dict[str, Any]:
    """Update triage_status or analysis_comments on a feedback record by line index."""
    path = _extended_feedback_path()
    if not path.exists():
        raise HTTPException(status_code=404, detail="No feedback records")
    lines = path.read_text().splitlines()
    if idx < 0 or idx >= len(lines):
        raise HTTPException(status_code=404, detail=f"Record {idx} not found")
    try:
        record = json.loads(lines[idx])
    except Exception:
        raise HTTPException(status_code=500, detail="Corrupt record")
    allowed = {"triage_status", "analysis_comments"}
    for k, v in body.items():
        if k in allowed:
            record[k] = v
    lines[idx] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n")
    return {"status": "ok", "record": record}


@router.get("/api/feedback/analysis")
def feedback_analysis() -> Dict[str, Any]:
    """Return feedback statistics plus gap analysis."""
    from advisor.feedback_collector import get_feedback_collector
    fc = get_feedback_collector()
    return {
        "stats": fc.get_feedback_stats(),
        "gaps": fc.get_gap_analysis(),
        "improvements": fc.get_routing_improvements(),
    }
