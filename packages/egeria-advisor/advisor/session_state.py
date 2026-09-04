"""
SessionState — the backend-owned session store from
docs/design/SESSION_AND_INTERACTION_STATE.md ("Session store — new, small,
in-memory"), implemented per docs/runtime-architecture-plan.md §4's
correction: **Postgres-backed from the start**, not the design doc's
original `Dict[str, SessionState]`, because a request can land on any web
worker (the design doc's own caveat: "If this app ever moves to
multi-worker or multi-instance deployment, the in-memory dict would need to
move to Redis... Not needed for the current single-process deployment" —
that assumption no longer holds once the web tier can run more than one
worker, so this implements the deployment-ready version directly rather
than building the single-process one and migrating later).

Two scoping dimensions, per the design doc:
  * user_id (JWT `sub`) — persistent, survives logout/browser close.
  * session_id — ephemeral, dies with the tab (minted client-side, sent as
    an `X-Session-Id` header — see the design doc's "Open question", still
    open; this store is agnostic to how session_id is minted).

A session's `state` is a small JSON blob (active_draft_id, mode, pending
clarification, ...) — this module does not interpret it, only stores and
returns it, matching the design doc's `SessionState` shape:
    {"user_id": str, "active_draft_id": Optional[str], "mode": str,
     "last_seen": float}

Table: `advisor_sessions` (DDL in advisor/db_consolidated.py, alongside the
other Postgres-backed stores — same `ConsolidatedDBManager` instance/pool,
same `egeria_advisor` database the pgvector tables use).

Expiry: sessions expire with the JWT that created/touched them — Egeria's
bearer token is capped at ~1 hour (`trellis_auth.EGERIA_TOKEN_TTL_SECONDS_OBSERVED`,
see advisor/auth.py's `create_access_token` docstring), so `expires_at`
tracks that, not a separate session TTL. A caller passes the JWT's own
`exp` (or omits it to fall back to now + EGERIA_TOKEN_TTL_SECONDS_OBSERVED)
so a session's expiry can never outlive the credential that authenticated
it.

Sweeping: no background thread or worker role exists for EA yet (per the
plan doc — "on access, not a thread"). `maybe_sweep()` deletes expired rows
and is called lazily, at low probability, from `touch()`/`upsert()` — see
its docstring for the throttling rationale.
"""
from __future__ import annotations

import json
import random
import time
from typing import Any, Dict, Optional

from loguru import logger

from advisor.db_consolidated import get_db_manager

try:
    from trellis_auth import EGERIA_TOKEN_TTL_SECONDS_OBSERVED
except Exception:  # pragma: no cover - trellis_auth always present in this workspace
    EGERIA_TOKEN_TTL_SECONDS_OBSERVED = 3600

#: Default session lifetime when no explicit expires_at is given — mirrors
#: the Egeria bearer token's own observed TTL (see module docstring).
DEFAULT_SESSION_TTL_SECONDS = EGERIA_TOKEN_TTL_SECONDS_OBSERVED

#: Probability maybe_sweep() actually runs its DELETE on any given call —
#: throttles the sweep to roughly "sometimes", not every request, with no
#: separate scheduler/thread required. 1-in-20 keeps a typical demo session
#: (a handful of requests a minute) sweeping every few minutes without
#: adding a DELETE to most requests' critical path.
_SWEEP_PROBABILITY = 0.05


def _now() -> float:
    return time.time()


def get(session_id: str) -> Optional[Dict[str, Any]]:
    """Return the session row (as a dict: session_id, user_id, created_at,
    last_seen_at, state, expires_at), or None if it doesn't exist or has
    expired. Does not enforce ownership — see get_for_owner() for the
    404-shaped ownership check callers with a requester identity should use.
    """
    rows = get_db_manager().execute_query(
        "SELECT session_id, user_id, created_at, last_seen_at, state, expires_at "
        "FROM advisor_sessions WHERE session_id = %s",
        (session_id,),
    )
    if not rows:
        return None
    row = rows[0]
    if row["expires_at"] <= _now():
        return None
    if isinstance(row["state"], str):
        row["state"] = json.loads(row["state"])
    return row


