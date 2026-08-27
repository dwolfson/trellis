"""A card must not claim "Never run" and "Published today" at once.

Both halves were wrong, from opposite causes:

* last_run_at read only operation='analysis_run' rows -- written solely by the
  per-analysis "Run" button. The database held 17 of those against 116
  operation='survey' rows, so every analysis on every repo reported never-run
  while its results sat in the findings tables.

* last_published_at joined on annotation_types, which are shared --
  ResourceMeasureAnnotation has 15 producers -- so one analysis publishing
  credited every sibling that declares the same type.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project


@pytest.fixture
def slug(request):
    import re as _re
    return "rp_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _log_survey(reg, slug, ts, steps, process="RepoCoarseProfile"):
    """One operation='survey' row shaped like the real ones."""
    from resource_explorer.activity_logger import log_survey

    log_survey(reg, "repo", slug, slug, "", "scouting", "ok", "surveyed", json.dumps({
        "source": "survey-definition", "entity_type": "repo", "slug": slug,
        "surveyed_at": ts,
        "steps": [{"step": f"GovActionProcessStep::{process}::{k}", "status": st}
                  for k, st in steps],
    }))


class TestRunAttribution:
    def test_a_survey_run_counts_as_running_its_analyses(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_security", "ok")])
        got = reg.get_analysis_last_run("repo", slug)
        assert "security_scan" in got, "an analysis run by a survey reported never-run"
        assert got["security_scan"]["last_run_via"] == "survey"
        assert got["security_scan"]["last_run_at"] == "2026-08-26T10:00:00"

    def test_step_keys_map_to_exactly_one_analysis(self):
        """The attribution is exact only if the map partitions the keys."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            REPO_ANALYSIS_STEP_MAP,
        )
        seen: dict[str, str] = {}
        for analysis_id, keys in REPO_ANALYSIS_STEP_MAP.items():
            for k in keys:
                assert k not in seen, f"step {k} claimed by {seen[k]} and {analysis_id}"
                seen[k] = analysis_id

    def test_a_partial_run_says_so(self, reg, slug):
        """language_file_classification owns three step keys. A survey running
        one of them did real work -- calling that "never run" is the larger
        error -- but it is not the whole analysis either."""
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_language", "ok")])
        got = reg.get_analysis_last_run("repo", slug)["language_file_classification"]
        assert got["last_run_partial"] is True

        _log_survey(reg, slug, "2026-08-26T11:00:00", [
            ("repo_language", "ok"), ("repo_file_classification", "ok"),
            ("repo_file_structure", "ok"),
        ])
        got = reg.get_analysis_last_run("repo", slug)["language_file_classification"]
        assert got["last_run_partial"] is False

    def test_the_steps_own_status_is_reported_not_the_surveys(self, reg, slug):
        """A survey that failed elsewhere still ran this analysis fine."""
        _log_survey(reg, slug, "2026-08-26T10:00:00",
                    [("repo_security", "ok"), ("repo_documentation", "error")])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["security_scan"]["last_run_status"] == "ok"
        assert got["documentation_coverage"]["last_run_status"] == "error"

    def test_an_unattributable_survey_row_credits_no_analysis(self, reg, slug):
        """Older survey rows carry no step detail. They must not be spread
        across every analysis on the theory that a survey ran something -- they
        are reported once, against a reserved key, as "we cannot say which"."""
        _log_survey(reg, slug, "2026-08-26T10:00:00", [])
        got = reg.get_analysis_last_run("repo", slug)
        assert [k for k in got if not k.startswith("__")] == []
        assert got["__unattributed_surveys__"]["count"] == 1


