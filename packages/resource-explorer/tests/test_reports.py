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

    def test_a_metrics_only_analysis_refuses_to_save_a_report(self, client, registry):
        # A "0 findings" report of repository_health (writes only
        # project_analysis_metrics) would be exactly the false record
        # REPORT-ACTS says must never be made -- the route must 422, not 200
        # with an empty snapshot.
        from resource_explorer.activity_logger import log_analysis_run
        log_analysis_run(registry, "repo", "p", "P repo", "success", "ran", "repository_health")
        registry.upsert_metric("p", "repository_health", {"quality_score": 90})
        r = client.post("/api/projects/p/members/repository_health/report", json={"metric": "quality_score"})
        assert r.status_code == 422, r.text
        assert "not members" in r.json()["detail"]


class TestTheThreeActsOnAReport:
    """REPORT-ACTS (designer, 2026-09-14): an act on a report is an act on
    what WAS true. Server acts on the snapshot; what it creates points at
    the record; staleness is carried, not blocked; the record learns it was
    used; the content stays frozen."""

    def _report(self, client, registry):
        TestTheRoute()._seed(registry)
        return client.post("/api/projects/p/members/cve_scan/report",
                           json={"metric": "advisories", "name": "High advisories with a fix"}).json()["record"]

    def test_add_to_work_list_points_at_the_record_and_names_the_list(self, client, registry):
        from resource_explorer.work_lists import WorkLists
        rec = self._report(client, registry)
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "work_list", "name": "Dependencies to fix before 6.2"})
        assert r.status_code == 200, r.text
        out = r.json()
        assert out["name"] == "Dependencies to fix before 6.2" and out["work_list"]
        wl = WorkLists(registry).get(out["work_list"])
        rationale = next(m for m in wl["members"] if m["entity_slug"] == "p")["rationale"]
        assert rationale.endswith(' · as recorded in "High advisories with a fix"')
        assert rationale.startswith("4 advisories · from cve_scan, run 20")
        assert wl["derived_from"] == f"record:{rec['id']}"
        # the record learned it was used, and its content did not move
        uses = out["record"]["uses"]
        assert uses[0]["act"] == "work_list" and uses[0]["target_name"] == "Dependencies to fix before 6.2" and uses[0]["by"] == "peterprofile"
        assert out["record"]["report"] == rec["report"]

    def test_a_row_subset_acts_on_the_snapshot_not_a_requery(self, client, registry):
        rec = self._report(client, registry)
        # the snapshot is what it is even if the findings change underneath
        registry.upsert_finding("p", "cve_scan", [{"check_name": "x", "label": "low", "summary": "", "detail": {"advisory_ids": ["GHSA-NEW"], "severity": "LOW"}}])
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "rfa", "rows": ["GHSA-1", "GHSA-9", "GHSA-NEW"]})
        assert r.status_code == 200, r.text
        assert r.json()["provenance"].startswith("2 of 4 advisories · from cve_scan")
        assert "GHSA-NEW" not in r.json()["provenance"]

    def test_the_rfa_points_at_the_record(self, client, registry):
        rec = self._report(client, registry)
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "rfa"})
        assert r.status_code == 200 and r.json()["rfa"]
        assert r.json()["record"]["uses"][0]["act"] == "rfa"

    def test_staleness_is_carried_into_what_the_act_creates(self, client, registry):
        from resource_explorer.activity_logger import log_analysis_run
        rec = self._report(client, registry)
        import time; time.sleep(1.1)
        log_analysis_run(registry, "repo", "p", "P repo", "success", "again", "cve_scan")
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "work_list"})
        assert r.status_code == 200
        assert 'as recorded in "High advisories with a fix", whose evidence has since moved — cve_scan re-ran on' in r.json()["provenance"]

    def test_the_journal_act_records_only_the_use(self, client, registry):
        from resource_explorer.journal import Journal
        rec = self._report(client, registry)
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "journal", "journal_id": "e1"})
        assert r.status_code == 200
        assert r.json()["record"]["uses"][0] | {"at": ""} == {"act": "journal", "target": "e1", "target_name": "the journal", "by": "peterprofile", "at": ""}
        assert Journal(registry).entries("repo", "p") == []     # nothing canned was written on anyone's behalf

    def test_anonymous_is_gated_with_a_sentence(self, client, registry, monkeypatch):
        rec = self._report(client, registry)
        monkeypatch.setattr("resource_explorer.auth.get_current_user", lambda request: None)
        r = client.post(f"/api/projects/p/records/{rec['id']}/act", json={"action": "work_list"})
        assert r.status_code == 401 and "someone who raised it" in r.json()["detail"]


class TestTheCorrection:
    def test_a_correction_is_a_new_record_naming_what_it_corrects_and_the_old_one_learns_it(self, client, registry):
        old = TestTheThreeActsOnAReport()._report(client, registry)
        r = client.post("/api/projects/p/members/cve_scan/report",
                        json={"metric": "advisories", "name": "High advisories — corrected", "corrects": old["id"]})
        assert r.status_code == 200, r.text
        new = r.json()["record"]
        assert new["corrects"] == old["id"] and new["report"]["corrects"] == old["id"]
        # the corrected record was the whole list: populations match, no clause
        assert new["report"]["header"] == "4 of 4 advisories — nothing capped."
        listed = {x["id"]: x for x in client.get("/api/projects/p/records").json()["records"]}
        assert listed[old["id"]]["corrected_by"]["id"] == new["id"]
        assert listed[old["id"]]["corrected_by"]["name"] == "High advisories — corrected"
        assert listed[old["id"]]["report"] == old["report"]      # frozen
        bad = client.post("/api/projects/p/members/cve_scan/report", json={"metric": "advisories", "corrects": "nope"})
        assert bad.status_code == 400


    def test_correcting_a_selection_names_what_the_correction_is_not_carrying(self, client, registry):
        TestTheRoute()._seed(registry)
        sel = client.post("/api/projects/p/members/cve_scan/report",
                          json={"metric": "advisories", "members": ["GHSA-1", "GHSA-9"], "facet": "high, fix available",
                                "name": "High advisories with a fix"}).json()["record"]
        new = client.post("/api/projects/p/members/cve_scan/report",
                          json={"metric": "advisories", "corrects": sel["id"]}).json()["record"]
        assert new["report"]["header"] == ('4 of 4 advisories — nothing capped. Corrects "High advisories with a fix", '
                                           'whose selection was high, fix available; this record is the whole list.')
