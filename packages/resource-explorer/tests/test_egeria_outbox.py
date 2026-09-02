"""Outbox rows and the drain that applies them.

docs/outbox-publishing-design.md §5. What is worth pinning here is not the CRUD
but the four properties the design actually promises: dependency ordering,
exponential backoff, dead-lettering, and idempotent apply.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from resource_explorer.egeria_outbox import (
    OutboxApplyError,
    OutboxClients,
    apply_element,
    drain_outbox,
    record_drain_outcome,
)
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

        assert apply_element(row, OutboxClients(discovery=discovery), lambda qn: "") == "already-there"
        assert calls == [], "a row with a GUID must not write again"

    def test_it_adopts_an_existing_element_instead_of_duplicating_it(self, db, project):
        # The exact failure the design names: Egeria wrote the annotation, we
        # crashed before recording success. Replaying must converge.
        calls = []
        discovery = type("D", (), {"create_annotation": lambda self, body: calls.append(body)})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Annotation::p::1::0",
               "element_kind": "annotation", "payload_json": "{}"}

        assert apply_element(row, OutboxClients(discovery=discovery), lambda qn: "found-guid") == "found-guid"
        assert calls == [], "a qualifiedName hit must adopt, not create"

    def test_it_creates_when_nothing_exists(self, db, project):
        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "new"}})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Annotation::p::1::0",
               "element_kind": "annotation", "payload_json": '{"class": "X"}'}

        assert apply_element(row, OutboxClients(discovery=discovery), lambda qn: "") == "new"

    def test_a_lookup_that_raises_falls_through_to_create(self, db, project):
        discovery = type("D", (), {"create_annotation": lambda self, body: "new"})()
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Q",
               "element_kind": "annotation", "payload_json": "{}"}

        def boom(qn):
            raise RuntimeError("lookup down")

        assert apply_element(row, OutboxClients(discovery=discovery), boom) == "new"

    def test_an_unknown_element_kind_raises_rather_than_reporting_success(self, db, project):
        # A row that reports 'done' without writing anything is the exact
        # confident-wrong-answer this subsystem exists to remove.
        row = {"id": 1, "egeria_guid": "", "qualified_name": "Q",
               "element_kind": "wormhole", "payload_json": "{}"}
        with pytest.raises(OutboxApplyError, match="wormhole"):
            apply_element(row, OutboxClients(discovery=object()), lambda qn: "")


class TestDrain:
    def test_it_applies_due_rows_and_records_their_guids(self, db, project):
        row_id = _enqueue(db, project)
        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "g1"}})()

        summary = drain_outbox(db, OutboxClients(discovery=discovery), lambda qn: "")
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
        summary = drain_outbox(db, OutboxClients(discovery=D()), lambda qn: "")
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
        assert drain_outbox(db, OutboxClients(discovery=object()), lambda qn: "")["claimed"] == 0


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


class TestRunScoping:
    """A publisher that enqueues then drains inline must write ITS OWN rows.

    An unscoped claim takes the oldest due rows in the table, so a publish
    could drain an unrelated resource's backlog and return believing it had
    published — the caller would see success with none of its own annotations
    written.
    """

    def test_a_scoped_drain_leaves_other_runs_alone(self, db, project):
        old = db.enqueue_outbox_element("repo", project, "annotation", "Old::0", {}, run_id="run-old")
        mine = db.enqueue_outbox_element("repo", project, "annotation", "Mine::0", {}, run_id="run-mine")

        claimed = db.claim_due_outbox_elements(run_id="run-mine")
        assert [r["id"] for r in claimed] == [mine], "the older row must not be claimed"

        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "g"}})()
        drain_outbox(db, OutboxClients(discovery=discovery), lambda qn: "", run_id="run-mine")

        counts = db.outbox_counts()
        assert counts == {"done": 1, "pending": 1}
        assert [r["id"] for r in db.claim_due_outbox_elements()] == [old]

    def test_an_unscoped_drain_still_sees_everything(self, db, project):
        db.enqueue_outbox_element("repo", project, "annotation", "A::0", {}, run_id="r1")
        db.enqueue_outbox_element("repo", project, "annotation", "B::0", {}, run_id="r2")
        assert len(db.claim_due_outbox_elements()) == 2


class TestEnqueueAnnotations:
    def test_it_writes_one_row_per_annotation_with_indexed_qualified_names(self, db, project):
        from resource_explorer.egeria_outbox import enqueue_annotations
        from resource_explorer.surveyors.survey_report import ClassificationAnnotation

        # The real annotation class, not a stub — build_annotation_body reads
        # fields a hand-rolled fake will not have, and a fake that drifts from
        # the real shape is how the filesystem publisher's AttributeError
        # survived under test (see test_annotation_props.py's docstring).
        anns = [ClassificationAnnotation(summary="a", analysis_step="s",
                                         candidate_classifications=["python"]),
                ClassificationAnnotation(summary="b", analysis_step="s",
                                         candidate_classifications=["rust"])]
        ids = enqueue_annotations(
            db, "repo", project, anns, "report-guid",
            "Annotation::p::2026-01-01T00:00:00", run_id="r1",
        )
        assert len(ids) == 2
        rows = db.claim_due_outbox_elements(run_id="r1")
        assert [r["qualified_name"] for r in rows] == [
            "Annotation::p::2026-01-01T00:00:00::0",
            "Annotation::p::2026-01-01T00:00:00::1",
        ]
        body = json.loads(rows[0]["payload_json"])
        assert body["parentGUID"] == "report-guid"
        assert body["class"] == "NewElementRequestBody"

    def test_no_annotations_enqueues_nothing(self, db, project):
        from resource_explorer.egeria_outbox import enqueue_annotations

        assert enqueue_annotations(db, "repo", project, [], "g", "Q") == []
        assert db.outbox_counts() == {}


class TestDrainOutcomeIsVisible:
    """Logging is not a surface: nothing configures logging and uvicorn.run()
    is called without a log_config, so INFO is discarded and WARNING/ERROR
    reach only the server's stderr. Failures must reach the activity log."""

    def test_a_failure_is_written_to_the_activity_log(self, db, project):
        _enqueue(db, project)

        class D:
            def create_annotation(self, body):
                raise RuntimeError("egeria said no")

        drain_outbox(db, OutboxClients(discovery=D()), lambda qn: "")
        entries = db.list_activity(limit=10)
        assert any("Egeria publish incomplete" in e["summary"] for e in entries), (
            "a failed drain must be visible in the Activity tab, not only on stderr"
        )

    def test_a_clean_pass_writes_no_activity_entry(self, db, project):
        # An entry every quarter-hour saying nothing was wrong is how a log
        # stops being read.
        _enqueue(db, project)
        discovery = type("D", (), {"create_annotation": lambda self, body: {"guid": "g"}})()
        drain_outbox(db, OutboxClients(discovery=discovery), lambda qn: "")
        assert db.list_activity(limit=10) == []


