"""The deployment topology view, and the three ways it would overclaim.

Design reference: docs/architecture-recovery-design.md §5.5f. Ports and wires
come from deployment artifacts only — Dockerfile EXPOSE, compose
ports/expose/depends_on, OpenAPI documents — and each of the rules below exists
because the obvious rendering states something the data does not support.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_HTML = pathlib.Path(__file__).parent.parent / "resource_explorer" / "web" / "static" / "index.html"


@pytest.fixture(scope="module")
def renderer() -> str:
    src = _HTML.read_text()
    m = re.search(r"function _renderDeploymentInterfaces\(deployments\) \{.*?\n\}", src, re.S)
    assert m, "the deployment topology renderer is missing"
    return m.group(0)


class TestItDoesNotClaimDataflow:
    """A wire is a compose `depends_on` — startup ordering, not traffic.
    `oneWay` is always true and frequency/dataExchanged are deliberately empty
    rather than invented, so the view must say what an arrow means instead of
    letting arrowheads imply it. A diagram overclaims persuasively."""

    def test_the_semantics_are_stated_in_words(self, renderer):
        assert "declared startup dependencies" in renderer.lower()

    def test_it_says_what_an_arrow_is_not(self, renderer):
        assert "not data flow" in renderer.lower()

    def test_edges_read_as_declarations(self, renderer):
        """"A depends on B" is the claim the evidence supports; "A → B" invites
        the reader to supply a direction of data that was never measured."""
        assert "depends on" in renderer


class TestItStatesItsOwnCoverage:
    """Coverage is partial by construction. Prometheus yields one port and zero
    wires — that must not read as a simple architecture."""

    def test_the_artifact_sources_are_named(self, renderer):
        for src in ("EXPOSE", "depends_on", "OpenAPI"):
            assert src in renderer, src

    def test_absence_is_explained_rather_than_implied(self, renderer):
        assert "not that nothing exists" in renderer.lower(), (
            "no wires means none were declared, not that none exist — and that "
            "belongs on the surface, not in a tooltip"
        )


class TestDeploymentsAreNeverMixed:
    def test_each_deployment_renders_separately(self, renderer):
        """egeria-workspaces declares 18 topologies across 26 artifacts. One
        graph over all of them would draw a system nobody runs."""
        assert "deployments.map" in renderer


class TestRestraintIsNotRenderedAsMissingData:
    def test_protocol_is_only_shown_when_stated(self, renderer):
        """The detector does not infer HTTP from port 8080 — convention dressed
        as evidence is how an unverifiable claim enters at the confidence of a
        measured one. Blank must render as blank, not as a gap."""
        assert "pt.protocol ?" in renderer, (
            "protocol must be conditional; a mostly-empty column reads as "
            "missing data rather than as restraint"
        )

    @pytest.mark.parametrize("banned", ["score", "grade", "maturity", "completeness", "%"])
    def test_no_scoring_vocabulary(self, renderer, banned):
        assert banned not in renderer.lower()


class TestReader:
    def test_deployment_name_comes_from_the_directory(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import _deployment_name
        assert _deployment_name("compose-configs/egeria-quickstart/egeria-quickstart.yaml") == "egeria-quickstart"
        # A bare docker-compose.yml must not collapse six stacks into one name.
        assert _deployment_name("compose-configs/optional/milvus/docker-compose.yml") == "milvus"
