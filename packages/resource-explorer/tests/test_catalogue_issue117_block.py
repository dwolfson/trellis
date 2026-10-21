"""Archive-cascade block (ISSUE-117): Egeria archives the WHOLE database tree when any part of it is archived (leaving
out us_sales archived the coco_pharma database element and both demo schemas, 2026-10-06). While
the block is on (the DEFAULT: env var RE_ISSUE_117_BLOCK_OFF unset), NOTHING reaches Egeria for any archive or delete of a database's
tree (schema, table, column, schema type), soft delete included; the choice stays recorded in RE.

These tests run with the block at its DEFAULT (the env var is removed for each test; conftest sets it only for
the older catalogue tests that exercise the frozen delete path against the fake). The block can be lifted ONLY by
RE_ISSUE_117_BLOCK_OFF=<who>/<UTC ISO time>/<database slug>, for ONE database, for 60 minutes, read at call time:
there is no code constant. `test_known_negative_*` proves the guard can fail: with a good override for the slug the
same scenarios DO reach the delete path. These tests run un-stubbed (conftest leaves them alone)."""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_catalogue_commit import (  # noqa: E402,F401  (fixtures and helpers are shared)
    ME, _attached, _catalogued, _zones, choose, derived, entity_stub, fake, press, registry, step, view, world,
)
from resource_explorer import catalogue_commit as cc  # noqa: E402
from resource_explorer import catalogue_gateway as gw  # noqa: E402
from resource_explorer.catalogue_gateway import GatewayError  # noqa: E402


@pytest.fixture(autouse=True)
def _zone_access_open(monkeypatch):
    """Brief Z2: this write path asks `curation_access` (the one decision). These tests are about something else,
    so no zone is in use: the access reads are faked open at the client boundary (`tests/zone_fakes.open_access`)."""
    from tests.zone_fakes import open_access

    return open_access(monkeypatch)

# Brief I: a catalog commit is a person's own action; it runs as a signed-in caller.
pytestmark = pytest.mark.usefixtures("signed_in_caller")

WORDS = ("Egeria archives the whole database tree when any part of it is archived "
         "(archive-cascade block, archiveBeanInRepository) · choice kept, nothing sent")


def stamp(minutes_ago: float = 0.0) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def override_for(monkeypatch, slug: str = "db", minutes_ago: float = 0.0) -> str:
    value = f"tester/{stamp(minutes_ago)}/{slug}"
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", value)
    return value


@pytest.fixture(autouse=True)
def _default_state(monkeypatch):
    monkeypatch.delenv("RE_ISSUE_117_BLOCK_OFF", raising=False)


def sent_to_egeria(fake):
    """Every call that would change Egeria on the leave-out path."""
    return fake.ops("delete_element") + fake.ops("remove_catalog_target")


def test_the_block_is_on_as_shipped():
    assert gw.issue_117_blocked("db") is True and gw.issue_117_blocked("") is True and gw.ISSUE_117_WORDS == WORDS
    assert not hasattr(gw, "ISSUE_117_BLOCK"), "no code constant to edit"


# ── the real gateway: every kind of element, both forms ─────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["schema", "table", "column", "schema type"])
@pytest.mark.parametrize("form", [gw.ARCHIVE, gw.SOFT_DELETE])
def test_the_real_gateway_sends_nothing_for_any_element_of_a_database_tree(kind, form):
    g = gw.PyegeriaCatalogueGateway(entity_stub())
    clients = {n: MagicMock(name=n) for n in ("AssetMaker", "MetadataExpert", "AutomatedCuration", "ServerOps")}
    g._clients.update(clients)
    with pytest.raises(GatewayError) as err:
        g.delete_element(f"guid-of-a-{kind}", form, slug="db")
    assert str(err.value) == WORDS
    for name, c in clients.items():
        assert c.method_calls == [], f"{name} was called: nothing may be sent"


