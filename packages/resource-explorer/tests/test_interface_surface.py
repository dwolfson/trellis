"""What can be talked to, and whether the contract is written down.

Two catalog questions, one analysis, because the second is a finding ABOUT the
first. The distinction carrying the weight is evidence strength: a committed
openapi.yaml IS an HTTP contract; a fastapi dependency SUGGESTS one and may be
a test fixture, a dev tool, or one service in a monorepo.

Grounded in the real catalog rather than invented: 9 openapi/swagger files
across 4 repos and 32 .proto across 4, against 17 repos depending on an HTTP
framework and 22 on a CLI framework. The two sources disagree far more often
than they agree, which is why they are never merged into one verdict.
"""
from __future__ import annotations

import pytest

from resource_explorer.surveyors.sub_surveyors.interface_surface import (
    DECLARED,
    IMPLEMENTED,
    IMPLIED,
    SPECIFIED,
    detect,
)


def _by_name(findings):
    return {f["check_name"]: f for f in findings}


class TestEvidenceStrength:
    def test_a_committed_spec_is_specified(self):
        f = _by_name(detect(["spec/openapi.yml"], []))
        assert f["http_api"]["label"] == SPECIFIED
        assert f["published_spec"]["label"] == "yes"

    def test_a_dependency_alone_is_only_implied(self):
        """And explicitly NOT a published API. Answering "is there a published
        API?" from a framework dependency is the failure this separation
        exists to prevent."""
        f = _by_name(detect([], ["fastapi"]))
        assert f["http_api"]["label"] == IMPLIED
        assert f["published_spec"]["label"] == "no"
        assert "without a published contract" in f["published_spec"]["summary"]

    def test_a_spec_supersedes_the_weaker_duplicate(self):
        """With both signals present, the strong one stands alone — a repo
        should not be reported as having http_api twice at two confidences."""
        findings = detect(["spec/openapi.yml"], ["fastapi"])
        http = [f for f in findings if f["check_name"] == "http_api"]
        assert len(http) == 1 and http[0]["label"] == SPECIFIED

    def test_implied_findings_carry_lower_confidence(self):
        f = _by_name(detect(["api/openapi.json"], ["click"]))
        assert f["http_api"]["confidence"] > f["cli"]["confidence"]


class TestExcludedTrees:
    """Found by reading real output, not by reasoning about it.

    OpenLineage was reported as publishing a gRPC API on the strength of
    `integration/flink/flink1/src/test/resources/InputEvent.proto` and
    `.../src/test/proto/ProtobufTestEvent.proto` — Maven test fixtures whose
    filenames literally say Test.
    """

    def test_a_java_test_fixture_is_not_a_published_contract(self):
        findings = detect(
            ["integration/flink/flink1/src/test/resources/InputEvent.proto"], [])
        assert _by_name(findings)["published_spec"]["label"] == "no"

    def test_vendored_and_generated_trees_are_excluded(self):
        for path in ("node_modules/x/openapi.yaml", "vendor/y/api.proto",
                     "target/generated/openapi.json", "third_party/z/schema.graphql"):
            assert _by_name(detect([path], []))["published_spec"]["label"] == "no", path

    def test_examples_are_not_the_projects_own_contract(self):
        """OpenMetadata ships 7 example specs alongside one real one; counting
        the examples would not change the verdict but would misstate the
        evidence."""
        assert _by_name(detect(["ingestion/examples/openapi/sample.json"], []))[
            "published_spec"]["label"] == "no"

    def test_a_real_spec_beside_excluded_ones_still_counts(self):
        """The filter must remove noise without losing the contract —
        OpenMetadata's actual case."""
        findings = _by_name(detect([
            "ingestion/examples/openapi/sample.json",
            "openmetadata-service/src/main/resources/openapi.yml",
        ], []))
        assert findings["published_spec"]["label"] == "yes"
        assert findings["http_api"]["label"] == SPECIFIED


class TestHonestAbsence:
    def test_nothing_found_still_answers_the_published_question(self):
        """"No" is a real answer here, and the question deserves one."""
        f = _by_name(detect([], []))
        assert f["published_spec"]["label"] == "no"

    def test_spec_patterns_are_anchored(self):
        """A file merely CONTAINING "swagger" is not a swagger spec — a
        substring match would credit any vendored bundle."""
        assert _by_name(detect(["docs/swagger-ui-bundle.js"], []))[
            "published_spec"]["label"] == "no"


