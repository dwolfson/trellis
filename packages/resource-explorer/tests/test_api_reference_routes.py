"""API reference: the HTTP surface (read the reference, register / re-check / clear the instance URL)."""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from resource_explorer.api_reference import live
from resource_explorer.registry import Project, ProjectRegistry

SPEC = (Path(__file__).parent / "fixtures" / "openapi" / "testgen-openapi.json").read_text()
URL = "http://localhost:8530/api/openapi.json"


@pytest.fixture
def client(tmp_path, monkeypatch):
    db_path = str(tmp_path / "t.db")
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{db_path}")
    reg = ProjectRegistry(db_path=db_path)
    reg.add(Project(slug="tg", display_name="TG", github_url="https://github.com/x/tg", description=""))
    from resource_explorer.web import app as app_mod
    from resource_explorer.web.routes import api_reference as routes
    monkeypatch.setattr(routes, "_registry", lambda: ProjectRegistry(db_path=db_path))
    monkeypatch.setattr(routes, "_transport", lambda: httpx.MockTransport(lambda r: (
        httpx.Response(200, text=SPEC, headers={"content-type": "application/json"}) if "8530" in str(r.url)
        else httpx.Response(200, text="<html/>", headers={"content-type": "text/html"}))))
    return TestClient(app_mod.app), reg


def test_reference_empty_explains_each_source(client):
    c, _ = client
    r = c.get("/api/api-reference/tg")
    assert r.status_code == 200 and r.json()["interfaces"] == [] and len(r.json()["missing"]) == 3


def test_unknown_repo_404(client):
    c, _ = client
    assert c.get("/api/api-reference/nope").status_code == 404


def test_register_validates_and_returns_the_reason(client):
    c, reg = client
    bad = c.put("/api/api-reference/tg/instance", json={"url": "http://localhost:8501/api/openapi.json"})
    assert bad.status_code == 200 and bad.json()["ok"] is False
    assert bad.json()["reason"] == "not an OpenAPI document: got text/html"
    assert live.load_instance(reg, "tg") is None


def test_register_then_read_back_then_recheck_then_clear(client):
    c, reg = client
    ok = c.put("/api/api-reference/tg/instance", json={"url": URL})
    assert ok.json()["ok"] is True and ok.json()["operations"] == 26
    ref = c.get("/api/api-reference/tg").json()
    assert ref["best"] == "running_instance" and ref["instance"]["url"] == URL
    assert c.post("/api/api-reference/tg/instance/refetch").json()["ok"] is True
    assert c.delete("/api/api-reference/tg/instance").json()["cleared"] is True
    assert c.get("/api/api-reference/tg").json()["instance"] is None


def test_non_http_url_is_a_400_free_validation_answer(client):
    c, _ = client
    r = c.put("/api/api-reference/tg/instance", json={"url": "file:///etc/passwd"})
    assert r.status_code == 200 and r.json()["ok"] is False and "http(s)" in r.json()["reason"]
