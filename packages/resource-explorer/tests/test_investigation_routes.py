"""Investigations — the framing step ahead of Scouting.

`docs/investigation-framing-design.md` §1. These pin the two decisions that make
promotion to Egeria a fill-in rather than a migration, and the one validation
that stops a purpose silently ranking nothing.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app


@pytest.fixture(scope="module")
def client():
    return TestClient(app)


@pytest.fixture
def made(client):
    created = []

    def _make(**kw):
        body = {"display_name": "Test Investigation", **kw}
        r = client.post("/api/investigations/", json=body)
        assert r.status_code == 200, r.text
        created.append(r.json()["slug"])
        return r.json()

    yield _make
    from resource_explorer.registry import ProjectRegistry
    reg = ProjectRegistry()
    with reg._conn() as conn:
        for slug in created:
            conn.execute("DELETE FROM investigation_members WHERE investigation_slug = ?", (slug,))
            conn.execute("DELETE FROM investigations WHERE slug = ?", (slug,))


def test_purposes_are_served_not_hardcoded_in_the_spa(client):
    """The UI must not carry its own copy of this vocabulary.

    Purpose is ProjectCharter.purposes (§2), and the same eight values all 41
    catalog questions are tagged with. A second copy in the SPA is exactly the
    frontend/backend mirror that has drifted twice in this codebase already.
    """
    r = client.get("/api/investigations/purposes")
    assert r.status_code == 200
    assert r.json()["purposes"] == [
        "Assess", "Certify", "Deploy", "Explore", "Learn", "Maintain", "Select", "Share",
    ]


def test_an_investigation_starts_local_with_no_egeria_write(made):
    """§1's third starting mode, and the structural decision behind it.

    One local row in all three modes, with a nullable egeria_project_guid, so
    promotion later is a fill-in rather than a migration.
    """
    inv = made(display_name="Local Only", purposes=["Explore"])
    assert inv["egeria_project_guid"] == ""
    assert inv["status"] == "open"
    assert inv["purposes"] == ["Explore"]


def test_an_unknown_purpose_is_rejected_rather_than_stored(client):
    """A purpose outside the vocabulary would rank nothing and look like an
    empty result — indistinguishable from 'nothing matched'."""
    r = client.post("/api/investigations/",
                    json={"display_name": "Bad", "purposes": ["Nonsense"]})
    assert r.status_code == 400
    assert "Nonsense" in r.json()["detail"]


def test_membership_is_shaped_like_the_relationship_it_becomes(client, made):
    """Members carry their own resource_use and state, so promotion replays
    each row as a ResourceList relationship rather than migrating a different
    shape (§1, §7's candidate/in-scope/excluded)."""
    inv = made(display_name="With Members")
    r = client.put(f"/api/investigations/{inv['slug']}/members", json={"members": [
        {"entity_type": "repo", "entity_slug": "milvus", "resource_use": "candidate"},
        {"entity_type": "repo", "entity_slug": "sqlglot", "state": "excluded"},
    ]})
    assert r.status_code == 200
    members = {m["entity_slug"]: m for m in r.json()}
    assert members["milvus"]["resource_use"] == "candidate"
    assert members["milvus"]["state"] == "in-scope"
    assert members["sqlglot"]["state"] == "excluded"
    refreshed = client.get(f"/api/investigations/{inv['slug']}").json()
    assert refreshed["member_count"] == 2


def test_members_on_a_missing_investigation_404s(client):
    assert client.get("/api/investigations/nope/members").status_code == 404
