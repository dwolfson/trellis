"""Feedback readable across resources, not only where it was written — AND
from both of the two independent stores that back the Admin pane.

`resource_feedback` has been collected per resource since Curate shipped, and
until 2026-08-31 the only reader was `list_resource_feedback(entity_type, slug)`.
That answers "what did people say about this one", which is right from a
resource page and useless from Admin: finding out whether anyone had said
anything meant visiting every resource in turn.

Separately, until 2026-09-01, `GET /api/curate/feedback` (this pane's only
data source) read `resource_feedback` alone. Page-level feedback — the
`feedback` table written by the page-widget in `feedback_store.py` — has its
own dedicated reader (`GET /api/feedback`, admin-feedback.html) but was never
folded into THIS pane, so a page-level submission looked, from here, exactly
like it had been dropped. It hadn't: the pane just never read the store it
landed in. See resource_explorer/web/routes/curate.py::list_all_feedback.

These tests pin what makes the combined Admin view honest rather than merely
present: both sources show up, each row is badged with which one it came
from, and an empty pane says which of "nobody wrote anything" or "your filter
excluded everything" is true.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


@pytest.fixture
def feedback_store(tmp_path):
    from resource_explorer.feedback_store import FeedbackStore
    return FeedbackStore(db_path=str(tmp_path / "test_feedback.db"))


@pytest.fixture
def client(monkeypatch, tmp_path, feedback_store):
    """An isolated SQLite registry AND an isolated page-feedback store, so this
    never reads or writes the shared Postgres instance either table normally
    lives in."""
    from resource_explorer import config as cfg_mod
    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.registry, "database_url", f"sqlite:///{tmp_path}/t.db", raising=False)
    # Route handlers instantiate FeedbackStore() with no args (curate.py's
    # list_all_feedback does exactly this) — redirect every instance to the
    # fixture's already-initialized tmp_path-backed store, same trick
    # test_feedback_routes.py uses for the dedicated /api/feedback routes.
    monkeypatch.setattr(
        "resource_explorer.feedback_store.FeedbackStore.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", feedback_store.__dict__) or None,
    )
    return TestClient(app)


def _registry(tmp_path):
    from resource_explorer.registry import ProjectRegistry
    return ProjectRegistry(database_url=f"sqlite:///{tmp_path}/t.db")


def test_feedback_spans_entity_types_not_just_repos(tmp_path):
    """The cross-resource reader must not quietly default to repos.

    Feedback is recorded against databases and filesystems too. A default of
    entity_type="repo" would make the other two look like nobody had ever
    commented on them.
    """
    reg = _registry(tmp_path)
    reg.add_resource_feedback("repo", "a", 5, "quality", "solid")
    reg.add_resource_feedback("database", "b", None, "", "no rating given")
    reg.add_resource_feedback("filesystem", "c", 2, "docs", "hard to follow")

    rows = reg.list_all_resource_feedback()
    assert len(rows) == 3, f"expected all three entity types, got {[r['entity_type'] for r in rows]}"
    assert {r["entity_type"] for r in rows} == {"repo", "database", "filesystem"}

    only_db = reg.list_all_resource_feedback(entity_type="database")
    assert len(only_db) == 1 and only_db[0]["entity_slug"] == "b"


def test_counts_distinguish_volume_from_reach(tmp_path):
    """"40 items" and "40 items across 3 resources" say different things about
    whether the feature is being used."""
    reg = _registry(tmp_path)
    for i in range(4):
        reg.add_resource_feedback("repo", "same-repo", 3, "", f"note {i}")
    reg.add_resource_feedback("repo", "other-repo", 4, "", "elsewhere")

    counts = reg.count_all_resource_feedback()
    assert counts == {"total": 5, "resources": 2}, counts


def test_the_route_says_whether_an_empty_list_was_filtered(client):
    """An empty list is ambiguous on its own: "nobody has left feedback" and
    "your filter excluded everything" look identical, and only the first is a
    fact about the world."""
    unfiltered = client.get("/api/curate/feedback")
    assert unfiltered.status_code == 200, unfiltered.text
    assert unfiltered.json()["filtered"] is False

    filtered = client.get("/api/curate/feedback?category=nonexistent-category")
    assert filtered.status_code == 200
    assert filtered.json()["filtered"] is True
    assert filtered.json()["feedback"] == []


def test_both_stores_are_genuinely_empty_and_both_counts_say_so(client):
    """Neither store has a row. The response must make that a stated fact for
    EACH source, not one combined total that hides which store is empty."""
    resp = client.get("/api/curate/feedback")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["feedback"] == []
    assert data["filtered"] is False
    assert data["counts"] == {
        "resource": {"total": 0, "resources": 0},
        "page": {"total": 0},
    }


def test_the_route_combines_both_sources_badged_by_origin(client, tmp_path, feedback_store):
    """The bug, verbatim: a page-level submission (`feedback` table) must show
    up here at all, alongside resource_feedback — and each row must say which
    store it came from, since the two are deliberately not merged."""
    from resource_explorer.feedback_store import FeedbackEntry

    reg = _registry(tmp_path)
    reg.add_resource_feedback("repo", "some-repo", 4, "quality", "from Curate")
    feedback_store.add(FeedbackEntry(page="/scouting", rating=5, message="from the page widget"))

    resp = client.get("/api/curate/feedback")
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert len(data["feedback"]) == 2, data["feedback"]

    sources = {r["source"] for r in data["feedback"]}
    assert sources == {"resource", "page"}, (
        "a page-level row must appear here — it was the entire bug report"
    )
    assert data["counts"]["resource"] == {"total": 1, "resources": 1}
    assert data["counts"]["page"] == {"total": 1}

    page_row = next(r for r in data["feedback"] if r["source"] == "page")
    resource_row = next(r for r in data["feedback"] if r["source"] == "resource")
    assert page_row["message"] == "from the page widget"
    assert page_row["page"] == "/scouting"
    # A page row has no entity_type/entity_slug at all — it was never
    # recorded against a resource.
    assert "entity_type" not in page_row or page_row.get("entity_type") in (None, "")
    assert resource_row["message"] == "from Curate"
    assert resource_row["entity_slug"] == "some-repo"
    # A resource_feedback row has no triage_status — that column belongs
    # only to the page-level `feedback` table's workflow.
    assert "triage_status" not in resource_row


def test_source_is_itself_a_filter(client, tmp_path, feedback_store):
    """Badging exists so the two stores can be told apart later; filtering by
    source is the same capability exercised from the query string."""
    from resource_explorer.feedback_store import FeedbackEntry

    reg = _registry(tmp_path)
    reg.add_resource_feedback("repo", "some-repo", 4, "quality", "from Curate")
    feedback_store.add(FeedbackEntry(page="/scouting", rating=5, message="from the page widget"))

    only_page = client.get("/api/curate/feedback?source=page").json()
    assert len(only_page["feedback"]) == 1
    assert only_page["feedback"][0]["source"] == "page"
    assert only_page["filtered"] is True

    only_resource = client.get("/api/curate/feedback?source=resource").json()
    assert len(only_resource["feedback"]) == 1
    assert only_resource["feedback"][0]["source"] == "resource"


def test_an_entity_type_filter_excludes_page_rows_rather_than_ignoring_them(
    client, tmp_path, feedback_store
):
    """entity_type has no meaning for page-level feedback — it was never
    recorded against a resource. Filtering by it must exclude every page row,
    not silently show them anyway because the filter doesn't apply to them."""
    from resource_explorer.feedback_store import FeedbackEntry

    reg = _registry(tmp_path)
    reg.add_resource_feedback("repo", "some-repo", 4, "quality", "from Curate")
    feedback_store.add(FeedbackEntry(page="/scouting", rating=5, message="from the page widget"))

    filtered = client.get("/api/curate/feedback?entity_type=repo").json()
    assert {r["source"] for r in filtered["feedback"]} == {"resource"}

    filtered_other = client.get("/api/curate/feedback?entity_type=database").json()
    assert filtered_other["feedback"] == []


