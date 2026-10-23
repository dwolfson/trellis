"""The record of Egeria resets (`egeria_resets`) and the pre-reset status rule (PLAN-EGERIA-RESET-2026-10-23.md,
architect rulings (b) and (c); the project owner approved the table 2026-10-23).

A proof row older than the latest recorded reset never produces ✓ / "published" / "in Egeria" on any surface the
rule changed; rows after it behave as before; the profile publish's "previous" ignores rows before it; the CLI refuses
a future or out-of-order reset; with no reset recorded every derivation is unchanged. Temp SQLite only; no Egeria.
"""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime

import pytest
from typer.testing import CliRunner

from resource_explorer import catalogue_commit as cc
from resource_explorer import repo_publish
from resource_explorer.registry import EGERIA_RESETS_DDL, DatabaseEntity, PostgresCursorWrapper, ProjectRegistry
from resource_explorer.surveyors.database.quality.profile_publish import profile_publish_words

RESET = "2026-10-24T09:00:00Z"
BEFORE = "2026-10-20T10:00:00"
AFTER = "2026-10-24T12:00:00"
NOW = datetime(2026, 10, 25, 0, 0, 0)
WORDS = "published before the 2026-10-24 reset · not in Egeria now"
STEP = "value_profile"


@pytest.fixture
def reg(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "resets.db"))
    r.register_database(DatabaseEntity(slug="db1", display_name="D1", db_type="postgresql", host="localhost",
                                       port=5432, database_name="d"))
    with r._conn() as c:
        c.execute("INSERT INTO projects (slug, display_name, github_url, created_at) "
                  "VALUES ('repo1', 'R1', 'https://x/r1', '2026-09-01')")
    return r


def _reset(reg, at=RESET):
    return reg.record_egeria_reset(reset_at=at, old_platform_digest="a8bcff5c", new_platform_digest="newdig",
                                   old_commit="c6dbf952", new_commit="newc", recorded_by="coordinator", now=NOW)


def _catalogued(reg, at, guid="g"):
    reg.append_catalogue_commit_proof("db1", proof=cc.P_DATABASE, node_kind="database", element_guid=f"{guid}-db",
                                      detail={"server_guid": f"{guid}-srv"}, read_at=at)
    reg.append_catalogue_commit_proof("db1", proof=cc.P_TARGET, node_kind="schema", schema_name="s1",
                                      element_guid=f"{guid}-s1", read_at=at)
    reg.append_catalogue_commit_proof("db1", proof=cc.P_ELEMENTS, node_kind="schema", schema_name="s1",
                                      element_guid=f"{guid}-s1", detail={"tables": ["t"]}, read_at=at)


def _view():
    return {"schemas": [{"name": "s1", "effective": "catalogue", "tables": [{"name": "t", "effective": "catalogue"}]}]}


def _chips(state):
    return {c["key"]: c for c in state["read_back"]["chips"]}


# ── the DDL: the one approved table, additive and idempotent ─────────────────────────────────────────────────────

def test_the_ddl_is_one_create_table_if_not_exists_that_survives_the_postgres_translator():
    assert len(EGERIA_RESETS_DDL) == 1
    stmt = EGERIA_RESETS_DDL[0]
    assert stmt.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS EGERIA_RESETS")
    assert not re.search(r"\b(ALTER|DROP|INSERT|UPDATE|DELETE|INDEX)\b", stmt.upper())
    assert "?" not in stmt and not re.search(r"(?<!:):[A-Za-z_]", stmt)
    out = PostgresCursorWrapper(None)._translate_sql(stmt)
    assert "SERIAL PRIMARY KEY" in out and "AUTOINCREMENT" not in out and "%" not in out


def test_the_table_is_created_and_a_second_run_is_clean(tmp_path):
    path = str(tmp_path / "ddl.db")
    ProjectRegistry(db_path=path)
    ProjectRegistry(db_path=path)
    con = sqlite3.connect(path)
    for stmt in EGERIA_RESETS_DDL:              # and the statement itself, run again by hand
        con.execute(stmt)
    cols = [r[1] for r in con.execute("PRAGMA table_info(egeria_resets)")]
    assert cols == ["id", "reset_at", "old_platform_digest", "new_platform_digest", "old_commit", "new_commit",
                    "recorded_by", "note"]


