"""Rehearsal 2 (2026-10-05) defects D-A .. D-I and the survey-report wording. Every payload is built
from the live shapes recorded in that rehearsal (`live_catalogue_payloads.py`); the fake Egeria emits
them too and PARSES them with the real gateway's parsers."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent))
import live_catalogue_payloads as live  # noqa: E402
from test_catalogue_commit import (  # noqa: E402,F401
    ME, SOURCE, _zones, choose, derived, entity, fake, press, registry, step, view, world)

from resource_explorer import catalogue_commit as cc  # noqa: E402
from resource_explorer import catalogue_gateway as gw  # noqa: E402
from resource_explorer.registry import DatabaseEntity  # noqa: E402

SALES_QN = "PostgreSQL Relational Database Schema::host.docker.internal:5442::shop.sales"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(cc, "_sleep", lambda s: None)


@pytest.fixture
def real():
    ent = DatabaseEntity(slug="db", display_name="Shop", db_type="postgresql", host="localhost",
                         egeria_host="host.docker.internal", port=5442, database_name="shop")
    g = gw.PyegeriaCatalogueGateway(ent)
    c = {n: MagicMock(name=n) for n in ("AssetMaker", "MetadataExpert", "AutomatedCuration", "ServerOps")}
    g._clients.update(c)
    return g, c, ent


def _catalogue(world, fake, *names, refresh=True):
    for n in names:
        choose(world, n, "catalogue")
    return press(world, fake, refresh=refresh)


# ── D-A: the template's own relationships are structure, not something that hangs off ───────────

def test_every_relationship_the_rehearsal_saw_on_a_template_made_schema_is_structural():
    for t in live.TEMPLATE_OWN_RELATIONSHIPS:
        assert t in cc.STRUCTURAL_RELATIONSHIPS, t
    assert "DataFlow" not in cc.STRUCTURAL_RELATIONSHIPS               # lineage someone asserted hangs off
    assert "SemanticAssignment" not in cc.STRUCTURAL_RELATIONSHIPS       # a steward's term stays "hangs off it"


def test_a_schema_with_only_the_templates_own_relationships_plans_a_soft_delete(world, fake):
    _catalogue(world, fake, "sales")
    choose(world, "sales", "leave_out")
    row = cc.build_preview(world["registry"], "db", view(world), fake)["leave_out"][0]
    assert row["form"] == gw.SOFT_DELETE and row["hangs_off"]["total"] == 0
    assert "will be removed (soft-deleted)" in row["text"] and "archived" not in row["text"]
    _, rec = press(world, fake)
    assert fake.by_qn(SALES_QN) is None and step(rec, "leave_outs")["state"] == "done"
    assert derived(world)["schemas"]["sales"]["state"] == "removed"


def test_a_term_assignment_on_a_table_still_plans_an_archive(world, fake):
    _catalogue(world, fake, "sales")
    fake.add_term_assignment("orders", SALES_QN)
    choose(world, "sales", "leave_out")
    row = cc.build_preview(world["registry"], "db", view(world), fake)["leave_out"][0]
    assert row["form"] == gw.ARCHIVE and row["hangs_off"]["by_type"] == {"SemanticAssignment": 1}
    assert "1 term assignment hang off it" in row["text"]


# ── D-B: a non-empty target list parses, an unknown one raises, nothing is initiated twice ──────

def test_the_live_target_item_parses_to_names_and_guids(real):
    g, c, _ = real
    item = live.raw_catalog_target("1d4d9b95-0000", "a13fd170-0000", "scratch_cat_test5.plain",
                                   {"schemaName": "plain", "templateGUID": "82a5417c"})
    c["AssetMaker"].get_catalog_targets.return_value = [item]
    [t] = g.list_catalog_targets()
    assert (t.relationship_guid, t.element_guid, t.name) == ("1d4d9b95-0000", "a13fd170-0000", "scratch_cat_test5.plain")
    assert set(item) == live.CATALOG_TARGET_ITEM_KEYS


@pytest.mark.parametrize("bad", [[{"relationshipHeader": {"guid": "r"}, "catalogTargetElement": {"elementHeader": {"guid": "e"}}}],
                                 [{"elementHeader": {"guid": "e"}}], ["x"], {"unexpected": 1}, None])
def test_an_unknown_target_answer_raises_and_is_never_an_empty_list(real, bad):
    g, c, _ = real
    c["AssetMaker"].get_catalog_targets.return_value = bad
    with pytest.raises(gw.GatewayError):
        g.list_catalog_targets()


def test_no_elements_found_is_still_an_empty_target_list(real):
    g, c, _ = real
    c["AssetMaker"].get_catalog_targets.return_value = "No elements found"
    assert g.list_catalog_targets() == []


def test_a_second_press_with_the_target_present_performs_zero_initiations(world, fake):
    _catalogue(world, fake, "sales", refresh=False)
    for _ in range(3):
        press(world, fake, refresh=False)
    assert fake.initiations == {fake.by_qn(SALES_QN)["guid"]: 1} and len(fake.targets) == 1
    assert fake.ops("add_catalog_target") == []


def test_a_drain_retry_with_the_target_present_performs_zero_initiations(world, fake):
    from resource_explorer.egeria_outbox import OutboxClients, drain_outbox
    reg = world["registry"]
    _catalogue(world, fake, "sales", refresh=False)
    ob = reg.list_catalogue_outbox_rows("db")[-1]
    with reg._conn() as conn:                                   # the worker's retry finds the row due again
        conn.execute("UPDATE egeria_outbox SET status = 'pending', next_attempt_at = '' WHERE id = ?", (ob["id"],))
    drain_outbox(reg, OutboxClients(catalogue_gateway=fake, registry=reg), lambda qn: "")
    assert sum(fake.initiations.values()) == 1 and len(fake.targets) == 1


def test_a_retry_after_a_lagging_read_back_never_double_attaches(world, fake):
    fake.target_lag_reads = 7                       # the live attach is not readable for longer than one poll window
    choose(world, "sales", "catalogue")
    _, rec = press(world, fake, refresh=False)
    assert step(rec, "schema_targets")["state"] == "failed"      # not seen yet: an error to retry
    for _ in range(3):
        press(world, fake, refresh=False)                        # retries while the read-back still lags / has caught up
    assert sum(fake.initiations.values()) == 1 and len(fake.targets) == 1
    assert fake.ops("add_catalog_target") == []
    assert derived(world)["schemas"]["sales"]["state"] in ("attached_waiting", "catalogued")


def test_the_read_order_is_targets_first_then_initiate_then_poll(world, fake):
    choose(world, "sales", "catalogue")
    press(world, fake, refresh=False)
    names = [c[0] for c in fake.calls]
    i = names.index("initiate_catalog_action")
    assert "list_catalog_targets" in names[:i] and "list_catalog_targets" in names[i + 1:]


# ── D-C: a failure older than a read-back proof does not outrank it ────────────────────────────

def test_a_failed_outbox_row_does_not_outrank_a_newer_catalogued_proof(world, fake):
    reg = world["registry"]
    _catalogue(world, fake, "sales", "archive")
    assert derived(world)["schemas"]["sales"]["state"] == "catalogued"
    for ob in reg.list_catalogue_outbox_rows("db"):             # the rows are marked failed AFTER being queued,
        reg.mark_outbox_failed(ob["id"], "OutboxApplyError: stale failure")      # the read-back proof is newer than their creation
    d = derived(world)
    assert [d["schemas"][n]["state"] for n in ("sales", "archive")] == ["catalogued", "catalogued"]
    assert "failed" not in d["header"]["text"] and "2 cataloged" in d["header"]["text"]
    assert d["tables"]["sales.orders"]["state"] == "catalogued"


def test_a_failure_newer_than_the_proof_still_reads_failed(world, fake):
    reg = world["registry"]
    _catalogue(world, fake, "sales")
    oid = reg.enqueue_outbox_element("database", "db", cc.KIND_ATTACH, "x", {"slug": "db", "schema": "sales"}, run_id="r2")
    reg.mark_outbox_failed(oid, "OutboxApplyError: 500 again")
    s = derived(world)["schemas"]["sales"]
    assert s["state"] == "failed" and "500 again" in s["words"]


def test_header_counts_agree_with_the_rows_catalogued_next_to_failed_is_impossible(world, fake):
    reg = world["registry"]
    _catalogue(world, fake, "sales", "archive")
    for ob in reg.list_catalogue_outbox_rows("db"):
        reg.mark_outbox_failed(ob["id"], "boom")
    d = derived(world)
    states = [d["schemas"][n]["state"] for n in ("sales", "archive")]
    text = d["header"]["text"]
    for st, word in (("catalogued", "cataloged"), ("failed", "failed")):
        assert (f"{states.count(st)} {word}" in text) == (st in states)


# ── D-H: the template's own connection graph is not catalogued content ─────────────────────────

def test_a_schema_with_only_its_template_elements_reads_attached_waiting_not_catalogued(world, fake):
    _catalogue(world, fake, "sales", refresh=False)            # no cataloguer cycle: only the 4 template elements exist
    s = derived(world)["schemas"]["sales"]
    assert s["state"] == "attached_waiting"
    fake.run_cataloguer()
    cc.read_back(world["registry"], fake, "db", ["sales"])
    assert derived(world)["schemas"]["sales"]["state"] == "catalogued"


# ── D-D: no invalid parent, and a 500 on a create that happened is adopted ────────────────────

def test_the_template_create_uses_the_cataloguers_own_parent_link_and_names_its_stage_in_a_failure(real):
    g, c, ent = real
    ac = c["AutomatedCuration"]
    ac.create_elem_from_template.return_value = "new"
    g.create_schema_element(ent, "sales", "db-guid")
    body = ac.create_elem_from_template.call_args[0][0]
    # RelationalDatabaseCataloguer.java:255-259: anchor = parent = the database, DataSetContent, the database at
    # END 2. Rehearsal 2 sent the database at end 1 for a RelationalDatabase and Egeria rejected it (400-047).
    assert body["anchorGUID"] == "db-guid" and body["parentGUID"] == "db-guid" and body["isOwnAnchor"] is False
    assert body["parentRelationshipTypeName"] == "DataSetContent" and body["parentAtEnd1"] is False
    assert not (body["parentRelationshipTypeName"] == "DataSetContent" and body["parentAtEnd1"] is True)
    ac.create_elem_from_template.side_effect = Exception(
        "SERVER_ERROR_500 => Egeria detected error: `https://localhost:9443/x/new-element`.")
    with pytest.raises(gw.GatewayError) as err:
        g.create_schema_element(ent, "sales", "db-guid")
    first = cc.egeria_first_sentence(str(err.value))[0]
    assert "schema" in first and "template" in first and "SERVER_ERROR_500" in first


def test_a_500_on_a_create_that_happened_is_adopted_and_attached_not_reported_failed(world, fake):
    fake.create_error_after_creating = True
    choose(world, "sales", "catalogue")
    _, rec = press(world, fake, refresh=False)
    assert step(rec, "schema_targets")["state"] == "done" and len(fake.targets) == 1
    assert len(fake.ops("create_schema_element")) == 1


def test_a_create_that_really_failed_says_so_with_its_stage(world, fake):
    fake.fail["create_schema_element"] = "SERVER_ERROR_500 => Egeria detected error: `u`."
    choose(world, "sales", "catalogue")
    _, rec = press(world, fake, refresh=False)
    assert step(rec, "schema_targets")["state"] == "failed" and fake.targets == []


# ── D-F: a survey is "done" only when its action COMPLETED and annotations were read back ──────

def test_a_partial_annotation_count_while_the_action_runs_is_submitted_running_not_done(world, fake):
    choose(world, "sales", "catalogue")
    out, _ = press(world, fake)
    fake.survey_behaviour = "partial"
    cc.read_back(world["registry"], fake, "db", ["sales"])
    from resource_explorer.curate_plan import Curations
    s = step(Curations(world["registry"]).get(out["curation"]["id"]), "survey")
    assert s["state"] == "submitted" and "running" in s["detail"] and "IN_PROGRESS" in s["detail"]
    assert "9 annotations so far" in s["detail"]
    fake.survey_behaviour = "annotated"
    cc.read_back(world["registry"], fake, "db", ["sales"])
    assert step(Curations(world["registry"]).get(out["curation"]["id"]), "survey")["state"] == "done"


# ── running statuses and wording ──────────────────────────────────────────────────────────────

def _block_row(world, fake, status, kind=""):
    _catalogue(world, fake, "sales")
    choose(world, "sales", "leave_out")
    fake.add_engine_action(SALES_QN, status, kind=kind)
    return cc.build_preview(world["registry"], "db", view(world), fake)["leave_out"][0]


def test_activating_blocks_like_in_progress(world, fake):
    row = _block_row(world, fake, "ACTIVATING")
    assert row["blocked"] and row["text"].startswith("sales: in use by a running survey · wait or cancel") \
        and "ACTIVATING" in row["text"]


def test_an_action_target_with_no_status_at_all_blocks(world, fake):
    row = _block_row(world, fake, "")
    assert row["blocked"] and "wait or cancel" in row["text"] and "no status stated" in row["text"]


def test_the_block_names_the_kind_of_action_when_it_is_not_a_survey(world, fake):
    row = _block_row(world, fake, "IN_PROGRESS", kind="catalog-postgres-schema")
    assert row["blocked"] and "in use by catalog-postgres-schema · wait or cancel" in row["text"]
    assert "survey" not in row["text"]


def test_a_survey_request_type_keeps_the_survey_wording(world, fake):
    row = _block_row(world, fake, "IN_PROGRESS", kind="survey-postgres-database")
    assert "in use by a running survey · wait or cancel" in row["text"]


def test_the_gateway_reads_the_request_type_and_a_missing_status_from_the_live_item(real):
    g, c, ent = real
    schema = live.raw_element("sch1", SALES_QN, "DeployedDatabaseSchema")
    ea = live.raw_engine_action("e1", "", request_type="catalog-postgres-schema")
    c["MetadataExpert"].get_all_related_elements.return_value = live.raw_related(
        schema, [("ActionTarget", "rl", ea, live.relationship_properties("newAsset", ""))])
    [r] = g.relationships("sch1")
    assert r.activity_status == "" and r.action_kind == "catalog-postgres-schema"


def test_an_archive_step_says_archived_and_a_removal_says_removed(world, fake):
    _catalogue(world, fake, "sales", "archive")
    fake.add_term_assignment("orders", SALES_QN)
    choose(world, "sales", "leave_out")
    choose(world, "archive", "leave_out")
    _, rec = press(world, fake)
    d = step(rec, "leave_outs")["detail"]
    assert "1 archived" in d and "1 removed" in d and "2 of 2" in d


def test_a_failed_row_says_it_retries_when_the_worker_runs(world, fake):
    fake.fail["create_schema_element"] = "500 no"
    choose(world, "sales", "catalogue")
    press(world, fake, refresh=False)
    s = derived(world)["schemas"]["sales"]
    assert "waiting for a worker" in s["second"] and "will retry" not in s["second"]


def test_the_survey_report_step_never_prints_a_question_mark(world, fake):
    fake.report_guid_missing = True
    choose(world, "sales", "catalogue")
    world["registry"]  # a measured survey of RE's own is needed for the step to run
    _, rec = press(world, fake, refresh=False)
    assert "?" not in step(rec, "survey_report")["detail"]


# ── the survey report is published whole (owner decision 2026-10-06) ──────────────────────────

def test_the_manifest_says_the_survey_report_is_published_whole_and_what_was_chosen(world, fake):
    choose(world, "sales", "catalogue")
    choose(world, "archive", "catalogue")
    p = cc.build_preview(world["registry"], "db", view(world), fake)
    m = len([s for s in view(world)["schemas"]])
    lines = [ln["text"] for ln in p["manifest"]["lines"]]
    assert f"RE's survey report is published whole; it describes all {m} schemas; elements are created for the 2 you chose." in lines


# ── D-E: the server shown is the SERVER element ───────────────────────────────────────────────

def test_a_repeat_publish_does_not_mistake_the_stored_database_guid_for_the_server():
    from resource_explorer.surveyors.database.egeria_database_surveyor import EgeriaDatabaseSurveyor
    ent = DatabaseEntity(slug="db", display_name="Shop", db_type="postgresql", host="localhost",
                         egeria_host="host.docker.internal", port=5442, database_name="shop",
                         egeria_asset_guid="db-guid-0000")        # RE stores the DATABASE's guid here
    s = EgeriaDatabaseSurveyor(platform_url="http://x")
    s._automated_curation = MagicMock()
    s.connect = lambda: None
    s._find_element_guid = lambda name: "db-guid-0000" if name == "shop" else "server-guid-0000"
    s._save_database_secret = lambda *a, **k: ("", "")
    s._warn_if_database_has_no_connection = lambda *a, **k: None
    created = []
    s._create_postgres_element_from_template = lambda tech, ph: (created.append(tech) or "x")
    res = s._catalog_and_survey(ent, "u", "p", registry=None, survey_after_catalog=False)
    assert res["database_guid"] == "db-guid-0000" and res["server_guid"] == "server-guid-0000"
    assert created == []


# ── DataFlow by the OTHER END (architect, 2026-10-06) ─────────────────────────────────────────

from fake_egeria_catalogue import CONNECTOR_JOB_QN  # noqa: E402


def _schema_with_dataflow(world, fake, other_qn, other_type, other_name):
    _catalogue(world, fake, "sales")
    choose(world, "sales", "leave_out")
    g = fake.by_qn(SALES_QN)["guid"]
    fake.rels.setdefault(g, []).append(gw.Relationship(
        "DataFlow", other_guid="far", other_type=other_type, other_qualified_name=other_qn, other_name=other_name))
    return cc.build_preview(world["registry"], "db", view(world), fake)["leave_out"][0]


def test_a_schema_with_only_the_connectors_own_dataflow_plans_a_delete(world, fake):
    _catalogue(world, fake, "sales")
    choose(world, "sales", "leave_out")
    row = cc.build_preview(world["registry"], "db", view(world), fake)["leave_out"][0]
    assert row["form"] == gw.SOFT_DELETE and "delete · nothing depends on it" in row["text"]
    _, rec = press(world, fake)
    assert fake.by_qn(SALES_QN) is None                                   # the element went, DataFlow and all


@pytest.mark.parametrize("qn,typ,name", [
    ("Asset::warehouse::orders_mart", "DataFile", "orders_mart"),                                  # another asset
    ("DeployedSoftwareComponent::MyJobs::nightly-load", "DeployedSoftwareComponent", "nightly-load"),  # a person's process
    ("PostgreSQLDatabaseSchema::CreateAsCatalogTargetGovernanceActionProcess", "GovernanceActionProcess", "CreateAsCatalogTarget"),
    ("PostgreSQL Relational Database Schema::h:1::shop.other", "DeployedDatabaseSchema", "other"),   # another schema
])
def test_a_dataflow_to_anything_else_plans_an_archive_naming_what_would_be_lost(world, fake, qn, typ, name):
    row = _schema_with_dataflow(world, fake, qn, typ, name)
    assert row["form"] == gw.ARCHIVE
    assert f"archive · lineage to {name or qn or 'an element Resource Explorer could not name'} would be lost" in row["text"]


def test_a_dataflow_to_the_connectors_job_component_is_machinery_only_by_its_exact_prefix(world, fake):
    row = _schema_with_dataflow(world, fake, "DeployedSoftwareComponent::GovernanceActionsX::foo", "DeployedSoftwareComponent", "foo")
    assert row["form"] == gw.ARCHIVE
    row = _schema_with_dataflow(world, fake, CONNECTOR_JOB_QN.replace("PostgreSQLSurvey", "Other"), "DeployedSoftwareComponent", "x")
    assert row["form"] == gw.ARCHIVE                                    # the connector's component PLUS a lineage to elsewhere


def test_the_dataflow_other_end_is_read_from_the_live_item(real):
    g, c, ent = real
    schema = live.raw_element("sch1", SALES_QN, "DeployedDatabaseSchema")
    job = live.raw_element("job1", CONNECTOR_JOB_QN, "DeployedSoftwareComponent", props={"displayName": "survey-postgres-database"})
    c["MetadataExpert"].get_all_related_elements.return_value = live.raw_related(schema, [("DataFlow", "rl", job)])
    [r] = g.relationships("sch1")
    assert (r.other_qualified_name, r.other_name, r.other_type) == (CONNECTOR_JOB_QN, "survey-postgres-database", "DeployedSoftwareComponent")


# ── a 3-target list (built from the single live item, distinct guids: the test6 run will give a live one) ──

def _three():
    return [live.raw_catalog_target(f"rel-{i}", f"el-{i}", f"scratch_cat_test5.{n}", {"schemaName": n})
            for i, n in enumerate(("plain", "leave_clean", "leave_term"))]


def test_a_three_target_list_parses_all_three_and_the_guard_matches_the_right_one(real):
    g, c, ent = real
    c["AssetMaker"].get_catalog_targets.return_value = _three()
    ts = g.list_catalog_targets()
    assert [(t.relationship_guid, t.element_guid, t.name) for t in ts] == [
        ("rel-0", "el-0", "scratch_cat_test5.plain"), ("rel-1", "el-1", "scratch_cat_test5.leave_clean"),
        ("rel-2", "el-2", "scratch_cat_test5.leave_term")]
    db = DatabaseEntity(slug="x", display_name="x", db_type="postgresql", host="h", port=1, database_name="scratch_cat_test5")
    assert [t.element_guid for t in cc._targets_for(ts, "el-1", db, "leave_clean")] == ["el-1"]
    assert cc._targets_for(ts, "el-9", db, "nothing") == []
    assert [t.element_guid for t in cc._targets_for(ts, "el-9", db, "leave_term")] == ["el-2"]      # by the target's own name


# ── D-E: the server by EXACT qualifiedName; none or several is an error, never a guess ────────

def _publish(real, matches):
    g, c, ent = real
    g._clients["surveyor"] = MagicMock()
    g._clients["surveyor"].catalog_and_survey.return_value = {"server_guid": "dbguid", "database_guid": "dbguid"}
    c["MetadataExpert"].find_metadata_elements_with_string.return_value = matches
    return g.publish_database(ent, "u", "p")


SERVER_QN = "PostgreSQL Server::host.docker.internal:5442"


def test_the_server_is_the_one_element_with_the_exact_server_qualified_name(real):
    pub = _publish(real, [live.raw_element("srv1", SERVER_QN, "SoftwareServer"),
                          live.raw_element("dbx", SERVER_QN + "::shop", "RelationalDatabase"),        # a fuzzy neighbour
                          live.raw_element("srv2", SERVER_QN + "-other", "SoftwareServer")])
    assert pub.server_guid == "srv1" and pub.server_name == "host.docker.internal:5442"


def test_no_server_reads_server_not_found_in_resource_explorers_own_words(real):
    with pytest.raises(gw.GatewayError) as err:
        _publish(real, "No elements found")
    assert cc.egeria_first_sentence(str(err.value))[0].startswith("server not found") and SERVER_QN in str(err.value)


def test_two_servers_read_server_ambiguous_and_the_commit_does_not_guess(real):
    with pytest.raises(gw.GatewayError) as err:
        _publish(real, [live.raw_element("a", SERVER_QN, "SoftwareServer"), live.raw_element("b", SERVER_QN, "SoftwareServer")])
    assert cc.egeria_first_sentence(str(err.value))[0].startswith("server ambiguous · 2 matches")


def test_an_ambiguous_server_fails_the_publish_step_with_the_cause_first(world, fake):
    fake.fail["publish_database"] = "server ambiguous · 2 matches for PostgreSQL Server::h:1; Resource Explorer will not guess"
    choose(world, "sales", "catalogue")
    _, rec = press(world, fake)
    st = step(rec, "publish_elements")
    assert st["state"] == "failed" and st["detail"].startswith("server ambiguous · 2 matches")
    assert fake.targets == []


def test_a_dataflow_whose_far_end_could_not_be_read_hangs_off_and_says_it_could_not_name_it():
    r = gw.Relationship("DataFlow", other_guid="far")
    h = cc.classify_hangs_off([[r]])
    assert h["total"] == 1 and h["lineage_to"] == ["an element Resource Explorer could not name"]
