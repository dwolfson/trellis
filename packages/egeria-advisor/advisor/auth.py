"""
JWT-based authentication for Egeria Advisor.

Public API:
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

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

import jwt
from fastapi import HTTPException, Request
from loguru import logger

# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------

_CFG_PATH  = Path(__file__).parent.parent / "config" / "advisor.yaml"
_MCP_PATH  = Path(__file__).parent.parent / "config" / "mcp_servers.json"

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


# ---------------------------------------------------------------------------
# Token creation / decoding
# ---------------------------------------------------------------------------

_ALG = "HS256"


def create_access_token(user_id: str, egeria_user: str, egeria_password: str) -> str:
    """Create a signed JWT containing the user's Egeria credentials."""
    now = datetime.now(timezone.utc)
    payload = {
        "sub":            user_id,
        "egeria_user":    egeria_user,
        "egeria_password": egeria_password,
        "iat":            now,
        "exp":            now + timedelta(hours=_jwt_ttl_hours()),
    }
    return jwt.encode(payload, _jwt_secret(), algorithm=_ALG)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT. Raises jwt.PyJWTError on failure."""
    return jwt.decode(token, _jwt_secret(), algorithms=[_ALG])


# ---------------------------------------------------------------------------
# FastAPI helpers
# ---------------------------------------------------------------------------

def get_current_user(request: Request) -> Optional[Dict[str, Any]]:
    """
    Extract and validate the bearer token from the Authorization header.
    Returns the decoded payload dict, or None if absent / invalid.
    Never raises — callers decide whether anonymous is acceptable.
    """
    if not _auth_enabled():
        return {"sub": "anonymous", "egeria_user": "", "egeria_password": "", "anonymous": True}

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[len("Bearer "):]
    try:
        return decode_token(token)
    except jwt.PyJWTError as exc:
        logger.debug(f"auth: invalid token — {exc}")
        return None


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

class EgeriaCredentials(TypedDict):
    user_id: str
    password: str


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
    """
    if creds and creds.get("user_id"):
        return {"user_id": creds["user_id"], "password": creds.get("password", "")}
    from advisor.config import settings
    return {"user_id": settings.egeria_user, "password": settings.egeria_password}


# ---------------------------------------------------------------------------
# Portal token exchange
# ---------------------------------------------------------------------------

def exchange_portal_token(portal_token: str) -> Dict[str, Any]:
    """
    Validate a short-lived JWT issued by the Portal (shared HS256 secret).
    Returns decoded payload on success; raises HTTP 401 on failure.

    Expected portal token payload:
      { egeria_user: str, egeria_password: str, iat: int, exp: int }
    """
    secret = _portal_secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Portal SSO is not configured on this server.")
    try:
        payload = jwt.decode(portal_token, secret, algorithms=[_ALG])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Portal token has expired. Please reload from the Portal.")
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"Invalid portal token: {exc}")


# ---------------------------------------------------------------------------
# Egeria credential validation
# ---------------------------------------------------------------------------

def validate_egeria_credentials(user_id: str, password: str) -> bool:
    """
    Validate credentials against the live Egeria instance by attempting to
    create a bearer token.  Returns True on success, False on failure.
    Falls back to checking against configured service account if Egeria is down.
    """
    try:
        from advisor.mcp_config import get_pyegeria_platform_config
        conn = get_pyegeria_platform_config()
        view_server  = conn["view_server"]
        platform_url = conn["platform_url"]

        cfg = json.loads(_MCP_PATH.read_text())
        env = cfg.get("mcpServers", {}).get("pyegeria", {}).get("env", {})
        svc_user     = env.get("EGERIA_USER", "")
        svc_pwd      = env.get("EGERIA_PASSWORD", "")

        if not view_server or not platform_url:
            logger.warning("auth: Egeria connection config incomplete — falling back to service account check")
            return user_id == svc_user and password == svc_pwd

        from pyegeria.egeria_tech_client import EgeriaTech
        client = EgeriaTech(
            view_server=view_server,
            platform_url=platform_url,
            user_id=user_id,
            user_pwd=password,
        )
        client.create_egeria_bearer_token(user_id, password)
        logger.info(f"auth: credentials validated for user {user_id!r}")
        return True

    except Exception as exc:
        logger.info(f"auth: credential validation failed for {user_id!r} — {type(exc).__name__}: {exc}")
        return False
