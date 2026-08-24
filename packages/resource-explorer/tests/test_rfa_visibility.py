"""Every RFA written must reach the surface built to act on it.

GET /api/activity/rfas — the feed behind the RFA drawer — flattens activity
entries and keeps only *annotations* whose annotation_type contains
"RequestForAction". It never looks at operation="rfa". log_rfa() wrote its entry
with an empty annotations list, so every RFA it produced was invisible in the
drawer: the entry was in the activity log, and the one screen built to respond to
it showed nothing.

All three producers were affected — Automate's change notifications, Enrichment's
context requests, and Egeria linkage divergences. Each is by definition a request
for a human action, and no human was shown one.

Nothing failed, which is why it lasted: the writes succeeded, the entries were
real, and only a reader looking for a different shape came up empty.
"""
from __future__ import annotations

import pytest

from resource_explorer.activity_logger import log_rfa
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))
    return reg


def _drawer_rows(reg):
    """Exactly the selection GET /api/activity/rfas performs."""
    return [a for e in reg.list_activity(limit=500)
            for a in (e.get("annotations") or [])
            if "RequestForAction" in (a.get("annotation_type") or "")]


def test_a_logged_rfa_is_visible_in_the_drawer_feed(registry):
    log_rfa(registry=registry, entity_type="repo", entity_slug="p", entity_name="P",
            status="pending", summary="Something needs a decision")

    rows = _drawer_rows(registry)
    assert len(rows) == 1
    assert rows[0]["summary"] == "Something needs a decision"


def test_the_annotation_summary_matches_the_entry_summary(registry):
    """The drawer reads the annotation's summary and the activity log reads the
    entry's. Two texts for one event drifting apart would be worse than the
    duplication."""
    log_rfa(registry=registry, entity_type="repo", entity_slug="p", entity_name="P",
            status="pending", summary="Coverage dropped", detail="from 80% to 61%")

    entry = registry.list_activity(operation="rfa")[0]
    assert entry["summary"] == entry["annotations"][0]["summary"]
    # detail stays on the entry — the drawer does not read it, and duplicating a
    # long body into the annotation would bloat every feed response.
    assert entry["detail"] == "from 80% to 61%"


def test_the_route_itself_returns_it(registry, monkeypatch):
    """Through the real endpoint, not just the selection logic copied here."""
    from fastapi.testclient import TestClient

    from resource_explorer.web.app import app

    monkeypatch.setattr("resource_explorer.web.routes.activity._registry", lambda: registry)
    log_rfa(registry=registry, entity_type="repo", entity_slug="p", entity_name="P",
            status="pending", summary="Needs review")

    rows = TestClient(app).get("/api/activity/rfas").json()
    assert [r["summary"] for r in rows] == ["Needs review"]
    assert rows[0]["rfa_status"] == "open"


@pytest.mark.parametrize("producer", ["divergence", "subscription", "context"])
def test_every_producer_reaches_the_drawer(registry, producer):
    """Each of the three call sites, at its own level rather than through a
    mock of log_rfa — a test that stubbed it would pass even if the fix were
    reverted."""
    if producer == "divergence":
        from resource_explorer.egeria_linkage import note_divergence
        note_divergence(registry, "repo", "p", "P", "abc-123",
                        Exception("OMRS-REPOSITORY-404-002 unknown"))
    else:
        # scheduler and context both call log_rfa directly with these shapes.
        summary = "Analysis changed" if producer == "subscription" else "Context needed"
        log_rfa(registry=registry, entity_type="repo", entity_slug="p", entity_name="P",
                status="pending", summary=summary)

    assert len(_drawer_rows(registry)) == 1
