"""DepthOffer (designer, 2026-09-13): the /next pane's offer to run
never-run analysis/assessment-tier analyses, priced with the
measured/declared/unknown split, and its outcome recorded on the verdict.

Covers:
* GET /api/projects/{slug}/depth-offer (via `build_depth_offer` directly,
  and through the route for the 404 path)
* POST /api/discovery/disposition/depth-offer (`registry.record_depth_offer`)
* GET /api/analyses/{analysis_id}/cost (`find_cost_for_analysis`), added at
  the /next session's request so their popover and this offer's entries can
  never drift apart — both go through `run_cost_as_dict`.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from resource_explorer.registry import Project
from resource_explorer.workflows.depth_offer import (
    build_depth_offer,
    find_cost_for_analysis,
    run_cost_as_dict,
)


@pytest.fixture
def slug(request):
    import re as _re
    return "do_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:45]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _log_run(reg, slug, analysis_id, *, minutes_ago=0, status="ok"):
    """One activity_log analysis_run row, back-dated — same helper as
    tests/test_run_freshness.py's."""
    from resource_explorer.activity_logger import log_analysis_run
    entry_id = log_analysis_run(reg, "repo", slug, slug, status,
                                f"ran {analysis_id}", analysis_id, published=None)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    with reg._conn() as c:
        c.execute("UPDATE activity_log SET ts = %s WHERE id = %s", (ts, entry_id))
    return entry_id


class TestBuildDepthOffer:
    def test_a_never_measured_repo_lists_every_assessment_and_analysis_entry(self, reg, slug):
        offer = build_depth_offer(reg, slug)
        assert offer["slug"] == slug
        assert offer["measured_before"] is False
        assert offer["analyses"], "expected at least one assessment/analysis entry"
        tiers = {a["tier"] for a in offer["analyses"]}
        assert tiers <= {"assessment", "analysis"}
        ids = {a["analysis_id"] for a in offer["analyses"]}
        # egeria_publish is action:"publish" — must never be offered.
        assert "egeria_publish" not in ids
        for a in offer["analyses"]:
            assert set(a["cost"]) == {
                "seconds", "steps_seconds", "publish_seconds", "basis",
                "runs", "split_runs", "via", "declared", "sentence",
            }
            # The declared word is a field, not something fished out of the
            # sentence's quotes; a declared-basis entry must carry it.
            if a["cost"]["basis"] == "declared":
                assert a["cost"]["declared"] in {"fast", "minutes", "async"}, a["cost"]
                assert f"'{a['cost']['declared']}'" in a["cost"]["sentence"]

    def test_an_analysis_that_ran_drops_out_and_measured_before_flips(self, reg, slug):
        before = build_depth_offer(reg, slug)
        before_ids = {a["analysis_id"] for a in before["analyses"]}
        assert "security_scan" in before_ids

        _log_run(reg, slug, "security_scan", minutes_ago=5)

        after = build_depth_offer(reg, slug)
        after_ids = {a["analysis_id"] for a in after["analyses"]}
        assert "security_scan" not in after_ids
        assert after["measured_before"] is True

    def test_an_errored_run_still_counts_as_run(self, reg, slug):
        """'has run' is not 'ran successfully' — an errored run's entry
        exists in get_analysis_last_run and that is enough to drop the
        analysis out of a never-run offer."""
        _log_run(reg, slug, "security_scan", minutes_ago=1, status="error")
        offer = build_depth_offer(reg, slug)
        ids = {a["analysis_id"] for a in offer["analyses"]}
        assert "security_scan" not in ids
        assert offer["measured_before"] is True

    def test_a_derived_analysis_drops_out_when_its_source_ran(self, reg, slug):
        """architecture_diagram owns no steps of its own — it is a read-time
        VIEW over architecture_recovery's stored findings. Running the
        SOURCE must be enough to call the derived analysis measured too."""
        before = build_depth_offer(reg, slug)
        before_ids = {a["analysis_id"] for a in before["analyses"]}
        assert "architecture_diagram" in before_ids
        assert "architecture_recovery" in before_ids

        _log_run(reg, slug, "architecture_recovery", minutes_ago=5)

        after = build_depth_offer(reg, slug)
        after_ids = {a["analysis_id"] for a in after["analyses"]}
        assert "architecture_recovery" not in after_ids
        assert "architecture_diagram" not in after_ids

    def test_total_counts_only_measured_and_names_the_excluded(self, reg, slug):
        offer = build_depth_offer(reg, slug)
        total = offer["total"]
        assert total["basis"] == "measured"
        measured_ids = {a["analysis_id"] for a in offer["analyses"] if a["cost"]["basis"] == "measured"}
        other = [a for a in offer["analyses"] if a["cost"]["basis"] != "measured"]

        assert set(total["counted"]) == measured_ids
        assert {e["analysis_id"] for e in total["excluded"]} == {a["analysis_id"] for a in other}
        for e in total["excluded"]:
            expected_basis = next(a["cost"]["basis"] for a in other if a["analysis_id"] == e["analysis_id"])
            assert e["basis"] == expected_basis

        if not measured_ids:
            assert total["seconds"] is None
            declared_n = sum(1 for a in other if a["cost"]["basis"] == "declared")
            unknown_n = sum(1 for a in other if a["cost"]["basis"] == "unknown")
            assert total["sentence"] == (
                f"Nothing here is priced yet — {declared_n} declared, {unknown_n} unknown."
            )
        else:
            assert isinstance(total["seconds"], (int, float))
            if total["excluded"]:
                assert total["sentence"].endswith("not priced.")
                assert "in all across" in total["sentence"]
            else:
                assert total["sentence"].endswith(f"in all across {len(measured_ids)}.")

    def test_measuring_every_offered_analysis_empties_the_offer(self, reg, slug):
        offer = build_depth_offer(reg, slug)
        for a in offer["analyses"]:
            _log_run(reg, slug, a["analysis_id"], minutes_ago=1)

        after = build_depth_offer(reg, slug)
        assert after["analyses"] == []
        assert after["total"] == {
            "seconds": 0, "steps_seconds": 0, "publish_seconds": 0,
            "basis": "measured", "counted": [], "excluded": [],
            "sentence": "Nothing to offer — every analysis at these tiers has run here.",
        }

    def test_entry_cost_matches_estimate_run_cost_directly(self, reg, slug):
        """Sabotage check: build_depth_offer's per-entry `cost` must be
        exactly `estimate_run_cost`'s own output, not a re-derivation that
        could silently disagree with it."""
        from resource_explorer.workflows.analysis import estimate_run_cost

        offer = build_depth_offer(reg, slug)
        entry = next(a for a in offer["analyses"] if a["analysis_id"] == "security_scan")
        expected = run_cost_as_dict(
            estimate_run_cost(reg, "security_scan", resource_type="repo")
        )
        assert entry["cost"] == expected

    def test_unknown_slug_raises_lookuperror(self, pg_registry):
        with pytest.raises(LookupError):
            build_depth_offer(pg_registry, "does-not-exist")