class TestCollectionMemberships:
    """Investigation membership writes (design §6 step 5).

    Idempotency here is NOT lookup-then-create — a CollectionMembership has no
    qualifiedName to search for. It rests on the relationship being uni-link,
    measured live 2026-08-25: add_to_collection returns None and adding the
    same element twice leaves one member.
    """

    def test_it_attaches_the_member_to_the_collection(self, db, project):
        from resource_explorer.egeria_outbox import OutboxClients, enqueue_collection_members

        calls = []

        class CM:
            def add_to_collection(self, coll, member):
                calls.append((coll, member))

        enqueue_collection_members(
            db, "inv-1", "coll-guid",
            [{"entity_type": "repo", "entity_slug": "p", "member_guid": "asset-1"}],
            run_id="r1",
        )
        summary = drain_outbox(db, OutboxClients(collection_manager=CM()), lambda qn: "", run_id="r1")

        assert summary["done"] == 1
        assert calls == [("coll-guid", "asset-1")]

    def test_replaying_a_membership_calls_the_upsert_again_rather_than_skipping(self, db, project):
        # Deliberate: there is no element to find by qualifiedName, so the
        # apply step cannot short-circuit. Safety comes from the operation.
        from resource_explorer.egeria_outbox import apply_element

        calls = []

        class CM:
            def add_to_collection(self, coll, member):
                calls.append((coll, member))

        row = {"id": 1, "egeria_guid": "", "qualified_name": "CollectionMembership::c::m",
               "element_kind": "collection_membership",
               "payload_json": json.dumps({"collection_guid": "c", "member_guid": "m"})}
        apply_element(row, OutboxClients(collection_manager=CM()), lambda qn: "")
        apply_element(row, OutboxClients(collection_manager=CM()), lambda qn: "")
        assert len(calls) == 2

    def test_a_missing_client_is_a_failure_not_a_silent_success(self, db, project):
        # The drain was given a discovery client but this row needs the
        # collection manager. Reporting 'done' here would record a write that
        # never happened.
        from resource_explorer.egeria_outbox import apply_element

        row = {"id": 1, "egeria_guid": "", "qualified_name": "CollectionMembership::c::m",
               "element_kind": "collection_membership",
               "payload_json": json.dumps({"collection_guid": "c", "member_guid": "m"})}
        with pytest.raises(OutboxApplyError, match="collection_manager"):
            apply_element(row, OutboxClients(discovery=object()), lambda qn: "")

    def test_resource_list_attaches_collection_to_its_parent(self, db, project):
        from resource_explorer.egeria_outbox import apply_element

        calls = []

        class CM:
            def attach_collection(self, parent, coll):
                calls.append((parent, coll))

        row = {"id": 1, "egeria_guid": "", "qualified_name": "ResourceList::p::c",
               "element_kind": "resource_list",
               "payload_json": json.dumps({"parent_guid": "proj", "collection_guid": "coll"})}
        apply_element(row, OutboxClients(collection_manager=CM()), lambda qn: "")
        assert calls == [("proj", "coll")]

    def test_enqueue_records_the_member_for_the_publish_queue(self, db, project):
        from resource_explorer.egeria_outbox import enqueue_collection_members

        ids = enqueue_collection_members(
            db, "inv-1", "coll",
            [{"entity_type": "repo", "entity_slug": "p", "member_guid": "a1"},
             {"entity_type": "repo", "entity_slug": "q", "member_guid": "a2"}],
            run_id="r1",
        )
        assert len(ids) == 2
        rows = db.list_outbox_elements(run_id="r1")
        assert {r["entity_type"] for r in rows} == {"investigation"}
        assert {json.loads(r["payload_json"])["member_entity_slug"] for r in rows} == {"p", "q"}