# ── through the commit: preview, press, outbox ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("setup", [_attached, _catalogued])
def test_leaving_out_a_cataloged_schema_sends_nothing_and_keeps_the_choice(world, fake, setup):
    setup(world, fake, "sales")
    before = len(sent_to_egeria(fake))
    choose(world, "sales", "leave_out")
    choose(world, "archive", "catalogue")                    # something else to commit, so the press happens
    out, rec = press(world, fake)
    row = next(r for r in out["preview"]["leave_out"] if r["schema"] == "sales")
    assert row["form"] == "issue_117" and row["blocked"] is True
    assert row["text"] == f"sales: {WORDS}"
    assert len(sent_to_egeria(fake)) == before, "the delete path was reached for a cataloged schema"
    assert step(rec, "leave_outs")["state"] == "skipped"
    assert view(world)["schemas"][[s["name"] for s in view(world)["schemas"]].index("sales")]["effective"] == "leave_out", "the choice is kept"
    assert any(n["reason"] == WORDS for n in out["preview"]["manifest"]["not_committed"])


def test_the_outbox_handler_refuses_a_cataloged_schema_before_sending_anything(world, fake):
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    before = len(sent_to_egeria(fake))
    with pytest.raises(GatewayError) as err:
        cc.apply_leave_out(world["registry"], fake, {"slug": "db", "schema": "sales", "form": gw.ARCHIVE, "curation_id": "c1", "by": ME})
    assert WORDS in str(err.value)
    assert len(sent_to_egeria(fake)) == before


def test_a_schema_that_was_never_cataloged_is_still_just_nothing_to_remove(world, fake):
    choose(world, "sales", "leave_out")
    choose(world, "archive", "catalogue")
    out, _ = press(world, fake)
    row = next(r for r in out["preview"]["leave_out"] if r["schema"] == "sales")
    assert row["form"] == "none" and "nothing to remove" in row["text"]


# ── the guard can fail ─────────────────────────────────────────────────────────────────────────────────────

# ── the switch: only the env var, one database, 60 minutes, read at call time ─────────────────────────────

def test_blank_values_leave_the_block_on(monkeypatch):
    for blank in ("", "   "):
        monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", blank)
        assert gw.issue_117_blocked("db") is True


def test_the_named_slug_inside_the_window_passes_the_guard(monkeypatch):
    override_for(monkeypatch, "db", minutes_ago=59)
    assert gw.issue_117_blocked("db") is False


def test_known_negative_the_named_slug_after_expiry_is_refused(monkeypatch):
    override_for(monkeypatch, "db", minutes_ago=61)
    assert gw.issue_117_blocked("db") is True
    override_for(monkeypatch, "db", minutes_ago=60)             # the boundary itself is expired
    assert gw.issue_117_blocked("db") is True


def test_another_slug_is_refused_while_the_override_is_set(monkeypatch):
    override_for(monkeypatch, "throwaway_db")
    assert gw.issue_117_blocked("throwaway_db") is False
    for other in ("db", "coco_pharma", "throwaway_db2", "THROWAWAY_DB", ""):
        assert gw.issue_117_blocked(other) is True, other


@pytest.mark.parametrize("value", [
    "test-clearance",                                            # the old bare clearance
    "dwolfson/2026-10-07T01:00Z",                                # the old <who>/<UTC> shape: no slug
    "tests/legacy-delete-path-fixture",                          # two parts, no time
    "dwolfson/not-a-time/db",                                    # unparsable time
    "dwolfson//db", "/2026-10-07T01:00:00Z/db", "dwolfson/2026-10-07T01:00:00Z/",   # an empty part
    "a/b/c/d",                                                   # a bad time in the third position
])
def test_malformed_values_are_on_with_a_logged_reason(monkeypatch, caplog, value):
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", value)
    assert gw.issue_117_blocked("db") is True and gw.issue_117_blocked("c") is True
    assert "archive-cascade block stays ON" in caplog.text


def test_a_time_more_than_a_few_minutes_ahead_is_on_but_a_small_skew_passes(monkeypatch, caplog):
    override_for(monkeypatch, "db", minutes_ago=-30)
    assert gw.issue_117_blocked("db") is True and "in the future" in caplog.text
    override_for(monkeypatch, "db", minutes_ago=-2)
    assert gw.issue_117_blocked("db") is False


