"""The stage page's backend facts (STAGE-PAGE-ROUND.md, 2026-09-14):

* `build_measurements` — point 10, "the fact opens under the answer".
* `fetch_step_counts` — point 2, the definition rows' "N steps · M fetch".
* `build_analyses_index` — points 1-3, "AnalysesIndex"'s rows.

All three are pure functions in resource_explorer/workflows/stage_page.py,
tested here directly against a throwaway Postgres schema (pg_registry) —
no FastAPI app needed, same convention as test_depth_offer.py /
test_run_freshness.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from resource_explorer.members import _READERS
from resource_explorer.registry import Project
from resource_explorer.workflows.stage_page import (
    build_analyses_index,
    build_measurements,
    fetch_step_counts,
    runnable_and_reason,
)


@pytest.fixture
def slug(request):
    import hashlib
    import re as _re
    # request.node.name alone collides across classes with a like-named test
    # (the shared, session-scoped pg_test_schema means every test in this
    # file's `projects` table is the same table) — nodeid disambiguates by
    # class, a short hash keeps it under Postgres' identifier length.
    h = hashlib.sha1(request.node.nodeid.encode()).hexdigest()[:8]
    base = _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:30]
    return f"sp_{base}_{h}"


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _log_run(reg, slug, analysis_id, *, minutes_ago=0, status="ok"):
    """One activity_log analysis_run row, back-dated — same helper as
    tests/test_run_freshness.py's and tests/test_depth_offer.py's."""
    from resource_explorer.activity_logger import log_analysis_run
    entry_id = log_analysis_run(reg, "repo", slug, slug, status,
                                f"ran {analysis_id}", analysis_id, published=None)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    with reg._conn() as c:
        c.execute("UPDATE activity_log SET ts = %s WHERE id = %s", (ts, entry_id))
    return entry_id


def _write_metric_row(reg, slug, kind, metrics, *, surveyed_at=None):
    """registry.upsert_metric requires every value to be a float — the
    schema's `metric_value REAL NOT NULL` means a genuinely null column
    cannot be written this way. Null-column handling is exercised in
    `test_null_column_renders_null_and_zero_stays_zero` via a monkeypatched
    `query_metrics` instead (build_measurements never coerces whatever that
    call returns)."""
    surveyed_at = surveyed_at or datetime.now(timezone.utc).isoformat()
    reg.upsert_metric(slug, kind, metrics, surveyed_at=surveyed_at)


class TestBuildMeasurements:
    def test_null_column_renders_null_and_zero_stays_zero(self, reg, slug, monkeypatch):
        # The schema's `metric_value REAL NOT NULL` means a real null column
        # cannot be written through upsert_metric/a raw INSERT — so this
        # exercises build_measurements' own pass-through by monkeypatching
        # what query_metrics returns, the way a null WOULD arrive if the
        # column ever did allow one. `zero stays zero` is covered for real
        # (through an actual write) in test_opens_present_exactly_where_a_
        # reader_exists below.
        _log_run(reg, slug, "api_structure", minutes_ago=2)
        real_query_metrics = reg.query_metrics

        def _fake_query_metrics(slug_, kind, scope_locator=""):
            if kind == "api_structure":
                return {"symbol_count": 0, "relationship_count": None,
                        "surveyed_at": "2026-09-14T00:00:00+00:00"}
            return real_query_metrics(slug_, kind, scope_locator)

        monkeypatch.setattr(reg, "query_metrics", _fake_query_metrics)
        m = build_measurements(reg, slug, "api_structure")
        assert m["not_applicable"] is False
        by_name = {row["name"]: row for row in m["measurements"]}
        assert by_name["symbol_count"]["value"] == 0
        assert by_name["relationship_count"]["value"] is None

    def test_opens_present_exactly_where_a_reader_exists(self, reg, slug):
        """Assert against members._READERS directly so this test cannot
        drift from the reader table it's supposed to track."""
        _log_run(reg, slug, "api_structure", minutes_ago=1)
        _write_metric_row(reg, slug, "api_structure",
                          {"symbol_count": 42, "relationship_count": 7})
        m = build_measurements(reg, slug, "api_structure")
        by_name = {row["name"]: row for row in m["measurements"]}

        assert ("api_structure", "symbol_count") in _READERS
        assert by_name["symbol_count"]["opens"] == {
            "analysis_id": "api_structure", "metric": "symbol_count",
        }
        # relationship_count has no reader keyed to it, exact or fallback —
        # _symbol_members (the (api_structure, symbol_count) reader) lists
        # symbols, not relationships.
        assert ("api_structure", "relationship_count") not in _READERS
        assert by_name["relationship_count"]["opens"] is None

    def test_cve_scan_opens_only_the_metric_the_fallback_reader_lists(self, reg, slug):
        _log_run(reg, slug, "cve_scan", minutes_ago=1)
        _write_metric_row(reg, slug, "cve_scan", {
            "advisories": 3, "packages_affected": 2, "checked": 10, "unqueryable": 0,
        })
        m = build_measurements(reg, slug, "cve_scan")
        by_name = {row["name"]: row for row in m["measurements"]}
        assert ("cve_scan", None) in _READERS
        assert by_name["advisories"]["opens"] == {"analysis_id": "cve_scan", "metric": "advisories"}
        assert by_name["packages_affected"]["opens"] is None
        assert by_name["checked"]["opens"] is None

    def test_findings_only_analysis_is_not_applicable(self, reg, slug):
        # `license_classification` (a findings_list kind with no metrics
        # kind mapping) never writes to project_analysis_metrics.
        m = build_measurements(reg, slug, "license_classification")
        assert m["not_applicable"] is True
        assert m["measurements"] == []
        assert "records findings, not measurements" in m["reason"]
        assert "license_classification" in m["reason"]

    def test_metrics_kind_exists_but_nothing_recorded_yet(self, reg, slug):
        m = build_measurements(reg, slug, "api_structure")
        assert m["not_applicable"] is False
        assert m["measurements"] == []
        assert "has not recorded measurements" in m["reason"]

    def test_unknown_analysis_id_raises_lookup_error(self, reg, slug):
        with pytest.raises(LookupError):
            build_measurements(reg, slug, "not_a_real_analysis")

    def test_unknown_slug_raises_lookup_error(self, reg):
        with pytest.raises(LookupError):
            build_measurements(reg, "no-such-slug-at-all", "api_structure")

    def test_footer_names_the_analysis_and_the_run_age(self, reg, slug):
        _log_run(reg, slug, "api_structure", minutes_ago=2)
        _write_metric_row(reg, slug, "api_structure", {"symbol_count": 1})
        m = build_measurements(reg, slug, "api_structure")
        assert m["footer"].startswith("Read from api_structure, run ")
        assert "ago" in m["footer"]

    def test_footer_says_run_date_not_recorded_when_never_run(self, reg, slug):
        m = build_measurements(reg, slug, "api_structure")
        assert "run date not recorded" in m["footer"]