# ── record / latest ──────────────────────────────────────────────────────────────────────────────────────────────

def test_no_reset_is_none_and_a_recorded_one_is_the_latest(reg):
    assert reg.latest_egeria_reset_at() is None
    _reset(reg)
    assert reg.latest_egeria_reset_at() == "2026-10-24T09:00:00Z"
    _reset(reg, "2026-10-24T21:00+00:00")
    assert reg.latest_egeria_reset_at() == "2026-10-24T21:00:00Z"
    assert reg.get_egeria_reset_at("anything") == "2026-10-24T21:00:00Z"   # applies to every resource


@pytest.mark.parametrize("at", ["2026-10-26T00:00:00Z", "not a time", "2026-10-23T00:00:00Z", RESET])
def test_record_refuses_future_unparseable_older_or_repeated(reg, at):
    _reset(reg)
    with pytest.raises(ValueError):
        _reset(reg, at)
    with reg._conn() as c:
        assert c.execute("SELECT COUNT(*) FROM egeria_resets").fetchone()[0] == 1


def _cli(monkeypatch, tmp_path, *args):
    import resource_explorer.config as config
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{tmp_path}/cli.db")
    config._config = None
    from resource_explorer.cli.main import app
    return CliRunner().invoke(app, ["registry", "record-egeria-reset", *args])


def test_the_cli_records_once_and_refuses_future_and_out_of_order(monkeypatch, tmp_path):
    ok = _cli(monkeypatch, tmp_path, "--reset-at", "2026-10-01T09:00Z", "--old-digest", "a8bcff5c",
              "--new-digest", "nd", "--old-commit", "c6dbf952", "--new-commit", "nc", "--recorded-by", "coord")
    assert ok.exit_code == 0, ok.output
    future = _cli(monkeypatch, tmp_path, "--reset-at", "2999-01-01T00:00Z")
    assert future.exit_code == 2 and "future" in future.output
    older = _cli(monkeypatch, tmp_path, "--reset-at", "2026-09-01T00:00Z")
    assert older.exit_code == 2 and "not newer" in older.output
    rows = sqlite3.connect(f"{tmp_path}/cli.db").execute(
        "SELECT reset_at, old_platform_digest, new_platform_digest, old_commit, new_commit, recorded_by "
        "FROM egeria_resets").fetchall()
    assert rows == [("2026-10-01T09:00:00Z", "a8bcff5c", "nd", "c6dbf952", "nc", "coord")]


# ── derivation 1: the catalogue commit state (derive_commit_state, header, table rows) ──────────────────────────

def test_no_reset_recorded_the_catalogue_state_is_unchanged(reg):
    _catalogued(reg, BEFORE)
    st = cc.derive_commit_state(reg, "db1", _view(), NOW)
    assert st["schemas"]["s1"]["state"] == "catalogued"
    assert "reset" not in st["header"]["text"]
    assert all(c["cue"] == "read_back" for c in st["read_back"]["chips"])


def test_a_pre_reset_proof_never_reads_catalogued(reg):
    _catalogued(reg, BEFORE)
    _reset(reg)
    st = cc.derive_commit_state(reg, "db1", _view(), NOW)
    s1 = st["schemas"]["s1"]
    assert s1["state"] == "reset" and s1["words"] == WORDS
    assert st["tables"]["s1.t"]["words"] == f"as its schema: {WORDS}"
    assert WORDS in st["header"]["text"] and "0 in Egeria" in st["header"]["text"]
    assert st["database"] is None
    assert "✓" not in cc.read_back_words(st["read_back"])


def test_a_post_reset_proof_behaves_as_today(reg):
    _catalogued(reg, BEFORE)
    _reset(reg)
    _catalogued(reg, AFTER, guid="n")
    st = cc.derive_commit_state(reg, "db1", _view(), NOW)
    assert st["schemas"]["s1"]["state"] == "catalogued" and st["database"]["guid"] == "n-db"
    assert all(c["cue"] == "read_back" for c in st["read_back"]["chips"])


