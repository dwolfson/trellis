"""Enrichment as testimony — PATCH /api/context/{type}/{slug}/field.

A judgement carries an author, a date, and the evidence on screen when it was
made; an observation carries a source. The author is stamped by the server
from the signed-in identity, never taken from the client. Each field saves
alone. These drive the route with a faked identity, since the shape under
test is what the server stamps.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    from resource_explorer.web.app import app
    return TestClient(app)


def signed_in_as(monkeypatch, user_id):
    monkeypatch.setattr("resource_explorer.web.routes.context.get_current_user", lambda request: {"user_id": user_id})


class TestJudgements:
    def test_author_and_date_are_stamped_by_the_server(self, client, monkeypatch):
        signed_in_as(monkeypatch, "peterprofile")
        r = client.patch("/api/context/repo/p/field", json={
            "key": "sensitivity", "value": "internal", "kind": "judgement",
            "evidence": {"cve_scan": "2026-09-03T00:00:00"},
        })
        assert r.status_code == 200, r.text
        f = r.json()["field"]
        assert f["author"] == "peterprofile"
        assert f["set_at"].startswith("2026")
        assert f["evidence"] == {"cve_scan": "2026-09-03T00:00:00"}
        assert f["kind"] == "judgement"

    def test_the_client_cannot_assert_an_author(self, client, monkeypatch):
        """A judgement with a client-supplied author is not testimony; the
        write model does not even have the field."""
        signed_in_as(monkeypatch, "peterprofile")
        r = client.patch("/api/context/repo/p/field", json={
            "key": "owner", "value": "someone", "kind": "judgement", "author": "forged",
        })
        assert r.status_code == 200
        assert r.json()["field"]["author"] == "peterprofile"

    def test_anonymous_is_refused_not_recorded_as_nobody(self, client, monkeypatch):
        monkeypatch.setattr("resource_explorer.web.routes.context.get_current_user", lambda request: None)
        r = client.patch("/api/context/repo/p/field", json={"key": "sensitivity", "value": "internal"})
        assert r.status_code == 401


class TestPerFieldSave:
    def test_two_fields_saved_separately_both_survive(self, client, monkeypatch, registry):
        """Eight independent facts should not share one Save. And a second
        field's save must not clobber the first — the server does the
        read-modify-write."""
        signed_in_as(monkeypatch, "a")
        client.patch("/api/context/repo/p/field", json={"key": "sensitivity", "value": "internal"})
        signed_in_as(monkeypatch, "b")
        client.patch("/api/context/repo/p/field", json={"key": "criticality", "value": "important"})
        ctx = registry.get_context("repo", "p")
        e = ctx["enrichment"]
        assert e["sensitivity"]["value"] == "internal" and e["sensitivity"]["author"] == "a"
        assert e["criticality"]["value"] == "important" and e["criticality"]["author"] == "b"

    def test_shared_fields_are_mirrored_to_the_flat_keys_the_old_ui_reads(self, client, monkeypatch, registry):
        signed_in_as(monkeypatch, "a")
        client.patch("/api/context/repo/p/field", json={"key": "sensitivity", "value": "confidential"})
        client.patch("/api/context/repo/p/field", json={"key": "owner", "value": "data-platform"})
        ctx = registry.get_context("repo", "p")
        assert ctx["sensitivity"] == "confidential"
        assert ctx["org_owner"] == "data-platform"


class TestReviseAfterReload:
    """PLAN-FINISH-REPOS.md item 1's done test: 'a curator can record and
    revisit an enrichment judgement.' The pane loads prior state through
    GET /api/context/repo/{slug} (see `loadPane()` in app.js), so the round
    trip that matters is PATCH-then-GET through the real HTTP routes, not a
    same-session read of the in-process registry object."""

    def test_a_saved_judgement_is_readable_back_through_get_context(self, client, monkeypatch):
        signed_in_as(monkeypatch, "peterprofile")
        client.patch("/api/context/repo/p/field", json={
            "key": "sensitivity", "value": "confidential", "kind": "judgement",
            "evidence": {"cve_scan": "2026-09-03T00:00:00"},
        })
        r = client.get("/api/context/repo/p")
        assert r.status_code == 200
        field = r.json()["enrichment"]["sensitivity"]
        assert field["value"] == "confidential"
        assert field["author"] == "peterprofile"
        assert field["evidence"] == {"cve_scan": "2026-09-03T00:00:00"}

    def test_a_second_field_saved_later_does_not_blank_the_first_on_reload(self, client, monkeypatch):
        signed_in_as(monkeypatch, "a")
        client.patch("/api/context/repo/p/field", json={"key": "owner", "value": "data-platform", "kind": "judgement"})
        signed_in_as(monkeypatch, "b")
        client.patch("/api/context/repo/p/field", json={"key": "criticality", "value": "critical", "kind": "judgement"})
        ctx = client.get("/api/context/repo/p").json()
        assert ctx["enrichment"]["owner"]["value"] == "data-platform"
        assert ctx["enrichment"]["criticality"]["value"] == "critical"

    def test_the_classic_context_form_save_does_not_erase_enrichment(self, client, monkeypatch):
        """The `/` page's Context form (`saveContextForm` in index.html) POSTs
        only its own fixed fields to the SAME document POST /api/context uses
        -- it never sends `enrichment`. `ContextData.enrichment` defaults to
        `{}`, so passing that request straight to model_dump() would silently
        erase every judgement /next recorded the next time someone saves the
        classic form. Regression for that."""
        signed_in_as(monkeypatch, "peterprofile")
        client.patch("/api/context/repo/p/field", json={"key": "sensitivity", "value": "restricted", "kind": "judgement"})

        # Mirrors saveContextForm's payload shape: the fixed fields only.
        r = client.post("/api/context/repo/p", json={"environment": "prod", "org_owner": "data-platform"})
        assert r.status_code == 200

        ctx = client.get("/api/context/repo/p").json()
        assert ctx["enrichment"]["sensitivity"]["value"] == "restricted", \
            "the classic Context form's save must not wipe /next's enrichment judgements"
        assert ctx["environment"] == "prod"

    def test_a_caller_that_explicitly_sends_empty_enrichment_can_still_clear_it(self, client, monkeypatch):
        signed_in_as(monkeypatch, "peterprofile")
        client.patch("/api/context/repo/p/field", json={"key": "sensitivity", "value": "restricted", "kind": "judgement"})
        r = client.post("/api/context/repo/p", json={"enrichment": {}})
        assert r.status_code == 200
        ctx = client.get("/api/context/repo/p").json()
        assert ctx["enrichment"] == {}


class TestObservations:
    def test_an_observation_carries_its_source(self, client, monkeypatch):
        signed_in_as(monkeypatch, "a")
        r = client.patch("/api/context/repo/p/field", json={
            "key": "licence", "value": "Apache License 2.0", "kind": "observation", "source": "license_classification",
        })
        f = r.json()["field"]
        assert f["kind"] == "observation" and f["source"] == "license_classification"
        assert f["evidence"] == {}

    def test_unknown_kind_is_refused(self, client, monkeypatch):
        signed_in_as(monkeypatch, "a")
        r = client.patch("/api/context/repo/p/field", json={"key": "x", "value": "y", "kind": "opinion"})
        assert r.status_code == 422
