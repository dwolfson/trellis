"""API docstring coverage: a measure, and never a verdict or a zero.

Two independent things are pinned here, and each has cost real money to get
wrong elsewhere in this codebase.

**1. A language whose extractor cannot read documentation must not be
scored.** `go_symbol_extractor.py` and `js_symbol_extractor.py` hardcode
`docstring=""` at every assignment site. Go doc comments and JSDoc both
exist; neither is extracted. Measured against the live registry 2026-09-01,
on milvus:

    naive (all languages):  5,968 / 80,094  =  7.5%
    guarded (measurable):   5,968 /  8,607  = 69.3%

69,954 Go symbols, every one recorded as undocumented because nobody taught
the extractor to read `// Foo does...`. Reporting 7.5% would call a major
CNCF project essentially undocumented on the strength of a gap in our own
tooling — a fact about us wearing the clothes of a fact about them, and
landing on the most alarming value available rather than the quietest.

**2. Coverage is a measure, not a grade.** Dan, who wrote most of
egeria-python, on being shown its 55.8%:

    "the documentation I put in was where I thought it was most useful...
     quantity is not the same as usefulness."

So the figure must not become a quality label, must not move `quality_score`,
and must not raise a RequestForAction. A repo is not worse for having
documented the parts that needed it. See
docs/code-volume-and-doc-coverage-design.md D2a.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.documentation import DocumentationSurveyor


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="myproj", display_name="My Project",
                github_url="https://github.com/test/myproj", collections=[])
    registry.add(p)
    return p


def _seed_symbols(registry, slug, spec):
    """spec: {language: (public_total, public_documented)}.

    Uses the real CodeSymbol dataclass the extractors emit, not a dict —
    upsert_code_symbols reads attributes, so a dict would only prove the test
    fixture works.
    """
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol

    rows = []
    for lang, (total, documented) in spec.items():
        for i in range(total):
            rows.append(CodeSymbol(
                resource_slug=slug, file_path=f"src/{lang}/f{i}.x", language=lang,
                kind="function", name=f"{lang}_sym_{i}", qualified_name=f"{lang}.sym{i}",
                signature="()",
                docstring="Does a thing." if i < documented else "",
                start_line=1, end_line=2,
            ))
    registry.upsert_code_symbols(slug, rows)


def _coverage_annotation(anns):
    for a in anns:
        s = a.summary or ""
        if "docstring" in s or "coverage" in s.lower():
            return a
    return None


class TestExtractorBlindness:
    def test_a_go_only_repo_is_not_established_never_zero(self, registry, project):
        """The known-negative. Drop the _DOCSTRING_CAPABLE_LANGUAGES filter
        and this fails with '0.0%' — the naive implementation, and the one
        anybody would reach for."""
        _seed_symbols(registry, "myproj", {"go": (500, 0)})
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())

        assert ann is not None, "absence of the measure is not an answer either"
        assert "0.0%" not in (ann.summary or ""), (
            "a language we cannot read documentation for must never be "
            f"reported as 0% documented: {ann.summary!r}"
        )
        assert "not established" in (ann.summary or "").lower()
        assert ann.resource_properties.get("languages_not_measured") == ["go"]

    def test_a_mixed_repo_scores_only_what_it_can_read(self, registry, project):
        """milvus in miniature: Go dominates the symbol count and must not
        drag the denominator."""
        _seed_symbols(registry, "myproj", {"go": (900, 0), "python": (100, 70)})
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())

        assert ann.resource_properties["public_symbols"] == 100, (
            "Go symbols must not enter the denominator"
        )
        assert ann.resource_properties["coverage_pct"] == 70.0
        assert "go" in (ann.summary or ""), (
            "the excluded language must be NAMED — a percentage over 1 of 2 "
            "languages must not read like one over both"
        )

    def test_java_and_python_are_both_measured(self, registry, project):
        _seed_symbols(registry, "myproj", {"java": (100, 50), "python": (100, 90)})
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())
        assert ann.resource_properties["public_symbols"] == 200
        assert ann.resource_properties["coverage_pct"] == 70.0
        assert ann.resource_properties["languages_not_measured"] == []


class TestItIsAMeasureNotAVerdict:
    def test_coverage_does_not_move_the_quality_score(self, registry, project):
        """Known-negative for D2a: fold the ratio into `score` and this
        fails. Two repos identical but for their docstrings must carry the
        same documentation quality label."""
        _seed_symbols(registry, "myproj", {"python": (100, 100)})
        well = [a for a in DocumentationSurveyor(project, registry).run()
                if "quality" in (a.summary or "").lower()]

        reg2 = ProjectRegistry(db_path=str(registry.db_path))
        with reg2._conn() as conn:
            conn.execute("DELETE FROM project_code_symbols WHERE project_slug = ?", ("myproj",))
        _seed_symbols(reg2, "myproj", {"python": (100, 0)})
        sparse = [a for a in DocumentationSurveyor(project, reg2).run()
                  if "quality" in (a.summary or "").lower()]

        assert well and sparse
        assert well[0].summary == sparse[0].summary, (
            "docstring coverage must not change the documentation quality "
            f"label: {well[0].summary!r} vs {sparse[0].summary!r}"
        )

    def test_the_score_counts_only_artifacts_and_hygiene(self, registry, project):
        """The stronger form of the test above, and the reason it is here.

        `test_coverage_does_not_move_the_quality_score` compares two repos
        that differ in COVERAGE — so it passes against a break that adds a
        flat bonus for merely having a measurable language, which shifts both
        repos equally. Verified: adding `+ (1 if measurable else 0)` to
        `score` left all eight tests green.

        This pins the composition instead of a difference: signal_count must
        equal doc collections plus hygiene files exactly, so ANY additional
        term fails regardless of what it varies with.
        """
        _seed_symbols(registry, "myproj", {"python": (100, 100)})
        with registry._conn() as conn:
            for path in ("README.md", "CONTRIBUTING.md"):
                conn.execute(
                    "INSERT INTO project_file_inventory "
                    "(project_slug, file_path, file_size_bytes, indexed_at) "
                    "VALUES (?, ?, ?, ?)", ("myproj", path, 10, "2026-09-01"))

        findings = DocumentationSurveyor(project, registry).run() and \
            registry.query_findings("myproj", "documentation")
        quality = next(f for f in findings if f["check_name"] == "quality_score")
        import json
        detail = json.loads(quality["detail_json"] or "{}")

        expected = len(detail.get("doc_collection_types", [])) + len(detail.get("hygiene_files", []))
        assert detail["signal_count"] == expected, (
            "the documentation quality score must be composed of exactly "
            "doc-collection kinds plus hygiene files — nothing else, and in "
            f"particular not docstring coverage: {detail}"
        )

    def test_it_is_a_measure_annotation_not_a_classification(self, registry, project):
        """A ClassificationAnnotation asserts what something IS. This counts."""
        _seed_symbols(registry, "myproj", {"python": (100, 40)})
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())
        assert type(ann).__name__ == "ResourceMeasureAnnotation", (
            f"coverage must not be classified, only measured: got {type(ann).__name__}"
        )

    def test_low_coverage_raises_no_request_for_action(self, registry, project):
        """Nobody here knows which symbol deserved a docstring, and the
        author has said the distribution was deliberate."""
        _seed_symbols(registry, "myproj", {"python": (100, 5)})
        anns = DocumentationSurveyor(project, registry).run()
        rfas = [a for a in anns if "RequestForAction" in type(a).__name__]
        assert rfas == [], f"low coverage must not become a demand: {rfas}"

    def test_the_annotation_says_presence_is_not_usefulness(self, registry, project):
        """A reader three months from now should not have to find the design
        doc to learn what the number does and does not mean."""
        _seed_symbols(registry, "myproj", {"python": (100, 40)})
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())
        note = (ann.json_properties or {}).get("interpretation", "").lower()
        assert "usefulness" in note and "deliberate" in note


class TestTheDenominator:
    def test_private_symbols_are_excluded(self, registry, project):
        _seed_symbols(registry, "myproj", {"python": (10, 10)})
        with registry._conn() as conn:
            conn.execute(
                "UPDATE project_code_symbols SET is_private = 1, docstring = '' "
                "WHERE project_slug = ? AND name LIKE ?", ("myproj", "python_sym_9%"))
        ann = _coverage_annotation(DocumentationSurveyor(project, registry).run())
        assert ann.resource_properties["public_symbols"] == 9
        assert ann.resource_properties["coverage_pct"] == 100.0, (
            "an undocumented PRIVATE symbol must not lower public coverage"
        )
