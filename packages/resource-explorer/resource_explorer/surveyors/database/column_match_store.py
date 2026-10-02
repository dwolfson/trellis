"""Local store for the three value-reading analyses (D1, DB-RESULTS-READERS).

`data_class_match`, `reference_data_match` and `nested_column_profile` produced
real verdicts that only ever became Egeria annotations. This writes the same
verdicts into three local detail tables (`database_data_class_matches`,
`database_reference_data_matches`, `database_nested_columns`) so a results
reader can answer from them, the way `schema_inventory` answers from
`database_tables`.

Two rules this module exists to keep:

* **A run that tried and could not measure says so.** Every section the step
  attempted gets a coverage row, including the ones with no rows and the ones
  that failed, so "never ran" (no coverage row), "ran and found nothing"
  (a coverage row, rows that are all negative or none) and "tried and could not"
  (coverage state `not_collected`, the reason in `detail`) stay three different
  stored facts. An empty table alone says all three at once.
* **Re-running must not duplicate rows.** Writing goes through
  `registry.write_detail_rows`, which replaces the rows of one
  `(slug, surveyed_at, source)`; a later run has its own `surveyed_at`, so two
  runs are two sets of rows and neither overwrites the other.

Nothing here talks to Egeria or to the database being surveyed.
"""
from __future__ import annotations

from typing import Any, Sequence

from resource_explorer.registry import (
    SECTION_DATA_CLASS_MATCHES,
    SECTION_NESTED_COLUMNS,
    SECTION_REFERENCE_DATA_MATCHES,
    STATE_EMPTY,
    STATE_MEASURED,
    STATE_NOT_APPLICABLE,
    STATE_NOT_COLLECTED,
    STATE_NOT_SUPPORTED,
)
from resource_explorer.surveyors.database.column_matching import (
    ESTABLISHED_VERDICTS,
    MATCH_NOT_APPLICABLE,
)
from resource_explorer.surveyors.database.sampling import TOTAL_ROWS_NOT_ESTABLISHED

TABLE_DATA_CLASS = "database_data_class_matches"
TABLE_REFERENCE_DATA = "database_reference_data_matches"
TABLE_NESTED = "database_nested_columns"

#: The question a `ColumnMatch` answers, to the table and coverage section it
#: is stored under.
_MATCH_TARGETS = {
    "data_class_match": (TABLE_DATA_CLASS, SECTION_DATA_CLASS_MATCHES),
    "reference_data_match": (TABLE_REFERENCE_DATA, SECTION_REFERENCE_DATA_MATCHES),
}


def _sample_fields(sample: dict | None) -> dict[str, Any]:
    """The §5.8 sample basis, flattened. `total_rows` carries a sentinel string
    when the table's row count was not established; that is NULL here, never a
    number and never the sentinel text in an integer column."""
    sample = sample or {}
    total = sample.get("total_rows")
    return {
        "sample_strategy": sample.get("strategy") or "",
        "sample_rows": sample.get("sample_rows"),
        "sample_total_rows": (
            None if total is None or total == TOTAL_ROWS_NOT_ESTABLISHED else total
        ),
        "sample_seed": sample.get("seed"),
    }


def _match_state(verdict: str) -> str:
    """The registry-vocabulary state of one verdict: measured when the verdict
    is a positive statement about the data (including "no known class matched"),
    not_applicable for a deliberate exclusion, and not_collected for everything
    that established nothing (not sampled, no candidates, inconclusive)."""
    if verdict in ESTABLISHED_VERDICTS:
        return STATE_MEASURED
    if verdict == MATCH_NOT_APPLICABLE:
        return STATE_NOT_APPLICABLE
    return STATE_NOT_COLLECTED


def match_rows(matches: Sequence[dict], question: str) -> list[dict]:
    """Detail rows for one question from `run_column_profile`'s `matches`
    (the `ColumnMatch.as_dict()` list, both questions interleaved)."""
    rows: list[dict] = []
    for m in matches:
        if m.get("question") != question:
            continue
        row = {
            "schema_name": m.get("schema") or "",
            "table_name": m.get("table") or "",
            "column_name": m.get("column") or "",
            "verdict": m.get("verdict") or "",
            "confidence": m.get("confidence"),
            "evidence": m.get("evidence") or "",
            "matched_display_name": m.get("matched_display_name") or "",
            "matched_qualified_name": m.get("matched_qualified_name") or "",
            "matched_guid": m.get("matched_guid") or "",
            "matched_element_is_draft": m.get("matched_element_is_draft"),
            "not_established_reason": m.get("not_established_reason") or "",
            "statement": m.get("statement") or "",
            "state": _match_state(m.get("verdict") or ""),
            **_sample_fields(m.get("sample")),
        }
        if question == "data_class_match":
            row.update({
                "sampled_conformance": m.get("sampled_conformance"),
                "privacy_relevant": m.get("privacy_relevant"),
                "proposed_specification": m.get("proposed_specification") or "",
                "detected_patterns_json": list(m.get("detected_patterns") or []),
            })
        else:
            row.update({
                "value_coverage": m.get("value_coverage"),
                "unmatched_values_json": list(m.get("unmatched_values") or []),
                "proposed_values_json": list(m.get("proposed_values") or []),
            })
        rows.append(row)
    return rows


