"""The four repo-built routes must resolve (or honestly refuse) by resource kind.

`/trend`, `/members/{id}`, `/members/{id}/children` and `/members/{id}/promote`
used to look every slug up as a repo Project, so a database caller got
"Project 'X' not found" -- a false claim about a resource that exists. Now:
the slug resolves as ITS kind, and a kind with no built reader gets a 400
"not built yet" sentence naming the kind (never 404, which would claim the
resource is absent; and never 401/422 first, since the request can never work).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import (
    DatabaseEntity, FileSystemEntity, Project, ProjectRegistry)


@pytest.fixture
def client(tmp_path, monkeypatch):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="myrepo", display_name="R", github_url="https://github.com/t/r"))
    r.register_database(DatabaseEntity(
        slug="mydb", display_name="D", db_type="postgresql", host="localhost",
        port=5432, database_name="d"))
    r.register_filesystem(FileSystemEntity(
        slug="myfs", display_name="F", local_mount_point="/tmp/x"))
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", r.__dict__) or None,
    )
    from resource_explorer.web.app import app
    return TestClient(app)


SLUG = {"repo": "myrepo", "database": "mydb", "filesystem": "myfs"}
PLURAL = {"database": "databases", "filesystem": "filesystems"}

TREND_ID = {"repo": "security_scan", "database": "schema_inventory", "filesystem": "filesystem_inventory"}
_PROMOTE_BODY = {"action": "journal", "members": ["a"], "total": 1}

# (route label, call, fragment the not-built sentence must carry)
ROUTES = {
    "trend": (lambda c, slug, kind: c.get(
        f"/api/projects/{slug}/analyses/{TREND_ID[kind]}/trend?entity_type={kind}"),
        "Trend history isn't built for"),
    "members": (lambda c, slug, kind: c.get(
        f"/api/projects/{slug}/members/cve_scan?entity_type={kind}"),
        "Members aren't built for"),
    "children": (lambda c, slug, kind: c.get(
        f"/api/projects/{slug}/members/api_structure/children?key=file:a.py&entity_type={kind}"),
        "Member children aren't built for"),
    "promote": (lambda c, slug, kind: c.post(
        f"/api/projects/{slug}/members/cve_scan/promote?entity_type={kind}", json=_PROMOTE_BODY),
        "Promoting members isn't built for"),
}


@pytest.mark.parametrize("kind", ["database", "filesystem"])
@pytest.mark.parametrize("route", sorted(ROUTES))
def test_non_repo_kind_gets_honest_400_naming_the_kind(client, route, kind):
    call, fragment = ROUTES[route]
    resp = call(client, SLUG[kind], kind)
    assert resp.status_code == 400, resp.text
    detail = resp.json()["detail"]
    assert fragment in detail and PLURAL[kind] in detail
    assert "not found" not in detail.lower()


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_repo_kind_still_resolves(client, route):
    call, _ = ROUTES[route]
    resp = call(client, SLUG["repo"], "repo")
    if route == "promote":
        assert resp.status_code == 401        # kind gate passed; anonymous
    else:
        assert resp.status_code == 200, resp.text


@pytest.mark.parametrize("route", sorted(ROUTES))
def test_unknown_repo_slug_is_still_a_404(client, route):
    call, _ = ROUTES[route]
    if route == "promote":
        pytest.skip("promote 401s before resolving the slug when anonymous")
    resp = call(client, "no-such-repo", "repo")
    assert resp.status_code == 404


def test_unknown_database_slug_trend_is_a_404_naming_database(client):
    resp = client.get("/api/projects/ghost/analyses/schema_inventory/trend?entity_type=database")
    assert resp.status_code == 404
    assert "Database 'ghost' not found" in resp.json()["detail"]


def test_anonymous_database_promote_sees_not_built_not_sign_in(client):
    resp = client.post("/api/projects/mydb/members/cve_scan/promote?entity_type=database",
                       json=_PROMOTE_BODY)
    assert resp.status_code == 400
    assert "sign in" not in resp.json()["detail"].lower()
    # ...and an invalid body (would be 422) gets the same sentence.
    resp = client.post("/api/projects/mydb/members/cve_scan/promote?entity_type=database",
                       json={"action": "nonsense", "members": []})
    assert resp.status_code == 400


def test_unknown_kind_is_400(client):
    resp = client.get("/api/projects/myrepo/members/cve_scan?entity_type=banana")
    assert resp.status_code == 400
    assert "banana" in resp.json()["detail"]


def test_exact_members_sentence(client):
    resp = client.get("/api/projects/mydb/members/cve_scan?entity_type=database")
    assert resp.json()["detail"] == (
        "Members aren't built for databases yet; today they list repository findings "
        "(advisories, dependencies, symbols, components).")
