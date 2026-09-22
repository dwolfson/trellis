"""Database change comparators on the local delivery path (Phase 1 slice 14,
design §9.1, coordinator brief row 14).

**What this closes.** `notification_detector.detect_change()` — the engine
behind Automate subscriptions and scheduler.py's `_check_subscriptions` — is
generic *across analysis kinds*, but only for kinds that persist through
`project_analysis_findings`/`project_analysis_metrics`
(`registry.upsert_finding`/`upsert_metric`). Both tables are foreign-keyed to
`projects(slug)` (repos only — see `registry.py`'s `CREATE TABLE
project_analysis_findings`/`project_analysis_metrics`), and no database step
writes to either: `db_derived.py`'s six checks (Phase 1 slice 9) return
annotations for Egeria publishing and are read by the Questions tab straight
from the structured tables, never through `upsert_finding`. The consequence,
confirmed by reading rather than assumed: `detect_change(registry, slug,
analysis_id)` for a database slug reads an always-empty findings/metrics
history and returns `changed=False` unconditionally — silently, since
`scheduler._check_subscriptions` treats that the same as "compared two runs,
nothing differed." A database Automate subscription (the UI already lets you
create one — `automate.py`'s `RESOURCE_ICON` map includes `database`) can
never fire, and nothing before this said so.

**What this does not do.** It does not add a database-scoped
findings/metrics table, and it does not touch `db_derived.py`'s computation.
`derive_change_rates()` (slice 9) already computes exactly what design
§9.1's `row_drift` comparator needs — per-table insert/update/delete deltas
— and the table-add/drop half of `schema_diff`, by differencing the two most
recent `database_table_activity`/`database_tables` snapshots. This module is
purely the bridge: read that already-computed result and turn it into a
`ChangeResult` the scheduler can act on, with the same
`ChangeResult`/`established` vocabulary `notification_detector.py` uses for
the repo side, so `_check_subscriptions` does not need two different
result shapes.

**What is still not built**, and stays open per design §9.1's full
comparator table: `grant_change`, `class_change`, `reference_set_change`,
`scope_change`, `resilience_change`, and the column/constraint-level half of
`schema_diff`. Each needs a two-snapshot diff over data this codebase
already collects elsewhere (`postgres_operations`'s `privilege_audit`/
`db_resilience`, `data_class_match`, `reference_data_match`, proposed
`DataScope`) but none of those checks is differenced across runs today —
that is a comparator apiece, not a re-run of this one. Logged to
`docs/Backlog.md`.
"""
from __future__ import annotations

from typing import Callable

from resource_explorer.notification_detector import ChangeResult
from resource_explorer.registry import STATE_MEASURED


def _compare_change_rates(registry, slug: str) -> ChangeResult:
    """`db_change_rates` → a `ChangeResult`, reusing `derive_change_rates`'s
    own computation verbatim (no re-derivation of any delta).

    A table is "changed" if `derive_change_rates` labelled it `active`
    (nonzero rows_inserted/updated/deleted since the previous snapshot), or
    if schema churn added/removed a table. `insufficient_history` — one
    snapshot, or none — is `changed=False, established=False`: a real,
    distinct claim from "measured and nothing moved" (`changed=False,
    established=True`), carried through so a subscriber is never told "no
    change" when the true state is "cannot tell yet." Both suppress an RFA
    identically (nothing to notify about either way); `established`
    distinguishes them for anyone reporting *why*.
    """
    from resource_explorer.surveyors.database.db_derived import (
        derive_change_rates,
        load_inputs,
    )

    inputs = load_inputs(registry, slug)
    result = derive_change_rates(registry, inputs)

    if result["state"] != STATE_MEASURED:
        return ChangeResult(
            changed=False,
            established=False,
            summary=result.get("explanation", result.get("reason", "")),
        )

    active_tables = [e for e in result["per_table"] if e.get("change") == "active"]
    churn = result["schema_churn"]
    schema_changed = churn["state"] == STATE_MEASURED and (
        churn["tables_added"] or churn["tables_removed"]
    )

    if not active_tables and not schema_changed:
        # Measured — both snapshots compared cleanly, and nothing moved.
        # This IS a real, distinct answer from "insufficient_history" above,
        # not just the fallback of no changes being found.
        return ChangeResult(changed=False, established=True, summary=result["explanation"])

    parts: list[str] = []
    if churn["tables_added"]:
        parts.append(f"{len(churn['tables_added'])} table(s) added: {', '.join(churn['tables_added'])}")
    if churn["tables_removed"]:
        parts.append(f"{len(churn['tables_removed'])} table(s) removed: {', '.join(churn['tables_removed'])}")
    if active_tables:
        detail = ", ".join(
            f"{e['qualified_name']} ("
            f"{e['deltas']['rows_inserted']} ins / "
            f"{e['deltas']['rows_updated']} upd / "
            f"{e['deltas']['rows_deleted']} del)"
            for e in active_tables
        )
        parts.append(f"{len(active_tables)} table(s) with row activity: {detail}")

    return ChangeResult(changed=True, established=True, summary="; ".join(parts))


#: One entry per database analysis_id this module can compare. The single
#: place both the scheduler and any future caller (a manual "check now",
#: the Automate UI) read — mirrors `db_derived.DB_DERIVED_ANALYSES`'s own
#: reasoning for having one list rather than scattering `if analysis_id ==`
#: checks.
DATABASE_CHANGE_COMPARATORS: dict[str, Callable[[object, str], ChangeResult]] = {
    "db_change_rates": _compare_change_rates,
}


def detect_database_change(registry, slug: str, analysis_id: str) -> ChangeResult:
    """The database-side counterpart to `notification_detector.detect_change`
    — dispatched by `scheduler._check_subscriptions` for `entity_type ==
    "database"` instead of the generic findings/metrics-backed detector,
    which has no database rows to read (see module docstring).

    An `analysis_id` with no comparator here is `changed=False,
    established=False` — "no comparator exists yet," never silently equal
    to "measured, no change." Subscribing to e.g. `db_classification` today
    falls in this bucket: nothing in the codebase currently diffs one
    classification against the next.
    """
    comparator = DATABASE_CHANGE_COMPARATORS.get(analysis_id)
    if comparator is None:
        return ChangeResult(
            changed=False,
            established=False,
            summary=(
                f"No change comparator is implemented yet for '{analysis_id}'. "
                "This is not a measurement of 'no change' — design §9.1 lists "
                "further database comparators (schema_diff, grant_change, "
                "class_change, reference_set_change, scope_change, "
                "resilience_change) that are not yet wired to the local "
                "delivery path."
            ),
        )
    return comparator(registry, slug)
