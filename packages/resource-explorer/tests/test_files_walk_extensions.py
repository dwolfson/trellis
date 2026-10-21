"""Files build step 1 (2026-10-21): the walk's extensions and `folder_narratives`.

What Egeria's Folder Survey does not keep, Resource Explorer's walk measures: bytes and depth per folder, owner, group and
mode, a content hash under a size limit, and the README-type narrative of each folder; with the per-file rows kept per run
(`filesystem_walk_files`, a PROPOSED table: every test here runs on a temp sqlite registry, never the shared Postgres).

Fakes bind the real signatures (`create_autospec(AssetMaker, instance=True, spec_set=True)`). Nothing reaches Egeria, a database
or Ollama.
"""
from __future__ import annotations

import builtins
import hashlib
import io
import json
import os
import pwd
import re
from pathlib import Path
from unittest.mock import create_autospec

import pytest

from resource_explorer import file_reach
from resource_explorer.registry import FILESYSTEM_WALK_FILES_DDL, FileSystemEntity, ProjectRegistry
from resource_explorer.surveyors.filesystem import walk_extensions as we

ASSET = "bbbbbbbb-0000-0000-0000-0000000000a1"


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "walkext.db"))


def _tree(tmp_path) -> Path:
    """  walkme/
           README.md            (title, paragraph, owner, source, dates, names data/payroll.csv)
           LICENSE              (MIT)
           .env                 (secret-looking name)
           top.txt
           data/payroll.csv, data/payroll.txt (sibling-named narrative), data/big.bin (over a tiny limit)
           data/deep/er/x.dat
           .git/HEAD, .git/objects/a (noise); node_modules/m/index.js (noise); sub/.git/HEAD (noise, nested)
    """
    root = tmp_path / "walkme"
    for d in ("data/deep/er", ".git/objects", "node_modules/m", "sub/.git"):
        (root / d).mkdir(parents=True)
    (root / "README.md").write_text(
        "# Walk Me\n\nThis folder holds the payroll extracts for 2026.\n\nOwner: Finance Data Team\n"
        "Source: HR system export\nCollected: 2026-01-05 to 2026-09-30\nFiles: data/payroll.csv\n")
    (root / "LICENSE").write_text("MIT License\n\nPermission is hereby granted, free of charge, to any person\n")
    (root / ".env").write_text("SECRET=1")
    (root / "top.txt").write_text("top")
    (root / "data" / "payroll.csv").write_text("a,b\n1,2\n")
    (root / "data" / "payroll.txt").write_text("Payroll columns: a is the id, b is the amount.\n")
    (root / "data" / "big.bin").write_bytes(b"x" * 5000)
    (root / "data" / "deep" / "er" / "x.dat").write_text("deep")
    (root / ".git" / "HEAD").write_text("ref")
    (root / ".git" / "objects" / "a").write_text("obj")
    (root / "node_modules" / "m" / "index.js").write_text("js")
    (root / "sub" / ".git" / "HEAD").write_text("ref")
    os.chmod(root / "top.txt", 0o600)
    os.chmod(root / "data" / "payroll.csv", 0o644)
    os.chmod(root / "data" / "deep" / "er" / "x.dat", 0o755)
    return root


def _register(registry, root, *, slug="walkme", canonical="/x/walkme"):
    registry.register_filesystem(FileSystemEntity(slug=slug, display_name="W", local_mount_point=str(root),
                                                  canonical_mount_point=canonical, egeria_asset_guid=ASSET))
    return registry.get_filesystem(slug)


def _walk(registry, root, *, slug="walkme", led_by="re", at=None, **kw):
    """The folder survey's walk with the extensions, finished the way the adapter finishes it."""
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor

    fs = registry.get_filesystem(slug) or _register(registry, root, slug=slug)
    sd = LocalFileSystemSurveyor(fs, registry, **kw).run(profile_contents=False, walk_extensions=True)
    if at:
        sd["surveyed_at"] = at
    we.attach_extensions(fs, registry, sd, led_by=led_by)
    return fs, sd


# ── 1. bytes and depth per folder; owner, group, mode ─────────────────────────────────────────────────────────────────

