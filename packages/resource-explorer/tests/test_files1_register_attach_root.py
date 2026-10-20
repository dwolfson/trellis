"""Files step 1 (2026-10-20): register a file system on /next and attach its root folder as an Egeria asset.

One end-to-end test per write path. Each fakes ONLY the pyegeria client boundary, with `create_autospec(...,
spec_set=True)` so every call binds the real pyegeria signature; RE's route, surveyor, registry and proof rows
run for real. The attached state is read from the proof row, never from the branch the code took.
"""
from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.usefixtures("signed_in_caller")

GUID = "11111111-2222-3333-4444-555555555555"
MISS = "No elements found"      # pyegeria's one real "absent" answer


def _fake(cls):
    from unittest.mock import create_autospec

    return create_autospec(cls, instance=True, spec_set=True)


class _Clients:
    user_id = "test-caller"

    def __init__(self, by_class):
        self.by_class = by_class

    def of(self, cls):
        return self.by_class[cls]


@pytest.fixture()
def _zone_access_open(monkeypatch):
    from tests.zone_fakes import open_access

    return open_access(monkeypatch, caller_if_none="files1-tester")


@pytest.fixture
def reg(tmp_path, monkeypatch):
    from resource_explorer.registry import ProjectRegistry

    r = ProjectRegistry(db_path=str(tmp_path / "files1.db"))
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None, **k: setattr(self, "__dict__", r.__dict__) or None)
    return r


def _headers():
    from resource_explorer.auth import create_access_token

    return {"Authorization": "Bearer " + create_access_token(user_id="files1-tester", egeria_token="tok")}


def _client():
    from resource_explorer.web.app import app

    return TestClient(app)


# ── 1. register: the answer names the row the list will show ─────────────

def test_register_answers_with_the_stored_slug_and_the_list_agrees(reg):
    """A dashed slug is stored with underscores. The register answer must carry the STORED slug, or the sidebar
    cannot select the new row (it matched on the slug the person typed)."""
    c = _client()
    r = c.post("/api/filesystems/", json={
        "slug": "My-Data", "display_name": "My data", "local_mount_point": "/mnt/mydata",
        "canonical_mount_point": "file://nas/mydata", "group_slug": ""}, headers=_headers())
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "my_data"
    listed = c.get("/api/filesystems/", headers=_headers()).json()
    assert [row["slug"] for row in listed] == ["my_data"]
    assert listed[0]["canonical_mount_point"] == "file://nas/mydata"
    # nothing was sent to Egeria by registering, and no GUID is claimed
    assert listed[0]["egeria_asset_guid"] == "" and listed[0]["is_published"] is False


def test_register_a_duplicate_slug_is_refused_even_when_spelt_with_dashes(reg):
    c = _client()
    body = {"slug": "my_data", "display_name": "A", "local_mount_point": "/mnt/a"}
    assert c.post("/api/filesystems/", json=body, headers=_headers()).status_code == 200
    again = c.post("/api/filesystems/", json={**body, "slug": "my-data"}, headers=_headers())
    assert again.status_code == 400
    assert "already registered" in again.json()["detail"]


# ── 2. the mount check: a warning, never a block ─────────────────────────

def test_check_mount_says_what_this_server_can_read(tmp_path, reg):
    c = _client()
    ok = c.post("/api/filesystems/check-mount", json={"path": str(tmp_path)}, headers=_headers()).json()
    assert ok["state"] == "readable"
    missing = c.post("/api/filesystems/check-mount", json={"path": str(tmp_path / "nope")}, headers=_headers()).json()
    assert missing["state"] == "not_readable"
    f = tmp_path / "a.csv"
    f.write_text("a,b\n1,2\n")
    not_dir = c.post("/api/filesystems/check-mount", json={"path": str(f)}, headers=_headers()).json()
    assert not_dir["state"] == "not_a_folder"
    blank = c.post("/api/filesystems/check-mount", json={"path": "  "}, headers=_headers()).json()
    assert blank["state"] == "empty"


# ── 3. attach the root folder: created once, proved by a read-back ───────

def _boundary(monkeypatch, *, lookup=None, read_back=None):
    from pyegeria import AssetMaker, AutomatedCuration
    from pyegeria.omvs.data_discovery import DataDiscovery

    ac, am, dd = _fake(AutomatedCuration), _fake(AssetMaker), _fake(DataDiscovery)
    ac.get_guid_for_name.side_effect = lookup or (lambda name, *a, **k: MISS)
    ac.create_folder_element_from_template.return_value = GUID

    def read(guid, *a, **k):
        return {"elementHeader": {"guid": guid, "type": {"typeName": "FileFolder"}},
                "properties": {"qualifiedName": f"FileFolder::{guid}", "displayName": "NAS data"}}

    am.get_asset_by_guid.side_effect = read_back or read
    monkeypatch.setattr("resource_explorer.egeria_clients.egeria_client",
                        lambda *a, **k: _Clients({AutomatedCuration: ac, AssetMaker: am, DataDiscovery: dd}))
    sent = []
    monkeypatch.setattr("resource_explorer.single_publish.send_with_publish",
                        lambda *a, **k: sent.append(a))
    return ac, am, dd, sent


