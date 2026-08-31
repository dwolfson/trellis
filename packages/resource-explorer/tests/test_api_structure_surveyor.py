"""Tests for ApiStructureSurveyor — AST-ownership-transfer plan Phase 4.

Confirms the surveyor's annotations now surface complexity and inheritance
data (previously RE had neither), and that it runs on already-populated
symbol/relationship data without doing any extraction itself.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.api_structure import ApiStructureSurveyor
from resource_explorer.surveyors.survey_report import ResourceMeasureAnnotation, SchemaAnalysisAnnotation


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="apiproj", display_name="API Proj", github_url="https://github.com/a/apiproj")
    registry.add(p)
    return p


def _symbol(**overrides):
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol
    defaults = dict(
        resource_slug="apiproj", file_path="mod.py", language="python",
        kind="function", name="f", qualified_name="f", signature="()",
        docstring="", start_line=1, end_line=2,
    )
    defaults.update(overrides)
    return CodeSymbol(**defaults)


class TestApiStructureSurveyor:
    def test_no_symbols_says_so_instead_of_returning_empty(self, registry, project):
        """Changed deliberately 2026-08-22 (step-outcome adoption). An empty
        annotation list is indistinguishable from the step never having run,
        and on the live registry 13 of 20 repos hit this path — with populated
        file inventories, so "no code" was the wrong reading."""
        results = ApiStructureSurveyor(project, registry).run()
        assert len(results) == 1
        assert results[0].json_properties["outcome"] == "unverified"

    def test_complexity_and_inheritance_surfaced(self, registry, project):
        symbols = [
            _symbol(kind="class", name="Base", qualified_name="Base"),
            _symbol(kind="class", name="Child", qualified_name="Child", bases=["Base"]),
            _symbol(
                kind="method", name="method", qualified_name="Child.method",
                parent_class="Child", complexity=7,
            ),
            _symbol(
                kind="function", name="helper", qualified_name="helper", complexity=3,
            ),
        ]
        registry.upsert_code_symbols("apiproj", symbols)

        results = ApiStructureSurveyor(project, registry).run()
        schema_annotations = [r for r in results if isinstance(r, SchemaAnalysisAnnotation)]
        measure_annotations = [r for r in results if isinstance(r, ResourceMeasureAnnotation)]

        assert len(schema_annotations) == 1  # one language: python
        python_annotation = schema_annotations[0]
        assert python_annotation.json_properties["complexity"]["max"] == 7
        assert python_annotation.json_properties["inheritance_edges"] == 1

        assert len(measure_annotations) == 1
        assert measure_annotations[0].resource_properties["relationship_count"] == 1
        assert "1 inheritance relationship(s)" in measure_annotations[0].summary

    def test_no_relationships_reports_zero(self, registry, project):
        registry.upsert_code_symbols("apiproj", [_symbol(kind="function", name="f", qualified_name="f")])
        results = ApiStructureSurveyor(project, registry).run()
        measure = next(r for r in results if isinstance(r, ResourceMeasureAnnotation))
        assert measure.resource_properties["relationship_count"] == 0
