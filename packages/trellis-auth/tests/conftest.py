from __future__ import annotations

import pytest

from trellis_auth import AuthConfig


@pytest.fixture
def config() -> AuthConfig:
    return AuthConfig(
        jwt_secret="test-secret",
        jwt_ttl_hours=8,
        portal_secret="portal-secret",
    )


class FakeRequest:
    """Minimal stand-in for starlette.requests.Request — only .headers is used."""

    def __init__(self, headers: dict | None = None):
        self.headers = headers or {}


@pytest.fixture
def make_request():
    def _make(authorization: str | None = None):
        headers = {}
        if authorization is not None:
            headers["Authorization"] = authorization
        return FakeRequest(headers)

    return _make
