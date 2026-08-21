"""The shared vocabulary for what a survey step actually achieved.

A step can complete, report success, and have produced nothing meaningful — and
that outcome is indistinguishable from a correct empty answer, because both are
a zero. Four separate bugs this session took that shape, in three different
subsystems, and none of them raised:

  * `repo_website_ingestion` reported success having embedded one chunk, then
    "0 chunks from 1 page" against a meta-refresh stub.
  * The file-inventory readers reported against whatever an earlier, unrelated
    run had left in the table.
  * A coupling run read source files from a `--no-checkout` clone whose root
    holds only `.git`, scanned an empty tree, and proposed zero components.
  * A coupling import graph came back 89% empty because a resolution bug
    pointed it at the wrong copy of a duplicated package.

Every one of those looks exactly like "this repo genuinely has nothing".

Three parts of this codebase independently invented a vocabulary for the
distinction — this module's `reason` strings, arch-recovery's
`run_scope`/`partial`, and `docs/approach-portfolio-model.md` §3. Egeria has the
concept already: a governance service completes by producing a **guard**, a
label the process can route on. This is that vocabulary, adopted from §3 because
it was derived from real failure modes rather than first principles.

**Outcome and cause are separate fields, and that is forced, not preferred.**
Egeria's `NextGovernanceActionProcessStepProperties` carries exactly
`guard: Optional[str]` and `mandatory_guard: Optional[bool]` — a flat token, no
structured payload. So the outcome is the routable label and the cause travels
in the finding/metric row beside it. `self_published` and `code_host` are both
`no_signal`, for different reasons worth keeping.

**Recording only, for now.** Branching is a deliberate v1 boundary in
`survey_definition_reader` (see docs/survey-definitions.md), deferred by
decision on 2026-08-21. Nothing routes on these labels yet; they make a zero
legible. Guards on authored links stay `Any` until branching is wanted.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# The five, from docs/approach-portfolio-model.md §3.
RECOVERED = "recovered"     # produced what the step claims to
PARTIAL = "partial"         # produced something, knowingly incomplete
NO_SIGNAL = "no_signal"     # genuinely nothing to find — and provably so
UNVERIFIED = "unverified"   # could not run, or ran with nothing to validate against
REGRESSION = "regression"   # worse than a previous run on the same target

OUTCOMES = (RECOVERED, PARTIAL, NO_SIGNAL, UNVERIFIED, REGRESSION)

# Outcomes that mean "the step's answer can be relied on as complete".
CONCLUSIVE = frozenset({RECOVERED, NO_SIGNAL})


class InvalidOutcome(ValueError):
    """Raised when an outcome is not expressible — see StepOutcome's rule."""


@dataclass(frozen=True)
class StepOutcome:
    """What a step achieved, in the shared vocabulary.

    The rule this type exists to enforce, from §3:

        An approach with no known-positive check cannot report `no_signal`,
        only `unverified`.

    A zero means either the thing is genuinely absent or the method is broken,
    and nothing distinguishes those without something that *would* have been
    found had the method worked. Claiming `no_signal` without one is claiming
    knowledge the run does not have.

    It is enforced in the constructor rather than checked by a caller, because
    the failure it prevents is silent by nature: the wrong label produces a
    plausible row that a later reader trusts. The coupling import graph that came
    back 89% empty is exactly this — recorded as a plain zero it read as "this
    repo has no structure", and the grid looked twice as informative as it was.

    `cause` is free-text and step-specific (`self_published`, `code_host`,
    `no_homepage`, `empty_file_inventory`). It is deliberately not enumerated:
    the outcome set is small and shared so it can be queried across steps, while
    causes are local knowledge and forcing them into a common enum would either
    balloon the enum or flatten real distinctions.
    """

    outcome: str
    cause: str = ""
    #: Whether this run had something that would have been found if the method
    #: worked. Only meaningful for a zero result; see the rule above.
    known_positive: bool = False
    detail: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES:
            raise InvalidOutcome(
                f"unknown outcome {self.outcome!r}; expected one of {', '.join(OUTCOMES)}")
        if self.outcome == NO_SIGNAL and not self.known_positive:
            raise InvalidOutcome(
                "no_signal requires known_positive=True — without a known-positive check a "
                "zero is indistinguishable from a broken method, so the honest label is "
                "'unverified'. Pass known_positive=True only when this run had something "
                "that would have been found had the step worked."
            )

    @property
    def is_conclusive(self) -> bool:
        """True when the answer can be relied on as complete."""
        return self.outcome in CONCLUSIVE

    def as_row(self) -> dict[str, Any]:
        """The fields to persist alongside a finding or metric.

        Flat, and prefixed, so it can be added to any existing detail dict
        without colliding with a step's own keys.
        """
        return {
            "outcome": self.outcome,
            "outcome_cause": self.cause,
            "outcome_known_positive": self.known_positive,
            **({"outcome_detail": self.detail} if self.detail else {}),
        }


def no_signal(cause: str, *, known_positive: bool, **detail: Any) -> StepOutcome:
    """A zero that is the real answer — if it can be shown to be.

    Takes `known_positive` as a required keyword rather than defaulting it,
    so that claiming a provable zero is always a deliberate act at the call
    site. Falls back to `unverified` rather than raising when the caller
    honestly has no known-positive: the point is to record the weaker
    guarantee, not to block the run.
    """
    if not known_positive:
        return StepOutcome(UNVERIFIED, cause=cause, known_positive=False, detail=detail)
    return StepOutcome(NO_SIGNAL, cause=cause, known_positive=True, detail=detail)
