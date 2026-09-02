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


# ── D3: the complexity summary reaches the metric, per language ─────────────
#
# docs/code-volume-and-doc-coverage-design.md D3. This surveyor computed a
# per-language complexity summary, put it in the SchemaAnalysisAnnotation, and
# then persisted only symbol_count/relationship_count/by_language — so the
# question layer could never read it. "How complex?" was a GAP for a number
# that already existed at survey time.
#
# The guard matters as much as the feature, and was nearly missed. An earlier
# draft of the design doc claimed complexity was populated for all four
# languages "unlike docstrings", derived from
# `COUNT(*) WHERE complexity IS NOT NULL` — which counts a stored 0 as
# populated. The distribution says otherwise: go and javascript have exactly
# ONE distinct complexity value across 62,403 and 35,764 functions, because
# their extractors contain no `complexity=` assignment at all.
#
# Measured on milvus 2026-09-01:
#
#     naive average across all languages:  0.32   (n = 71,798)
#     guarded (python only):               2.69   (n =  8,662)
#
# 0.32 would read as trivially simple code for a distributed vector database,
# purely because 61,614 Go functions are recorded as zero.
class TestComplexityIsPersistedPerLanguage:
    def test_complexity_reaches_the_metric(self, registry, project):
        registry.upsert_code_symbols("apiproj", [
            _symbol(name="a", qualified_name="a", kind="function", complexity=5),
            _symbol(name="b", qualified_name="b", kind="function", complexity=1),
        ])
        ApiStructureSurveyor(project, registry).run()

        import json
        detail = registry.query_metrics("apiproj", "api_structure").get("detail")
        detail = json.loads(detail) if isinstance(detail, str) else (detail or {})
        assert detail["complexity_by_language"]["python"]["max"] == 5
        assert detail["complexity_by_language"]["python"]["avg"] == 3.0
        assert detail["complexity_by_language"]["python"]["measured_over"] == 2

    def test_a_language_that_never_computes_complexity_is_excluded_and_named(
            self, registry, project):
        """The known-negative. Drop _COMPLEXITY_CAPABLE_LANGUAGES and go's
        zeros enter the summary, reporting max=0 avg=0 for real code."""
        registry.upsert_code_symbols("apiproj", [
            _symbol(name="g", qualified_name="g", kind="function",
                    language="go", file_path="m.go", complexity=0),
            _symbol(name="p", qualified_name="p", kind="function", complexity=7),
        ])
        ApiStructureSurveyor(project, registry).run()

        import json
        detail = registry.query_metrics("apiproj", "api_structure").get("detail")
        detail = json.loads(detail) if isinstance(detail, str) else (detail or {})
        assert "go" not in detail["complexity_by_language"], (
            "go stores 0 for every symbol because its extractor never computes "
            "complexity — including it reports 'trivially simple' for unmeasured code"
        )
        assert detail["complexity_languages_not_measured"] == ["go"], (
            "an excluded language must be NAMED, not silently absent"
        )
        assert detail["complexity_by_language"]["python"]["max"] == 7

    def test_no_aggregate_across_languages_is_published(self, registry, project):
        """There must be no single repo-wide complexity number to misread.
        Averaging java and python is defensible; averaging in go's zeros is
        not, and one field invites the second."""
        registry.upsert_code_symbols("apiproj", [
            _symbol(name="p", qualified_name="p", kind="function", complexity=7),
        ])
        ApiStructureSurveyor(project, registry).run()

        metrics = registry.query_metrics("apiproj", "api_structure")
        assert "complexity" not in metrics, (
            "complexity must be reported per language only, never as one "
            f"repo-wide scalar: {metrics}"
        )
