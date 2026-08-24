"""Tests for WebsiteIngestionSurveyor's persistence, added when the step was
wired into the Analysis Survey (2026-08-20).

The discovery logic these results depend on is tested separately and without
network in tests/test_site_discovery.py. What is covered here is the part that
makes the step visible: it must write a `website_ingestion` metric on *every*
terminal path, not only when it ingests something.

That matters because three of this step's outcomes are legitimate zeros — no
homepage derived yet, the repo builds its own site (so the source is already
ingested in a better form), and discovery finding nothing. Persisting only on
success would render all three identically to "never run", which is the reading
most likely to prompt someone to "fix" a duplicate ingest we deliberately avoid.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.website_ingestion import (
    WebsiteIngestionSurveyor,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


def _project(registry, homepage=""):
    p = Project(slug="myproj", display_name="My Proj",
                github_url="https://github.com/o/myproj", description="",
                homepage_url=homepage)
    registry.add(p)
    return p


def test_no_homepage_still_records_a_result_with_its_reason(registry):
    project = _project(registry, homepage="")

    annotations = WebsiteIngestionSurveyor(project, registry).run()

    assert len(annotations) == 1
    m = registry.query_metrics("myproj", "website_ingestion")
    assert m["chunks"] == 0
    # The reason is the whole point — a bare zero is indistinguishable from
    # a failed run, and this outcome is neither a failure nor final.
    assert (m.get("detail") or {}).get("reason") == "no_homepage"


def test_repo_that_publishes_its_own_site_records_the_skip_and_its_marker(registry):
    """egeria-docs is the real instance: it builds egeria-project.org, which
    four registered repos declare as their homepage. Ingesting the rendered
    HTML would duplicate content already held as source markdown."""
    project = _project(registry, homepage="https://egeria-project.org")
    registry.upsert_file_inventory("myproj", [("site/mkdocs.yml", 10)])

    annotations = WebsiteIngestionSurveyor(project, registry).run()

    assert "Skipped" in annotations[0].summary
    detail = registry.query_metrics("myproj", "website_ingestion").get("detail") or {}
    assert detail["reason"] == "self_published"
    assert detail["marker"] == "site/mkdocs.yml"


def test_results_reader_surfaces_the_skip_rather_than_a_bare_zero(registry):
    """The Analysis card reads this, so the distinction has to survive the
    round-trip through the registry, not just exist at annotation time."""
    from resource_explorer.surveyors.repo_survey_definition_adapter import ANALYSIS_KINDS

    project = _project(registry, homepage="https://egeria-project.org")
    registry.upsert_file_inventory("myproj", [("site/mkdocs.yml", 10)])
    WebsiteIngestionSurveyor(project, registry).run()

    kind = ANALYSIS_KINDS["website_ingestion"]
    results = kind.results.results_reader(registry, "myproj")
    assert results["reason"] == "self_published"

    headline = kind.results.headline_reader(results)
    # Reported as ok, not as a shortfall: this is a correct final answer.
    assert headline["status"] == "ok"
    assert "repo source" in headline["label"]
