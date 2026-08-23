"""Tests for role-derived expectation sets (design §5.5b).

Offline and hermetic — the classification and lookup layers are stubbed, so
these test the expectation/gate LOGIC rather than GitHub. Live behaviour is
recorded in the module docstring and the commit that introduced it.
"""
from __future__ import annotations

import pytest

from resource_explorer.github import expectations as ex
from resource_explorer.github import repo_role as rr


def _classification(*roles_with_signals, notes=None):
    """Build a RepoRoleClassification from (role, [signal, ...]) pairs."""
    c = rr.RepoRoleClassification(owner_repo="acme/thing", notes=list(notes or []))
    for role, signals in roles_with_signals:
        result = rr.RoleResult(role=role)
        for s in signals:
            result.add(s, f"evidence for {s}")
        c.roles.append(result)
    return c


class TestRecoveryGate:
    """§5.5b: the gate keys on CONTAINMENT, not primacy. This is the
    correction that building the classifier forced."""

    def test_no_non_architectural_role_runs(self):
        c = _classification((rr.ROLE_APPLICATION, ["deployment-artifacts"]))
        gate, reason = ex.recovery_gate(c)
        assert gate == ex.RUN
        assert "no tutorial/samples/documentation" in reason

    def test_pure_docs_repo_skips(self):
        c = _classification((rr.ROLE_DOCUMENTATION, ["documentation-dominance"]))
        gate, reason = ex.recovery_gate(c)
        assert gate == ex.SKIP
        assert "wrong question" in reason

    def test_tutorial_PRIMARY_still_runs_when_structural_evidence_exists(self):
        """The `odpi/egeria-workspaces` case, and the whole reason the gate
        does not read the primary role: it ranks `tutorial` first AND is
        target T1, from which architecture recovery scored 18/27. A gate on
        primacy would skip the repo we recovered most successfully."""
        c = _classification(
            (rr.ROLE_TUTORIAL, ["ipynb-ratio", "tutorial-sample-dirs"]),
            (rr.ROLE_APPLICATION, ["deployment-artifacts"]),
        )
        gate, reason = ex.recovery_gate(c)
        assert gate == ex.RUN
        assert "there is an architecture here" in reason

    def test_tutorial_with_no_structural_evidence_skips(self):
        c = _classification((rr.ROLE_TUTORIAL, ["ipynb-ratio", "readme-stated-intent"]))
        assert ex.recovery_gate(c)[0] == ex.SKIP

    @pytest.mark.parametrize("signal", ["deployment-artifacts", "entry-points", "package-manifest"])
    def test_any_structural_signal_is_enough_to_run(self, signal):
        c = _classification((rr.ROLE_SAMPLES, ["tutorial-sample-dirs"]),
                            (rr.ROLE_LIBRARY, [signal]))
        assert ex.recovery_gate(c)[0] == ex.RUN

    def test_a_documentation_only_signal_is_not_structural(self):
        c = _classification((rr.ROLE_DOCUMENTATION, ["documentation-dominance",
                                                     "readme-stated-intent"]))
        assert ex.recovery_gate(c)[0] == ex.SKIP


class TestExpectationSets:
    def test_library_does_not_expect_deployment_and_absence_confirms(self):
        """Absence cuts both ways — `trellis.md` records exactly this: "no
        Dockerfiles, no compose files ... no deployment perspective at all"
        CONFIRMS the library role rather than counting against the project."""
        expected, not_expected = ex.expectations_for(rr.ROLE_LIBRARY)
        assert "deployment" not in expected
        assert "deployment" in not_expected

    def test_application_expects_deployment(self):
        expected, _ = ex.expectations_for(rr.ROLE_APPLICATION)
        assert "deployment" in expected and "architecture" in expected

    def test_unknown_role_yields_no_expectations_rather_than_a_guess(self):
        assert ex.expectations_for(None) == ((), ())
        assert ex.expectations_for("not-a-role") == ((), ())

    def test_every_expected_kind_is_resolvable(self):
        """An expectation no signal can resolve would report as a permanent
        absence and read as a defect in the PROJECT rather than in the table."""
        from resource_explorer.github import doc_locations as dl
        known = set(dl._ARTIFACT_KEYWORDS)
        for role, kinds in ex.EXPECTED.items():
            assert set(kinds) <= known, f"{role} expects unresolvable {set(kinds) - known}"
        for role, kinds in ex.NOT_EXPECTED.items():
            assert set(kinds) <= known, f"{role} not-expects unresolvable {set(kinds) - known}"


class TestReportShape:
    def test_no_score_is_exposed(self):
        """§5.5a(c)/§5.5b: a checklist becomes a score, and a score punishes
        deliberate choices. The report exposes four named lists and no tally."""
        fields = set(ex.ExpectationReport.__dataclass_fields__)
        for banned in ("score", "grade", "rating", "maturity", "percentage", "count"):
            assert not any(banned in f for f in fields), f"{banned!r} leaked into the report"

    def test_four_states_are_kept_separate(self):
        fields = set(ex.ExpectationReport.__dataclass_fields__)
        assert {"found", "missing", "confirmations", "unexpected"} <= fields
