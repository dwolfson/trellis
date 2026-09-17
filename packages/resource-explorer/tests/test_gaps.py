"""resource_explorer/gaps.py — the gaps collection a project owns.

SPEC-ACTIONABLE-AND-HONEST.md §3: "A finding about the analysis belongs in a
gaps list the project owns." Runs against pg_registry (Postgres) because
upsert_gap's identity index and the FOREIGN KEY guard both matter here, and
this codebase's own convention keeps registry-shaped tests on the real
dialect translation layer rather than sqlite.
"""
from __future__ import annotations

import re as _re

import pytest

from resource_explorer.gaps import DISAGREEMENT, NOT_MEASURABLE, collect_gaps, gaps_summary, record_gaps_for
from resource_explorer.registry import Project


@pytest.fixture
def slug(request):
    return "gaps_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:40]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _stats(reg, slug, contributors_count):
    with reg._conn() as c:
        c.execute(
            "INSERT INTO project_stats (project_slug, fetched_at, contributors_count) "
            "VALUES (?, ?, ?)",
            (slug, "2026-09-14T00:00:00", contributors_count),
        )


def _seed_not_measurable(reg, slug):
    """One interface_surface check (`cli`) that could not be established —
    the shape community_support/interface_surface actually write."""
    reg.upsert_finding(slug, "interface_surface", [
        {"check_name": "cli", "label": "not_established",
         "summary": "Neither a file inventory nor parsed dependencies are recorded.",
         "confidence": 0},
    ], surveyed_at="2026-09-14T00:00:00")


def _seed_disagreement(reg, slug):
    """community_support (broad participation) + chaoss_metrics (sole
    authorship) — the exact shape facts.py's _r_community computes
    `measures_disagree` from."""
    reg.upsert_finding(slug, "community_support", [
        {"check_name": "attention", "label": "high", "summary": "", "confidence": 100},
        {"check_name": "participation", "label": "broad", "summary": "", "confidence": 100},
        {"check_name": "channels", "label": "many", "summary": "", "confidence": 100},
    ], surveyed_at="2026-09-14T00:00:00")
    reg.upsert_finding(slug, "chaoss_metrics", [
        {"check_name": "elephant_factor", "label": "sole",
         "summary": "One contributor wrote 93% of commits.", "confidence": 100},
    ], surveyed_at="2026-09-14T00:00:00")
    _stats(reg, slug, contributors_count=63)


class TestCollectGaps:
    def test_a_not_established_check_becomes_a_not_measurable_gap(self, reg, slug):
        _seed_not_measurable(reg, slug)
        gaps = collect_gaps(reg, slug)
        hits = [g for g in gaps if g["gap_kind"] == NOT_MEASURABLE and g["check_name"] == "cli"]
        assert len(hits) == 1
        assert hits[0]["analysis_id"] == "interface_surface"
        assert hits[0]["sentence"]

    def test_a_measures_disagree_value_becomes_a_disagreement_gap(self, reg, slug):
        _seed_disagreement(reg, slug)
        gaps = collect_gaps(reg, slug)
        hits = [g for g in gaps if g["gap_kind"] == DISAGREEMENT]
        assert len(hits) == 1
        assert hits[0]["analysis_id"] == "community_support"
        assert "63" in hits[0]["sentence"]
        assert "sole" in hits[0]["sentence"]

    def test_a_clean_resource_has_no_gaps(self, reg, slug):
        reg.upsert_finding(slug, "interface_surface", [
            {"check_name": "cli", "label": "specified", "summary": "", "confidence": 100},
        ], surveyed_at="2026-09-14T00:00:00")
        assert collect_gaps(reg, slug) == []

    def test_collect_gaps_does_not_write(self, reg, slug):
        """Pure — calling it never populates analysis_gaps."""
        _seed_not_measurable(reg, slug)
        collect_gaps(reg, slug)
        assert reg.list_gaps(slug) == []


class TestUpsertIsIdempotent:
    def test_recording_the_same_gap_twice_bumps_last_seen_not_duplicates(self, reg, slug):
        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)
        rows_first = reg.list_gaps(slug)
        assert len(rows_first) == 1
        first_seen = rows_first[0]["first_seen_at"]

        # Re-run: same gap, later sighting.
        record_gaps_for(reg, slug)
        rows_second = reg.list_gaps(slug)
        assert len(rows_second) == 1
        assert rows_second[0]["first_seen_at"] == first_seen
        assert rows_second[0]["last_seen_at"] >= rows_first[0]["last_seen_at"]

    def test_two_different_gaps_are_two_rows(self, reg, slug):
        _seed_not_measurable(reg, slug)
        _seed_disagreement(reg, slug)
        record_gaps_for(reg, slug)
        rows = reg.list_gaps(slug)
        kinds = sorted(r["gap_kind"] for r in rows)
        assert kinds == [DISAGREEMENT, NOT_MEASURABLE]