def test_a_resource_with_nothing_before_the_reset_reads_as_before(reg):
    _reset(reg)
    _catalogued(reg, AFTER, guid="n")
    st = cc.derive_commit_state(reg, "db1", _view(), NOW)
    assert "reset" not in st["header"]["text"] and "in Egeria" not in st["header"]["text"].split("·")[-1]


# ── derivation 2: the read-back chips (read_back_chips / read_back_chips_for) ───────────────────────────────────

def test_the_chips_count_post_reset_proof_only_and_are_pending_not_checked(reg):
    _catalogued(reg, BEFORE)
    _reset(reg)
    chips = _chips(cc.derive_commit_state(reg, "db1", _view(), NOW))
    for key in ("published", "attached", "catalogued"):
        assert chips[key]["count"] == 0 and chips[key]["cue"] == "pending", key
        assert chips[key]["pre_reset_at"] == "2026-10-24T09:00:00Z" and WORDS in chips[key]["hover"]
    words = cc.read_back_words(cc.read_back_chips_for(reg, "db1", ["s1"], NOW))
    assert words == "published by RE 0 ◌ · attached 0 schemas ◌ · cataloged by Egeria 0 schemas ◌"


def test_cataloged_by_egeria_stays_pending_until_the_cataloguer_rebuilds(reg):
    _catalogued(reg, BEFORE)
    _reset(reg)
    reg.append_catalogue_commit_proof("db1", proof=cc.P_DATABASE, node_kind="database", element_guid="n-db",
                                      detail={"server_guid": "n-srv"}, read_at=AFTER)
    reg.append_catalogue_commit_proof("db1", proof=cc.P_TARGET, node_kind="schema", schema_name="s1",
                                      element_guid="n-s1", read_at=AFTER)
    chips = _chips(cc.derive_commit_state(reg, "db1", _view(), NOW))
    assert chips["published"]["cue"] == "read_back" and chips["attached"]["cue"] == "read_back"
    assert chips["catalogued"]["count"] == 0 and chips["catalogued"]["cue"] == "pending"


# ── derivation 3: the repository's publish row (repo_publish.publish_state) ─────────────────────────────────────

def _report(reg, at, guid="r"):
    reg.append_catalogue_commit_proof("repo1", proof=cc.P_REPORT, node_kind=repo_publish.NODE_REPORT,
                                      element_guid=guid, detail={"annotation_count": 3}, read_at=at)


def test_repo_publish_row_before_the_reset_is_not_published(reg):
    _report(reg, BEFORE)
    assert repo_publish.publish_state(reg, "repo1")["row"]["word"] == "published"   # no reset: unchanged
    _reset(reg)
    row = repo_publish.publish_state(reg, "repo1")["row"]
    assert row["word"] == "reset" and row["first"] == WORDS
    _report(reg, AFTER, guid="r2")
    assert repo_publish.publish_state(reg, "repo1")["row"]["word"] == "published"


def test_a_never_published_repo_says_nothing_about_the_reset(reg):
    _reset(reg)
    assert repo_publish.publish_state(reg, "repo1")["row"]["word"] == "none"


# ── derivation 4: the commit table's proof summary (repo_publish.commit_proof_summary) ──────────────────────────

def test_commit_summary_before_the_reset_is_pre_reset_not_read_back(reg):
    _report(reg, BEFORE)
    reg.append_catalogue_commit_proof("repo1", proof=repo_publish.P_SUB_RESOURCE, node_kind=repo_publish.NODE_SUB_RESOURCE,
                                      curation_id="c1", element_guid="sr", detail={"kind": "file", "role": "chosen"},
                                      read_at=BEFORE)
    cur = {"id": "c1", "requested_at": "2026-10-20T09:00:00"}
    plain = repo_publish.commit_proof_summary(reg, "repo1", cur)
    assert plain["report"]["state"] == "published" and plain["sub_resources"]["read_back"] == 1
    _reset(reg)
    out = repo_publish.commit_proof_summary(reg, "repo1", cur)
    assert out["report"]["state"] == "pre_reset" and out["report"]["words"] == WORDS
    assert out["sub_resources"]["read_back"] == 0 and out["sub_resources"]["by_row"]["files"]["pre_reset"] == 1
    assert out["pre_reset_words"] == WORDS


