"""Suppressing an RFA must be a record, and must stay visible.

Dan, 2026-08-31, looking at ten near-identical SecurityHygieneCheck rows:
"it seems that another option should be Ignore (or Not Applicable) because
the user, generally can't do something about no SECURITY.md file found on
repos they don't control" — then, on how to build it: "suppress with
visibility - do both - there may be a future admin setting that allows you
to reset or clear some of these decisions in the future (for example, you
become a maintainer)".

Two properties carry that, and each has a known-negative here:

  1. A dismissal is keyed by the finding's CONTENT, not by the occurrence.
     rfa_actions is keyed "{entry_id}::{index}", which is one row of one
     activity entry; every survey run writes a new entry, so a dismissal
     recorded that way would silently stop suppressing the moment the next
     survey ran. The whole reason "not applicable" exists is that the
     finding WILL recur.
  2. A suppressed finding is still returned by the API and still rendered.
     Filtering it out server-side would make "we decided this doesn't apply"
     indistinguishable from "this never happened" — the absence-as-answer
     shape this codebase keeps paying for.

And one that is really about honesty: a cleared dismissal stops suppressing
but stays in the table, so "we decided X, then changed our mind" is legible
afterwards.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.activity_logger import log_survey
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))
    return reg


def _log_run(reg, summary="No SECURITY.md found", analysis="SecurityHygieneCheck"):
    """One survey run producing one RFA. Returns the new entry's id."""
    log_survey(
        registry=reg, entity_type="repo", entity_slug="p", entity_name="P",
        entity_location="", intent="scouting", status="success", summary="survey",
        annotations=[{
            "analysis_name": analysis,
            "annotation_type": "RequestForAction",
            "count": 1, "status": "local", "summary": summary,
        }],
    )
    return reg.list_activity(limit=1)[0]["id"]


@pytest.fixture
def client(registry, monkeypatch):
    from resource_explorer.web.app import app
    monkeypatch.setattr(
        "resource_explorer.web.routes.activity._registry", lambda: registry
    )
    return TestClient(app)


class TestTheKey:
    def test_the_same_finding_from_a_later_run_is_still_suppressed(self, registry, client):
        """The property rfa_actions' occurrence key cannot provide.

        Known-negative: key on the rfa_id instead and this fails — the second
        run's entry has a different id, so its row comes back undismissed.
        """
        first = _log_run(registry)
        client.post(f"/api/activity/rfas/{first}::0/dismiss", json={"reason": "not_applicable"})

        second = _log_run(registry)
        assert second != first

        rows = client.get("/api/activity/rfas").json()
        assert len(rows) == 2, "both runs' RFAs should be listed"
        assert all(r["dismissed"] for r in rows), (
            "a dismissal keyed by occurrence would leave the newer run's "
            "identical finding unsuppressed"
        )

    def test_a_different_finding_is_not_suppressed(self, registry, client):
        """The key must not be so loose that one dismissal silences a step."""
        first = _log_run(registry, summary="No SECURITY.md found")
        client.post(f"/api/activity/rfas/{first}::0/dismiss", json={"reason": "not_applicable"})
        _log_run(registry, summary="No CI configuration found")

        rows = {r["summary"]: r["dismissed"] for r in client.get("/api/activity/rfas").json()}
        assert rows["No SECURITY.md found"] is True
        assert rows["No CI configuration found"] is False

    def test_key_tolerates_whitespace_and_case(self, registry):
        a = registry.rfa_dismissal_key("repo", "p", "SecurityHygieneCheck", "No SECURITY.md found")
        b = registry.rfa_dismissal_key("repo", "P", "securityhygienecheck", " No  SECURITY.md   found ")
        assert a == b

    def test_key_separates_entities(self, registry):
        a = registry.rfa_dismissal_key("repo", "p", "X", "s")
        b = registry.rfa_dismissal_key("repo", "q", "X", "s")
        assert a != b, "one repo's dismissal must not suppress another's finding"