def get_for_owner(session_id: str, requester_user_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Like get(), but returns None (never distinguishing "doesn't exist"
    from "exists but belongs to someone else") unless requester_user_id
    matches the session's own user_id. A session created under one user is
    therefore not readable by another — 404, not 403, so a caller can't use
    this to enumerate which session_ids exist for other users. Anonymous
    sessions (user_id None) are visible to anonymous requests (also None),
    matching `_anonymous_rag_mode`."""
    row = get(session_id)
    if row is None:
        return None
    if row.get("user_id") != requester_user_id:
        return None
    return row


def upsert(session_id: str, user_id: Optional[str], state: Dict[str, Any],
           expires_at: Optional[float] = None) -> Dict[str, Any]:
    """Create or fully replace a session's state (INSERT ... ON CONFLICT
    UPDATE, matching this codebase's other Postgres-backed stores' upsert
    shape — see `advisor.query_cache` / `advisor.analytics` for the
    convention this follows). created_at is preserved across an update
    (via the ON CONFLICT clause) — only last_seen_at/state/expires_at
    change.

    expires_at defaults to now + DEFAULT_SESSION_TTL_SECONDS when omitted;
    a caller holding the request's JWT should pass its own `exp` claim
    instead, so the session can never outlive the credential that
    authenticated it (see module docstring).

    Returns the row as stored (same shape as get()).
    """
    now = _now()
    if expires_at is None:
        expires_at = now + DEFAULT_SESSION_TTL_SECONDS
    get_db_manager().execute_update(
        """
        INSERT INTO advisor_sessions (session_id, user_id, created_at, last_seen_at, state, expires_at)
        VALUES (%s, %s, %s, %s, %s, %s)
        ON CONFLICT (session_id) DO UPDATE SET
            user_id      = EXCLUDED.user_id,
            last_seen_at = EXCLUDED.last_seen_at,
            state        = EXCLUDED.state,
            expires_at   = EXCLUDED.expires_at
        """,
        (session_id, user_id, now, now, json.dumps(state), expires_at),
    )
    maybe_sweep()
    return {
        "session_id": session_id, "user_id": user_id, "created_at": now,
        "last_seen_at": now, "state": state, "expires_at": expires_at,
    }


def touch(session_id: str, state: Optional[Dict[str, Any]] = None,
          expires_at: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """Update last_seen_at (and, optionally, state and/or expires_at) for
    an existing session without needing its user_id — used by request
    handlers that already know session_id is valid and just want to record
    activity / patch a couple of state fields. Returns the updated row, or
    None if the session doesn't exist or has already expired (does not
    resurrect an expired session — call upsert() to start a new one).
    """
    row = get(session_id)
    if row is None:
        return None
    new_state = state if state is not None else row["state"]
    new_expires_at = expires_at if expires_at is not None else row["expires_at"]
    now = _now()
    get_db_manager().execute_update(
        "UPDATE advisor_sessions SET last_seen_at = %s, state = %s, expires_at = %s "
        "WHERE session_id = %s",
        (now, json.dumps(new_state), new_expires_at, session_id),
    )
    maybe_sweep()
    row["last_seen_at"] = now
    row["state"] = new_state
    row["expires_at"] = new_expires_at
    return row


def expire(session_id: str) -> bool:
    """Delete one session immediately (explicit logout, "clear context").
    Returns True if a row was deleted."""
    affected = get_db_manager().execute_update(
        "DELETE FROM advisor_sessions WHERE session_id = %s", (session_id,)
    )
    return affected > 0


def sweep_expired() -> int:
    """Delete every session whose expires_at has passed. Returns the count
    deleted. Safe to call anytime — this is the only cleanup mechanism EA
    has for this table (no worker role/thread exists yet — see module
    docstring); maybe_sweep() is what actually invokes it in practice."""
    affected = get_db_manager().execute_update(
        "DELETE FROM advisor_sessions WHERE expires_at <= %s", (_now(),)
    )
    if affected:
        logger.debug(f"session_state: swept {affected} expired session(s)")
    return affected


def maybe_sweep() -> None:
    """Run sweep_expired() with low probability (_SWEEP_PROBABILITY) —
    "the web app runs lazily (on access, not a thread)": EA has no worker
    role to own a periodic job, so cleanup piggybacks on ordinary request
    traffic instead of a dedicated scheduler. Throttled rather than run on
    every call so a busy deployment doesn't add a DELETE to every request's
    critical path — see _SWEEP_PROBABILITY's docstring for the specific
    rate chosen."""
    if random.random() < _SWEEP_PROBABILITY:
        sweep_expired()