# ── derivation 5: published-as / publish proofs on run cards (registry._attach_publish_proofs) ──────────────────

def _activity(reg, ts):
    detail = json.dumps({"publish_state": "published to Egeria", "egeria_report_guid": "g", "published_as": "peter"})
    with reg._conn() as c:
        c.execute("INSERT INTO activity_log (id, ts, operation, intent, entity_type, entity_slug, status, detail) "
                  "VALUES (?, ?, 'survey', 'discovery', 'database', 'db1', 'ok', ?)", (f"a-{ts}", ts, detail))


def test_a_run_logged_before_the_reset_carries_pre_reset_and_its_read_back_proof_is_not_published(reg):
    _activity(reg, BEFORE)
    assert "pre_reset" not in reg.list_activity(entity_slug="db1")[0]                 # no reset: unchanged
    proof = {"state": "read_back", "word": "published · read back", "at": BEFORE, "words": ""}
    assert reg._pre_reset_publish_proof(proof, "db1") is proof
    _reset(reg)
    _activity(reg, AFTER)
    by_ts = {e["ts"]: e for e in reg.list_activity(entity_slug="db1")}
    assert by_ts[BEFORE]["pre_reset"] == {"at": "2026-10-24T09:00:00Z", "words": WORDS}
    assert "pre_reset" not in by_ts[AFTER]
    pre = reg._pre_reset_publish_proof(proof, "db1")
    assert pre["state"] == "pre_reset" and pre["word"] == WORDS
    assert reg._pre_reset_publish_proof({**proof, "at": AFTER}, "db1")["state"] == "read_back"


# ── derivation 6 + ruling (c): the profile publish ("previous" and the card's counts/words) ─────────────────────

def _profile(reg, guid, at, h="h1"):
    reg.record_profile_publish("database", "db1", report_guid=guid, report_at=at, read_at=at, analysis_step=STEP,
                               rows=[{"annotation_guid": f"{guid}-a", "item_key": "s1.t.c", "content_hash": h,
                                      "outcome": "created", "summary": "c"}])


def test_profile_previous_ignores_rows_before_the_reset(reg):
    _profile(reg, "rep-old", BEFORE)
    assert reg.latest_profile_publish("database", "db1", STEP)["report_guid"] == "rep-old"   # no reset: unchanged
    _reset(reg)
    assert reg.latest_profile_publish("database", "db1", STEP) is None   # the first post-reset run creates all
    _profile(reg, "rep-new", AFTER)
    prev = reg.latest_profile_publish("database", "db1", STEP)
    assert prev["report_guid"] == "rep-new" and set(prev["measures"]) == {"s1.t.c"}


def test_profile_card_of_a_pre_reset_publish_never_says_published(reg):
    _profile(reg, "rep-old", BEFORE)
    plain = reg.profile_publish_counts("rep-old", STEP)
    assert plain["pre_reset_at"] == "" and profile_publish_words(plain).startswith("1 measures published ·")
    _reset(reg)
    counts = reg.profile_publish_counts("rep-old", STEP)
    assert counts["pre_reset_at"] == "2026-10-24T09:00:00Z"
    assert profile_publish_words(counts) == f"1 measures {WORDS}"
    _profile(reg, "rep-new", AFTER)
    assert reg.profile_publish_counts("rep-new", STEP)["pre_reset_at"] == ""


# ── the per-resource reset readers pick the recorded reset up (publish_fields, stored copies, root folder) ─────

def test_publish_fields_and_reset_since_read_use_the_recorded_reset(reg):
    assert cc.publish_fields(reg, "repo1", BEFORE)["published_state"] == "published"
    _reset(reg)
    assert cc.publish_fields(reg, "repo1", BEFORE)["published_state"] == "published_earlier"
    assert cc.publish_fields(reg, "repo1", AFTER)["published_state"] == "published"
    assert cc.reset_since_read(BEFORE, cc.egeria_reset_at(reg, "repo1")) is True
