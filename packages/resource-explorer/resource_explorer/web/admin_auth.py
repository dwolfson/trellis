"""Minimal, fail-closed admin check for RE.

RE has no multi-user authentication system yet (see FeedbackConfig / the
Slice 1 plan). This is deliberately NOT a general auth system — it exists
only to gate the feedback-triage admin endpoints, and is the seam a real
auth system should replace later.

It inverts a real bug found in Egeria Workspaces Portal's
demo_feedback_handler.py::_is_admin(), which returned True unconditionally
whenever neither DEMO_MODE nor SERVER_MANAGED_AUTH was configured — i.e.
it failed OPEN with no auth at all in the simple/local case. Here, absence
of any admin configuration means every admin request is denied.
"""
from __future__ import annotations

from fastapi import Request

from resource_explorer.config import FeedbackConfig


def is_admin_request(request: Request, cfg: FeedbackConfig) -> bool:
    """True only if the request presents a valid, configured admin credential.

    Recognizes either:
      - header 'X-Admin-Token' matching a non-empty cfg.admin_token, or
      - header 'X-Admin-User' present and non-empty and listed in cfg.admin_users

    If neither admin_token nor admin_users is configured, this always
    returns False — fail closed, not fail open.
    """
    token = request.headers.get("X-Admin-Token", "")
    if cfg.admin_token and token and token == cfg.admin_token:
        return True

    user = request.headers.get("X-Admin-User", "")
    if cfg.admin_users and user and user in cfg.admin_users:
        return True

    return False
