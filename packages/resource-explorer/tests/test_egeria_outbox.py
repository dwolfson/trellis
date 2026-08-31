"""Outbox rows and the drain that applies them.

docs/outbox-publishing-design.md §5. What is worth pinning here is not the CRUD
but the four properties the design actually promises: dependency ordering,
exponential backoff, dead-lettering, and idempotent apply.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from resource_explorer.egeria_outbox import OutboxApplyError, apply_element, drain_outbox
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture()
def db(tmp_path):
    reg = ProjectRegistry(database_url=f"sqlite:///{tmp_path/'t.db'}")
    reg._init_schema()
    return reg


@pytest.fixture()
def project(db):
    db.add(Project(slug="p", display_name="p", github_url="https://github.com/o/p"))
    return "p"


def _enqueue(db, slug, kind="annotation", qn="Annotation::p::2026-01-01T00:00:00::0", **kw):
    return db.enqueue_outbox_element("repo", slug, kind, qn, {"class": "X"}, **kw)


class TestEnqueue:
    def test_it_round_trips_and_starts_pending_and_due(self, db, project):
        row_id = _enqueue(db, project)
        due = db.claim_due_outbox_elements()
        assert [r["id"] for r in due] == [row_id]
        assert due[0]["status"] == "pending"
        assert due[0]["attempts"] == 0
        assert json.loads(due[0]["payload_json"]) == {"class": "X"}

    def test_an_empty_qualified_name_is_refused(self, db, project):
        # It is the idempotency key. A row without one cannot be checked for
        # prior application, so accepting it would silently reintroduce the
        # duplicate-on-replay bug the whole table exists to prevent.
        with pytest.raises(ValueError, match="idempotency key"):
            db.enqueue_outbox_element("repo", project, "annotation", "", {})


class TestDependencyOrdering:
    def test_a_dependent_row_is_not_due_until_its_dependency_is_done(self, db, project):
        report = _enqueue(db, project, kind="report", qn="Report::p::1")
        ann = _enqueue(db, project, qn="Annotation::p::1::0", depends_on_id=report)

        assert [r["id"] for r in db.claim_due_outbox_elements()] == [report]

        db.mark_outbox_done(report, "guid-report")
        assert [r["id"] for r in db.claim_due_outbox_elements()] == [ann]

    def test_a_failed_dependency_still_blocks_its_dependent(self, db, project):
        # The point of ordering: a partial drain must leave a coherent prefix,
        # never an annotation whose report was never written.
        report = _enqueue(db, project, kind="report", qn="Report::p::1")
        ann = _enqueue(db, project, qn="Annotation::p::1::0", depends_on_id=report)
        db.mark_outbox_failed(report, "boom")

        assert ann not in [r["id"] for r in db.claim_due_outbox_elements()]


class TestBackoffAndDeadLettering:
    def test_backoff_grows_and_the_row_is_not_immediately_due(self, db, project):
        row_id = _enqueue(db, project)
        now = datetime(2026, 1, 1, 12, 0, 0)

        assert db.mark_outbox_failed(row_id, "e1", now=now, base_delay_seconds=60) == "failed"
        first = db.claim_due_outbox_elements(now=now.isoformat())
        assert first == [], "a just-failed row must wait for its backoff"

        due_later = db.claim_due_outbox_elements(now=(now + timedelta(seconds=61)).isoformat())
        assert [r["id"] for r in due_later] == [row_id]

        # Second failure waits twice as long as the first.
        db.mark_outbox_failed(row_id, "e2", now=now, base_delay_seconds=60)
        assert db.claim_due_outbox_elements(now=(now + timedelta(seconds=61)).isoformat()) == []
        assert db.claim_due_outbox_elements(now=(now + timedelta(seconds=121)).isoformat())

    def test_backoff_is_capped(self, db, project):
        row_id = _enqueue(db, project)
        now = datetime(2026, 1, 1, 12, 0, 0)
        for _ in range(6):
            db.mark_outbox_failed(row_id, "e", now=now, max_attempts=99, base_delay_seconds=60)
        row = db.claim_due_outbox_elements(now=(now + timedelta(days=2)).isoformat())
        assert row, "capped backoff must eventually come due"
        gap = datetime.fromisoformat(row[0]["next_attempt_at"]) - now
        assert gap <= timedelta(days=1)

    def test_it_dead_letters_instead_of_retrying_forever(self, db, project):
        row_id = _enqueue(db, project)
        statuses = [db.mark_outbox_failed(row_id, "nope", max_attempts=3) for _ in range(3)]
        assert statuses == ["failed", "failed", "dead"]

        # Terminal: never picked up again, however far in the future.
        assert db.claim_due_outbox_elements(now="2099-01-01T00:00:00") == []
        dead = db.list_dead_outbox_elements()
        assert [r["id"] for r in dead] == [row_id]
        assert dead[0]["last_error"] == "nope"

    def test_a_long_error_is_truncated_rather_than_rejected(self, db, project):
        row_id = _enqueue(db, project)
        db.mark_outbox_failed(row_id, "x" * 5000)
        assert len(db.list_dead_outbox_elements(limit=0) or []) == 0
        row = db.claim_due_outbox_elements(now="2099-01-01T00:00:00")[0]
        assert len(row["last_error"]) <= 2000


class TestApplyIsIdempotent:
    def test_a_recorded_guid_short_circuits_without_writing(self, db, project):
        calls = []
        discovery = type("D", (), {"create_annotation": lambda self, body: calls.append(body)})()
        row = {"id": 1, "egeria_guid": "already-there", "qualified_name": "Q",
               "element_kind": "annotation", "payload_json": "{}"}

        assert apply_element(row, discovery, lambda qn: "") == "already-there"
        assert calls == [], "a row with a GUID must not write again"

    def test_it_adopts_an_existing_element_instead_of_duplicating_it(self, db, project):
        # The exact failure the design names: Egeria wrote the annotation, we
        # crashed before recording success. Replaying must converge.
        calls = []
        discovery = type("D", (), {"create_annotation": lambda self, body: calls.append(body)})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Annotation::p::1::0",
               "element_kind": "annotation", "payload_json": "{}"}

        assert apply_element(row, discovery, lambda qn: "found-guid") == "found-guid"
        assert calls == [], "a qualifiedName hit must adopt, not create"

    def test_it_creates_when_nothing_exists(self, db, project):
        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "new"}})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Annotation::p::1::0",
               "element_kind": "annotation", "payload_json": '{"class": "X"}'}

        assert apply_element(row, discovery, lambda qn: "") == "new"

    def test_a_lookup_that_raises_falls_through_to_create(self, db, project):
        discovery = type("D", (), {"create_annotation": lambda self, body: "new"})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Q",
               "element_kind": "annotation", "payload_json": "{}"}

        def boom(qn):
            raise RuntimeError("lookup down")

        assert apply_element(row, discovery, boom) == "new"

    def test_an_unknown_element_kind_raises_rather_than_reporting_success(self, db, project):
        # A row that reports 'done' without writing anything is the exact
        # confident-wrong-answer this subsystem exists to remove.
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Q",
               "element_kind": "wormhole", "payload_json": "{}"}
        with pytest.raises(OutboxApplyError, match="wormhole"):
            apply_element(row, object(), lambda qn: "")


class TestDrain:
    def test_it_applies_due_rows_and_records_their_guids(self, db, project):
        row_id = _enqueue(db, project)
        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "g1"}})()

        summary = drain_outbox(db, discovery, lambda qn: "")
        assert summary["done"] == 1 and summary["failed"] == 0
        assert db.outbox_counts() == {"done": 1}

    def test_one_bad_row_does_not_stop_the_rest(self, db, project):
        bad = _enqueue(db, project, qn="Annotation::p::1::0")
        good = _enqueue(db, project, qn="Annotation::p::1::1")

        class D:
            def create_annotation(self, body):
                if body.get("fail"):
                    raise RuntimeError("egeria said no")
                return {"guid": "ok"}

        db.enqueue_outbox_element("repo", project, "annotation", "Q3", {"fail": True})
        summary = drain_outbox(db, D(), lambda qn: "")
        assert summary["done"] == 2 and summary["failed"] == 1

    def test_no_client_leaves_rows_pending_rather_than_burning_an_attempt(self, db, project, monkeypatch):
        # A transient outage must not consume the retry budget — that is how
        # a good write dead-letters for reasons that had nothing to do with it.
        _enqueue(db, project)
        monkeypatch.setattr(
            "resource_explorer.egeria_outbox._default_clients",
            lambda: (_ for _ in ()).throw(RuntimeError("no platform")),
        )
        summary = drain_outbox(db)
        assert summary["skipped"] == 1 and summary["done"] == 0
        still_due = db.claim_due_outbox_elements()
        assert len(still_due) == 1 and still_due[0]["attempts"] == 0

    def test_an_empty_outbox_is_a_no_op(self, db):
        assert drain_outbox(db, object(), lambda qn: "")["claimed"] == 0


class TestRetention:
    def test_it_purges_only_old_done_rows(self, db, project):
        done_old = _enqueue(db, project, qn="Q1")
        done_new = _enqueue(db, project, qn="Q2")
        dead = _enqueue(db, project, qn="Q3")
        pending = _enqueue(db, project, qn="Q4")

        db.mark_outbox_done(done_old)
        db.mark_outbox_done(done_new)
        db.mark_outbox_failed(dead, "x", max_attempts=1)
        with db._conn() as conn:
            conn.execute("UPDATE egeria_outbox SET completed_at=? WHERE id=?",
                         ("2020-01-01T00:00:00", done_old))

        assert db.purge_outbox_completed(older_than_days=14) == 1
        remaining = db.outbox_counts()
        assert remaining == {"done": 1, "dead": 1, "pending": 1}, (
            "dead rows still need a human and pending rows are live work"
        )
