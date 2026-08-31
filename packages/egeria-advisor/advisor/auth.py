"""
JWT-based authentication for Egeria Advisor — a thin adapter over the shared
`trellis-auth` package.

**Extraction note (2026-08-29):** this used to be a self-contained 255-line
module. The mechanism (JWT create/decode, request-header parsing, Portal
token exchange, live-credential validation) now lives in `trellis_auth` —
shared with Resource Explorer so the two apps can't independently drift on
the *contract with the Portal* (a shared-secret JWT agreement), which is the
kind of divergence this repo has hit before (query cache, annotation
properties, ...). See `docs/trellis-auth-extraction.md`.

What stays here, deliberately, because it's EA's own policy/config, not
mechanism:
  * config file locations (`advisor/configdata/advisor.yaml`,
    `mcp_servers.json`) and reading the environment for secrets;
  * `_anonymous_rag_mode()` / `_auth_enabled()` — whether EA *requires* login
    at all is EA's own answer, and `get_current_user`'s anonymous bypass
    below depends on it, which is why `get_current_user`/`require_egeria_user`/
    `is_authenticated`/`get_egeria_credentials` are re-implemented here (each
    just a few lines) on top of this module's own bypass-aware
    `get_current_user` rather than delegated straight to `trellis_auth`'s
    versions of the same names, which have no notion of "auth disabled";
  * `resolve_egeria_credentials`'s service-account fallback — deliberately
    excluded from `trellis_auth` (see its module docstring) per the
    2026-08-29 decision that artifact ownership requires an authenticated
    identity with NO config fallback.

Public API is unchanged from before the extraction — every name below, same
signature, same behaviour:
  create_access_token(user_id, egeria_user, egeria_password) -> str
  decode_token(token) -> dict
  get_current_user(request) -> Optional[dict]   -- None for anonymous
  require_egeria_user(request) -> dict           -- raises HTTP 401 if missing
  exchange_portal_token(portal_token) -> dict    -- validates portal short-lived token
  validate_egeria_credentials(user_id, password) -> bool
  get_egeria_credentials(request) -> Optional[EgeriaCredentials]  -- None if anonymous
  resolve_egeria_credentials(creds) -> EgeriaCredentials          -- falls back to service account
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException, Request
from loguru import logger

from trellis_auth import AuthConfig
from trellis_auth import EgeriaCredentials
from trellis_auth import create_access_token as _create_access_token
from trellis_auth import decode_token as _decode_token
from trellis_auth import exchange_portal_token as _exchange_portal_token
from trellis_auth import get_current_user as _get_current_user
from trellis_auth import validate_egeria_credentials as _validate_egeria_credentials

__all__ = [
    "EgeriaCredentials",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "require_egeria_user",
    "is_authenticated",
    "get_egeria_credentials",
    "resolve_egeria_credentials",
    "exchange_portal_token",
    "validate_egeria_credentials",
]

# ---------------------------------------------------------------------------
# Configuration helpers — unchanged from before the extraction. Config file
# locations and env-var names are EA's own; trellis_auth never reads either.
# ---------------------------------------------------------------------------

_CFG_PATH  = Path(__file__).parent / "configdata" / "advisor.yaml"
_MCP_PATH  = Path(__file__).parent / "configdata" / "mcp_servers.json"

_cfg_cache: Optional[Dict[str, Any]] = None


def _auth_cfg() -> Dict[str, Any]:
    global _cfg_cache
    if _cfg_cache is None:
        try:
            import yaml
            with open(_CFG_PATH) as f:
                _cfg_cache = yaml.safe_load(f).get("auth", {})
        except Exception:
            _cfg_cache = {}
    return _cfg_cache


def _jwt_secret() -> str:
    secret = os.environ.get("ADVISOR_JWT_SECRET", "") or _auth_cfg().get("jwt_secret", "")
    if not secret:
        # Fallback: derive from machine ID for single-host deployments.
        # This means tokens survive process restart but NOT machine migration.
        import hashlib
        machine = os.environ.get("HOSTNAME", "egeria-advisor-local")
        secret = hashlib.sha256(f"egeria-advisor-{machine}".encode()).hexdigest()
    return secret


def _portal_secret() -> str:
    return (
        os.environ.get("ADVISOR_PORTAL_SECRET", "")
        or _auth_cfg().get("portal", {}).get("shared_secret", "")
    )


def _jwt_ttl_hours() -> int:
    return int(_auth_cfg().get("jwt_ttl_hours", 8))


def _anonymous_rag_mode() -> bool:
    return bool(_auth_cfg().get("anonymous_rag_mode", True))


def _auth_enabled() -> bool:
    return bool(_auth_cfg().get("enabled", True))


def _base_config() -> AuthConfig:
    """AuthConfig for the token-only operations (no Egeria connection needed)."""
    return AuthConfig(
        jwt_secret=_jwt_secret(),
        jwt_ttl_hours=_jwt_ttl_hours(),
        portal_secret=_portal_secret(),
    )


def _validation_config() -> AuthConfig:
    """AuthConfig for validate_egeria_credentials — also carries the Egeria
    connection + service-account-sanity-check fields. Built lazily (and only
    when validation is actually invoked) to preserve the original module's
    lazy `from advisor.mcp_config import ...` import, which avoids a
    circular import at module load time."""
    from advisor.mcp_config import get_pyegeria_platform_config

    conn = get_pyegeria_platform_config()
    view_server = conn["view_server"]
    platform_url = conn["platform_url"]

    svc_user = svc_pwd = ""
    try:
        import json
        cfg = json.loads(_MCP_PATH.read_text())
        env = cfg.get("mcpServers", {}).get("pyegeria", {}).get("env", {})
        svc_user = env.get("EGERIA_USER", "")
        svc_pwd = env.get("EGERIA_PASSWORD", "")
    except Exception as exc:
        logger.warning(f"auth: failed to read {_MCP_PATH} for service-account check: {exc}")

    return AuthConfig(
        jwt_secret=_jwt_secret(),
        jwt_ttl_hours=_jwt_ttl_hours(),
        portal_secret=_portal_secret(),
        egeria_view_server=view_server,
        egeria_platform_url=platform_url,
        egeria_service_account_user=svc_user,
        egeria_service_account_password=svc_pwd,
    )


# ---------------------------------------------------------------------------
# Token creation / decoding — pure delegation, no EA-specific behaviour.
# ---------------------------------------------------------------------------

def create_access_token(user_id: str, egeria_user: str, egeria_password: str) -> str:
    """Create a signed JWT containing the user's Egeria credentials."""
    return _create_access_token(user_id, egeria_user, egeria_password, _base_config())


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    return _decode_token(token, _base_config())


