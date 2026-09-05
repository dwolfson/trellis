"""Tests for the shared login policy and its ASGI middleware.

The middleware is exercised through a real ASGI call rather than by poking at
`AuthPolicy.is_public()` alone: the thing that must hold is "an unauthenticated
request to a private path receives a 401 with `WWW-Authenticate: Bearer`", and
only driving the ASGI callable proves the response is actually shaped that way.
A helper collects the ASGI messages instead of pulling in a test client, which
would add a dependency for what is three lines of protocol.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from trellis_auth import AuthConfig, AuthPolicy, LoginRequiredMiddleware, create_access_token
from trellis_auth.policy import (
    DEFAULT_PUBLIC_PATHS,
    OPENAPI_PUBLIC_PATHS,
    resolve_policy,
)

# An Egeria bearer token stand-in with no `exp`, so `create_access_token` leaves
# the app JWT's own TTL alone and the token stays valid for the test run.
FAKE_EGERIA_TOKEN = "opaque-egeria-token"


# ---------------------------------------------------------------------------
# ASGI plumbing
# ---------------------------------------------------------------------------

async def _inner_app(scope, receive, send):
    """The app behind the middleware — answers 200 with a marker body."""
    await send({
        "type": "http.response.start",
        "status": 200,
        "headers": [(b"content-type", b"text/plain")],
    })
    await send({"type": "http.response.body", "body": b"reached-the-app"})


def call(middleware, path: str, method: str = "GET", authorization: str | None = None):
    """Drive one HTTP request through `middleware`; return (status, headers, body)."""
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode()))
    scope = {"type": "http", "path": path, "method": method, "headers": headers}

    sent: list = []

    async def send(message):
        sent.append(message)

    async def receive():  # pragma: no cover - nothing here reads a body
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(middleware(scope, receive, send))

    start = next(m for m in sent if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    header_map = {k.decode().lower(): v.decode() for k, v in start["headers"]}
    return start["status"], header_map, body


@pytest.fixture
def middleware(config):
    def _build(policy: AuthPolicy | None = None):
        return LoginRequiredMiddleware(_inner_app, config, policy or AuthPolicy())
    return _build


@pytest.fixture
def valid_auth_header(config):
    token = create_access_token("peterprofile", FAKE_EGERIA_TOKEN, config)
    return f"Bearer {token}"


# ---------------------------------------------------------------------------
# The default policy: login required
# ---------------------------------------------------------------------------

def test_private_path_without_a_token_is_401(middleware):
    status, headers, body = call(middleware(), "/api/plans")
    assert status == 401
    assert headers["www-authenticate"] == "Bearer"
    payload = json.loads(body)
    assert payload["error"] == "login_required"
    assert payload["login_url"] == "/api/auth/login"
    assert "Authentication required" in payload["detail"]


def test_private_path_with_a_valid_jwt_reaches_the_app(middleware, valid_auth_header):
    status, _headers, body = call(middleware(), "/api/plans", authorization=valid_auth_header)
    assert status == 200
    assert body == b"reached-the-app"


@pytest.mark.parametrize("path", list(DEFAULT_PUBLIC_PATHS[:4]) + ["/static/app.js", "/.well-known/agent.json"])
def test_public_paths_pass_without_a_token(middleware, path):
    status, _headers, _body = call(middleware(), path)
    assert status == 200


def test_public_prefix_does_not_leak_to_a_sibling_path(middleware):
    """`/health` is exact, so a route that merely starts with it stays private.

    This is the failure an allowlist of bare prefixes would have: `/health`
    matching `/healthz-internal-dump` is a hole nobody would notice until it
    was used.
    """
    status, _headers, _body = call(middleware(), "/health-internal")
    assert status == 401


def test_a_garbage_or_foreign_token_is_401(middleware):
    status, _headers, _body = call(middleware(), "/api/plans", authorization="Bearer not-a-jwt")
    assert status == 401


def test_a_token_signed_with_another_secret_is_401(middleware):
    other = AuthConfig(jwt_secret="a-completely-different-secret-value")
    forged = create_access_token("mallory", FAKE_EGERIA_TOKEN, other)
    status, _headers, _body = call(middleware(), "/api/plans", authorization=f"Bearer {forged}")
    assert status == 401


def test_an_expired_app_jwt_is_401(config, middleware):
    """An app JWT whose `exp` has passed must not open the door.

    Built by capping against an already-expired Egeria token, which is the
    real-world route to this state: `create_access_token` takes the Egeria
    token's expiry when it is the earlier one.
    """
    import jwt as pyjwt
    expired_egeria = pyjwt.encode({"sub": "peterprofile", "exp": 1_000_000_000}, "irrelevant")
    token = create_access_token("peterprofile", expired_egeria, config)
    status, _headers, _body = call(middleware(), "/api/plans", authorization=f"Bearer {token}")
    assert status == 401


def test_options_preflight_is_never_challenged(middleware):
    """A CORS preflight carries no Authorization header, by definition."""
    status, _headers, _body = call(middleware(), "/api/plans", method="OPTIONS")
    assert status == 200


def test_require_login_false_disables_the_gate(middleware):
    status, _headers, _body = call(middleware(AuthPolicy(require_login=False)), "/api/plans")
    assert status == 200


def test_non_http_scopes_pass_through(config):
    """Lifespan startup must not be intercepted — there is nothing to 401."""
    mw = LoginRequiredMiddleware(_inner_app, config, AuthPolicy())
    seen = {}

    async def inner(scope, receive, send):
        seen["type"] = scope["type"]

    mw.app = inner
    asyncio.run(mw({"type": "lifespan"}, None, None))
    assert seen["type"] == "lifespan"


# ---------------------------------------------------------------------------
# anonymous_read: reads through, writes still challenged
# ---------------------------------------------------------------------------

@pytest.fixture
def anon_policy():
    return AuthPolicy(anonymous_read=True)


@pytest.mark.parametrize("method", ["GET", "HEAD"])
def test_anonymous_read_lets_reads_through(middleware, anon_policy, method):
    status, _headers, _body = call(middleware(anon_policy), "/api/plans", method=method)
    assert status == 200


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_anonymous_read_still_blocks_writes(middleware, anon_policy, method):
    """The asymmetry is the point: nothing gets created without an identity."""
    status, headers, _body = call(middleware(anon_policy), "/api/plans", method=method)
    assert status == 401
    assert headers["www-authenticate"] == "Bearer"


def test_anonymous_read_still_admits_an_authenticated_write(middleware, anon_policy, valid_auth_header):
    status, _headers, _body = call(
        middleware(anon_policy), "/api/plans", method="POST", authorization=valid_auth_header
    )
    assert status == 200


def test_anonymous_read_logs_a_warning(config, caplog):
    with caplog.at_level("WARNING", logger="trellis_auth.policy"):
        LoginRequiredMiddleware(_inner_app, config, AuthPolicy(anonymous_read=True))
    assert any("TRELLIS_ANONYMOUS_READ is ON" in r.message for r in caplog.records)


def test_default_policy_logs_its_mode_once_at_startup(config, caplog):
    with caplog.at_level("INFO", logger="trellis_auth.policy"):
        LoginRequiredMiddleware(_inner_app, config, AuthPolicy())
    modes = [r for r in caplog.records if "login required for every non-public path" in r.message]
    assert len(modes) == 1
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


# ---------------------------------------------------------------------------
# resolve_policy: precedence
# ---------------------------------------------------------------------------

def _clear_env(monkeypatch):
    for var in (
        "TRELLIS_REQUIRE_LOGIN", "ADVISOR_REQUIRE_LOGIN",
        "TRELLIS_ANONYMOUS_READ", "ADVISOR_ANONYMOUS_READ",
        "TRELLIS_EXPOSE_OPENAPI", "ADVISOR_EXPOSE_OPENAPI",
        "TRELLIS_PUBLIC_PATHS", "ADVISOR_PUBLIC_PATHS",
    ):
        monkeypatch.delenv(var, raising=False)


def test_defaults_are_require_login_and_no_anonymous_read(monkeypatch):
    _clear_env(monkeypatch)
    policy = resolve_policy("ADVISOR")
    assert policy.require_login is True
    assert policy.anonymous_read is False
    assert policy.public_paths == DEFAULT_PUBLIC_PATHS


@pytest.mark.parametrize("raw,expected", [("true", True), ("TRUE", True), ("1", True),
                                          ("false", False), ("0", False), ("yes", False)])
def test_anonymous_read_only_accepts_true_or_one(monkeypatch, raw, expected):
    """`yes` is false, deliberately — and warns rather than silently differing."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", raw)
    assert resolve_policy("ADVISOR").anonymous_read is expected