class TestNothingWrittenIsNotOneState:
    """Three different outcomes all look like "no elements were written".

    The shape to avoid is the cii_badge bug of 2026-08-31: "matched nothing"
    and "not registered" were both (None, ""), so a real gap read as a
    non-answer. The same collapse is available here — an empty queue, an
    unreachable platform, and every write failing are indistinguishable from
    the outside if all you observe is "nothing landed in Egeria".

    They must stay distinguishable in the summary AND in what reaches a person,
    because the right response to each is different: nothing to do, wait and
    retry, and go look at the errors.
    """

    def _fail_client(self):
        class D:
            def create_annotation(self, body):
                raise RuntimeError("egeria said no")
        return OutboxClients(discovery=D())

    def test_the_three_outcomes_have_different_summaries(self, db, project):
        empty = drain_outbox(db, OutboxClients(discovery=object()), lambda qn: "")

        _enqueue(db, project, qn="Q::fail")
        failed = drain_outbox(db, self._fail_client(), lambda qn: "")

        db.mark_outbox_done(_enqueue(db, project, qn="Q::done2"))
        _enqueue(db, project, qn="Q::skip")
        import resource_explorer.egeria_outbox as mod
        original = mod._default_clients
        mod._default_clients = lambda: (_ for _ in ()).throw(RuntimeError("no platform"))
        try:
            skipped = drain_outbox(db)
        finally:
            mod._default_clients = original

        assert (empty["claimed"], empty["failed"], empty["skipped"]) == (0, 0, 0)
        assert (failed["claimed"], failed["failed"], failed["skipped"]) == (1, 1, 0)
        assert (skipped["claimed"], skipped["failed"], skipped["skipped"]) == (1, 0, 1)

    def test_only_a_failure_reaches_a_person(self, db, project):
        # An empty queue and an unreachable platform are not incidents. A
        # failure is. If all three wrote an activity entry, the entry would
        # stop meaning anything; if none did, the failure would be invisible.
        drain_outbox(db, OutboxClients(discovery=object()), lambda qn: "")
        assert db.list_activity(limit=10) == [], "an empty queue is not an incident"

        _enqueue(db, project, qn="Q::skip")
        import resource_explorer.egeria_outbox as mod
        original = mod._default_clients
        mod._default_clients = lambda: (_ for _ in ()).throw(RuntimeError("no platform"))
        try:
            drain_outbox(db)
        finally:
            mod._default_clients = original
        assert db.list_activity(limit=10) == [], "an outage is not a failed write"

        drain_outbox(db, self._fail_client(), lambda qn: "")
        entries = db.list_activity(limit=10)
        assert len(entries) == 1 and "incomplete" in entries[0]["summary"]

    def test_an_outage_leaves_the_retry_budget_untouched(self, db, project):
        # The consequence of confusing outage with failure: rows would burn
        # attempts and dead-letter for a reason that had nothing to do with them.
        row_id = _enqueue(db, project, qn="Q::skip")
        import resource_explorer.egeria_outbox as mod
        original = mod._default_clients
        mod._default_clients = lambda: (_ for _ in ()).throw(RuntimeError("no platform"))
        try:
            for _ in range(20):
                drain_outbox(db)
        finally:
            mod._default_clients = original
        rows = db.claim_due_outbox_elements()
        assert len(rows) == 1 and rows[0]["attempts"] == 0
        assert db.list_dead_outbox_elements() == []