def test_per_folder_bytes_and_depth_and_the_rows_agree_a_second_way(registry, tmp_path):
    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    ext = sd["walk_extensions"]
    folders = ext["folders"]
    # deepest folder level: data/deep/er is level 3 (root = 0)
    assert folders["deepest_folder_depth"] == 3
    by_depth = {h["depth"]: h for h in folders["depth_histogram"]}
    assert by_depth[0]["files"] == 4 and by_depth[3]["files"] == 1
    # the heaviest folder by recursive bytes is data/ (5000 + 8 + 46 + 4 ...); its numbers are the sum of its files'
    largest = folders["largest_folders"]
    assert largest[0]["path"] == "data" and largest[0]["depth"] == 1
    data_bytes = sum(p.stat().st_size for p in (root / "data").rglob("*") if p.is_file())
    assert largest[0]["bytes"] == data_bytes and largest[0]["files"] == 4
    # a SECOND way to the same numbers: group the stored per-file rows in SQL and add them up again
    direct = {r["folder_path"]: r for r in registry.filesystem_walk_folder_totals("walkme", sd["surveyed_at"])}
    recursive = sum(r["bytes"] for k, r in direct.items() if k == "data" or k.startswith("data/"))
    assert recursive == largest[0]["bytes"]
    assert sum(r["bytes"] for r in direct.values()) == sd["total_size_bytes"] == folders["total_bytes"]
    assert direct["data/deep/er"]["folder_depth"] == 3 and direct[""]["folder_depth"] == 0


def test_owner_group_and_mode_come_from_stat(registry, tmp_path):
    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    rows = {r["file_path"]: r for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])}
    me = pwd.getpwuid(os.getuid()).pw_name
    assert rows["top.txt"]["owner_name"] == me and rows["top.txt"]["mode_octal"] == "0600"
    assert rows["top.txt"]["world_readable"] == 0
    assert rows["data/payroll.csv"]["mode_octal"] == "0644" and rows["data/payroll.csv"]["world_readable"] == 1
    assert rows["data/deep/er/x.dat"]["mode_octal"] == "0755"
    assert rows["top.txt"]["group_name"]
    ext = sd["walk_extensions"]
    assert ext["owners"]["distinct_owners"] == 1
    assert ext["modes"]["0600"] >= 1 and ext["modes"]["0644"] >= 1 and ext["modes"]["0755"] == 1
    assert ext["owners"]["world_readable_files"] == sum(1 for r in rows.values() if r["world_readable"])
    # depth rides on every row
    assert rows["data/deep/er/x.dat"]["folder_depth"] == 3 and rows["README.md"]["folder_depth"] == 0


# ── 2. the hash: under and over the limit, secrets, links, off ────────────────────────────────────────────────────────

def test_hash_under_the_limit_is_sha256_and_over_it_is_not_taken(registry, tmp_path, monkeypatch):
    monkeypatch.setenv(we.HASH_ENV, "1000")
    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    rows = {r["file_path"]: r for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])}
    assert rows["top.txt"]["content_hash"] == hashlib.sha256(b"top").hexdigest() and rows["top.txt"]["hash_state"] == "hashed"
    assert rows["data/big.bin"]["content_hash"] == "" and rows["data/big.bin"]["hash_state"] == "over_limit"
    h = sd["walk_extensions"]["hashing"]
    assert h["limit_bytes"] == 1000 and h["algorithm"] == "SHA-256" and h["over_limit_files"] == 1
    assert h["hashed_files"] == sum(1 for r in rows.values() if r["hash_state"] == "hashed")
    assert h["hashed_bytes"] == sum(r["size_bytes"] for r in rows.values() if r["hash_state"] == "hashed")


def test_the_default_hash_limit_is_ten_mebibytes_and_zero_turns_hashing_off(registry, tmp_path, monkeypatch):
    monkeypatch.delenv(we.HASH_ENV, raising=False)
    assert we.hash_limit_bytes() == 10 * 1024 * 1024 == we.HASH_MAX_BYTES_DEFAULT
    monkeypatch.setenv(we.HASH_ENV, "0")
    fs, sd = _walk(registry, _tree(tmp_path))
    rows = registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])
    assert {r["hash_state"] for r in rows} == {"hashing_off"} and not any(r["content_hash"] for r in rows)
    assert sd["walk_extensions"]["hashing"]["off"] is True
    monkeypatch.setenv(we.HASH_ENV, "not-a-number")
    assert we.hash_limit_bytes() == we.HASH_MAX_BYTES_DEFAULT


