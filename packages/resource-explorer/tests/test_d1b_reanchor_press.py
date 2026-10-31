"""D1-b: the database-level press adds DataSetContent from RE's database element to the pack's schemas.

DESIGN-ADOPT-BY-ENDPOINT-D1-2026-10-30.md §10, §12; docs/design-notes/D1B-DATABASE-LINK-PRESS-UNDO.md. Over the D1-a
fake gateway (the live shape: the schema at end 1, the database at end 2), plus a fake `link_data_set_content` that
can refuse a schema or drop a link. Temp SQLite; no Egeria.
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from test_catalogue_commit import (  # noqa: F401  (fixtures and helpers re-used by name)
    _curation_access_reads,
    _zones,
    as_user,
    client,
    registry,
    world,
)
from test_d1a_endpoint_resolver import PACK, RE_SERVER, FakeGateway, _coco, _coco_entity

from resource_explorer import catalogue_commit as cc
from resource_explorer import endpoint_identity as ei
from resource_explorer import reanchor_press as rp
from resource_explorer.catalogue_gateway import GatewayError
from resource_explorer.registry import ProjectRegistry

ME = "peterprofile"


class PressGateway(FakeGateway):
    """The resolver's reads, and the one write: a link appears on the next read unless the schema is refused
    (Egeria's words) or `silent` (accepted but never seen on the read-back)."""

    def __init__(self):
        super().__init__()
        self.refuse: dict[str, str] = {}
        self.silent: set[str] = set()
        self.linked: list[tuple[str, str]] = []

    def link_data_set_content(self, data_set_guid, content_guid):
        self.calls.append(("link_data_set_content", data_set_guid, content_guid))
        if data_set_guid in self.refuse:
            raise GatewayError(self.refuse[data_set_guid])
        self.linked.append((data_set_guid, content_guid))
        if data_set_guid not in self.silent:
            self.member(content_guid, data_set_guid, guid=f"new-{len(self.linked)}")

    def writes(self):
        return [c for c in self.calls if c[0] == "link_data_set_content"]


@pytest.fixture
def reg(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.register_database(_coco_entity())
    r.register_database(_coco_entity(slug="throwaway", db="throwaway"))
    return r


@pytest.fixture
def coco():
    gw = PressGateway()
    _coco(gw)                     # RE's db with 4 schemas; the pack's aus_inventory, coco_ods, cocopages
    return gw


def _press(reg, gw, slug="localhost_docker_coco_pharma"):
    return rp.press(reg, gw, reg.get_database(slug), by=ME)


def _press_rows(reg, slug="localhost_docker_coco_pharma"):
    return [p for p in reg.list_catalogue_commit_proofs(slug) if p["proof"] == rp.PROOF_KIND]


def _view(names):
    return {"schemas": [{"name": n, "effective": None, "tables": []} for n in names]}


def test_the_happy_path_adds_each_pack_schema_once_with_the_schema_at_the_end_read(reg, coco):
    out = _press(reg, coco)
    assert out["state"] == rp.ADDED
    assert coco.writes() == [("link_data_set_content", f"pack-{s}", "re-db")
                             for s in ("aus_inventory", "coco_ods", "cocopages")]      # schema = data set, end 1
    assert [a["relationship_guid"] for a in out["added"]] == ["new-1", "new-2", "new-3"]
    assert (out["members_before"], out["members_after"]) == (4, 7)
    assert out["words"] == "added 3 of 3 schemas to re-db (DataSetContent) · read back: 7 members"
    rows = _press_rows(reg)
    assert len(rows) == 1 and rows[0]["element_guid"] == "re-db" and rows[0]["recorded_by"] == ME
    d = rows[0]["detail"]
    assert [(a["guid"], a["relationship_guid"]) for a in d["added"]] == [
        ("pack-aus_inventory", "new-1"), ("pack-coco_ods", "new-2"), ("pack-cocopages", "new-3")]
    assert rp.UNDO_CALL in d["undo"] and d["failed"] == [] and d["unverified"] == []
    # The page reads the result back: the plan's database row now has nothing to add and 7 members.
    derived = cc.derive_commit_state(reg, "localhost_docker_coco_pharma", _view(["aus_inventory"]))
    db = derived["endpoint"]["plan"]["database_row"]
    assert (db["members_now"], db["to_add"]) == (7, [])
    assert derived["endpoint"]["press"]["added"] == 3 and derived["endpoint"]["press"]["words"] == out["words"]


def test_a_second_press_adds_nothing_and_writes_nothing(reg, coco):
    _press(reg, coco)
    n = len(coco.writes())
    again = _press(reg, coco)
    assert again["state"] == rp.NOTHING_TO_ADD and len(coco.writes()) == n
    assert again["words"].startswith("nothing to add") and "7 members" in again["words"]
    assert len(_press_rows(reg)) == 1                          # a press that wrote nothing leaves no press row


def test_a_link_made_since_the_plan_was_read_is_skipped(reg, coco, monkeypatch):
    """The plan the person saw is not trusted: the links are read again just before writing."""
    real = rp._links_to

    def race(gateway, database_guid, link_type, schema_end):
        if not coco.writes() and "dsc-pack-cocopages" not in str(coco.rels.get("re-db")):
            coco.member("re-db", "pack-cocopages")              # someone else linked it after the plan was read
        return real(gateway, database_guid, link_type, schema_end)

    monkeypatch.setattr(rp, "_links_to", race)
    out = _press(reg, coco)
    assert [w[1] for w in coco.writes()] == ["pack-aus_inventory", "pack-coco_ods"]
    assert [x["guid"] for x in out["skipped_present"]] == ["pack-cocopages"]


def test_partial_failure_names_the_schemas_that_failed_and_never_says_failed_for_all(reg, coco):
    coco.refuse["pack-coco_ods"] = "user peterprofile is not authorized to update pack-coco_ods"
    out = _press(reg, coco)
    assert out["state"] == rp.PARTLY
    assert [a["guid"] for a in out["added"]] == ["pack-aus_inventory", "pack-cocopages"]
    assert out["failed"][0]["schema"] == "coco_ods" and "not authorized" in out["failed"][0]["error"]
    assert out["words"].startswith("added 2 of 3 schemas")
    assert "1 not added: coco_ods (user peterprofile is not authorized" in out["words"]
    assert not out["words"].startswith("nothing added")
    assert out["members_after"] == 6
    # The press row lists exactly what was added, so the undo removes exactly that.
    assert [a["relationship_guid"] for a in _press_rows(reg)[0]["detail"]["added"]] == ["new-1", "new-2"]


def test_every_schema_refused_is_nothing_added_with_each_reason(reg, coco):
    for s in ("aus_inventory", "coco_ods", "cocopages"):
        coco.refuse[f"pack-{s}"] = "refused"
    out = _press(reg, coco)
    assert out["state"] == rp.NOTHING_ADDED and out["added"] == []
    assert out["words"].startswith("nothing added · 3 not added: aus_inventory (refused)")


def test_a_link_sent_but_not_read_back_is_never_called_added(reg, coco):
    coco.silent.add("pack-cocopages")
    out = _press(reg, coco)
    assert out["state"] == rp.PARTLY and [u["schema"] for u in out["unverified"]] == ["cocopages"]
    assert "1 sent but not seen on the read-back: cocopages" in out["words"]


def test_an_empty_plan_writes_nothing(reg):
    gw = PressGateway()
    gw.database("t-db", RE_SERVER, db="throwaway")
    gw.schema("t-s", RE_SERVER, "sales", db="throwaway")
    gw.member("t-db", "t-s")
    with pytest.raises(rp.PressRefused) as exc:
        _press(reg, gw, "throwaway")
    assert "no database-level row" in exc.value.message and gw.writes() == []
    assert _press_rows(reg, "throwaway") == []


def test_ends_or_type_not_read_writes_nothing(reg):
    gw = PressGateway()
    _coco(gw)
    for rels in gw.rels.values():                     # Egeria did not say which end: no end is proposed
        for r in rels:
            r.other_at_end1 = None
    with pytest.raises(rp.PressRefused) as exc:
        _press(reg, gw)
    assert "nothing proposed" in exc.value.message and gw.writes() == []


def test_a_failed_endpoint_read_writes_nothing(reg, coco):
    coco.fail = "Egeria answered 503"
    with pytest.raises(rp.PressRefused) as exc:
        _press(reg, coco)
    assert exc.value.status == 503 and coco.writes() == []


def test_one_press_per_database_at_a_time(reg, coco, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    real = rp._press

    def slow(*a, **k):
        entered.set()
        release.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(rp, "_press", slow)
    t = threading.Thread(target=_press, args=(reg, coco))
    t.start()
    assert entered.wait(5)
    with pytest.raises(rp.PressBusy):
        _press(reg, coco)
    release.set()
    t.join(5)
    assert len(coco.writes()) == 3                    # the first press ran once; the second wrote nothing


def test_the_proof_kind_is_the_one_contents_reads():
    assert cc.P_REANCHOR == rp.PROOF_KIND


# ── the route ────────────────────────────────────────────────────────────────

@pytest.fixture
def fake():
    """The commit tests' `client` builds its gateway from this: the shop database at host.docker.internal:5442,
    RE's family with one schema and the pack with two."""
    gw = PressGateway()
    server = "host.docker.internal:5442"
    gw.database("shop-db", server, db="shop")
    gw.schema("shop-sales", server, "sales", db="shop")
    gw.member("shop-db", "shop-sales")
    for s in ("hr", "ops"):
        gw.schema(f"pack-{s}", PACK, s, host="localhost", db="shop")
    return gw


def test_the_route_refuses_a_signed_out_press_and_writes_nothing(client, fake):
    r = client.post("/api/catalogue-scope/db/reanchor")
    assert r.status_code == 401 and fake.writes() == []


def test_the_route_presses_for_a_signed_in_person_and_the_scope_reads_the_result(client, fake, registry):
    r = client.post("/api/catalogue-scope/db/reanchor", headers=as_user(ME))
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["state"] == rp.ADDED and len(j["added"]) == 2 and j["members_after"] == 3
    assert [w[1:] for w in fake.writes()] == [("pack-hr", "shop-db"), ("pack-ops", "shop-db")]
    plan = client.get("/api/catalogue-scope/db").json()["commit"]["endpoint"]["plan"]
    assert (plan["database_row"]["members_now"], plan["database_row"]["to_add"]) == (3, [])
    again = client.post("/api/catalogue-scope/db/reanchor", headers=as_user(ME)).json()
    assert again["state"] == rp.NOTHING_TO_ADD and len(fake.writes()) == 2


def test_the_route_says_why_when_there_is_nothing_to_press(client, fake):
    fake.endpoints = [e for e in fake.endpoints if "pack-" not in e.guid]      # a unique endpoint
    r = client.post("/api/catalogue-scope/db/reanchor", headers=as_user(ME))
    assert r.status_code == 409 and "no database-level row" in r.json()["detail"] and fake.writes() == []


def test_the_undo_note_names_the_one_relationship_call():
    note = (Path(rp.__file__).parent.parent / "docs/design-notes/D1B-DATABASE-LINK-PRESS-UNDO.md").read_text()
    assert "detach_data_set_content_relationship" in note and rp.UNDO_CALL.split(".")[1] in rp.UNDO_NOTE
    assert ei.SCHEMA_TYPE == "DeployedDatabaseSchema"