class TestDeadLettersReachAPerson:
    """A dead-lettered element will never be retried on its own, so it is a
    request for human action rather than a status line — and it has to reach
    the RFA drawer, which is the surface people actually watch.

    The drawer is fed by GET /api/activity/rfas, which keeps only ANNOTATIONS
    whose annotation_type contains "RequestForAction" and ignores
    operation="rfa" entirely. An entry without that annotation exists in the
    activity log and is invisible where it matters — which is exactly how three
    earlier RFA callers were silently unseen.
    """

    def test_a_dead_letter_raises_an_rfa_the_drawer_can_see(self, db, project):
        # Driven to dead via mark_outbox_failed rather than repeated drains:
        # the backoff means real drains would need a clock, and what is under
        # test here is the reporting, not the retry policy.
        row_id = _enqueue(db, project, qn="Q::dead")
        for _ in range(ProjectRegistry.OUTBOX_MAX_ATTEMPTS):
            db.mark_outbox_failed(row_id, "permission denied")
        assert db.list_dead_outbox_elements()

        record_drain_outcome(db, {"claimed": 1, "done": 0, "failed": 0, "dead": 1, "skipped": 0})
        entries = db.list_activity(limit=10)
        assert len(entries) == 1, "one event must produce one entry, not two"
        entry = entries[0]
        assert entry["operation"] == "rfa"
        anns = entry.get("annotations") or []
        assert any("RequestForAction" in (a.get("annotation_type") or "") for a in anns), (
            "without this annotation the RFA drawer never shows it"
        )
        assert "stuck" in entry["summary"]

    def test_a_retrying_failure_is_an_audit_line_not_an_rfa(self, db, project):
        # The scheduler is already handling it; asking a person to act would
        # make the drawer noise, and noise is how a drawer stops being read.
        record_drain_outcome(db, {"claimed": 1, "done": 0, "failed": 1, "dead": 0, "skipped": 0})
        entries = db.list_activity(limit=10)
        assert len(entries) == 1
        assert entries[0]["operation"] == "catalog"
        assert "incomplete" in entries[0]["summary"]

    def test_the_rfa_carries_the_link_to_the_publish_queue(self, db, project):
        record_drain_outcome(db, {"claimed": 1, "dead": 1, "failed": 0, "done": 0, "skipped": 0},
                             troubled_runs={"run-x": "p"})
        entry = db.list_activity(limit=10)[0]
        links = [i for i in (entry.get("items") or []) if i.get("link")]
        assert links and links[0]["link"] == "admin-outbox"
        assert links[0]["run_id"] == "run-x", (
            "an RFA saying publishes are stuck is only actionable if it says which"
        )


