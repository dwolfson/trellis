"""Login, Portal SSO, and the two reads the login form makes before it has a token.

Mirrors `advisor/web/app.py`'s `/api/auth/*` routes deliberately — one shape,
so a reader who knows one app knows the other and neither can drift on the
contract with the Egeria Portal. See `docs/runtime-architecture-plan.md` §4.

All five routes are on the public allowlist (`auth.RE_PUBLIC_PATHS` plus
`trellis_auth`'s shared defaults): a login form that required a token to
reach could never be used.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter()


class LoginRequest(BaseModel):
    username: str
    password: str


class PortalTokenRequest(BaseModel):
    portal_token: str


@router.post("/login")
async def auth_login(req: LoginRequest) -> Dict[str, Any]:
    """Exchange Egeria credentials for RE's session JWT.

    The password is used exactly once, here, to obtain an Egeria bearer token.
    It is never stored and never signed into the JWT (contract, 2026-09-04).
    """
    from resource_explorer.auth import create_access_token, login_with_password

    if not req.username or not req.password:
        raise HTTPException(status_code=400, detail="username and password required")
    egeria_token = await asyncio.get_event_loop().run_in_executor(
        None, login_with_password, req.username, req.password
    )
    if not egeria_token:
        raise HTTPException(
            status_code=401, detail="Invalid credentials or Egeria is unreachable."
        )
    token = create_access_token(user_id=req.username, egeria_token=egeria_token)
    return {"access_token": token, "token_type": "bearer", "egeria_user": req.username}


@router.post("/portal")
async def auth_portal(req: PortalTokenRequest) -> Dict[str, Any]:
    """Exchange a Portal-issued token for RE's own session JWT.

    The Portal has already signed the user into Egeria; its JWT carries the
    resulting bearer token as `{sub, role, display_name, egeria_token, exp}`.
    We validate that under the shared secret (`RE_PORTAL_SECRET`) and re-sign
    it as our own session, so a Portal user never sees a second login.
    """
    from resource_explorer.auth import (
        create_access_token,
        exchange_portal_token,
        validate_egeria_token,
    )

    payload = exchange_portal_token(req.portal_token)
    egeria_user = payload.get("sub", "")
    egeria_token = payload.get("egeria_token", "")

    # Liveness check, deliberately NOT a gate: the token was minted by someone
    # else, so confirming it works is worth one cheap call — but a briefly
    # unreachable Egeria should degrade SSO to "signed in, live calls may
    # fail", which is exactly what a self-minted token would do anyway.
    ok = await asyncio.get_event_loop().run_in_executor(
        None, validate_egeria_token, egeria_token
    )
    if not ok:
        log.warning(
            "auth: Portal token for %r did not validate against Egeria; issuing the "
            "session anyway (live calls may 401)", egeria_user,
        )

    token = create_access_token(
        user_id=egeria_user,
        egeria_token=egeria_token,
        role=payload.get("role", "user"),
        display_name=payload.get("display_name") or egeria_user,
    )
    return {"access_token": token, "token_type": "bearer", "egeria_user": egeria_user}


@router.get("/me")
async def auth_me(request: Request) -> Dict[str, Any]:
    """Who this request is, if anyone. Public — answers `{authenticated: false}`."""
    from resource_explorer.auth import get_current_user

    user = get_current_user(request)
    if user is None:
        return {"authenticated": False}
    user_id = user.get("user_id") or user.get("sub", "")
    return {
        "authenticated": True,
        "user_id": user_id,
        "egeria_user": user_id,
        "role": user.get("role", "user"),
        "display_name": user.get("display_name") or user_id,
    }


@router.post("/logout")
async def auth_logout() -> Dict[str, str]:
    """Client-side logout — the server holds no session state to clear."""
    return {"status": "ok"}


@router.get("/defaults")
async def auth_defaults() -> Dict[str, Any]:
    """The configured default Egeria username, for login-form prefill.

    Deliberately does NOT return the password: this endpoint is public by
    necessity, and returning a plaintext service-account password from it
    would hand it to anyone who can reach the port.
    """
    from resource_explorer.config import get_config

    return {"username": get_config().egeria.user_id}


@router.get("/policy")
async def auth_policy() -> Dict[str, Any]:
    """The active login policy, so the SPA knows what to show before it has a token.

    Public deliberately, and it discloses nothing an unauthenticated caller
    could not learn by making one request and reading the 401.
    """
    from resource_explorer.auth import get_policy

    policy = get_policy()
    return {
        "login_required": policy.require_login and not policy.anonymous_read,
        "anonymous_read": policy.anonymous_read,
    }
