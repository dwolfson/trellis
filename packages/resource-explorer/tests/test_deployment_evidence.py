"""`deployment_evidence` — layer 1 of "Cataloguing in layers" (project owner,
2026-09-14): per declared distribution, whether deployment evidence exists,
and the verdict (application/library/unknown) that evidence supports.

Built zero-fetch: every signal read here comes from tables an earlier step
already wrote (repo_manifest_parse's `distribution`/`repo_conventions`
findings, `project_dependencies`, `project_file_inventory`). The tests pin
the three verdicts, the could_not_check branch (ambiguous shared Dockerfile
across multiple distributions), and the no-manifest-read state.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors import deployment_evidence as de


def _dist(name="pkg", ecosystem="python", scripts=None, packages=None, manifest="pyproject.toml"):
    return {"name": name, "ecosystem": ecosystem, "scripts": scripts or [],
            "packages": packages or [], "manifest": manifest}


class TestClassifyDistribution:
    def test_console_script_is_application_evidence(self):
        d = de.classify_distribution(
            _dist(scripts=["mytool"]), all_distributions=[_dist(scripts=["mytool"])],
            file_inventory_paths=[], docker_evidence_paths=[], dependency_rows=[],
        )
        assert d.verdict == de.APPLICATION
        assert any(e.kind == "console_script" for e in d.evidence)

    def test_no_evidence_is_library(self):
        d = de.classify_distribution(
            _dist(), all_distributions=[_dist()],
            file_inventory_paths=[], docker_evidence_paths=[], dependency_rows=[],
        )
        assert d.verdict == de.LIBRARY
        assert d.evidence == []

    def test_dunder_main_under_own_package_is_evidence(self):
        dist = _dist(packages=["mypkg"])
        d = de.classify_distribution(
            dist, all_distributions=[dist],
            file_inventory_paths=["mypkg/__main__.py", "other/__main__.py"],
            docker_evidence_paths=[], dependency_rows=[],
        )
        assert d.verdict == de.APPLICATION
        mains = [e for e in d.evidence if e.kind == "dunder_main"]
        assert mains and mains[0].path == "mypkg/__main__.py"

    def test_dockerfile_is_unambiguous_evidence_for_a_single_distribution(self):
        dist = _dist()
        d = de.classify_distribution(
            dist, all_distributions=[dist],
            file_inventory_paths=[], docker_evidence_paths=["Dockerfile"], dependency_rows=[],
        )
        assert d.verdict == de.APPLICATION
        assert any(e.kind == "dockerfile_present" for e in d.evidence)
        assert d.could_not_check == []

    def test_dockerfile_is_could_not_check_when_multiple_distributions_share_the_repo(self):
        dist1 = _dist(name="a", manifest="a/pyproject.toml")
        dist2 = _dist(name="b", manifest="b/pyproject.toml")
        d = de.classify_distribution(
            dist1, all_distributions=[dist1, dist2],
            file_inventory_paths=[], docker_evidence_paths=["Dockerfile"], dependency_rows=[],
        )
        assert d.verdict == de.LIBRARY, "an unattributed shared Dockerfile must not be credited to either distribution"
        assert d.could_not_check and d.could_not_check[0]["kind"] == "dockerfile_present"

    def test_compose_file_is_recognized_by_name(self):
        dist = _dist()
        d = de.classify_distribution(
            dist, all_distributions=[dist],
            file_inventory_paths=[], docker_evidence_paths=["docker-compose.yml"], dependency_rows=[],
        )
        assert any(e.kind == "compose_present" for e in d.evidence)

    def test_web_framework_dependency_is_corroborating_evidence(self):
        dist = _dist(manifest="pyproject.toml")
        d = de.classify_distribution(
            dist, all_distributions=[dist], file_inventory_paths=[], docker_evidence_paths=[],
            dependency_rows=[{"dep_name": "fastapi", "source_file": "pyproject.toml"}],
        )
        assert d.verdict == de.APPLICATION
        assert any(e.kind == "web_framework_dependency" for e in d.evidence)

    def test_cli_framework_dependency_alone_without_a_script_is_not_evidence(self):
        """A `click` dependency with no declared console script is weak on its
        own — it must not manufacture an application verdict alone."""
        dist = _dist(manifest="pyproject.toml", scripts=[])
        d = de.classify_distribution(
            dist, all_distributions=[dist], file_inventory_paths=[], docker_evidence_paths=[],
            dependency_rows=[{"dep_name": "click", "source_file": "pyproject.toml"}],
        )
        assert d.verdict == de.LIBRARY

    def test_consumers_in_repo_derived_from_other_distributions_own_manifest(self):
        lib = _dist(name="trellis-context", manifest="packages/trellis-context/pyproject.toml")
        app = _dist(name="resource-explorer", manifest="packages/resource-explorer/pyproject.toml")
        deps = [{"dep_name": "trellis-context", "source_file": "packages/resource-explorer/pyproject.toml"}]
        d = de.classify_distribution(
            lib, all_distributions=[lib, app], file_inventory_paths=[],
            docker_evidence_paths=[], dependency_rows=deps,
        )
        assert d.consumers_in_repo == ["resource-explorer"]

    def test_consumers_in_repo_is_none_without_a_manifest_path(self):
        dist = _dist(manifest="")
        d = de.classify_distribution(
            dist, all_distributions=[dist], file_inventory_paths=[],
            docker_evidence_paths=[], dependency_rows=[],
        )
        assert d.consumers_in_repo is None


class TestAssessARepo:
    def test_no_distribution_findings_reads_no_manifest_read(self):
        a = de.assess([], file_inventory_paths=[], docker_evidence_paths=[], dependency_rows=[])
        assert a.no_manifest_read is True
        assert a.distributions == []
        rows = a.as_findings()
        assert len(rows) == 1 and rows[0]["check_name"] == "coverage"
        assert rows[0]["label"] == "no_manifest_read"

    def test_mixed_verdicts_are_counted(self):
        findings = [
            {"detail": _dist(name="app", scripts=["cli"], manifest="app/pyproject.toml")},
            {"detail": _dist(name="lib", manifest="lib/pyproject.toml")},
        ]
        a = de.assess(findings, file_inventory_paths=[], docker_evidence_paths=[], dependency_rows=[])
        assert a.counts[de.APPLICATION] == 1
        assert a.counts[de.LIBRARY] == 1
        rows = a.as_findings()
        assert len(rows) == 3  # two distributions + coverage
        cov = [r for r in rows if r["check_name"] == "coverage"][0]
        assert "1 application" in cov["summary"] and "1 library" in cov["summary"]

    def test_every_distribution_row_carries_its_name_in_detail(self):
        findings = [{"detail": _dist(name="pkg")}]
        a = de.assess(findings, file_inventory_paths=[], docker_evidence_paths=[], dependency_rows=[])
        rows = [r for r in a.as_findings() if r["check_name"] == "distribution"]
        assert rows[0]["detail"]["name"] == "pkg"


# ── the surveyor, against the real registry ─────────────────────────────────

class TestTheSurveyor:
    @pytest.fixture
    def slug(self, request):
        import re
        return "de_" + re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]

    @pytest.fixture
    def reg(self, pg_registry, slug):
        from resource_explorer.registry import Project
        pg_registry.add(Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}"))
        return pg_registry

    def _run(self, reg, slug):
        from resource_explorer.surveyors.sub_surveyors.deployment_evidence import DeploymentEvidenceSurveyor
        return DeploymentEvidenceSurveyor(project=reg.get(slug), registry=reg).run()

    def test_no_distribution_rows_is_unverified_not_zero_distributions(self, reg, slug):
        anns = self._run(reg, slug)
        assert len(anns) == 1 and anns[0].check_name == "nothing_to_assess"
        assert anns[0].json_properties.get("outcome") == "unverified"
        rows = reg.query_findings(slug, "deployment_evidence")
        assert rows and rows[0]["label"] == "no_manifest_read"

    def test_a_single_distribution_with_a_console_script_reads_application(self, reg, slug):
        reg.upsert_finding(slug, "distribution", [{
            "check_name": "python:mytool", "label": "declared",
            "summary": "mytool distribution",
            "detail": {"name": "mytool", "ecosystem": "python", "scripts": ["mytool"],
                       "packages": [], "manifest": "pyproject.toml", "publish_workflow": ""},
        }], surveyed_at="2026-09-14T00:00:00")
        anns = self._run(reg, slug)
        assert {a.check_name for a in anns} == {"distribution", "coverage"}
        dist_ann = [a for a in anns if a.check_name == "distribution"][0]
        assert dist_ann.item_key == "mytool"
        assert dist_ann.candidate_classifications == [de.APPLICATION]

        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _deployment_evidence_headline, _deployment_evidence_results)
        res = _deployment_evidence_results(reg, slug)
        assert res["distributions"][0]["name"] == "mytool"
        assert res["distributions"][0]["verdict"] == de.APPLICATION
        h = _deployment_evidence_headline(reg, slug)
        assert "1 application" in h["label"]

    def test_never_run_is_a_status_envelope_not_content(self, reg, slug):
        from resource_explorer.facts import _has_content
        from resource_explorer.surveyors.repo_survey_definition_adapter import _deployment_evidence_results
        res = _deployment_evidence_results(reg, "no_such_repo_at_all")
        assert "_status" in res and not _has_content(res)


class TestItsAnnotationsPublish:
    """Same regression class dependency_support's #46 caught: a list-shaped
    check (one annotation per distribution) must carry a distinct item_key
    per row, or the publisher refuses the whole publish on a collision."""

    @pytest.fixture
    def slug(self, request):
        import re
        return "dep_" + re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:44]

    @pytest.fixture
    def reg(self, pg_registry, slug):
        from resource_explorer.registry import Project
        pg_registry.add(Project(slug=slug, display_name=slug, github_url=f"https://github.com/x/{slug}"))
        pg_registry.upsert_finding(slug, "distribution", [
            {"check_name": "python:a", "label": "declared", "summary": "a",
             "detail": {"name": "a", "ecosystem": "python", "scripts": ["a-cli"],
                        "packages": [], "manifest": "a/pyproject.toml", "publish_workflow": ""}},
            {"check_name": "python:b", "label": "declared", "summary": "b",
             "detail": {"name": "b", "ecosystem": "python", "scripts": ["b-cli"],
                        "packages": [], "manifest": "b/pyproject.toml", "publish_workflow": ""}},
        ], surveyed_at="2026-09-14T00:00:00")
        return pg_registry

    def test_multiple_distributions_publish_under_distinct_qualified_names(self, reg, slug):
        from resource_explorer.surveyors.sub_surveyors.deployment_evidence import DeploymentEvidenceSurveyor
        from resource_explorer.surveyors.survey_report import assert_unique_qualified_names
        anns = DeploymentEvidenceSurveyor(project=reg.get(slug), registry=reg).run()
        dists = [a for a in anns if a.check_name == "distribution"]
        assert len(dists) == 2
        assert_unique_qualified_names(f"Annotation::{slug}::2026-09-14T00:00:00", anns)
        keys = [a.item_key for a in dists]
        assert all(keys) and len(set(keys)) == len(keys)


class TestItIsWiredEverywhere:
    def test_step_kind_and_ownership(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, REPO_ANALYSIS_STEP_MAP, STEP_REGISTRY)
        assert "repo_deployment_evidence" in STEP_REGISTRY
        assert REPO_ANALYSIS_STEP_MAP["deployment_evidence"] == ["repo_deployment_evidence"]
        from resource_explorer.surveyors.repo_survey_definition_adapter import REPO_ANALYSIS_RESULTS_MAP
        assert "deployment_evidence" in REPO_ANALYSIS_RESULTS_MAP

    def test_the_step_fetches_nothing_so_discovery_is_honest(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        assert not (getattr(STEP_REGISTRY["repo_deployment_evidence"], "requires_resources", {}) or {})

    def test_the_catalog_entry_is_discovery(self):
        from resource_explorer.surveyors.analysis_catalog_reader import get_analyses
        e = {a["id"]: a for a in get_analyses("repo", include_egeria_live=False)}["deployment_evidence"]
        assert e["intent"] == "discovery"

    def test_it_is_in_the_discovery_survey(self):
        import csv
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / "docs" / "dr-egeria" / "repo_survey_types.csv"
        rows = [r for r in csv.DictReader(p.open()) if r["step_key"] == "repo_deployment_evidence"]
        assert {r["survey_group"] for r in rows} == {"RepoDiscoverySurvey"}