class TestResourceListIsQueued:
    def test_it_attaches_the_collection_to_its_parent(self, db, project):
        from resource_explorer.egeria_outbox import enqueue_resource_list

        calls = []

        class CM:
            def attach_collection(self, parent, coll):
                calls.append((parent, coll))

        enqueue_resource_list(db, "inv-1", "proj-guid", "coll-guid", run_id="rl")
        summary = drain_outbox(db, OutboxClients(collection_manager=CM()), lambda qn: "",
                               run_id="rl")
        assert summary["done"] == 1
        assert calls == [("proj-guid", "coll-guid")]

    def test_a_failed_attach_survives_as_a_retryable_row(self, db, project):
        # Previously this failure went into PromotionResult.errors and was
        # forgotten, leaving a Project and Collection that both exist, unlinked.
        from resource_explorer.egeria_outbox import enqueue_resource_list

        class CM:
            def attach_collection(self, parent, coll):
                raise RuntimeError("no permission")

        enqueue_resource_list(db, "inv-1", "p", "c", run_id="rl")
        drain_outbox(db, OutboxClients(collection_manager=CM()), lambda qn: "", run_id="rl")
        rows = db.list_outbox_elements(run_id="rl")
        assert rows[0]["status"] == "failed"
        assert "no permission" in rows[0]["last_error"]


# ── A duplicate-name 409 means "already created", not "failed" ──────────────
#
# Live, 2026-09-01. The pre-fix secret scan enqueued ~48,500 annotations per
# run; some were written to Egeria, then retried. Egeria answered:
#
#   OMAG-COMMON-409-001 ... parameter name qualifiedName is defined as a
#   unique property and value Annotation::egeria_python_git::... is not
#   available for use
#
# which is proof the element EXISTS. It was counted as a write failure, so
# those rows retried a write that had already succeeded — an exception storm
# on the console and rows that could never complete.
#
# apply_element already looks up before creating. The 409 means that lookup
# MISSED something Egeria can see, so the fix is not to skip the lookup but
# to repeat it on rejection and adopt the GUID.
_DUPE = (
    "SERVER_ERROR_500 ... relatedHTTPCode= `409` ... OMAG-COMMON-409-001 Method "
    "createMetadataElementInStore ... parameter name qualifiedName is defined as "
    "a unique property and value Annotation::x::y::1 is not available for use"
)


class TestDuplicateQualifiedName:
    def _row(self):
        return {"id": 1, "egeria_guid": "", "qualified_name": "Annotation::x::y::1",
                "payload_json": "{}", "element_kind": "annotation"}

    def test_a_rejected_duplicate_is_adopted_when_it_can_be_found(self, monkeypatch):
        """Known-negative: remove the 409 branch and this raises instead of
        returning the GUID — which is the retry-forever behaviour."""
        from resource_explorer import egeria_outbox as ob

        monkeypatch.setitem(ob._CREATORS, "annotation",
                            lambda clients, payload: (_ for _ in ()).throw(RuntimeError(_DUPE)))
        lookups = []

        def _find(qn):
            lookups.append(qn)
            return "" if len(lookups) == 1 else "guid-from-second-lookup"

        assert ob.apply_element(self._row(), None, _find) == "guid-from-second-lookup"
        assert len(lookups) == 2, "the lookup must be REPEATED after the rejection"

    def test_an_unfindable_duplicate_is_an_error_not_a_silent_success(self, monkeypatch):
        """Egeria will not create it and we cannot find it. Marking the row
        done would claim success with no GUID to show for it."""
        from resource_explorer import egeria_outbox as ob

        monkeypatch.setitem(ob._CREATORS, "annotation",
                            lambda clients, payload: (_ for _ in ()).throw(RuntimeError(_DUPE)))
        with pytest.raises(ob.OutboxApplyError, match="invisible to our lookup"):
            ob.apply_element(self._row(), None, lambda qn: "")

    def test_an_ordinary_failure_still_fails(self, monkeypatch):
        """The guard must not swallow real write errors — a message that is
        not the duplicate signature propagates untouched."""
        from resource_explorer import egeria_outbox as ob

        monkeypatch.setitem(ob._CREATORS, "annotation",
                            lambda clients, payload: (_ for _ in ()).throw(RuntimeError("connection refused")))
        with pytest.raises(RuntimeError, match="connection refused"):
            ob.apply_element(self._row(), None, lambda qn: "")

    def test_a_passing_mention_of_409_is_not_enough(self):
        """Both markers are required, so an unrelated error that happens to
        contain '409' is not mistaken for an already-created element."""
        from resource_explorer.egeria_outbox import _is_duplicate_qualified_name

        assert not _is_duplicate_qualified_name(RuntimeError("gateway said 409"))
        assert _is_duplicate_qualified_name(RuntimeError(_DUPE))
