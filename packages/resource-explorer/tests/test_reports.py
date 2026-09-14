"""The report record (REPORT-RECORD-AND-TWO-CALLS C1-C4, 2026-09-13): one
table, two kinds; the header sentence names the cap; the provenance line
travels; Markdown and CSV are exports of the record; append-only with
out-of-date marking."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.curate_plan import Curations
from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.reports import build_report, header_sentence, out_of_date, to_csv, to_markdown


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    r.add(Project(slug="p", display_name="P repo", github_url="https://github.com/x/p", description=""))
    return r


@pytest.fixture
def client(registry, monkeypatch):
    monkeypatch.setattr("resource_explorer.registry.ProjectRegistry.__init__",
                        lambda self, db_path=None: setattr(self, "__dict__", registry.__dict__) or None)
    monkeypatch.setenv("TRELLIS_ANONYMOUS_READ", "true")
    monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: {"user_id": "peterprofile"})
    from resource_explorer.web.app import app
    return TestClient(app)


PAYLOAD = {"total": 4, "metric": "advisories", "source": "project_analysis_findings", "groups": [
    {"name": "jackson-core 2.12.2", "count": 3, "truncated": False, "members": [
        {"name": "GHSA-1", "detail": "high"}, {"name": "GHSA-2", "detail": "high"}, {"name": "GHSA-3", "detail": "moderate"}]},
    {"name": "guava 30.1", "count": 1, "truncated": False, "members": [{"name": "GHSA-9", "detail": "high"}]},
]}


class TestTheHeaderSentence:
    def test_names_the_cap_in_the_header(self):
        assert header_sentence(total=32, shown=32, noun="dependencies") == "32 of 32 dependencies — nothing capped."
        assert header_sentence(total=1412, shown=200, noun="dependencies") == "200 of 1,412 dependencies — capped by the request."


class TestTheRecordBody:
    def test_the_whole_list_and_a_selection_are_both_snapshots_with_the_line(self):
        whole = build_report(question="list the advisories", slug="p", display_name="P repo", analysis_id="cve_scan",
                             metric="advisories", run_at="2026-09-04T01:14:21", facet="", members_payload=PAYLOAD)
        assert whole["header"] == "4 of 4 advisories — nothing capped."
        assert whole["provenance"] == "4 advisories · from cve_scan, run 2026-09-04: GHSA-1, GHSA-2, GHSA-3, GHSA-9"
        assert [g["name"] for g in whole["groups"]] == ["jackson-core 2.12.2", "guava 30.1"]
        sel = build_report(question="", slug="p", display_name="P repo", analysis_id="cve_scan", metric="advisories",
                           run_at="2026-09-04T01:14:21", facet="high", members_payload=PAYLOAD, selected=["GHSA-1", "GHSA-9"])
        assert sel["header"] == "2 of 2 advisories — nothing capped."
        assert sel["provenance"].startswith("2 advisories · high · from cve_scan, run 2026-09-04: GHSA-1, GHSA-9")
        assert [r["name"] for g in sel["groups"] for r in g["rows"]] == ["GHSA-1", "GHSA-9"]

    def test_a_truncated_group_survives_into_the_record(self):
        p = {**PAYLOAD, "total": 300, "groups": [{**PAYLOAD["groups"][0], "truncated": True}]}
        r = build_report(question="", slug="p", display_name="P", analysis_id="cve_scan", metric="advisories",
                         run_at="", facet="", members_payload=p)
        assert r["groups"][0]["truncated"] is True and r["header"] == "3 of 300 advisories — capped by the request."

    def test_out_of_date_when_the_analysis_re_ran(self):
        rep = {"analysis_id": "cve_scan", "run_at": "2026-09-04T01:14:21"}
        assert out_of_date(rep, "2026-09-04T01:14:21") == ""
        assert out_of_date(rep, "2026-09-12T20:00:00") == "out of date — cve_scan re-ran on 09-12. No correcting record has been written yet."


class TestTheStore:
    def test_a_report_is_a_done_record_with_no_steps_beside_the_catalogue_ones(self, registry):
        c = Curations(registry)
        cat = c.create("repo", "p", author="a", selection={}, manifest={}, steps=["publish_asset"])
        rep = c.create_report("repo", "p", author="peterprofile", name="P — 4 advisories", report={"header": "4 of 4 advisories — nothing capped."})
        assert rep["kind"] == "report" and rep["state"] == "done" and rep["steps"] == [] and rep["finished_at"]
        assert cat["kind"] == "catalogue"
        assert [r["kind"] for r in c.for_resource("repo", "p")] == ["report", "catalogue"]   # newest first, together
        with pytest.raises(ValueError):
            c.create_report("repo", "p", author="", name="x", report={})
        with pytest.raises(ValueError):
            c.create_report("repo", "p", author="a", name="  ", report={})


class TestTheRoute:
    def _seed(self, registry):
        registry.upsert_finding("p", "cve_scan", [
            {"check_name": "java:jackson-core 2.12.2", "label": "high", "summary": "3 advisories",
             "detail": {"advisory_ids": ["GHSA-1", "GHSA-2", "GHSA-3"], "severity": "HIGH"}},
            {"check_name": "java:guava 30.1", "label": "high", "summary": "1 advisory",
             "detail": {"advisory_ids": ["GHSA-9"], "severity": "HIGH"}}])
        from resource_explorer.activity_logger import log_analysis_run
        log_analysis_run(registry, "repo", "p", "P repo", "success", "ran", "cve_scan")

    def test_save_whole_list_then_list_and_export(self, client, registry):
        self._seed(registry)
        r = client.post("/api/projects/p/members/cve_scan/report", json={"question": "list the advisories", "metric": "advisories"})
        assert r.status_code == 200, r.text
        rec = r.json()["record"]
        assert rec["kind"] == "report" and rec["author"] == "peterprofile"
        assert rec["name"].startswith("P repo — 4 advisories, 20")
        assert rec["report"]["header"] == "4 of 4 advisories — nothing capped."
        assert "from cve_scan, run 20" in rec["report"]["provenance"]
        listed = client.get("/api/projects/p/records").json()["records"]
        assert listed[0]["id"] == rec["id"] and listed[0]["out_of_date"] == ""
        md = client.get(f"/api/projects/p/records/{rec['id']}?fmt=md").text
        assert md.startswith(f"# {rec['name']}\n") and "**4 of 4 advisories — nothing capped.**" in md and "a snapshot, not a query" in md
        csv_ = client.get(f"/api/projects/p/records/{rec['id']}?fmt=csv").text
        assert csv_.splitlines()[0] == "# 4 of 4 advisories — nothing capped." and "GHSA-9" in csv_

    def test_a_typed_name_wins_and_a_selection_narrows(self, client, registry):
        self._seed(registry)
        r = client.post("/api/projects/p/members/cve_scan/report",
                        json={"metric": "advisories", "members": ["GHSA-1", "GHSA-9"], "facet": "high", "name": " the two to fix "})
        rec = r.json()["record"]
        assert rec["name"] == "the two to fix"
        assert rec["report"]["shown"] == 2 and rec["report"]["facet"] == "high"

    def test_out_of_date_shows_up_on_the_list_after_a_re_run(self, client, registry):
        self._seed(registry)
        rec = client.post("/api/projects/p/members/cve_scan/report", json={"metric": "advisories"}).json()["record"]
        import time; time.sleep(1.1)
        from resource_explorer.activity_logger import log_analysis_run
        log_analysis_run(registry, "repo", "p", "P repo", "success", "ran again", "cve_scan")
        listed = client.get("/api/projects/p/records").json()["records"]
        assert listed[0]["id"] == rec["id"] and listed[0]["out_of_date"].startswith("out of date — cve_scan re-ran on")

    def test_anonymous_and_empty_are_refused(self, client, registry, monkeypatch):
        self._seed(registry)
        assert client.post("/api/projects/p/members/cve_scan/report", json={"members": ["nope"]}).status_code == 400
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
        assert client.post("/api/projects/p/members/cve_scan/report", json={}).status_code == 401