def test_a_secret_looking_name_and_a_link_are_never_opened_or_hashed(registry, tmp_path, monkeypatch):
    root = _tree(tmp_path)
    (root / "keys.omsecrets").write_text("x")
    (root / "server.pem").write_text("-----BEGIN-----")
    outside = tmp_path / "outside.txt"
    outside.write_text("not ours")
    os.symlink(outside, root / "linked.txt")
    opened = _watch_opens(monkeypatch, root)
    fs, sd = _walk(registry, root)
    rows = {r["file_path"]: r for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])}
    for name in (".env", "keys.omsecrets", "server.pem"):
        assert rows[name]["hash_state"] == "secret_name" and rows[name]["content_hash"] == ""
    assert rows["linked.txt"]["hash_state"] == "symlink" and rows["linked.txt"]["content_hash"] == ""
    assert not any(p.endswith((".env", ".omsecrets", ".pem", "linked.txt")) for p in opened), opened
    h = sd["walk_extensions"]["hashing"]
    assert h["secret_named_files"] == 3 and h["symlink_files"] == 1


def _watch_opens(monkeypatch, root):
    opened: list[str] = []
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open

    def watch(path):
        try:
            p = os.fspath(path)
        except TypeError:
            return
        if isinstance(p, bytes):
            p = os.fsdecode(p)
        if isinstance(p, str) and p.startswith(str(root)):
            opened.append(p)

    monkeypatch.setattr(builtins, "open", lambda f, *a, **k: (watch(f), real_open(f, *a, **k))[1])
    monkeypatch.setattr(io, "open", lambda f, *a, **k: (watch(f), real_io_open(f, *a, **k))[1])
    monkeypatch.setattr(os, "open", lambda f, *a, **k: (watch(f), real_os_open(f, *a, **k))[1])
    return opened


def test_the_walk_writes_nothing_into_the_path_and_changes_no_mtime(registry, tmp_path):
    root = _tree(tmp_path)

    def snapshot():
        out = {}
        for dirpath, dirnames, filenames in os.walk(root):
            for n in dirnames + filenames:
                st = (Path(dirpath) / n).lstat()
                out[str(Path(dirpath) / n)] = (st.st_size, st.st_mtime_ns)
        out[str(root)] = (0, root.stat().st_mtime_ns)
        return out

    before = snapshot()
    _walk(registry, root)
    assert snapshot() == before


# ── 3. noise directories counted and named; the cap says "capped at N" ────────────────────────────────────────────────

def test_noise_directories_are_counted_by_name_and_never_walked(registry, tmp_path):
    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    lim = sd["walk_limits"]
    assert lim["not_walked_by_name"] == {".git": 2, "node_modules": 1}
    assert lim["not_walked_directories"] == 3
    paths = {r["file_path"] for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])}
    assert not any(".git" in p or "node_modules" in p for p in paths)
    # and the publish names them (fixed noise names only), as a profile
    names = {s["annotation_type_name"]: s for s in we.extension_specs(sd)}
    assert names[we.PROFILE_DIRECTORIES_NOT_WALKED]["value_count"] == {".git": 2, "node_modules": 1}


def test_a_walk_that_hits_the_cap_says_capped_at_n(registry, tmp_path):
    root = _tree(tmp_path)
    fs, whole = _walk(registry, root)
    assert whole["walk_limits"]["capped"] is False and whole["walk_limits"]["capped_words"] == ""
    assert whole["walk_extensions"]["capped_words"] == ""
    registry.remove_filesystem("walkme")
    fs, sd = _walk(registry, root, max_entries=3)
    assert sd["walk_limits"]["capped"] is True
    assert sd["walk_limits"]["capped_words"] == "capped at 3 entries"
    assert sd["walk_extensions"]["capped_words"] == "capped at 3 entries"
    registry.remove_filesystem("walkme")
    fs, sd = _walk(registry, root, max_depth=1)
    assert sd["walk_limits"]["capped_words"] == "capped at depth 1"
    assert we.capped_words({"capped": True, "capped_reasons": ["entry cap", "depth cap"], "max_entries": 100000,
                            "max_depth": 20}) == "capped at 100,000 entries and depth 20"
    # the default cap is the walk's existing one
    from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import DEFAULT_MAX_ENTRIES

    assert DEFAULT_MAX_ENTRIES == 100_000


# ── 4. per-file rows per run id; retention; removal ───────────────────────────────────────────────────────────────────