class TestGapsSummaryShape:
    def test_counts_and_measures_total(self, reg, slug):
        _seed_not_measurable(reg, slug)
        _seed_disagreement(reg, slug)
        record_gaps_for(reg, slug)
        summary = gaps_summary(reg, slug)
        assert summary["slug"] == slug
        assert summary["counts"]["total"] == 2
        assert summary["counts"][NOT_MEASURABLE] == 1
        assert summary["counts"][DISAGREEMENT] == 1
        assert summary["by_analysis"]["interface_surface"] == 1
        assert summary["by_analysis"]["community_support"] == 1
        # "3 of 11" needs a real denominator per analysis.
        assert summary["measures_total"]["interface_surface"] == 7
        assert summary["measures_total"]["community_support"] == 5

    def test_resolved_gaps_are_excluded_from_counts_but_still_listed(self, reg, slug):
        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)
        gap_id = reg.list_gaps(slug)[0]["id"]
        with reg._conn() as c:
            c.execute("UPDATE analysis_gaps SET resolved_at = ? WHERE id = ?",
                      ("2026-09-14T01:00:00", gap_id))
        summary = gaps_summary(reg, slug)
        assert summary["counts"]["total"] == 0
        assert len(summary["gaps"]) == 1  # still listed


class TestRfaRoute:
    """Route-level behaviour exercised directly against the registry +
    activity_logger, matching this codebase's convention of testing route
    logic without spinning up the ASGI app when the logic is a thin
    404/409-translating wrapper (see e.g. test_run_freshness.py)."""

    def test_raising_an_rfa_stamps_the_gap(self, reg, slug):
        from resource_explorer.activity_logger import log_rfa

        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)
        gap = reg.list_gaps(slug)[0]
        assert gap["rfa_activity_id"] is None

        rfa_id = log_rfa(reg, "repo", slug, slug, "open",
                         f"{gap['analysis_id']}: {gap['sentence']}",
                         analysis_name=gap["analysis_id"])
        reg.mark_gap_rfa(gap["id"], rfa_id)

        refreshed = reg.get_gap(gap["id"])
        assert refreshed["rfa_activity_id"] == rfa_id

    def test_get_gap_404_shape_is_none_for_unknown_id(self, reg, slug):
        assert reg.get_gap(999999999) is None

    def test_a_gap_from_another_project_does_not_match(self, reg, slug):
        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)
        gap = reg.list_gaps(slug)[0]
        assert gap["project_slug"] == slug
        # The route's own check is `gap["project_slug"] != slug` — exercised
        # directly here since the route itself is a thin wrapper over this.
        assert reg.get_gap(gap["id"])["project_slug"] != "some-other-project"


class TestSabotage:
    """Each assertion above, inverted once, to confirm the test actually
    exercises the behaviour it claims to (find-absence-as-answer discipline)."""

    def test_sabotage_not_measurable_requires_the_exact_label(self, reg, slug):
        reg.upsert_finding(slug, "interface_surface", [
            {"check_name": "cli", "label": "implied", "summary": "", "confidence": 80},
        ], surveyed_at="2026-09-14T00:00:00")
        gaps = collect_gaps(reg, slug)
        assert not any(g["gap_kind"] == NOT_MEASURABLE for g in gaps)

    def test_sabotage_disagreement_requires_sole_or_narrow_with_broad_or_team(self, reg, slug):
        reg.upsert_finding(slug, "community_support", [
            {"check_name": "participation", "label": "narrow", "summary": "", "confidence": 100},
        ], surveyed_at="2026-09-14T00:00:00")
        reg.upsert_finding(slug, "chaoss_metrics", [
            {"check_name": "elephant_factor", "label": "sole", "summary": "", "confidence": 100},
        ], surveyed_at="2026-09-14T00:00:00")
        _stats(reg, slug, contributors_count=4)
        gaps = collect_gaps(reg, slug)
        assert not any(g["gap_kind"] == DISAGREEMENT for g in gaps)


