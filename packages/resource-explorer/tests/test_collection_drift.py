"""Collection drift — what a project is now eligible for but does not ingest.

The bar here is precision, not recall. A check that reports 4,583 false
positives is a check nobody reads, and the first version of this module did
exactly that.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from resource_explorer.collection_drift import DriftFinding, detect_drift, enabled_types


def _registry(collections, paths):
    r = MagicMock()
    r.get.return_value = MagicMock(collections=collections)
    r.get_file_inventory.return_value = paths
    return r


class TestEnabledTypes:
    def test_per_project_naming(self):
        assert enabled_types("egeria_docs", ["egeria_docs_markdown_docs"]) == {"markdown_docs"}

    def test_shared_collection_naming(self):
        """Shared collections are '{type}_{something}' -- matching only the
        per-project shape would report web_docs missing on every project that
        uses the shared one."""
        assert "web_docs" in enabled_types("egeria_git", ["web_docs_egeria_project_org"])

    def test_unknown_names_are_ignored(self):
        assert enabled_types("x", ["something_unrelated"]) == set()


class TestPrecision:
    def test_examples_keys_on_directories_not_extensions(self):
        """Matching .java would make every source file in Egeria evidence for
        an 'examples' collection -- 4,583 of them on the real repo."""
        r = _registry(["x_markdown_docs"], ["src/main/java/Foo.java", "core/Bar.java"])
        assert [f.collection_type for f in detect_drift(r, "x")] == []

    def test_examples_is_found_when_the_directory_exists(self):
        r = _registry(["x_markdown_docs"], ["examples/demo.py", "samples/a.py"])
        assert "examples" in [f.collection_type for f in detect_drift(r, "x")]

    def test_api_reference_keys_on_spec_filenames(self):
        """A GitHub workflow YAML is not an OpenAPI spec."""
        r = _registry(["x_markdown_docs"], [".github/workflows/release.yml", "config/config.json"])
        assert "api_reference" not in [f.collection_type for f in detect_drift(r, "x")]

    def test_api_reference_is_found_for_a_real_spec(self):
        r = _registry(["x_markdown_docs"], ["docs/openapi.yaml"])
        assert "api_reference" in [f.collection_type for f in detect_drift(r, "x")]

    def test_release_notes_is_never_file_judged(self):
        """It declares .md/.txt but reads the GitHub releases API. Matching its
        extensions reported every markdown file in a docs repo."""
        r = _registry(["x_python_code"], ["README.md", "docs/a.md", "notes.txt"])
        assert "release_notes" not in [f.collection_type for f in detect_drift(r, "x")]


class TestReporting:
    def test_pdfs_are_reported_with_samples(self):
        r = _registry(["x_markdown_docs"], ["saved/a.pdf", "saved/b.pdf"])
        found = detect_drift(r, "x")
        pdfs = next(f for f in found if f.collection_type == "pdfs")
        assert pdfs.matching_files == 2
        assert pdfs.sample_paths == ("saved/a.pdf", "saved/b.pdf")
        assert "pdfs: 2 matching file(s)" in pdfs.summary

    def test_already_enabled_is_not_drift(self):
        r = _registry(["x_pdfs"], ["a.pdf"])
        assert detect_drift(r, "x") == []

    def test_no_inventory_is_not_drift(self):
        """A never-indexed project has nothing to be wrong about; reporting
        every collection type would be noise on a fresh add."""
        assert detect_drift(_registry([], []), "x") == []

    def test_unknown_project_is_not_an_error(self):
        r = MagicMock()
        r.get.return_value = None
        assert detect_drift(r, "nope") == []

    def test_findings_are_ordered_by_weight(self):
        r = _registry(["x_markdown_docs"], ["a.pdf"] + [f"examples/e{i}.py" for i in range(5)])
        found = detect_drift(r, "x")
        assert [f.matching_files for f in found] == sorted(
            [f.matching_files for f in found], reverse=True
        )