def test_two_runs_keep_both_sets_of_rows(registry, tmp_path):
    root = _tree(tmp_path)
    fs, first = _walk(registry, root, at="2026-10-21T10:00:00")
    (root / "top.txt").write_text("changed content")
    (root / "new.txt").write_text("new")
    fs, second = _walk(registry, root, at="2026-10-21T11:00:00")
    runs = registry.list_filesystem_walk_runs("walkme")
    assert [r["run_id"] for r in runs] == ["2026-10-21T11:00:00", "2026-10-21T10:00:00"]
    one = {r["file_path"]: r for r in registry.list_filesystem_walk_files("walkme", "2026-10-21T10:00:00")}
    two = {r["file_path"]: r for r in registry.list_filesystem_walk_files("walkme", "2026-10-21T11:00:00")}
    assert "new.txt" not in one and "new.txt" in two
    assert one["top.txt"]["content_hash"] == hashlib.sha256(b"top").hexdigest()
    assert two["top.txt"]["content_hash"] == hashlib.sha256(b"changed content").hexdigest()
    assert runs[0]["files"] == len(two) and runs[1]["files"] == len(one)


def test_rows_say_who_led_and_which_egeria_report_their_counts_live_in(registry, tmp_path):
    fs, sd = _walk(registry, _tree(tmp_path))
    assert {r["led_by"] for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])} == {"re"}
    assert {r["egeria_report_guid"] for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])} == {""}
    n = registry.set_filesystem_walk_report("walkme", sd["surveyed_at"], "report-guid-9")
    rows = registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])
    assert n == len(rows) and {r["egeria_report_guid"] for r in rows} == {"report-guid-9"}
    assert {r["led_by"] for r in rows} == {"egeria"}


def test_retention_keeps_the_newest_runs_and_removal_takes_them_all(registry, tmp_path):
    root = _tree(tmp_path)
    fs = _register(registry, root)
    for i in range(we.WALK_RUNS_KEPT + 2):
        registry.add_filesystem_walk_files("walkme", f"2026-10-21T0{i}:00:00", [
            {"file_path": "a.txt", "folder_path": "", "folder_depth": 0, "size_bytes": 1, "modified_at": "", "owner_name": "o",
             "group_name": "g", "mode_octal": "0644", "world_readable": 1, "content_hash": "", "hash_state": "over_limit"}])
    runs = [r["run_id"] for r in registry.list_filesystem_walk_runs("walkme")]
    assert len(runs) == we.WALK_RUNS_KEPT == 5
    assert runs[0] == "2026-10-21T06:00:00" and runs[-1] == "2026-10-21T02:00:00"      # the two oldest are gone
    registry.remove_filesystem("walkme")
    assert registry.list_filesystem_walk_runs("walkme") == []


def test_rows_are_stored_all_or_none(registry, tmp_path):
    fs = _register(registry, _tree(tmp_path))
    good = {"file_path": "a.txt", "folder_path": "", "folder_depth": 0, "size_bytes": 1, "modified_at": "", "owner_name": "o",
            "group_name": "g", "mode_octal": "0644", "world_readable": 1, "content_hash": "", "hash_state": "hashed"}
    with pytest.raises(Exception):
        registry.add_filesystem_walk_files("walkme", "r1", [good, {**good, "file_path": None}])     # NOT NULL fails midway
    assert registry.list_filesystem_walk_runs("walkme") == []


def test_the_blob_never_carries_the_rows_and_the_view_proves_them_from_the_registry(registry, tmp_path):
    from resource_explorer.folder_survey_view import extensions_view

    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    assert "walk_files" not in sd
    registry.add_filesystem_survey("walkme", sd["surveyed_at"], {**sd, "surveyed_by": {"surveyor": "Resource Explorer", "reach": {}}},
                                   source="survey-definition")
    assert "walk_files" not in json.dumps(registry.list_filesystem_surveys("walkme"))
    v = extensions_view(registry, "walkme")
    assert v["rows"]["kept"] is True and v["rows"]["files"] == sd["total_files"] and v["rows"]["runs_kept"] == 1
    # the claim "rows kept" follows the registry: remove the rows and the view stops saying so, though the blob still says it ran
    with registry._conn() as conn:
        conn.execute("DELETE FROM filesystem_walk_files WHERE filesystem_slug = ?", ("walkme",))
    v = extensions_view(registry, "walkme")
    assert v["rows"]["kept"] is False and v["rows"]["files"] == 0
    assert extensions_view(registry, "no-such-slug") is None


# ── 5. folder_narratives ──────────────────────────────────────────────────────────────────────────────────────────────

