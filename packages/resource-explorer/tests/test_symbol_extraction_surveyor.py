"""Tests for SymbolExtractionSurveyor — D5 (docs/unified-survey-execution-
model-plan.md), the self-contained microflow closing the bug where
project_code_symbols was only ever populated by RAG ingestion, never by a
survey step.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.symbol_extraction import SymbolExtractionSurveyor
from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="symproj", display_name="Sym Proj", github_url="https://github.com/a/symproj")
    registry.add(p)
    return p


def test_extracts_python_symbols_and_upserts(tmp_path, registry, project):
    (tmp_path / "mod.py").write_text(
        "class Widget:\n    def render(self):\n        pass\n\n\ndef helper():\n    pass\n"
    )

    results = SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

    assert len(results) == 1
    assert isinstance(results[0], ResourceMeasureAnnotation)
    assert results[0].resource_properties["symbol_counts_by_language"]["python"] == 3  # class + method + function

    rows = registry.query_findings  # sanity: registry object still usable after run
    with registry._conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) as c FROM project_code_symbols WHERE project_slug = ?", ("symproj",)
        ).fetchone()["c"]
    assert count == 3


def test_no_matching_files_returns_zero_symbols(tmp_path, registry, project):
    (tmp_path / "README.md").write_text("nothing to extract here")

    results = SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

    assert len(results) == 1
    assert results[0].resource_properties["symbol_counts_by_language"] == {}


def test_rerun_clears_stale_symbols(tmp_path, registry, project):
    (tmp_path / "mod.py").write_text("def old_func():\n    pass\n")
    SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

    # Simulate the file being renamed/removed between runs.
    (tmp_path / "mod.py").unlink()
    (tmp_path / "mod2.py").write_text("def new_func():\n    pass\n")

    SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

    with registry._conn() as conn:
        names = [
            r["name"] for r in conn.execute(
                "SELECT name FROM project_code_symbols WHERE project_slug = ?", ("symproj",)
            ).fetchall()
        ]
    assert names == ["new_func"]


def test_accepts_surveyed_at_kwarg(tmp_path, registry, project):
    # Regression guard: StepInfo.accepts_surveyed_at=True means
    # SurveyOrchestrator always passes surveyed_at as a kwarg.
    surveyor = SymbolExtractionSurveyor(
        project, registry, local_path=str(tmp_path), surveyed_at="2026-01-01T00:00:00"
    )
    assert surveyor._surveyed_at == "2026-01-01T00:00:00"