# ---------------------------------------------------------------------------
# FastAPI helpers — reimplemented (not delegated) because they depend on
# EA's anonymous-mode bypass, which trellis_auth deliberately has no notion
# of (see module docstring).
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extract and validate the bearer token from the Authorization header.
    Returns the decoded payload dict, or None if absent / invalid.
    Never raises — callers decide whether anonymous is acceptable.
    """
    if not _auth_enabled():
        return {"sub": "anonymous", "egeria_user": "", "egeria_password": "", "anonymous": True}
    return _get_current_user(request, _base_config())


def require_egeria_user(request: Request) -> Dict[str, Any]:
    """
    Like get_current_user but raises HTTP 401 if not authenticated.
    Use as a FastAPI dependency for endpoints that need live Egeria access.
    """
    user = get_current_user(request)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="Authentication required. Please log in to access live Egeria features.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def is_authenticated(request: Request) -> bool:
    """Convenience helper for conditional auth checks in the query pipeline."""
    return get_current_user(request) is not None


# ---------------------------------------------------------------------------
# Per-user Egeria credential propagation
#
# The JWT already embeds the real egeria_user/egeria_password a user signed
# in with (see create_access_token above). Live-Egeria call sites (reports,
# Dr.Egeria actions, plan execution) must use THESE credentials rather than
# falling back to a static service account, so that live_reports/actions run
# as the actual signed-in user and not one shared identity for everyone.
# ---------------------------------------------------------------------------

def get_egeria_credentials(request: Request) -> Optional[EgeriaCredentials]:
    """
    Extract {user_id, password} from the request's JWT.
    Returns None only when there is no authenticated user (anonymous, no/invalid
    token) — callers decide whether to fall back via resolve_egeria_credentials().
    """
    user = get_current_user(request)
    if user is None:
        return None
    return {
        "user_id": user.get("egeria_user", ""),
        "password": user.get("egeria_password", ""),
    }


def resolve_egeria_credentials(creds: Optional[Dict[str, str]]) -> EgeriaCredentials:
    """
    Single fallback point for Egeria user_id/password: use the given per-request
    credentials if present and non-empty, otherwise fall back to the .env-backed
    service account (advisor.config.settings.egeria_user/egeria_password).

    Deliberately does NOT fall back to config/mcp_servers.json — that file's
    "EGERIA_USER"/"EGERIA_PASSWORD" env entries are unresolved template
    placeholders on a typical local checkout, never substituted anywhere.

    This fallback stays app-specific and is NOT in trellis_auth — see the
    module docstring above and docs/trellis-auth-extraction.md §4.
    """
    if creds and creds.get("user_id"):
        return {"user_id": creds["user_id"], "password": creds.get("password", "")}
    from advisor.config import settings
    return {"user_id": settings.egeria_user, "password": settings.egeria_password}


# ---------------------------------------------------------------------------
# Portal token exchange — pure delegation.
# ---------------------------------------------------------------------------

def exchange_portal_token(portal_token: str) -> Dict[str, Any]:
    """
    Validate a short-lived JWT issued by the Portal (shared HS256 secret).
    Returns decoded payload on success; raises HTTP 401 on failure.

    Expected portal token payload:
      { egeria_user: str, egeria_password: str, iat: int, exp: int }
    """
    return _exchange_portal_token(portal_token, _base_config())


# ---------------------------------------------------------------------------
# Egeria credential validation — delegates, but resolves EA's own connection
# config + service-account-sanity-check values first (trellis_auth never
# reads mcp_servers.json itself).
# ---------------------------------------------------------------------------

def validate_egeria_credentials(user_id: str, password: str) -> bool:
    """
    Validate credentials against the live Egeria instance by attempting to
    create a bearer token.  Returns True on success, False on failure.
    Falls back to checking against configured service account if Egeria is down.
    """
    return _validate_egeria_credentials(user_id, password, _validation_config())