class TestFetchStepCounts:
    def test_mixed_step_list_splits_correctly_and_surfaces_unregistered(self):
        # repo_file_inventory and repo_manifest_parse both declare
        # requires_resources={"zipball_root": ...}; repo_language declares
        # none; "not_a_real_step" is in no STEP_REGISTRY at all.
        step_count, fetch_steps, unregistered = fetch_step_counts([
            "repo_file_inventory", "repo_manifest_parse", "repo_language", "not_a_real_step",
        ])
        assert step_count == 4
        assert fetch_steps == 2
        assert unregistered == ["not_a_real_step"]

    def test_empty_list(self):
        assert fetch_step_counts([]) == (0, 0, [])

    def test_every_step_fetches(self):
        step_count, fetch_steps, unregistered = fetch_step_counts(
            ["repo_file_inventory", "repo_manifest_parse"])
        assert step_count == fetch_steps == 2
        assert unregistered == []


class TestBuildAnalysesIndex:
    def test_question_backed_analysis_serves_question(self, reg, slug):
        idx = build_analyses_index(reg, slug)
        by_id = {r["analysis_id"]: r for r in idx["analyses"]}
        question_backed = [r for r in idx["analyses"] if r["questions"]]
        assert question_backed, "expected at least one analysis with a naming question"
        row = question_backed[0]
        assert row["serves"] == "question"

    def test_results_reader_with_no_question_is_chat_only(self, reg, slug):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

        questions = get_questions("repo")
        named = set()
        for q in questions:
            named.update(q["answering"]["analysis_ids"] or [])

        candidate = None
        for a in get_analyses("repo", include_egeria_live=False):
            if a["id"] in named or a.get("action") == "publish":
                continue
            kind = ANALYSIS_KINDS.get(a["id"])
            if kind and kind.results is not None:
                candidate = a["id"]
                break
        assert candidate, "expected a results-reader analysis with no naming question"

        idx = build_analyses_index(reg, slug)
        row = next(r for r in idx["analyses"] if r["analysis_id"] == candidate)
        assert row["serves"] == "chat-only"
        assert row["questions"] == []

    def test_neither_question_nor_reader_is_nothing_yet(self, reg, slug):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        from resource_explorer.surveyors.question_catalog_reader import get_questions
        from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

        questions = get_questions("repo")
        named = set()
        for q in questions:
            named.update(q["answering"]["analysis_ids"] or [])

        candidate = None
        for a in get_analyses("repo", include_egeria_live=False):
            if a["id"] in named or a.get("action") == "publish":
                continue
            kind = ANALYSIS_KINDS.get(a["id"])
            if not kind or kind.results is None:
                candidate = a["id"]
                break

        idx = build_analyses_index(reg, slug)
        if candidate is None:
            pytest.skip("no analysis in the local catalog has neither a question nor a results reader")
        row = next(r for r in idx["analyses"] if r["analysis_id"] == candidate)
        assert row["serves"] == "nothing-yet"

    def test_short_description_is_the_first_sentence(self, reg, slug):
        idx = build_analyses_index(reg, slug)
        for row in idx["analyses"]:
            if ". " in row["description"]:
                assert row["short_description"] == row["description"].split(". ", 1)[0] + "."
                assert len(row["short_description"]) < len(row["description"])
                break
        else:
            pytest.skip("no catalog description spans more than one sentence")

    def test_egeria_publish_is_excluded_but_its_reason_matches_the_route(self):
        # egeria_publish (action: "publish") never appears as a row — see
        # the analyses-index population test below — but the underlying
        # gate is the same one the run route uses, and is id-only.
        runnable, reason = runnable_and_reason("egeria_publish")
        assert runnable is False
        assert reason == (
            "Analysis 'egeria_publish' has no mapped survey step(s) — "
            "either it's a publish action (not a survey) or an unknown id."
        )

    def test_publish_actions_are_excluded_from_the_index(self, reg, slug):
        idx = build_analyses_index(reg, slug)
        ids = {r["analysis_id"] for r in idx["analyses"]}
        assert "egeria_publish" not in ids

    def test_last_run_via_carries_the_source_for_a_derived_analysis(self, reg, slug):
        # architecture_diagram owns no steps of its own — it derives from
        # architecture_recovery's (AnalysisKind.derives_from). Only the
        # SOURCE ran directly; the derived row must still report a run,
        # attributed to the source, not "never run."
        _log_run(reg, slug, "architecture_recovery", minutes_ago=3)
        idx = build_analyses_index(reg, slug)
        row = next(r for r in idx["analyses"] if r["analysis_id"] == "architecture_diagram")
        assert row["last_run_at"]
        assert row["last_run_via"] == "architecture_recovery"

    def test_counts_never_run_and_no_question(self, reg, slug):
        idx = build_analyses_index(reg, slug)
        assert idx["counts"]["total"] == len(idx["analyses"])
        assert idx["counts"]["never_run"] == sum(
            1 for r in idx["analyses"] if not r["last_run_at"])
        assert idx["counts"]["no_question"] == sum(
            1 for r in idx["analyses"] if r["serves"] != "question")

    def test_unknown_slug_raises_lookup_error(self, reg):
        with pytest.raises(LookupError):
            build_analyses_index(reg, "no-such-slug-at-all")

    def test_catalog_field_is_the_entry_verbatim(self, reg, slug):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

        by_id = {a["id"]: a for a in get_analyses("repo", include_egeria_live=False)}
        idx = build_analyses_index(reg, slug)
        for row in idx["analyses"]:
            assert row["catalog"] == by_id[row["analysis_id"]]
