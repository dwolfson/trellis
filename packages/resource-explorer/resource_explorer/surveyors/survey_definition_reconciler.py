"""Survey Definition step-link reconciliation — docs/survey-question-context-plan.md
follow-up, born from a real live incident (2026-08-13).

Dr.Egeria's "Link First/Next Process Step" commands are NOT idempotent —
unlike "Create/Update Governance Action Process(Step)" (which merge-update
by qualified_name), re-running a Survey Definition's generated markdown
against an already-linked process creates a *brand new* NextProcessStep
relationship alongside the existing one, rather than replacing it. Left
unreconciled, a step ends up with more than one outgoing edge, and
SurveyDefinitionReader._parse_graph() correctly refuses to guess which one
is real — it raises UnsupportedSurveyDefinitionError ("branching ... not
supported"). That's the exact incident that surfaced this: regenerating
docs/dr-egeria/repo-survey-definition-*.md to add D1's ScopedBy Question
links (docs/survey-question-context-plan.md) meant re-running the *whole*
doc, including the pre-existing Link Next Process Step commands, which
duplicated every existing edge across all three repo Survey Definitions (1,
2, and 27 duplicate edges respectively). Repo Full Survey also had one
genuinely stale edge — repo_ci_quality -> repo_api_structure — left over
from before repo_maturity/repo_conventions were inserted into the chain by
an earlier change; a duplicate and a stale edge look identical to the
reader (a step with >1 outgoing edge), so both need reconciling the same
way.

This module is the pure, side-effect-free diff logic (the unit-testable
seam, matching survey_definition_reader.py's own _parse_graph convention)
— it decides *what* to delete. SurveyDefinitionReader.reconcile_step_links()
does the actual fetch + delete against live Egeria.
"""
from __future__ import annotations

from dataclasses import dataclass, field


def compute_expected_edges(survey_group: str, step_keys: list[str]) -> set[tuple[str, str]]:
    """The single linear chain of (prev_qualified_name, next_qualified_name)
    pairs a Survey Definition's step_keys, in order, should produce — same
    qualified_name convention dr_egeria_survey_publisher.py's
    _step_qualified_name() uses. A 0- or 1-step chain has no edges at all."""
    def qn(key: str) -> str:
        return f"GovActionProcessStep::{survey_group}::{key}"

    return {(qn(a), qn(b)) for a, b in zip(step_keys, step_keys[1:])}


@dataclass
class LinkToRemove:
    link_guid: str
    prev_qualified_name: str | None
    next_qualified_name: str | None
    reason: str  # "duplicate" | "stale"


@dataclass
class ReconcileResult:
    process_qualified_name: str
    kept: int = 0
    to_remove: list[LinkToRemove] = field(default_factory=list)
    error: str = ""

    @property
    def removed_duplicate(self) -> int:
        return sum(1 for r in self.to_remove if r.reason == "duplicate")

    @property
    def removed_stale(self) -> int:
        return sum(1 for r in self.to_remove if r.reason == "stale")

    @property
    def removed_total(self) -> int:
        return len(self.to_remove)


def diff_links(links: list[dict], expected_edges: set[tuple[str, str]], process_qualified_name: str) -> ReconcileResult:
    """Pure diff — no network calls. Given the raw `processStepLinks` list
    from GovernanceOfficer.get_governance_process_graph()'s response and the
    edges a Survey Definition's step chain should have, decide which live
    link relationships to keep vs. remove.

    For each expected edge, exactly the *first* matching live link is kept;
    any further live link with the same (prev, next) pair is a duplicate.
    Any live link whose (prev, next) pair isn't in expected_edges at all is
    stale (left over from a prior, different chain ordering). Idempotent —
    a fully-reconciled graph (each expected edge appearing exactly once,
    nothing else) produces an empty to_remove list."""
    result = ReconcileResult(process_qualified_name=process_qualified_name)
    seen_edges: set[tuple[str, str]] = set()

    for link in links:
        prev = (link.get("previousProcessStep") or {}).get("uniqueName")
        nxt = (link.get("nextProcessStep") or {}).get("uniqueName")
        link_guid = link.get("nextProcessStepLinkGUID")
        edge = (prev, nxt)

        if edge not in expected_edges:
            result.to_remove.append(LinkToRemove(link_guid, prev, nxt, "stale"))
        elif edge in seen_edges:
            result.to_remove.append(LinkToRemove(link_guid, prev, nxt, "duplicate"))
        else:
            seen_edges.add(edge)
            result.kept += 1

    return result