def test_shared_trellis_var_applies_when_no_app_var_is_set(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    assert resolve_policy("ADVISOR").anonymous_read is True
    assert resolve_policy("RE").anonymous_read is True   # both apps resolve the same way


def test_app_specific_var_wins_over_the_shared_one(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setenv("ADVISOR_ANONYMOUS_READ", "false")
    assert resolve_policy("ADVISOR").anonymous_read is False
    assert resolve_policy("RE").anonymous_read is True   # unaffected


def test_an_empty_app_var_does_not_mask_the_shared_one(monkeypatch):
    """`ADVISOR_ANONYMOUS_READ=` is "not set", not "set to false".

    Otherwise an env file that declares every variable and leaves some blank —
    the normal shape of a `.env.example` copied into place — would silently
    override the deployment-wide setting with a default.
    """
    _clear_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setenv("ADVISOR_ANONYMOUS_READ", "")
    assert resolve_policy("ADVISOR").anonymous_read is True


def test_require_login_can_be_turned_off_by_env(monkeypatch):
    _clear_env(monkeypatch)
    monkeypatch.setenv("ADVISOR_REQUIRE_LOGIN", "false")
    assert resolve_policy("ADVISOR").require_login is False


def test_openapi_paths_are_public_only_when_exposed(monkeypatch):
    _clear_env(monkeypatch)
    assert not set(OPENAPI_PUBLIC_PATHS) & set(resolve_policy("ADVISOR").public_paths)
    monkeypatch.setenv("TRELLIS_EXPOSE_OPENAPI", "true")
    assert set(OPENAPI_PUBLIC_PATHS) <= set(resolve_policy("ADVISOR").public_paths)


def test_public_paths_env_is_additive_not_a_replacement(monkeypatch):
    """An operator adding an A2A card must not delete the login route."""
    _clear_env(monkeypatch)
    monkeypatch.setenv("TRELLIS_PUBLIC_PATHS", "/a2a/agent.json, /a2a/index")
    policy = resolve_policy("ADVISOR")
    assert "/a2a/agent.json" in policy.public_paths
    assert "/a2a/index" in policy.public_paths
    assert set(DEFAULT_PUBLIC_PATHS) <= set(policy.public_paths)


def test_extra_public_paths_argument_is_merged_without_duplicates(monkeypatch):
    _clear_env(monkeypatch)
    policy = resolve_policy("ADVISOR", extra_public_paths=["/api/auth/defaults", "/health"])
    assert policy.public_paths.count("/health") == 1
    assert "/api/auth/defaults" in policy.public_paths
