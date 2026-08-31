"""Feedback readable across resources, not only where it was written.

`resource_feedback` has been collected per resource since Curate shipped, and
until 2026-08-31 the only reader was `list_resource_feedback(entity_type, slug)`.
That answers "what did people say about this one", which is right from a
resource page and useless from Admin: finding out whether anyone had said
anything meant visiting every resource in turn.

These tests pin the three things that make the Admin view honest rather than
merely present.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app

INDEX = Path(__file__).resolve().parents[1] / "resource_explorer" / "web" / "static" / "index.html"


@pytest.fixture
def client(monkeypatch, tmp_path):
    """An isolated SQLite registry, so this never reads or writes the shared one."""
    from resource_explorer import config as cfg_mod
    cfg = cfg_mod.get_config()
    monkeypatch.setattr(cfg.registry, "database_url", f"sqlite:///{tmp_path}/t.db", raising=False)
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
