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

**What this module adds now (Phase 1 slice 14 follow-up).** `grant_change`
and the column/constraint-level half of `schema_diff` — the two comparators
the 2026-09-22 live done-test verification found missing (`docs/Backlog.md`,
"Phase 1 done-test verification (2026-09-22)"). Both follow
`_compare_change_rates`'s exact bridge shape, but over their own new
`db_derived.derive_schema_diff`/`derive_grant_change` computations rather
than `derive_change_rates`'s — see those functions' own docstrings in
`db_derived.py` (§7/§8) for the two-snapshot diff itself. Each is its own
`analysis_id`, distinct from `db_change_rates`: design §9.1's Perspective
presets subscribe to `schema_diff` and `grant_change` separately from
`db_change_rates` (Steward: `schema_diff`; Security/Privacy: `grant_change`),
and `scheduler._check_subscriptions` dispatches by `analysis_id` matched to
whichever schedule just completed — a subscription to `schema_diff` is only
ever checked after a `schema_diff` schedule run, so it needs its own
schedulable id, not a subscription against `db_change_rates`'s.

**What is still not built**, and stays open per design §9.1's full
comparator table: `class_change`, `reference_set_change`, `scope_change`,
`resilience_change`. Each needs a two-snapshot diff over data this codebase
already collects elsewhere (`postgres_column_profile`'s `data_class_match`/
`reference_data_match`, `postgres_operations`'s `db_resilience`, proposed
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


def _compare_schema_diff(registry, slug: str) -> ChangeResult:
    """`schema_diff` (column/constraint half) → a `ChangeResult`, bridging
    `derive_schema_diff`'s own two-snapshot diff verbatim.

    Same `established` discipline as `_compare_change_rates`:
    `insufficient_history` is `changed=False, established=False`, a measured
    diff with nothing added/dropped/retyped is `changed=False,
    established=True`.
    """
    from resource_explorer.surveyors.database.db_derived import derive_schema_diff

    result = derive_schema_diff(registry, slug)

    if result["state"] != STATE_MEASURED:
        return ChangeResult(
            changed=False,
            established=False,
            summary=result.get("explanation", result.get("reason", "")),
        )

    changed = bool(result["columns_added"] or result["columns_dropped"] or result["columns_retyped"])
    return ChangeResult(changed=changed, established=True, summary=result["explanation"])


def _compare_grant_change(registry, slug: str) -> ChangeResult:
    """`grant_change` → a `ChangeResult`, bridging `derive_grant_change`'s own
    two-snapshot diff verbatim.

    A new grant to PUBLIC is a real change like any other new grant — the
    `established`/`changed` split does not special-case it, since
    `derive_grant_change`'s `public_grants_added` already makes it
    unambiguous in the summary text a subscriber reads (design §9.1's own
    wording: "new grant, especially to PUBLIC").
    """
    from resource_explorer.surveyors.database.db_derived import derive_grant_change

    result = derive_grant_change(registry, slug)

    if result["state"] != STATE_MEASURED:
        return ChangeResult(
            changed=False,
            established=False,
            summary=result.get("explanation", result.get("reason", "")),
        )

    changed = bool(result["grants_added"] or result["grants_revoked"])
    return ChangeResult(changed=changed, established=True, summary=result["explanation"])


#: One entry per database analysis_id this module can compare. The single
#: place both the scheduler and any future caller (a manual "check now",
#: the Automate UI) read — mirrors `db_derived.DB_DERIVED_ANALYSES`'s own
#: reasoning for having one list rather than scattering `if analysis_id ==`
#: checks.
DATABASE_CHANGE_COMPARATORS: dict[str, Callable[[object, str], ChangeResult]] = {
    "db_change_rates": _compare_change_rates,
    "schema_diff": _compare_schema_diff,
    "grant_change": _compare_grant_change,
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
                "further database comparators (class_change, "
                "reference_set_change, scope_change, "
                "resilience_change) that are not yet wired to the local "
                "delivery path."
            ),
        )
    return comparator(registry, slug)
