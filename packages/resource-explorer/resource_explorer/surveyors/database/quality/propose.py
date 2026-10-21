"""`propose_quality_checks`: the vendored selection rules over the latest value profile. Zero-fetch.

DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md §5. Opens no connection: it reads the latest `database_value_profiles`
batch and the current verdicts, and writes one `database_quality_proposals` batch. For each (column, test type)
the ported rule (`catalogue.PREDICATES`) gives one of three answers:

- true: a proposal, with the catalogue's default parameters evaluated against the profile;
- false: nothing stored, only counted (`not_applicable_ct`);
- NULL (an input was not measured): `not_established`, listed by column with the inputs that were missing.
  Never a silent false. A column the profile marked `not_applicable` (a view or foreign table) is counted as
  not applicable instead: there is nothing to check, rather than something we could not measure.

Row_Ct_Pct is proposed by RE itself (origin `re`) for every table with `record_ct > 0`.

Verdicts (append-only, latest per key wins) shape what a proposal becomes:
- accepted: the row is `accepted`, and `reason` says whether the new profile drifted from the accepted
  baseline. Drift is a fact for the reviewer; nothing is re-applied.
- rejected: `suppressed`, until the column's general_type changes or the selection outcome flips (a propose run
  after the rejection in which the rule did not select it). "Rejected" means "not for this column".
- retired, or no verdict: proposed afresh. An open proposal is superseded by the next batch; nothing is deleted.
"""
from __future__ import annotations

from datetime import UTC, datetime

from resource_explorer.surveyors.database.quality.catalogue import (
    PREDICATES,
    ParameterError,
    TestType,
    catalogue_ref,
    check_key,
    default_params,
    load_catalogue,
    not_established_inputs,
)

PROPOSALS_TABLE = "database_quality_proposals"
PROFILE_TABLE = "database_value_profiles"
ANALYSIS_STEP = "propose_quality_checks"

#: Parameters compared between the accepted check and the new profile's defaults to report drift.
BASELINE_KEYS = ("baseline_ct", "baseline_value_ct", "baseline_value")


def _not_established_reason(test_type: str, profile: dict) -> str:
    state = profile.get("state") or "measured"
    if state != "measured":
        why = profile.get("reason") or "no reason recorded"
        return f"not profiled ({state}: {why}), so its selection rule could not be evaluated"
    missing = not_established_inputs(test_type, profile)
    if profile.get("record_ct") == 0:
        return f"the table was empty when profiled, so {', '.join(missing) or 'an input'} is undefined"
    return f"its selection rule reads {', '.join(missing) or 'an input'}, which the profile did not measure"


def _drift(accepted: dict, current: dict) -> str:
    changes = []
    for key in BASELINE_KEYS:
        before, after = accepted.get(key), current.get(key)
        if before is not None and after is not None and str(before) != str(after):
            changes.append(f"{key} {before} -> {after}")
    if not changes:
        return "no drift from the accepted baseline"
    return "the profile has drifted from the accepted baseline: " + "; ".join(changes)


class _Batches:
    """The proposal keys of earlier batches, read once each (for the rejected-verdict flip rule)."""

    def __init__(self, registry, slug: str):
        self.registry, self.slug = registry, slug
        self.batches = registry.list_detail_batches(PROPOSALS_TABLE, slug)
        self._keys: dict[str, set[str]] = {}

    def keys(self, batch: str) -> set[str]:
        if batch not in self._keys:
            self._keys[batch] = {r["check_key"] for r in
                                 self.registry.query_detail_rows(PROPOSALS_TABLE, self.slug, batch)}
        return self._keys[batch]

    def flipped_since(self, key: str, since: str) -> bool:
        """True when a batch after `since` did not carry `key`: the rule did not select it then."""
        return any(key not in self.keys(b) for b in self.batches if b > since)


