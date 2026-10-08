"""scripts/clear_egeria_pointers_after_reset.py: clear Egeria POINTERS, keep DECISIONS and HISTORY.

Only temp SQLite. The script is never pointed at the shared registry by a test (REGISTRY_DATABASE_URL is a
tmp file in every test).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import clear_egeria_pointers_after_reset as S  # noqa: E402

from resource_explorer import catalogue_commit as cc  # noqa: E402
from resource_explorer import repo_publish  # noqa: E402
from resource_explorer.registry import DatabaseEntity, ProjectRegistry  # noqa: E402

RESET = "2026-10-08T18:30Z"
RESET_ISO = "2026-10-08T18:30:00"
NOW = datetime(2026, 10, 8, 19, 5, 0)
TOKEN = "dwolfson/2026-10-08T19:00Z"
PROJECT_STATUS = "linked"


@pytest.fixture
def env(tmp_path, monkeypatch):
    db = tmp_path / "reset_test.db"
    url = f"sqlite:///{db}"
    monkeypatch.setenv("REGISTRY_DATABASE_URL", url)
    monkeypatch.setenv("PGVECTOR_PORT", "1")
    reg = ProjectRegistry(db_path=str(db))
    with reg._conn() as c:
        from resource_explorer import work_lists
        work_lists._ensure_schema(c)
    seed(reg)
    return {"reg": reg, "dir": tmp_path / "plans", "name": "reset_test.db"}


def ins(reg, table, **cols):
    names = ", ".join(cols)
    marks = ", ".join("?" for _ in cols)
    with reg._conn() as c:
        c.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", list(cols.values()))


def seed(reg):
    G = "11111111-1111-1111-1111-111111111111"
    with reg._conn() as c:
        c.execute("INSERT INTO projects (slug, display_name, github_url, created_at, egeria_asset_guid) "
                  "VALUES ('repo1', 'R1', 'https://x/r1', '2026-09-01', ?)", (G,))
        c.execute("INSERT INTO projects (slug, display_name, github_url, created_at) "
                  "VALUES ('repo2', 'R2', 'https://x/r2', '2026-09-01')")
    reg.register_database(DatabaseEntity(slug="db1", display_name="D1", db_type="postgresql", host="localhost",
                                         port=5432, database_name="d", egeria_asset_guid=G))
    ins(reg, "sub_resources", resource_type="repo", resource_slug="repo1", locator="a/b", kind="file",
        cataloged_at="2026-10-01T00:00:00", egeria_guid=G)
    ins(reg, "entity_egeria_project_context", entity_type="repo", entity_slug="repo1", user_id="",
        status="linked", egeria_project_guid=G, egeria_project_qualified_name="Project::X::x")
    ins(reg, "entity_egeria_project_context", entity_type="repo", entity_slug="repo2", user_id="",
        status="personal")
    ins(reg, "project_egeria_surveys", project_slug="repo1", surveyed_at="2026-09-01T00:00:00",
        egeria_report_guid=G, published_at="2026-09-01T01:00:00", annotation_count=3)
    ins(reg, "project_published_annotation_types", project_slug="repo1", annotation_type="Q",
        published_at="2026-09-01T01:00:00", egeria_report_guid=G)
    ins(reg, "architecture_materialized_blueprints", id="b1", entity_type="repo", entity_slug="repo1",
        perspective="deployment", cluster_name="c", qualified_name="q", guid=G, materialized_at="2026-09-01")
    ins(reg, "architecture_materialized_components", id="c1", entity_type="repo", entity_slug="repo1",
        scope_locator="s", qualified_name="q", guid=G, materialized_at="2026-09-01")
    ins(reg, "survey_definition_cache", entity_type="repo", entity_slug="repo1", technology_type="t",
        process_guid=G, cached_at="2026-09-01")
    ins(reg, "egeria_linkage_status", entity_type="repo", entity_slug="repo1", status="stale", stale_guid=G,
        detected_at="2026-09-01")
    ins(reg, "work_lists", slug="wl", display_name="WL", created_at="2026-09-01", egeria_guid=G,
        published_at="2026-09-10")
    ins(reg, "native_survey_annotations", entity_type="database", slug="db1", engine_action_guid=G,
        report_guid=G, annotation_guid=G, annotation_type="X", read_at="2026-09-01") \
        if _has_native(reg) else None
    # keepers
    ins(reg, "architecture_component_verdicts", id="v1", entity_type="repo", entity_slug="repo1",
        scope_locator="s", verdict="accepted", decided_by="me", created_at="2026-09-02") if _has_verdicts(reg) else None
    for k, v in (("egeria_register_claim::db1", "x"), ("egeria_server_claim::h", "x"),
                 ("egeria_server_unconfirmed::h", "x"), ("egeria.github_source_control_library_guid", G),
                 ("repo_survey_step::repo1::x", "keep-me")):
        reg.set_setting(k, v)
    for status, kind in (("done", "annotation"), ("dead", "collection_membership"), ("pending", "annotation"),
                         ("failed", "annotation"), ("cancelled", "annotation")):
        ins(reg, "egeria_outbox", entity_type="repo", entity_slug="repo1", element_kind=kind,
            qualified_name=f"qn-{status}", payload_json="{}", status=status, created_at="2026-09-01",
            egeria_guid=G if status == "done" else "")
    reg.append_catalogue_commit_proof("db1", proof="database_published", node_kind="database", element_guid=G, read_at="2026-10-06T10:00:00")
    reg.append_catalogue_commit_proof("db1", proof="elements_read_back", node_kind="schema", schema_name="s1",
                                      element_guid=G, target_guid=G, detail={"tables": ["t"]},
                                      read_at="2026-10-06T11:00:00")
    reg.append_catalogue_commit_proof("repo1", proof="report_published", node_kind="repo_report", element_guid=G,
                                      read_at="2026-10-06T12:00:00")
    ins(reg, "catalogue_scope_events", database_slug="db1", node_kind="schema", schema_name="s1", table_name="",
        choice="catalogue", action="set", source="person", proposal_rule="", proposal_choice="", reason="",
        measured_at="", measured_json="{}", author="me", changed_at="2026-10-01")


def _has_native(reg):
    return _has_table(reg, "native_survey_annotations")


def _has_verdicts(reg):
    return _has_table(reg, "architecture_component_verdicts")


def _has_table(reg, t):
    with reg._conn() as c:
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (t,)).fetchone())


def dump(reg, tables=None) -> dict:
    out = {}
    with reg._conn() as c:
        names = tables or [r["name"] for r in c.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()]
        for t in names:
            out[t] = [dict(r) for r in c.execute(f"SELECT * FROM {t} ORDER BY 1, 2").fetchall()]
    return json.loads(json.dumps(out, default=str, sort_keys=True))


class Cap:
    def __init__(self):
        self.lines = []

    def __call__(self, s):
        self.lines.append(str(s))

    @property
    def text(self):
        return "\n".join(self.lines)


def dry(env, *extra, now=NOW):
    cap = Cap()
    rc = S.run(["--reset-at", RESET, "--out-dir", str(env["dir"]), *extra], out=cap, now=now)
    plan_hash = next((l.split(": ", 1)[1] for l in cap.text.splitlines() if l.startswith("plan hash: ")), "")
    plan_file = next((l.split(": ", 1)[1] for l in cap.text.splitlines() if l.startswith("plan file: ")), "")
    return rc, cap, plan_hash, plan_file


def apply(env, plan_hash, plan_file, extra=(), **over):
    args = {"--database": env["name"], "--cleared-by": TOKEN, "--plan-hash": plan_hash, "--plan-file": plan_file}
    args.update(over)
    argv = ["--reset-at", RESET, "--out-dir", str(env["dir"]), "--apply", *extra]
    for k, v in args.items():
        if v is not None:
            argv += [k, v]
    cap = Cap()
    rc = S.run(argv, out=cap, now=NOW)
    return rc, cap


# ── dry run ──────────────────────────────────────────────────────────────────

def test_dry_run_writes_nothing_and_prints_a_plan_and_a_hash(env):
    before = dump(env["reg"])
    rc, cap, h, f = dry(env)
    assert rc == 0 and len(h) == 64 and Path(f).exists()
    assert dump(env["reg"]) == before
    assert "DRY RUN (nothing written to the registry)" in cap.text and "reset_test.db" in cap.text
    plan = json.loads(Path(f).read_text())["plan"]
    assert "password" not in json.dumps(plan).lower() and "sqlite:///" not in Path(f).read_text()
    by = {a["id"]: a for a in plan["actions"]}
    assert by["clear:projects"]["count"] == 1 and by["clear:databases"]["count"] == 1
    assert by["supersede:egeria_outbox"]["count"] == 2          # pending + failed only
    assert plan["dead_outbox_untouched"] and "dead before the reset · untouched" in cap.text
    assert by["marker:catalogue_commit_proofs"]["count"] == 2   # db1 and repo1


def test_reset_at_must_be_a_time(env):
    cap = Cap()
    assert S.run(["--reset-at", "yesterday"], out=cap, now=NOW) == 2 and "REFUSED" in cap.text


# ── guards (each one fails on purpose, see the note in the report) ───────────

def test_apply_refuses_without_the_token(env):
    _, _, h, f = dry(env)
    before = dump(env["reg"])
    for bad in (None, "", "dwolfson", "dwolfson/not-a-time", "dwolfson/2026-10-01T19:00Z", "/2026-10-08T19:00Z"):
        rc, cap = apply(env, h, f, **{"--cleared-by": bad})
        assert rc == 2 and "REFUSED" in cap.text, bad
    assert dump(env["reg"]) == before


def test_apply_refuses_when_the_database_name_is_not_passed_again_or_is_wrong(env):
    _, _, h, f = dry(env)
    before = dump(env["reg"])
    for bad in (None, "", "other.db"):
        rc, cap = apply(env, h, f, **{"--database": bad})
        assert rc == 2 and "REFUSED" in cap.text
    assert dump(env["reg"]) == before


def test_apply_refuses_a_missing_or_wrong_plan_hash(env):
    _, _, h, f = dry(env)
    before = dump(env["reg"])
    assert apply(env, "", f)[0] == 2
    assert apply(env, "0" * 64, f)[0] == 2
    assert apply(env, h, "")[0] == 2
    assert dump(env["reg"]) == before


def test_apply_refuses_when_the_data_changed_since_the_dry_run(env):
    _, _, h, f = dry(env)
    env["reg"].set_setting("egeria_server_claim::new", "x")       # one more thing to clear
    before = dump(env["reg"])
    rc, cap = apply(env, h, f)
    assert rc == 2 and "changed since the dry run" in cap.text
    assert dump(env["reg"]) == before


def test_apply_refuses_a_stale_dry_run(env):
    _, _, h, f = dry(env, now=datetime(2026, 10, 8, 18, 0, 0))
    rc, cap = apply(env, h, f)
    assert rc == 2 and "older than" in cap.text


def test_apply_refuses_an_edited_plan_file(env):
    _, _, h, f = dry(env)
    data = json.loads(Path(f).read_text())
    data["plan"]["actions"][0]["count"] = 99
    Path(f).write_text(json.dumps(data))
    assert apply(env, h, f)[0] == 2


def test_apply_refuses_while_a_process_looks_active(env):
    reg = env["reg"]
    ins(reg, "activity_log", id="live", ts="2026-10-08T19:00:00", operation="survey", intent="x",
        entity_type="repo", entity_slug="repo1", status="running",
        detail=json.dumps({"_runner": __import__("resource_explorer.run_reconciler", fromlist=["x"]).process_identity()}))
    _, _, h, f = dry(env)
    before = dump(reg)
    rc, cap = apply(env, h, f)
    assert rc == 2 and "activity_log row live is running" in cap.text and dump(reg) == before
    with reg._conn() as c:
        c.execute("DELETE FROM activity_log WHERE id = 'live'")
        c.execute("UPDATE egeria_outbox SET status = 'running' WHERE qualified_name = 'qn-pending'")
    _, _, h, f = dry(env)
    rc, cap = apply(env, h, f)
    assert rc == 2 and "egeria_outbox row(s) are running" in cap.text


def test_an_owner_less_running_row_is_refused_not_assumed_dead(env):
    ins(env["reg"], "activity_log", id="mystery", ts="2026-10-08T19:00:00", operation="survey", intent="x",
        entity_type="repo", entity_slug="repo1", status="running", detail="{}")
    _, _, h, f = dry(env)
    rc, cap = apply(env, h, f)
    assert rc == 2 and "cannot be judged" in cap.text


def test_a_missing_column_fails_loudly(env):
    with env["reg"]._conn() as c:
        c.execute("ALTER TABLE doc_sources RENAME COLUMN egeria_link_relationship_guid TO renamed_away")
    rc, cap, _, f = dry(env)
    assert rc == 2 and "doc_sources.egeria_link_relationship_guid" in cap.text and not f


def test_a_missing_table_fails_loudly(env):
    with env["reg"]._conn() as c:
        c.execute("DROP TABLE survey_definition_cache")
    rc, cap, _, _ = dry(env)
    assert rc == 2 and "survey_definition_cache" in cap.text


def test_no_registry_url_is_a_refusal(monkeypatch):
    monkeypatch.delenv("REGISTRY_DATABASE_URL", raising=False)
    cap = Cap()
    assert S.run(["--reset-at", RESET], out=cap, now=NOW) == 2


# ── apply ────────────────────────────────────────────────────────────────────

KEEP_TABLES = ["architecture_component_verdicts", "catalogue_scope_events", "catalogue_scope_baselines",
               "resource_scope_events", "native_survey_annotations", "step_runs", "database_surveys",
               "project_analysis_findings", "project_analysis_metrics", "resource_journal", "project_groups",
               "work_list_members", "resource_curator_notes"]


def applied(env):
    _, _, h, f = dry(env, "--old-collection-id", "OLD", "--new-collection-id", "NEW")
    kept_before = dump(env["reg"], [t for t in KEEP_TABLES if _has_table(env["reg"], t)])
    proofs_before = dump(env["reg"], ["catalogue_commit_proofs"])["catalogue_commit_proofs"]
    outbox_before = {r["qualified_name"]: r for r in dump(env["reg"], ["egeria_outbox"])["egeria_outbox"]}
    argv = ["--reset-at", RESET, "--out-dir", str(env["dir"]), "--old-collection-id", "OLD",
            "--new-collection-id", "NEW", "--apply", "--plan-file", f, "--plan-hash", h,
            "--database", env["name"], "--cleared-by", TOKEN]
    cap = Cap()
    rc = S.run(argv, out=cap, now=NOW)
    return rc, cap, h, f, kept_before, proofs_before, outbox_before


def test_apply_clears_pointers_and_keeps_decisions_history_and_proofs(env):
    rc, cap, h, f, kept_before, proofs_before, outbox_before = applied(env)
    assert rc == 0, cap.text
    reg = env["reg"]
    d = dump(reg)
    # pointers cleared, rows kept
    assert d["projects"][0]["egeria_asset_guid"] in (None, "") and len(d["projects"]) == 2
    assert d["databases"][0]["egeria_asset_guid"] == ""
    assert d["sub_resources"][0]["egeria_guid"] == "" and d["sub_resources"][0]["cataloged_at"] == "2026-10-01T00:00:00"
    ctx = {r["entity_slug"]: r for r in d["entity_egeria_project_context"]}
    assert ctx["repo1"]["egeria_project_guid"] == "" and ctx["repo1"]["status"] == S.UNBOUND_STATUS
    assert ctx["repo1"]["egeria_project_qualified_name"] == "Project::X::x"
    assert ctx["repo2"]["status"] == "personal"
    assert d["project_egeria_surveys"][0]["egeria_report_guid"] == ""
    assert d["project_egeria_surveys"][0]["published_at"] == "2026-09-01T01:00:00"
    assert d["project_published_annotation_types"][0]["egeria_report_guid"] == ""
    assert d["work_lists"][0]["egeria_guid"] == "" and d["work_lists"][0]["published_at"] == ""
    # cache rows removed
    for t in ("architecture_materialized_blueprints", "architecture_materialized_components",
              "survey_definition_cache", "egeria_linkage_status"):
        assert d[t] == []
    keys = {r["key"] for r in d["app_settings"]}
    assert keys == {"repo_survey_step::repo1::x"}
    # decisions and history byte-identical
    assert dump(reg, [t for t in KEEP_TABLES if _has_table(reg, t)]) == kept_before
    # proofs: every old row identical, plus one marker per resource
    proofs = d["catalogue_commit_proofs"]
    assert proofs[:len(proofs_before)] == proofs_before
    markers = proofs[len(proofs_before):]
    assert sorted(m["database_slug"] for m in markers) == ["db1", "repo1"]
    assert all(m["proof"] == "egeria_reset" and m["read_at"] == RESET_ISO for m in markers)
    detail = json.loads(markers[0]["detail_json"])
    assert detail["text"] == "Egeria reset 2026-10-08 18:30 UTC · OLD → NEW"
    # outbox: done kept, dead left dead, cancelled left, pending and failed superseded
    ob = {r["qualified_name"]: r for r in d["egeria_outbox"]}
    assert ob["qn-done"] == outbox_before["qn-done"] and ob["qn-dead"] == outbox_before["qn-dead"]
    assert ob["qn-cancelled"] == outbox_before["qn-cancelled"]
    for q in ("qn-pending", "qn-failed"):
        assert ob[q]["status"] == "superseded" and ob[q]["last_error"] == "Egeria reset 2026-10-08 18:30 UTC"
    # audit row and snapshot
    act = [r for r in d["activity_log"] if r["operation"] == "egeria_reset_cleanup"]
    assert len(act) == 1 and act[0]["status"] == "ok" and TOKEN in act[0]["detail"]
    snap = Path(f).parent / f"egeria-reset-snapshot-reset_test.db-{h[:12]}.json"
    assert snap.exists() and oct(snap.stat().st_mode & 0o777) == "0o600"
    assert "egeria_asset_guid" in snap.read_text()


def test_second_run_clears_nothing_and_writes_no_second_marker(env):
    applied(env)
    reg = env["reg"]
    after_first = dump(reg)
    rc, cap, h, f = dry(env, "--old-collection-id", "OLD", "--new-collection-id", "NEW")
    plan = json.loads(Path(f).read_text())["plan"]
    assert rc == 0 and all(a["count"] == 0 for a in plan["actions"])
    rc, cap = apply(env, h, f, extra=("--old-collection-id", "OLD", "--new-collection-id", "NEW"))
    assert rc == 0
    after_second = dump(reg)
    after_second["activity_log"] = [r for r in after_second["activity_log"] if r["operation"] != "egeria_reset_cleanup"]
    expect = dict(after_first)
    expect["activity_log"] = [r for r in expect["activity_log"] if r["operation"] != "egeria_reset_cleanup"]
    assert after_second == expect
    assert sum(1 for p in after_second["catalogue_commit_proofs"] if p["proof"] == "egeria_reset") == 2


def test_a_failure_in_one_group_rolls_that_group_back_and_stops(env):
    _, _, h, f = dry(env)
    reg = env["reg"]
    with reg._conn() as c:
        c.execute("CREATE TRIGGER boom BEFORE UPDATE ON egeria_outbox BEGIN SELECT RAISE(ABORT, 'boom'); END")
    with pytest.raises(Exception, match="boom"):
        apply(env, h, f)
    d = dump(reg)
    assert d["sub_resources"][0]["egeria_guid"] == ""            # the groups before it were committed
    ob = {r["qualified_name"]: r["status"] for r in d["egeria_outbox"]}
    assert ob["qn-pending"] == "pending" and ob["qn-failed"] == "failed"   # the failing group rolled back whole
    assert all(p["proof"] != "egeria_reset" for p in d["catalogue_commit_proofs"])   # and nothing after it ran
    act = [r for r in d["activity_log"] if r["operation"] == "egeria_reset_cleanup"]
    assert act and act[0]["status"] == "error"


# ── the status derives from the marker ───────────────────────────────────────

def _view(reg, schemas=("s1",)):
    return {"schemas": [{"name": n, "effective": "catalogue", "tables": [{"name": "t", "effective": "catalogue"}]}
                        for n in schemas]}


def test_status_reads_published_earlier_and_counts_zero_in_egeria_after_the_marker(env):
    reg = env["reg"]
    before = cc.derive_commit_state(reg, "db1", _view(reg))
    assert before["schemas"]["s1"]["state"] == "catalogued" and "in Egeria" in before["header"]["text"]
    applied(env)
    after = cc.derive_commit_state(reg, "db1", _view(reg))
    st = after["schemas"]["s1"]
    assert st["state"] == "reset" and st["words"] == "published earlier · Egeria was reset · not in Egeria now"
    assert "Egeria reset 2026-10-08 18:30 UTC · OLD → NEW" in st["second"]
    assert after["tables"]["s1.t"]["words"].endswith("not in Egeria now")
    text = after["header"]["text"]
    assert "0 in Egeria" in text and "published earlier · Egeria was reset 10-08 18:30" in text
    # the proof rows are still there, unedited
    assert len(reg.list_catalogue_commit_proofs("db1")) == 3


def test_a_proof_after_the_reset_time_wins_over_the_marker(env):
    reg = env["reg"]
    applied(env)
    reg.append_catalogue_commit_proof("db1", proof="elements_read_back", node_kind="schema", schema_name="s1",
                                      element_guid="new", detail={"tables": ["t"]}, read_at="2026-10-08T20:00:00")
    after = cc.derive_commit_state(reg, "db1", _view(reg))
    assert after["schemas"]["s1"]["state"] == "catalogued"
    assert "1 in Egeria" in after["header"]["text"]


def test_a_resource_without_a_marker_derives_as_before(env):
    reg = env["reg"]
    h = cc.derive_commit_state(reg, "db1", _view(reg))["header"]["text"]
    assert "in Egeria" in h and "reset" not in h


def test_repo_publish_state_reads_the_marker_and_the_unbound_status(env):
    reg = env["reg"]
    assert repo_publish.publish_state(reg, "repo1")["row"]["word"] == "published"
    applied(env)
    st = repo_publish.publish_state(reg, "repo1")
    assert st["row"]["word"] == "reset" and st["in_egeria"] is False
    assert st["row"]["first"] == "published earlier · Egeria was reset · not in Egeria now"
    assert st["project"]["word"] == "unbound by reset · rebind to recreate"


# ── schema guard ─────────────────────────────────────────────────────────────

PG = "postgresql://u:secret@localhost:5442/egeria_advisor?options=-csearch_path%3Dresource_explorer"


def test_target_schema_parses_the_registry_url_and_refuses_a_missing_one():
    assert S.target_schema(PG) == "resource_explorer"
    assert S.target_schema("sqlite:///x.db") == "main"
    with pytest.raises(S.Refused, match="names no schema"):
        S.target_schema("postgresql://u:p@localhost:5442/egeria_advisor")


def test_a_postgres_url_without_a_search_path_is_refused_in_dry_run_and_apply(monkeypatch):
    monkeypatch.setenv("REGISTRY_DATABASE_URL", "postgresql://u:secret@localhost:1/egeria_advisor")
    for extra in ([], ["--apply", "--database", "egeria_advisor", "--schema", "public", "--cleared-by", TOKEN,
                       "--plan-file", "x", "--plan-hash", "y"]):
        cap = Cap()
        assert S.run(["--reset-at", RESET, *extra], out=cap, now=NOW) == 2
        assert "names no schema" in cap.text and "secret" not in cap.text


def test_dry_run_header_prints_the_schema_only(env):
    _, cap, _, f = dry(env)
    assert "schema: main" in cap.text
    assert json.loads(Path(f).read_text())["plan"]["schema"] == "main"


def test_the_plan_hash_covers_the_schema(env):
    reg = env["reg"]
    with reg._conn() as c:
        a = S.build_plan(c, "d", RESET_ISO, "", "", "resource_explorer")
        b = S.build_plan(c, "d", RESET_ISO, "", "", "public")
    assert a["hash"] != b["hash"]


def test_sqlite_apply_accepts_no_schema_flag_or_main_but_not_another(env):
    _, _, h, f = dry(env)
    before = dump(env["reg"])
    rc, cap = apply(env, h, f, **{"--schema": "resource_explorer"})
    assert rc == 2 and "--schema" in cap.text and dump(env["reg"]) == before
    rc, cap = apply(env, h, f, **{"--schema": "main"})
    assert rc == 0, cap.text


def test_sqlite_apply_without_the_schema_flag_is_accepted(env):
    _, _, h, f = dry(env)
    rc, cap = apply(env, h, f)
    assert rc == 0, cap.text


def test_a_plan_file_made_for_another_schema_is_refused(env):
    _, _, h, f = dry(env)
    data = json.loads(Path(f).read_text())
    data["plan"]["schema"] = "public"
    data["plan"]["hash"] = S.plan_hash(data["plan"])
    Path(f).write_text(json.dumps(data))
    rc, cap = apply(env, data["plan"]["hash"], f)
    assert rc == 2 and "schema" in cap.text