def _distribution(name="pyegeria", scripts=None, targets=None, table="[project.scripts]",
                  manifest="pyproject.toml", ecosystem="python"):
    return {"name": name, "ecosystem": ecosystem, "scripts": scripts or [],
            "script_targets": targets or {}, "script_table": table,
            "manifest": manifest, "packages": [], "version": ""}


def _deployment_evidence(evidence):
    return {"name": "pyegeria", "ecosystem": "python", "evidence": evidence,
            "consumers_in_repo": [], "could_not_check": []}


class TestTheThreeRungLadder:
    """§6 of SPEC-ACTIONABLE-AND-HONEST.md: declared beats implemented beats
    implied for the SAME interface kind, and each rung reads from stored
    facts — never a second parse of the manifest or a second file walk."""

    def test_a_declared_entry_point_beats_a_bare_dependency(self):
        """The exact defect the designer named: `cli — implied. Depends on
        click` on a repo whose own manifest names the entry point."""
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        f = _by_name(detect([], ["click"], dist, []))
        assert f["cli"]["label"] == DECLARED
        assert 'pyegeria = "pyegeria.cli:main" in [project.scripts]' in f["cli"]["summary"]
        assert f["cli"]["detail"]["spec_path"] == "pyproject.toml"

    def test_the_egeria_python_sentence(self):
        """The designer's expected sentence, verbatim modulo punctuation."""
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        f = _by_name(detect([], [], dist, []))
        evidence = f["cli"]["detail"]["evidence"][0]
        assert evidence["value"] == 'pyegeria = "pyegeria.cli:main" in [project.scripts]'

    def test_implemented_without_a_declared_entry_point(self):
        """A __main__.py under the distribution's own package, and no
        [project.scripts] entry at all — implemented, not implied, because
        deployment_evidence already recorded the fact."""
        de = [_deployment_evidence([{"kind": "dunder_main", "path": "pyegeria/__main__.py"}])]
        f = _by_name(detect([], ["click"], [], de))
        assert f["cli"]["label"] == IMPLEMENTED
        assert f["cli"]["detail"]["evidence"][0]["value"] == "pyegeria/__main__.py"

    def test_declared_beats_implemented_for_the_same_kind(self):
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        de = [_deployment_evidence([{"kind": "dunder_main", "path": "pyegeria/__main__.py"}])]
        findings = detect([], ["click"], dist, de)
        cli = [f for f in findings if f["check_name"] == "cli"]
        assert len(cli) == 1 and cli[0]["label"] == DECLARED

    def test_a_committed_spec_still_beats_a_declared_entry_point_for_a_different_kind(self):
        """http_api and cli are independent kinds — a spec for one must not
        suppress or alter the other's rung."""
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        f = _by_name(detect(["openapi.yaml"], [], dist, []))
        assert f["http_api"]["label"] == DECLARED
        assert f["cli"]["label"] == DECLARED
        assert f["published_spec"]["label"] == "yes"
        # An entry point is not a published CONTRACT — only the spec kind is.
        assert f["published_spec"]["detail"]["kinds"] == ["http_api"]

    def test_routes_could_not_check_when_nothing_records_them(self):
        """The honest half of the defect: a fastapi dependency with no
        openapi.yaml cannot be promoted to `implemented` because no
        Discovery-tier step records route decorators — reported, not
        guessed past."""
        f = _by_name(detect([], ["fastapi"]))
        assert f["http_api"]["label"] == IMPLIED
        routes = f["http_api"]["detail"]["routes"]
        assert routes is not None
        assert routes["could_not_check_reason"] == "route decorators are not recorded"
        assert "could not be checked" in f["http_api"]["summary"]

    def test_cli_implied_carries_no_could_not_check_note(self):
        """Unlike http_api, cli's implemented rung WAS checked (via
        deployment_evidence's dunder_main) and simply found nothing — that is
        a checked zero, not an unchecked gap, so no could_not_check_reason."""
        f = _by_name(detect([], ["click"], [], []))
        assert f["cli"]["label"] == IMPLIED
        assert f["cli"]["detail"]["routes"] is None

    def test_confidence_scale_declared_implemented_implied(self):
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        de = [_deployment_evidence([{"kind": "dunder_main", "path": "x/__main__.py"}])]
        declared = _by_name(detect([], [], dist, []))["cli"]
        implemented = _by_name(detect([], [], [], de))["cli"]
        implied = _by_name(detect([], ["click"], [], []))["cli"]
        assert declared["confidence"] > implemented["confidence"] > implied["confidence"]

    def test_item_keys_stay_unique_per_kind(self):
        """Never two rows for the same interface kind, whatever the mix of
        evidence — the list-shaped item_key contract test_annotation_check_
        names.py enforces at the surveyor layer."""
        dist = [_distribution(scripts=["pyegeria"], targets={"pyegeria": "pyegeria.cli:main"})]
        de = [_deployment_evidence([{"kind": "dunder_main", "path": "x/__main__.py"}])]
        findings = detect(["openapi.yaml"], ["click", "fastapi"], dist, de)
        names = [f["check_name"] for f in findings]
        assert len(names) == len(set(names))

    def test_none_passed_for_the_new_parameters_behaves_like_before(self):
        """Every pre-existing call site (and every test above this class)
        passes only (paths, deps) — the new parameters must default safely."""
        assert detect([], ["fastapi"]) == detect([], ["fastapi"], None, None)