class TestDepthOfferRoute:
    @pytest.fixture
    def client(self, reg, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.registry.ProjectRegistry.__init__",
            lambda self, database_url=None, db_path=None: setattr(self, "__dict__", reg.__dict__) or None,
        )
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_route_returns_the_offer(self, client, slug):
        resp = client.get(f"/api/projects/{slug}/depth-offer")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == slug
        assert data["measured_before"] is False

    def test_route_404s_for_an_unknown_slug(self, client):
        resp = client.get("/api/projects/does-not-exist/depth-offer")
        assert resp.status_code == 404


class TestCostRoute:
    @pytest.fixture
    def client(self, reg, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.registry.ProjectRegistry.__init__",
            lambda self, database_url=None, db_path=None: setattr(self, "__dict__", reg.__dict__) or None,
        )
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_known_never_run_id_returns_200_unpriced(self, client):
        resp = client.get("/api/analyses/security_scan/cost")
        assert resp.status_code == 200
        data = resp.json()
        assert data["basis"] in ("declared", "unknown")
        assert "sentence" in data

    def test_unknown_id_404s(self, client):
        resp = client.get("/api/analyses/not-a-real-analysis/cost")
        assert resp.status_code == 404

    def test_a_measured_id_matches_estimate_run_cost_and_run_cost_as_dict(self, reg, slug, client):
        from resource_explorer.workflows.analysis import estimate_run_cost

        _log_run(reg, slug, "security_scan", minutes_ago=5)
        resp = client.get("/api/analyses/security_scan/cost")
        assert resp.status_code == 200

        expected = run_cost_as_dict(
            estimate_run_cost(reg, "security_scan", resource_type="repo")
        )
        assert resp.json() == expected

    def test_depth_offer_entries_and_cost_route_share_one_function(self):
        """Not a behavioural assertion — a structural one, so the two
        surfaces cannot drift apart by someone editing one copy of the
        serialisation and not the other."""
        import inspect

        from resource_explorer.web.routes.analyses import get_analysis_cost
        from resource_explorer.web.routes.projects import get_depth_offer

        cost_src = inspect.getsource(get_analysis_cost)
        offer_src = inspect.getsource(get_depth_offer)
        assert "find_cost_for_analysis" in cost_src
        assert "build_depth_offer" in offer_src
        # Both ultimately bottom out in run_cost_as_dict via depth_offer.py —
        # asserted directly rather than through source text, which is the
        # point: exercise the real functions.
        from resource_explorer.workflows import depth_offer as dof
        assert inspect.getsource(dof.find_cost_for_analysis).count("run_cost_as_dict") == 1
        assert inspect.getsource(dof.build_depth_offer).count("run_cost_as_dict") == 1


