"""Suggested action — evidence into an answer (design §5.5d, §5.5d-i).

Offline: the expectation report is constructed directly, so these test the
derivation rather than GitHub.
"""
from __future__ import annotations

import dataclasses

from resource_explorer.github import suggested_action as sa
from resource_explorer.github import expectations as ex


def _report(**kw):
    base = dict(owner_repo="acme/thing", primary_role="application",
                roles=["application"], gate=ex.RUN, gate_reason="")
    base.update(kw)
    return ex.ExpectationReport(**base)


def _item(kind, outcome="in-repo", expected=True, date=None):
    return ex.Expectation(kind=kind, outcome=outcome, evidence="x", date=date,
                          expected=expected)


class TestGateDeclined:
    def test_a_skip_is_nothing_to_do_not_an_absence(self):
        """§5.5b: the gate is the funnel working. Rendering a skip as an empty
        or degraded result makes the system's biggest win look like a failure."""
        r = _report(gate=ex.SKIP, gate_reason="documentation role present and no "
                                              "structural evidence",
                    primary_role="documentation", roles=["documentation"])
        d = sa.from_report(r)
        assert d.action == sa.NOTHING_TO_DO
        assert "documentation role present" in d.reason
        assert d.next_step == "", "nothing to do means no action to offer"

    def test_the_gate_reason_travels_verbatim(self):
        r = _report(gate=ex.SKIP, gate_reason="a very specific reason")
        assert "a very specific reason" in sa.from_report(r).reason


class TestInsufficientEvidence:
    def test_unknown_role_is_not_nothing_to_do(self):
        """'We could not tell' and 'there is nothing to do' are different
        statements, and the first must not be dressed as the second."""
        r = _report(primary_role=None, roles=[], notes=["no role determined"])
        d = sa.from_report(r)
        assert d.action == sa.INSUFFICIENT_EVIDENCE
        assert d.action != sa.NOTHING_TO_DO
        assert d.next_step == "rfa"


class TestInvestigate:
    def test_missing_expected_artifacts_warrant_a_look(self):
        r = _report(missing=[_item("architecture", outcome="not-found"),
                             _item("changelog", outcome="not-found")])
        d = sa.from_report(r)
        assert d.action == sa.INVESTIGATE
        assert "architecture" in d.reason and "changelog" in d.reason

    def test_the_reason_names_the_artifacts_and_never_counts_them(self):
        """"3 of 5 present" is the score §5.5a(c) forbids, wearing a hat."""
        r = _report(missing=[_item("architecture", outcome="not-found")])
        reason = sa.from_report(r).reason
        assert "architecture" in reason
        for banned in (" of ", "%", "3 of 5"):
            assert banned not in reason.replace("part of", "")


class TestMonitor:
    def test_everything_located_means_watch_for_change(self):
        r = _report(found=[_item("readme", date="2026-08-01T00:00:00Z"),
                           _item("architecture", outcome="sibling-repo")])
        d = sa.from_report(r)
        assert d.action == sa.MONITOR
        assert d.next_step == "subscription", "watching is an Automate subscription"

    def test_confirmations_do_not_trigger_investigate(self):
        """A library having no deployment artifacts is CONFIRMATION of the
        role, not a gap — same observation, opposite meaning by role (§5.5b)."""
        r = _report(primary_role="library", roles=["library"],
                    found=[_item("readme")],
                    confirmations=[_item("deployment", outcome="not-found", expected=False)])
        assert sa.from_report(r).action == sa.MONITOR


class TestScopeIsOnTheRecord:
    def test_the_undecidable_dispositions_are_named_not_omitted(self):
        """§5.5d listed adopt/avoid/upgrade/replace/compare. None is derivable
        from what we collect, and each is named with what it would need so its
        absence reads as a scoped decision rather than an oversight."""
        assert set(sa.NOT_DERIVABLE) == {"adopt", "avoid", "upgrade", "replace", "compare"}
        assert "motivation" in sa.NOT_DERIVABLE["adopt"]
        assert "usage corpus" in sa.NOT_DERIVABLE["upgrade"]

    def test_no_numeric_field_exists(self):
        fields = {f.name for f in dataclasses.fields(sa.SuggestedAction)}
        for banned in ("score", "grade", "rating", "count", "percentage", "confidence"):
            assert not any(banned in f for f in fields), f"{banned!r} leaked in"

    def test_every_disposition_carries_a_reason(self):
        for r in (_report(gate=ex.SKIP, gate_reason="x"),
                  _report(primary_role=None, roles=[]),
                  _report(missing=[_item("architecture", outcome="not-found")]),
                  _report(found=[_item("readme")])):
            d = sa.from_report(r)
            assert d.reason and len(d.reason) > 20
            assert d.action in sa.ACTIONS


class TestTheSubscriptionCanActuallyFire:
    """A subscription only fires if an active schedule exists for the SAME
    analysis_id. One bound to a plausible-but-wrong id never fires, and never
    firing is indistinguishable from "nothing changed" — the absence-looks-like-
    zero shape this project keeps meeting. So the target is pinned to a real one.
    """

    def test_monitored_analysis_is_a_real_analysis_id(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import (
            ANALYSIS_KINDS,
        )
        assert sa.MONITORED_ANALYSIS in ANALYSIS_KINDS

    def test_monitor_names_what_it_watches(self):
        d = sa.from_report(_report(found=[_item("readme")]))
        assert d.next_step == "subscription"
        assert d.next_step_target == sa.MONITORED_ANALYSIS

    def test_a_next_step_never_goes_unaddressed(self):
        for r in (_report(gate=ex.SKIP, gate_reason="x"),
                  _report(primary_role=None, roles=[]),
                  _report(missing=[_item("architecture", outcome="not-found")]),
                  _report(found=[_item("readme")])):
            d = sa.from_report(r)
            assert bool(d.next_step) == bool(d.next_step_target), (
                f"{d.action}: a next step with no target cannot be acted on"
            )


class TestItIsNotTheHumanDisposition:
    """`registry.repo_dispositions` records what a PERSON decided about a repo
    (tracking/investigating/using/...). This module derives what the evidence
    supports. Two purposes under one name is this project's most-repeated bug,
    and the UI already renders the human one in a Disposition sub-tab — so the
    separation is pinned here rather than left to whoever reads the docstring.
    """

    def test_the_type_does_not_carry_a_disposition_field(self):
        fields = {f.name for f in dataclasses.fields(sa.SuggestedAction)}
        assert "disposition" not in fields
        assert "action" in fields

    def test_a_suggestion_is_not_a_valid_human_disposition_value(self):
        """If a suggestion were assignable straight into repo_dispositions, the
        arrow could silently reverse and the system would appear to have made a
        human's decision for them."""
        from resource_explorer.web.routes.discovery import _VALID_DISPOSITIONS
        assert not (set(sa.ACTIONS) & _VALID_DISPOSITIONS), (
            "overlap makes derived and decided indistinguishable downstream"
        )

    def test_the_near_synonyms_stay_distinguishable(self):
        """investigate/investigating and monitor/tracking are deliberately
        different words for the two sides of the same handoff."""
        from resource_explorer.web.routes.discovery import _VALID_DISPOSITIONS
        assert sa.INVESTIGATE == "investigate" and "investigating" in _VALID_DISPOSITIONS
        assert sa.MONITOR == "monitor" and "tracking" in _VALID_DISPOSITIONS