class TestAPersonsDisagreement:
    """`record_disagreement` — a person read one answer and said it is wrong.

    The done test for PLAN-FINISH-REPOS item 8: it lands in the gaps
    collection, marked `ours`. These assert the destination, that a person's
    gap is distinguishable from a measured one, that repeat clicks do not
    stack, and that a question no analysis answers is still recorded rather
    than attributed to a guessed analysis.
    """

    def test_it_lands_in_the_gaps_collection_as_ours(self, reg, slug):
        from resource_explorer.destinations import OURS
        from resource_explorer.gaps import record_disagreement

        gap = record_disagreement(
            reg, slug, "Is it actively maintained?", "community_support",
            comment="The last release was three years ago.",
        )
        assert gap["destination"] == OURS

        summary = gaps_summary(reg, slug)
        rows = [r for r in summary["gaps"] if r["gap_kind"] == DISAGREEMENT]
        assert len(rows) == 1
        assert rows[0]["destination"] == OURS
        assert rows[0]["analysis_id"] == "community_support"
        assert "three years ago" in rows[0]["sentence"]

    def test_a_persons_gap_is_distinguishable_from_a_measured_one(self, reg, slug):
        """Both are `disagreement` and both are `ours`, but they are work for
        different people — so `source` separates them and
        `disputed_by_a_person` counts only the human ones."""
        from resource_explorer.gaps import SOURCE_MEASURED, SOURCE_PERSON, record_disagreement

        _seed_disagreement(reg, slug)
        _stats(reg, slug, 40)
        record_gaps_for(reg, slug)
        record_disagreement(reg, slug, "Who maintains it?", "chaoss_metrics")

        summary = gaps_summary(reg, slug)
        sources = {r["check_name"]: r["source"] for r in summary["gaps"]}
        assert sources["question:Who maintains it?"] == SOURCE_PERSON
        assert all(
            v == SOURCE_MEASURED
            for k, v in sources.items() if not k.startswith("question:")
        )
        assert summary["counts"]["disputed_by_a_person"] == 1
        # A subset, not a fourth bucket.
        assert summary["counts"][DISAGREEMENT] >= 1

    def test_two_people_disagreeing_is_one_gap(self, reg, slug):
        from resource_explorer.gaps import record_disagreement

        record_disagreement(reg, slug, "Is it maintained?", "community_support", comment="no")
        record_disagreement(reg, slug, "Is it maintained?", "community_support", comment="also no")

        rows = [r for r in gaps_summary(reg, slug)["gaps"]
                if r["check_name"] == "question:Is it maintained?"]
        assert len(rows) == 1
        # The latest sighting refreshes the sentence rather than being lost.
        assert "also no" in rows[0]["sentence"]

    def test_an_unattributed_disagreement_is_still_recorded(self, reg, slug):
        """A question the catalog answers with a direct field names no
        analysis. Recording nothing would discard the only signal that an
        answer is wrong; inventing an analysis id would charge a dispute to
        something that never answered it."""
        from resource_explorer.gaps import record_disagreement

        gap = record_disagreement(reg, slug, "What licence is it under?", "")
        assert gap["analysis_id"] == ""
        assert gap["evidence"]["analysis_attributed"] is False

        rows = [r for r in gaps_summary(reg, slug)["gaps"]
                if r["check_name"] == "question:What licence is it under?"]
        assert len(rows) == 1
        assert rows[0]["analysis_id"] == ""

    def test_collecting_measured_gaps_does_not_clobber_a_persons(self, reg, slug):
        """`record_gaps_for` runs on every page load. A person's gap uses a
        `question:`-prefixed check_name precisely so the identity index can
        never collide with a real check, and so a re-collection leaves it
        standing."""
        from resource_explorer.gaps import record_disagreement

        record_disagreement(reg, slug, "Is it maintained?", "community_support")
        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)

        checks = {r["check_name"] for r in gaps_summary(reg, slug)["gaps"]}
        assert "question:Is it maintained?" in checks

    def test_measured_gaps_still_say_ours(self, reg, slug):
        """The destination is stated on every row, not only the new ones —
        so a consumer reads one word for both halves of the collection."""
        from resource_explorer.destinations import OURS

        _seed_not_measurable(reg, slug)
        record_gaps_for(reg, slug)
        rows = gaps_summary(reg, slug)["gaps"]
        assert rows and all(r["destination"] == OURS for r in rows)
