"""Admin → Feedback triage: a status filter, a status control with a note, and each item's history.

docs/trellis-feedback-extraction.md §6 step 3 part C. Page items and rated answers carry a trellis-feedback
status (six, Q1); Curate's resource_feedback rows do not until part D, so a status filter leaves them out.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app

STATIC = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "next" / "admin"


@pytest.fixture
def feedback_store(tmp_path):
    from resource_explorer.feedback_store import FeedbackStore
    return FeedbackStore(db_path=str(tmp_path / "triage_feedback.db"))


@pytest.fixture
def client(monkeypatch, feedback_store, tmp_path):
    # Its own registry file: this writes Curate feedback / projects, which must not reach another test even when
    # REGISTRY_DATABASE_URL was set to one file for the whole run.
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{tmp_path}/registry.db")
    import resource_explorer.config as _config_module
    _config_module._config = None
    monkeypatch.setattr(
        "resource_explorer.feedback_store.FeedbackStore.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", feedback_store.__dict__) or None,
    )
    return TestClient(app)


@pytest.fixture
def admin_headers(monkeypatch):
    from resource_explorer import config as cfg_mod
    monkeypatch.setattr(cfg_mod.get_config().feedback, "admin_token", "test-token", raising=False)
    return {"X-Admin-Token": "test-token"}


def _seed(store):
    from resource_explorer.feedback_store import FeedbackEntry
    from resource_explorer.registry import ProjectRegistry

    page = store.add(FeedbackEntry(page="/scouting", category="bug", message="broken"))
    other = store.add(FeedbackEntry(page="/curate", category="praise", message="nice"))
    answer_id, _ = store.add_answer(vote=-1, question="what changed?")
    ProjectRegistry().add_resource_feedback("repo", "r1", 4, "quality", "solid")
    return page.id, other.id, answer_id


class TestTheStatusFilter:
    def test_it_selects_page_and_answer_items_by_their_current_status(self, client, feedback_store, admin_headers):
        page_id, other_id, answer_id = _seed(feedback_store)
        feedback_store.update_triage_status(page_id, "known_issue")
        feedback_store.update_triage_status(answer_id, "known_issue")
        feedback_store.update_triage_status(other_id, "triaged")
        data = client.get("/api/curate/feedback?status=known_issue", headers=admin_headers).json()
        assert {r["id"] for r in data["feedback"]} == {page_id, answer_id}
        assert data["filtered"] is True

    def test_resource_feedback_has_no_status_so_a_status_filter_leaves_it_out(self, client, feedback_store,
                                                                               admin_headers):
        _seed(feedback_store)
        unfiltered = client.get("/api/curate/feedback", headers=admin_headers).json()["feedback"]
        assert "resource" in {r["source"] for r in unfiltered}
        new_only = client.get("/api/curate/feedback?status=new", headers=admin_headers).json()["feedback"]
        assert {r["source"] for r in new_only} == {"page", "answer"}

    def test_an_unknown_status_is_a_400(self, client, feedback_store, admin_headers):
        resp = client.get("/api/curate/feedback?status=closed", headers=admin_headers)
        assert resp.status_code == 400
        assert "known_issue" in resp.json()["detail"]

    def test_the_vocabulary_is_served_in_order(self, client, feedback_store, admin_headers):
        data = client.get("/api/curate/feedback", headers=admin_headers).json()
        assert data["statuses"] == ["new", "triaged", "known_issue", "actioned", "deferred", "not_an_issue"]

    def test_a_change_the_library_refuses_is_a_400_with_its_words(self, client, feedback_store, admin_headers,
                                                                  monkeypatch):
        # From trellis-feedback 0.3 a status can contradict the item's current cause; the library says so with
        # FeedbackError, and the row must show that sentence, not "HTTP 500" (read-back of #1018).
        from trellis_feedback import FeedbackError
        page_id, _, _ = _seed(feedback_store)

        def refuse(*a, **kw):
            raise FeedbackError("status 'not_an_issue' contradicts the item's current cause 'analysis_defect': "
                                "re-diagnose it with this change")
        monkeypatch.setattr(feedback_store.store, "triage", refuse)
        resp = client.patch(f"/api/feedback/{page_id}", headers=admin_headers, json={"triage_status": "not_an_issue"})
        assert resp.status_code == 400
        assert "re-diagnose" in resp.json()["detail"]

    def test_a_change_made_through_patch_is_what_the_listing_shows(self, client, feedback_store, admin_headers):
        page_id, _, _ = _seed(feedback_store)
        resp = client.patch(f"/api/feedback/{page_id}", headers=admin_headers,
                            json={"triage_status": "deferred", "note": "after the release"})
        assert resp.status_code == 200, resp.text
        [row] = [r for r in client.get("/api/curate/feedback", headers=admin_headers).json()["feedback"]
                 if r.get("id") == page_id]
        assert row["triage_status"] == "deferred"
        assert (row["triage"]["note"], row["triage"]["actor"], row["triage"]["events"]) == (
            "after the release", "admin-token", 1)


def _feedback_js() -> str:
    return (STATIC / "feedback.js").read_text()


class TestThePage:
    """Source checks on admin/feedback.js: the control saves through the triage route and says when it did not."""

    def test_each_page_and_answer_row_has_a_status_control_with_a_note(self):
        js = _feedback_js()
        assert "triageHtml(r, statuses)" in js
        assert "data-triage-status" in js and "data-triage-note" in js and "data-triage-save" in js

    def test_save_patches_the_item_by_id_with_status_and_note(self):
        js = _feedback_js()
        assert "fetch(`/api/feedback/${encodeURIComponent(id)}`, {\n          method: 'PATCH'" in js
        assert "JSON.stringify({ triage_status: triageStatus, note })" in js

    def test_a_refused_save_is_said_on_the_row(self):
        js = _feedback_js()
        assert "error.textContent = `Not saved: ${detail}`;" in js

    def test_the_vocabulary_comes_from_the_server(self):
        js = _feedback_js()
        assert "const statuses = data.statuses || ['new'];" in js
        assert "chip(statusWord(s), 'status', s)" in js

    def test_history_is_read_from_the_item_route(self):
        js = _feedback_js()
        assert "data-triage-history" in js
        assert "(item.history || [])" in js

    def test_resource_rows_still_say_they_have_no_status(self):
        assert "resource_feedback has no triage workflow yet" in _feedback_js()
