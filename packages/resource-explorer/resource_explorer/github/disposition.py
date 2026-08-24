"""Disposition — turning evidence into an answer (design §5.5d, §5.5d-i).

The rest of this package produces *evidence*: what the repo is (`repo_role`),
where its expected artifacts live (`doc_locations`, `expectations`), and whether
architecture recovery is worth running. A **disposition** is what a decision
maker actually wants: *what should I do about this?*

**Deliberately a small vocabulary, and deliberately smaller than §5.5d's list.**
That list — adopt, avoid, monitor, upgrade, compare, expand — was written from
the *motivations* for looking at a repo. Most of those cannot be derived from
what we currently collect, and saying them anyway would be the failure this
project has spent its whole history avoiding: a confident answer to a question
the evidence does not reach.

| §5.5d disposition | derivable today? |
|---|---|
| monitor | **yes** — role + expectations + dates |
| investigate | **yes** — expected artifacts that are absent |
| nothing to do | **yes** — the gate declined, and that is a complete answer |
| adopt / avoid | **no** — needs *motivation* (§5.5d): "should we adopt this" is a different question from "what is this" |
| upgrade / replace | **no** — needs the second corpus §5.5d names: which version we run, which APIs we call, how deeply it is embedded. **None of that lives in the repo being surveyed** |
| compare with alternatives | **no** — needs a second resource |

The four that are derivable are implemented. The rest are named here with what
they would need, so their absence reads as a scoped decision rather than an
oversight — and so nobody adds them from the same evidence later.

**Three constraints, all carried from §5.5:**

* **A recommendation, not a verdict.** Every disposition carries the evidence
  that produced it and the reason in prose. It never implies the system decided.
* **No score, and no ranking.** §5.5a(c): a checklist becomes a score and a score
  punishes deliberate choices. There is no numeric field here and a test asserts
  it.
* **"Nothing to do" is a complete answer**, not an empty one — the same
  distinction `result_status.SKIPPED_BY_DESIGN` exists to make, and it reuses
  that vocabulary rather than inventing a parallel one.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from . import expectations as ex

# The four derivable today. Not an enum: §5.5d-i concluded this needs a new
# vocabulary (Egeria's `ResourceUse` is governance operations on metadata, not
# judgements about a resource), and a valid value set is the eventual home —
# §5.5b's "Recommended shape" paragraph applies here too.
NOTHING_TO_DO = "nothing-to-do"
MONITOR = "monitor"
INVESTIGATE = "investigate"
INSUFFICIENT_EVIDENCE = "insufficient-evidence"

DISPOSITIONS = (NOTHING_TO_DO, MONITOR, INVESTIGATE, INSUFFICIENT_EVIDENCE)

# Named so their absence is a decision on the record rather than a gap.
# The analysis whose re-run would change a disposition. `monitor` means "watch
# THIS", and naming it is not decoration: a notification subscription only fires
# if there is an active schedule for the same analysis_id, so a subscription
# created without one silently never fires — absence indistinguishable from
# "nothing changed", the bug family this project keeps meeting. A test asserts
# this is a real ANALYSIS_KINDS key rather than a plausible string.
MONITORED_ANALYSIS = "repo_classification"

NOT_DERIVABLE = {
    "adopt": "needs the user's motivation (§5.5d) — 'should we adopt this' is a "
             "different question from 'what is this'",
    "avoid": "needs motivation, and usually a comparison",
    "upgrade": "needs a usage corpus — which version we run, which APIs we call, "
               "how deeply it is embedded. None of it lives in the repo surveyed",
    "replace": "needs a usage corpus and a candidate alternative",
    "compare": "needs a second resource",
}


@dataclass
class Disposition:
    """One recommendation, with what produced it. No number, by design."""
    disposition: str
    reason: str
    evidence: list[str] = field(default_factory=list)
    # What this leads to, in mechanisms that already exist (§5.5d-i):
    # "subscription" (Automate), "rfa" (a human action), or "" (none).
    next_step: str = ""
    # Which analysis `next_step` refers to. Empty when there is no next step.
    # For "subscription" this is the analysis_id the subscription must be bound
    # to, and which must also have an active schedule, or it never fires.
    next_step_target: str = ""
    primary_role: str | None = None
    roles: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def from_report(report: ex.ExpectationReport) -> Disposition:
    """Derive a disposition from an expectation report.

    Ordered, and it stops at the first that fits — the same shape as §5.5b's
    role decision guide, for the same reason: an ordered list of falsifiable
    conditions is auditable where a weighted blend is not.
    """
    common = {
        "primary_role": report.primary_role,
        "roles": list(report.roles),
        "notes": list(report.notes),
    }

    # 1. The gate declined. This is the funnel working, and it is a COMPLETE
    #    answer — §5.5b's "it is a gate, not a weighting". Rendering it as an
    #    absence would make the system's biggest win look like a failure.
    if report.gate == ex.SKIP:
        return Disposition(
            disposition=NOTHING_TO_DO,
            reason=f"no further analysis is worthwhile: {report.gate_reason}",
            evidence=[report.gate_reason],
            next_step="",
            **common,
        )

    # 2. No role determined. Not "nothing to do" — we could not tell, which is a
    #    different statement and must not be dressed as the first.
    if not report.primary_role:
        return Disposition(
            disposition=INSUFFICIENT_EVIDENCE,
            reason="could not determine what this repository is, so no "
                   "recommendation follows from it",
            evidence=list(report.notes[:3]),
            next_step="rfa",
            next_step_target=MONITORED_ANALYSIS,
            **common,
        )

    # 3. Something the role implies is absent. Reported as the artifacts
    #    themselves, never as a count — "3 of 5 present" is the score §5.5a(c)
    #    forbids wearing a different hat.
    if report.missing:
        kinds = [m.kind for m in report.missing]
        return Disposition(
            disposition=INVESTIGATE,
            reason=(f"a {report.primary_role} would normally have "
                    f"{', '.join(kinds)}; not found in this repo, in a sibling "
                    f"repo, or on the project's documentation site"),
            evidence=[f"{m.kind}: not-found" for m in report.missing],
            next_step="rfa",
            next_step_target=MONITORED_ANALYSIS,
            **common,
        )

    # 4. Everything the role implies was located. Nothing is wrong *now*, which
    #    is a reason to watch rather than a reason to act — and "watch" is an
    #    Automate subscription, a mechanism that already exists, not a badge.
    located = [f"{f.kind}: {f.outcome}" + (f" ({f.date[:10]})" if f.date else "")
               for f in report.found]
    return Disposition(
        disposition=MONITOR,
        reason=(f"everything a {report.primary_role} implies was located; "
                f"nothing needs attention now, so the useful next step is to "
                f"notice when that changes"),
        evidence=located,
        next_step="subscription",
        next_step_target=MONITORED_ANALYSIS,
        **common,
    )


def for_repo(owner_repo: str, client=None) -> Disposition:
    """Classify, resolve expectations, and recommend."""
    return from_report(ex.build_report(owner_repo, client=client))