def nested_rows(columns: Sequence[dict]) -> list[dict]:
    """Detail rows from `run_nested_columns`'s `nested_columns["columns"]`."""
    rows: list[dict] = []
    for c in columns:
        schema = c.get("schema")
        keys = (schema or {}).get("keys") or (schema or {}).get("names")
        rows.append({
            "schema_name": c.get("schema_name") or "",
            "table_name": c.get("table_name") or "",
            "column_name": c.get("column_name") or "",
            "column_family": c.get("family") or "",
            "label": c.get("label") or "",
            "key_count": len(keys) if isinstance(keys, list) else None,
            "max_depth": (schema or {}).get("max_depth"),
            "schema_json": schema,
            "not_established_reason": c.get("not_established_reason") or "",
            "state": c.get("state") or STATE_MEASURED,
            **_sample_fields(c.get("sample")),
        })
    return rows


def _coverage_for(rows: list[dict], established_states: set[str], noun: str) -> tuple[str, str]:
    """(coverage state, detail) for a section the step attempted.

    No rows: the step ran and there was nothing to examine (`empty`). Rows but
    none established: the step ran and established nothing (`not_collected`,
    the most common reason named). Otherwise measured."""
    if not rows:
        return STATE_EMPTY, f"the run examined no {noun}"
    if not any(r.get("state") in established_states for r in rows):
        reasons: dict[str, int] = {}
        for r in rows:
            reason = r.get("not_established_reason") or ""
            if reason:
                reasons[reason] = reasons.get(reason, 0) + 1
        top = max(reasons.items(), key=lambda kv: kv[1])[0] if reasons else ""
        return STATE_NOT_COLLECTED, top or f"no {noun} was established"
    return STATE_MEASURED, ""


def store_column_match_results(registry, slug: str, surveyed_at: str, results: dict) -> None:
    """Write whatever value-reading steps this run attempted.

    `results` is `DatabaseSurveyor.survey()`'s dict. A step that did not run
    leaves an empty dict behind and writes nothing: its sections get no coverage row,
    which is exactly "never ran". A step that raised leaves
    `column_profile_failed` / `nested_columns_failed` and is recorded as
    `not_collected` with the message, never as an empty success.
    """
    profile = results.get("column_profile")
    failed = results.get("column_profile_failed")
    # `survey()` seeds both keys with `{}`, so a step that did not run is an
    # empty dict, not a missing key; a step that ran always returns a non-empty
    # dict (`matches`/`columns` are present even when empty).
    if profile or failed:
        matches = (profile or {}).get("matches") or []
        for question, (table, section) in _MATCH_TARGETS.items():
            if failed:
                registry.write_detail_rows(
                    table, slug, surveyed_at, rows=[],
                    coverage_section=section, coverage_state=STATE_NOT_COLLECTED,
                    coverage_detail=f"the column-profile step failed: {failed}",
                )
                continue
            rows = match_rows(matches, question)
            state, detail = _coverage_for(rows, {STATE_MEASURED}, "columns")
            registry.write_detail_rows(
                table, slug, surveyed_at, rows=rows,
                coverage_section=section, coverage_state=state, coverage_detail=detail,
            )

    nested = results.get("nested_columns")
    nested_failed = results.get("nested_columns_failed")
    if nested or nested_failed:
        if nested_failed:
            registry.write_detail_rows(
                TABLE_NESTED, slug, surveyed_at, rows=[],
                coverage_section=SECTION_NESTED_COLUMNS, coverage_state=STATE_NOT_COLLECTED,
                coverage_detail=f"the nested-column step failed: {nested_failed}",
            )
        else:
            rows = nested_rows((nested or {}).get("columns") or [])
            if rows and not (nested or {}).get("value_sampling_supported", True):
                state, detail = STATE_NOT_SUPPORTED, (
                    "this connection's engine declares no value_sampling capability"
                )
            else:
                state, detail = _coverage_for(
                    rows, {STATE_MEASURED, STATE_EMPTY}, "JSON, JSONB or XML columns"
                )
            registry.write_detail_rows(
                TABLE_NESTED, slug, surveyed_at, rows=rows,
                coverage_section=SECTION_NESTED_COLUMNS, coverage_state=state,
                coverage_detail=detail,
            )
