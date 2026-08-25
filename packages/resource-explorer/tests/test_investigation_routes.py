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
            ws = reg.investigation_working_set_slug(slug)
            if ws:
                conn.execute("DELETE FROM working_set_members WHERE working_set_slug = ?", (ws,))
                conn.execute("DELETE FROM working_sets WHERE slug = ?", (ws,))
            conn.execute("DELETE FROM investigation_resource_lists WHERE investigation_slug = ?", (slug,))
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


def test_membership_goes_through_a_working_set(client, made):
    """Storage mirrors Egeria's real two-hop shape:

        Project --ResourceList--> WorkingSet --CollectionMembership--> resource

    A flat Project->resource link (which an earlier pass here used, and which
    design §6 itself sketched) has nowhere to put a per-resource rationale and
    makes the working set unnameable. The API stays flat because every caller
    only wants "what is in scope"; the two hops are a storage-fidelity decision
    so promotion to Egeria is a replay rather than a migration.
    """
    from resource_explorer.registry import ProjectRegistry

    inv = made(display_name="Two Hop")
    reg = ProjectRegistry()

    # A brand-new investigation has NO working set — that is what makes the
    # empty sidebar an honest prompt rather than an empty shell.
    assert reg.investigation_working_set_slug(inv["slug"]) == ""

    r = client.post(f"/api/investigations/{inv['slug']}/members", json={
        "entity_type": "repo", "entity_slug": "milvus",
        "membership_rationale": "already adopted; tracking health",
    })
    assert r.status_code == 200
    assert r.json()[0]["membership_rationale"] == "already adopted; tracking health"

    # ...and the working set was created lazily, on first use.
    ws_slug = reg.investigation_working_set_slug(inv["slug"])
    assert ws_slug
    assert reg.get_working_set(ws_slug)["members"][0]["entity_slug"] == "milvus"

    assert client.get(f"/api/investigations/{inv['slug']}").json()["member_count"] == 1

    d = client.delete(f"/api/investigations/{inv['slug']}/members/repo/milvus")
    assert d.status_code == 200 and d.json() == []


def test_members_on_a_missing_investigation_404s(client):
    assert client.get("/api/investigations/nope/members").status_code == 404
