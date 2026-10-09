"""Parity P1 round 2: admin-only Egeria-writing routes, and one bootstrap heal at a time."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app

ADMIN = "resource_explorer.web.admin_auth.is_admin_request"


@pytest.fixture()
def client():
    return TestClient(app)


def _admin(monkeypatch, value):
    monkeypatch.setattr(ADMIN, lambda *a, **k: value)


class TestBootstrapRun:
    def test_non_admin_is_refused_and_nothing_runs(self, client, monkeypatch):
        _admin(monkeypatch, False)
        with patch("resource_explorer.bootstrap.check_and_heal") as heal:
            res = client.post("/api/bootstrap/run", json={"force": False})
        assert res.status_code == 403
        heal.assert_not_called()

    def test_refused_with_409_while_a_heal_is_reinitializing(self, client, monkeypatch):
        _admin(monkeypatch, True)
        monkeypatch.setattr("resource_explorer.bootstrap._reinitializing", True)
        with patch("resource_explorer.bootstrap.check_and_heal") as heal:
            res = client.post("/api/bootstrap/run", json={})
        assert res.status_code == 409 and "already running" in res.json()["detail"]
        heal.assert_not_called()

    def test_refused_with_409_while_another_manual_run_holds_the_lock(self, client, monkeypatch):
        _admin(monkeypatch, True)
        from resource_explorer.web.routes import bootstrap as route
        assert route._run_lock.acquire(blocking=False)
        try:
            with patch("resource_explorer.bootstrap.check_and_heal") as heal:
                res = client.post("/api/bootstrap/run", json={})
            assert res.status_code == 409
            heal.assert_not_called()
        finally:
            route._run_lock.release()

    def test_the_lock_is_released_after_a_run_and_after_a_failure(self, client, monkeypatch):
        _admin(monkeypatch, True)
        from resource_explorer.web.routes import bootstrap as route
        with patch("resource_explorer.bootstrap.check_and_heal", return_value={"batches": {}}):
            assert client.post("/api/bootstrap/run", json={}).status_code == 200
        with patch("resource_explorer.bootstrap.check_and_heal", side_effect=RuntimeError("boom")):
            assert client.post("/api/bootstrap/run", json={}).status_code == 500
        assert route._run_lock.acquire(blocking=False), "released"
        route._run_lock.release()

    def test_two_concurrent_runs_heal_once(self, client, monkeypatch):
        _admin(monkeypatch, True)
        started, release = threading.Event(), threading.Event()
        calls = []

        def slow(*a, **k):
            calls.append(1); started.set(); release.wait(5)
            return {"batches": {}}

        results = []
        with patch("resource_explorer.bootstrap.check_and_heal", slow):
            t = threading.Thread(target=lambda: results.append(client.post("/api/bootstrap/run", json={}).status_code))
            t.start()
            assert started.wait(5)
            second = client.post("/api/bootstrap/run", json={}).status_code
            release.set(); t.join(5)
        assert second == 409 and results == [200] and len(calls) == 1


class TestBulkResolveAdminOnly:
    def test_non_admin_bulk_resolve_is_refused_in_dry_run_too(self, client, monkeypatch):
        _admin(monkeypatch, False)
        with patch("resource_explorer.bulk_ops.resolve_all") as ra:
            res = client.post("/api/egeria/linkage/resolve-all",
                              json={"targets": [{"entity_type": "repo", "slug": "x"}], "action": "republish"})
        assert res.status_code == 403
        ra.assert_not_called()

    def test_admin_reaches_it(self, client, monkeypatch):
        _admin(monkeypatch, True)
        res = client.post("/api/egeria/linkage/resolve-all",
                          json={"targets": [], "action": "republish", "dry_run": True})
        assert res.status_code == 200

    def test_the_single_resource_resolve_stays_open_to_a_non_admin(self, client, monkeypatch):
        _admin(monkeypatch, False)
        res = client.post("/api/egeria/linkage/repo/no-such-slug/resolve", json={"action": "discard"})
        assert res.status_code == 404, "reaches its own 'no stale linkage' answer, not a 403"


class TestAdminStatus:
    @pytest.mark.parametrize("value", [True, False])
    def test_reports_the_request_credential(self, client, monkeypatch, value):
        _admin(monkeypatch, value)
        assert client.get("/api/egeria/admin-status").json() == {"admin": value}
