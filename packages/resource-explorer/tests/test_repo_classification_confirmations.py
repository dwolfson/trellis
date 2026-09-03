"""confirmations/unexpected are two of only three things this module's own
docstring says it reports ("located artifacts, absent ones, and
*confirmations*") — and were computed, sent to Egeria's additionalProperties,
and never turned into local findings at all. Not a reader dropping a
persisted field (the usual shape this session's field-allowlist sweep found)
— one layer upstream: the writer's own finding-persistence loop only ever
looped `report.missing`/`report.found`.

Filed under docs/Backlog.md item 3's 31-reader sweep.
"""
from __future__ import annotations

from unittest.mock import patch

from resource_explorer.github.expectations import Expectation, ExpectationReport
from resource_explorer.registry import Project, ProjectStatus
from resource_explorer.surveyors.sub_surveyors.repo_classification import RepoClassificationSurveyor


class _Reg:
    def __init__(self):
        self.findings = None

    def upsert_finding(self, slug, kind, findings, surveyed_at=None):
        self.findings = findings


def _project() -> Project:
    return Project(
        slug="acme-widget", display_name="widget", github_url="https://github.com/acme/widget",
        status=ProjectStatus.ACTIVE,
    )


def _report() -> ExpectationReport:
    return ExpectationReport(
        owner_repo="acme/widget",
        primary_role="library",
        roles=["library"],
        found=[Expectation(kind="readme", outcome="in-repo", evidence="README.md",
                           date="2026-01-01", expected=True)],
        missing=[],
        confirmations=[Expectation(kind="deployment_manifest", outcome="not-found",
                                   evidence="", date=None, expected=False)],
        unexpected=[Expectation(kind="dockerfile", outcome="in-repo", evidence="Dockerfile",
                                date="2026-01-01", expected=False)],
        gate="run",
    )


class TestConfirmationsAndUnexpectedReachFindings:
    def test_a_confirmation_is_persisted_as_a_finding(self):
        reg = _Reg()
        with patch("resource_explorer.github.expectations.build_report", return_value=_report()):
            RepoClassificationSurveyor(_project(), reg).run()

        confirmed = [f for f in reg.findings if f["check_name"] == "confirmed_deployment_manifest"]
        assert len(confirmed) == 1, "the confirmations list was computed but never persisted"
        assert confirmed[0]["detail"]["kind"] == "deployment_manifest"

    def test_an_unexpected_artifact_is_persisted_as_a_finding(self):
        reg = _Reg()
        with patch("resource_explorer.github.expectations.build_report", return_value=_report()):
            RepoClassificationSurveyor(_project(), reg).run()

        unexpected = [f for f in reg.findings if f["check_name"] == "unexpected_dockerfile"]
        assert len(unexpected) == 1, "the unexpected list was computed but never persisted"
        assert unexpected[0]["detail"] == {"kind": "dockerfile", "outcome": "in-repo"}

    def test_no_confirmations_or_unexpected_produces_no_extra_findings(self):
        """The fix must not invent rows when the lists are genuinely empty."""
        reg = _Reg()
        report = _report()
        report.confirmations = []
        report.unexpected = []
        with patch("resource_explorer.github.expectations.build_report", return_value=report):
            RepoClassificationSurveyor(_project(), reg).run()

        assert not any(f["check_name"].startswith(("confirmed_", "unexpected_"))
                       for f in reg.findings)
