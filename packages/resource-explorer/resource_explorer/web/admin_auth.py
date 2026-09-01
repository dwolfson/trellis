"""Minimal, fail-closed admin check for RE.

RE has no multi-user authentication system yet (see FeedbackConfig / the
Slice 1 plan). This is deliberately NOT a general auth system — it exists
only to gate the feedback-triage admin endpoints, and is the seam a real
auth system should replace later.

It takes the OPPOSITE default from Egeria Workspaces Portal's
demo_feedback_handler.py::_is_admin(), which returns True when neither
DEMO_MODE nor SERVER_MANAGED_AUTH is set.

**That is a deliberate design there, not a bug, and an earlier version of this
docstring called it one.** Corrected 2026-09-01 by Dan, who owns both: the
Portal has two modes — a public demo requiring an external identity, and a
local mode that relies on Egeria's own users for authentication. Permitting
the request in the unconfigured case is that local mode working as intended,
because the authentication happens in Egeria rather than in the handler.

RE chooses the other default because it has no equivalent: no multi-user
authentication, and nothing behind it that authenticates on its behalf. With
nothing to defer to, absence of admin configuration must deny rather than
permit — the same reasoning reaching the opposite conclusion from different
surroundings, not a correction of anyone.

Recorded at length because the original claim was wrong ABOUT ANOTHER PROJECT
and would have long outlived the conversation that produced it.
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