class TestHeadlineWording:
    """The designer's exact headline (§6): "2 interfaces declared or
    implemented · 0 with a published contract" — a task, not a judgement."""

    @pytest.fixture
    def registry(self, tmp_path):
        from resource_explorer.registry import Project, ProjectRegistry
        r = ProjectRegistry(db_path=str(tmp_path / "t.db"))
        r.add(Project(slug="p", display_name="P", github_url="https://github.com/x/p", description=""))
        return r

    def test_declared_and_implemented_count_toward_the_headline(self, registry):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _interface_surface_headline,
        )

        registry.upsert_finding("p", "interface_surface", [
            {"check_name": "cli", "label": DECLARED, "summary": "declared", "detail": {}},
            {"check_name": "http_api", "label": IMPLEMENTED, "summary": "implemented", "detail": {}},
            {"check_name": "published_spec", "label": "no", "summary": "no spec", "detail": {"kinds": []}},
        ])
        h = _interface_surface_headline(registry, "p")
        assert h["label"] == "2 interfaces declared or implemented · 0 with a published contract"
        assert h["tone"] == "warn"

    def test_a_published_contract_is_counted_and_toned_good(self, registry):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _interface_surface_headline,
        )

        registry.upsert_finding("p", "interface_surface", [
            {"check_name": "http_api", "label": DECLARED, "summary": "declared", "detail": {}},
            {"check_name": "published_spec", "label": "yes", "summary": "yes",
             "detail": {"kinds": ["http_api"]}},
        ])
        h = _interface_surface_headline(registry, "p")
        assert h["label"] == "1 interface declared or implemented · 1 with a published contract"
        assert h["tone"] == "good"

    def test_implied_only_never_reaches_the_headline_as_declared(self, registry):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _interface_surface_headline,
        )

        registry.upsert_finding("p", "interface_surface", [
            {"check_name": "cli", "label": IMPLIED, "summary": "implied", "detail": {}},
            {"check_name": "published_spec", "label": "no", "summary": "no spec", "detail": {"kinds": []}},
        ])
        h = _interface_surface_headline(registry, "p")
        assert "implied, no published contract" in h["label"]

    def test_the_old_specified_label_still_counts_as_strong(self, registry):
        """Rows a survey run before this migration left in the table — read-
        side compatibility, per interface_surface.py's own SPECIFIED note."""
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            _interface_surface_headline,
        )

        registry.upsert_finding("p", "interface_surface", [
            {"check_name": "http_api", "label": "specified", "summary": "old label", "detail": {}},
            {"check_name": "published_spec", "label": "yes", "summary": "yes",
             "detail": {"kinds": ["http_api"]}},
        ])
        h = _interface_surface_headline(registry, "p")
        assert h["label"].startswith("1 interface declared or implemented")


class TestRegistration:
    def test_wired_and_tagged(self):
        from resource_explorer.surveyors.analysis_catalog_reader import (
            EGERIA_PERSPECTIVES, get_analyses,
        )
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS, REPO_ANALYSIS_RESULTS_MAP, STEP_REGISTRY,
        )

        assert "repo_interface_surface" in STEP_REGISTRY
        assert "interface_surface" in ANALYSIS_KINDS
        assert "interface_surface" in REPO_ANALYSIS_RESULTS_MAP
        entry = next(a for a in get_analyses("repo", include_egeria_live=False)
                     if a["id"] == "interface_surface")
        assert entry["intent"] == "discovery", "zero-fetch derivation is Discovery-tier"
        for p in entry["perspectives"]:
            assert p == "all" or p in EGERIA_PERSPECTIVES
