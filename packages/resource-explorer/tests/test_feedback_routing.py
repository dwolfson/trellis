"""Closed-loop step 2a: a saved diagnosis is routed to its one consumer, a gap (BRIEF-CLOSED-LOOP-STEP2-ROUTING.md).

The owner's rules under test: route on Save; one route per (item, cause); a re-diagnosis leaves the earlier route;
a failed route never fails the diagnosis; the admin picks one charged analysis; the asker's id never reaches a gap.
And the architect's A1 (gap counts sum to the total) and A2 (a deleted item is said to be deleted).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from resource_explorer.web.app import app


def manifest(**kw) -> dict:
    base = {"coverage": {"kind": "analysis", "question": "Which dependencies does it use?", "note": ""},
            "packed": [], "gaps": [], "dropped": [], "deferred": [], "declared": {}}
    base.update(kw)
    return base


ABSENT = manifest(gaps=[{"key": "cve_scan", "state": "never_run", "reason": "has not run"}],
                  packed=[{"key": "deps", "rung": "FULL"}])


@pytest.fixture
def feedback_store(tmp_path):
    from resource_explorer.feedback_store import FeedbackStore
    return FeedbackStore(db_path=str(tmp_path / "route_feedback.db"))


@pytest.fixture
def client(monkeypatch, feedback_store, tmp_path):
    monkeypatch.setenv("REGISTRY_DATABASE_URL", f"sqlite:///{tmp_path}/registry.db")
    import resource_explorer.config as _config_module
    _config_module._config = None
    monkeypatch.setattr(
        "resource_explorer.feedback_store.FeedbackStore.__init__",
        lambda self, db_path=None: setattr(self, "__dict__", feedback_store.__dict__) or None,
    )
    return TestClient(app)


@pytest.fixture
def admin_headers(monkeypatch):
    from resource_explorer import config as cfg_mod
    monkeypatch.setattr(cfg_mod.get_config().feedback, "admin_token", "test-token", raising=False)
    return {"X-Admin-Token": "test-token"}


@pytest.fixture
def reg(client):
    from resource_explorer.registry import Project, ProjectRegistry
    r = ProjectRegistry()
    r.add(Project(slug="r1", display_name="r1", github_url="https://github.com/x/r1"))
    return r


def _compile(reg, compile_id: str, m: dict) -> None:
    reg.record_compile(compile_id, "r1", "what does it use?", {**m, "text": "## deps\nrequests"}, [])


def _answer(store, *, slug="r1", compile_id="c1", question="what does it use?", user="peterprofile", **kw):
    item_id, _ = store.add_answer(vote=-1, question=question, compile_id=compile_id, slug=slug,
                                  entity_type="repo" if slug else "", user_id=user, **kw)
    return item_id


def _save(client, headers, item_id, cause, **kw):
    return client.patch(f"/api/feedback/{item_id}", headers=headers,
                        json={"triage_status": "triaged", "cause": cause, **kw})


class TestRouteOnSave:
    def test_missing_evidence_raises_a_gap_on_the_first_charged_analysis(self, client, reg, feedback_store,
                                                                         admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        out = _save(client, admin_headers, item_id, "missing_evidence")
        assert out.status_code == 200, out.text
        route = out.json()["route"]
        assert route["state"] == "routed" and route["consumer"] == "gap"
        gap = reg.get_gap(int(route["target"]))
        assert (gap["analysis_id"], gap["gap_kind"]) == ("cve_scan", "missing_evidence")
        assert "“what does it use?”" in gap["sentence"]          # Q8: the question as asked
        assert gap["evidence"]["feedback_items"] == [item_id] and gap["evidence"]["role"] == "absent"

    def test_the_admin_picks_another_charged_analysis(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        route = _save(client, admin_headers, _answer(feedback_store), "analysis_defect",
                      analysis_id="deps").json()["route"]
        gap = reg.get_gap(int(route["target"]))
        assert (gap["analysis_id"], gap["gap_kind"]) == ("deps", "analysis_defect")

    def test_an_analysis_outside_the_charge_set_is_refused_before_anything_is_written(
            self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        bad = _save(client, admin_headers, item_id, "missing_evidence", analysis_id="stars")
        assert bad.status_code == 400 and "not in this answer's charge set" in bad.json()["detail"]
        assert feedback_store.get(item_id)["triage"]["cause"] == ""          # no diagnosis written
        assert reg.list_feedback_routes([item_id]) == {}

    def test_the_asker_id_never_reaches_the_gap(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        route = _save(client, admin_headers, _answer(feedback_store, user="peterprofile"),
                      "missing_evidence").json()["route"]
        assert "peterprofile" not in repr(reg.get_gap(int(route["target"])))

    def test_a_catalog_gap_is_a_gap_on_no_analysis(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", manifest(coverage={"kind": "none", "question": "", "note": ""}))
        route = _save(client, admin_headers, _answer(feedback_store), "catalog_gap").json()["route"]
        gap = reg.get_gap(int(route["target"]))
        assert (gap["analysis_id"], gap["gap_kind"]) == ("", "catalog_gap")


class TestWhatRoutesNothing:
    @pytest.mark.parametrize("cause", ["wrong_evidence", "over_compressed", "reasoning", "not_an_issue"])
    def test_causes_without_a_step_2_consumer_route_nothing(self, client, reg, feedback_store, admin_headers,
                                                             cause):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        status = "not_an_issue" if cause == "not_an_issue" else "triaged"
        out = client.patch(f"/api/feedback/{item_id}", headers=admin_headers,
                           json={"triage_status": status, "cause": cause})
        assert out.status_code == 200, out.text
        assert out.json()["route"]["state"] == "skipped"
        assert reg.list_feedback_routes([item_id]) == {} and reg.list_gaps("r1") == []

    @pytest.mark.parametrize("cause", ["unclear_question", "stale"])
    def test_later_steps_are_said_and_not_claimed(self, client, reg, feedback_store, admin_headers, cause):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        route = _save(client, admin_headers, item_id, cause).json()["route"]
        assert route["state"] == "skipped" and "Not routed yet" in route["words"]
        assert reg.list_feedback_routes([item_id]) == {}                  # left for 2b / 2c to route

    def test_a_status_change_alone_routes_nothing(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        out = client.patch(f"/api/feedback/{item_id}", headers=admin_headers, json={"triage_status": "triaged"})
        assert "route" not in out.json() and reg.list_gaps("r1") == []

    def test_the_secondary_cause_never_routes(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        _save(client, admin_headers, item_id, "reasoning", secondary_cause="missing_evidence")
        assert reg.list_gaps("r1") == []


class TestOnceAndAgain:
    def test_saving_the_same_cause_twice_routes_once(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        first = _save(client, admin_headers, item_id, "missing_evidence").json()["route"]
        client.patch(f"/api/feedback/{item_id}", headers=admin_headers,
                     json={"triage_status": "triaged", "cause": "reasoning"})
        again = _save(client, admin_headers, item_id, "missing_evidence").json()["route"]
        assert again["state"] == "already" and again["target"] == first["target"]
        assert len(reg.list_gaps("r1")) == 1

    def test_a_re_diagnosis_routes_the_new_cause_and_leaves_the_old_route(self, client, reg, feedback_store,
                                                                         admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        first = _save(client, admin_headers, item_id, "missing_evidence").json()["route"]
        second = _save(client, admin_headers, item_id, "analysis_defect").json()["route"]
        assert second["state"] == "routed" and second["target"] != first["target"]
        assert reg.get_gap(int(first["target"]))["resolved_at"] is None
        routes = client.get(f"/api/feedback/{item_id}", headers=admin_headers).json()["routes"]
        assert [r["cause"] for r in routes] == ["missing_evidence", "analysis_defect"]

    def test_routing_back_to_a_resolved_route_says_so(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        first = _save(client, admin_headers, item_id, "missing_evidence").json()["route"]
        with reg._conn() as c:
            c.execute("UPDATE analysis_gaps SET resolved_at = '2026-11-10T00:00:00' WHERE id = ?",
                      (int(first["target"]),))
        _save(client, admin_headers, item_id, "reasoning")
        again = _save(client, admin_headers, item_id, "missing_evidence").json()["route"]
        assert again["state"] == "already" and again["words"].endswith(", resolved.")

    def test_two_answers_on_one_question_make_one_gap_listing_both(self, client, reg, feedback_store,
                                                                    admin_headers):
        _compile(reg, "c1", ABSENT)
        a, b = _answer(feedback_store), _answer(feedback_store, user="erinoverview")
        ra = _save(client, admin_headers, a, "missing_evidence").json()["route"]
        rb = _save(client, admin_headers, b, "missing_evidence").json()["route"]
        assert ra["target"] == rb["target"]
        assert reg.get_gap(int(ra["target"]))["evidence"]["feedback_items"] == [a, b]

    def test_the_claim_is_taken_once(self, reg):
        assert reg.claim_feedback_route("i1", "missing_evidence", "admin") is True
        assert reg.claim_feedback_route("i1", "missing_evidence", "admin") is False


class TestAFailedRouteNeverFailsTheDiagnosis:
    def test_no_resource_is_recorded_as_not_routed(self, client, reg, feedback_store, admin_headers):
        item_id = _answer(feedback_store, slug="", compile_id="")
        out = _save(client, admin_headers, item_id, "missing_evidence")
        assert out.status_code == 200 and out.json()["triage"]["cause"] == "missing_evidence"
        route = out.json()["route"]
        assert route["state"] == "not_routed" and "no resource in scope" in route["words"]

    def test_no_compile_says_nothing_to_charge(self, client, reg, feedback_store, admin_headers):
        route = _save(client, admin_headers, _answer(feedback_store, compile_id=""),
                      "missing_evidence").json()["route"]
        assert route["state"] == "not_routed" and "nothing to charge" in route["words"]

    def test_a_resource_that_cannot_hold_gaps_is_not_routed_with_why(self, client, reg, feedback_store,
                                                                     admin_headers):
        # Gaps are keyed to the projects table: a slug it does not hold (today, any non-repository) cannot hold one.
        reg.record_compile("c9", "db1", "q?", {**ABSENT, "text": ""}, [])
        route = _save(client, admin_headers, _answer(feedback_store, slug="db1", compile_id="c9"),
                      "missing_evidence").json()["route"]
        assert route["state"] == "not_routed" and "no gap could be raised" in route["words"]

    def test_a_passing_failure_is_released_so_the_next_save_retries(self, client, reg, feedback_store,
                                                                    admin_headers, monkeypatch):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        from resource_explorer import feedback_routing

        def broken(*a, **kw):
            raise RuntimeError("registry unavailable")
        with monkeypatch.context() as m:           # scoped: undo() would also undo the fixtures' patches
            m.setattr(feedback_routing, "_raise_gap", broken)
            out = _save(client, admin_headers, item_id, "missing_evidence")
        assert out.status_code == 200 and out.json()["route"]["state"] == "failed"
        assert reg.list_feedback_routes([item_id]) == {}
        _save(client, admin_headers, item_id, "reasoning")
        assert _save(client, admin_headers, item_id, "missing_evidence").json()["route"]["state"] == "routed"


class TestTheChecklistDisagreement:
    def test_both_gaps_stay_and_link_both_ways(self, client, reg, feedback_store, admin_headers):
        from resource_explorer.gaps import record_disagreement
        _compile(reg, "c1", ABSENT)
        disputed = record_disagreement(reg, "r1", "what does it use?", "cve_scan")
        [d_row] = [g for g in reg.list_gaps("r1") if g["gap_kind"] == "disagreement"]
        route = _save(client, admin_headers, _answer(feedback_store), "missing_evidence").json()["route"]
        diagnosed = reg.get_gap(int(route["target"]))
        assert diagnosed["evidence"]["disagreement_gap"] == d_row["id"]
        assert reg.get_gap(d_row["id"])["evidence"]["diagnosed_as"] == [diagnosed["id"]]
        assert reg.get_gap(d_row["id"])["last_seen_at"] == d_row["last_seen_at"]   # linking is not a sighting
        assert disputed["gap_kind"] == "disagreement"


class TestGapsSummary:
    def test_buckets_sum_to_the_total_and_disputed_counts_disagreements_only(self, client, reg, feedback_store,
                                                                             admin_headers):
        from resource_explorer.gaps import GAP_KINDS, gaps_summary, record_disagreement
        _compile(reg, "c1", ABSENT)
        record_disagreement(reg, "r1", "what does it use?", "cve_scan")
        _save(client, admin_headers, _answer(feedback_store), "missing_evidence")
        _save(client, admin_headers, _answer(feedback_store, question="other?"), "catalog_gap")
        counts = gaps_summary(reg, "r1")["counts"]
        assert sum(counts[k] for k in GAP_KINDS) == counts["total"] == 3
        assert counts["disputed_by_a_person"] == 1                         # the disagreement, not the diagnoses

    def test_a_deleted_item_is_said_to_be_deleted(self, client, reg, feedback_store, admin_headers):
        from resource_explorer.gaps import gaps_summary
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        _save(client, admin_headers, item_id, "missing_evidence")
        feedback_store.store.delete_item(item_id)
        reg.delete_feedback_routes(item_id)
        [gap] = gaps_summary(reg, "r1")["gaps"]
        assert gap["evidence"]["feedback_items_deleted"] == [item_id]


def test_re_offers_no_way_to_delete_an_answer_item_yet():
    """A2: deleting an item must also delete its routes (`registry.delete_feedback_routes`). RE has no delete path
    for library items today. If one is added to FeedbackStore, this fails so the route cleanup goes with it."""
    from resource_explorer.feedback_store import FeedbackStore
    deleters = [n for n in dir(FeedbackStore) if "delete" in n and "event" not in n and not n.startswith("_")]
    assert deleters == [], f"{deleters}: make it call registry.delete_feedback_routes, then update this test"


class TestTheAdminListingCarriesRoutes:
    def test_each_answer_row_lists_its_routes(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        item_id = _answer(feedback_store)
        _save(client, admin_headers, item_id, "missing_evidence")
        rows = client.get("/api/curate/feedback?source=answer", headers=admin_headers).json()["feedback"]
        [row] = [r for r in rows if r["id"] == item_id]
        assert row["routes"][0]["consumer"] == "gap" and row["routes"][0]["words"].startswith("Routed: gap #")


def test_the_claim_is_taken_once_on_postgres(pg_registry):
    """The route's lock is `INSERT ... ON CONFLICT (item_id, cause) DO NOTHING` and its row count: checked on the
    real dialect, where the shared registry runs."""
    assert pg_registry.claim_feedback_route("pg-i1", "missing_evidence", "admin") is True
    assert pg_registry.claim_feedback_route("pg-i1", "missing_evidence", "admin") is False
    pg_registry.finish_feedback_route("pg-i1", "missing_evidence", "none", reason="no resource in scope")
    assert pg_registry.list_feedback_routes(["pg-i1"])["pg-i1"][0]["reason"] == "no resource in scope"
    assert pg_registry.delete_feedback_routes("pg-i1") == 1


class TestRaisingAnRfaForADiagnosedGap:
    """projects.py's gap→RFA route knew only the two measured kinds; a diagnosed gap reads as what it is."""

    def _rfa_detail(self, reg, rfa_id):
        with reg._conn() as c:
            rows = c.execute("SELECT detail, annotations_json FROM activity_log WHERE id = ?", (rfa_id,)).fetchall()
        return " ".join(str(r["detail"]) + str(r["annotations_json"]) for r in rows)

    def test_a_catalog_gap_names_the_question_catalog(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", manifest(coverage={"kind": "none", "question": "", "note": ""}))
        gap_id = int(_save(client, admin_headers, _answer(feedback_store), "catalog_gap").json()["route"]["target"])
        out = client.post(f"/api/projects/r1/gaps/{gap_id}/rfa")
        assert out.status_code == 200, out.text
        detail = self._rfa_detail(reg, out.json()["rfa"])
        assert "a question nothing in the catalog answers, in the question catalog" in detail
        assert "'' analysis" not in detail

    def test_a_missing_evidence_gap_names_its_analysis(self, client, reg, feedback_store, admin_headers):
        _compile(reg, "c1", ABSENT)
        gap_id = int(_save(client, admin_headers, _answer(feedback_store), "missing_evidence").json()["route"]["target"])
        detail = self._rfa_detail(reg, client.post(f"/api/projects/r1/gaps/{gap_id}/rfa").json()["rfa"])
        assert "missing this analysis's result, in the 'cve_scan' analysis" in detail