def test_folder_narratives_over_the_rows(registry, tmp_path):
    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    entries = {e["file"]: e for e in sd["folder_narratives"]}
    assert set(entries) == {"README.md", "LICENSE", "data/payroll.txt"}          # .env is secret-named; top.txt is no narrative
    readme = entries["README.md"]
    assert readme["status"] == "proposal" and readme["stated_by"] == "README.md"
    assert readme["title"] == "Walk Me" and readme["description"].startswith("This folder holds the payroll extracts for 2026")
    assert readme["stated_owner"] == "Finance Data Team" and readme["stated_source"] == "HR system export"
    assert "2026-01-05" in readme["stated_dates"] and "2026-09-30" in readme["stated_dates"]
    assert readme["declared_files"] == ["LICENSE"] or "LICENSE" not in readme["declared_files"]      # names found in the text
    assert "top.txt" not in readme["declared_files"]
    # evidence: the file and its modified time (from the rows), the folder and its depth
    assert readme["modified_at"] and readme["folder"] == "" and readme["folder_depth"] == 0
    assert entries["LICENSE"]["licence"] == "MIT"
    sibling = entries["data/payroll.txt"]               # a text file named for its sibling data file
    assert sibling["folder"] == "data" and "payroll" in sibling["title"].lower()
    summary = sd["walk_extensions"]["narratives"]
    assert summary["folders_with_narrative"] == 2 and summary["files_read"] == 3
    assert summary["licences"] == {"MIT": 1} and summary["folders_with_stated_owner"] == 1
    assert summary["folders_with_licence"] == 1 and summary["stopped_at_read_cap"] is False


def test_the_narrative_step_opens_only_its_candidate_files(registry, tmp_path, monkeypatch):
    """Hashing off, so any file opened was opened to be read as a narrative: exactly the candidates, never a secret."""
    monkeypatch.setenv(we.HASH_ENV, "0")
    root = _tree(tmp_path)
    (root / "NOTES.md").write_text("# Notes\n\nmore\n")
    (root / "SECRETS-README.md").write_text("password=hunter2")        # candidate-looking, but secret-named
    (root / "README_big.md").write_text("x" * (we.NARRATIVE_MAX_FILE_BYTES + 1))
    opened = _watch_opens(monkeypatch, root)
    fs, sd = _walk(registry, root)
    got = sorted(Path(p).relative_to(root).as_posix() for p in opened)
    assert got == ["LICENSE", "NOTES.md", "README.md", "data/payroll.txt"]
    assert not any("SECRETS" in p or ".env" in p or "payroll.csv" in p for p in opened)


def test_a_narrative_read_is_capped_per_file(tmp_path):
    root = tmp_path / "r"
    root.mkdir()
    (root / "README.md").write_text("# T\n\n" + ("word " * 100000) + "\nOwner: beyond the read cap\n")
    row = {"file_path": "README.md", "folder_path": "", "folder_depth": 0, "size_bytes": 500_000, "modified_at": "t",
           "hash_state": "hashing_off"}
    out = we.folder_narratives(root, [row], read_bytes=1024)
    assert out["entries"][0]["stated_owner"] == ""          # the owner line sat past the 1 KiB that was read
    assert len(out["entries"][0]["description"]) <= 400


def test_licence_names_are_recognised_or_not_kept():
    assert we.licence_name("Apache License\nVersion 2.0, January 2004") == "Apache-2.0"
    assert we.licence_name("GNU GENERAL PUBLIC LICENSE\nVersion 3, 29 June 2007") == "GPL-3.0"
    assert we.licence_name("License: MIT") == "MIT"
    assert we.licence_name("License: all rights reserved to Acme") == ""        # unrecognised text is never kept


# ── 6. what is published: counts only, one annotation per declared type ──────────────────────────────────────────────

def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for k, v in value.items():
            yield str(k)
            yield from _strings(v)
    elif isinstance(value, (list, tuple, set)):
        for v in value:
            yield from _strings(v)


