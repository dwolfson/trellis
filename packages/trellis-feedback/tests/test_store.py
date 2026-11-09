"""The store: items, idempotency, append-only triage, deletion, and external references.

Decisions Q1-Q7 are docs/trellis-feedback-extraction.md §7.
"""
from __future__ import annotations

import threading

import pytest
from trellis_feedback import STATUSES, FeedbackError, FeedbackItem, NotFound


def answer(**kw) -> FeedbackItem:
    base = {"app": "ignored", "kind": "answer", "vote": -1, "query_text": "what changed?", "response_text": "it did"}
    base.update(kw)
    return FeedbackItem(**base)


def product(**kw) -> FeedbackItem:
    base = {"app": "ignored", "kind": "product", "category": "bug", "message": "the button is wrong"}
    base.update(kw)
    return FeedbackItem(**base)


class TestItems:
    def test_a_submitted_item_gets_an_id_and_the_stores_app(self, store):
        item, created = store.submit(answer(user_id="peterprofile"))
        assert created and item.id and item.created_at
        assert item.app == "resource-explorer"
        got = store.get(item.id)
        assert got.query_text == "what changed?" and got.user_id == "peterprofile" and got.vote == -1

    def test_the_full_answer_text_is_kept(self, store):
        # Q4: always the full answer, whatever the vote -- including a positive one.
        long = "x" * 50_000
        item, _ = store.submit(answer(vote=1, response_text=long))
        assert store.get(item.id).response_text == long

    @pytest.mark.parametrize("bad, words", [
        ({"kind": "other"}, "kind"),
        ({"vote": 2}, "vote"),
        ({"query_text": ""}, "query_text"),
        ({"rating": 9}, "rating"),
    ])
    def test_a_malformed_answer_is_refused(self, store, bad, words):
        with pytest.raises(FeedbackError, match=words):
            store.submit(answer(**bad))
        assert store.count() == 0

    def test_a_product_item_needs_something_said(self, store):
        with pytest.raises(FeedbackError):
            store.submit(product(category="", message=""))
        with pytest.raises(FeedbackError, match="category"):
            store.submit(product(category="rant"))

    def test_extra_round_trips(self, store):
        item, _ = store.submit(product(extra={"route": "/admin", "n": 3}))
        assert store.get(item.id).extra == {"route": "/admin", "n": 3}

    def test_two_apps_on_one_database_do_not_see_each_other(self, make_store):
        re_store = make_store("resource-explorer")
        ea_store = make_store("egeria-advisor")
        a, _ = re_store.submit(answer())
        ea_store.submit(answer())
        assert re_store.count() == 1 and ea_store.count() == 1
        assert ea_store.get(a.id) is None
        with pytest.raises(NotFound):
            ea_store.triage(a.id, "actioned")


