"""Login policy — shared, and required by default.

**Decided 2026-09-04 (project owner), superseding this package's original
"whether an app requires login at all is each app's own answer."** Both Trellis
apps require login, and the policy that says so lives *here* rather than being
re-decided in each app. See `docs/runtime-architecture-plan.md` §4 ("Login
policy: shared, and required") and `docs/trellis-auth-extraction.md` §7.

The mechanism is deliberately small:

  * `AuthPolicy` — a frozen dataclass: require login, a short allowlist of
    public paths, and one dev-only anonymous-read override.
  * `LoginRequiredMiddleware` — pure ASGI, no FastAPI dependency. Any request
    to a non-public path without a valid app JWT gets a `401` carrying
    `WWW-Authenticate: Bearer` and a JSON body.
  * `resolve_policy(app_prefix)` — the one place the environment is read, so
    both apps resolve the same knobs from the same variable names.

`config.py`'s "this package never reads the environment" rule still holds for
`AuthConfig`: connection settings and secrets stay app-resolved. `resolve_policy`
is the deliberate exception, and it exists *because* the policy is shared — two
apps reading two different env vars for "is login required" is exactly the drift
this decision removes.

Why a public-path allowlist rather than a private-path denylist: a route added
tomorrow must default to protected. A denylist fails open, an allowlist fails
closed, and the failure mode of an allowlist (a new health probe 401s) is loud
and harmless.

**The A2A agent cards and discovery index must stay public** so a client can
learn how to authenticate before it holds a token — pass them through
`extra_public_paths` (or `TRELLIS_PUBLIC_PATHS`) in the app that serves them.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, replace
from typing import Iterable, Optional, Tuple

import jwt

from trellis_auth.config import AuthConfig

logger = logging.getLogger(__name__)

__all__ = [
    "AuthPolicy",
    "LoginRequiredMiddleware",
    "DEFAULT_PUBLIC_PATHS",
    "OPENAPI_PUBLIC_PATHS",
    "DEFAULT_LOGIN_REQUIRED_MESSAGE",
    "resolve_policy",
    "env_flag",
]


#: Paths every Trellis app serves that must work before anyone has a token.
#:
#: An entry ending in ``/`` is a **prefix** match (``/static/`` covers
#: ``/static/app.js``); every other entry is an **exact** match, so
#: ``/health`` does not accidentally make ``/health-secrets`` public.
#: ``/health/ready`` is listed explicitly for that reason rather than relying
#: on a ``/health/`` prefix, which would also expose anything else nested
#: under it.
DEFAULT_PUBLIC_PATHS: Tuple[str, ...] = (
    "/health",
    "/health/ready",
    "/static/",
    "/api/auth/login",
    "/api/auth/portal",
    "/api/auth/logout",
    "/.well-known/",
    "/favicon.ico",
)

#: Added to the allowlist only when `expose_openapi` is true — the schema names
#: every route including the private ones, which is useful on a dev box and is
#: information disclosure anywhere else.
OPENAPI_PUBLIC_PATHS: Tuple[str, ...] = ("/docs", "/openapi.json")

DEFAULT_LOGIN_REQUIRED_MESSAGE = (
    "Authentication required. Sign in with your Egeria user id and password "
    "(POST /api/auth/login), or open this app from the Egeria Portal."
)


def env_flag(name: str) -> Optional[bool]:
    """Read a boolean env var, returning None when it is unset or empty.

    None rather than False, deliberately: the caller needs to tell "not set"
    (inherit the default, or the shared `TRELLIS_*` value) from "set to false".
    Truthy is exactly `"true"`/`"1"` case-insensitively, per the spec; anything
    else set to a non-empty value is false, and is logged, because a typo like
    `TRELLIS_ANONYMOUS_READ=yes` silently meaning "no" is the kind of quiet
    misconfiguration that only shows up as a support question.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return None
    value = raw.strip().lower()
    if value in ("true", "1"):
        return True
    if value not in ("false", "0"):
        logger.warning(
            "trellis-auth: %s=%r is not one of true/1/false/0 — treating it as false",
            name, raw,
        )
    return False


def _env_paths(name: str) -> Tuple[str, ...]:
    raw = os.environ.get(name, "")
    return tuple(p.strip() for p in raw.split(",") if p.strip())