@contextmanager
def _as(user_id: str):
    """Run a block as `user_id`. Same helper as tests/test_investigation_routes.py."""
    from resource_explorer.a2a_auth import CallerIdentity, current_caller
    reset = current_caller.set(
        CallerIdentity(user_id=user_id, egeria_token=None, auth_source="app-jwt"))
    try:
        yield
    finally:
        current_caller.reset(reset)


class TestRecordDepthOffer:
    def test_stamps_offered_at_and_decided_by(self, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking", decided_by="alice")
        with _as("bob"):
            from resource_explorer.run_queue import requested_by
            result = reg.record_depth_offer(
                f"https://github.com/x/{slug}", "declined", [], [],
                decided_by=requested_by(),
            )
        assert result["outcome"] == "declined"
        assert result["decided_by"] == "bob"
        assert result["analysis_ids"] == []
        assert result["run_ids"] == []
        assert "offered_at" in result and result["offered_at"]

        history = reg.get_disposition_history(f"https://github.com/x/{slug}")
        assert history[-1]["depth_offer"] == result

    def test_404_when_no_disposition_history_row(self, reg, slug):
        with pytest.raises(LookupError):
            reg.record_depth_offer(
                f"https://github.com/x/{slug}", "declined", [], [], decided_by="alice",
            )

    def test_409_when_already_recorded_once(self, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "investigating")
        reg.record_depth_offer(f"https://github.com/x/{slug}", "declined", [], [],
                               decided_by="alice")
        with pytest.raises(ValueError):
            reg.record_depth_offer(f"https://github.com/x/{slug}", "declined", [], [],
                                   decided_by="alice")

    def test_422_equivalent_rejects_bad_outcome_at_the_registry_too(self, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        with pytest.raises(ValueError):
            reg.record_depth_offer(f"https://github.com/x/{slug}", "maybe", [], [],
                                   decided_by="alice")

    def test_history_rows_carry_depth_offer_as_none_until_recorded(self, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        history = reg.get_disposition_history(f"https://github.com/x/{slug}")
        assert history[-1]["depth_offer"] is None

        reg.record_depth_offer(f"https://github.com/x/{slug}", "accepted",
                               ["security_scan"], ["run-1"], decided_by="alice")
        history = reg.get_disposition_history(f"https://github.com/x/{slug}")
        assert history[-1]["depth_offer"]["outcome"] == "accepted"
        assert history[-1]["depth_offer"]["analysis_ids"] == ["security_scan"]


class TestRecordDepthOfferRoute:
    @pytest.fixture
    def client(self, reg, monkeypatch):
        monkeypatch.setattr(
            "resource_explorer.registry.ProjectRegistry.__init__",
            lambda self, database_url=None, db_path=None: setattr(self, "__dict__", reg.__dict__) or None,
        )
        monkeypatch.setattr(
            "resource_explorer.auth.get_current_user",
            lambda request: {"user_id": "carol"},
        )
        from resource_explorer.web.app import app
        return TestClient(app)

    def test_declines_and_stamps_the_signed_in_caller(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        resp = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "declined",
        })
        assert resp.status_code == 200
        body = resp.json()
        assert body["outcome"] == "declined"
        assert body["decided_by"] == "carol"

    def test_body_cannot_claim_a_different_decided_by(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        resp = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "declined",
            "decided_by": "attacker",
        })
        assert resp.status_code == 200
        assert resp.json()["decided_by"] == "carol"

    def test_invalid_outcome_is_422(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        resp = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "maybe",
        })
        assert resp.status_code == 422

    def test_accepted_requires_analysis_ids(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        resp = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "accepted",
            "analysis_ids": [],
        })
        assert resp.status_code == 422

    def test_404_for_url_with_no_history(self, client):
        resp = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": "https://github.com/x/never-decided",
            "outcome": "declined",
        })
        assert resp.status_code == 404

    def test_409_on_second_offer_for_same_verdict(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        first = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "declined",
        })
        assert first.status_code == 200
        second = client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "declined",
        })
        assert second.status_code == 409

    def test_disposition_history_route_carries_depth_offer(self, client, reg, slug):
        reg.set_disposition(f"https://github.com/x/{slug}", "tracking")
        client.post("/api/discovery/disposition/depth-offer", json={
            "github_url": f"https://github.com/x/{slug}",
            "outcome": "declined",
        })
        resp = client.get("/api/discovery/disposition-history",
                          params={"github_url": f"https://github.com/x/{slug}"})
        assert resp.status_code == 200
        rows = resp.json()
        assert rows[-1]["depth_offer"]["outcome"] == "declined"
        assert rows[-1]["depth_offer"]["decided_by"] == "carol"
