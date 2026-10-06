"""ISSUE-117 hard block: Egeria archives the WHOLE database tree when any part of it is archived (leaving
out us_sales archived the coco_pharma database element and both demo schemas, 2026-10-06). While
`catalogue_gateway.ISSUE_117_BLOCK` is on, NOTHING reaches Egeria for any archive or delete of a database's
tree (schema, table, column, schema type), soft delete included; the choice stays recorded in RE.

These tests run with the block ON (conftest turns it off for every other catalogue test, which exercise the
frozen delete path against the fake). `test_known_negative_*` proves the guard can fail: with the block off the
same scenario DOES reach the delete path."""
from __future__ import annotations

import sys
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

WORDS = ("Egeria archives the whole database tree when any part of it is archived "
         "(ISSUE-117, archiveBeanInRepository) · choice kept, nothing sent")


def sent_to_egeria(fake):
    """Every call that would change Egeria on the leave-out path."""
    return fake.ops("delete_element") + fake.ops("remove_catalog_target")


def test_the_block_is_on_as_shipped():
    assert gw.ISSUE_117_BLOCK is True and gw.ISSUE_117_WORDS == WORDS


# ── the real gateway: every kind of element, both forms ─────────────────────────────────────────────

@pytest.mark.parametrize("kind", ["schema", "table", "column", "schema type"])
@pytest.mark.parametrize("form", [gw.ARCHIVE, gw.SOFT_DELETE])
def test_the_real_gateway_sends_nothing_for_any_element_of_a_database_tree(kind, form):
    g = gw.PyegeriaCatalogueGateway(entity_stub())
    clients = {n: MagicMock(name=n) for n in ("AssetMaker", "MetadataExpert", "AutomatedCuration", "ServerOps")}
    g._clients.update(clients)
    with pytest.raises(GatewayError) as err:
        g.delete_element(f"guid-of-a-{kind}", form)
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

def test_known_negative_with_the_block_off_the_same_scenario_reaches_the_delete_path(world, fake, monkeypatch):
    monkeypatch.setattr(gw, "ISSUE_117_BLOCK", False)
    _attached(world, fake, "sales")
    choose(world, "sales", "leave_out")
    press(world, fake)
    assert fake.ops("delete_element"), "if this does not fail the other tests prove nothing"