def test_the_state_line_names_the_slug_and_the_expiry_or_says_on(monkeypatch):
    assert gw.issue_117_state_line() == "archive-cascade block: ON"
    monkeypatch.setattr(gw, "_now_utc", lambda: datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc))
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", "dwolfson/2026-10-21T14:05:00Z/throwaway_db")
    assert gw.issue_117_state_line() == "archive-cascade block: OFF for throwaway_db until 2026-10-21T15:05:00Z"
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", "dwolfson/2026-10-21T12:05:00Z/throwaway_db")      # expired
    assert gw.issue_117_state_line() == "archive-cascade block: ON"
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", "bare-clearance")
    assert gw.issue_117_state_line() == "archive-cascade block: ON"


def test_an_offset_time_is_read_as_that_instant(monkeypatch):
    monkeypatch.setattr(gw, "_now_utc", lambda: datetime(2026, 10, 21, 14, 30, tzinfo=timezone.utc))
    monkeypatch.setenv("RE_ISSUE_117_BLOCK_OFF", "who/2026-10-21T10:05:00-04:00/db")           # = 14:05Z
    assert gw.issue_117_blocked("db") is False


def test_the_session_start_logs_the_state(caplog):
    import logging
    from resource_explorer.web import app as web_app
    src = Path(web_app.__file__).read_text(encoding="utf-8")
    assert "issue_117_state_line()" in src, "the lifespan logs the state at start"


# ── the proof row: "0 archived" comes from a row, not from the absence of one ──────────────────────────────

def _blocked_commit(world, fake):
    _catalogued(world, fake, "sales")
    choose(world, "sales", "leave_out")
    choose(world, "archive", "catalogue")
    return press(world, fake)


def test_a_refused_leave_out_is_a_proof_row_and_the_header_and_row_derive_from_it(world, fake):
    out, rec = _blocked_commit(world, fake)
    rows = [p for p in world["registry"].list_catalogue_commit_proofs("db") if p["proof"] == cc.P_LEAVE_OUT_BLOCKED]
    assert len(rows) == 1 and rows[0]["schema_name"] == "sales"
    assert rows[0]["detail"]["note"] == "kept, not sent · archive-cascade block"
    d = derived(world)
    assert "1 left out, kept, not sent · archive-cascade block · 0 archived or deleted in Egeria" in d["header"]["text"]
    assert d["schemas"]["sales"]["blocked_117"] is True and d["schemas"]["sales"]["second"].startswith("kept, not sent · archive-cascade block")
    assert "sales" in step(rec, "leave_outs")["detail"] and "kept, not sent" in step(rec, "leave_outs")["detail"]
    # delete the row: the claim goes with it (a word on screen derives from a proof row)
    conn = world["registry"]._conn
    with conn() as c:
        c.execute("DELETE FROM catalogue_commit_proofs WHERE proof = ?", (cc.P_LEAVE_OUT_BLOCKED,))
    d2 = derived(world)
    assert "ISSUE-117" not in d2["header"]["text"] and "blocked_117" not in d2["schemas"]["sales"]


def test_the_outbox_refusal_also_writes_the_row(world, fake):
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    with pytest.raises(GatewayError):
        cc.apply_leave_out(world["registry"], fake, {"slug": "db", "schema": "sales", "form": gw.ARCHIVE, "curation_id": "c1", "by": ME})
    assert [p["detail"]["note"] for p in world["registry"].list_catalogue_commit_proofs("db") if p["proof"] == cc.P_LEAVE_OUT_BLOCKED] == ["kept, not sent · archive-cascade block"]


# ── the guard can fail: with the variable set the same scenarios reach the delete path ───────────────────────────

def test_known_negative_with_an_override_for_the_slug_the_commit_reaches_the_delete_path(world, fake, monkeypatch):
    override_for(monkeypatch, "db")
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    press(world, fake)
    assert fake.ops("delete_element"), "if this does not fail the other tests prove nothing"