def test_one_annotation_per_declared_type_with_egerias_types_and_properties(registry, tmp_path):
    from resource_explorer.surveyors.filesystem.folder_survey_annotations import to_annotations

    fs, sd = _walk(registry, _tree(tmp_path))
    specs = we.extension_specs(sd)
    names = [s["annotation_type_name"] for s in specs]
    assert sorted(names) == sorted(we.EXTENSION_NAMES) and len(set(names)) == len(names)      # each declared type, once
    kinds = {a.annotation_type_name: a.annotation_type.value for a in to_annotations(specs)}
    assert kinds == {
        we.CAPTURE_FOLDER_BULK: "ResourceMeasureAnnotation", we.PROFILE_FOLDER_DEPTHS: "ResourceProfileAnnotation",
        we.CAPTURE_FILE_OWNERSHIP: "ResourceMeasureAnnotation", we.PROFILE_FILE_MODES: "ResourceProfileAnnotation",
        we.CAPTURE_CONTENT_HASHES: "ResourceMeasureAnnotation", we.CAPTURE_FOLDER_NARRATIVES: "ResourceMeasureAnnotation",
        we.PROFILE_NARRATIVE_LICENCES: "ResourceProfileAnnotation", we.PROFILE_DIRECTORIES_NOT_WALKED: "ResourceProfileAnnotation",
    }
    by = {s["annotation_type_name"]: s for s in specs}
    assert by[we.CAPTURE_FOLDER_BULK]["resource_properties"]["Deepest folder level"] == "3"
    assert by[we.CAPTURE_FOLDER_BULK]["resource_properties"]["Folders holding files"] == str(sd["walk_extensions"]["folders"]["folders_with_files"])
    assert by[we.CAPTURE_FILE_OWNERSHIP]["resource_properties"]["Distinct owners"] == "1"
    assert by[we.CAPTURE_CONTENT_HASHES]["resource_properties"]["Hash algorithm"] == "SHA-256"
    assert by[we.CAPTURE_CONTENT_HASHES]["resource_properties"]["Files not hashed (secret-looking name)"] == "1"
    assert by[we.PROFILE_FILE_MODES]["value_count"]["0755"] == 1
    assert by[we.PROFILE_NARRATIVE_LICENCES]["value_count"] == {"MIT": 1}
    assert by[we.PROFILE_FOLDER_DEPTHS]["value_count"]["3"] == 1
    assert all(isinstance(v, str) for s in specs if "resource_properties" in s for v in s["resource_properties"].values())


def test_no_path_name_owner_hash_or_narrative_text_reaches_any_annotation(registry, tmp_path):
    from resource_explorer.surveyors.filesystem.folder_survey_annotations import to_annotations

    root = _tree(tmp_path)
    fs, sd = _walk(registry, root)
    me = pwd.getpwuid(os.getuid()).pw_name
    group = registry.list_filesystem_walk_files("walkme", sd["surveyed_at"])[0]["group_name"]
    hashes = [r["content_hash"] for r in registry.list_filesystem_walk_files("walkme", sd["surveyed_at"]) if r["content_hash"]]
    assert hashes
    seen = []
    for a in to_annotations(we.extension_specs(sd), additional={"surveyor": "Resource Explorer"}):
        for attr in ("resource_properties", "json_properties", "value_count", "additional_properties", "action_requested",
                     "summary", "explanation"):
            seen.extend(_strings(getattr(a, attr, None)))
    blob = "\n".join(seen)
    leaks = [str(root), "/x/walkme", "payroll", "README", "LICENSE", ".env", "top.txt", "big.bin", "x.dat", "data/deep", "Finance Data Team",
             "HR system export", "Walk Me", "extracts", me, group, *hashes]
    for leak in leaks:
        assert leak not in blob, f"{leak!r} reached an annotation property"
    assert not re.search(r"[0-9a-f]{64}", blob)


def test_a_section_the_walk_did_not_measure_is_left_out_not_published_as_zero():
    assert we.extension_specs({"surveyed_at": "t"}) == []
    only = we.extension_specs({"walk_extensions": {"hashing": {"algorithm": "SHA-256", "limit_bytes": 0, "off": True,
                                                              "hashed_files": 0, "hashed_bytes": 0}}})
    assert [s["annotation_type_name"] for s in only] == [we.CAPTURE_CONTENT_HASHES]
    assert only[0]["resource_properties"]["Hashing off"] == "true"


# ── 7. the DDL (proposed): additive, idempotent, translator-safe; no test touches the shared Postgres ───────────────

def test_the_ddl_block_is_additive_and_idempotent_text():
    assert all(s.lstrip().upper().startswith(("CREATE TABLE IF NOT EXISTS", "CREATE INDEX IF NOT EXISTS"))
               for s in FILESYSTEM_WALK_FILES_DDL)
    joined = " ".join(FILESYSTEM_WALK_FILES_DDL).upper()
    assert "ALTER" not in joined and "DROP" not in joined and "INSERT" not in joined and "UPDATE" not in joined


def test_the_ddl_survives_the_postgres_translator():
    from resource_explorer.registry import PostgresCursorWrapper

    t = PostgresCursorWrapper(None)._translate_sql
    for stmt in FILESYSTEM_WALK_FILES_DDL:
        assert "?" not in stmt and not re.search(r"(?<!:):[A-Za-z_]", stmt)
        assert "%" not in t(stmt)
    out = t(FILESYSTEM_WALK_FILES_DDL[0])
    assert "SERIAL PRIMARY KEY" in out and "AUTOINCREMENT" not in out


