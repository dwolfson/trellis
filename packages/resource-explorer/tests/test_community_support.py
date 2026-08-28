"""Popularity is not support.

repository_health's community_score is stars/100*20 + forks/20*20 +
min(contributors,50)*1.2 — dominated by attention. Measured on the real catalog
2026-08-26: docling_graph scores 100/100 on it with FOUR contributors, because
683 stars and 71 forks max out the popularity terms on their own. 22 of 59
registered repos have six contributors or fewer.

A number that says "excellent community" about a project one person could
strand is the worst place for this codebase's recurring failure to appear,
because it is precisely the number someone consults before depending on
something.
"""
from __future__ import annotations

from resource_explorer.surveyors.sub_surveyors.community_support import assess, headline


def _labels(stats):
    return {d["check_name"]: d["label"] for d in assess(stats)}


class TestDimensionsStaySeparate:
    def test_high_attention_does_not_hide_low_participation(self):
        """The docling_graph case, as a test. Health scores this 100/100."""
        labels = _labels({"stars": 683, "forks": 71, "contributors_count": 4,
                          "has_issues": 1})
        assert labels["attention"] == "high"
        assert labels["participation"] == "small_team"
        assert labels["attention_exceeds_participation"] == "yes"

    def test_the_divergence_gets_its_own_finding(self):
        """Averaging it away is what produced the misleading score, so it is
        reported rather than folded into one of the other dimensions."""
        dims = assess({"stars": 683, "forks": 71, "contributors_count": 4})
        names = [d["check_name"] for d in dims]
        assert "attention_exceeds_participation" in names

    def test_a_broadly_maintained_project_does_not_trigger_it(self):
        labels = _labels({"stars": 65306, "forks": 4668, "contributors_count": 279})
        assert labels["participation"] == "broad"
        assert "attention_exceeds_participation" not in labels

    def test_an_unpopular_but_well_maintained_project_reads_correctly(self):
        """The inverse case: low attention says nothing bad about support."""
        labels = _labels({"stars": 3, "forks": 0, "contributors_count": 40})
        assert labels["attention"] == "low"
        assert labels["participation"] == "broad"


class TestHonestAbsence:
    def test_responsiveness_is_never_claimed(self):
        """An open-issue count is a COUNT, not a latency: a large number can
        mean an engaged community or an abandoned one, and picking either
        reading invents the answer someone actually wants."""
        dims = {d["check_name"]: d for d in assess({"stars": 10, "open_issues": 900})}
        assert dims["responsiveness"]["detail"]["known"] is False
        assert dims["responsiveness"]["label"] == "not_established"

    def test_an_uncounted_contributor_count_is_not_zero_contributors(self):
        """A repo always has at least one. Absent means uncounted."""
        dims = {d["check_name"]: d for d in assess({"stars": 10})}
        assert dims["participation"]["detail"]["known"] is False

    def test_no_channels_is_a_real_finding_not_an_unknown(self):
        """We can see that discussions/issues/wiki are all off, and "nowhere to
        ask" is exactly what someone evaluating support needs told."""
        # The flags must be COLLECTED and off. Omitting them is a different
        # fact, covered by the test below.
        dims = {d["check_name"]: d for d in assess(
            {"stars": 10, "contributors_count": 3,
             "has_discussions": 0, "has_issues": 0, "has_wiki": 0})}
        assert dims["channels"]["label"] == "none"
        assert dims["channels"]["detail"]["known"] is True

    def test_uncollected_channel_flags_are_not_read_as_all_off(self):
        """"All off" and "never looked" are the same absence in a dict, and only
        one of them means there is nowhere to ask a question. Caught by this
        file's own headline test before it could ship."""
        dims = {d["check_name"]: d for d in assess({"stars": 10, "contributors_count": 3})}
        assert dims["channels"]["detail"]["known"] is False


class TestHeadline:
    def test_it_names_the_weakest_dimension_not_an_average(self):
        """An average is what let attention mask participation."""
        line = headline(assess({"stars": 683, "forks": 71, "contributors_count": 1,
                                "has_issues": 1}))
        assert "sole_maintainer" in line

    def test_unknowns_are_named_rather_than_dropped(self):
        line = headline(assess({"stars": 683, "contributors_count": 40, "has_issues": 1}))
        assert "responsiveness not established" in line

    def test_nothing_known_says_so(self):
        assert "could be established" in headline(assess({}))


class TestRegistration:
    def test_wired_end_to_end_and_tagged(self):
        from resource_explorer.surveyors.analysis_catalog_reader import (
            EGERIA_PERSPECTIVES, get_analyses,
        )
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, REPO_ANALYSIS_RESULTS_MAP, STEP_REGISTRY,
        )

        assert "repo_community_support" in STEP_REGISTRY
        assert "community_support" in ANALYSIS_KINDS
        assert "community_support" in REPO_ANALYSIS_RESULTS_MAP
        entry = next(a for a in get_analyses("repo", include_egeria_live=False)
                     if a["id"] == "community_support")
        # Discovery until 2026-08-28 on zero-fetch grounds; Assessment now,
        # because naming the weakest support dimension is a judgement
        # against criteria and that signature outranks cost.
        assert entry["intent"] == "assessment"
        for p in entry["perspectives"]:
            assert p == "all" or p in EGERIA_PERSPECTIVES
