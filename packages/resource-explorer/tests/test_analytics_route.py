"""Curate's By-analysis tab reads the Analytic Library's curation_coverage through one read-only route.

Temp SQLite throughout; the real registry is never opened. One source: the routine's undecided / chosen
counts are the Contents tab's own (`build_scope_view(...)["counts"]`), because both count `resolve_node_set`."""
from __future__ import annotations

import builtins

import pytest
from fastapi.testclient import TestClient

from resource_explorer import catalogue_scope as scope
from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.web.routes import analytics


@pytest.fixture
def reg(tmp_path):
    db = str(tmp_path / "t.db")
    assert db.startswith(str(tmp_path))
    r = ProjectRegistry(db_path=db)
    r.register_database(DatabaseEntity(slug="demo", display_name="demo", db_type="postgresql", host="localhost",
                                       port=5442, database_name="demo"))
    r.write_detail_rows("database_tables", "demo", "2026-10-01T00:00:00Z", rows=[
        {"schema_name": s, "table_name": "t", "table_type": "BASE TABLE", "row_count": 1, "column_count": 1}
        for s in ("sales", "hr", "ops", "fin")])
    return r


@pytest.fixture
def client(reg, monkeypatch):
    monkeypatch.setattr(analytics, "registry_url", lambda: reg.database_url)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    from resource_explorer.web.app import app
    return TestClient(app)


def test_route_returns_the_routine_result(client):
    body = client.get("/api/analytics/curation-coverage/database/demo").json()
    assert body["envelope"]["result_state"] in ("measured", "nothing_found")
    assert body["known_schemas"] == 4
    assert [g["key"] for g in body["groups"]] == ["published", "not_yet", "blocked"]


def test_undecided_count_is_the_contents_tabs_count(client, reg):
    scope.set_node_choice(reg, "demo", "tester", schema="sales", choice="catalogue")
    scope.set_node_choice(reg, "demo", "tester", schema="hr", choice="leave_out")
    contents = scope.build_scope_view(reg, "demo")["counts"]
    body = client.get("/api/analytics/curation-coverage/database/demo").json()
    ny = {l["key"]: l["count"] for g in body["groups"] if g["key"] == "not_yet" for l in g["lines"]}
    assert contents["schemas_undecided"] == ny["undecided"] == 2
    assert contents["schemas_catalogue"] == ny["chosen"] + ny["chosen_confirmed"] == 1
    assert contents["schemas_leave_out"] == ny["left_out"] + ny["left_out_confirmed"] == 1


def test_library_not_installed_is_not_applicable_never_an_error(client, monkeypatch):
    real = builtins.__import__

    def deny(name, *a, **kw):
        if name.startswith("trellis_analytics"):
            raise ImportError("No module named 'trellis_analytics'")
        return real(name, *a, **kw)
    monkeypatch.setattr(builtins, "__import__", deny)
    r = client.get("/api/analytics/curation-coverage/database/demo")
    assert r.status_code == 200
    body = r.json()
    assert body["envelope"]["result_state"] == "not_applicable"
    assert "not installed" in body["envelope"]["result_state_reason"]
    assert body["groups"] == []


def test_unreadable_registry_is_not_established(client, monkeypatch):
    monkeypatch.setattr(analytics, "registry_url", lambda: "sqlite:////nonexistent-dir/none.db")
    r = client.get("/api/analytics/curation-coverage/database/demo")
    assert r.status_code == 200
    assert r.json()["envelope"]["result_state"] == "not_established"
