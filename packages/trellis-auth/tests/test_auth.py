from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.exceptions import HTTPException

from trellis_auth import (
    AuthConfig,
    create_access_token,
    decode_token,
    exchange_portal_token,
    get_current_user,
    get_egeria_credentials,
    is_authenticated,
    require_egeria_user,
    validate_egeria_credentials,
)


# ---------------------------------------------------------------------------
# Token round-trip
# ---------------------------------------------------------------------------

def test_create_and_decode_round_trip(config):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    payload = decode_token(token, config)

    assert payload["sub"] == "dan"
    assert payload["egeria_user"] == "dan.egeria"
    assert payload["egeria_password"] == "hunter2"
    assert "exp" in payload and "iat" in payload


def test_decode_expired_token(config):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": "dan",
        "egeria_user": "dan.egeria",
        "egeria_password": "hunter2",
        "iat": now - timedelta(hours=10),
        "exp": now - timedelta(hours=2),
    }
    expired = jwt.encode(payload, config.jwt_secret, algorithm=config.jwt_algorithm)

    with pytest.raises(jwt.ExpiredSignatureError):
        decode_token(expired, config)


def test_decode_invalid_signature(config):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    wrong_config = AuthConfig(jwt_secret="a-different-secret")

    with pytest.raises(jwt.InvalidSignatureError):
        decode_token(token, wrong_config)


# ---------------------------------------------------------------------------
# get_current_user / require_egeria_user / is_authenticated
# ---------------------------------------------------------------------------

def test_get_current_user_missing_header_returns_none(config, make_request):
    request = make_request(authorization=None)
    assert get_current_user(request, config) is None


def test_get_current_user_malformed_header_returns_none(config, make_request):
    # No "Bearer " prefix at all.
    request = make_request(authorization="Basic dXNlcjpwYXNz")
    assert get_current_user(request, config) is None


def test_get_current_user_invalid_token_returns_none(config, make_request):
    request = make_request(authorization="Bearer not-a-real-jwt")
    assert get_current_user(request, config) is None


def test_get_current_user_valid_token(config, make_request):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    request = make_request(authorization=f"Bearer {token}")

    user = get_current_user(request, config)

    assert user is not None
    assert user["sub"] == "dan"


def test_require_egeria_user_raises_401_when_absent(config, make_request):
    request = make_request(authorization=None)
    with pytest.raises(HTTPException) as excinfo:
        require_egeria_user(request, config)
    assert excinfo.value.status_code == 401


def test_require_egeria_user_returns_payload_when_present(config, make_request):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    request = make_request(authorization=f"Bearer {token}")

    user = require_egeria_user(request, config)

    assert user["sub"] == "dan"


def test_is_authenticated(config, make_request):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    assert is_authenticated(make_request(authorization=f"Bearer {token}"), config) is True
    assert is_authenticated(make_request(authorization=None), config) is False


# ---------------------------------------------------------------------------
# get_egeria_credentials
# ---------------------------------------------------------------------------

def test_get_egeria_credentials_present(config, make_request):
    token = create_access_token("dan", "dan.egeria", "hunter2", config)
    request = make_request(authorization=f"Bearer {token}")

    creds = get_egeria_credentials(request, config)

    assert creds == {"user_id": "dan.egeria", "password": "hunter2"}


def test_get_egeria_credentials_absent_returns_none(config, make_request):
    request = make_request(authorization=None)
    assert get_egeria_credentials(request, config) is None


# ---------------------------------------------------------------------------
# Portal token exchange
# ---------------------------------------------------------------------------