@pytest.fixture
def fs(reg):
    from resource_explorer.registry import FileSystemEntity

    reg.register_filesystem(FileSystemEntity(slug="nas", display_name="NAS data", local_mount_point="/mnt/nas",
                                             canonical_mount_point="file://nas/data"))
    return reg


@pytest.mark.usefixtures("_zone_access_open")
def test_attach_root_creates_the_folder_once_and_a_second_press_creates_nothing(fs, monkeypatch):
    ac, am, dd, sent = _boundary(monkeypatch)
    c = _client()

    # before any press: nothing attached, and nothing says otherwise
    before = c.get("/api/filesystems/nas/root-folder", headers=_headers()).json()
    assert before["state"] == "not_attached" and before["guid"] == "" and before["read_back_at"] == ""

    r = c.post("/api/filesystems/nas/attach-root", headers=_headers())
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["state"] == "attached" and first["created"] is True and first["guid"] == GUID
    ac.create_folder_element_from_template.assert_called_once()
    kw = ac.create_folder_element_from_template.call_args.kwargs
    assert kw["path_name"] == "file://nas/data" and kw["file_system"] == "nas" and kw["folder_name"] == "NAS data"
    am.get_asset_by_guid.assert_called_once()
    assert am.get_asset_by_guid.call_args.args[0] == GUID            # read back BY GUID

    # the proof row, read from the registry: the GUID Egeria's read-back returned, and when
    proof = fs.latest_filesystem_root_proof("nas")
    assert proof["proof"] == "folder_attached" and proof["element_guid"] == GUID
    assert proof["read_at"] and proof["recorded_by"] == "files1-tester"
    state = c.get("/api/filesystems/nas/root-folder", headers=_headers()).json()
    assert state["state"] == "attached" and state["guid"] == GUID and state["read_back_at"] == proof["read_at"]

    # a second press: the cached element is READ BACK, not looked up by name and not created again
    r2 = c.post("/api/filesystems/nas/attach-root", headers=_headers())
    assert r2.status_code == 200, r2.text
    assert r2.json()["state"] == "attached" and r2.json()["created"] is False and r2.json()["guid"] == GUID
    ac.create_folder_element_from_template.assert_called_once()     # still one folder
    assert ac.create_elem_from_template.call_count == 0              # no data file
    assert am.create_asset.call_count == 0                            # no SurveyReport
    assert dd.create_annotation.call_count == 0                       # no annotation, no relationship
    assert am.get_asset_by_guid.call_count == 2                       # read back again, by GUID
    # the page's other saved items go out with the press, once per press, as the signed-in person
    assert len(sent) == 2 and sent[0][1:4] == ("filesystem", "nas", GUID)


@pytest.mark.usefixtures("_zone_access_open")
def test_attach_root_adopts_a_folder_egeria_already_has_by_name_and_creates_nothing(fs, monkeypatch):
    ac, am, dd, _sent = _boundary(monkeypatch, lookup=lambda name, *a, **k: GUID)
    r = _client().post("/api/filesystems/nas/attach-root", headers=_headers())
    assert r.status_code == 200, r.text
    assert r.json()["created"] is False and r.json()["state"] == "attached"
    ac.create_folder_element_from_template.assert_not_called()
    assert fs.get_filesystem("nas").egeria_asset_guid == GUID


@pytest.mark.usefixtures("_zone_access_open")
def test_a_read_back_that_does_not_match_is_not_attached(fs, monkeypatch):
    other = "99999999-9999-9999-9999-999999999999"
    ac, am, dd, _sent = _boundary(
        monkeypatch, read_back=lambda guid, *a, **k: {"elementHeader": {"guid": other}, "properties": {}})
    c = _client()
    r = c.post("/api/filesystems/nas/attach-root", headers=_headers())
    assert r.status_code == 200, r.text
    assert r.json()["state"] == "not_confirmed"
    proof = fs.latest_filesystem_root_proof("nas")
    assert proof["proof"] != "folder_attached"
    assert c.get("/api/filesystems/nas/root-folder", headers=_headers()).json()["state"] == "not_confirmed"


@pytest.mark.usefixtures("_zone_access_open")
def test_a_lookup_that_could_not_be_made_creates_nothing(fs, monkeypatch):
    from pyegeria.core._exceptions import PyegeriaConnectionException

    def boom(*a, **k):
        raise PyegeriaConnectionException()

    ac, am, dd, _sent = _boundary(monkeypatch, lookup=boom)
    r = _client().post("/api/filesystems/nas/attach-root", headers=_headers())
    assert r.status_code >= 400
    ac.create_folder_element_from_template.assert_not_called()
    assert fs.latest_filesystem_root_proof("nas") is None


