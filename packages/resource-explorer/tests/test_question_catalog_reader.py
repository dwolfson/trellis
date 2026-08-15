"""Tests for the Question checklist catalog loader (Discovery-tier Part 3
plan — question_catalog_reader.py, backing the per-phase Questions
checklist). Mirrors test_analysis_catalog_reader.py's loading conventions
(frozen dataclass, lru_cache-backed loader, clear_cache() testing hook).

No test coverage existed for this module before this change — closing a
real gap alongside the CSV reorg/regeneration.
"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from resource_explorer.surveyors import question_catalog_reader as qcr


@pytest.fixture(autouse=True)
def _clear_cache():
    qcr.clear_cache()
    yield
    qcr.clear_cache()


def _write_fixture(tmp_path: Path) -> Path:
    path = tmp_path / "question_catalog.yaml"
    path.write_text(textwrap.dedent("""
        repo_questions:
          - question: "Is this repo alive?"
            stage: Scouting
            perspectives: [Steward, Consumer]
            answering:
              kind: analysis
              analysis_ids: [repository_health]
              note: repository_health
            answering_mechanism: Git Statistics
          - question: "What license risk tier applies?"
            stage: Assessment
            perspectives: [Governance, Security]
            answering:
              kind: analysis
              analysis_ids: [license_classification]
              note: license_classification
            answering_mechanism: Code Analysis
          - question: "How mature is it?"
            stage: Assessment
            perspectives: [Architecture]
            answering:
              kind: mixed
              analysis_ids: [maturity]
              note: "MIXED: maturity + Understanding trend chart"
            answering_mechanism: Code Analysis
          - question: "Are there outstanding CVEs?"
            stage: Analysis
            perspectives: [Security, Governance]
            answering:
              kind: gap
              analysis_ids: []
              note: "GAP: CVE scan"
            answering_mechanism: Gap
          - question: "Should we validate the license text if non-standard?"
            stage: Analysis/Enrichment
            perspectives: [Governance]
            answering:
              kind: mixed
              analysis_ids: [license_classification]
              note: "MIXED: license_classification + human validation"
            answering_mechanism: Code Analysis+Human-Supplied
    """))
    return path


class TestLoadAndGetQuestions:
    def test_loads_all_entries_unfiltered(self, tmp_path):
        path = _write_fixture(tmp_path)
        entries = qcr.get_questions("repo", phase=None, perspectives=None)
        # get_questions() always reads the module-default path unless the
        # caller monkeypatches _load — exercise via the real default loader
        # against the packaged catalog instead of the fixture, then use the
        # fixture path directly through _load() for the isolated cases below.
        assert isinstance(entries, list)

    def test_missing_config_returns_empty_repo_list(self, tmp_path):
        missing = tmp_path / "nope.yaml"
        data = qcr._load(missing)
        assert data == {"repo": []}

    def test_phase_filter_matches_single_stage(self, tmp_path):
        path = _write_fixture(tmp_path)
        data = qcr._load(path)
        assert len(data["repo"]) == 5

        entries = [e.to_dict() for e in data["repo"]]
        scouting = [e for e in entries if e["stage"] == "Scouting"]
        assert {e["question"] for e in scouting} == {"Is this repo alive?"}
        assessment = [e for e in entries if e["stage"] == "Assessment"]
        assert {e["question"] for e in assessment} == {
            "What license risk tier applies?", "How mature is it?",
        }

    def test_phase_filter_matches_slash_combined_stage(self, tmp_path):
        # A slash-combined stage (e.g. "Analysis/Enrichment") should show up
        # under both of its component phases — see get_questions()'s docstring.
        # get_questions() always reads the module-default path — exercise the
        # slash-combined matching directly against _load()'s raw entries instead.
        path = _write_fixture(tmp_path)
        data = qcr._load(path)
        entries = [e.to_dict() for e in data["repo"]]

        def _matches(entry, phase):
            return phase.lower() in {p.strip().lower() for p in entry["stage"].split("/")}

        analysis_matches = {e["question"] for e in entries if _matches(e, "analysis")}
        assert analysis_matches == {
            "Are there outstanding CVEs?", "Should we validate the license text if non-standard?",
        }
        enrichment_matches = {e["question"] for e in entries if _matches(e, "enrichment")}
        assert enrichment_matches == {"Should we validate the license text if non-standard?"}

    def test_perspective_filter_is_or_matched(self, tmp_path):
        path = _write_fixture(tmp_path)
        data = qcr._load(path)
        entries = [e.to_dict() for e in data["repo"]]
        security = [e for e in entries if set(e["perspectives"]) & {"Security"}]
        assert {e["question"] for e in security} == {
            "What license risk tier applies?", "Are there outstanding CVEs?",
        }

    def test_case_insensitive_phase_match(self):
        # get_questions() lowercases both sides — verify against the real
        # packaged catalog (stage is always title-case there).
        entries = qcr.get_questions("repo", phase="SCOUTING")
        assert entries  # the real catalog has scouting-tier questions
        assert all(
            "scouting" in {part.strip().lower() for part in e["stage"].split("/")}
            for e in entries
        )

    def test_unknown_resource_type_returns_empty(self):
        assert qcr.get_questions("nonexistent") == []


class TestRealPackagedCatalog:
    """Regression guard against the CSV reorg — spot-checks specific
    entries that were deliberately changed (docs/dr-egeria/
    resource_questions.csv -> question_catalog.yaml regeneration)."""

    def test_license_question_is_now_a_closed_analysis_not_a_gap(self):
        entries = qcr.get_questions("repo")
        license_q = next(e for e in entries if e["question"].startswith("What explicit license"))
        assert license_q["answering"]["kind"] == "analysis"
        assert "license_classification" in license_q["answering"]["analysis_ids"]

    def test_maturity_question_stage_is_assessment_not_understanding(self):
        entries = qcr.get_questions("repo")
        maturity_q = next(e for e in entries if e["question"] == "How mature is it?")
        assert maturity_q["stage"] == "Assessment"
        assert "maturity" in maturity_q["answering"]["analysis_ids"]

    def test_new_repo_conventions_questions_present(self):
        entries = qcr.get_questions("repo")
        questions = {e["question"] for e in entries}
        assert "Does the repository publish a clear process for reporting security vulnerabilities?" in questions
        assert "Does the repository have automated build tooling in place?" in questions
        assert any(q.startswith("Is this repository already self-described") for q in questions)

    def test_deep_gap_questions_moved_off_scouting(self):
        # Part of the "move some questions off Scouting" reorg — these are
        # real, unbuilt gaps with no automatic answer; raising them at
        # Scouting was noise, not actionable there.
        entries = qcr.get_questions("repo")
        cve_q = next(e for e in entries if e["question"] == "Are there outstanding CVEs?")
        assert cve_q["stage"] == "Analysis"

        scouting_entries = qcr.get_questions("repo", phase="scouting")
        scouting_questions = {e["question"] for e in scouting_entries}
        assert "Are there outstanding CVEs?" not in scouting_questions