@dataclass(frozen=True)
class AuthPolicy:
    """Whether this app requires a signed-in user, and what is exempt.

    `require_login` defaults to True — that is the decision. Setting it False
    turns the middleware into a no-op and is not a supported deployment mode;
    it exists so a test, or a one-off local experiment, can opt out explicitly
    rather than by deleting the middleware.

    `anonymous_read` is the dev-box override (`TRELLIS_ANONYMOUS_READ=true`):
    unauthenticated GET/HEAD is allowed, unauthenticated writes are still 401.
    It is *not* "auth off" — a read-only anonymous user cannot create anything,
    so nothing lands in Egeria or in a namespace without an identity behind it.
    That asymmetry is the whole point: the 2026-08-29 decision that artifact
    ownership requires an authenticated identity survives the override.
    """

    require_login: bool = True
    public_paths: Tuple[str, ...] = DEFAULT_PUBLIC_PATHS
    anonymous_read: bool = False
    login_required_message: str = DEFAULT_LOGIN_REQUIRED_MESSAGE

    #: Methods an `anonymous_read` deployment lets through unauthenticated.
    #: OPTIONS is included because a CORS preflight carries no Authorization
    #: header by definition — 401ing it breaks cross-origin login itself. It is
    #: exempt regardless of `anonymous_read` (see `is_exempt_method`).
    read_methods: Tuple[str, ...] = ("GET", "HEAD")

    def __post_init__(self) -> None:
        if not isinstance(self.public_paths, tuple):
            # A list would make the frozen dataclass unhashable and lets a
            # caller mutate the allowlist after the middleware read it.
            object.__setattr__(self, "public_paths", tuple(self.public_paths))
        if not isinstance(self.read_methods, tuple):
            object.__setattr__(self, "read_methods", tuple(self.read_methods))

    # -- path / method classification ---------------------------------------

    def is_public(self, path: str) -> bool:
        """True when `path` is on the allowlist (exact, or under a `/` prefix).

        `"/"` is the one entry that cannot be a prefix — read that way it makes
        every path public, which is the entire policy switched off by an
        allowlist entry that looks like the most innocuous one there is. An app
        listing `"/"` means its SPA shell, so it is matched exactly.
        """
        for entry in self.public_paths:
            if len(entry) > 1 and entry.endswith("/"):
                if path.startswith(entry):
                    return True
            elif path == entry:
                return True
        return False

    def is_exempt_method(self, method: str) -> bool:
        """True when this method never needs authentication.

        Only CORS preflight: a browser sends `OPTIONS` without the
        `Authorization` header, so a 401 here would break the very login the
        header is for. Every other method is subject to the policy.
        """
        return method.upper() == "OPTIONS"

    def allows_anonymous(self, method: str) -> bool:
        """True when an unauthenticated request with this method may proceed."""
        if not self.require_login:
            return True
        if not self.anonymous_read:
            return False
        return method.upper() in self.read_methods

    def with_public_paths(self, extra: Iterable[str]) -> "AuthPolicy":
        """A copy with `extra` appended to the allowlist (duplicates dropped)."""
        seen = list(self.public_paths)
        for entry in extra:
            if entry and entry not in seen:
                seen.append(entry)
        return replace(self, public_paths=tuple(seen))

    def describe(self) -> str:
        """One line naming the active mode, for the startup log."""
        if not self.require_login:
            return "login NOT required (require_login=false)"
        if self.anonymous_read:
            return "login required for writes; anonymous GET/HEAD allowed (TRELLIS_ANONYMOUS_READ)"
        return "login required for every non-public path"


# ---------------------------------------------------------------------------
# Environment resolution
# ---------------------------------------------------------------------------

def resolve_policy(
    app_prefix: str,
    *,
    extra_public_paths: Iterable[str] = (),
    login_required_message: Optional[str] = None,
) -> AuthPolicy:
    """Build an `AuthPolicy` from the environment, the same way in every app.

    Each knob is read first as ``TRELLIS_<NAME>`` (the shared, deployment-wide
    value) and then as ``<APP_PREFIX>_<NAME>``; **the app-specific one wins when
    it is set**, because the more specific setting is the one an operator
    reached for deliberately. An unset or empty variable is "not set" and falls
    through, so `ADVISOR_ANONYMOUS_READ=` does not mask `TRELLIS_ANONYMOUS_READ=true`.

    Variables read, for `app_prefix="ADVISOR"`:

    ==================================  ==============================================
    ``TRELLIS_REQUIRE_LOGIN``           default true; false disables the middleware
    ``ADVISOR_REQUIRE_LOGIN``
    ``TRELLIS_ANONYMOUS_READ``          default false; dev-only, GET/HEAD without a token
    ``ADVISOR_ANONYMOUS_READ``
    ``TRELLIS_EXPOSE_OPENAPI``          default false; adds /docs and /openapi.json
    ``ADVISOR_EXPOSE_OPENAPI``
    ``TRELLIS_PUBLIC_PATHS``            comma-separated, *added* to the defaults
    ``ADVISOR_PUBLIC_PATHS``
    ==================================  ==============================================

    `TRELLIS_PUBLIC_PATHS` is additive rather than an override in both places:
    an operator adding an A2A discovery path must not silently drop `/health`
    or the login route and lock the deployment out of its own login form.
    """
    prefix = app_prefix.strip().upper().rstrip("_")

    def flag(name: str, default: bool) -> bool:
        shared = env_flag(f"TRELLIS_{name}")
        specific = env_flag(f"{prefix}_{name}") if prefix else None
        if specific is not None:
            return specific
        if shared is not None:
            return shared
        return default

    require_login = flag("REQUIRE_LOGIN", True)
    anonymous_read = flag("ANONYMOUS_READ", False)
    expose_openapi = flag("EXPOSE_OPENAPI", False)

    paths = list(DEFAULT_PUBLIC_PATHS)
    if expose_openapi:
        paths.extend(OPENAPI_PUBLIC_PATHS)
    for entry in (*_env_paths("TRELLIS_PUBLIC_PATHS"),
                  *(_env_paths(f"{prefix}_PUBLIC_PATHS") if prefix else ()),
                  *extra_public_paths):
        if entry and entry not in paths:
            paths.append(entry)

    return AuthPolicy(
        require_login=require_login,
        public_paths=tuple(paths),
        anonymous_read=anonymous_read,
        login_required_message=login_required_message or DEFAULT_LOGIN_REQUIRED_MESSAGE,
    )


