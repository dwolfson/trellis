"""Files build step 5 (2026-10-23): `file_profiles`, column rows per run with the source named, priced before the run.

Every test runs on a temp sqlite registry and fixture folders under tmp_path. The Egeria boundary is a fake bound to the
real port's signatures (`create_autospec(PyegeriaCsvSurveyPort, instance=True, spec_set=True)`). Nothing reaches Egeria, a
database or Ollama.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from resource_explorer.native_survey_run import ReportRead
from resource_explorer.registry import FILESYSTEM_FILE_COLUMNS_DDL, FileSystemEntity, ProjectRegistry
from resource_explorer.surveyors.filesystem import file_profiles as fp
from resource_explorer.surveyors.filesystem import walk_extensions as we

ASSET = "bbbbbbbb-0000-0000-0000-0000000000f5"
LIMIT = 40_000          # the profile limit the tests use (the step's default is 50 MB)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "fileprofiles.db"))


def _tree(tmp_path) -> Path:
    """3 csv, 1 parquet, 1 json, 1 xlsx, 1 binary data format (pickle), 1 oversize csv, and a README (not a data file)."""
    import pandas as pd

    root = tmp_path / "lake"
    (root / "sub").mkdir(parents=True)
    (root / "a.csv").write_text("id,name\n1,ann\n2,bob\n3,\n")
    (root / "b.csv").write_text("x,y,z\n1,2.5,2026-01-01\n2,3.5,2026-02-01\n")
    (root / "sub" / "c.csv").write_text("only\nq\nq\nr\n")
    pd.DataFrame({"k": [1, 2, 3], "v": ["a", "b", None]}).to_parquet(root / "d.parquet")
    (root / "e.json").write_text('[{"p": 1, "q": "s"}, {"p": 2, "q": "t"}]')
    pd.DataFrame({"m": [1, 2], "n": ["u", "w"]}).to_excel(root / "f.xlsx", index=False)
    (root / "g.pkl").write_bytes(b"\x80\x04binary")
    lines = ["n,word"] + [f"{i},w{i % 97}" for i in range(12_000)]
    (root / "big.csv").write_text("\n".join(lines) + "\n")
    (root / "README.md").write_text("# Lake\n\nData.\n")
    return root


def _walk(registry, root, *, slug="lake", led_by="re"):
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor

    fs = registry.get_filesystem(slug)
    if fs is None:
        registry.register_filesystem(FileSystemEntity(slug=slug, display_name="Lake", local_mount_point=str(root),
                                                      canonical_mount_point="/deployments/lake", egeria_asset_guid=ASSET))
        fs = registry.get_filesystem(slug)
    sd = LocalFileSystemSurveyor(fs, registry).run(profile_contents=False, walk_extensions=True)
    we.attach_extensions(fs, registry, sd, led_by=led_by)
    return fs


def _states(registry, slug="lake"):
    run = registry.list_filesystem_file_column_runs(slug)[0]
    return {r["file_path"]: r for r in registry.filesystem_file_profile_states(slug, run)}, run


def _port(*, listed=True):
    port = create_autospec(fp.pyegeria_port_class(), instance=True, spec_set=True)
    port.csv_survey_listed.return_value = listed
    port.csv_asset_guid.side_effect = lambda fs, rel, canonical: f"asset-{rel}"
    port.initiate.side_effect = lambda qn, target, guid, request_parameters=None: f"action-{guid}"
    return port


# ── 1. sampling: over the limit is sampled, never skipped ────────────────────────────────────────────────────────────

def test_a_file_over_the_limit_is_sampled_with_a_ratio_under_one_and_one_under_it_has_ratio_one(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root)
    fp.run_file_profiles(fs, registry, limit=LIMIT)
    states, run = _states(registry)
    assert states["big.csv"]["state"] == fp.SAMPLED
    assert 0 < states["big.csv"]["sample_ratio"] < 1
    assert states["a.csv"]["state"] == fp.MEASURED and states["a.csv"]["sample_ratio"] == 1
    big = registry.list_filesystem_file_columns("lake", run, file_path="big.csv")
    assert [c["column_name"] for c in big] == ["n", "word"]
    # a whole-line prefix was profiled: fewer records than the file holds, and no half row
    assert 0 < big[0]["record_ct"] < 12_000 and big[0]["null_ct"] == 0


def test_a_parquet_file_over_the_limit_reads_its_first_row_groups(tmp_path):
    import pandas as pd

    path = tmp_path / "rg.parquet"
    pd.DataFrame({"i": range(40_000), "s": [f"v{i}" for i in range(40_000)]}).to_parquet(path, row_group_size=5_000)
    size = path.stat().st_size
    out = fp.profile_file(path, "parquet", size, limit=size // 3)
    assert out["state"] == fp.SAMPLED and 0 < out["sample_ratio"] < 1
    assert out["columns"][0]["record_ct"] == round(out["sample_ratio"] * 40_000)
    assert out["columns"][0]["declared_type"] == "int64" and out["columns"][1]["declared_type"] == "string"


def test_a_whole_only_format_over_the_limit_is_a_row_saying_so_never_a_skip(tmp_path):
    path = tmp_path / "x.json"
    path.write_text('[{"a": 1}]' + " " * 5000)
    assert fp.profile_file(path, "json", path.stat().st_size, limit=100)["state"] == fp.OVER_LIMIT


# ── 2. formats not read, files not permitted ─────────────────────────────────────────────────────────────────────────

def test_an_unreadable_format_is_not_applicable_with_the_format_named_not_an_empty_profile(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root)
    fp.run_file_profiles(fs, registry, limit=LIMIT)
    states, run = _states(registry)
    assert states["g.pkl"]["state"] == fp.NOT_APPLICABLE and states["g.pkl"]["columns"] == 0
    rows = registry.list_filesystem_file_columns("lake", run, file_path="g.pkl")
    assert len(rows) == 1 and rows[0]["column_name"] == "" and rows[0]["record_ct"] is None
    counts = fp.card_counts(list(states.values()))
    assert counts["not_read"] == 1 and counts["not_read_formats"] == ["pkl"]
    assert "1 not read (formats: pkl)" in fp.card_words(counts)


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_an_inaccessible_file_is_not_permitted(registry, tmp_path):
    root = _tree(tmp_path)
    locked = root / "locked.csv"
    locked.write_text("a\n1\n")
    os.chmod(locked, 0)
    try:
        fs = _walk(registry, root)
        fp.run_file_profiles(fs, registry, limit=LIMIT)
        states, _ = _states(registry)
        assert states["locked.csv"]["state"] == fp.NOT_PERMITTED
        assert fp.card_counts(list(states.values()))["not_permitted"] == 1
    finally:
        os.chmod(locked, 0o644)


def test_a_secret_looking_data_file_is_never_opened(registry, tmp_path, monkeypatch):
    root = _tree(tmp_path)
    (root / "secret_keys.csv").write_text("k\nv\n")
    fs = _walk(registry, root)
    opened = []
    real = fp.profile_file
    monkeypatch.setattr(fp, "profile_file", lambda path, *a, **k: opened.append(path.name) or real(path, *a, **k))
    fp.run_file_profiles(fs, registry, limit=LIMIT)
    states, _ = _states(registry)
    assert states["secret_keys.csv"]["state"] == fp.SECRET_NAME and "secret_keys.csv" not in opened


# ── 3. the source choice ─────────────────────────────────────────────────────────────────────────────────────────────

def test_on_an_egeria_led_file_system_csv_goes_to_egeria_and_parquet_to_re(registry, tmp_path, monkeypatch):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="egeria")
    opened = []
    real = fp.profile_file
    monkeypatch.setattr(fp, "profile_file", lambda path, *a, **k: opened.append(path.name) or real(path, *a, **k))
    port = _port()
    out = fp.run_file_profiles(fs, registry, port=port, limit=LIMIT)
    states, _ = _states(registry)
    for name in ("a.csv", "b.csv", "sub/c.csv", "big.csv"):
        assert states[name]["state"] == fp.SUBMITTED
    assert states["d.parquet"]["state"] == fp.MEASURED and states["d.parquet"]["stats_source"] == fp.STATS_SOURCE_RE
    assert not {"a.csv", "b.csv", "c.csv", "big.csv"} & set(opened), "RE measures nothing Egeria measures"
    assert out["egeria_half"] == fp.EGERIA_HALF_SUBMITTED and out["egeria_files"] == 4
    # the survey is started on each file's asset, at the canonical path
    port.csv_asset_guid.assert_any_call(fs, "a.csv", "/deployments/lake/a.csv")
    port.initiate.assert_any_call(fp.CSV_SURVEY_QN, fp.CSV_ACTION_TARGET, "asset-a.csv")


def test_on_an_re_led_file_system_csv_and_parquet_both_go_to_re(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="re")
    port = _port()
    out = fp.run_file_profiles(fs, registry, port=port, limit=LIMIT)
    states, _ = _states(registry)
    assert states["a.csv"]["stats_source"] == fp.STATS_SOURCE_RE and states["d.parquet"]["stats_source"] == fp.STATS_SOURCE_RE
    assert out["egeria_half"] == fp.EGERIA_HALF_NONE
    port.csv_survey_listed.assert_not_called()
    port.initiate.assert_not_called()


def test_source_for_is_by_extension_and_lead():
    assert fp.source_for("x/a.csv", "egeria") == fp.SOURCE_EGERIA
    assert fp.source_for("x/a.parquet", "egeria") == fp.SOURCE_RE
    assert fp.source_for("x/a.csv", "re") == fp.SOURCE_RE
    assert fp.source_for("x/a.tsv", "egeria") == fp.SOURCE_RE


# ── 4. the Egeria half ───────────────────────────────────────────────────────────────────────────────────────────────

def test_egeria_not_listing_the_request_type_is_not_installed_and_the_re_half_still_runs(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="egeria")
    port = _port(listed=False)
    out = fp.run_file_profiles(fs, registry, port=port, limit=LIMIT)
    states, _ = _states(registry)
    assert out["egeria_half"] == fp.EGERIA_HALF_NOT_INSTALLED
    assert states["a.csv"]["state"] == fp.NOT_INSTALLED
    assert states["d.parquet"]["state"] == fp.MEASURED and states["f.xlsx"]["state"] == fp.MEASURED
    port.initiate.assert_not_called()
    assert fp.card_counts(list(states.values()))["not_installed"] == 4


def test_a_failed_check_is_could_not_check_never_not_installed(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="egeria")
    port = _port()
    port.csv_survey_listed.side_effect = TimeoutError("view server timed out")
    out = fp.run_file_profiles(fs, registry, port=port, limit=LIMIT)
    states, _ = _states(registry)
    assert out["egeria_half"] == fp.EGERIA_HALF_UNCHECKED and states["a.csv"]["state"] == fp.EGERIA_UNCHECKED
    assert "timed out" in out["egeria_actions"]["a.csv"]["error"]


def test_egerias_report_is_read_back_by_guid_into_column_rows_named_by_source(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="egeria")
    port = _port()
    fp.run_file_profiles(fs, registry, port=port, limit=LIMIT)
    port.report_guid_for_action.side_effect = lambda action: "rep-a" if action == "action-asset-a.csv" else None
    ann = lambda name, rec, nulls: {"guid": f"ann-{name}", "annotation_type": "ResourceProfileAnnotation", "analysis_step": "",  # noqa: E731
                                    "summary": "", "explanation": "", "confidence": 100,
                                    "detail": {"type_name": "ResourceProfileAnnotation",
                                               "profile_properties": {"columnName": name},
                                               "profile_counts": {"recordCount": rec, "nullCount": nulls},
                                               "inferred_data_type": "string", "value_range_from": "1", "value_range_to": "3"}}
    port.read_report.return_value = ReportRead(guid="rep-a", at="", originator_guid="action-asset-a.csv",
                                               annotations=[ann("id", 3, 0), ann("name", 3, 1)])
    out = fp.read_back_egeria(fs, registry, port)
    assert out["read"] == 1 and out["waiting"] == 3
    port.read_report.assert_called_once_with("rep-a")
    states, run = _states(registry)
    assert states["a.csv"]["state"] == fp.MEASURED and states["a.csv"]["stats_source"] == "egeria:rep-a"
    assert states["b.csv"]["state"] == fp.SUBMITTED
    cols = registry.list_filesystem_file_columns("lake", run, file_path="a.csv")
    assert [(c["column_name"], c["record_ct"], c["null_ct"], c["value_ct"]) for c in cols] == [("id", 3, 0, 3), ("name", 3, 1, 2)]
    assert all(c["egeria_report_guid"] == "rep-a" for c in cols)
    counts = fp.card_counts(list(states.values()))
    assert counts["by_egeria"] == 1 and counts["submitted"] == 3


# ── 5. the end to end over the fixture folder ────────────────────────────────────────────────────────────────────────

def test_end_to_end_row_counts_and_states_over_the_fixture_folder(registry, tmp_path):
    """The PR body states these: 8 data files (README.md is not one), 7 profiled by RE (1 of them sampled), 1 not read."""
    root = _tree(tmp_path)
    fs = _walk(registry, root)
    out = fp.run_file_profiles(fs, registry, limit=LIMIT)
    states, run = _states(registry)
    assert set(states) == {"a.csv", "b.csv", "sub/c.csv", "d.parquet", "e.json", "f.xlsx", "g.pkl", "big.csv"}
    assert out["data_files"] == 8 and out["re_files"] == 8 and out["egeria_files"] == 0
    columns = {k: v["columns"] for k, v in states.items()}
    assert columns == {"a.csv": 2, "b.csv": 3, "sub/c.csv": 1, "d.parquet": 2, "e.json": 2, "f.xlsx": 2, "g.pkl": 0,
                       "big.csv": 2}
    rows = registry.list_filesystem_file_columns("lake", run)
    assert len(rows) == 15                     # 14 column rows + the pkl's one state row
    c = fp.card_counts(list(states.values()))
    assert fp.card_words(c) == ("7 files profiled (0 by Egeria, 7 by RE), 1 sampled, 1 not read (formats: pkl), "
                                "0 not permitted")
    a = {r["column_name"]: r for r in rows if r["file_path"] == "a.csv"}
    assert a["name"]["record_ct"] == 3 and a["name"]["null_ct"] == 1 and a["name"]["distinct_ct"] == 2
    assert a["name"]["inferred_general_type"] == "A" and a["name"]["min_len"] == 3 and a["id"]["inferred_general_type"] == "N"
    assert a["id"]["min_text"] == "1" and a["id"]["max_text"] == "3"
    # nothing was written into the path
    assert sorted(p.name for p in root.rglob("*")) == sorted(
        ["a.csv", "b.csv", "sub", "c.csv", "d.parquet", "e.json", "f.xlsx", "g.pkl", "big.csv", "README.md"])
    # the run's own record: the walk it profiled, bytes and seconds, this machine
    record = fp.run_record(registry, "lake", run)
    assert record["metrics"]["walk_run_id"] and record["metrics"]["machine"] == fp.machine()
    assert record["metrics"]["re_bytes_read"] > 0


# ── 6. the price before the run ──────────────────────────────────────────────────────────────────────────────────────

def test_the_cost_line_before_any_run_and_after_one(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root, led_by="egeria")
    first = fp.price(registry, "lake", limit=LIMIT)
    assert first["words"].startswith("8 data files, ")
    assert "Egeria will profile 4 CSV files, RE will profile 4 others; no run yet to price from" in first["words"]
    ticks = iter([100.0, 102.0])
    out = fp.run_file_profiles(fs, registry, port=_port(listed=False), limit=LIMIT, clock=lambda: next(ticks))
    second = fp.price(registry, "lake", limit=LIMIT)
    assert second["bytes_per_second"] == round(out["re_bytes_read"] / 2.0)
    assert re.search(r"; about \d[\d,]* s$", second["words"])


def test_no_walk_yet_says_so(registry, tmp_path):
    registry.register_filesystem(FileSystemEntity(slug="empty", display_name="E", local_mount_point=str(tmp_path)))
    assert fp.price(registry, "empty")["words"] == "no walk yet · run the folder survey first"
    with pytest.raises(fp.NothingToProfile):
        fp.run_file_profiles(registry.get_filesystem("empty"), registry)


# ── 7. publish: RE's rows only, changed ones only, counts not values ─────────────────────────────────────────────────

def test_publish_takes_res_changed_rows_only_and_carries_sample_ratio_and_source_not_values(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root)
    first = fp.run_file_profiles(fs, registry, limit=LIMIT)
    rows = fp.changed_rows(registry, "lake", first["run_id"])
    assert len(rows) == 14
    specs = fp.publish_specs(rows, "/deployments/lake")
    big = next(s for s in specs if s["additional"]["filePath"] == "/deployments/lake/big.csv")
    assert float(big["additional"]["sampleRatio"]) < 1 and big["additional"]["statsSource"] == "resource-explorer"
    assert "sampled" in big["explanation"] and "surveyed by Resource Explorer" in big["summary"]
    assert all("min_text" not in s["value_count"] and "max_text" not in s["value_count"] for s in specs)
    second = fp.run_file_profiles(fs, registry, limit=LIMIT)
    assert fp.changed_rows(registry, "lake", second["run_id"]) == []
    (root / "a.csv").write_text("id,name\n1,ann\n2,bob\n3,cy\n4,dee\n")
    fs = _walk(registry, root)
    third = fp.run_file_profiles(fs, registry, limit=LIMIT)
    assert {r["file_path"] for r in fp.changed_rows(registry, "lake", third["run_id"])} == {"a.csv"}


def test_runs_are_kept_per_run_and_pruned_to_the_newest(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _walk(registry, root)
    for _ in range(fp.RUNS_KEPT + 1):
        fp.run_file_profiles(fs, registry, limit=LIMIT)
    assert len(registry.list_filesystem_file_column_runs("lake")) == fp.RUNS_KEPT
    registry.remove_filesystem("lake")
    assert registry.list_filesystem_file_column_runs("lake") == []


# ── 8. the DDL (owner's go 2026-10-23): one additive, idempotent statement ───────────────────────────────────────────

def test_the_ddl_is_one_create_table_if_not_exists_and_nothing_else():
    assert len(FILESYSTEM_FILE_COLUMNS_DDL) == 1
    stmt = FILESYSTEM_FILE_COLUMNS_DDL[0]
    assert stmt.lstrip().upper().startswith("CREATE TABLE IF NOT EXISTS FILESYSTEM_FILE_COLUMNS")
    up = stmt.upper()
    assert "ALTER" not in up and "DROP" not in up and "INSERT" not in up and "INDEX" not in up


def test_the_ddl_survives_the_postgres_translator():
    from resource_explorer.registry import PostgresCursorWrapper

    stmt = FILESYSTEM_FILE_COLUMNS_DDL[0]
    assert "?" not in stmt and not re.search(r"(?<!:):[A-Za-z_]", stmt)
    assert "%" not in PostgresCursorWrapper(None)._translate_sql(stmt)


def test_the_table_is_created_on_a_fresh_registry_and_a_reopen_is_idempotent(tmp_path):
    import sqlite3

    path = str(tmp_path / "ddl.db")
    ProjectRegistry(db_path=path)
    ProjectRegistry(db_path=path)
    con = sqlite3.connect(path)
    cols = [c[1] for c in con.execute("PRAGMA table_info(filesystem_file_columns)")]
    assert cols == ["filesystem_slug", "run_id", "file_path", "column_name", "ordinal", "declared_type",
                    "inferred_general_type", "record_ct", "value_ct", "null_ct", "distinct_ct", "min_text", "max_text",
                    "min_len", "max_len", "sample_ratio", "stats_source", "egeria_report_guid", "egeria_datafield_guid",
                    "state"]
    con.execute("INSERT INTO filesystem_file_columns (filesystem_slug, run_id, file_path, column_name) VALUES ('s','r','f','c')")
    with pytest.raises(sqlite3.IntegrityError):
        con.execute("INSERT INTO filesystem_file_columns (filesystem_slug, run_id, file_path, column_name) VALUES ('s','r','f','c')")


# ── 9. the routes: the card's view comes with the folder survey, the press runs the step ─────────────────────────────

@pytest.fixture
def api(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.auth import create_access_token
    from resource_explorer.web.app import app

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", registry.__dict__) or None)
    from tests.zone_fakes import open_access

    open_access(monkeypatch, caller_if_none="fileprofiles-tester")
    headers = {"Authorization": "Bearer " + create_access_token(user_id="fileprofiles-tester", egeria_token="tok")}
    return TestClient(app), headers


@pytest.mark.usefixtures("signed_in_caller")
def test_the_press_profiles_and_the_folder_survey_view_carries_the_card(api, registry, tmp_path, monkeypatch):
    client, headers = api
    root = _tree(tmp_path)
    _walk(registry, root)
    before = client.get("/api/filesystems/lake/file-profiles", headers=headers).json()
    assert before["run"] is None and "no run yet to price from" in before["price"]["words"]
    monkeypatch.setattr(fp, "PROFILE_LIMIT_BYTES", LIMIT)
    monkeypatch.setattr(fp.run_file_profiles, "__kwdefaults__", {**fp.run_file_profiles.__kwdefaults__, "limit": LIMIT})
    r = client.post("/api/filesystems/lake/file-profiles", headers=headers)
    assert r.status_code == 200, r.text
    assert r.json()["view"]["run"]["words"].startswith("7 files profiled (0 by Egeria, 7 by RE), 1 sampled")
    view = client.get("/api/filesystems/lake/folder-survey", headers=headers).json()
    assert view["file_profiles"]["run"]["counts"]["profiled"] == 7


@pytest.mark.usefixtures("signed_in_caller")
def test_the_press_with_no_walk_is_409_with_the_words(api, registry, tmp_path):
    client, headers = api
    registry.register_filesystem(FileSystemEntity(slug="nowalk", display_name="N", local_mount_point=str(tmp_path)))
    r = client.post("/api/filesystems/nowalk/file-profiles", headers=headers)
    assert r.status_code == 409 and "run the folder survey first" in r.json()["detail"]