def test_the_per_resource_route_still_works(client):
    """The new collection route must not shadow the two-segment one."""
    res = client.get("/api/curate/feedback/repo/anything")
    assert res.status_code == 200, res.text
    assert isinstance(res.json(), list)


def test_an_absent_rating_does_not_render_as_zero_stars():
    """`rating` is nullable and the form allows a message with no score.
    "No rating given" and "rated 0" are different, and only one is a judgement.
    """
    html = INDEX.read_text()
    fn = html[html.index("function _feedbackRatingHtml"):]
    fn = fn[:fn.index("\n}")]
    assert "null" in fn and "undefined" in fn, (
        "_feedbackRatingHtml does not special-case a missing rating, so an "
        "absent score would render as zero stars"
    )


def test_the_feedback_pane_is_wired_end_to_end():
    """A pane needs four things; three of them fail silently rather than erroring."""
    html = INDEX.read_text()
    assert 'id="admin-feedback-view"' in html, "no pane element"
    assert "adminFeedbackView" in html, "pane is not in showMainView's hide-list"
    assert "tab === 'admin-feedback'" in html, "no route in showMainView"
    assert "function loadAdminFeedbackPanel" in html, "no loader"

    groups = html[html.index("const _ADMIN_GROUPS"):html.index("function _adminSubnavHtml")]
    assert "admin-feedback" in groups, "pane exists but no subnav button reaches it"
    # It belongs under Observe, which existed as a group of one specifically to
    # hold this and the log viewer.
    observe = groups[groups.index("'Observe'"):]
    assert "admin-feedback" in observe, "Feedback should sit under Observe"


