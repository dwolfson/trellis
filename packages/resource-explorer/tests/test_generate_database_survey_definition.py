"""Tests for scripts/generate_database_survey_definition.py — cloned from
tests/test_generate_repo_survey_definition.py's D1 cross-reference logic
(docs/survey-question-context-plan.md), adapted for the database script's
hardcoded SPECS (no repo_survey_types.csv equivalent — see the script's
module docstring for why). No live Egeria needed; loaded by path since
scripts/ isn't a package."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "generate_database_survey_definition.py"


@pytest.fixture
def script(monkeypatch):
    """Loads the script module fresh per test, with get_questions() patched
    at its import site so tests don't depend on the real question catalog's
    current content."""
    spec = importlib.util.spec_from_file_location("generate_database_survey_definition", _SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # dataclass field resolution needs the module registered
    try:
        spec.loader.exec_module(module)
    finally:
        del sys.modules[spec.name]
    return module


def _entry(question, analysis_ids):
    return {"question": question, "answering": {"analysis_ids": analysis_ids}}


class TestBuildStepKeyToQuestions:
    def test_maps_analysis_id_through_step_map_to_step_keys(self, script, monkeypatch):
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["privilege_audit"])])
        monkeypatch.setattr(script, "DATABASE_ANALYSIS_SOURCE_STEPS", {"privilege_audit": ["postgres_operations"]})
        mapping = script._build_step_key_to_questions()
        assert mapping == {"postgres_operations": ["Q1"]}

    def test_question_with_multiple_analysis_ids_spans_multiple_step_keys(self, script, monkeypatch):
        monkeypatch.setattr(
            script, "get_questions",
            lambda **_kw: [_entry("Q1", ["privilege_audit", "schema_inventory"])],
        )
        monkeypatch.setattr(
            script, "DATABASE_ANALYSIS_SOURCE_STEPS",
            {"privilege_audit": ["postgres_operations"], "schema_inventory": ["postgres_schema_and_stats"]},
        )
        mapping = script._build_step_key_to_questions()
        assert mapping == {"postgres_operations": ["Q1"], "postgres_schema_and_stats": ["Q1"]}

    def test_question_with_no_analysis_ids_contributes_nothing(self, script, monkeypatch):
        # kind="human"/"gap" questions with no real analysis_ids at all.
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", [])])
        monkeypatch.setattr(script, "DATABASE_ANALYSIS_SOURCE_STEPS", {})
        assert script._build_step_key_to_questions() == {}

    def test_unmapped_analysis_id_contributes_nothing(self, script, monkeypatch):
        # A "GAP: <proposed id>" analysis id that names no real step yet
        # (e.g. db_documentation_coverage, schema_conventions) — the id shows
        # up in analysis_ids per the regex-scan convention, but the join must
        # not manufacture a link to a step that cannot produce it.
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["db_documentation_coverage"])])
        monkeypatch.setattr(script, "DATABASE_ANALYSIS_SOURCE_STEPS", {"privilege_audit": ["postgres_operations"]})
        assert script._build_step_key_to_questions() == {}

    def test_gap_kind_question_with_a_now_real_analysis_id_still_links(self, script, monkeypatch):
        # answering.kind is never consulted here — governs Questions-tab
        # answerability, not this join. A GAP row naming a "(proposed)" id
        # that a later slice actually built (db_activity_signals,
        # db_resilience, db_external_dependencies via postgres_operations)
        # still gets linked, matching repo's identical behavior.
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["db_activity_signals"])])
        monkeypatch.setattr(script, "DATABASE_ANALYSIS_SOURCE_STEPS", {"db_activity_signals": ["postgres_operations"]})
        mapping = script._build_step_key_to_questions()
        assert mapping == {"postgres_operations": ["Q1"]}

    def test_dedupes_same_question_reaching_a_step_key_twice(self, script, monkeypatch):
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["a", "b"])])
        monkeypatch.setattr(script, "DATABASE_ANALYSIS_SOURCE_STEPS", {"a": ["postgres_operations"], "b": ["postgres_operations"]})
        mapping = script._build_step_key_to_questions()
        assert mapping == {"postgres_operations": ["Q1"]}


class TestAnsweredQuestions:
    def test_unions_across_step_keys_without_duplicates(self, script):
        step_key_to_questions = {"a": ["Q1", "Q2"], "b": ["Q2", "Q3"]}
        result = script._answered_questions(["a", "b"], step_key_to_questions)
        assert result == ["Q1", "Q2", "Q3"]

    def test_step_key_with_no_questions_is_fine(self, script):
        assert script._answered_questions(["postgres_schema_and_stats"], {}) == []

    def test_order_is_stable_by_first_appearance(self, script):
        step_key_to_questions = {"a": ["Q2", "Q1"]}
        assert script._answered_questions(["a"], step_key_to_questions) == ["Q2", "Q1"]


class TestBuildSteps:
    def test_builds_a_publishable_step_per_key(self, script):
        steps = script.build_steps(["postgres_schema_and_stats"])
        assert len(steps) == 1
        assert steps[0].step_key == "postgres_schema_and_stats"
        assert steps[0].technology_type == script.TECHNOLOGY_TYPE
        assert steps[0].executes_at == "resource-explorer"

    def test_description_comes_from_the_adapter_step_info(self, script):
        steps = script.build_steps(["postgres_schema_and_stats"])
        assert steps[0].description == script.STEP_INFO["postgres_schema_and_stats"]["description"]

    def test_missing_step_info_falls_back_to_the_key(self, script, monkeypatch):
        monkeypatch.setattr(script, "STEP_INFO", {})
        steps = script.build_steps(["postgres_operations"])
        assert steps[0].description == "postgres_operations"


class TestValidateSpecs:
    """Mirrors repo's SurveyTypesCsvError guard — loud on a step SPECS
    references that the database adapter doesn't actually register, so a
    future rename/removal in survey_definition_adapter.py can't silently
    generate a Survey Definition chaining a step the executor can't
    dispatch."""

    def test_unknown_step_key_raises(self, script, monkeypatch):
        bad_spec = script.SurveyDefSpec(
            survey_kind="k", survey_group="G", survey_display_name="G",
            description="d", step_keys=["not_a_real_step"], output_filename="g.md",
        )
        monkeypatch.setattr(script, "SPECS", [bad_spec])
        with pytest.raises(script.DatabaseSurveySpecError, match="not_a_real_step"):
            script._validate_specs()

    def test_real_specs_reference_only_real_registered_steps(self, script):
        """Regression guard against SPECS going stale the same way the
        generated docs did for repo — the real STEP_REGISTRY, the real
        SPECS. Must not raise."""
        script._validate_specs()  # must not raise
        referenced = {k for spec in script.SPECS for k in spec.step_keys}
        assert referenced <= set(script.STEP_REGISTRY.keys())

    def test_every_registered_step_is_referenced_by_some_spec(self, script, capsys):
        """Coverage: every one of the three currently-registered database
        steps (postgres_schema_and_stats, postgres_operations, sql_analysis)
        should appear in at least one tier, or it's invisible to every
        generated Survey Definition. Warn-only in the script itself; this
        test pins that today's real registry produces no such warning."""
        script._validate_specs()
        assert "WARNING" not in capsys.readouterr().out


class TestSpecsShape:
    def test_three_tiers_scouting_analysis_assessment(self, script):
        assert {s.survey_kind for s in script.SPECS} == {"scouting", "analysis", "assessment"}

    def test_scouting_is_the_cheapest_tier(self, script):
        scouting = next(s for s in script.SPECS if s.survey_kind == "scouting")
        assert scouting.step_keys == ["postgres_schema_and_stats"]

    def test_analysis_chains_every_registered_step(self, script):
        analysis = next(s for s in script.SPECS if s.survey_kind == "analysis")
        assert set(analysis.step_keys) == set(script.STEP_REGISTRY.keys())

    def test_assessment_omits_sql_analysis(self, script):
        assessment = next(s for s in script.SPECS if s.survey_kind == "assessment")
        assert "sql_analysis" not in assessment.step_keys
        assert set(assessment.step_keys) == {"postgres_schema_and_stats", "postgres_operations"}
