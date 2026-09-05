"""
Tests for the per-user namespacing + ownership mechanism added to
advisor/governance_docs.py (docs/runtime-architecture-plan.md §4).

Mirrors the pattern in tests/unit/test_governance_docs.py (monkeypatch
_load_paths to a tmp_path) and tests/unit/test_draft_namespacing.py
(ownership visibility). Also exercises that the full inbox → outbox →
trash lifecycle keeps working end-to-end for a document created in a
user's namespace, which is the actual risk this mechanism has to cover —
see governance_docs.DocumentManager's class docstring.
"""
from __future__ import annotations

import pytest

from advisor.governance_docs import DocumentManager


@pytest.fixture
def doc_manager(tmp_path, monkeypatch):
    paths = {
        "inbox": tmp_path / "inbox",
        "outbox": tmp_path / "outbox",
        "trash": tmp_path / "trash",
        "versions": tmp_path / "versions",
    }
    monkeypatch.setattr("advisor.governance_docs._load_paths", lambda: paths)
    return DocumentManager()


def test_create_with_no_user_id_writes_to_shared_root_unchanged(doc_manager, tmp_path):
    doc_id = doc_manager.create("Shared Plan", "# Shared Plan\n\ncontent")
    assert (tmp_path / "inbox" / f"{doc_id}.md").exists()
    assert doc_manager.folder_of(doc_id) == "inbox"


def test_create_with_user_id_writes_under_users_subtree(doc_manager, tmp_path):
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")
    expected = tmp_path / "users" / "alice" / "inbox" / f"{doc_id}.md"
    assert expected.exists()
    assert not (tmp_path / "inbox" / f"{doc_id}.md").exists()


def test_namespaced_doc_is_findable_via_load_with_no_requester_args(doc_manager):
    """Internal engine callers (execute/validate/fork/...) call load(doc_id)
    with no requester context and must still find a namespaced document —
    this is what keeps the whole lifecycle working for a namespaced plan
    with zero changes to governance_plan_agent.py/plan_elicitor.py."""
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")
    assert doc_manager.load(doc_id) is not None
    assert doc_manager.folder_of(doc_id) == "inbox"


def test_namespaced_doc_full_lifecycle_execute_and_back(doc_manager):
    """A document created in a user's namespace survives the full
    inbox -> outbox -> trash -> restore cycle, landing back in the SAME
    namespace at every step (never silently falling back to shared)."""
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")

    outbox_doc_id = doc_manager.move_to_outbox(doc_id, "## Outcome\n\nDone")
    assert outbox_doc_id is not None
    assert doc_manager.folder_of(outbox_doc_id) == "outbox"
    assert doc_manager._owner_of_root(doc_manager._locate(outbox_doc_id, ("outbox",))[0]) == "alice"

    recovered = doc_manager.move_to_inbox(outbox_doc_id)
    assert recovered == doc_id
    assert doc_manager.folder_of(doc_id) == "inbox"
    assert doc_manager._owner_of_root(doc_manager._locate(doc_id, ("inbox",))[0]) == "alice"

    assert doc_manager.delete(doc_id) is True
    assert doc_manager.folder_of(doc_id) == "trash"
    assert doc_manager.restore_from_trash(doc_id) is True
    assert doc_manager.folder_of(doc_id) == "inbox"
    assert doc_manager._owner_of_root(doc_manager._locate(doc_id, ("inbox",))[0]) == "alice"


def test_load_enforce_ownership_owner_sees_their_own(doc_manager):
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")
    content = doc_manager.load(doc_id, requester_user_id="alice", requester_role="user",
                                enforce_ownership=True)
    assert content is not None


def test_load_enforce_ownership_other_user_gets_none(doc_manager):
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")
    content = doc_manager.load(doc_id, requester_user_id="bob", requester_role="user",
                                enforce_ownership=True)
    assert content is None  # 404-shaped, matches the draft store's rule


def test_load_enforce_ownership_curator_sees_anyones(doc_manager):
    doc_id = doc_manager.create("Alice's Plan", "# Alice's Plan\n\ncontent", user_id="alice")
    content = doc_manager.load(doc_id, requester_user_id="admin_user", requester_role="admin",
                                enforce_ownership=True)
    assert content is not None


def test_load_enforce_ownership_shared_doc_visible_to_anyone(doc_manager):
    doc_id = doc_manager.create("Shared Plan", "# Shared Plan\n\ncontent")  # no user_id
    content = doc_manager.load(doc_id, requester_user_id="bob", requester_role="user",
                                enforce_ownership=True)
    assert content is not None


def test_list_inbox_no_args_is_shared_only_unchanged(doc_manager):
    doc_manager.create("Shared Plan", "# Shared Plan")
    doc_manager.create("Alice's Plan", "# Alice's Plan", user_id="alice")
    entries = doc_manager.list_inbox()
    titles = {e["title"] for e in entries}
    assert titles == {"Shared Plan"}
    assert "owner" not in entries[0]  # no requester args -> back-compat shape, no owner key


def test_list_inbox_with_requester_merges_shared_and_own(doc_manager):
    doc_manager.create("Shared Plan", "# Shared Plan")
    doc_manager.create("Alice's Plan", "# Alice's Plan", user_id="alice")
    doc_manager.create("Bob's Plan", "# Bob's Plan", user_id="bob")

    entries = doc_manager.list_inbox(requester_user_id="alice", requester_role="user")
    titles = {e["title"] for e in entries}
    assert titles == {"Shared Plan", "Alice's Plan"}


def test_list_inbox_curator_sees_all_namespaces(doc_manager):
    doc_manager.create("Shared Plan", "# Shared Plan")
    doc_manager.create("Alice's Plan", "# Alice's Plan", user_id="alice")
    doc_manager.create("Bob's Plan", "# Bob's Plan", user_id="bob")

    entries = doc_manager.list_inbox(requester_user_id="admin_user", requester_role="admin")
    titles = {e["title"] for e in entries}
    assert titles == {"Shared Plan", "Alice's Plan", "Bob's Plan"}


def test_existing_shared_docs_are_never_moved(doc_manager, tmp_path):
    """Migration note: pre-existing shared items stay in the shared
    namespace — nothing in this mechanism relocates a file."""
    doc_id = doc_manager.create("Shared Plan", "# Shared Plan")
    path_before = tmp_path / "inbox" / f"{doc_id}.md"
    assert path_before.exists()

    # Namespaced operations on other documents must not disturb it
    doc_manager.create("Alice's Plan", "# Alice's Plan", user_id="alice")
    doc_manager.list_inbox(requester_user_id="alice", requester_role="user")

    assert path_before.exists()
    assert doc_manager.folder_of(doc_id) == "inbox"