def run_propose(registry, slug: str, *, row_ct_pct_threshold: float, surveyed_at: str | None = None) -> dict:
    surveyed_at = surveyed_at or datetime.now(UTC).isoformat()
    profile = registry.query_detail_rows(PROFILE_TABLE, slug)
    if not profile:
        return {"quality_proposals": {
            "surveyed_at": surveyed_at, "state": "not_established",
            "reason": "no value profile stored: run the value profile first; nothing was proposed",
        }}
    profile_surveyed_at = profile[0]["surveyed_at"]
    catalogue = load_catalogue()
    verdicts = registry.get_quality_verdicts(slug)
    batches = _Batches(registry, slug)

    rows: list[dict] = []
    not_applicable_ct = 0

    def consider(test_type: TestType, prow: dict, column: str, general_type: str) -> None:
        nonlocal not_applicable_ct
        key = check_key(prow["schema_name"], prow["table_name"], column, test_type.test_type)
        if prow.get("state") == "not_applicable" and key not in verdicts:
            # A view or foreign table: the profile does not apply, so neither does any check on it.
            not_applicable_ct += 1
            return
        selected = PREDICATES[test_type.test_type].evaluate(prow)
        params: dict = {}
        state, reason = "proposed", ""
        if selected is None:
            state, reason = "not_established", _not_established_reason(test_type.test_type, prow)
        elif selected:
            try:
                params = default_params(test_type, prow, row_ct_pct_threshold)
                params["profile_surveyed_at"] = profile_surveyed_at
            except ParameterError as exc:
                state, reason = "not_established", str(exc)

        verdict = verdicts.get(key)
        kind = (verdict or {}).get("verdict")
        if kind == "accepted":
            accepted = verdict.get("params_json") if isinstance(verdict.get("params_json"), dict) else {}
            if selected is False:
                reason = "accepted; the selection rule no longer selects it in this profile"
            elif state == "not_established":
                reason = f"accepted; this profile could not re-evaluate it: {reason}"
            else:
                reason = f"accepted; {_drift(accepted, params)}"
            state = "accepted"
        elif kind == "rejected" and selected is not False:
            earlier = registry.get_quality_proposal(verdict.get("proposal_id")) or {}
            if earlier.get("check_key") != key:
                earlier = {}
            type_changed = bool(earlier.get("general_type")) and earlier.get("general_type") != general_type
            # "Since" is the batch the person judged, a scan time like every batch it is compared with; the
            # verdict's own wall-clock time is the fallback only when that proposal cannot be found.
            since = earlier.get("surveyed_at") or verdict.get("created_at") or ""
            if type_changed or batches.flipped_since(key, since):
                pass  # proposed afresh: the column is no longer what was rejected
            else:
                state = "suppressed"
                reason = f"rejected {verdict.get('created_at', '')[:10]} by {verdict.get('decided_by') or 'unknown'}"
        elif selected is False:
            not_applicable_ct += 1
            return

        rows.append({
            "check_key": key, "schema_name": prow["schema_name"], "table_name": prow["table_name"],
            "column_name": column, "test_type": test_type.test_type, "origin": test_type.origin,
            "general_type": general_type, "profile_surveyed_at": profile_surveyed_at, "params_json": params,
            "catalogue_ref": catalogue_ref(test_type), "state": state, "reason": reason,
        })

    column_types = [t for t in catalogue.values() if not t.is_table_check]
    table_types = [t for t in catalogue.values() if t.is_table_check]
    tables: dict[tuple[str, str], list[dict]] = {}
    for prow in profile:
        tables.setdefault((prow["schema_name"], prow["table_name"]), []).append(prow)
        for test_type in column_types:
            consider(test_type, prow, prow["column_name"], prow.get("general_type") or "")
    for (_schema, _table), prows in sorted(tables.items()):
        # The table's record_ct is on every measured column's row; an unprofiled table has none.
        table_row = next((r for r in prows if r.get("state") == "measured"), prows[0])
        for test_type in table_types:
            consider(test_type, table_row, "", "")

    registry.write_detail_rows(PROPOSALS_TABLE, slug, surveyed_at, rows=rows)
    states: dict[str, int] = {}
    for row in rows:
        states[row["state"]] = states.get(row["state"], 0) + 1
    not_established = {}
    for row in rows:
        if row["state"] == "not_established":
            path = f"{row['schema_name']}.{row['table_name']}" + (f".{row['column_name']}" if row["column_name"] else "")
            not_established.setdefault(path, []).append({"test_type": row["test_type"], "reason": row["reason"]})
    return {"quality_proposals": {
        "surveyed_at": surveyed_at,
        "state": "measured",
        "profile_surveyed_at": profile_surveyed_at,
        "proposed_ct": states.get("proposed", 0),
        "accepted_ct": states.get("accepted", 0),
        "suppressed_ct": states.get("suppressed", 0),
        "not_established_ct": states.get("not_established", 0),
        "not_applicable_ct": not_applicable_ct,
        "not_established_by_column": not_established,
    }}
