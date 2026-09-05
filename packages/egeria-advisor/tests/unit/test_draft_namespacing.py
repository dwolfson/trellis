"""
Tests for the per-user namespacing + ownership mechanism added to
advisor/governance_draft.py (docs/runtime-architecture-plan.md §4 /
docs/design/SESSION_AND_INTERACTION_STATE.md's "Storage layout by user").

Filesystem-based (no Postgres needed) — each test points DraftManager's
shared root at a fresh tmp_path via `_drafts_path`, exactly like the
existing governance_docs monkeypatch pattern
(tests/unit/test_governance_docs.py), so a namespaced `users/{uid}/drafts/`
tree is created under tmp_path too (governance_draft's `_user_drafts_path`
derives it from `_drafts_path().parent`).
"""
from __future__ import annotations

import pytest


@pytest.fixture
def draft_env(tmp_path, monkeypatch):
    """Point the shared drafts root at tmp_path/drafts and reset the
    module's per-user manager caches so namespaces from a previous test
    (or the real ~/egeria-plans) can't leak in."""
    import advisor.governance_draft as gd

    shared = tmp_path / "drafts"

    def _shared_path():
        shared.mkdir(parents=True, exist_ok=True)
        return shared

    monkeypatch.setattr(gd, "_drafts_path", _shared_path)
    monkeypatch.setattr(gd, "_dm", None)
    monkeypatch.setattr(gd, "_dm_by_user", {})
    return gd


def _make_draft(dm, title="Test Plan"):
    return dm.create(
        title=title,
        original_query=f"create {title}",
        commands_identified=[],
        pending_questions={"required": [], "optional": []},
        pre_filled_answers={},
    )


def test_shared_manager_writes_to_shared_root_unchanged(draft_env):
    """No-args get_draft_manager() behaves exactly as before this change —
    the anonymous/back-compat path (`_anonymous_rag_mode`)."""
    dm = draft_env.get_draft_manager()
    spec = _make_draft(dm)
    assert spec["user_id"] is None
    assert dm.load(spec["draft_id"]) is not None


def test_namespaced_manager_writes_under_users_subtree(draft_env, tmp_path):
    dm = draft_env.get_draft_manager("alice")
    spec = _make_draft(dm, "Alice's Plan")
    assert spec["user_id"] == "alice"

    expected_dir = tmp_path / "users" / "alice" / "drafts"
    assert (expected_dir / f"{spec['draft_id']}.json").exists()
    # Never lands in the shared root
    assert not (tmp_path / "drafts" / f"{spec['draft_id']}.json").exists()


def test_get_draft_manager_caches_per_user(draft_env):
    dm1 = draft_env.get_draft_manager("alice")
    dm2 = draft_env.get_draft_manager("alice")
    dm3 = draft_env.get_draft_manager("bob")
    assert dm1 is dm2
    assert dm1 is not dm3


def test_existing_shared_items_are_not_moved(draft_env):
    """Migration note: pre-existing shared-namespace drafts stay put — this
    is implicit here (nothing in create()/get_draft_manager() ever moves a
    file), verified by confirming a shared draft is still found via the
    shared manager after a namespaced manager for the same title is used."""
    shared_dm = draft_env.get_draft_manager()
    shared_spec = _make_draft(shared_dm, "Shared Plan")

    alice_dm = draft_env.get_draft_manager("alice")
    _make_draft(alice_dm, "Shared Plan")  # same title, different namespace

    assert shared_dm.load(shared_spec["draft_id"]) is not None


# ---------------------------------------------------------------------------
# Ownership visibility: owner, other user, curator, anonymous
# ---------------------------------------------------------------------------

def test_resolve_draft_owner_sees_their_own(draft_env):
    dm = draft_env.get_draft_manager("alice")
    spec = _make_draft(dm, "Alice's Plan")

    resolved = draft_env.resolve_draft(spec["draft_id"], user_id="alice", role="user")
    assert resolved is not None
    assert resolved[1]["draft_id"] == spec["draft_id"]


def test_resolve_draft_other_user_gets_none_not_403(draft_env):
    dm = draft_env.get_draft_manager("alice")
    spec = _make_draft(dm, "Alice's Plan")

    resolved = draft_env.resolve_draft(spec["draft_id"], user_id="bob", role="user")
    assert resolved is None  # 404-shaped — never distinguishes "not found" from "not yours"


def test_resolve_draft_curator_sees_anyones(draft_env):
    dm = draft_env.get_draft_manager("alice")
    spec = _make_draft(dm, "Alice's Plan")

    resolved = draft_env.resolve_draft(spec["draft_id"], user_id="admin_user", role="admin")
    assert resolved is not None
    assert resolved[1]["draft_id"] == spec["draft_id"]

    # "curator" role (the plan doc's eventual GovernanceRole-backed name) works too
    resolved2 = draft_env.resolve_draft(spec["draft_id"], user_id="someone_else", role="curator")
    assert resolved2 is not None


def test_resolve_draft_anonymous_sees_shared_only(draft_env):
    shared_dm = draft_env.get_draft_manager()
    shared_spec = _make_draft(shared_dm, "Shared Plan")
    alice_dm = draft_env.get_draft_manager("alice")
    alice_spec = _make_draft(alice_dm, "Alice's Plan")

    # Anonymous (user_id=None) finds the shared draft...
    resolved = draft_env.resolve_draft(shared_spec["draft_id"], user_id=None, role=None)
    assert resolved is not None
    # ...but not alice's namespaced one
    resolved2 = draft_env.resolve_draft(alice_spec["draft_id"], user_id=None, role=None)
    assert resolved2 is None


def test_list_visible_drafts_owner_plus_shared(draft_env):
    shared_dm = draft_env.get_draft_manager()
    _make_draft(shared_dm, "Shared Plan")
    alice_dm = draft_env.get_draft_manager("alice")
    _make_draft(alice_dm, "Alice's Plan")
    bob_dm = draft_env.get_draft_manager("bob")
    _make_draft(bob_dm, "Bob's Plan")

    visible = draft_env.list_visible_drafts(user_id="alice", role="user")
    titles = {d["title"] for d in visible}
    assert "Shared Plan" in titles
    assert "Alice's Plan" in titles
    assert "Bob's Plan" not in titles  # not alice's, not shared, not a curator


def test_list_visible_drafts_curator_sees_everything(draft_env):
    shared_dm = draft_env.get_draft_manager()
    _make_draft(shared_dm, "Shared Plan")
    alice_dm = draft_env.get_draft_manager("alice")
    _make_draft(alice_dm, "Alice's Plan")
    bob_dm = draft_env.get_draft_manager("bob")
    _make_draft(bob_dm, "Bob's Plan")

    visible = draft_env.list_visible_drafts(user_id="admin_user", role="admin")
    titles = {d["title"] for d in visible}
    assert titles == {"Shared Plan", "Alice's Plan", "Bob's Plan"}


def test_list_visible_drafts_anonymous_sees_shared_only(draft_env):
    shared_dm = draft_env.get_draft_manager()
    _make_draft(shared_dm, "Shared Plan")
    alice_dm = draft_env.get_draft_manager("alice")
    _make_draft(alice_dm, "Alice's Plan")

    visible = draft_env.list_visible_drafts(user_id=None, role=None)
    titles = {d["title"] for d in visible}
    assert titles == {"Shared Plan"}