def test_the_fakes_bind_the_real_pyegeria_signatures():
    """The calls the attach path makes, bound against the installed pyegeria."""
    from pyegeria import AssetMaker, AutomatedCuration

    inspect.signature(AutomatedCuration.get_guid_for_name).bind(object(), "file://nas/data")
    inspect.signature(AutomatedCuration.create_folder_element_from_template).bind(
        object(), path_name="p", folder_name="f", file_system="s", description="d")
    inspect.signature(AssetMaker.get_asset_by_guid).bind(object(), GUID, body={"class": "GetRequestBody"})


def test_removing_a_file_system_removes_its_proof_rows(fs):
    fs.append_filesystem_root_proof("nas", proof="folder_attached", element_guid=GUID, recorded_by="x")
    assert fs.latest_filesystem_root_proof("nas") is not None
    fs.remove_filesystem("nas")
    assert fs.latest_filesystem_root_proof("nas") is None


def test_the_form_posts_the_routes_own_model_and_no_egeria_field():
    """The keys fs-register.js sends are the route model's fields, and none of them is an Egeria field: those
    come from the platform configuration the server already reads."""
    import re
    from pathlib import Path

    from resource_explorer.web.routes.filesystems import FileSystemRegistration

    src = (Path(__file__).resolve().parents[1] / "resource_explorer/web/static/next/fs-register.js").read_text()
    body = re.search(r"registerFilesystem\(\{(.*?)\}\)", src, re.S).group(1)
    sent = set(re.findall(r"(\w+):", body))
    assert sent == {"slug", "display_name", "local_mount_point", "canonical_mount_point", "group_slug"}
    assert sent <= set(FileSystemRegistration.model_fields)
    assert not [k for k in sent if k.startswith("egeria")]


def test_the_read_back_matches_on_the_shape_egeria_really_returns(fs, monkeypatch):
    """The read-back is parsed from a RECORDED get_asset_by_guid answer (tests/fixtures/egeria_6_2), not from a
    shape this file invented: header guid, properties.qualifiedName and type.typeName."""
    import json
    from pathlib import Path

    rec = json.loads((Path(__file__).parent / "fixtures/egeria_6_2/"
                      "asset_maker_by_guid__database_ownership_anchor_datascope.json").read_text())["answer"]
    guid = rec["elementHeader"]["guid"]
    from resource_explorer.egeria_clients import Caller
    from resource_explorer.surveyors.filesystem.egeria_filesystem_surveyor import EgeriaFileSystemSurveyor
    from pyegeria import AssetMaker

    s = EgeriaFileSystemSurveyor(platform_url="https://localhost:9443", view_server="qs-view-server", identity=Caller())
    s._asset_maker = _fake(AssetMaker)
    s._asset_maker.get_asset_by_guid.return_value = rec
    out = s._read_back_by_guid(guid)
    assert out["matched"] is True
    assert out["qualified_name"] == rec["properties"]["qualifiedName"]
    assert out["type_name"] == "RelationalDatabase"
    assert s._read_back_by_guid("00000000-0000-0000-0000-000000000000")["matched"] is False


@pytest.mark.usefixtures("_zone_access_open")
def test_registering_and_attaching_write_nothing_into_the_registered_path(tmp_path, reg, monkeypatch):
    """Owner's path holds .env files and credentials: check-mount, register and attach-root leave the folder's
    listing and every mtime exactly as they were, and read no file inside it."""
    import os

    tmp_path = tmp_path / "owned"      # the registry's own db sits beside it in the fixture's dir
    tmp_path.mkdir()
    (tmp_path / ".env").write_text("SECRET=1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "a.csv").write_text("a\n1\n")

    def snap():
        return sorted((str(p.relative_to(tmp_path)), p.stat().st_mtime_ns, p.stat().st_size)
                      for p in [tmp_path, *tmp_path.rglob("*")])

    before = snap()
    opened = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda f, *a, **k: (opened.append(str(f)), real_open(f, *a, **k))[1])
    _boundary(monkeypatch)
    c = _client()
    assert c.post("/api/filesystems/check-mount", json={"path": str(tmp_path)}, headers=_headers()).status_code == 200
    assert c.post("/api/filesystems/", json={"slug": "own", "display_name": "Own",
                                             "local_mount_point": str(tmp_path)}, headers=_headers()).status_code == 200
    assert c.post("/api/filesystems/own/attach-root", headers=_headers()).status_code == 200
    assert snap() == before
    assert not [f for f in opened if str(tmp_path) in f]
    assert sorted(os.listdir(tmp_path)) == [".env", "sub"]
