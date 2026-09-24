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

**The producer is derived, not typed here (2026-09-23, design §17.1).** Each
entry used to carry a step-key string beside its check, "for the reason text
only". §17.1 needs the same fact for a second purpose — the resolver has to
run the producer, not merely name it — and two purposes reading one hand-typed
string in a module that otherwise refuses to name steps is exactly the drift
this file's own docstring warns about. So an entry now declares the **table**
it counts, and `step_produces.producer_of()` answers which step fills it, from
that step's own `StepInfo.produces`. The vocabulary of this module is
unchanged: it still names stored data.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Callable

from resource_explorer.surveyors import result_status

log = logging.getLogger(__name__)


def _row_count(registry, table: str, slug: str, where: str = "",
               slug_column: str = "project_slug") -> int:
    """-1 when the table cannot be read at all, which is not the same as empty."""
    try:
        with registry._conn() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {slug_column} = ?"
                + (f" AND {where}" if where else ""),
                (slug,),
            ).fetchone()
        return int(row["n"] or 0)
    except Exception as exc:
        log.debug("precondition: cannot count %s for %s: %s", table, slug, exc)
        return -1


def _needs_rows(table: str, what: str, where: str = "",
                slug_column: str = "project_slug") -> Callable:
    def check(registry, project) -> tuple[bool, str]:
        n = _row_count(registry, table, project.slug, where, slug_column)
        if n < 0:
            # Cannot tell. Run the step: refusing on an unreadable check would
            # turn our own failure into a claim about the repository, and the
            # step's own absence handling is better than a guess here.
            return True, f"could not read {table}; running the step rather than assuming"
        if n:
            return True, f"{n} row(s) in {table}"
        return False, f"no {what} recorded for this resource"
    return check


@dataclass(frozen=True)
class Precondition:
    """One named condition on stored data.

    `table` is the load-bearing field: it is what the check counts AND what
    `step_produces.producer_of()` inverts to a step key. The producer is
    therefore never written down twice.

    `caveat` carries the part of a remedy that is NOT "run this step" — the
    Gradle/BOM case below is the whole reason the field exists: running
    `repo_manifest_parse` is necessary and, on that repository, not
    sufficient.
    """
    check: Callable
    table: str
    caveat: str = ""

    def produced_by(self) -> str:
        """The step that fills `self.table`, from its own `produces`."""
        from resource_explorer.surveyors import step_produces

        return step_produces.producer_of(self.table)

    def remedy(self) -> str:
        """What a reader should do next, as one sentence. Says so honestly
        when nothing declares a producer — naming a step that does not exist
        would be worse than admitting the gap."""
        step = self.produced_by()
        if not step:
            return (
                f"Nothing in this build declares that it writes {self.table} — "
                "no step can be named to satisfy this."
            )
        return f"Run {step}{f' ({self.caveat})' if self.caveat else ''} first."


#: name → the condition. No producer string: see this module's docstring and
#: `Precondition.produced_by`.
PRECONDITIONS: dict[str, Precondition] = {
    "has_dependencies": Precondition(
        _needs_rows("project_dependencies", "dependencies"),
        table="project_dependencies"),
    # NOT the same condition, and the difference is the whole point. Measured
    # 2026-09-01: `egeria_git` has 216 dependency rows and **0 with a version** —
    # Gradle declares versions through a BOM or version catalog, so the parser
    # recovers the coordinate and not the version. `has_dependencies` passes
    # there and `cve_scan` still cannot query OSV, which needs a pinned version.
    # A guard that fires on the wrong property is worse than no guard: it reads
    # as coverage. Reported by a concurrent session and verified here directly.
    "has_versioned_dependencies": Precondition(
        _needs_rows("project_dependencies", "dependencies with a resolved version",
                    where="dep_version IS NOT NULL AND dep_version != ''"),
        table="project_dependencies",
        caveat="and version resolution — see Backlog, Gradle/BOM"),
    "has_file_inventory": Precondition(
        _needs_rows("project_file_inventory", "file inventory"),
        table="project_file_inventory"),
    "has_code_symbols": Precondition(
        _needs_rows("project_code_symbols", "code symbols"),
        table="project_code_symbols"),
    # ── databases (2026-09-23, design §17.1's own worked chain) ───────────
    #
    # `postgres_column_profile` reads table/column rows to know what to
    # sample; with none stored it would sample nothing and report a confident
    # empty profile. The slug column differs from the repo tables' — the
    # database detail tables are keyed by `database_slug` (registry.py's
    # `_DB_FS_DETAIL_TABLE_DDL`), which is why `_needs_rows` takes one.
    "has_schema_inventory": Precondition(
        _needs_rows("database_tables", "schema inventory",
                    slug_column="database_slug"),
        table="database_tables"),
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
        met, detail = entry.check(registry, project)
        if not met:
            return False, name, f"{why} — {detail}. {entry.remedy()}"
    return True, "", ""


def unmet(registry, project, requires_context: dict[str, str]) -> list[tuple[str, str]]:
    """Every unmet precondition, as (name, reason) — not just the first.

    `evaluate()` stops at the first failure, which is right for "may this step
    run" and wrong for §17.1's resolver: a step missing two inputs must produce
    ONE proposal naming both, not one proposal and then, after that is
    accepted, a second. Kept as a separate function rather than changing
    `evaluate`'s shape, because every existing caller wants the cheap
    short-circuit.
    """
    out: list[tuple[str, str]] = []
    for name, why in (requires_context or {}).items():
        entry = PRECONDITIONS.get(name)
        if entry is None:
            log.error(
                "step declares unknown precondition %r — running it anyway. "
                "Known: %s", name, ", ".join(sorted(PRECONDITIONS)))
            continue
        met, detail = entry.check(registry, project)
        if not met:
            out.append((name, f"{why} — {detail}. {entry.remedy()}"))
    return out


def skip_status(precondition: str, reason: str) -> dict:
    """The status row for a skipped step. `skipped()` requires the reason."""
    return result_status.skipped(reason, gate=precondition)
