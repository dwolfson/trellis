"""Tests for GET /health/ready — the real DB-connectivity readiness check,
as distinct from GET /health (a pure liveness check that returns 200 even
when Postgres is unreachable — confirmed live to be exactly why a whole
Docker-down session read as "the buttons don't work" instead of an obvious
error)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from resource_explorer.web.app import app

client = TestClient(app)


class TestHealthRoute:
    def test_plain_health_never_touches_the_database(self):
        # Confirms /health stays a pure liveness check, unchanged —
        # /health/ready is the new one that actually exercises the DB.
        with patch("resource_explorer.registry.ProjectRegistry") as MockRegistry:
            resp = client.get("/health")
        assert resp.status_code == 200
        MockRegistry.assert_not_called()


class TestHealthReadyRoute:
    def test_returns_200_when_database_reachable(self):
        mock_registry = MagicMock()
        mock_conn = MagicMock()
        mock_registry._conn.return_value.__enter__.return_value = mock_conn
        with patch("resource_explorer.registry.ProjectRegistry", return_value=mock_registry):
            resp = client.get("/health/ready")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["database"] == "ok"
        mock_conn.execute.assert_called_once_with("SELECT 1")

    def test_returns_503_when_database_unreachable(self):
        with patch(
            "resource_explorer.registry.ProjectRegistry",
            side_effect=RuntimeError("connection refused"),
        ):
            resp = client.get("/health/ready")

        assert resp.status_code == 503
        data = resp.json()
        assert data["status"] == "error"
        assert data["database"] == "unreachable"
        assert "connection refused" in data["detail"]

    def test_returns_503_when_query_itself_fails(self):
        mock_registry = MagicMock()
        mock_registry._conn.side_effect = RuntimeError("could not connect to server")
        with patch("resource_explorer.registry.ProjectRegistry", return_value=mock_registry):
            resp = client.get("/health/ready")

        assert resp.status_code == 503
        assert "could not connect to server" in resp.json()["detail"]
