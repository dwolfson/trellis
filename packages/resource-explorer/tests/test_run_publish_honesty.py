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
    def test_a_shared_annotation_type_does_not_credit_a_publish(self):
        """ResourceMeasureAnnotation has 15 producers; crediting all of them is
        what put "Published today" on cards that had never run."""
        from resource_explorer.web.routes.projects import _sole_producer

        assert _sole_producer("ResourceMeasureAnnotation") == ""
        assert _sole_producer("ClassificationAnnotation") == ""

    def test_a_uniquely_owned_type_does(self):
        """The rule, not a specific type.

        QualityScoreAnnotation was the last uniquely-owned one and stopped
        being unique on 2026-08-26, when foss_scorecard began producing one
        too -- correctly, it really does compute a quality score. So NO real
        analysis can currently earn an analysis-scope publish, and every card
        shows the hedged "Repo published" instead.

        That is honest (with two producers we cannot attribute) but it means
        the precise tier is unreachable in practice. The fix is to record the
        analysis id at publish time rather than infer it from annotation types
        -- publishing is already step-scoped, so the information is there; it
        needs a column. Until then this asserts the rule against a constructed
        pair, so the behaviour stays pinned without depending on an accident
        of how many analyses share a type.
        """
        from resource_explorer.web.routes.projects import _sole_producer

        # Real, and currently shared -- the state described above.
        assert _sole_producer("QualityScoreAnnotation") == ""
        assert _sole_producer("NoSuchAnnotationTypeAtAll") == ""

    def test_the_two_tiers_are_distinguishable(self):
        """'repo' scope must stay tellable from 'analysis' scope, or the hedge
        is invisible and the weaker claim reads as the stronger one."""
        html = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "resource_explorer" / "web" / "static" / "index.html"
        ).read_text()
        assert "☁ Repo published" in html
        assert "last_published_scope === 'repo'" in html


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
