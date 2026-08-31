"""JWT-based authentication, shared across Trellis apps.

Extracted from Egeria Advisor's `advisor/auth.py`, which had a real login
(HS256 JWTs carrying the signed-in user's Egeria credentials, plus Portal
SSO); Resource Explorer had none. See `docs/trellis-auth-extraction.md`.

This module never reads the environment or a config file — every function
takes an `AuthConfig` the caller has already resolved (see `config.py`).

Deliberately NOT here (stays app-specific — see the design note, §4):
  * whether an app *requires* login at all (EA's `_auth_enabled` /
    `_anonymous_rag_mode` are policy, not mechanism);
  * where config lives (`advisor/configdata/advisor.yaml`, `mcp_servers.json`
    are EA's own paths);
  * `resolve_egeria_credentials`'s service-account fallback — deliberately
    excluded per the 2026-08-29 decision that artifact ownership requires an
    authenticated identity with no config fallback.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, TypedDict

import jwt
from starlette.exceptions import HTTPException
from starlette.requests import Request

from trellis_auth.config import AuthConfig

logger = logging.getLogger(__name__)

__all__ = [
    "EgeriaCredentials",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "require_egeria_user",
    "is_authenticated",
    "get_egeria_credentials",
    "exchange_portal_token",
    "validate_egeria_credentials",
]


# ---------------------------------------------------------------------------
# Token creation / decoding
# ---------------------------------------------------------------------------

def create_access_token(
    user_id: str, egeria_user: str, egeria_password: str, config: AuthConfig
) -> str:
    """Create a signed JWT containing the user's Egeria credentials."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "egeria_user": egeria_user,
        "egeria_password": egeria_password,
        "iat": now,
        "exp": now + timedelta(hours=config.jwt_ttl_hours),
    }
    return jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)


def decode_token(token: str, config: AuthConfig) -> Dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])


# ---------------------------------------------------------------------------
# Request helpers
# ---------------------------------------------------------------------------

def get_current_user(request: Request, config: AuthConfig) -> Optional[Dict[str, Any]]:
    """
    Extract and validate the bearer token from the Authorization header.
    Returns the decoded payload dict, or None if absent / invalid.
    Never raises — callers decide whether anonymous is acceptable.

    This does NOT implement an "auth disabled" bypass — whether an app ever
    calls this at all for anonymous-allowed requests is that app's own
    policy (see module docstring).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        return decode_token(token, config)
    except jwt.PyJWTError as exc:
        logger.debug("auth: invalid token — %s", exc)
        return None


def require_egeria_user(request: Request, config: AuthConfig) -> Dict[str, Any]:
    """
    Like get_current_user but raises HTTP 401 if not authenticated.
    Use as a dependency for endpoints that need live Egeria access.
    """
    user = get_current_user(request, config)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in to access live Egeria features.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def is_authenticated(request: Request, config: AuthConfig) -> bool:
    """Convenience helper for conditional auth checks in a query pipeline."""
    return get_current_user(request, config) is not None


# ---------------------------------------------------------------------------
# Per-user Egeria credential propagation
# ---------------------------------------------------------------------------

class EgeriaCredentials(TypedDict):
    user_id: str
    password: str


def get_egeria_credentials(request: Request, config: AuthConfig) -> Optional[EgeriaCredentials]:
    """
    Extract {user_id, password} from the request's JWT.
    Returns None only when there is no authenticated user (no/invalid
    token) — callers decide whether/how to fall back.
    """
    user = get_current_user(request, config)
    if user is None:
        return None
    return {
        "user_id": user.get("egeria_user", ""),
        "password": user.get("egeria_password", ""),
    }


# ---------------------------------------------------------------------------
# Portal token exchange
# ---------------------------------------------------------------------------

def exchange_portal_token(portal_token: str, config: AuthConfig) -> Dict[str, Any]:
    """
    Validate a short-lived JWT issued by the Portal (shared HS256 secret).
    Returns decoded payload on success; raises HTTP 401 on failure.

    Expected portal token payload:
      { egeria_user: str, egeria_password: str, iat: int, exp: int }
    """
    secret = config.portal_secret
    if not secret:
        raise HTTPException(status_code=503, detail="Portal SSO is not configured on this server.")
    try:
        return jwt.decode(portal_token, secret, algorithms=[config.jwt_algorithm])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Portal token has expired. Please reload from the Portal.")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid portal token: {exc}")


# ---------------------------------------------------------------------------
# Egeria credential validation
# ---------------------------------------------------------------------------

def validate_egeria_credentials(user_id: str, password: str, config: AuthConfig) -> bool:
    """
    Validate credentials against the live Egeria instance by attempting to
    create a bearer token. Returns True on success, False on failure.

    If `config.egeria_view_server`/`egeria_platform_url` aren't set, falls
    back to comparing against `config.egeria_service_account_*` instead of
    attempting a live call — this is a sanity check for a misconfigured
    deployment, not the credential-resolution fallback that
    `resolve_egeria_credentials` deliberately does NOT get in this package
    (see module docstring).

    `pyegeria` is imported lazily (it's an optional `egeria` extra); a
    missing install is caught by the same broad except as "Egeria is
    unreachable" and reported as a failed validation, not an ImportError.
    """
    try:
        view_server = config.egeria_view_server
        platform_url = config.egeria_platform_url

        if not view_server or not platform_url:
            logger.warning(
                "auth: Egeria connection config incomplete — falling back to service account check"
            )
            return (
                user_id == config.egeria_service_account_user
                and password == config.egeria_service_account_password
            )

        from pyegeria.egeria_tech_client import EgeriaTech

        client = EgeriaTech(
            view_server=view_server,
            platform_url=platform_url,
            user_id=user_id,
            user_pwd=password,
        )
        client.create_egeria_bearer_token(user_id, password)
        logger.info("auth: credentials validated for user %r", user_id)
        return True

    except Exception as exc:
        logger.info(
            "auth: credential validation failed for %r — %s: %s", user_id, type(exc).__name__, exc
        )
        return False
