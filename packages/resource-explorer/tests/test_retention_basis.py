"""Retention basis: one list, one reading of a stored field, the body the publish builds, and an error
that keeps Egeria's reason. The ordinals come from Dr.Egeria's code, NOT from a read of this platform."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from resource_explorer import retention_basis as rb
from resource_explorer.curate_plan import Curations
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.workflows import curate_commit as wf

EXPECTED = {"UNCLASSIFIED": 0, "TEMPORARY": 1, "PROJECT_LIFETIME": 2, "TEAM_LIFETIME": 3,
            "CONTRACT_LIFETIME": 4, "REGULATED_LIFETIME": 5, "TIMEBOXED_LIFETIME": 6, "OTHER": 99}


def test_mapping_is_every_value_and_unknown_is_refused():
    assert rb.ORDINALS == EXPECTED
    for name, n in EXPECTED.items():
        assert rb.ordinal(name) == n
    for bad in ("Ongoing", "", "project_lifetime", "ACTIVE"):
        with pytest.raises(ValueError):
            rb.ordinal(bad)


def test_the_page_copy_equals_the_python_list():
    js = Path(rb.__file__).parent / "web/static/next/retention-basis.js"
    rows = re.findall(r"name: '(\w+)', label: '([^']+)', ordinal: (\d+), hint: '([^']+)'", js.read_text())
    assert [(n, l, int(o), h) for n, l, o, h in rows] == list(rb.RETENTION_BASES)


class TestResolve:
    def test_legacy_free_text_reads_as_project_lifetime_and_keeps_its_text_as_the_note(self):
        r = rb.resolve({"value": "Ongoing"})
        assert r == {"basis": "PROJECT_LIFETIME", "note": "Ongoing", "carried": True}
        assert rb.ordinal(r["basis"]) == 2

    def test_new_shape_is_unchanged(self):
        assert rb.resolve({"value": "REGULATED_LIFETIME", "note": "SOX"}) == \
            {"basis": "REGULATED_LIFETIME", "note": "SOX", "carried": False}

    def test_nothing_stored_is_unset_never_defaulted(self):
        assert rb.resolve(None)["basis"] == "" and rb.resolve({})["basis"] == ""
        assert rb.resolve({"value": "", "note": "just a note"}) == {"basis": "", "note": "just a note", "carried": False}


def _enrichment(retention):
    return {"retention": {"author": "dan", "set_at": "2026-10-08T00:00:00+00:00", "kind": "observation", **retention}}


@pytest.mark.parametrize("name,n", sorted(EXPECTED.items()))
def test_body_built_for_each_of_the_eight(name, n):
    (method, label, body), = wf._classification_bodies(_enrichment({"value": name, "note": "why"}))
    assert method == "set_retention_classification"
    assert body["class"] == "NewClassificationRequestBody"
    p = body["properties"]
    assert p["class"] == "RetentionClassificationProperties"
    assert p["retentionBasis"] == n and isinstance(p["retentionBasis"], int)
    assert "status" not in p                      # ISSUE-22: ignored by the server; Dr.Egeria's confirmed path omits it
    assert "why" in p["notes"] and rb.LABELS[name] in label


def test_legacy_value_publishes_ordinal_2_with_text_in_the_notes():
    (_m, _l, body), = wf._classification_bodies(_enrichment({"value": "Ongoing"}))
    assert body["properties"]["retentionBasis"] == 2 and "Ongoing" in body["properties"]["notes"]


def test_no_retention_builds_no_body():
    assert wf._classification_bodies(_enrichment({"value": "", "note": "only a note"})) == []
    assert wf._classification_bodies({}) == []


class _Err(Exception):
    def __init__(self, msg, reason):
        super().__init__(msg)
        self.additional_info = {"reason": reason}


def test_error_text_keeps_egeria_reason_and_scrubs_secrets():
    short, full, reason = wf._exc_text(_Err("CLIENT_ERROR_400", '{"exceptionErrorMessage": "retentionBasis not valid", "x": "password=hunter2"}'))
    assert short == "retentionBasis not valid" and reason == "retentionBasis not valid"
    _s, _f, r2 = wf._exc_text(_Err("boom", "bad request password: hunter2"))
    assert "hunter2" not in r2


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
    return r


def _run(registry, monkeypatch, enrichment, client):
    registry.save_context("repo", "p", {"enrichment": enrichment})
    from resource_explorer import repo_publish
    from resource_explorer.surveyors import survey_snapshot
    monkeypatch.setattr(repo_publish, "resolve_project_context", lambda *a, **k: object())
    monkeypatch.setattr(survey_snapshot, "latest", lambda *a, **k: object())
    monkeypatch.setattr(repo_publish, "publish_snapshot", lambda *a, **k: {
        "ok": True, "asset_guid": "a-1", "read_back": True, "surveyed_at": "2026-10-07", "reused": False,
        "report_guid": "r", "annotation_count": 0})
    monkeypatch.setattr("resource_explorer.egeria_identity.classification_client", lambda *a, **k: client)
    rec = Curations(registry).create("repo", "p", author="dan", selection={}, manifest={}, steps=list(wf.STEPS))
    out = wf.execute_curation(registry, rec["id"])
    return {s["name"]: s for s in out["steps"]}["classifications"]


class Recorder:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail
    def _do(self, kind, guid, body):
        if self.fail == kind:
            raise _Err("PyegeriaClientException CLIENT_ERROR_400", '{"exceptionErrorMessage": "OMAG-400: retentionBasis is not valid"}')
        self.calls.append((kind, guid, body))
    def set_confidentiality_classification(self, g, b): self._do("conf", g, b)
    def set_criticality_classification(self, g, b): self._do("crit", g, b)
    def set_retention_classification(self, g, b): self._do("ret", g, b)


SENS = {"value": "public", "author": "dan", "set_at": "2026-10-08T00:00:00+00:00"}


def test_no_stored_retention_step_is_silent_about_retention(registry, monkeypatch):
    rec = Recorder()
    step = _run(registry, monkeypatch, {"sensitivity": SENS}, rec)
    assert step["state"] == "done" and "Retention" not in step["detail"]


def test_note_only_retention_is_skipped_visibly_not_written_not_failed(registry, monkeypatch):
    rec = Recorder()
    step = _run(registry, monkeypatch, {"sensitivity": SENS, **_enrichment({"value": "", "note": "x"})}, rec)
    assert [c[0] for c in rec.calls] == ["conf"]
    assert step["state"] == "done"
    assert "done: Confidentiality · public" in step["detail"]
    assert "skipped: Retention · skipped · no retention basis picked" in step["detail"]


def test_only_a_skipped_retention_leaves_the_step_skipped(registry, monkeypatch):
    step = _run(registry, monkeypatch, _enrichment({"value": "", "note": "x"}), Recorder())
    assert step["state"] == "skipped" and "no retention basis picked" in step["detail"]


def test_two_landed_one_failed_says_so_per_item_with_the_reason(registry, monkeypatch):
    rec = Recorder(fail="ret")
    step = _run(registry, monkeypatch, {"sensitivity": SENS, **_enrichment({"value": "TEAM_LIFETIME"})}, rec)
    assert step["state"] == "failed"
    assert "done: Confidentiality · public" in step["detail"]
    assert "failed: Retention · Team Lifetime: OMAG-400: retentionBasis is not valid" in step["detail"]
    assert "full text in the log" in step["detail"]
    assert "retentionBasis is not valid" in step["more"]
    assert rec.calls[0][0] == "conf"


def test_the_reason_is_logged_in_full(registry, monkeypatch, caplog):
    import logging
    with caplog.at_level(logging.WARNING):
        _run(registry, monkeypatch, _enrichment({"value": "TEAM_LIFETIME"}), Recorder(fail="ret"))
    assert any("egeria reason: OMAG-400: retentionBasis is not valid" in r.getMessage() for r in caplog.records)


def test_a_confidentiality_failure_gets_the_same_treatment(registry, monkeypatch):
    step = _run(registry, monkeypatch, {"sensitivity": SENS}, Recorder(fail="conf"))
    assert step["state"] == "failed" and "retentionBasis is not valid" in step["detail"]


class TestTheSaveRoute:
    @pytest.fixture
    def client(self, registry, monkeypatch):
        from fastapi.testclient import TestClient
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
        monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
        monkeypatch.setattr("resource_explorer.web.routes.context.get_current_user", lambda request: {"user_id": "dan"})
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_value_and_note_are_stored_together_without_a_new_column(self, client, registry):
        r = client.patch("/api/context/repo/p/field", json={"key": "retention", "value": "TEAM_LIFETIME",
                                                              "note": "per charter", "kind": "observation"})
        assert r.status_code == 200, r.text
        f = registry.get_context("repo", "p")["enrichment"]["retention"]
        assert f["value"] == "TEAM_LIFETIME" and f["note"] == "per charter"

    def test_a_free_text_retention_value_is_refused_with_the_list(self, client):
        r = client.patch("/api/context/repo/p/field", json={"key": "retention", "value": "Ongoing", "kind": "observation"})
        assert r.status_code == 422 and "PROJECT_LIFETIME" in r.text


# ── secret scrubbing: by shape, before truncation, on every path ───────────────────────────────────
from resource_explorer.secret_redaction import scrub_text  # noqa: E402

SECRETS = [
    ("Authorization: Bearer abc123def", "abc123def"),
    ('{"password": "a b c"}', "b c"),
    ('{"password": "a b c"}', "a b"),
    ("api_key=ZZtop99", "ZZtop99"),
    ("apikey: ZZtop99", "ZZtop99"),
    ("pwd=hunter2 next", "hunter2"),
    ("postgresql://u:pw0rd@h:5432/db", "pw0rd"),
    ("token=tok_123&x=1", "tok_123"),
    ('escaped \\"password\\": \\"a b c\\" end', "b c"),
    ("bearer eyJhbGciOi.payload.sig", "eyJhbGciOi"),
]


@pytest.mark.parametrize("text,secret", SECRETS)
def test_scrub_text_masks_by_shape(text, secret):
    assert secret not in scrub_text(text)


def test_scrub_keeps_the_rest_readable():
    out = scrub_text("Authorization: Bearer abc123def failed for user u")
    assert "abc123def" not in out and out.endswith("failed for user u") and "Authorization" in out
    assert scrub_text("retentionBasis is not valid") == "retentionBasis is not valid"


def test_scrub_happens_before_truncation():
    reason = "x" * 175 + " postgresql://user:SECRETSECRETSECRET@host/db"
    short, _full, _r = wf._exc_text(_Err("boom", reason))
    assert "SECRET" not in short and len(short) <= 200


@pytest.mark.parametrize("text,secret", SECRETS[:4] + SECRETS[6:7])
def test_scrub_runs_on_every_path_that_stores_or_logs_the_text(registry, monkeypatch, caplog, text, secret):
    import logging

    class Leaky(Recorder):
        def set_retention_classification(self, g, b):
            raise _Err("CLIENT_ERROR_400 " + text, text)

    with caplog.at_level(logging.WARNING):
        step = _run(registry, monkeypatch, _enrichment({"value": "TEAM_LIFETIME"}), Leaky())
    assert step["state"] == "failed"
    assert secret not in step["detail"] and secret not in step["more"]
    assert all(secret not in r.getMessage() for r in caplog.records)
    # the HTTP response is the stored record read back
    from fastapi.testclient import TestClient
    cid = Curations(registry).for_resource("repo", "p")[0]["id"]
    if cid:
        from resource_explorer.web.app import app
        monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                            lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
        monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
        r = TestClient(app).get(f"/api/projects/p/curate/commits/{cid}")
        assert r.status_code == 200 and secret not in r.text


# ── legacy forms ────────────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("stored,basis", [
    ("Temporary", "TEMPORARY"), ("temporary", "TEMPORARY"),
    ("Time Boxed Lifetime", "TIMEBOXED_LIFETIME"), ("time boxed lifetime", "TIMEBOXED_LIFETIME"),
    ("1", "TEMPORARY"), ("99", "OTHER"), (" 0 ", "UNCLASSIFIED"), ("Regulated Lifetime", "REGULATED_LIFETIME"),
    ("Ongoing", "PROJECT_LIFETIME"), ("7", "PROJECT_LIFETIME"), ("forever and a day", "PROJECT_LIFETIME"),
])
def test_old_values_that_name_a_basis_get_that_basis_others_get_project_lifetime(stored, basis):
    r = rb.resolve({"value": stored})
    assert r["basis"] == basis and r["note"] == stored.strip() and r["carried"] is True
    (_m, _l, body), = wf._classification_bodies(_enrichment({"value": stored}))
    assert body["properties"]["retentionBasis"] == rb.ORDINALS[basis]


def test_the_page_resolves_the_same_forms_as_python(tmp_path):
    import json
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    js = tmp_path / "rb.mjs"
    js.write_text((Path(rb.__file__).parent / "web/static/next/retention-basis.js").read_text())
    cases = [s for s, _b in [("Temporary", 0), ("temporary", 0), ("Time Boxed Lifetime", 0), ("1", 0), ("99", 0), (" 0 ", 0),
                             ("Ongoing", 0), ("7", 0), ("TEAM_LIFETIME", 0), ("  TEMPORARY  ", 0), ("", 0)]]
    prog = (f"import('{js.as_uri()}').then(m => console.log(JSON.stringify({json.dumps(cases)}.map(v => m.resolveRetention({{value: v}})))))")
    out = subprocess.run([node, "-e", prog], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout) == [rb.resolve({"value": v}) for v in cases]


# ── LOW items ───────────────────────────────────────────────────────────────────────────────────────
def test_notes_are_the_retention_text_and_class_and_basis_cannot_be_overridden():
    (_m, _l, body), = wf._classification_bodies(_enrichment({"value": "TEAM_LIFETIME", "note": "per charter"}))
    p = body["properties"]
    assert p["notes"].startswith("Team Lifetime — per charter — set by dan on 2026-10-08")
    assert p["class"] == "RetentionClassificationProperties" and p["retentionBasis"] == 3
    assert p["steward"] == "dan"


class TestThePlanPreviewsTheSkip:
    def _plan(self, registry, enrichment):
        from resource_explorer.curate_plan import build_plan
        registry.save_context("repo", "p", {"enrichment": enrichment})
        return {c["key"]: c for c in build_plan(registry, "p")["writes"]["classifications"]}

    def test_a_note_without_a_basis_is_shown_as_skipped(self, registry):
        c = self._plan(registry, _enrichment({"value": "", "note": "x"}))["retention"]
        assert c["skipped"] is True and c["value"] == "skipped · no retention basis picked"

    def test_a_basis_is_shown_as_a_write(self, registry):
        c = self._plan(registry, _enrichment({"value": "TEAM_LIFETIME"}))["retention"]
        assert c["skipped"] is False and c["value"] == "Team Lifetime"

    def test_nothing_stored_adds_no_row(self, registry):
        assert "retention" not in self._plan(registry, {"sensitivity": SENS})
