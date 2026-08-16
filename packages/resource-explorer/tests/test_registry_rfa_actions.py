"""Tests for the rfa_actions registry methods — docs/rfa-egeria-todo-followup.md's
"one model, not one location" decision (rfa_actions mirrors ToDoProperties
directly) plus the sync-bookkeeping methods (mark_rfa_synced/
mark_rfa_sync_error/list_unsynced_rfa_actions/list_synced_rfa_actions/
update_rfa_from_remote) the reconciliation pass (rfa_egeria_sync.py) needs.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


class TestUpsertRfaAction:
    def test_stores_both_friendly_status_and_activity_status(self, registry):
        registry.upsert_rfa_action(
            rfa_id="e1::0", entry_id="e1", annotation_index=0,
            status="deferred", activity_status="WAITING", defer_until="2026-09-01",
        )
        row = registry.get_rfa_action("e1::0")
        assert row["rfa_status"] == "deferred"
        assert row["activity_status"] == "WAITING"
        assert row["defer_until"] == "2026-09-01"
        assert row["due_time"] == "2026-09-01"

    def test_upsert_updates_existing_row(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        registry.upsert_rfa_action("e1::0", "e1", 0, status="completed", activity_status="COMPLETED")
        row = registry.get_rfa_action("e1::0")
        assert row["rfa_status"] == "completed"
        assert row["activity_status"] == "COMPLETED"

    def test_new_row_defaults_unsynced(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        row = registry.get_rfa_action("e1::0")
        assert row["egeria_todo_guid"] == ""
        assert row["synced_at"] == ""
        assert row["sync_error"] == ""

    def test_priority_and_start_time_round_trip(self, registry):
        registry.upsert_rfa_action(
            "e1::0", "e1", 0, status="open", activity_status="REQUESTED",
            start_time="2026-09-01T00:00:00", priority=5,
        )
        row = registry.get_rfa_action("e1::0")
        assert row["start_time"] == "2026-09-01T00:00:00"
        assert row["priority"] == 5


class TestUpsertRfaNote:
    def test_note_creates_a_row_when_none_exists(self, registry):
        registry.upsert_rfa_note("e1::0", "e1", 0, "first interaction is a note")
        row = registry.get_rfa_action("e1::0")
        assert row["notes"] == "first interaction is a note"
        assert row["rfa_status"] == "open"

    def test_note_does_not_disturb_existing_status_fields(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="deferred", activity_status="WAITING", defer_until="2026-09-01")
        registry.upsert_rfa_note("e1::0", "e1", 0, "a note on a deferred item")
        row = registry.get_rfa_action("e1::0")
        assert row["notes"] == "a note on a deferred item"
        assert row["rfa_status"] == "deferred"
        assert row["defer_until"] == "2026-09-01"

    def test_note_overwrites_on_repeat_calls(self, registry):
        registry.upsert_rfa_note("e1::0", "e1", 0, "first note")
        registry.upsert_rfa_note("e1::0", "e1", 0, "second note")
        assert registry.get_rfa_action("e1::0")["notes"] == "second note"


class TestSyncBookkeeping:
    def test_mark_rfa_synced_sets_guid_and_clears_error(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        registry.mark_rfa_sync_error("e1::0", "boom")
        registry.mark_rfa_synced("e1::0", "todo-guid-123")
        row = registry.get_rfa_action("e1::0")
        assert row["egeria_todo_guid"] == "todo-guid-123"
        assert row["sync_error"] == ""
        assert row["synced_at"]

    def test_mark_rfa_sync_error_records_message(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        registry.mark_rfa_sync_error("e1::0", "connection refused")
        row = registry.get_rfa_action("e1::0")
        assert row["sync_error"] == "connection refused"

    def test_list_unsynced_includes_never_synced_and_errored(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        registry.upsert_rfa_action("e1::1", "e1", 1, status="open", activity_status="REQUESTED")
        registry.upsert_rfa_action("e1::2", "e1", 2, status="open", activity_status="REQUESTED")
        registry.mark_rfa_synced("e1::1", "guid-1")  # fully synced — excluded
        registry.mark_rfa_synced("e1::2", "guid-2")
        registry.mark_rfa_sync_error("e1::2", "timeout")  # synced once, now errored — included

        unsynced_ids = {r["id"] for r in registry.list_unsynced_rfa_actions()}
        assert unsynced_ids == {"e1::0", "e1::2"}

    def test_list_synced_only_includes_clean_synced_rows(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="open", activity_status="REQUESTED")
        registry.upsert_rfa_action("e1::1", "e1", 1, status="open", activity_status="REQUESTED")
        registry.mark_rfa_synced("e1::1", "guid-1")

        synced_ids = {r["id"] for r in registry.list_synced_rfa_actions()}
        assert synced_ids == {"e1::1"}

    def test_update_rfa_from_remote_overwrites_local_fields(self, registry):
        registry.upsert_rfa_action("e1::0", "e1", 0, status="deferred", activity_status="WAITING", defer_until="2026-09-01")
        registry.mark_rfa_synced("e1::0", "guid-1")

        registry.update_rfa_from_remote("e1::0", "IN_PROGRESS", due_time="2026-10-01", start_time="", priority=3)

        row = registry.get_rfa_action("e1::0")
        assert row["activity_status"] == "IN_PROGRESS"
        assert row["due_time"] == "2026-10-01"
        assert row["priority"] == 3
        # write-direction bookkeeping untouched by a read-direction update
        assert row["egeria_todo_guid"] == "guid-1"
        assert row["sync_error"] == ""
