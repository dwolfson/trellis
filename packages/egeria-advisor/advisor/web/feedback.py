"""
Feedback API routes for Egeria Advisor.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor,
slice 2). Follows `admin.py`'s/`auth.py`'s existing pattern: a bare
`APIRouter()` with full paths on each route (no `prefix=` at
`include_router` time). Depends on `advisor.web.shared` for
`FeedbackRequest` and `_extended_feedback_path` — the two pieces of
cross-cutting state these routes share with the rest of app.py.

Endpoints:
  POST  /api/feedback                 → record 👍/😐/👎 feedback
  GET   /api/feedback/extended        → all extended feedback records
  PATCH /api/feedback/extended/{idx}  → update triage_status/analysis_comments
  GET   /api/feedback/analysis        → feedback stats + gap analysis
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Dict

from fastapi import APIRouter, HTTPException
from loguru import logger

from advisor.web.shared import FeedbackRequest, _extended_feedback_path

router = APIRouter()


@router.post("/api/feedback")
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
            from advisor.config import ensure_writable_dir
            ext_path = _extended_feedback_path()
            ensure_writable_dir(ext_path.parent, "ADVISOR_DATA_PATH")
            record = {
                "timestamp": datetime.utcnow().isoformat(),
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
    except Exception as exc:
        logger.warning(f"Feedback recording failed: {exc}")
    return {"status": "ok"}


@router.get("/api/feedback/extended")
async def feedback_extended() -> Dict[str, Any]:
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
async def update_feedback_record(idx: int, body: Dict[str, Any]) -> Dict[str, Any]:
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
async def feedback_analysis() -> Dict[str, Any]:
    """Return feedback statistics plus gap analysis."""
    from advisor.feedback_collector import get_feedback_collector
    fc = get_feedback_collector()
    return {
        "stats": fc.get_feedback_stats(),
        "gaps": fc.get_gap_analysis(),
        "improvements": fc.get_routing_improvements(),
    }