def test_exchange_portal_token_success(config):
    now = datetime.now(timezone.utc)
    portal_payload = {
        "egeria_user": "dan.egeria",
        "egeria_password": "hunter2",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    portal_token = jwt.encode(portal_payload, config.portal_secret, algorithm=config.jwt_algorithm)

    result = exchange_portal_token(portal_token, config)

    assert result["egeria_user"] == "dan.egeria"
    assert result["egeria_password"] == "hunter2"


def test_exchange_portal_token_not_configured():
    config = AuthConfig(jwt_secret="test-secret", portal_secret="")

    with pytest.raises(HTTPException) as excinfo:
        exchange_portal_token("whatever", config)
    assert excinfo.value.status_code == 503


def test_exchange_portal_token_expired(config):
    now = datetime.now(timezone.utc)
    portal_payload = {
        "egeria_user": "dan.egeria",
        "egeria_password": "hunter2",
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(minutes=1),
    }
    expired = jwt.encode(portal_payload, config.portal_secret, algorithm=config.jwt_algorithm)

    with pytest.raises(HTTPException) as excinfo:
        exchange_portal_token(expired, config)
    assert excinfo.value.status_code == 401
    assert "expired" in excinfo.value.detail.lower()


def test_exchange_portal_token_wrong_secret(config):
    now = datetime.now(timezone.utc)
    portal_payload = {
        "egeria_user": "dan.egeria",
        "egeria_password": "hunter2",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }
    signed_wrong = jwt.encode(portal_payload, "not-the-portal-secret", algorithm=config.jwt_algorithm)

    with pytest.raises(HTTPException) as excinfo:
        exchange_portal_token(signed_wrong, config)
    assert excinfo.value.status_code == 401


# ---------------------------------------------------------------------------
# validate_egeria_credentials — pyegeria client mocked, never a live server
# ---------------------------------------------------------------------------

def test_validate_egeria_credentials_service_account_match_when_unconfigured():
    config = AuthConfig(
        jwt_secret="test-secret",
        egeria_view_server="",
        egeria_platform_url="",
        egeria_service_account_user="svc",
        egeria_service_account_password="svc-pwd",
    )

    assert validate_egeria_credentials("svc", "svc-pwd", config) is True
    assert validate_egeria_credentials("svc", "wrong-pwd", config) is False


def test_validate_egeria_credentials_success_via_mocked_client(monkeypatch):
    config = AuthConfig(
        jwt_secret="test-secret",
        egeria_view_server="qs-view-server",
        egeria_platform_url="https://localhost:9443",
    )

    class _FakeEgeriaTech:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def create_egeria_bearer_token(self, user_id, password):
            return "fake-bearer-token"

    fake_module = type("module", (), {"EgeriaTech": _FakeEgeriaTech})
    monkeypatch.setitem(
        __import__("sys").modules, "pyegeria.egeria_tech_client", fake_module
    )

    assert validate_egeria_credentials("dan.egeria", "hunter2", config) is True


def test_validate_egeria_credentials_failure_via_mocked_client(monkeypatch):
    config = AuthConfig(
        jwt_secret="test-secret",
        egeria_view_server="qs-view-server",
        egeria_platform_url="https://localhost:9443",
    )

    class _FakeEgeriaTech:
        def __init__(self, **kwargs):
            pass

        def create_egeria_bearer_token(self, user_id, password):
            raise RuntimeError("invalid credentials")

    fake_module = type("module", (), {"EgeriaTech": _FakeEgeriaTech})
    monkeypatch.setitem(
        __import__("sys").modules, "pyegeria.egeria_tech_client", fake_module
    )

    assert validate_egeria_credentials("dan.egeria", "wrong", config) is False


def test_validate_egeria_credentials_missing_pyegeria_returns_false(monkeypatch):
    """pyegeria is an optional extra — a missing install must degrade to
    False (caught by the broad except), not raise ImportError."""
    config = AuthConfig(
        jwt_secret="test-secret",
        egeria_view_server="qs-view-server",
        egeria_platform_url="https://localhost:9443",
    )
    monkeypatch.setitem(__import__("sys").modules, "pyegeria.egeria_tech_client", None)

    assert validate_egeria_credentials("dan.egeria", "hunter2", config) is False
