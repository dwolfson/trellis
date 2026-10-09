"""The drain's lease reclaim must never make a destructive write due again (incident rule: the drain never
retries a destructive write). A lapsed claim on such a row means the first send may have landed."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from resource_explorer.egeria_outbox import CLAIM_LAPSED_DESTRUCTIVE
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture()
def db(tmp_path):
    reg = ProjectRegistry(database_url=f"sqlite:///{tmp_path/'t.db'}")
    reg._init_schema()
    reg.add(Project(slug="p", display_name="p", github_url="https://github.com/o/p"))
    return reg


def _later():
    return (datetime.utcnow() + timedelta(hours=2)).isoformat()


@pytest.mark.parametrize("kind", ["catalogue_schema_leave_out", "doc_source_unpublish", "some_new_archive_kind"])
def test_a_lapsed_destructive_claim_is_dead_not_due(db, kind):
    row = db.enqueue_outbox_element("repo", "p", kind, "Q::0", {})
    assert [r["id"] for r in db.claim_due_outbox_elements()] == [row]      # claimer takes it, then "dies"
    assert db.peek_due_outbox_elements(now=_later()) == [], "not even visible as due"
    assert db.claim_due_outbox_elements(now=_later()) == [], "never handed to a drainer again"
    r = db.get_outbox_element(row)
    assert r["status"] == "dead"
    assert r["last_error"] == CLAIM_LAPSED_DESTRUCTIVE == "claim lapsed; destructive writes are never re-sent"
    assert db.outbox_counts() == {"dead": 1}


def test_a_lapsed_ordinary_claim_is_still_reclaimed(db):
    row = db.enqueue_outbox_element("repo", "p", "annotation", "Q::0", {})
    db.claim_due_outbox_elements()
    assert [r["id"] for r in db.claim_due_outbox_elements(now=_later())] == [row]


def test_a_destructive_claim_inside_the_lease_is_left_running(db):
    row = db.enqueue_outbox_element("repo", "p", "doc_source_unpublish", "Q::0", {})
    db.claim_due_outbox_elements()
    assert db.claim_due_outbox_elements() == []
    assert db.get_outbox_element(row)["status"] == "running"


def test_a_pending_destructive_row_is_still_sent_the_first_time(db):
    row = db.enqueue_outbox_element("repo", "p", "doc_source_unpublish", "Q::0", {})
    assert [r["id"] for r in db.claim_due_outbox_elements()] == [row]


def test_the_dead_row_is_not_retried_from_the_queue_either(db):
    from fastapi import HTTPException

    from resource_explorer.web.routes import outbox as routes
    row = db.enqueue_outbox_element("repo", "p", "catalogue_schema_leave_out", "Q::0", {})
    db.claim_due_outbox_elements()
    db.claim_due_outbox_elements(now=_later())
    assert routes.is_destructive_kind("catalogue_schema_leave_out") is True
    assert db.get_outbox_element(row)["status"] == "dead"
