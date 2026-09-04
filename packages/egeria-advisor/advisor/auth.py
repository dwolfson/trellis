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

**Contract change (2026-09-04): the session JWT carries the user's Egeria
bearer token, never their password.** Previously `create_access_token` signed
the raw Egeria password into the HS256 token and `get_egeria_credentials`
handed `{user_id, password}` to every live-Egeria call site, which then called
`create_egeria_bearer_token(user_id, password)` again on each request. The
Portal never issued the password-shaped token this module's SSO route expected
— it issues `{sub, role, display_name, egeria_token, exp}` — so
`POST /api/auth/portal` was wired to a payload nothing produced. Now:

  * the login form exchanges the password for an Egeria bearer token exactly
    once (`trellis_auth.login_with_password`) and forgets it;
  * `get_egeria_credentials(request)` still returns a dict — same name, same
    call shape, so the ~15 `egeria_credentials=` call sites are unchanged — but
    it is now `{user_id, password: "", token}`. `password` is always empty for
    an authenticated user; `token` is what live call sites must use, via
    `trellis_auth.apply_token(client, token)`.

See `docs/runtime-architecture-plan.md` §4 and `docs/trellis-auth-extraction.md`.

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
    identity with NO config fallback. That decision is unchanged here: the
    fallback still only fires for an *anonymous* request, and it now yields a
    creds dict with an empty `token`, so a call site can tell "this is the
    service account" from "this is a signed-in person" by looking at `token`.

Public API:
  create_access_token(user_id, egeria_token, role=..., display_name=...) -> str
  decode_token(token) -> dict
  get_current_user(request) -> Optional[dict]   -- None for anonymous
  require_egeria_user(request) -> dict           -- raises HTTP 401 if missing
  exchange_portal_token(portal_token) -> dict    -- validates the Portal's real shape
  login_with_password(user_id, password) -> Optional[str]   -- Egeria bearer token
  validate_egeria_token(token) -> bool
  validate_egeria_credentials(user_id, password) -> bool
  get_egeria_token(request) -> Optional[str]
  get_egeria_credentials(request) -> Optional[EgeriaCredentials]  -- None if anonymous
  resolve_egeria_credentials(creds) -> EgeriaCredentials          -- falls back to service account
  apply_token(client, token) -> None
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional, TypedDict

from fastapi import HTTPException, Request
from loguru import logger

from trellis_auth import AuthConfig
from trellis_auth import apply_token  # re-exported for live call sites
from trellis_auth import create_access_token as _create_access_token
from trellis_auth import decode_token as _decode_token
from trellis_auth import exchange_portal_token as _exchange_portal_token
from trellis_auth import get_current_user as _get_current_user
from trellis_auth import login_with_password as _login_with_password
from trellis_auth import validate_egeria_credentials as _validate_egeria_credentials
from trellis_auth import validate_egeria_token as _validate_egeria_token

__all__ = [
    "EgeriaCredentials",
    "apply_token",
    "create_access_token",
    "decode_token",
    "get_current_user",
    "require_egeria_user",
    "is_authenticated",
    "get_egeria_token",
    "get_egeria_credentials",
    "resolve_egeria_credentials",
    "exchange_portal_token",
    "login_with_password",
    "validate_egeria_token",
    "validate_egeria_credentials",
]


class EgeriaCredentials(TypedDict):
    """What a live-Egeria call site gets for the current request.

    `token` is the Egeria bearer token of the signed-in user — the thing to
    authenticate a pyegeria client with (`apply_token`). `password` is retained
    only so that the one legitimately password-backed path (the .env service
    account, used for anonymous/background work) still has somewhere to put its
    value; it is always `""` for a signed-in user, because the session JWT no
    longer carries a password. `token` empty + `user_id` set means "service
    account", never "signed-in person with no token".
    """

    user_id: str
    password: str
    token: str


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
    """AuthConfig for the functions that talk to Egeria (`login_with_password`,
    `validate_egeria_token`, `validate_egeria_credentials`) — also carries the
    Egeria connection + service-account-sanity-check fields. Built lazily (and
    only when one of those is actually invoked) to preserve the original
    module's lazy `from advisor.mcp_config import ...` import, which avoids a
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

def create_access_token(
    user_id: str,
    egeria_token: str,
    role: str = "user",
    display_name: Optional[str] = None,
) -> str:
    """Create the session JWT carrying the user's Egeria bearer token.

    The JWT's `exp` is capped at the Egeria token's own expiry by
    `trellis_auth` — Egeria's tokens last one hour (measured 2026-09-04, see
    `trellis_auth.auth.EGERIA_TOKEN_TTL_SECONDS_OBSERVED`), well under EA's
    8-hour `jwt_ttl_hours`, so in practice the Egeria expiry is the session
    bound and refresh is a re-login.
    """
    return _create_access_token(
        user_id, egeria_token, _base_config(), role=role, display_name=display_name
    )


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
        return {
            "sub": "anonymous",
            "user_id": "anonymous",
            "role": "user",
            "display_name": "anonymous",
            "egeria_token": "",
            "anonymous": True,
        }
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
# Per-user Egeria token propagation
#
# The JWT embeds the Egeria bearer token the user's login (or the Portal's)
# obtained for them — never a password. Live-Egeria call sites (reports,
# Dr.Egeria actions, plan execution) must authenticate their pyegeria client
# with THIS token via apply_token(), so that live reads/writes run as the
# actual signed-in user and Egeria's own provenance records that person
# rather than one shared service identity.
# ---------------------------------------------------------------------------

def get_egeria_token(request: Request) -> Optional[str]:
    """The signed-in user's Egeria bearer token, or None when anonymous."""
    user = get_current_user(request)
    if user is None:
        return None
    return user.get("egeria_token") or None


