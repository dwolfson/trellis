"""Catalogue scope for a database, slice A (storage, routes, proposals, states).

the designer reply on catalogue scope (page 18 of the CatalogueScope wireframe). Never touches the shared
registry: every test uses a tmp SQLite file, asserted below. Nothing here
reaches Egeria, and a test asserts the module cannot.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from resource_explorer import catalogue_scope as cs
from resource_explorer.auth import create_access_token
from resource_explorer.registry import DatabaseEntity, ProjectRegistry

SURVEY_AT = "2026-10-02T09:00:00"


def tbl(name, rows=10, table_type="BASE TABLE"):
    return {"name": name, "table_type": table_type, "row_count": rows, "row_count_state": "measured",
            "size_bytes": 100, "column_count": 1,
            "columns": [{"name": "id", "type": "integer", "nullable": False, "key_role": "PK",
                         "foreign_key": None, "comment": ""}]}


def sch(name, tables=(), cls=None, table_count=None):
    tables = list(tables)
    if cls is None:
        cls = "data" if tables else "no_tables"
    return {"schema": name, "table_count": len(tables) if table_count is None else table_count,
            "row_total": sum(t["row_count"] or 0 for t in tables) if tables else None,
            "bytes_total": None, "is_estimate": False, "classification": cls, "reason": "",
            "tables": tables}


SYSTEM = {"schema": None, "table_count": None, "row_total": None, "bytes_total": None,
          "is_estimate": False, "reason": "", "classification": "system", "system_count": 3}


@pytest.fixture
def registry(tmp_path):
    db = str(tmp_path / "scope.db")
    r = ProjectRegistry(db_path=db)
    # the tests must never be able to open the shared registry
    assert r.database_url == f"sqlite:///{db}" and str(tmp_path) in r.database_url
    r.register_database(DatabaseEntity(
        slug="db", display_name="db", db_type="postgresql", host="localhost", port=5442,
        database_name="db", egeria_asset_guid="abcdef12-0000-0000-0000-000000000000"))
    return r


@pytest.fixture
def world(registry, monkeypatch):
    """A mutable tree and fixed measurement dates, injected under the module."""
    w = {"tree": {"schemas": [sch("sales", [tbl("orders"), tbl("customers")]),
                              sch("archive", [tbl("orders"), tbl("old_stuff")]),
                              sch("empty_one"), SYSTEM]}}
    monkeypatch.setattr(cs, "_load_tree", lambda reg, slug: w["tree"])
    monkeypatch.setattr(cs, "_tree_survey_at", lambda reg, slug: SURVEY_AT)
    monkeypatch.setattr(cs, "_change_rates", lambda reg, slug: w.get("rates", {}))
    w["registry"] = registry
    return w


def view(w, **kw):
    return cs.build_scope_view(w["registry"], "db", **kw)


def node(v, schema, table=None):
    s = next(x for x in v["schemas"] if x["name"] == schema)
    return s if table is None else next(t for t in s["tables"] if t["name"] == table)


def rates(idle=(), active=()):
    per = [{"schema_name": s, "table_name": t, "change": "idle"} for s, t in idle]
    per += [{"schema_name": s, "table_name": t, "change": "active"} for s, t in active]
    return {"per_table": per, "from_surveyed_at": "2026-09-27T00:00:00", "to_surveyed_at": SURVEY_AT}


# ── storage: tables, migrations ──────────────────────────────────────────────

def test_the_registry_under_test_is_a_temp_sqlite_file(registry, tmp_path):
    assert registry.database_url.startswith("sqlite:///") and str(tmp_path) in registry.database_url
    assert "5442" not in registry.database_url and "5432" not in registry.database_url


def test_migration_is_idempotent_and_additive(tmp_path):
    db = str(tmp_path / "m.db")
    ProjectRegistry(db_path=db)
    r = ProjectRegistry(db_path=db)   # second init over the same file
    r2 = ProjectRegistry(db_path=db)
    for table, cols in (("catalogue_scope_events", {"database_slug", "node_kind", "schema_name",
                         "table_name", "choice", "action", "source", "proposal_rule",
                         "proposal_choice", "reason", "measured_at", "measured_json",
                         "author", "changed_at"}),
                        ("catalogue_scope_baselines", {"database_slug", "kind", "baseline_json",
                         "survey_at", "declared_by", "declared_at"})):
        with r2._conn() as conn:
            assert cols <= set(r2._get_table_columns(conn, table))
    assert r.list_catalogue_scope_events("db") == []


def test_events_are_append_only_and_need_an_author(registry):
    registry.append_catalogue_scope_event("db", node_kind="schema", schema_name="s",
                                          choice="catalogue", author="a")
    registry.append_catalogue_scope_event("db", node_kind="schema", schema_name="s",
                                          choice="leave_out", author="b")
    ev = registry.list_catalogue_scope_events("db")
    assert [(e["choice"], e["author"]) for e in ev] == [("catalogue", "a"), ("leave_out", "b")]
    with pytest.raises(ValueError):
        registry.append_catalogue_scope_event("db", node_kind="schema", schema_name="s",
                                              choice="catalogue", author="")


def test_this_module_cannot_reach_egeria():
    src = inspect.getsource(cs)
    for needle in ("pyegeria", "egeria_outbox", "requests", "httpx", "publish("):
        assert needle not in src


# ── proposals: one test per rule, with negatives ─────────────────────────────

def test_rule_empty_schema_proposes_leave_out_with_measurement_date(world):
    v = view(world)
    p = node(v, "empty_one")["proposal"]
    assert (p["rule"], p["choice"]) == ("empty_schema", "leave_out")
    assert p["reason"] == "0 tables, measured 10-02"
    assert node(v, "empty_one")["state"] == "proposed"
    assert node(v, "empty_one")["effective"] is None   # unconfirmed: still undecided


def test_rule_empty_schema_no_access_proposes_nothing(world):
    world["tree"]["schemas"].insert(0, sch("locked", cls="no_access", table_count=0))
    n = node(view(world), "locked")
    assert n["proposal"] is None and n["state"] == "undecided"
    assert n["access"] == "not_established"


def test_rule_no_writes_proposes_leave_out_with_evidence(world):
    world["rates"] = rates(idle=[("archive", "orders"), ("archive", "old_stuff")])
    n = node(view(world), "archive")
    assert n["proposal"]["rule"] == "no_writes" and n["proposal"]["choice"] == "leave_out"
    assert "no writes since 09-27" in n["proposal"]["reason"]
    assert "10-02" in n["proposal"]["reason"]
    t = node(view(world), "archive", "orders")
    assert t["proposal"]["rule"] == "no_writes"


def test_rule_no_writes_negatives_active_or_unmeasured(world):
    world["rates"] = rates(idle=[("archive", "orders")], active=[("archive", "old_stuff")])
    v = view(world)
    assert node(v, "archive")["proposal"] is None            # one active table: not idle
    assert node(v, "archive", "old_stuff")["proposal"] is None
    world["rates"] = {}                                       # one snapshot: no change rate at all
    assert node(view(world), "archive")["proposal"] is None


def test_rule_lens_match_proposes_catalogue_only_with_a_lens(world):
    assert node(view(world), "sales", "orders")["proposal"] is None       # no lens: nothing
    v = view(world, lens={"subjectTerms": ["orders"]})
    p = node(v, "sales", "orders")["proposal"]
    assert (p["rule"], p["choice"]) == ("data_lens_match", "catalogue")
    assert "orders" in p["reason"]
    assert node(v, "sales", "customers")["proposal"] is None              # no match: nothing


def test_the_database_has_no_lens_on_this_build():
    assert cs.data_lens_for(None, "db") is None


def test_pii_is_a_mark_never_a_proposal(world):
    v = view(world, data_classes={("sales", "customers"): {"classes": ["Email"], "pii_columns": 3}})
    t = node(v, "sales", "customers")
    assert t["proposal"] is None and t["state"] == "undecided"
    assert "PII · 3 columns" in t["marks"]
    assert "PII · 3 columns" in node(v, "sales")["marks"]


def test_staging_name_is_a_note_never_a_proposal(world):
    world["tree"]["schemas"].insert(0, sch("stg_load", [tbl("t1")], cls="staging"))
    n = node(view(world), "stg_load")
    assert n["proposal"] is None and "name suggests staging" in n["notes"]


def test_verdict_never_proposes():
    facts = {"kind": "schema", "name": "s", "classification": "data", "table_count": 5,
             "idle": None, "verdict": "recommended", "disposition": "using"}
    assert cs.propose_for_node(facts) is None
    assert set(cs.PROPOSAL_RULES) == {"empty_schema", "no_writes", "data_lens_match"}


def test_two_rules_that_disagree_propose_nothing(world):
    world["rates"] = rates(idle=[("sales", "orders")])
    v = view(world, lens={"subjectTerms": ["orders"]})
    t = node(v, "sales", "orders")
    assert t["proposal"] is None and any("disagree" in n for n in t["notes"])


def test_system_schemas_are_folded_never_offered(world):
    v = view(world)
    assert all(s["name"] for s in v["schemas"]) and "pg_catalog" not in str(v["schemas"])
    assert v["system"]["text"] == "not catalogued: system schemas are never offered"
    with pytest.raises(cs.ScopeError) as e:
        cs.set_node_choice(world["registry"], "db", "alice", schema="pg_catalog", choice="catalogue")
    assert e.value.status == 404


# ── the four observation states ──────────────────────────────────────────────

def test_confirm_override_and_the_struck_reason(world):
    r = world["registry"]
    cs.confirm_proposal(r, "db", "alice", schema="empty_one", now="2026-10-04T10:00:00")
    n = node(view(world), "empty_one")
    assert n["state"] == "confirmed" and n["effective"] == "leave_out"
    assert n["explicit"]["by"] == "alice" and n["explicit"]["source"] == "empty_schema"
    assert n["explicit"]["at"].startswith("2026-10-04")
    # a second proposal, overridden
    world["tree"]["schemas"].append(sch("tiny"))
    cs.override_proposal(r, "db", "bob", schema="tiny")
    o = node(view(world), "tiny")
    assert o["state"] == "overridden" and o["effective"] == "catalogue"
    assert o["overridden"]["reason"] == "0 tables, measured 10-02"
    assert o["overridden"]["choice"] == "leave_out"
    assert o["explicit"]["source"] == "person" and o["explicit"]["proposal_rule"] == "empty_schema"


def test_survey_now_disagrees_does_not_change_the_choice(world):
    r = world["registry"]
    cs.confirm_proposal(r, "db", "alice", schema="empty_one")
    world["tree"]["schemas"][2] = sch("empty_one", [tbl("a"), tbl("b"), tbl("c"), tbl("d")])
    n = node(view(world), "empty_one")
    assert n["state"] == "disagrees"
    assert n["effective"] == "leave_out"                        # the choice did not move
    assert n["disagrees"]["was"] == {"table_count": 0} and n["disagrees"]["now"] == {"table_count": 4}
    assert n["disagrees"]["survey_at"] == SURVEY_AT
    assert "it had 0 tables; it now has 4" in n["disagrees"]["words"]


def test_a_person_choice_with_no_proposal_is_chosen_not_an_observation_state(world):
    cs.set_node_choice(world["registry"], "db", "alice", schema="sales", choice="catalogue")
    assert node(view(world), "sales")["state"] == "chosen"


def test_clear_keeps_who_cleared_it_and_returns_to_undecided(world):
    r = world["registry"]
    cs.set_node_choice(r, "db", "alice", schema="sales", choice="catalogue")
    cs.clear_node_choice(r, "db", "bob", schema="sales")
    n = node(view(world), "sales")
    assert n["explicit"] is None and n["effective"] is None and n["state"] == "undecided"
    last = r.list_catalogue_scope_events("db")[-1]
    assert (last["choice"], last["author"], last["action"]) == ("", "bob", "clear")
    with pytest.raises(cs.ScopeError) as e:
        cs.clear_node_choice(r, "db", "bob", schema="sales")
    assert e.value.status == 409


def test_confirm_with_nothing_proposed_is_refused(world):
    with pytest.raises(cs.ScopeError) as e:
        cs.confirm_proposal(world["registry"], "db", "alice", schema="sales")
    assert e.value.status == 409


# ── undecided and inheritance ────────────────────────────────────────────────

def test_table_inherits_schema_and_differs_when_set(world):
    r = world["registry"]
    cs.set_node_choice(r, "db", "alice", schema="sales", choice="catalogue")
    v = view(world)
    t = node(v, "sales", "customers")
    assert (t["effective"], t["effective_from"], t["inherited"]) == ("catalogue", "schema", "catalogue")
    assert t["differs_from_schema"] is False and t["explicit"] is None
    cs.set_node_choice(r, "db", "alice", schema="sales", table="customers", choice="leave_out")
    t = node(view(world), "sales", "customers")
    assert t["effective"] == "leave_out" and t["differs_from_schema"] is True
    assert node(view(world), "sales", "orders")["effective"] == "catalogue"   # sibling unchanged


def test_undecided_schema_keeps_what_is_in_egeria_and_an_unconfirmed_proposal_is_undecided(world):
    v = view(world)
    assert node(v, "sales")["undecided_words"] == "keeps what’s in Egeria now"
    e = node(v, "empty_one")
    assert e["proposal"] is not None and e["effective"] is None
    assert world["registry"].list_catalogue_scope_events("db") == []      # nothing was written


# ── baseline and "new since" ─────────────────────────────────────────────────

def _seven_then_twentynine(world):
    seven = [sch(f"s{i}", [tbl("t1"), tbl("t2")]) for i in range(7)]
    world["tree"] = {"schemas": seven + [SYSTEM]}
    cs.set_node_choice(world["registry"], "db", "dwolfson", schema="s0", choice="catalogue",
                       now="2026-10-04T08:00:00")
    for i in range(1, 7):
        cs.set_node_choice(world["registry"], "db", "dwolfson", schema=f"s{i}", choice="catalogue")
    world["tree"] = {"schemas": seven + [sch(f"new{i}", [tbl("a"), tbl("b"), tbl("c")])
                                         for i in range(22)] + [SYSTEM]}


def test_nothing_is_new_before_a_scope_is_declared(world):
    v = view(world)
    assert v["declared"]["declared"] is False
    assert v["new_since"]["declared"] is False and v["new_since"]["schemas"] == 0
    assert not any(s["new_since"] for s in v["schemas"])


def test_22_schemas_added_after_the_declaration_are_counted(world):
    _seven_then_twentynine(world)
    v = view(world)
    assert v["declared"]["by"] == "dwolfson" and v["declared"]["at"].startswith("2026-10-04")
    ns = cs.new_since_declared(world["registry"], "db")
    assert (ns["schemas"], ns["tables"]) == (22, 66)
    assert ns["text"] == "22 new schemas (66 tables) not in your scope"
    assert all(node(v, f"new{i}")["new_since"] for i in range(22))
    assert not node(v, "s0")["new_since"]
    assert v["counts"]["schemas_catalogue"] == 7 and v["counts"]["schemas_offered"] == 29


def test_a_decision_on_a_new_schema_takes_it_out_of_the_count_and_redeclare_resets(world):
    _seven_then_twentynine(world)
    cs.set_node_choice(world["registry"], "db", "dwolfson", schema="new0", choice="leave_out")
    assert cs.new_since_declared(world["registry"], "db")["schemas"] == 21
    cs.redeclare(world["registry"], "db", "dwolfson")
    assert cs.new_since_declared(world["registry"], "db")["schemas"] == 0
    base = world["registry"].list_catalogue_scope_baselines("db")
    assert [b["kind"] for b in base] == ["first", "redeclare"]       # history kept
    assert len(base[0]["baseline"]["schemas"]) == 7 and len(base[1]["baseline"]["schemas"]) == 29


def test_new_table_in_a_known_schema_is_reported_separately(world):
    cs.set_node_choice(world["registry"], "db", "alice", schema="sales", choice="catalogue")
    world["tree"]["schemas"][0]["tables"].append(tbl("fresh"))
    ns = cs.new_since_declared(world["registry"], "db")
    assert ns["schemas"] == 0 and ns["tables_in_known_schemas"] == 1
    assert node(view(world), "sales", "fresh")["new_since"] is True


# ── the name conflict ────────────────────────────────────────────────────────

def test_conflict_is_detected_marks_both_rows_and_resolves(world):
    r = world["registry"]
    cs.set_node_choice(r, "db", "alice", schema="sales", table="orders", choice="catalogue")
    cs.set_node_choice(r, "db", "alice", schema="archive", table="orders", choice="leave_out")
    v = view(world)
    c = cs.scope_conflicts(r, "db")
    assert c["count"] == 1 and c["names"] == ["orders"]
    assert c["pairs"] == [{"name": "orders", "catalogue_in": "sales", "leave_out_in": "archive"}]
    for sname in ("sales", "archive"):
        assert node(v, sname, "orders")["conflict"]["text"] == "orders is chosen differently in sales and archive"
    assert node(v, "sales", "customers")["conflict"] is None
    cs.resolve_conflict(r, "db", "alice", name="orders", choice="catalogue")
    assert cs.scope_conflicts(r, "db")["count"] == 0
    assert node(view(world), "archive", "orders")["effective"] == "catalogue"


def test_conflict_through_inheritance_and_undecided_is_not_a_conflict(world):
    r = world["registry"]
    cs.set_node_choice(r, "db", "alice", schema="sales", choice="catalogue")     # orders inherits catalogue
    assert cs.scope_conflicts(r, "db")["count"] == 0                             # archive.orders undecided
    cs.set_node_choice(r, "db", "alice", schema="archive", choice="leave_out")   # orders inherits leave_out
    assert cs.scope_conflicts(r, "db")["names"] == ["orders"]


def test_resolving_a_name_not_in_conflict_is_refused(world):
    with pytest.raises(cs.ScopeError) as e:
        cs.resolve_conflict(world["registry"], "db", "alice", name="orders", choice="catalogue")
    assert e.value.status == 409


# ── depth, header, element ───────────────────────────────────────────────────

def test_depth_is_stored_with_author_and_changes_what_the_tree_shows(world):
    r = world["registry"]
    v = view(world)
    assert v["depth"]["value"] == "schemas_and_tables" and v["depth"]["declared"] is False
    assert [d["id"] for d in v["depth"]["options"]] == list(cs.DEPTH_IDS)
    assert "columns" not in node(v, "sales", "orders")
    cs.set_depth(r, "db", "alice", depth="tables_and_columns")
    v = view(world)
    assert v["depth"]["value"] == "tables_and_columns" and v["depth"]["by"] == "alice"
    assert node(v, "sales", "orders")["columns"][0]["name"] == "id"
    assert "Views follow the table lists" in v["depth"]["help"]
    with pytest.raises(cs.ScopeError):
        cs.set_depth(r, "db", "alice", depth="everything")


def test_depth_provenance_names_the_excluded_level():
    assert cs.depth_provenance("schemas", "table") == "tables excluded via include list"
    assert cs.depth_provenance("schemas_and_tables", "table") == "columns excluded via include list"
    assert cs.depth_provenance("tables_and_columns", "table") == ""
    assert "no catalog target" in cs.depth_provenance("database_only", "schema")


def test_header_survey_numbers_come_from_the_native_survey_row(world):
    r = world["registry"]
    assert view(world)["survey"]["state"] == "not_measured"
    r.record_database_survey("db", 99, 99, 99, {"schema_info": {"x": 1}}, source="local")
    assert view(world)["survey"]["state"] == "not_measured"        # RE's own survey is not Egeria's
    r.record_database_survey("db", 29, 266, 1000, {}, source="egeria", egeria_report_guid="g1",
                             surveyed_at="2026-10-03T00:00:00")
    s = view(world)["survey"]
    assert (s["state"], s["schema_count"], s["table_count"]) == ("measured", 29, 266)


# ── routes ───────────────────────────────────────────────────────────────────

@pytest.fixture
def client(registry, world, monkeypatch):
    monkeypatch.setattr(
        "resource_explorer.registry.ProjectRegistry.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None,
    )
    from resource_explorer import auth
    from resource_explorer.web.app import app
    from resource_explorer.web.routes import catalogue_scope as routes
    monkeypatch.setattr(routes, "get_current_user", auth.get_current_user)
    return TestClient(app)


def as_user(u):
    return {"Authorization": "Bearer " + create_access_token(user_id=u, egeria_token="t")}


WRITES = [
    ("depth", "put", "/api/catalogue-scope/db/depth", {"depth": "schemas"}),
    ("node", "put", "/api/catalogue-scope/db/node", {"schema_name": "sales", "choice": "catalogue"}),
    ("confirm", "post", "/api/catalogue-scope/db/node/confirm", {"schema_name": "empty_one"}),
    ("override", "post", "/api/catalogue-scope/db/node/override", {"schema_name": "empty_one"}),
    ("clear", "post", "/api/catalogue-scope/db/node/clear", {"schema_name": "sales"}),
    ("redeclare", "post", "/api/catalogue-scope/db/redeclare", None),
    ("resolve", "post", "/api/catalogue-scope/db/resolve", {"name": "orders", "choice": "catalogue"}),
]


@pytest.mark.parametrize("name,method,url,body", WRITES, ids=[w[0] for w in WRITES])
def test_signed_out_write_is_401_and_writes_nothing(client, registry, name, method, url, body):
    r = getattr(client, method)(url, **({"json": body} if body is not None else {}))
    assert r.status_code == 401, r.text
    assert "Sign in to" in r.json()["detail"]
    assert registry.list_catalogue_scope_events("db") == []
    assert registry.list_catalogue_scope_baselines("db") == []


def test_read_is_open_signed_out_and_names_the_element(client):
    j = client.get("/api/catalogue-scope/db").json()
    assert j["egeria_element"]["short"] == "abcdef12"
    assert j["declared"]["declared"] is False
    assert client.get("/api/catalogue-scope/nope").status_code == 404


def test_set_confirm_override_clear_and_history_through_the_routes(client, registry):
    a, b = as_user("alice"), as_user("bob")
    r = client.put("/api/catalogue-scope/db/node", json={"schema_name": "sales", "choice": "catalogue",
                                                          "author": "mallory"}, headers=a)
    assert r.status_code == 200
    assert client.post("/api/catalogue-scope/db/node/confirm", json={"schema_name": "empty_one"},
                       headers=b).status_code == 200
    h = client.get("/api/catalogue-scope/db/history").json()
    assert [e["author"] for e in h["events"]] == ["alice", "bob"]        # body author ignored
    assert h["declarations"][0]["declared_by"] == "alice"
    j = client.get("/api/catalogue-scope/db").json()
    assert next(s for s in j["schemas"] if s["name"] == "empty_one")["state"] == "confirmed"
    assert client.post("/api/catalogue-scope/db/node/clear", json={"schema_name": "sales"},
                       headers=b).status_code == 200
    assert client.post("/api/catalogue-scope/db/node/confirm", json={"schema_name": "sales"},
                       headers=b).status_code == 409
    assert client.put("/api/catalogue-scope/db/node", json={"schema_name": "nope", "choice": "catalogue"},
                      headers=a).status_code == 404
    assert client.put("/api/catalogue-scope/db/node", json={"schema_name": "sales", "choice": "maybe"},
                      headers=a).status_code == 400
    assert len(registry.list_catalogue_scope_events("db")) == 3          # failures wrote nothing


def test_conflicts_and_new_since_routes(client):
    a = as_user("alice")
    client.put("/api/catalogue-scope/db/node", json={"schema_name": "sales", "table_name": "orders",
                                                      "choice": "catalogue"}, headers=a)
    client.put("/api/catalogue-scope/db/node", json={"schema_name": "archive", "table_name": "orders",
                                                      "choice": "leave_out"}, headers=a)
    assert client.get("/api/catalogue-scope/db/conflicts").json()["count"] == 1
    assert client.get("/api/catalogue-scope/db/new-since").json()["declared"] is True