def test_known_negative_with_an_override_for_the_slug_the_real_gateway_reaches_its_client(monkeypatch):
    override_for(monkeypatch, "db")
    g = gw.PyegeriaCatalogueGateway(entity_stub())
    md = MagicMock()
    g._clients.update({"MetadataExpert": md})
    g.delete_element("guid", gw.ARCHIVE, slug="db")
    assert md.delete_metadata_element.called


def test_the_real_gateway_refuses_another_slug_and_an_expired_override_and_sends_nothing(monkeypatch):
    md = MagicMock()
    for slug, minutes_ago in (("other_db", 0), ("db", 61)):
        override_for(monkeypatch, "db", minutes_ago=minutes_ago)
        g = gw.PyegeriaCatalogueGateway(entity_stub())
        g._clients.update({"MetadataExpert": md})
        with pytest.raises(GatewayError) as err:
            g.delete_element("guid", gw.ARCHIVE, slug=slug)
        assert str(err.value) == WORDS
    assert md.method_calls == []


def test_a_leave_out_on_another_slug_is_refused_while_the_override_names_a_different_database(world, fake, monkeypatch):
    override_for(monkeypatch, "some_other_throwaway")
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    choose(world, "archive", "catalogue")
    before = len(sent_to_egeria(fake))
    out, _ = press(world, fake)
    row = next(r for r in out["preview"]["leave_out"] if r["schema"] == "sales")
    assert row["form"] == "issue_117" and len(sent_to_egeria(fake)) == before
    with pytest.raises(GatewayError):
        cc.apply_leave_out(world["registry"], fake, {"slug": "db", "schema": "sales", "form": gw.ARCHIVE, "curation_id": "c1", "by": ME})
    assert len(sent_to_egeria(fake)) == before


def test_a_leave_out_for_the_named_slug_after_expiry_is_refused(world, fake, monkeypatch):
    override_for(monkeypatch, "db", minutes_ago=61)
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    before = len(sent_to_egeria(fake))
    with pytest.raises(GatewayError):
        cc.apply_leave_out(world["registry"], fake, {"slug": "db", "schema": "sales", "form": gw.ARCHIVE, "curation_id": "c1", "by": ME})
    assert len(sent_to_egeria(fake)) == before



# ── P_RESTORED: a restore script appends the row by kind name; the word derives from it ───────────────────────

def test_the_restored_proof_kind_name_is_a_stable_string():
    assert cc.P_RESTORED == "restored" and cc.P_RESTORED in cc.STATE_PROOFS


def _append_restored(world, schema="sales"):
    return world["registry"].append_catalogue_commit_proof(
        "db", proof="restored", node_kind="schema", schema_name=schema,
        element_guid="aaaaaaaa-0000-0000-0000-000000000001",
        detail={"from_guid": "bbbbbbbb-0000-0000-0000-000000000002", "note": "restored by the Egeria lead"},
        recorded_by="restore-script", read_at="2026-10-06T16:40:00")


def test_the_restored_word_derives_from_the_proof_row_and_goes_when_the_row_does(world, fake):
    choose(world, "sales", "catalogue")
    _append_restored(world)
    d = derived(world)
    st = d["schemas"]["sales"]
    assert st["state"] == "restored"
    assert st["words"] == "restored · aaaaaaaa · from bbbbbbbb · 10-06 16:40"
    assert st["second"] == "restored by the Egeria lead"
    assert "1 restored" in d["header"]["text"]
    # the row text on the page is that state's words (egeriaStateHtml prints st.words): same string
    with world["registry"]._conn() as c:
        c.execute("DELETE FROM catalogue_commit_proofs WHERE proof = ?", ("restored",))
    d2 = derived(world)
    assert d2["schemas"]["sales"]["state"] != "restored" and "restored" not in d2["schemas"]["sales"]["words"]
    assert "restored" not in d2["header"]["text"]


def test_a_restored_schema_that_is_left_out_is_still_blocked_from_any_archive(world, fake):
    choose(world, "sales", "leave_out")
    choose(world, "archive", "catalogue")
    _append_restored(world)
    out, _ = press(world, fake)
    row = next(r for r in out["preview"]["leave_out"] if r["schema"] == "sales")
    assert row["form"] == "issue_117" and not sent_to_egeria(fake)
