"""Whether a step can say anything at all, checked before it is dispatched.

`StepInfo` already declares `requires_resources` (a zipball, a clone) and
`requires_views` — both about *runtime inputs*. Neither expresses "this step
reads rows another step writes, and there are none", which is a different and
commoner condition. `cve_scan` is the worked example: on a repo with no parsed
dependencies it runs, reads `project_dependencies`, finds nothing, and correctly
declines rather than claiming "no CVEs" — right behaviour, but it was dispatched,
timed, and counted as an input that produced no answer.

**A skip is a result, not an omission.** Every skip here carries a reason, via
`result_status.skipped()`, which takes one as a required argument. A step that
simply vanishes from a report is indistinguishable from one that ran and found
nothing — the failure this codebase keeps removing — so the skip is emitted as a
real annotation rather than by not appearing.

**This is the precondition half, not the guard half.** Egeria's own model answers
*which links fire* — each `NextGovernanceActionProcessStep` carries a `guard`,
and `EngineActionHandler.initiateNextEngineActions` follows the links whose guard
appears in the previous step's `outputGuards` (`validNextAction = (guard ==
null)`). That governs traversal of an authored graph. This governs whether a step
in a flat orchestrator run has anything to work with. They compose: a guard says
a branch was not taken, a precondition says a step had no input, and both must
leave a trace rather than a silence.

**Preconditions are named, not inlined.** A name can be declared on a step, read
in a report, and tested; a lambda on a step cannot. The names are deliberately
about *stored data*, not about steps, so the check does not encode an execution
order it cannot enforce — `test_step_execution_order.py` already pins
producers-before-consumers positionally, and a second implicit ordering beside it
is how the two drift.
"""
from __future__ import annotations

import logging
from typing import Callable

from resource_explorer.surveyors import result_status

log = logging.getLogger(__name__)


def _row_count(registry, table: str, slug: str, where: str = "") -> int:
    """-1 when the table cannot be read at all, which is not the same as empty."""
    try:
        with registry._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE project_slug = ?"
                + (f" AND {where}" if where else ""),
                (slug,),
            ).fetchone()
        return int(row["n"] or 0)
    except Exception as exc:
        log.debug("precondition: cannot count %s for %s: %s", table, slug, exc)
        return -1


def _needs_rows(table: str, what: str, where: str = "") -> Callable:
    def check(registry, project) -> tuple[bool, str]:
        n = _row_count(registry, table, project.slug, where)
        if n < 0:
            # Cannot tell. Run the step: refusing on an unreadable check would
            # turn our own failure into a claim about the repository, and the
            # step's own absence handling is better than a guess here.
            return True, f"could not read {table}; running the step rather than assuming"
        if n:
            return True, f"{n} row(s) in {table}"
        return False, f"no {what} recorded for this repo"
    return check


#: name → (check, the step this data comes from). The second element is for the
#: reason text only: it tells a reader what to run to satisfy the precondition,
#: which is the question they will have next.
PRECONDITIONS: dict[str, tuple[Callable, str]] = {
    "has_dependencies": (
        _needs_rows("project_dependencies", "dependencies"), "repo_manifest_parse"),
    # NOT the same condition, and the difference is the whole point. Measured
    # 2026-09-01: `egeria_git` has 216 dependency rows and **0 with a version** —
    # Gradle declares versions through a BOM or version catalog, so the parser
    # recovers the coordinate and not the version. `has_dependencies` passes
    # there and `cve_scan` still cannot query OSV, which needs a pinned version.
    # A guard that fires on the wrong property is worse than no guard: it reads
    # as coverage. Reported by a concurrent session and verified here directly.
    "has_versioned_dependencies": (
        _needs_rows("project_dependencies", "dependencies with a resolved version",
                    where="dep_version IS NOT NULL AND dep_version != ''"),
        "repo_manifest_parse (and version resolution — see Backlog, Gradle/BOM)"),
    "has_file_inventory": (
        _needs_rows("project_file_inventory", "file inventory"), "repo_file_inventory"),
    "has_code_symbols": (
        _needs_rows("project_code_symbols", "code symbols"), "repo_symbol_extraction"),
}


def evaluate(registry, project, requires_context: dict[str, str]) -> tuple[bool, str, str]:
    """(may_run, precondition_name, reason).

    `requires_context` maps a precondition name to the step's own explanation of
    why it needs it. The returned reason combines that with what was actually
    measured, so the skip says both what was missing and why this step cares.

    An unknown precondition name RUNS the step and logs loudly. Silently skipping
    on a typo would be the worst outcome available: a step that never runs, for a
    reason nobody can look up, indistinguishable from one with nothing to say.
    """
    for name, why in (requires_context or {}).items():
        entry = PRECONDITIONS.get(name)
        if entry is None:
            log.error(
                "step declares unknown precondition %r — running it anyway. "
                "Known: %s", name, ", ".join(sorted(PRECONDITIONS)))
            continue
        check, produced_by = entry
        met, detail = check(registry, project)
        if not met:
            return False, name, f"{why} — {detail}. Run {produced_by} first."
    return True, "", ""


def skip_status(precondition: str, reason: str) -> dict:
    """The status row for a skipped step. `skipped()` requires the reason."""
    return result_status.skipped(reason, gate=precondition)