def test_every_row_is_badged_with_its_origin():
    """Badging is what keeps a future, deliberate merge possible — it must be
    visible on the row, not only in a tooltip."""
    html = INDEX.read_text()
    fn = html[html.index("function loadAdminFeedbackPanel"):]
    fn = fn[:fn.index("\nfunction _adminFeedbackSetFilter")]
    assert "_feedbackSourceBadge(r.source)" in fn, (
        "loadAdminFeedbackPanel's row template does not call the source badge"
    )
    badge_fn = html[html.index("function _feedbackSourceBadge"):]
    badge_fn = badge_fn[:badge_fn.index("\n}")]
    assert "'page'" in badge_fn and ">page<" in badge_fn and ">resource<" in badge_fn


def test_a_field_absent_by_source_is_not_rendered_like_a_measured_empty():
    """resource_feedback rows have no triage_status; page rows have no
    entity_type/slug. Neither should render as the same "—" the pane uses for
    an optional field left blank (e.g. no rating given) — that would claim
    the column was measured and came back empty, which isn't what happened."""
    html = INDEX.read_text()
    assert "function _feedbackNA" in html, "no distinct 'not applicable' renderer"
    fn = html[html.index("function loadAdminFeedbackPanel"):]
    fn = fn[:fn.index("\nfunction _adminFeedbackSetFilter")]
    assert "_feedbackNA(" in fn, (
        "the row template never reaches for the not-applicable renderer, so a "
        "column absent by source falls back to the same marker as an empty one"
    )


def test_counts_are_shown_per_source_not_one_hiding_total():
    """A single combined total would hide that one store is empty while the
    other has content — exactly the situation the bug report was about."""
    html = INDEX.read_text()
    fn = html[html.index("function loadAdminFeedbackPanel"):]
    fn = fn[:fn.index("\nfunction _adminFeedbackSetFilter")]
    assert "counts.page" in fn and "counts.resource" in fn, (
        "the pane's summary text does not reference both sources' counts "
        "separately"
    )


def test_the_source_filter_is_reachable_from_the_pane():
    """Filtering by origin is the same capability the badge exists for,
    surfaced as a control."""
    html = INDEX.read_text()
    fn = html[html.index("function loadAdminFeedbackPanel"):]
    fn = fn[:fn.index("\nfunction _adminFeedbackSetFilter")]
    assert "'source', 'page'" in fn and "'source', 'resource'" in fn


class TestUngatedRouteDoesNotServeContactFields:
    """`/api/curate/feedback` has no admin gate; `/api/feedback` does.

    On 2026-09-01 this route was widened to serve the page-level store so the
    Admin pane would stop showing an empty list. Correct fix, wrong scope: it
    routed data the GATED endpoint protects through an UNGATED one.
    `admin_auth.is_admin_request` is fail-closed by design and an admin token is
    configured, so the gate was real and being bypassed rather than aspirational.

    Nothing leaked — no stored row carries an email — but the store has
    `wants_response` and `consent_to_contact` columns, so emails are expected.
    This pins the interim fix until the route is properly gated.
    """

    def test_contact_fields_are_absent_from_page_rows(self, client, feedback_store):
        from resource_explorer.feedback_store import FeedbackEntry

        feedback_store.add(FeedbackEntry(
            page="/scouting", rating=5, message="please reply",
            email="someone@example.com", wants_response=True,
            consent_to_contact=True))
        rows = client.get("/api/curate/feedback").json()["feedback"]
        page = [r for r in rows if r["source"] == "page"]
        assert page, "no page rows — this test would pass vacuously"
        for field in ("email", "session_id", "user_agent", "viewport", "locale"):
            assert all(field not in r for r in page), (
                f"{field} served by an ungated route")

    def test_the_feedback_itself_survives_stripping(self, client, feedback_store):
        """Known-negative for over-stripping: a filter that removed everything
        would pass the test above. The pane exists to show these."""
        from resource_explorer.feedback_store import FeedbackEntry

        feedback_store.add(FeedbackEntry(
            page="/scouting", rating=5, message="the actual feedback",
            category="suggestion", email="someone@example.com"))
        rows = client.get("/api/curate/feedback").json()["feedback"]
        page = [r for r in rows if r["source"] == "page"]
        assert page
        # Only fields this test actually SET — asserting on a field the entry
        # never carried would fail for the wrong reason, which the first version
        # of this test did.
        for key in ("message", "category", "created_at"):
            assert any((r.get(key) or "") != "" for r in page), (
                f"{key} was stripped too — the pane would show nothing useful")

    def test_keys_are_removed_not_blanked(self):
        """A blank email is indistinguishable from an author who left none.
        Removing the key means a caller cannot mistake absence for a measured
        empty — the distinction this codebase keeps having to restore."""
        from resource_explorer.web.routes.curate import _without_contact_fields

        out = _without_contact_fields(
            {"email": "a@b.c", "message": "hi", "session_id": "s1"})
        assert "email" not in out and "session_id" not in out
        assert out["message"] == "hi"