def test_the_table_is_created_on_a_fresh_sqlite_registry_and_a_reopen_is_idempotent(tmp_path):
    import sqlite3

    path = str(tmp_path / "ddl.db")
    ProjectRegistry(db_path=path)
    ProjectRegistry(db_path=path)
    con = sqlite3.connect(path)
    cols = [c[1] for c in con.execute("PRAGMA table_info(filesystem_walk_files)")]
    assert cols == ["id", "filesystem_slug", "run_id", "file_path", "folder_path", "folder_depth", "size_bytes", "modified_at",
                    "owner_name", "group_name", "mode_octal", "world_readable", "content_hash", "hash_state", "led_by",
                    "egeria_report_guid"]
    idx = {i[1] for i in con.execute("PRAGMA index_list(filesystem_walk_files)")}
    assert {"idx_fs_walk_files_folder", "idx_fs_walk_files_hash"} <= idx
    con.close()


def test_the_tests_never_reach_the_shared_registry(registry):
    assert "5442" not in str(getattr(registry, "database_url", "")) and not getattr(registry, "is_postgres", False)
    assert os.environ.get("REGISTRY_DATABASE_URL", "").startswith("sqlite")


# ── 8. publish through the real publisher with a fake that binds the real signatures ────────────────────────────────

def _fake_surveyor(monkeypatch, *, landed):
    from pyegeria import AssetMaker

    from resource_explorer.surveyors.filesystem import egeria_filesystem_surveyor as mod

    maker = create_autospec(AssetMaker, instance=True, spec_set=True)
    maker.create_asset.return_value = "report-guid-7"
    maker.get_asset_by_guid.return_value = {"elementHeader": {"guid": "report-guid-7", "type": {"typeName": "SurveyReport"}},
                                            "properties": {"qualifiedName": "q"}}
    real = mod.EgeriaFileSystemSurveyor
    built: list = []

    class Fake(real):
        def __init__(self, **kw):
            super().__init__()
            self.connect = lambda: None
            self._asset_maker = maker

        def _create_annotations(self, anns, report_guid, slug, at):
            built.extend(anns)
            n = len(anns) if landed is None else min(landed, len(anns))
            return [f"g{i}" for i in range(n)] + [""] * (len(anns) - n)

    monkeypatch.setattr(mod, "EgeriaFileSystemSurveyor", Fake)
    return maker, built


@pytest.fixture
def api(registry, monkeypatch):
    from fastapi.testclient import TestClient

    from resource_explorer.auth import create_access_token
    from resource_explorer.web.app import app

    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", registry.__dict__) or None)
    from tests.zone_fakes import open_access

    open_access(monkeypatch, caller_if_none="walkext-tester")
    headers = {"Authorization": "Bearer " + create_access_token(user_id="walkext-tester", egeria_token="tok")}
    return TestClient(app), headers


def _probe_row(registry, outcome, *, slug="walkme", at="2026-10-21T08:00:00+00:00", **detail):
    registry.record_reachability_check(slug, probed_at=at, outcome=outcome, error_detail=json.dumps({"path": "/x/walkme", **detail}))