class TestIdempotency:
    def test_a_retried_submit_returns_the_first_item(self, store):
        first, created = store.submit(answer(), idempotency_key="k1")
        again, created_again = store.submit(answer(query_text="different body"), idempotency_key="k1")
        assert created and not created_again
        assert again.id == first.id and again.query_text == "what changed?"
        assert store.count() == 1

    def test_no_key_means_no_deduplication(self, store):
        store.submit(answer())
        store.submit(answer())
        assert store.count() == 2

    def test_the_same_key_in_two_apps_is_two_items(self, make_store):
        a, _ = make_store("resource-explorer").submit(answer(), idempotency_key="k")
        b, _ = make_store("egeria-advisor").submit(answer(), idempotency_key="k")
        assert a.id != b.id

    def test_concurrent_retries_with_one_key_store_one_item(self, store):
        results = []

        def go():
            results.append(store.submit(answer(), idempotency_key="race"))

        threads = [threading.Thread(target=go) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert store.count() == 1
        assert len({item.id for item, _ in results}) == 1
        assert sum(1 for _, created in results if created) == 1


class TestTriage:
    def test_an_untouched_item_is_new(self, store):
        item, _ = store.submit(answer())
        state = store.state(item.id)
        assert (state.status, state.events) == ("new", 0)

    def test_the_latest_event_is_the_status_and_every_note_is_kept(self, store):
        item, _ = store.submit(answer())
        store.triage(item.id, "triaged", note="seen", actor="erinoverview")
        store.triage(item.id, "known_issue", note="same as #12", actor="peterprofile")
        state = store.state(item.id)
        assert (state.status, state.note, state.actor, state.events) == ("known_issue", "same as #12", "peterprofile", 2)
        assert [(e.status, e.note) for e in store.history(item.id)] == [("triaged", "seen"), ("known_issue", "same as #12")]

    def test_events_are_ordered_by_sequence_not_time(self, store):
        item, _ = store.submit(answer())
        seqs = [store.triage(item.id, s).seq for s in ("triaged", "deferred", "actioned")]
        assert seqs == sorted(seqs) and len(set(seqs)) == 3
        assert store.state(item.id).status == "actioned"

    def test_all_six_statuses_are_accepted_and_nothing_else(self, store):
        # Q1: EA's five plus RE's `triaged`.
        assert STATUSES == ("new", "triaged", "known_issue", "actioned", "deferred", "not_an_issue")
        item, _ = store.submit(answer())
        for s in STATUSES:
            store.triage(item.id, s)
        with pytest.raises(FeedbackError, match="status"):
            store.triage(item.id, "resolved")

    def test_triage_of_a_missing_item_is_refused(self, store):
        with pytest.raises(NotFound):
            store.triage("no-such-id", "actioned")

    def test_an_undeclared_source_is_refused(self, store):
        with pytest.raises(FeedbackError, match="declared"):
            store.triage("1", "actioned", source="resource_feedbak")

    def test_list_filters_on_the_current_status(self, store):
        a, _ = store.submit(answer(query_text="a"))
        b, _ = store.submit(answer(query_text="b"))
        store.triage(a.id, "actioned")
        store.triage(b.id, "actioned")
        store.triage(b.id, "new")          # reopened
        assert [r["id"] for r in store.list(status="actioned")] == [a.id]
        assert [r["id"] for r in store.list(status="new")] == [b.id]

    def test_a_listed_rows_triage_target_is_always_that_row(self, store):
        """The guard for EA's live bug (§1): its admin view numbered records by their position in a
        filtered list, and triage treated the number as a raw line, so one skipped line made edits
        land on the wrong record. Here the only handle is the item's own id, so for every listed
        row, triaging by that row's id must change that row and no other -- including when odd rows
        (empty optional fields, unicode, a very long body) sit between them."""
        odd = [
            answer(query_text="ordinary"),
            answer(query_text="éè \U0001f44e 中文", response_text=""),
            product(message="", rating=3, category=""),
            answer(query_text="long", response_text="y" * 100_000),
            product(),
        ]
        for it in odd:
            store.submit(it)
        listed = store.list()
        assert len(listed) == len(odd)
        wanted = {}
        for n, row in enumerate(listed):
            status = STATUSES[1 + n % (len(STATUSES) - 1)]
            store.triage(row["id"], status, note=f"row {n}")
            wanted[row["id"]] = (status, f"row {n}")
        for row in store.list():
            assert (row["triage"]["status"], row["triage"]["note"]) == wanted[row["id"]]
            assert row == {**store.get(row["id"]).to_dict(), "triage": row["triage"]}

    def test_concurrent_triage_and_submits_lose_nothing(self, store):
        a, _ = store.submit(answer(query_text="a"))
        b, _ = store.submit(answer(query_text="b"))
        errors = []

        def triage(item_id, n):
            try:
                for i in range(n):
                    store.triage(item_id, "triaged" if i % 2 else "deferred", note=str(i))
            except Exception as exc:  # noqa: BLE001 -- collected and asserted on below
                errors.append(exc)

        def submit(n):
            try:
                for _ in range(n):
                    store.submit(product())
            except Exception as exc:  # noqa: BLE001 -- collected and asserted on below
                errors.append(exc)

        threads = [threading.Thread(target=triage, args=(a.id, 15)),
                   threading.Thread(target=triage, args=(b.id, 15)),
                   threading.Thread(target=submit, args=(15,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        assert len(store.history(a.id)) == 15 and len(store.history(b.id)) == 15
        assert store.count(kind="product") == 15


class TestDeletion:
    def test_deleting_an_item_removes_its_events_too(self, store):
        # Q6: deleting removes the item, its text and its triage history.
        item, _ = store.submit(answer())
        store.triage(item.id, "triaged", note="has a note")
        assert store.delete_item(item.id)
        assert store.get(item.id) is None
        assert store.history(item.id) == []
        assert item.id not in store.referenced("item")

    def test_deleting_a_missing_item_says_so(self, store):
        assert store.delete_item("nope") is False

    def test_sequence_numbers_are_not_reused_after_a_delete(self, store):
        a, _ = store.submit(answer())
        last = store.triage(a.id, "triaged").seq
        store.delete_item(a.id)
        b, _ = store.submit(answer())
        assert store.triage(b.id, "triaged").seq > last


class TestExternalReferences:
    def test_an_external_row_is_triaged_by_reference(self, store):
        store.triage("42", "known_issue", source="resource_feedback", note="dup")
        assert store.state("42", source="resource_feedback").status == "known_issue"
        assert store.states(["42", "43"], source="resource_feedback")["43"].status == "new"
        # an external id and a library id are different subjects
        assert store.history("42") == []

    def test_a_row_deleted_outside_the_library_keeps_its_history_as_gone(self, store):
        # Q7: RE deletes the row itself; the events stay, shown as "item gone", until an admin
        # deletes them.
        store.triage("7", "triaged", source="resource_feedback", note="looking")
        store.triage("8", "actioned", source="resource_feedback")
        still_there = {"8"}
        assert store.gone("resource_feedback", lambda ids: [i for i in ids if i in still_there]) == ["7"]
        assert [e.note for e in store.history("7", source="resource_feedback")] == ["looking"]
        assert store.delete_events("7", source="resource_feedback") == 1
        assert store.gone("resource_feedback", lambda ids: [i for i in ids if i in still_there]) == []

    def test_library_items_cannot_be_gone_or_have_events_deleted_separately(self, store):
        item, _ = store.submit(answer())
        store.triage(item.id, "triaged")
        with pytest.raises(FeedbackError):
            store.delete_events(item.id, source="item")
        with pytest.raises(FeedbackError):
            store.gone("item", lambda ids: [])
        assert len(store.history(item.id)) == 1

    def test_a_reserved_or_malformed_source_name_is_refused(self, make_store):
        with pytest.raises(FeedbackError):
            make_store(external_sources=("item",))
        with pytest.raises(FeedbackError):
            make_store(external_sources=("Resource Feedback",))
