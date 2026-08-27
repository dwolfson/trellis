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

from resource_explorer.surveyors.sub_surveyors.interface_surface import (
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
        assert "no contract is published" in f["published_spec"]["summary"]

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
