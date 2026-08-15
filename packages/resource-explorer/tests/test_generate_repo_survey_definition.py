"""Tests for scripts/generate_repo_survey_definition.py's D1 cross-reference
logic (docs/survey-question-context-plan.md) — the step_key -> Question join
via question_catalog.yaml's answering.analysis_ids and REPO_ANALYSIS_STEP_MAP.
No live Egeria needed; loaded by path since scripts/ isn't a package."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "generate_repo_survey_definition.py"


@pytest.fixture
def script(monkeypatch):
    """Loads the script module fresh per test, with get_questions() patched
    at its import site so tests don't depend on the real question catalog's
    current content."""
    spec = importlib.util.spec_from_file_location("generate_repo_survey_definition", _SCRIPT_PATH)
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
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["security_scan"])])
        monkeypatch.setattr(script, "REPO_ANALYSIS_STEP_MAP", {"security_scan": ["repo_security"]})
        mapping = script._build_step_key_to_questions()
        assert mapping == {"repo_security": ["Q1"]}

    def test_question_with_multiple_analysis_ids_spans_multiple_step_keys(self, script, monkeypatch):
        monkeypatch.setattr(
            script, "get_questions",
            lambda **_kw: [_entry("Q1", ["security_scan", "repository_health"])],
        )
        monkeypatch.setattr(
            script, "REPO_ANALYSIS_STEP_MAP",
            {"security_scan": ["repo_security"], "repository_health": ["repo_health"]},
        )
        mapping = script._build_step_key_to_questions()
        assert mapping == {"repo_security": ["Q1"], "repo_health": ["Q1"]}

    def test_analysis_id_bundling_multiple_step_keys_fans_out_to_all(self, script, monkeypatch):
        # language_file_classification-style bundle — one analysis id, three step keys.
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["language_file_classification"])])
        monkeypatch.setattr(
            script, "REPO_ANALYSIS_STEP_MAP",
            {"language_file_classification": ["repo_language", "repo_file_classification", "repo_file_structure"]},
        )
        mapping = script._build_step_key_to_questions()
        assert set(mapping.keys()) == {"repo_language", "repo_file_classification", "repo_file_structure"}
        assert all(v == ["Q1"] for v in mapping.values())

    def test_question_with_no_analysis_ids_contributes_nothing(self, script, monkeypatch):
        # kind="human"/"gap" questions have no answering.analysis_ids at all.
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", [])])
        monkeypatch.setattr(script, "REPO_ANALYSIS_STEP_MAP", {})
        assert script._build_step_key_to_questions() == {}

    def test_unmapped_analysis_id_contributes_nothing(self, script, monkeypatch):
        monkeypatch.setattr(script, "get_questions", lambda **_kw: [_entry("Q1", ["not_a_real_analysis_id"])])
        monkeypatch.setattr(script, "REPO_ANALYSIS_STEP_MAP", {"security_scan": ["repo_security"]})
        assert script._build_step_key_to_questions() == {}

    def test_dedupes_same_question_reaching_a_step_key_twice(self, script, monkeypatch):
        # Two analysis ids that both map into the same step_key shouldn't
        # duplicate the question in that step_key's list.
        monkeypatch.setattr(
            script, "get_questions",
            lambda **_kw: [_entry("Q1", ["a", "b"])],
        )
        monkeypatch.setattr(script, "REPO_ANALYSIS_STEP_MAP", {"a": ["repo_x"], "b": ["repo_x"]})
        mapping = script._build_step_key_to_questions()
        assert mapping == {"repo_x": ["Q1"]}


class TestAnsweredQuestions:
    def test_unions_across_step_keys_without_duplicates(self, script):
        step_key_to_questions = {"repo_a": ["Q1", "Q2"], "repo_b": ["Q2", "Q3"]}
        result = script._answered_questions(["repo_a", "repo_b"], step_key_to_questions)
        assert result == ["Q1", "Q2", "Q3"]

    def test_step_key_with_no_questions_is_fine(self, script):
        assert script._answered_questions(["repo_x"], {}) == []

    def test_order_is_stable_by_first_appearance(self, script):
        step_key_to_questions = {"repo_a": ["Q2", "Q1"]}
        assert script._answered_questions(["repo_a"], step_key_to_questions) == ["Q2", "Q1"]
