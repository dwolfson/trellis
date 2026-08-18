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


def _write_csv(path, rows):
    import csv as _csv
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = _csv.DictWriter(
            f,
            fieldnames=[
                "survey_kind", "survey_group", "survey_display_name",
                "description", "output_filename", "step_key", "step_order",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


class TestLoadSpecsFromCsv:
    """D3 (docs/repo-survey-catalog-completion-plan.md) — the CSV-driven
    SPECS loader, and its two validation guards."""

    def test_groups_rows_by_survey_ordered_by_step_order(self, script, monkeypatch, tmp_path):
        monkeypatch.setattr(
            script, "STEP_REGISTRY", {"repo_a": object(), "repo_b": object()},
        )
        csv_path = tmp_path / "specs.csv"
        _write_csv(csv_path, [
            {"survey_kind": "k", "survey_group": "G", "survey_display_name": "G Name",
             "description": "desc", "output_filename": "g.md", "step_key": "repo_b", "step_order": "2"},
            {"survey_kind": "k", "survey_group": "G", "survey_display_name": "G Name",
             "description": "desc", "output_filename": "g.md", "step_key": "repo_a", "step_order": "1"},
        ])
        specs = script.load_specs_from_csv(csv_path)
        assert len(specs) == 1
        assert specs[0].step_keys == ["repo_a", "repo_b"]  # sorted by step_order, not file order
        assert specs[0].survey_display_name == "G Name"
        assert specs[0].output_filename == "g.md"

    def test_preserves_first_appearance_order_across_multiple_surveys(self, script, monkeypatch, tmp_path):
        monkeypatch.setattr(script, "STEP_REGISTRY", {"repo_a": object(), "repo_b": object()})
        csv_path = tmp_path / "specs.csv"
        _write_csv(csv_path, [
            {"survey_kind": "second", "survey_group": "Second", "survey_display_name": "Second",
             "description": "d", "output_filename": "s.md", "step_key": "repo_b", "step_order": "1"},
            {"survey_kind": "first", "survey_group": "First", "survey_display_name": "First",
             "description": "d", "output_filename": "f.md", "step_key": "repo_a", "step_order": "1"},
        ])
        specs = script.load_specs_from_csv(csv_path)
        assert [s.survey_group for s in specs] == ["Second", "First"]

    def test_star_sentinel_expands_to_all_step_registry_keys_in_order(self, script, monkeypatch, tmp_path):
        monkeypatch.setattr(
            script, "STEP_REGISTRY",
            {"repo_a": object(), "repo_b": object(), "repo_c": object()},
        )
        csv_path = tmp_path / "specs.csv"
        _write_csv(csv_path, [
            {"survey_kind": "full", "survey_group": "Full", "survey_display_name": "Full",
             "description": "d", "output_filename": "full.md", "step_key": "*", "step_order": "1"},
        ])
        specs = script.load_specs_from_csv(csv_path)
        assert specs[0].step_keys == ["repo_a", "repo_b", "repo_c"]

    def test_unknown_step_key_raises(self, script, monkeypatch, tmp_path):
        monkeypatch.setattr(script, "STEP_REGISTRY", {"repo_a": object()})
        csv_path = tmp_path / "specs.csv"
        _write_csv(csv_path, [
            {"survey_kind": "k", "survey_group": "G", "survey_display_name": "G",
             "description": "d", "output_filename": "g.md", "step_key": "repo_typo", "step_order": "1"},
        ])
        with pytest.raises(script.SurveyTypesCsvError, match="repo_typo"):
            script.load_specs_from_csv(csv_path)

    def test_unreferenced_step_registry_key_warns_not_raises(self, script, monkeypatch, tmp_path, capsys):
        # The exact gap class that let repo_symbol_extraction silently fall
        # out of Repo Full Survey — a step in STEP_REGISTRY with zero CSV
        # references anywhere should be visible, but must not block
        # generation of everything else.
        monkeypatch.setattr(
            script, "STEP_REGISTRY", {"repo_a": object(), "repo_orphan": object()},
        )
        csv_path = tmp_path / "specs.csv"
        _write_csv(csv_path, [
            {"survey_kind": "k", "survey_group": "G", "survey_display_name": "G",
             "description": "d", "output_filename": "g.md", "step_key": "repo_a", "step_order": "1"},
        ])
        specs = script.load_specs_from_csv(csv_path)  # must not raise
        assert len(specs) == 1
        assert "repo_orphan" in capsys.readouterr().out

    def test_real_csv_matches_step_registry_with_no_unreferenced_warning(self, script, capsys):
        """Regression guard against the real, committed
        docs/dr-egeria/repo_survey_types.csv going stale the same way the
        generated docs did — the real STEP_REGISTRY, the real CSV."""
        specs = script.load_specs_from_csv()
        assert "WARNING" not in capsys.readouterr().out
        full = next(s for s in specs if s.survey_group == "RepoFullSurvey")
        assert set(full.step_keys) == set(script.STEP_REGISTRY.keys())