class TestPublishAttribution:
    """Which analysis a publish covered is RECORDED, not inferred.

    It used to be worked out backwards: join a publish's annotation types
    against each analysis's declared ones, and treat a uniquely-owned type as
    proof. That held only while every type had one producer. It stopped being
    true the moment a second analysis produced a QualityScoreAnnotation —
    after which NO analysis could earn an attributable publish and every card
    showed the hedged "Repo published". The inference was always going to break
    that way; nothing prevented a second producer.

    SurveyOrchestrator knows exactly which steps ran, so the publish records
    the analyses outright (project_published_analyses).
    """

    def test_the_orchestrator_records_what_actually_ran(self):
        """`steps_run` must reflect the post-cost-filter set: attributing an
        analysis a cost ceiling excluded would be the same false claim in a
        new place."""
        import inspect

        from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator

        src = inspect.getsource(SurveyOrchestrator.run)
        assert "result.steps_run" in src
        assert src.index("result.steps_run") > src.index("max_compute_cost is not None"), \
            "steps_run recorded before the cost filter narrowed the set"

    def test_steps_map_to_the_analyses_that_own_them(self):
        from resource_explorer.surveyors.egeria_publisher import _analyses_for_steps

        assert _analyses_for_steps(["repo_health"]) == {"repository_health"}
        assert _analyses_for_steps([]) == set()

    def test_a_partial_run_still_attributes_its_analysis(self):
        """language_file_classification owns three steps. One of them running
        published real findings under its name, and reporting nothing would
        lose them."""
        from resource_explorer.surveyors.egeria_publisher import _analyses_for_steps

        assert _analyses_for_steps(["repo_language"]) == {"language_file_classification"}

    def test_recorded_attribution_round_trips(self, pg_registry):
        reg = pg_registry
        reg.record_published_analyses("attr-demo", ["repository_health", "security_scan"],
                                      "guid-1", published_at="2026-08-27T00:00:00")
        got = reg.get_last_published_analyses("attr-demo")
        assert got["repository_health"] == "2026-08-27T00:00:00"
        assert got["security_scan"] == "2026-08-27T00:00:00"

    def test_recording_nothing_is_not_an_error(self, pg_registry):
        pg_registry.record_published_analyses("attr-none", [])
        assert pg_registry.get_last_published_analyses("attr-none") == {}

    def test_the_route_prefers_the_record_over_the_inference(self):
        import inspect

        from resource_explorer.web.routes import projects

        src = inspect.getsource(projects.get_analyses_last_activity)
        assert "published_by_analysis" in src
        # The dead inference helper is gone, not left to rot beside its
        # replacement.
        assert not hasattr(projects, "_sole_producer")


class TestNotEstablished:
    """"Never run" and "we cannot say" are different claims.

    Older survey rows carry no step detail. Their analyses cannot be credited
    with a run -- but the repo WAS surveyed, so calling them never-run beside a
    publish we can attribute reproduces the original contradiction with extra
    steps.
    """

    def test_an_undetailed_survey_yields_not_established_not_never_run(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T10:00:00", [])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["__unattributed_surveys__"]["count"] == 1

    def test_a_repo_with_no_surveys_at_all_is_never_run(self, reg, slug):
        """The third state must not swallow the second: a genuinely unsurveyed
        repo has to keep saying so, or "never run" stops meaning anything."""
        assert reg.get_analysis_last_run("repo", slug) == {}

    def test_an_attributed_run_is_not_downgraded_by_an_undetailed_one(self, reg, slug):
        _log_survey(reg, slug, "2026-08-26T09:00:00", [])
        _log_survey(reg, slug, "2026-08-26T10:00:00", [("repo_security", "ok")])
        got = reg.get_analysis_last_run("repo", slug)
        assert got["security_scan"]["last_run_at"] == "2026-08-26T10:00:00"
        assert got["__unattributed_surveys__"]["count"] == 1

    def test_the_ui_renders_all_three_states(self):
        html = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "resource_explorer" / "web" / "static" / "index.html"
        ).read_text()
        assert "📅 Last run not established" in html
        assert "📅 Never run" in html
        assert "la.last_run_basis === 'not_established'" in html


class TestProposedPerspectives:
    """The eight analyses that carried no lens at all now carry one.

    Not asserted individually -- the specific choices are a judgement the user
    can revise. What must hold is that none is untagged, and every tag is a
    real Egeria Perspective.
    """

    def test_no_analysis_is_left_without_a_perspective(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        untagged = [
            f"{rt}:{a['id']}"
            for rt in ("repo", "database", "filesystem")
            for a in get_analyses(rt, include_egeria_live=False)
            if not [p for p in (a.get("perspectives") or []) if p != "all"]
        ]
        assert untagged == [], f"analyses with no lens: {untagged}"

    def test_every_tag_is_a_real_egeria_perspective(self):
        from resource_explorer.surveyors.analysis_catalog_reader import (
            EGERIA_PERSPECTIVES, get_analyses,
        )
        for rt in ("repo", "database", "filesystem"):
            for a in get_analyses(rt, include_egeria_live=False):
                for p in (a.get("perspectives") or []):
                    assert p == "all" or p in EGERIA_PERSPECTIVES, f"{a['id']}: {p}"