class TestVisibility:
    def test_a_dismissed_rfa_is_still_returned(self, registry, client):
        """Known-negative: filter dismissed rows out of GET /rfas and this
        fails — which is exactly the behaviour that would make a suppressed
        finding look like one that never occurred."""
        entry = _log_run(registry)
        client.post(f"/api/activity/rfas/{entry}::0/dismiss",
                    json={"reason": "not_applicable", "note": "upstream repo"})

        rows = client.get("/api/activity/rfas").json()
        assert len(rows) == 1
        assert rows[0]["dismissed"] is True
        assert rows[0]["dismissal"]["reason"] == "not_applicable"
        assert rows[0]["dismissal"]["note"] == "upstream repo"

    def test_an_undismissed_rfa_carries_the_flag_too(self, registry, client):
        """`dismissed` is always present, so the frontend never has to treat
        a missing field as false."""
        _log_run(registry)
        row = client.get("/api/activity/rfas").json()[0]
        assert row["dismissed"] is False
        assert row["dismissal"] is None


class TestClearing:
    def test_clearing_stops_suppression_but_keeps_the_record(self, registry, client):
        entry = _log_run(registry)
        did = client.post(f"/api/activity/rfas/{entry}::0/dismiss",
                          json={"reason": "wont_do"}).json()["dismissal"]["id"]

        res = client.post(f"/api/activity/rfas/dismissals/{did}/clear",
                          json={"cleared_by": "maintainer-now"})
        assert res.status_code == 200
        assert res.json()["dismissal"]["cleared_by"] == "maintainer-now"

        assert client.get("/api/activity/rfas").json()[0]["dismissed"] is False
        assert client.get("/api/activity/rfas/dismissals").json() == []
        history = client.get("/api/activity/rfas/dismissals?include_cleared=true").json()
        assert len(history) == 1, "a reversed decision is history, not a deletion"
        assert history[0]["reason"] == "wont_do"

    def test_redismissing_reinstates_in_place(self, registry, client):
        entry = _log_run(registry)
        did = client.post(f"/api/activity/rfas/{entry}::0/dismiss",
                          json={"reason": "not_applicable"}).json()["dismissal"]["id"]
        client.post(f"/api/activity/rfas/dismissals/{did}/clear", json={})
        client.post(f"/api/activity/rfas/{entry}::0/dismiss", json={"reason": "wont_do"})

        rows = client.get("/api/activity/rfas/dismissals?include_cleared=true").json()
        assert len(rows) == 1, "one finding has one suppression answer, not a stack"
        assert rows[0]["reason"] == "wont_do"
        assert rows[0]["cleared_at"] == ""

    def test_clearing_an_unknown_dismissal_is_404_not_success(self, client):
        assert client.post("/api/activity/rfas/dismissals/nope/clear", json={}).status_code == 404


class TestRefusals:
    def test_an_unknown_reason_is_rejected(self, registry, client):
        """Storing an unrecognised reason would match no filter and suppress
        nothing, reporting success — the silent no-op this table exists to
        avoid."""
        entry = _log_run(registry)
        res = client.post(f"/api/activity/rfas/{entry}::0/dismiss", json={"reason": "maybe"})
        assert res.status_code == 400
        assert registry.list_rfa_dismissals(include_cleared=True) == []

    def test_a_malformed_rfa_id_is_rejected(self, client):
        assert client.post("/api/activity/rfas/garbage/dismiss",
                           json={"reason": "wont_do"}).status_code == 400

    def test_a_missing_entry_is_404(self, client):
        assert client.post("/api/activity/rfas/nosuch::0/dismiss",
                           json={"reason": "wont_do"}).status_code == 404

    def test_an_out_of_range_annotation_index_is_404(self, registry, client):
        entry = _log_run(registry)
        assert client.post(f"/api/activity/rfas/{entry}::99/dismiss",
                           json={"reason": "wont_do"}).status_code == 404

    def test_a_blank_entity_slug_is_refused(self, registry):
        """A dismissal with no subject would hash to a key that could match
        another blank-slug finding — refuse rather than store it."""
        with pytest.raises(ValueError):
            registry.dismiss_rfa("repo", "  ", "X", "s", "wont_do")