@pytest.mark.usefixtures("signed_in_caller")
def test_end_to_end_the_press_walks_keeps_rows_publishes_and_reads_back(api, registry, tmp_path, monkeypatch):
    """Through the real routes and the real publisher: only the Egeria boundary (AssetMaker) is faked."""
    client, headers = api
    root = _tree(tmp_path)
    _register(registry, root)
    _probe_row(registry, "re_only")
    maker, built = _fake_surveyor(monkeypatch, landed=None)

    r = client.post("/api/filesystems/walkme/folder-survey", json={"publish": True}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["led_by"] == "resource_explorer" and body["capped"] is False and body["capped_words"] == ""
    assert body["rows_kept"]["rows"] == body["total_files"] and body["rows_kept"]["error"] == ""
    n = body["annotation_count"]
    assert body["published"] is True and body["annotations_in_egeria"] == n
    assert body["landed_words"] == f"{n} of {n} annotations in Egeria"
    maker.get_asset_by_guid.assert_called_once()                    # the SurveyReport was read back
    # the report carries Egeria's folder-survey types AND one annotation per extension type; nothing else
    types = [a.annotation_type_name for a in built]
    assert set(we.EXTENSION_NAMES) <= set(types) and len(types) == len(set(types))
    assert "Capture File Counts" in types and "Profile File Names to External Log" not in types
    props = maker.create_asset.call_args.kwargs["body"]["properties"]
    assert props["additionalProperties"]["walkExtensions"] == "true" and props["additionalProperties"]["hashAlgorithm"] == "SHA-256"

    view = client.get("/api/filesystems/walkme/folder-survey", headers=headers).json()
    ext = view["extensions"]
    assert ext["rows"]["kept"] is True and ext["rows"]["files"] == body["total_files"] and ext["led_by"] == "re"
    assert ext["published"] is True and ext["publish"]["landed_words"] == f"{n} of {n} annotations in Egeria"
    assert ext["folders"]["deepest_folder_depth"] == 3 and ext["hashing"]["algorithm"] == "SHA-256"
    assert ext["owners"]["distinct_owners"] == 1 and {e["file"] for e in ext["narratives"]} == {"README.md", "LICENSE", "data/payroll.txt"}
    assert ext["not_walked_by_name"] == {".git": 2, "node_modules": 1}
    # the stored rows are what "kept" means
    assert len(registry.list_filesystem_walk_files("walkme", ext["run_id"])) == body["total_files"]


@pytest.mark.usefixtures("signed_in_caller")
@pytest.mark.parametrize("landed, words", [(2, "2 of {n} annotations in Egeria"), (0, None)])
def test_publish_says_how_many_landed_including_none(api, registry, tmp_path, monkeypatch, landed, words):
    client, headers = api
    _register(registry, _tree(tmp_path))
    _probe_row(registry, "re_only")
    _fake_surveyor(monkeypatch, landed=landed)
    body = client.post("/api/filesystems/walkme/folder-survey", json={"publish": True}, headers=headers).json()
    if landed == 0:
        assert body["published"] is False and body["not_published_why"] == "no annotation landed in Egeria"
        ext = client.get("/api/filesystems/walkme/folder-survey", headers=headers).json()["extensions"]
        assert ext["published"] is False and ext["publish"]["not_published_why"] == "no annotation landed in Egeria"
    else:
        assert body["published"] is True and body["landed_words"] == words.format(n=body["annotation_count"])


@pytest.mark.usefixtures("signed_in_caller")
def test_beside_an_egeria_led_survey_only_the_extensions_are_measured_and_published(api, registry, tmp_path, monkeypatch):
    client, headers = api
    root = _tree(tmp_path)
    _register(registry, root)
    _probe_row(registry, "egeria_verified")
    maker, built = _fake_surveyor(monkeypatch, landed=None)

    r = client.post("/api/filesystems/walkme/walk-extensions", json={"publish": True}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["led_by"] == "egeria" and body["files"] > 0 and body["rows_kept"]["error"] == ""
    types = {a.annotation_type_name for a in built}
    assert types == set(we.EXTENSION_NAMES)                          # none of Egeria's own types: Egeria keeps those
    assert body["published"] is True
    props = maker.create_asset.call_args.kwargs["body"]["properties"]
    assert "beside Egeria's Folder Survey" in props["description"]
    rows = registry.list_filesystem_walk_files("walkme", body["run_id"])
    assert rows and {r["led_by"] for r in rows} == {"egeria"}
    # the card is not fooled: the extensions-only run is not the folder survey
    view = client.get("/api/filesystems/walkme/folder-survey", headers=headers).json()
    assert view["state"] == "none" and view["extensions"]["led_by"] == "egeria" and view["extensions"]["published"] is True
    assert view["extensions"]["rows"]["kept"] is True


@pytest.mark.usefixtures("signed_in_caller")
def test_beside_egeria_is_refused_where_resource_explorer_leads_and_where_nobody_can_be_named(api, registry, tmp_path):
    client, headers = api
    _register(registry, _tree(tmp_path))
    _probe_row(registry, "re_only")
    r = client.post("/api/filesystems/walkme/walk-extensions", json={}, headers=headers)
    assert r.status_code == 409 and "already measures these" in r.json()["detail"]
    assert registry.list_filesystem_walk_runs("walkme") == []
    assert client.post("/api/filesystems/walkme/walk-extensions/publish", headers=headers).status_code == 409
    assert client.post("/api/filesystems/nope/walk-extensions", json={}, headers=headers).status_code == 404


def test_the_walk_extensions_request_model_is_what_the_screen_posts():
    from resource_explorer.web.routes.filesystems import WalkExtensionsRequest

    assert set(WalkExtensionsRequest.model_fields) == {"publish"}