# ---------------------------------------------------------------------------
# The middleware
# ---------------------------------------------------------------------------

class LoginRequiredMiddleware:
    """Pure-ASGI gate: no valid app JWT, no access to a non-public path.

    Pure ASGI rather than starlette's `BaseHTTPMiddleware` for two reasons.
    It must run *outermost*, before anything that reads a request body or
    opens a streaming response, and `BaseHTTPMiddleware` wraps every response
    in a task/queue pair that has a documented history of interacting badly
    with streaming endpoints — EA serves `/api/query/stream`. And rejecting
    an unauthenticated request should not cost a `Request` object.

    It validates the *app* JWT (HS256, our own secret), not the Egeria bearer
    token inside it. That is the right check here: the app JWT's `exp` is
    already capped at the Egeria token's own expiry by `create_access_token`,
    so an app JWT that still verifies carries an Egeria token that has not
    expired either. Whether Egeria still *accepts* that token is Egeria's
    answer to give, on the call that uses it — not something to spend a
    view-server round-trip on for every request.
    """

    def __init__(self, app, config: AuthConfig, policy: AuthPolicy) -> None:
        self.app = app
        self.config = config
        self.policy = policy
        # Logged once, at construction, so a deployment's mode is visible in
        # the first lines of its log rather than inferred from a 401 later.
        logger.info("trellis-auth: %s", policy.describe())
        if policy.anonymous_read:
            logger.warning(
                "trellis-auth: TRELLIS_ANONYMOUS_READ is ON — unauthenticated GET/HEAD is "
                "allowed on every path. This is a development-box override and is not a "
                "supported deployment mode; writes still require a signed-in user."
            )
        if not policy.require_login:
            logger.warning(
                "trellis-auth: require_login is OFF — every path is open. This is not a "
                "supported deployment mode."
            )

    # -- helpers -------------------------------------------------------------

    def _has_valid_token(self, scope) -> bool:
        for key, value in scope.get("headers") or ():
            if key.lower() != b"authorization":
                continue
            try:
                header = value.decode("latin-1")
            except Exception:  # pragma: no cover - headers are latin-1 by spec
                return False
            if not header.startswith("Bearer "):
                return False
            token = header[len("Bearer "):].strip()
            if not token:
                return False
            try:
                jwt.decode(token, self.config.jwt_secret, algorithms=[self.config.jwt_algorithm])
                return True
            except jwt.PyJWTError as exc:
                logger.debug("trellis-auth: rejecting request — invalid app JWT (%s)", exc)
                return False
        return False

    async def _deny(self, send, path: str, method: str) -> None:
        logger.info("trellis-auth: 401 %s %s (no valid session)", method, path)
        body = json.dumps({
            "detail": self.policy.login_required_message,
            "error": "login_required",
            "login_url": "/api/auth/login",
        }).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 401,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
                # Names the scheme so a CLI/A2A client knows what to present,
                # and is what makes this a well-formed 401 rather than a 403
                # wearing the wrong number.
                (b"www-authenticate", b"Bearer"),
            ],
        })
        await send({"type": "http.response.body", "body": body})

    # -- ASGI ----------------------------------------------------------------

    async def __call__(self, scope, receive, send):
        # Non-HTTP scopes (lifespan, and websockets if an app ever adds one)
        # pass straight through: there is nothing to 401 with here, and a
        # websocket handshake must be rejected with a close frame, not a
        # response — an app adding one needs its own check.
        if scope["type"] != "http" or not self.policy.require_login:
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = (scope.get("method") or "GET").upper()

        if self.policy.is_exempt_method(method) or self.policy.is_public(path):
            await self.app(scope, receive, send)
            return

        if self._has_valid_token(scope):
            await self.app(scope, receive, send)
            return

        if self.policy.allows_anonymous(method):
            await self.app(scope, receive, send)
            return

        await self._deny(send, path, method)
