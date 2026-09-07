"""
Session-transcript API routes for Egeria Advisor.

Extracted from `app.py` (TC-5, BACKLOG.md — router-per-domain refactor,
slice 3). Fully self-contained — no dependency on `advisor.web.shared`.

Endpoints:
  GET /api/sessions              → list planning session transcript metadata
  GET /api/sessions/{session_id} → full transcript for one session
"""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/api/sessions")
async def list_sessions() -> Dict[str, Any]:
    """Return planning session transcript metadata (newest first)."""
    from advisor.session_logger import get_session_logger
    return {"sessions": get_session_logger().list_sessions()}


@router.get("/api/sessions/{session_id}")
async def get_session(session_id: str) -> Dict[str, Any]:
    """Return the full transcript for a planning session."""
    from advisor.session_logger import get_session_logger
    entries = get_session_logger().load_session(session_id)
    if not entries:
        raise HTTPException(status_code=404, detail=f"Session {session_id!r} not found")
    return {"session_id": session_id, "entries": entries}
