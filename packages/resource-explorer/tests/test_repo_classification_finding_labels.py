"""A finding's `label` is rendered as a bold header over its `summary`
(`_factFindingLines` in web/static/index.html: `**{label}** — {summary}`).
Reported live 2026-09-07 (Dan, asking "what kind of thing is this
repository" on a documentation repo): every one of the per-artifact bullets
bold-headed "in-repo" — the near-constant outcome, repeated once per
artifact and telling a reader nothing — while `kind` (readme/api-reference/
deployment — the one field that actually differs per bullet) sat buried
mid-sentence. The `repo_role` finding had the same shape one level up:
`label=primary_role` while `summary` already led with that exact word,
rendering "**documentation** — documentation (also tutorial...)".

Pins two things per per-artifact loop (missing/found/confirmations/
unexpected): the label is the distinguishing `kind`, not a word repeated
across every item in that loop; and the summary no longer repeats it.
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
        slug="acme-docs", display_name="docs", github_url="https://github.com/acme/docs",
        status=ProjectStatus.ACTIVE,
    )


def _report() -> ExpectationReport:
    """Mirrors the live report: a documentation repo with several artifacts
    checked, at least one found, one missing, one confirmed, one unexpected —
    so every affected loop actually runs."""
    return ExpectationReport(
        owner_repo="acme/docs",
        primary_role="documentation",
        roles=["documentation", "tutorial", "application", "tool", "library"],
        found=[
            Expectation(kind="readme", outcome="in-repo", evidence="README.md",
                        date="2026-01-01", expected=True),
            Expectation(kind="api-reference", outcome="in-repo", evidence="docs/api.md",
                        date="2026-01-01", expected=False),
        ],
        missing=[Expectation(kind="changelog", outcome="not-found", evidence="",
                              date=None, expected=True)],
        confirmations=[Expectation(kind="deployment_manifest", outcome="not-found",
                                   evidence="", date=None, expected=False)],
        unexpected=[Expectation(kind="dockerfile", outcome="in-repo", evidence="Dockerfile",
                                date="2026-01-01", expected=False)],
        gate="run",
    )


def _run() -> list[dict]:
    reg = _Reg()
    with patch("resource_explorer.github.expectations.build_report", return_value=_report()):
        RepoClassificationSurveyor(_project(), reg).run()
    return reg.findings


def _first_word(text: str) -> str:
    return text.split()[0].rstrip(":") if text else ""


class TestFindingLabelsDoNotDuplicateTheirSummary:
    def test_repo_role_label_is_not_the_summary_s_leading_word(self):
        findings = _run()
        role = next(f for f in findings if f["check_name"] == "repo_role")
        assert role["label"] != "documentation"
        assert _first_word(role["summary"]) != role["label"]

    def test_found_artifacts_are_labeled_by_kind_not_by_the_shared_outcome(self):
        findings = _run()
        readme = next(f for f in findings if f["check_name"] == "expected_readme")
        api_ref = next(f for f in findings if f["check_name"] == "expected_api-reference")
        # The bug: both would have carried the SAME label ("in-repo") despite
        # being about two different artifacts — indistinguishable at a glance.
        assert readme["label"] == "readme"
        assert api_ref["label"] == "api-reference"
        assert readme["label"] != api_ref["label"]
        # And the summary no longer repeats the kind the label now carries.
        assert not readme["summary"].startswith("readme")

    def test_missing_artifact_is_labeled_by_kind_not_by_the_fixed_word(self):
        findings = _run()
        changelog = next(f for f in findings if f["check_name"] == "expected_changelog")
        assert changelog["label"] == "changelog"
        assert not changelog["summary"].startswith("changelog")

    def test_confirmation_is_labeled_by_kind_not_by_the_fixed_word(self):
        findings = _run()
        confirmed = next(f for f in findings if f["check_name"] == "confirmed_deployment_manifest")
        assert confirmed["label"] == "deployment_manifest"
        assert not confirmed["summary"].startswith("deployment_manifest")

    def test_unexpected_artifact_is_labeled_by_kind_not_by_the_shared_outcome(self):
        findings = _run()
        unexpected = next(f for f in findings if f["check_name"] == "unexpected_dockerfile")
        assert unexpected["label"] == "dockerfile"
        assert not unexpected["summary"].startswith("dockerfile")

    def test_rendered_bullets_have_no_repeated_leading_word(self):
        """End-to-end check mirroring _factFindingLines's own format string
        (`**{label}** — {summary}`) — the shape actually seen in chat."""
        findings = _run()
        for f in findings:
            rendered = f"{f['label']} — {f['summary']}"
            words = rendered.replace("—", " ").split()
            # The label (first token) must not reappear as the summary's own
            # first word — that exact adjacency is what "in-repo — in-repo"-
            # style duplication looked like live.
            if len(words) >= 2:
                assert words[0].lower() != words[1].lower(), (
                    f"{f['check_name']!r} renders with an immediately "
                    f"repeated word: {rendered!r}"
                )