def get_egeria_credentials(request: Request) -> Optional[EgeriaCredentials]:
    """
    Extract `{user_id, password, token}` from the request's JWT.

    `password` is always `""` — the JWT has carried a bearer token instead of a
    password since 2026-09-04. Returns None only when there is no authenticated
    user (anonymous, no/invalid token) — callers decide whether to fall back
    via resolve_egeria_credentials().
    """
    user = get_current_user(request)
    if user is None:
        return None
    return {
        "user_id": user.get("user_id") or user.get("sub", ""),
        "password": "",
        "token": user.get("egeria_token", ""),
    }


def resolve_egeria_credentials(creds: Optional[Dict[str, str]]) -> EgeriaCredentials:
    """
    Single fallback point for how a live Egeria call authenticates: use the
    per-request credentials if present, otherwise fall back to the .env-backed
    service account (advisor.config.settings.egeria_user/egeria_password).

    A signed-in request yields `token` set and `password` empty — the call site
    should hand `token` to `apply_token()`. The anonymous/background fallback
    yields `password` set and `token` empty, which is the one legitimately
    password-backed path.

    Deliberately does NOT fall back to config/mcp_servers.json — that file's
    "EGERIA_USER"/"EGERIA_PASSWORD" env entries are unresolved template
    placeholders on a typical local checkout, never substituted anywhere.

    This fallback stays app-specific and is NOT in trellis_auth — see the
    module docstring above and docs/trellis-auth-extraction.md §4. The
    2026-08-29 decision (artifact ownership requires an authenticated identity
    with no config fallback) is unaffected: the fallback still fires only for a
    request with no signed-in user at all.
    """
    if creds and creds.get("user_id"):
        return {
            "user_id": creds["user_id"],
            "password": creds.get("password", ""),
            "token": creds.get("token", ""),
        }
    from advisor.config import settings
    return {"user_id": settings.egeria_user, "password": settings.egeria_password, "token": ""}


# ---------------------------------------------------------------------------
# Portal token exchange — pure delegation.
# ---------------------------------------------------------------------------

def exchange_portal_token(portal_token: str) -> Dict[str, Any]:
    """
    Validate a short-lived JWT issued by the Portal (shared HS256 secret).
    Returns decoded payload on success; raises HTTP 401/400 on failure.

    Expected portal token payload — the shape the Portal actually issues
    (`demo_auth_handler.py::_make_jwt`):
      { sub: str, role: str, display_name: str, egeria_token: str, exp: int }
    """
    return _exchange_portal_token(portal_token, _base_config())


# ---------------------------------------------------------------------------
# Egeria login / token validation — delegates, but resolves EA's own connection
# config + service-account-sanity-check values first (trellis_auth never
# reads mcp_servers.json itself).
# ---------------------------------------------------------------------------

def login_with_password(user_id: str, password: str) -> Optional[str]:
    """Exchange an Egeria user id + password for a bearer token, once.

    Returns the token, or None when the credentials are bad / Egeria is
    unreachable. The caller mints the session JWT from the token and drops the
    password — this is the only point at which EA handles one.
    """
    return _login_with_password(user_id, password, _validation_config())


def validate_egeria_token(token: str) -> bool:
    """Check an Egeria bearer token with one cheap authenticated view-server call."""
    return _validate_egeria_token(token, _validation_config())


def validate_egeria_credentials(user_id: str, password: str) -> bool:
    """
    Validate credentials against the live Egeria instance by attempting to
    create a bearer token.  Returns True on success, False on failure.
    Falls back to checking against configured service account if Egeria is down.

    Prefer `login_with_password`, which keeps the token it just obtained.
    """
    return _validate_egeria_credentials(user_id, password, _validation_config())
