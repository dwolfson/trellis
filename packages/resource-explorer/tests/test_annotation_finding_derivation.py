"""The finding row is DERIVED from the annotation, not typed again beside it.

Written for the security_hygiene migration (2026-09-02), the first surveyor
moved onto `check_name`/`label`. The bug these pin is not hypothetical: before
the migration the SECURITY.md check emitted an annotation at confidence=90 and
stored a finding that omitted confidence, so project_analysis_findings
defaulted it to 100. Same check, same run, two stores, two numbers, and
nothing anywhere raised — which is why it survived.

Each test below was run against the pre-migration surveyor and observed to
fail, so a green result here means the derivation holds rather than that the
check did not fire.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors.sub_surveyors.security_hygiene import (
    SecurityHygieneSurveyor,
)
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    RequestForActionAnnotation,
    annotation_qualified_name,
    finding_from_annotation,
    findings_from_annotations,
)


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="myproj", display_name="My Project",
                github_url="https://github.com/test/myproj", collections=[])
    registry.add(p)
    return p


def _seed(registry, slug, *paths):
    with registry._conn() as conn:
        for path in paths:
            conn.execute(
                "INSERT INTO project_file_inventory (project_slug, file_path, indexed_at) "
                "VALUES (?, ?, ?)", (slug, path, "2026-01-01T00:00:00"))


class TestTheDriftIsGone:
    def test_the_security_md_check_reports_one_confidence_not_two(self, registry, project):
        """The exact drift: annotation said 90, the finding row said 100."""
        _seed(registry, "myproj", "src/a.py")          # no SECURITY.md
        annotations = SecurityHygieneSurveyor(project, registry).run()

        rfa = next(a for a in annotations
                   if isinstance(a, RequestForActionAnnotation)
                   and a.check_name == "security_policy")
        assert rfa.confidence == 90, "fixture assumption: the RFA is emitted at 90"

        row = next(f for f in registry.query_findings("myproj", "security_hygiene")
                   if f["check_name"] == "security_policy")
        assert row["confidence"] == rfa.confidence == 90

    def test_no_check_disagrees_with_its_own_annotation(self, registry, project):
        """The general form — every stored row matches the annotation it came
        from on every field both records carry."""
        _seed(registry, "myproj", "src/a.py")
        annotations = SecurityHygieneSurveyor(project, registry).run()
        rows = {f["check_name"]: f
                for f in registry.query_findings("myproj", "security_hygiene")}

        labelled = [a for a in annotations if a.label]
        assert labelled, "fixture assumption: the surveyor emits labelled annotations"
        for a in labelled:
            row = rows[a.check_name]
            assert row["confidence"] == a.confidence, a.check_name
            assert row["summary"] == a.summary, a.check_name
            assert row["label"] == a.label, a.check_name

    def test_the_explanation_survives_into_the_finding(self, registry, project):
        """Previously dropped: the annotation carried an explanation and the
        hand-written finding had nowhere to put it."""
        _seed(registry, "myproj", "src/a.py")
        SecurityHygieneSurveyor(project, registry).run()
        row = next(f for f in registry.query_findings("myproj", "security_hygiene")
                   if f["check_name"] == "security_policy")
        detail = json.loads(row["detail_json"])
        assert "vulnerabilities responsibly" in detail["explanation"]

    def test_the_unverified_early_return_still_leaves_a_row(self, registry, project):
        """An empty inventory is a result, not a silence — and it goes through
        the same derived path as a completed run."""
        annotations = SecurityHygieneSurveyor(project, registry).run()   # no inventory
        rows = registry.query_findings("myproj", "security_hygiene")
        assert [r["check_name"] for r in rows] == ["inventory_available"]
        assert rows[0]["label"] == "unverified"
        assert rows[0]["confidence"] == annotations[0].confidence


class TestDerivationItself:
    def test_an_unlabelled_annotation_is_not_a_finding(self):
        """A measure or a warning has no verdict, so it must not be stored as
        one with an empty label."""
        labelled = ClassificationAnnotation(summary="s", analysis_step="x",
                                            check_name="c", label="pass")
        unlabelled = ClassificationAnnotation(summary="s", analysis_step="x")
        assert len(findings_from_annotations([labelled, unlabelled])) == 1

    def test_the_rfa_action_pair_reaches_the_detail(self):
        row = finding_from_annotation(RequestForActionAnnotation(
            summary="No LICENSE", analysis_step="x", check_name="license",
            label="gap", action_requested="Add one", action_target_name="LICENSE"))
        assert row["detail"]["action_requested"] == "Add one"
        assert row["detail"]["action_target_name"] == "LICENSE"

    def test_a_key_collision_cannot_erase_the_typed_field(self):
        """A real collision, not a co-existence: json_properties carrying the
        same key must not overwrite the annotation's own structured answer."""
        row = finding_from_annotation(RequestForActionAnnotation(
            summary="s", analysis_step="x", check_name="c", label="gap",
            action_target_name="LICENSE",
            json_properties={"action_target_name": "WRONG", "cause": "none"}))
        assert row["detail"]["action_target_name"] == "LICENSE"
        assert row["detail"]["cause"] == "none"


class TestTheQualifiedNameIsNowStable:
    def test_the_same_check_gets_the_same_name_at_a_different_position(self, registry, project):
        """The reason for the whole change: the name used to be the enumeration
        index, and a check's position moves between runs."""
        a = RequestForActionAnnotation(summary="s", analysis_step="x",
                                       check_name="security_policy", label="gap")
        assert (annotation_qualified_name("P", 3, a)
                == annotation_qualified_name("P", 41, a)
                == "P::security_policy")

    def test_two_runs_of_the_surveyor_name_the_same_checks_the_same_way(self, registry, project):
        _seed(registry, "myproj", "src/a.py")
        first = SecurityHygieneSurveyor(project, registry).run()
        second = SecurityHygieneSurveyor(project, registry).run()
        names = lambda anns: sorted(annotation_qualified_name("P", i, a)
                                    for i, a in enumerate(anns))
        assert names(first) == names(second)
        assert len(set(names(first))) == len(first), "names must not collide"
