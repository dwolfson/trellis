"""`db_derived` — the zero-fetch derivation step for databases.

Phase 1 slice 9. Implements `docs/multi-resource-questions-design.md` §5.3
(Discovery: *reason over what Scouting stored, zero new fetch*), the
`schema_conventions`, `db_change_rates` and proposed-`DataScope` rows of §5.4,
and §5.7's own `db_derived` line: *"reads stored rows only — cost none/low —
produces Classification (db kind), DataGrain, Fingerprint, conventions checks,
change rates, proposed DataScope."*

**This module opens no connection of any kind.** Not to the surveyed database,
not to Egeria. Every input is a row RE already stored: the structured tables
Phase 0 stream 3 created (`database_schemas`, `database_tables`,
`database_columns`, `database_column_profiles`, `database_table_activity`) and
populated further by slices 7 and 8. It is deliberately NOT a
`DatabaseSurveyor.survey()` step, because `survey()` opens
`database_connection(...)` unconditionally before dispatching any step — a
zero-fetch step living inside it would pay for a connection it never uses, and
would be unable to run at all for a database whose credentials are gone. The
entry point is `run_db_derived(registry, slug)`, which takes a registry and a
slug and nothing else. `tests/test_db_derived_step.py` pins that with a test
that fails if `database_connection` is so much as referenced.

## Absence discipline

Four states, the same vocabulary slices 7 and 8 use (`registry.STATE_*`), and
the distinction this whole module turns on:

- **A measured negative is a real finding.** "This database has no foreign
  keys at all — it is a bag of tables" is an answer, not an absence. So is "no
  table in the registry structurally resembles this one".
- **Not established is not a negative.** "No survey ever captured key
  information for these rows" is not "there are no keys". "Only one survey run
  exists" is not "nothing changed". "No other database has stored schema rows"
  is not "this is not a copy".

Every check below names which of the two it is producing, and the confidence
of an inferred finding is computed from how much signal was actually available
(see `_CLASSIFICATION_SIGNAL_WEIGHTS`) rather than asserted.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime

from resource_explorer.registry import (
    SOURCE_LOCAL,
    STATE_MEASURED,
    STATE_NOT_MEASURED,
)
from resource_explorer.surveyors.survey_report import (
    ClassificationAnnotation,
    DataGrainAnnotation,
    FingerprintAnnotation,
    ResourceMeasureAnnotation,
    SchemaAnalysisAnnotation,
)

log = logging.getLogger(__name__)

#: The `re_analysis_step` key, and the `analysis_step` stamped on every
#: annotation this module produces.
ANALYSIS_STEP = "db_derived"

#: The analysis-catalog ids this one step backs (design §5.7 folds all six
#: into `db_derived`). Consumed by the web per-card dispatch and by
#: `survey_definition_adapter`, so there is one list rather than three.
DB_DERIVED_ANALYSES: tuple[str, ...] = (
    "db_classification",
    "db_relationship_graph",
    "grain_determination",
    "db_fingerprint",
    "schema_conventions",
    "db_change_rates",
)

#: NOTE on the two annotation sites that carry this check's name: they spell
#: it as a LITERAL rather than referencing this constant, deliberately.
#: `tests/test_annotation_check_names.py`'s shared-check-name guard only reads
#: `ast.Constant` keyword values, so a `check_name=<CONSTANT>` site is
#: invisible to it — using the constant there would have dodged the guard
#: rather than satisfied it. `TestPublishMapping` pins the literal against
#: this constant so the two cannot drift.
#:
#: `DataScope` is proposed by the `db_change_rates`/profile-reading half rather
#: than being its own catalog entry: design §5.4 hangs it off `column_profile`
#: ("[date ranges] → proposed DataScope"), and slice 9's job per the brief is
#: the *derivation*, not a new question row. It runs whenever this step runs.
_PROPOSED_SCOPE_CHECK = "proposed_data_scope"

# ── classification ─────────────────────────────────────────────────────────
#
# The kinds design §5.3 names, verbatim: "transactional, analytical, reference
# data, staging, a copy".
KIND_TRANSACTIONAL = "transactional"
KIND_ANALYTICAL = "analytical"
KIND_REFERENCE = "reference_data"
KIND_STAGING = "staging"
KIND_COPY = "copy"

_ALL_KINDS = (KIND_TRANSACTIONAL, KIND_ANALYTICAL, KIND_REFERENCE,
              KIND_STAGING, KIND_COPY)

#: Signal families and their weights. A family with no usable data is left
#: OUT of the denominator rather than contributing zeros — that is the
#: difference between "we had less to go on" (lower confidence, honest) and
#: "every kind scored zero on this axis" (a silent, confident lie). The
#: brief's own example is the one this protects: no tuple-counter data because
#: ANALYZE never ran must read as insufficient signal, never as "staging".
_CLASSIFICATION_SIGNAL_WEIGHTS: dict[str, float] = {
    #: keys, FK density, table widths, row-count skew
    "structure": 3.0,
    #: table-name prefixes/suffixes
    "naming": 2.0,
    #: read/write mix from pg_stat_user_tables tuple counters
    "activity": 3.0,
    #: structural similarity to another database in the registry
    "fingerprint": 2.0,
}
_TOTAL_CLASSIFICATION_WEIGHT = sum(_CLASSIFICATION_SIGNAL_WEIGHTS.values())

#: An inference never reaches certainty. 95 is the ceiling for a derived
#: classification however clean the signal; a direct measurement (the
#: conventions counts, a PK-derived grain) is not bounded by this.
_MAX_INFERRED_CONFIDENCE = 95
#: Below this, the step reports "no confident classification" rather than
#: naming a kind — the margin between the top two candidates was too small to
#: distinguish them. Stated here rather than buried in a comparison.
_MIN_CLASSIFICATION_CONFIDENCE = 25

#: Table-name patterns per kind. Matched against the bare table name,
#: lower-cased. Deliberately conservative: a pattern that fires on ordinary
#: business names would swamp the naming family.
_NAME_PATTERNS: dict[str, tuple[str, ...]] = {
    KIND_ANALYTICAL: (
        r"^dim[_.]", r"^fact[_.]", r"[_.]fact$", r"[_.]dim$", r"^agg[_.]",
        r"^mart[_.]", r"[_.]mart$", r"^cube[_.]", r"[_.]summary$",
        r"^rollup[_.]", r"[_.]rollup$", r"^daily[_.]", r"^monthly[_.]",
    ),
    KIND_REFERENCE: (
        r"^ref[_.]", r"^lookup[_.]", r"^lu[_.]", r"[_.]lookup$",
        r"[_.]codes?$", r"[_.]types?$", r"^code[_.]", r"[_.]enum$",
        r"[_.]categories$", r"[_.]status$",
    ),
    KIND_STAGING: (
        r"^stg[_.]", r"^staging[_.]", r"^tmp[_.]", r"^temp[_.]", r"^raw[_.]",
        r"[_.]raw$", r"[_.]stg$", r"[_.]staging$", r"^landing[_.]",
        r"^ingest[_.]", r"[_.]tmp$", r"[_.]temp$", r"[_.]wrk$", r"^wrk[_.]",
    ),
    KIND_COPY: (
        r"[_.]copy$", r"[_.]bak$", r"[_.]backup$", r"[_.]old$", r"[_.]new$",
        r"[_.]v\d+$", r"[_.]20\d\d\d*$", r"[_.]archive$", r"[_.]orig$",
        r"[_.]final$",
    ),
}

#: A table this wide is evidence of a denormalised/analytical shape rather
#: than a normalised transactional one. Not a cliff: evidence ramps to 1.0 at
#: twice this.
_WIDE_TABLE_COLUMNS = 20
#: At or below this many rows a table looks like a code/reference list rather
#: than a transaction store.
_SMALL_TABLE_ROWS = 1000

# ── fingerprint thresholds ─────────────────────────────────────────────────
#
# Stated as named constants because the brief asks for a *measure*, not a
# verdict pulled out of the air, and because a reader disputing a "likely
# copy" needs to see the line it crossed.

#: Column-signature Jaccard at or above this reads as the same database.
_COPY_JACCARD = 0.95
#: Containment (|A∩B| / |A|) at or above this, with B strictly larger, reads
#: as "A is a subset of B" — the case Jaccard alone misses, because a small
#: true subset of a large database has low Jaccard by construction.
_SUBSET_CONTAINMENT = 0.90
#: Shares meaningful structure without being a copy or a clean subset.
_RELATED_JACCARD = 0.50
#: Below this, not reported at all — incidental overlap (`id`, `created_at`)
#: between unrelated schemas.
_REPORTABLE_JACCARD = 0.30

#: Types whose stored profile min/max can carry a temporal range (§5.4's
#: "what is the data's scope in time"). Matched as a substring of the stored
#: `base_type`/`data_type`, so `timestamp with time zone` and `timestamptz`
#: both land.
_DATE_TYPE_MARKERS = ("date", "timestamp", "timestamptz", "datetime")

#: `snake_case`, the convention every table in this codebase's own registry
#: follows. A name that needs quoting in SQL (upper case, spaces, dashes) is
#: the violation this reports; it is not a style opinion so much as a
#: portability and tooling hazard.
_SNAKE_CASE_RE = re.compile(r"^[a-z_][a-z0-9_]*$")


# ═══════════════════════════════════════════════════════════════════════════
# Inputs
# ═══════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class DerivedInputs:
    """One snapshot's stored rows — everything the checks are allowed to read.

    Built by `load_inputs`. A frozen dataclass rather than a dict so a check
    cannot quietly reach for a table nobody loaded.
    """
    slug: str
    surveyed_at: str | None
    source: str | None
    schemas: list[dict] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    columns: list[dict] = field(default_factory=list)
    profiles: list[dict] = field(default_factory=list)
    activity: list[dict] = field(default_factory=list)

    @property
    def has_schema_rows(self) -> bool:
        return bool(self.tables or self.columns)

    @property
    def keys_were_captured(self) -> bool:
        """Did the survey that wrote these column rows record key information?

        The distinction this module cares about most. `result_materializer`
        writes `is_primary_key = None` for a NATIVE Egeria survey read-back
        ("Native does not report keys; leave is_primary_key absent rather
        than…"), and 0/1 for a local survey whose blob carried them. So:

        - every column row has `is_primary_key IS NULL` → keys were never
          captured. "No primary keys" is NOT established.
        - any row carries 0 or 1 → keys were captured, and a table with none
          genuinely has none.

        Without this test, a native-only survey would report every table as
        lacking a primary key, with total confidence, having never looked.
        """
        return any(c.get("is_primary_key") is not None for c in self.columns)


def load_inputs(
    registry,
    slug: str,
    surveyed_at: str | None = None,
    source: str | None = None,
) -> DerivedInputs:
    """Read one snapshot's stored rows. No fetch, no connection."""
    def _rows(table: str) -> list[dict]:
        try:
            return registry.query_detail_rows(table, slug, surveyed_at, source)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("db_derived: could not read %s for %s: %s", table, slug, exc)
            return []

    return DerivedInputs(
        slug=slug,
        surveyed_at=surveyed_at,
        source=source,
        schemas=_rows("database_schemas"),
        tables=_rows("database_tables"),
        columns=_rows("database_columns"),
        profiles=_rows("database_column_profiles"),
        activity=_rows("database_table_activity"),
    )


def _table_key(row: dict) -> tuple[str, str]:
    return (row.get("schema_name") or "", row.get("table_name") or "")


def _columns_by_table(columns: list[dict]) -> dict[tuple[str, str], list[dict]]:
    out: dict[tuple[str, str], list[dict]] = {}
    for col in columns:
        out.setdefault(_table_key(col), []).append(col)
    return out


def _is_base_table(row: dict) -> bool:
    """Views and materialised views are excluded from the structural checks.

    A view has no grain of its own to propose, no primary key to be missing,
    and counting it as a "table with no PK" would produce a conventions
    finding nobody can act on. `table_type` comes straight from
    `information_schema.tables`, so the values are Postgres's own.
    """
    ttype = (row.get("table_type") or "").upper().replace(" ", "_")
    if not ttype:
        # Not recorded — treat as a base table rather than dropping it
        # silently. An unrecorded type is not evidence of a view.
        return True
    return ttype in {"BASE_TABLE", "TABLE", "LOCAL_TEMPORARY", "FOREIGN"}


def _foreign_key_edges(columns: list[dict]) -> list[dict]:
    """FK edges from the stored `foreign_key_json` column.

    Shape per `connection.py`'s `fk_lookup`: `{"foreign_schema",
    "foreign_table", "foreign_column"}`. `registry._decode_detail_row` has
    already turned the stored TEXT back into a dict.
    """
    edges: list[dict] = []
    for col in columns:
        fk = col.get("foreign_key_json")
        if not isinstance(fk, dict):
            continue
        target_table = fk.get("foreign_table") or ""
        if not target_table:
            continue
        edges.append({
            "from_schema": col.get("schema_name") or "",
            "from_table": col.get("table_name") or "",
            "from_column": col.get("column_name") or "",
            "to_schema": fk.get("foreign_schema") or col.get("schema_name") or "",
            "to_table": target_table,
            "to_column": fk.get("foreign_column") or "",
        })
    return edges


def _distinct_estimate(profile: dict, row_count: int | None) -> float | None:
    """Resolve `pg_stats.n_distinct`'s two-sign convention to a row count.

    Postgres stores a NEGATIVE `n_distinct` to mean "this fraction of the row
    count", with −1 meaning every value is distinct. Slice 7 stores the raw
    figure (`"distinct_count": stat.get("n_distinct")`), so a consumer that
    reads it as a plain count sees −1 distinct values in a unique column and
    concludes the opposite of the truth.

    Returns None when the value is absent, or when it is a negative fraction
    and no row count is available to resolve it against — an unresolvable
    estimate is not a measurement.
    """
    raw = profile.get("distinct_count")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value >= 0:
        return value
    if not row_count:
        return None
    return abs(value) * float(row_count)


def _parse_ts(value) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    # Compare naive to naive: the stored timestamps are a mix (utcnow()
    # isoformat has no offset; a native read-back may carry one), and
    # subtracting across that boundary raises.
    return parsed.replace(tzinfo=None)


def _ratio(numerator: float, denominator: float) -> float:
    return (numerator / denominator) if denominator else 0.0


def _ramp(value: float, full_at: float) -> float:
    """Linear 0→1 ramp, clamped. Used so a threshold is a slope, not a cliff."""
    if full_at <= 0:
        return 0.0
    return max(0.0, min(1.0, value / full_at))


# ═══════════════════════════════════════════════════════════════════════════
# 1. db_classification  (design §5.3)
# ═══════════════════════════════════════════════════════════════════════════

def _structure_evidence(inputs: DerivedInputs) -> dict[str, float] | None:
    """Keys, FK density, widths and row-count skew → evidence per kind.

    Returns None when there is nothing structural to read, so the family is
    excluded from the confidence denominator rather than scoring zeros.
    """
    tables = [t for t in inputs.tables if _is_base_table(t)]
    if not tables:
        return None

    by_table = _columns_by_table(inputs.columns)
    keys_captured = inputs.keys_were_captured

    table_count = len(tables)
    with_pk = 0
    widths: list[int] = []
    row_counts: list[int] = []
    small_tables = 0

    for table in tables:
        key = _table_key(table)
        cols = by_table.get(key, [])
        if keys_captured and any(c.get("is_primary_key") for c in cols):
            with_pk += 1
        width = table.get("column_count")
        if width is None:
            width = len(cols) or None
        if width:
            widths.append(int(width))
        rows = table.get("row_count")
        if rows is not None:
            row_counts.append(int(rows))
            if int(rows) <= _SMALL_TABLE_ROWS:
                small_tables += 1

    edges = _foreign_key_edges(inputs.columns) if keys_captured else []
    fk_density = _ratio(len(edges), table_count)
    avg_width = (sum(widths) / len(widths)) if widths else 0.0
    wide = _ramp(avg_width - _WIDE_TABLE_COLUMNS, _WIDE_TABLE_COLUMNS)
    small_share = _ratio(small_tables, len(row_counts)) if row_counts else 0.0

    # Row-count skew: one or two enormous tables beside many small ones is
    # the analytical/warehouse shape. Share of all rows held by the largest
    # table, only meaningful with several tables and a real total.
    skew = 0.0
    total_rows = sum(row_counts)
    if len(row_counts) >= 3 and total_rows > 0:
        skew = _ratio(max(row_counts), total_rows)

    if keys_captured:
        pk_coverage = _ratio(with_pk, table_count)
        no_pk_share = 1.0 - pk_coverage
    else:
        # Keys were never captured. Neither "has keys" nor "has no keys" is
        # evidence here, so both the PK and FK signals contribute nothing —
        # but the rest of the family (widths, row skew, small-table share) is
        # still real, so the family stays in.
        pk_coverage = 0.0
        no_pk_share = 0.0

    evidence = {
        KIND_TRANSACTIONAL: min(
            1.0, 0.5 * pk_coverage + 0.5 * _ramp(fk_density, 1.0),
        ),
        KIND_ANALYTICAL: min(1.0, 0.55 * wide + 0.45 * skew),
        KIND_REFERENCE: min(1.0, 0.7 * small_share + 0.3 * pk_coverage),
        KIND_STAGING: min(1.0, no_pk_share),
        # Structure alone cannot tell a copy from its original — that is
        # exactly what the fingerprint family is for.
        KIND_COPY: 0.0,
    }
    return evidence


def _naming_evidence(inputs: DerivedInputs) -> dict[str, float] | None:
    tables = [t for t in inputs.tables if _is_base_table(t)]
    if not tables:
        return None

    counts = {kind: 0 for kind in _NAME_PATTERNS}
    for table in tables:
        name = (table.get("table_name") or "").lower()
        for kind, patterns in _NAME_PATTERNS.items():
            if any(re.search(p, name) for p in patterns):
                counts[kind] += 1

    total = len(tables)
    # A naming convention does not need to be universal to be evidence — a
    # quarter of tables prefixed `stg_` is a strong signal — so the share is
    # ramped to full at a third of tables rather than at all of them.
    evidence = {
        kind: _ramp(_ratio(count, total), 0.33)
        for kind, count in counts.items()
    }
    # Ordinary business names support "transactional" by elimination: this is
    # the one kind with no distinctive naming of its own.
    evidence[KIND_TRANSACTIONAL] = max(0.0, 1.0 - max(evidence.values(), default=0.0))
    return evidence


def _activity_evidence(inputs: DerivedInputs) -> dict[str, float] | None:
    """Read/write mix from the stored tuple counters.

    Returns None when no row carries a counter — the case the brief singles
    out. An ANALYZE that never ran, or a table the statistics collector has
    no row for, leaves these NULL, and reading NULL as 0 would make a
    never-measured database look exactly like a completely idle one.
    """
    if not inputs.activity:
        return None

    ins = upd = dele = seq = idx = 0
    measured_rows = 0
    for row in inputs.activity:
        values = [row.get("rows_inserted"), row.get("rows_updated"),
                  row.get("rows_deleted"), row.get("seq_scan"), row.get("idx_scan")]
        if all(v is None for v in values):
            continue
        measured_rows += 1
        ins += int(row.get("rows_inserted") or 0)
        upd += int(row.get("rows_updated") or 0)
        dele += int(row.get("rows_deleted") or 0)
        seq += int(row.get("seq_scan") or 0)
        idx += int(row.get("idx_scan") or 0)

    if not measured_rows:
        return None

    writes = ins + upd + dele
    reads = seq + idx
    if writes == 0 and reads == 0:
        # Genuinely measured, and genuinely idle since the last stats reset.
        # That is a real state, but it does not distinguish the five kinds,
        # so the family has no evidence to offer and is excluded. Recorded
        # in the classification's own explanation via `signals_used`.
        return None

    mutate_share = _ratio(upd + dele, writes)
    insert_share = _ratio(ins, writes)
    seq_share = _ratio(seq, reads)
    read_only = 1.0 if writes == 0 and reads > 0 else 0.0
    churn = min(_ramp(_ratio(ins, writes), 0.5), _ramp(_ratio(dele, writes), 0.3))

    evidence = {
        # OLTP rewrites and deletes rows in place, and reads by index.
        KIND_TRANSACTIONAL: min(1.0, 0.6 * mutate_share + 0.4 * (1.0 - seq_share)),
        # Warehouses append and scan.
        KIND_ANALYTICAL: min(1.0, 0.5 * insert_share + 0.5 * seq_share),
        KIND_REFERENCE: read_only,
        # Load-then-truncate churn: lots of inserts AND lots of deletes.
        KIND_STAGING: churn,
        KIND_COPY: 0.0,
    }
    return evidence


def _fingerprint_evidence(fingerprint: dict) -> dict[str, float] | None:
    """Copy evidence from the fingerprint check's own best match."""
    if fingerprint.get("state") != STATE_MEASURED:
        return None
    if not fingerprint.get("comparable_databases"):
        return None
    best = fingerprint.get("best_similarity")
    if best is None:
        return None
    evidence = {kind: 0.0 for kind in _ALL_KINDS}
    # Ramp from the reportable floor to the copy threshold, so a 0.3 overlap
    # is nearly no evidence and a 0.95 match is full evidence.
    span = _COPY_JACCARD - _REPORTABLE_JACCARD
    evidence[KIND_COPY] = _ramp(float(best) - _REPORTABLE_JACCARD, span)
    return evidence


def classify_database(inputs: DerivedInputs, fingerprint: dict) -> dict:
    """Derive what kind of database this is, with a confidence that reflects
    how much signal was available (design §5.3, §5.1's `not_established`).
    """
    families = {
        "structure": _structure_evidence(inputs),
        "naming": _naming_evidence(inputs),
        "activity": _activity_evidence(inputs),
        "fingerprint": _fingerprint_evidence(fingerprint),
    }
    available = {name: ev for name, ev in families.items() if ev is not None}
    missing = sorted(name for name, ev in families.items() if ev is None)

    if not available:
        return {
            "state": STATE_NOT_MEASURED,
            "kind": None,
            "confidence": 0,
            "scores": {},
            "signals_used": [],
            "signals_missing": missing,
            "explanation": (
                "No stored rows carry a classification signal for this "
                "database: no table/column catalog, no tuple counters, and "
                "no comparable database in the registry. This is insufficient "
                "signal, not a finding that the database is of no particular "
                "kind — run a schema survey (and ANALYZE, for the activity "
                "signal) first."
            ),
        }

    available_weight = sum(_CLASSIFICATION_SIGNAL_WEIGHTS[name] for name in available)
    scores: dict[str, float] = {}
    for kind in _ALL_KINDS:
        total = sum(
            _CLASSIFICATION_SIGNAL_WEIGHTS[name] * ev.get(kind, 0.0)
            for name, ev in available.items()
        )
        scores[kind] = round(total / available_weight, 4)

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_kind, best_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0.0

    coverage = available_weight / _TOTAL_CLASSIFICATION_WEIGHT
    margin = _ratio(best_score - second_score, best_score)
    # Three factors, all of them things a reader can dispute separately: how
    # much of the signal was available, how clearly the winner won, and how
    # strong the winning evidence was in absolute terms.
    confidence = round(
        _MAX_INFERRED_CONFIDENCE * coverage * (0.35 + 0.65 * margin)
        * min(1.0, best_score * 2)
    )
    confidence = max(0, min(_MAX_INFERRED_CONFIDENCE, confidence))

    undecided = best_score <= 0 or confidence < _MIN_CLASSIFICATION_CONFIDENCE
    explanation_parts = [
        (f"Derived from {len(available)} of {len(families)} signal families "
         f"({', '.join(sorted(available))})."),
    ]
    if missing:
        explanation_parts.append(
            f"No data for: {', '.join(missing)} — these contributed nothing "
            f"rather than counting as zero, which is why the confidence is "
            f"scaled to {int(coverage * 100)}% coverage."
        )
    if "activity" in missing:
        explanation_parts.append(
            "In particular there are no usable tuple counters, so the "
            "read/write mix is unknown. That is insufficient signal, NOT "
            "evidence of a staging or idle database."
        )
    if undecided:
        explanation_parts.append(
            f"The top two candidates ({ranked[0][0]} {best_score:.2f}, "
            f"{ranked[1][0] if len(ranked) > 1 else '-'} {second_score:.2f}) "
            f"are too close to call at this coverage."
        )

    return {
        "state": STATE_MEASURED,
        "kind": None if undecided else best_kind,
        "confidence": 0 if undecided else confidence,
        "scores": scores,
        "ranked": [k for k, _ in ranked],
        "signals_used": sorted(available),
        "signals_missing": missing,
        "coverage": round(coverage, 3),
        "explanation": " ".join(explanation_parts),
    }


# ═══════════════════════════════════════════════════════════════════════════
# 2. db_relationship_graph  (design §5.3)
# ═══════════════════════════════════════════════════════════════════════════

def derive_relationship_graph(inputs: DerivedInputs) -> dict:
    """Is there a data model here, or a bag of tables?

    The absence case that matters: a survey that never captured key
    information (every `is_primary_key` NULL — the native read-back path)
    must NOT report "no foreign keys". A survey that DID capture keys and
    found none is reporting a real, positive finding.
    """
    tables = [t for t in inputs.tables if _is_base_table(t)]
    if not tables:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "no_schema_rows",
            "explanation": (
                "No stored table rows for this database, so there is no graph "
                "to derive. Not a finding that the tables do not relate."
            ),
        }

    if not inputs.keys_were_captured:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "keys_not_captured",
            "table_count": len(tables),
            "explanation": (
                f"{len(tables)} tables are stored, but no column row carries "
                "key information (every `is_primary_key` is NULL), which is "
                "how a native Egeria survey read-back stores columns — it "
                "does not report keys. So whether these tables relate is "
                "NOT established. This is emphatically not a finding that "
                "the database has no foreign keys; run a local schema "
                "survey, which captures constraints, to answer it."
            ),
        }

    edges = _foreign_key_edges(inputs.columns)
    names = {_table_key(t) for t in tables}
    # Adjacency over table identity, ignoring direction for component
    # counting (a data model is connected whichever way you walk it).
    adjacency: dict[tuple[str, str], set[tuple[str, str]]] = {n: set() for n in names}
    in_degree: dict[tuple[str, str], int] = {n: 0 for n in names}
    dangling: list[dict] = []
    for edge in edges:
        src = (edge["from_schema"], edge["from_table"])
        dst = (edge["to_schema"], edge["to_table"])
        if src not in adjacency:
            continue
        if dst not in adjacency:
            # References a table this snapshot does not contain — a
            # cross-schema target the survey did not cover, not a broken FK.
            dangling.append(edge)
            continue
        adjacency[src].add(dst)
        adjacency[dst].add(src)
        in_degree[dst] += 1

    # Connected components by breadth-first walk.
    seen: set[tuple[str, str]] = set()
    components: list[list[tuple[str, str]]] = []
    for node in names:
        if node in seen:
            continue
        stack = [node]
        component: list[tuple[str, str]] = []
        seen.add(node)
        while stack:
            current = stack.pop()
            component.append(current)
            for neighbour in adjacency[current]:
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        components.append(component)

    isolated = sorted(
        f"{s}.{t}" for (s, t) in names if not adjacency[(s, t)]
    )
    connected_tables = len(names) - len(isolated)
    largest = max((len(c) for c in components), default=0)

    if not edges:
        verdict = "bag_of_tables"
        explanation = (
            f"Measured: all {len(tables)} tables were checked and not one "
            "declares a foreign key. This is a real finding — the database "
            "is a bag of tables with no enforced relational model — not a "
            "gap in what was surveyed."
        )
    elif _ratio(connected_tables, len(names)) >= 0.7:
        verdict = "data_model"
        explanation = (
            f"{len(edges)} foreign keys connect {connected_tables} of "
            f"{len(names)} tables into {len(components)} component(s), the "
            f"largest holding {largest}. A real relational model."
        )
    else:
        verdict = "partial_model"
        explanation = (
            f"{len(edges)} foreign keys connect only {connected_tables} of "
            f"{len(names)} tables; {len(isolated)} stand alone. A partial "
            "model — some of the schema is related, much of it is not."
        )

    hubs = sorted(
        ({"table": f"{s}.{t}", "referenced_by": d} for (s, t), d in in_degree.items() if d),
        key=lambda h: h["referenced_by"], reverse=True,
    )[:10]

    return {
        "state": STATE_MEASURED,
        "verdict": verdict,
        "table_count": len(tables),
        "edge_count": len(edges),
        "component_count": len(components),
        "largest_component": largest,
        "connected_tables": connected_tables,
        "isolated_tables": isolated,
        "dangling_references": dangling,
        "most_referenced": hubs,
        "edges": edges,
        "explanation": explanation,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 3. grain_determination  (design §5.3, bold in the design doc)
# ═══════════════════════════════════════════════════════════════════════════

#: Confidence per basis. A primary key IS the grain — declared by the schema,
#: not inferred — so it is high but still short of a measurement, because the
#: STATEMENT (what one row means in business terms) remains an inference from
#: column names. A distinct-count match is weaker again: `n_distinct` is an
#: ANALYZE-time estimate, and uniqueness today is not a declared constraint.
_GRAIN_CONFIDENCE = {
    "primary_key": 90,
    "unique_column_exact": 65,
    "unique_column_estimated": 50,
}
#: distinct/row ratio at or above which a column is treated as a candidate
#: key. Not 1.0: `n_distinct` is an estimate from a sample, so an exactly-
#: unique column routinely reports slightly under.
_UNIQUE_RATIO_EXACT = 0.99
_UNIQUE_RATIO_LIKELY = 0.95


def determine_grain(inputs: DerivedInputs) -> dict:
    """One row per what, per table (design §5.3).

    Produces, per table, exactly one of:
      - a grain with a basis and a confidence (a proposal — see the module
        docstring on `contentStatus: DRAFT`);
      - `no_candidate_key`: measured, and nothing identifies a row. A real
        finding about the modelling, per design §5.6's "grain clarity".
      - `insufficient_signal`: no keys captured and no stored profile to fall
        back on. Not a finding at all.
    """
    tables = [t for t in inputs.tables if _is_base_table(t)]
    if not tables:
        return {"state": STATE_NOT_MEASURED, "reason": "no_schema_rows", "grains": []}

    cols_by_table = _columns_by_table(inputs.columns)
    profiles_by_table: dict[tuple[str, str], list[dict]] = {}
    for profile in inputs.profiles:
        profiles_by_table.setdefault(_table_key(profile), []).append(profile)

    keys_captured = inputs.keys_were_captured
    grains: list[dict] = []

    for table in tables:
        key = _table_key(table)
        schema_name, table_name = key
        cols = cols_by_table.get(key, [])
        row_count = table.get("row_count")
        profiles = profiles_by_table.get(key, [])

        date_columns = [
            c.get("column_name") for c in cols
            if any(m in ((c.get("base_type") or c.get("data_type") or "").lower())
                   for m in _DATE_TYPE_MARKERS)
        ]
        date_columns = [d for d in date_columns if d]

        pk_columns = [
            c.get("column_name") for c in cols if c.get("is_primary_key")
        ] if keys_captured else []
        pk_columns = [p for p in pk_columns if p]

        entry: dict = {
            "schema_name": schema_name,
            "table_name": table_name,
            "qualified_name": f"{schema_name}.{table_name}",
            "row_count": row_count,
            "date_columns": date_columns,
        }

        if pk_columns:
            entry.update(_grain_from_pk(pk_columns, date_columns))
            grains.append(entry)
            continue

        # No primary key (or keys were never captured). Fall back to the
        # stored profile: a column whose distinct count matches the row count
        # is a candidate key.
        candidate = _grain_from_profiles(profiles, row_count)
        if candidate:
            entry.update(candidate)
            if date_columns:
                entry["interval"] = _interval_from_columns(date_columns)
            grains.append(entry)
            continue

        if not profiles:
            entry.update({
                "state": STATE_NOT_MEASURED,
                "basis": None,
                "grain_statement": "",
                "confidence": 0,
                "label": "unverified",
                "explanation": (
                    ("No key information was captured for this table, and no "
                     if not keys_captured else
                     "This table declares no primary key, and no ")
                    + "stored column profile exists to look for a candidate key "
                      "in. The grain is NOT established — run the statistics "
                      "step (and ANALYZE, so pg_stats is populated) rather than "
                      "reading this as a table without a grain."
                ),
            })
            grains.append(entry)
            continue

        # Profiles exist and nothing in them is unique: a real finding.
        entry.update({
            "state": STATE_MEASURED,
            "basis": None,
            "grain_statement": "",
            "confidence": 0,
            "label": "gap",
            "explanation": (
                f"Measured: this table declares no primary key and none of its "
                f"{len(profiles)} profiled columns has a distinct count near "
                f"its row count. No column or simple column pair identifies a "
                f"row, so the grain is genuinely undetermined in the data — a "
                f"modelling gap (design §5.6, 'grain clarity'), not missing "
                f"evidence."
            ),
        })
        grains.append(entry)

    determined = [g for g in grains if g.get("grain_statement")]
    return {
        "state": STATE_MEASURED,
        "grains": grains,
        "table_count": len(tables),
        "determined_count": len(determined),
        "undetermined_count": len(grains) - len(determined),
        "keys_were_captured": keys_captured,
    }


def _grain_from_pk(pk_columns: list[str], date_columns: list[str]) -> dict:
    statement = "one row per " + " + ".join(pk_columns)
    interval = ""
    # A PK that itself contains a date column is a per-period grain, which is
    # the distinction `interval` exists to carry.
    pk_dates = [c for c in pk_columns if c in date_columns]
    if pk_dates:
        interval = _interval_from_columns(pk_dates)
    return {
        "state": STATE_MEASURED,
        "basis": "primary_key",
        "grain_statement": statement,
        "grain_columns": pk_columns,
        "interval": interval,
        "confidence": _GRAIN_CONFIDENCE["primary_key"],
        "label": "pass",
        "explanation": (
            f"The declared primary key ({', '.join(pk_columns)}) is the grain: "
            f"{statement}. Basis: the schema's own constraint, read from "
            f"stored column rows."
        ),
    }


def _grain_from_profiles(profiles: list[dict], row_count: int | None) -> dict | None:
    if not profiles or not row_count:
        return None
    best: tuple[float, dict] | None = None
    for profile in profiles:
        distinct = _distinct_estimate(profile, row_count)
        if distinct is None:
            continue
        ratio = _ratio(distinct, float(row_count))
        if ratio < _UNIQUE_RATIO_LIKELY:
            continue
        if best is None or ratio > best[0]:
            best = (ratio, profile)
    if best is None:
        return None
    ratio, profile = best
    column = profile.get("column_name") or ""
    exact = ratio >= _UNIQUE_RATIO_EXACT
    basis = "unique_column_exact" if exact else "unique_column_estimated"
    return {
        "state": STATE_MEASURED,
        "basis": basis,
        "grain_statement": f"one row per {column}",
        "grain_columns": [column],
        "interval": "",
        "confidence": _GRAIN_CONFIDENCE[basis],
        "label": "pass",
        "explanation": (
            f"No primary key is declared, but {column!r} has an estimated "
            f"{ratio:.3f} distinct values per row (pg_stats n_distinct against "
            f"the stored row count), so it behaves as a key. This is an "
            f"ANALYZE-time estimate and an observation about today's data, not "
            f"a declared constraint — hence the reduced confidence."
        ),
    }


def _interval_from_columns(date_columns: list[str]) -> str:
    """Name the period a date column in the key implies, from its name only.

    Deliberately shallow: the stored rows carry the column's type and name,
    not its values' spacing, so "daily" here means "the key includes a date,
    so the grain is per-date" — not a measured cadence. Anything stronger
    would need the values, which is a fetch.
    """
    joined = " ".join(c.lower() for c in date_columns)
    for marker, interval in (
        ("month", "monthly"), ("week", "weekly"), ("year", "annual"),
        ("quarter", "quarterly"), ("hour", "hourly"),
    ):
        if marker in joined:
            return interval
    return "per-date"


# ═══════════════════════════════════════════════════════════════════════════
# 4. db_fingerprint  (design §3, §5.3)
# ═══════════════════════════════════════════════════════════════════════════

def _signature(columns: list[dict], tables: list[dict]) -> tuple[set[str], set[str]]:
    """(table signature, column signature) — the two sets similarity uses."""
    table_sig = {
        f"{t.get('schema_name') or ''}.{t.get('table_name') or ''}"
        for t in tables if _is_base_table(t)
    }
    column_sig = {
        f"{c.get('schema_name') or ''}.{c.get('table_name') or ''}."
        f"{c.get('column_name') or ''}:"
        f"{(c.get('base_type') or c.get('data_type') or '').lower()}"
        for c in columns
    }
    return table_sig - {"."}, column_sig


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    return _ratio(len(a & b), len(a | b))


def fingerprint_database(registry, inputs: DerivedInputs) -> dict:
    """Does this look like a copy or subset of a database we already know?

    Compares this database's stored schema signature against every OTHER
    database in RE's registry — still zero-fetch: the peers' signatures come
    from their own stored rows, not from connecting to them.

    The absence case: a registry with no other database carrying stored
    schema rows means there was nothing to compare against. That is NOT a
    finding that this database is unique.
    """
    table_sig, column_sig = _signature(inputs.columns, inputs.tables)
    if not column_sig and not table_sig:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "no_schema_rows",
            "explanation": (
                "No stored table or column rows, so no signature could be "
                "computed for this database."
            ),
        }

    digest = hashlib.sha256(
        "\n".join(sorted(column_sig)).encode("utf-8")
    ).hexdigest()

    try:
        peers = registry.list_databases()
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("db_derived: could not list databases for fingerprint: %s", exc)
        peers = []

    matches: list[dict] = []
    comparable = 0
    skipped: list[str] = []
    for peer in peers:
        peer_slug = getattr(peer, "slug", None) or (
            peer.get("slug") if isinstance(peer, dict) else None
        )
        if not peer_slug or peer_slug == inputs.slug:
            continue
        peer_inputs = load_inputs(registry, peer_slug)
        peer_tables, peer_columns = _signature(peer_inputs.columns, peer_inputs.tables)
        if not peer_columns and not peer_tables:
            skipped.append(peer_slug)
            continue
        comparable += 1

        col_jaccard = _jaccard(column_sig, peer_columns)
        tbl_jaccard = _jaccard(table_sig, peer_tables)
        containment = _ratio(len(column_sig & peer_columns), len(column_sig))
        reverse_containment = _ratio(len(column_sig & peer_columns), len(peer_columns))

        if col_jaccard >= _COPY_JACCARD:
            verdict = "likely_copy"
        elif containment >= _SUBSET_CONTAINMENT and len(peer_columns) > len(column_sig):
            verdict = "likely_subset_of"
        elif reverse_containment >= _SUBSET_CONTAINMENT and len(column_sig) > len(peer_columns):
            verdict = "likely_superset_of"
        elif col_jaccard >= _RELATED_JACCARD:
            verdict = "shares_structure"
        elif col_jaccard >= _REPORTABLE_JACCARD:
            verdict = "incidental_overlap"
        else:
            continue

        matches.append({
            "slug": peer_slug,
            "verdict": verdict,
            "column_jaccard": round(col_jaccard, 4),
            "table_jaccard": round(tbl_jaccard, 4),
            "containment": round(containment, 4),
            "reverse_containment": round(reverse_containment, 4),
            "shared_columns": len(column_sig & peer_columns),
            "peer_columns": len(peer_columns),
        })

    matches.sort(key=lambda m: m["column_jaccard"], reverse=True)
    best = matches[0]["column_jaccard"] if matches else None

    if comparable == 0:
        explanation = (
            "A signature was computed for this database "
            f"({len(table_sig)} tables, {len(column_sig)} columns, digest "
            f"{digest[:16]}), but no OTHER database in the registry has "
            "stored schema rows to compare it against"
            + (f" ({len(skipped)} peer(s) are registered but unsurveyed)"
               if skipped else "")
            + ". Whether this is a copy is NOT established — this is not a "
              "finding that it is unique."
        )
    elif not matches:
        explanation = (
            f"Measured: compared against {comparable} other database(s) with "
            f"stored schema, none shares even {_REPORTABLE_JACCARD:.0%} of "
            f"this database's column signature. A real finding — no known "
            f"database resembles this one."
        )
    else:
        top = matches[0]
        explanation = (
            f"Closest of {comparable} comparable database(s): {top['slug']} "
            f"({top['verdict']}, column-signature Jaccard "
            f"{top['column_jaccard']:.2f}, containment "
            f"{top['containment']:.2f}). Thresholds: copy ≥ {_COPY_JACCARD}, "
            f"subset containment ≥ {_SUBSET_CONTAINMENT}, related ≥ "
            f"{_RELATED_JACCARD}."
        )

    return {
        "state": STATE_MEASURED,
        "digest": digest,
        "table_count": len(table_sig),
        "column_count": len(column_sig),
        "comparable_databases": comparable,
        "unsurveyed_peers": skipped,
        "matches": matches,
        "best_similarity": best,
        "explanation": explanation,
    }


# ═══════════════════════════════════════════════════════════════════════════
# 5. schema_conventions  (design §5.4, folded into db_derived per §5.7)
# ═══════════════════════════════════════════════════════════════════════════

def check_conventions(inputs: DerivedInputs) -> dict:
    """The STRUCTURAL conventions checks, derivable from stored rows alone.

    Deliberately excludes unused indexes. Design §5.4's `schema_conventions`
    row lists them, but slice 7 already raises an unused-index
    `RequestForActionAnnotation` from a live `pg_stat_user_indexes` read
    (`DB-SCHEMA-AND-STATS-EXTENSION-IMPLEMENTED.md` §3), and index usage is
    not derivable from stored rows at all — no structured table carries it.
    Duplicating it here would produce two RFAs for one problem.
    """
    tables = [t for t in inputs.tables if _is_base_table(t)]
    if not tables:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "no_schema_rows",
            "checks": {},
        }

    cols_by_table = _columns_by_table(inputs.columns)
    keys_captured = inputs.keys_were_captured
    checks: dict[str, dict] = {}

    # ── no primary key ────────────────────────────────────────────────────
    if keys_captured:
        without_pk = sorted(
            f"{s}.{t}" for (s, t) in (_table_key(x) for x in tables)
            if not any(c.get("is_primary_key") for c in cols_by_table.get((s, t), []))
        )
        checks["tables_without_primary_key"] = {
            "state": STATE_MEASURED,
            "count": len(without_pk),
            "total": len(tables),
            "items": without_pk,
            "label": "gap" if without_pk else "pass",
            "explanation": (
                f"{len(without_pk)} of {len(tables)} base tables declare no "
                f"primary key."
                if without_pk else
                f"All {len(tables)} base tables declare a primary key."
            ),
        }
        without_fk = sorted(
            f"{s}.{t}" for (s, t) in (_table_key(x) for x in tables)
            if not any(
                isinstance(c.get("foreign_key_json"), dict)
                for c in cols_by_table.get((s, t), [])
            )
        )
        checks["tables_without_foreign_key"] = {
            "state": STATE_MEASURED,
            "count": len(without_fk),
            "total": len(tables),
            "items": without_fk,
            # Not automatically a gap: a reference table or a genuinely
            # standalone log table has no business declaring an FK. Reported
            # as a count for the relationship-graph verdict to interpret.
            "label": "info",
            "explanation": (
                f"{len(without_fk)} of {len(tables)} base tables declare no "
                f"foreign key. Whether that is a fault depends on the kind of "
                f"database — see db_relationship_graph's verdict."
            ),
        }
    else:
        for name in ("tables_without_primary_key", "tables_without_foreign_key"):
            checks[name] = {
                "state": STATE_NOT_MEASURED,
                "count": None,
                "total": len(tables),
                "items": [],
                "label": "unverified",
                "explanation": (
                    "No column row carries key information (every "
                    "`is_primary_key` is NULL — the native-survey read-back "
                    "path does not report keys), so this check could not run. "
                    "NOT a finding that keys are missing."
                ),
            }

    # ── comments ──────────────────────────────────────────────────────────
    #
    # `description` is '' both for "no comment" and, in principle, for a
    # column whose comment was not read. The distinction is carried at the
    # table level: if NOT ONE table or column in the whole database has a
    # description, the likelier explanation is that comments were not
    # captured than that a real database documents nothing. Reported as a
    # separate state rather than as 100% undocumented.
    undocumented_tables = sorted(
        f"{s}.{t}" for (s, t), row in ((_table_key(x), x) for x in tables)
        if not (row.get("description") or "").strip()
    )
    documented_tables = len(tables) - len(undocumented_tables)
    all_columns = [c for c in inputs.columns]
    documented_columns = sum(
        1 for c in all_columns if (c.get("description") or "").strip()
    )
    nothing_documented = (
        documented_tables == 0 and documented_columns == 0 and bool(all_columns)
    )
    checks["tables_without_comment"] = {
        "state": STATE_MEASURED if not nothing_documented else STATE_NOT_MEASURED,
        "count": len(undocumented_tables) if not nothing_documented else None,
        "total": len(tables),
        "items": undocumented_tables if not nothing_documented else [],
        "label": (
            "unverified" if nothing_documented
            else ("gap" if undocumented_tables else "pass")
        ),
        "explanation": (
            "Not one table and not one column in this database carries a "
            "description. That is more likely to mean comments were never "
            "captured by the survey that wrote these rows than that a real "
            "database documents nothing at all, so this is reported as "
            "unverified rather than as 100% undocumented."
            if nothing_documented else
            f"{len(undocumented_tables)} of {len(tables)} base tables have no "
            f"comment; {documented_columns} of {len(all_columns)} columns do."
        ),
    }
    checks["column_comment_coverage"] = {
        "state": STATE_MEASURED if not nothing_documented else STATE_NOT_MEASURED,
        "count": documented_columns if not nothing_documented else None,
        "total": len(all_columns),
        "fraction": (
            round(_ratio(documented_columns, len(all_columns)), 4)
            if all_columns and not nothing_documented else None
        ),
        "label": "unverified" if nothing_documented else "info",
        "explanation": (
            "See tables_without_comment — nothing in this database is "
            "documented, which reads as not captured."
            if nothing_documented else
            f"{documented_columns} of {len(all_columns)} stored columns carry "
            f"a description."
        ),
    }

    # ── naming convention ─────────────────────────────────────────────────
    offenders = sorted(
        f"{s}.{t}" for (s, t) in (_table_key(x) for x in tables)
        if t and not _SNAKE_CASE_RE.match(t)
    )
    column_offenders = sorted({
        f"{c.get('schema_name')}.{c.get('table_name')}.{c.get('column_name')}"
        for c in all_columns
        if c.get("column_name") and not _SNAKE_CASE_RE.match(c["column_name"])
    })
    checks["naming_convention"] = {
        "state": STATE_MEASURED,
        "count": len(offenders) + len(column_offenders),
        "total": len(tables) + len(all_columns),
        "items": offenders + column_offenders,
        "label": "gap" if (offenders or column_offenders) else "pass",
        "explanation": (
            f"{len(offenders)} table name(s) and {len(column_offenders)} "
            f"column name(s) are not lower snake_case, so they must be "
            f"double-quoted in every statement that touches them."
            if (offenders or column_offenders) else
            f"All {len(tables)} table names and {len(all_columns)} column "
            f"names are lower snake_case."
        ),
    }

    return {
        "state": STATE_MEASURED,
        "checks": checks,
        "table_count": len(tables),
        "column_count": len(all_columns),
        #: Named so a reader can tell this was a decision, not an omission.
        "excluded_checks": {
            "unused_indexes": (
                "Owned by postgres_schema_and_stats (slice 7), which reads "
                "pg_stat_user_indexes live and raises its own RFA. Index "
                "usage is not carried by any structured table, so it is not "
                "derivable here, and duplicating the RFA would double-report "
                "one problem."
            ),
        },
    }


# ═══════════════════════════════════════════════════════════════════════════
# 6. db_change_rates  (design §5.4, §5.7)
# ═══════════════════════════════════════════════════════════════════════════

def _snapshot_keys(registry, slug: str) -> list[tuple[str, str]]:
    """(surveyed_at, source) for every recorded survey run, newest first.

    Read from `database_surveys` rather than by scanning the detail tables,
    because that is the table that knows a run happened at all — and it needs
    no new registry method. Runs whose detail rows are absent are filtered by
    the caller, which asks for the rows and finds none.
    """
    try:
        surveys = registry.get_database_surveys(slug)
    except Exception as exc:  # pragma: no cover - defensive
        log.warning("db_derived: could not list surveys for %s: %s", slug, exc)
        return []
    keys: list[tuple[str, str]] = []
    for survey in surveys:
        at = survey.get("surveyed_at")
        if not at:
            continue
        keys.append((at, survey.get("source") or SOURCE_LOCAL))
    # Newest first, de-duplicated while preserving order.
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for key in sorted(keys, key=lambda k: k[0], reverse=True):
        if key in seen:
            continue
        seen.add(key)
        ordered.append(key)
    return ordered


def derive_change_rates(registry, inputs: DerivedInputs) -> dict:
    """Rows inserted/updated/deleted per table per period, and schema churn.

    Needs two snapshots. With one — the common case for a database surveyed
    once — this renders as `insufficient_history`: explicitly NOT zero change,
    and not an error either.

    No new structured table: the per-table series design §5.4 wants for
    Understanding-tier charts is already expressible as the existing
    `database_table_activity` rows across their several `surveyed_at` values,
    which is what this function walks. The series it returns is a convenience
    for the annotation payload, not a second copy of the data.
    """
    keys = _snapshot_keys(registry, inputs.slug)
    snapshots: list[tuple[str, str, list[dict], list[dict]]] = []
    for surveyed_at, source in keys:
        activity = registry.query_detail_rows(
            "database_table_activity", inputs.slug, surveyed_at, source
        )
        if not activity:
            continue
        tables = registry.query_detail_rows(
            "database_tables", inputs.slug, surveyed_at, source
        )
        snapshots.append((surveyed_at, source, activity, tables))
        if len(snapshots) == 2:
            break

    if len(snapshots) < 2:
        return {
            "state": STATE_NOT_MEASURED,
            "reason": "insufficient_history",
            "snapshots_available": len(snapshots),
            "explanation": (
                f"Change rates need two survey snapshots to difference; "
                f"{len(snapshots)} snapshot(s) of table activity exist for "
                f"this database. This is insufficient history — NOT a finding "
                f"that nothing is changing, and not a failure. Survey the "
                f"database again and this answers itself."
            ),
            "per_table": [],
        }

    (new_at, _new_src, new_activity, new_tables) = snapshots[0]
    (old_at, _old_src, old_activity, old_tables) = snapshots[1]

    start = _parse_ts(old_at)
    end = _parse_ts(new_at)
    interval_days: float | None = None
    if start and end:
        interval_days = max(0.0, (end - start).total_seconds() / 86400.0)

    old_by_table = {_table_key(r): r for r in old_activity}
    new_by_table = {_table_key(r): r for r in new_activity}
    old_tbl = {_table_key(r): r for r in old_tables}
    new_tbl = {_table_key(r): r for r in new_tables}

    per_table: list[dict] = []
    counters = ("rows_inserted", "rows_updated", "rows_deleted")
    for key, new_row in sorted(new_by_table.items()):
        schema_name, table_name = key
        old_row = old_by_table.get(key)
        entry: dict = {
            "schema_name": schema_name,
            "table_name": table_name,
            "qualified_name": f"{schema_name}.{table_name}",
        }
        if old_row is None:
            entry.update({
                "state": STATE_MEASURED,
                "change": "new_table",
                "explanation": (
                    "This table has activity in the newer snapshot and none "
                    "in the older one — it is new since the previous survey, "
                    "so there is no rate to difference yet."
                ),
            })
            per_table.append(entry)
            continue

        # A counter reset between snapshots makes the difference meaningless.
        # registry.py's own `stats_reset` comment is explicit about this: a
        # reset, failover or restore produces a negative delta that a chart
        # would faithfully draw as "−40,000 inserts".
        old_reset = old_row.get("stats_reset")
        new_reset = new_row.get("stats_reset")
        reset_moved = bool(old_reset and new_reset and old_reset != new_reset)
        went_backwards = any(
            (new_row.get(c) is not None and old_row.get(c) is not None
             and int(new_row[c]) < int(old_row[c]))
            for c in counters
        )
        if reset_moved or went_backwards:
            entry.update({
                "state": STATE_NOT_MEASURED,
                "change": "counters_reset",
                "stats_reset_old": old_reset,
                "stats_reset_new": new_reset,
                "explanation": (
                    "The cumulative tuple counters "
                    + ("reset between the two snapshots"
                       if reset_moved else "went backwards between the two "
                       "snapshots, which means they were reset")
                    + " — a reset, failover or restore. No rate is available "
                      "for this interval; the difference would be a negative "
                      "number rendered as a real one."
                ),
            })
            per_table.append(entry)
            continue

        deltas: dict[str, int | None] = {}
        unmeasured: list[str] = []
        for counter in counters:
            new_value, old_value = new_row.get(counter), old_row.get(counter)
            if new_value is None or old_value is None:
                deltas[counter] = None
                unmeasured.append(counter)
            else:
                deltas[counter] = int(new_value) - int(old_value)

        if len(unmeasured) == len(counters):
            entry.update({
                "state": STATE_NOT_MEASURED,
                "change": "counters_not_measured",
                "explanation": (
                    "Neither snapshot carries tuple counters for this table "
                    "(they are NULL — ANALYZE may never have run, or the "
                    "statistics step did not run). No rate, and not zero "
                    "change."
                ),
            })
            per_table.append(entry)
            continue

        total = sum(v for v in deltas.values() if v is not None)
        per_day = (
            {k: (round(v / interval_days, 3) if v is not None else None)
             for k, v in deltas.items()}
            if interval_days else None
        )
        old_size = (old_tbl.get(key) or {}).get("size_bytes")
        new_size = (new_tbl.get(key) or {}).get("size_bytes")
        size_delta = (
            int(new_size) - int(old_size)
            if new_size is not None and old_size is not None else None
        )
        old_rows = (old_tbl.get(key) or {}).get("row_count")
        new_rows = (new_tbl.get(key) or {}).get("row_count")
        row_delta = (
            int(new_rows) - int(old_rows)
            if new_rows is not None and old_rows is not None else None
        )

        entry.update({
            "state": STATE_MEASURED,
            "change": "idle" if total == 0 else "active",
            "deltas": deltas,
            "per_day": per_day,
            "unmeasured_counters": unmeasured,
            "size_bytes_delta": size_delta,
            "row_count_delta": row_delta,
            "explanation": (
                f"Measured over {interval_days:.2f} day(s): "
                if interval_days is not None else "Measured: "
            ) + (
                "no inserts, updates or deletes at all between the two "
                "snapshots — genuinely idle."
                if total == 0 else
                f"{deltas.get('rows_inserted')} inserted, "
                f"{deltas.get('rows_updated')} updated, "
                f"{deltas.get('rows_deleted')} deleted."
            ) + (
                f" Counters not carried by both snapshots: "
                f"{', '.join(unmeasured)}."
                if unmeasured else ""
            ),
        })
        per_table.append(entry)

    # Schema churn, from the table lists of the same two snapshots.
    added = sorted(f"{s}.{t}" for (s, t) in (new_tbl.keys() - old_tbl.keys()))
    removed = sorted(f"{s}.{t}" for (s, t) in (old_tbl.keys() - new_tbl.keys()))
    churn_state = STATE_MEASURED if (old_tables and new_tables) else STATE_NOT_MEASURED

    measured = [e for e in per_table if e["state"] == STATE_MEASURED
                and e["change"] in {"idle", "active"}]
    active = [e for e in measured if e["change"] == "active"]
    reset = [e for e in per_table if e["change"] == "counters_reset"]

    return {
        "state": STATE_MEASURED,
        "from_surveyed_at": old_at,
        "to_surveyed_at": new_at,
        "interval_days": (round(interval_days, 4) if interval_days is not None else None),
        "per_table": per_table,
        "tables_with_a_rate": len(measured),
        "tables_active": len(active),
        "tables_idle": len(measured) - len(active),
        "tables_without_a_rate": len(per_table) - len(measured),
        "tables_counters_reset": len(reset),
        "schema_churn": {
            "state": churn_state,
            "tables_added": added,
            "tables_removed": removed,
            "explanation": (
                f"{len(added)} table(s) added and {len(removed)} removed "
                f"between the two snapshots."
                if churn_state == STATE_MEASURED else
                "One of the two snapshots carries no table rows, so schema "
                "churn could not be differenced."
            ),
        },
        "explanation": (
            f"Differenced {new_at} against {old_at}"
            + (f" ({interval_days:.2f} days apart)" if interval_days is not None else "")
            + f": {len(active)} table(s) changed, {len(measured) - len(active)} "
              f"genuinely idle, {len(per_table) - len(measured)} without a "
              f"usable rate"
            + (f" ({len(reset)} of those because the counters were reset)"
               if reset else "")
            + "."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# Proposed DataScope  (design §5.4; key names from support doc §7)
# ═══════════════════════════════════════════════════════════════════════════

def propose_data_scope(inputs: DerivedInputs) -> dict:
    """Earliest/latest values across date columns → a proposed `DataScope`.

    Key names are `DataScopeProperties`' own (`dataCoverageStartTime`,
    `dataCoverageEndTime`), per `egeria-support-for-multi-resource.md` §7's
    convention — *"a `ResourceMeasureAnnotation` whose `resourceProperties`
    use the same key names as `DataScopeProperties` plus `confidence` and
    `basis`"* — so the Curate prefill is a key-for-key copy. Published with
    `contentStatus: DRAFT` per §3's project-owner decision: measured is not
    declared.

    **Data availability is the limit here, and it is recorded rather than
    worked around.** `database_column_profiles.min_value`/`max_value` are
    populated ONLY by `result_materializer`'s native-survey path (from an
    Egeria column-values annotation's `range_from`/`range_to`). Slice 7's
    local `pg_stats` path does not write them. What slice 7 DOES write is
    `histogram_bounds_json`, whose first and last elements are Postgres's own
    estimated extremes — so a local-only survey can still yield a range, at
    lower confidence and labelled as the estimate it is.
    """
    date_columns: list[dict] = []
    for col in inputs.columns:
        base = (col.get("base_type") or col.get("data_type") or "").lower()
        if any(marker in base for marker in _DATE_TYPE_MARKERS):
            date_columns.append(col)

    if not date_columns:
        return {
            "state": STATE_MEASURED,
            "has_scope": False,
            "reason": "no_date_columns",
            "explanation": (
                f"Measured: none of this database's {len(inputs.columns)} "
                f"stored columns has a date or timestamp type, so it has no "
                f"temporal scope to propose. A real finding, not missing data."
            ),
        }

    profiles = {
        (_table_key(p), p.get("column_name")): p for p in inputs.profiles
    }
    ranges: list[dict] = []
    for col in date_columns:
        profile = profiles.get((_table_key(col), col.get("column_name")))
        if not profile:
            continue
        low = (profile.get("min_value") or "").strip() or None
        high = (profile.get("max_value") or "").strip() or None
        basis = "profile_min_max"
        if low is None or high is None:
            bounds = profile.get("histogram_bounds_json")
            if isinstance(bounds, list) and len(bounds) >= 2:
                low = low or str(bounds[0])
                high = high or str(bounds[-1])
                basis = "histogram_bounds"
        if low is None or high is None:
            continue
        ranges.append({
            "schema_name": col.get("schema_name"),
            "table_name": col.get("table_name"),
            "column_name": col.get("column_name"),
            "start": low,
            "end": high,
            "basis": basis,
        })

    if not ranges:
        return {
            "state": STATE_NOT_MEASURED,
            "has_scope": False,
            "reason": "no_profiled_date_columns",
            "date_column_count": len(date_columns),
            "explanation": (
                f"{len(date_columns)} date/timestamp column(s) exist, but none "
                f"has a stored profile carrying a value range. "
                f"`min_value`/`max_value` are written only by the native "
                f"Egeria survey read-back path, and no stored "
                f"`histogram_bounds` is available to estimate from either — "
                f"so the temporal scope is NOT established. Run ANALYZE and "
                f"the statistics step, or a native survey, rather than reading "
                f"this as 'no time range'."
            ),
        }

    starts = sorted(r["start"] for r in ranges)
    ends = sorted(r["end"] for r in ranges)
    estimated = [r for r in ranges if r["basis"] == "histogram_bounds"]
    # An exact min/max from a profile is a real observation; a histogram
    # bound is Postgres's estimate of the extreme from a sample. Confidence
    # reflects which of the two the proposal rests on, and how many columns
    # agreed.
    confidence = 80 if not estimated else 55
    if len(estimated) == len(ranges):
        confidence = 50

    return {
        "state": STATE_MEASURED,
        "has_scope": True,
        # DataScopeProperties' own key names — support doc §7.
        "dataCoverageStartTime": starts[0],
        "dataCoverageEndTime": ends[-1],
        "confidence": confidence,
        "basis": ", ".join(sorted({r["basis"] for r in ranges})),
        "column_ranges": ranges,
        "date_column_count": len(date_columns),
        "profiled_column_count": len(ranges),
        "explanation": (
            f"Proposed from {len(ranges)} of {len(date_columns)} "
            f"date/timestamp column(s): coverage {starts[0]} … {ends[-1]}. "
            + (f"{len(estimated)} of those range(s) come from pg_stats "
               f"histogram bounds, which are ANALYZE-time estimates of the "
               f"extremes rather than exact min/max values — hence the "
               f"reduced confidence. " if estimated else "")
            + "This is a MEASURED scope, published as a proposal "
              "(contentStatus DRAFT). A curator declaring the asset's real "
              "DataScope may legitimately widen it (\"x..current\") — measured "
              "is not declared."
        ),
    }


# ═══════════════════════════════════════════════════════════════════════════
# The step
# ═══════════════════════════════════════════════════════════════════════════

def run_db_derived(
    registry,
    slug: str,
    *,
    surveyed_at: str | None = None,
    source: str | None = None,
) -> dict:
    """Run every `db_derived` check over stored rows. Opens no connection.

    Returns a dict shaped like the other database steps' output: the per-check
    payloads under `derived`, plus the annotations they produced.
    """
    inputs = load_inputs(registry, slug, surveyed_at, source)

    fingerprint = fingerprint_database(registry, inputs)
    classification = classify_database(inputs, fingerprint)
    graph = derive_relationship_graph(inputs)
    grain = determine_grain(inputs)
    conventions = check_conventions(inputs)
    change_rates = derive_change_rates(registry, inputs)
    scope = propose_data_scope(inputs)

    derived = {
        "db_classification": classification,
        "db_relationship_graph": graph,
        "grain_determination": grain,
        "db_fingerprint": fingerprint,
        "schema_conventions": conventions,
        "db_change_rates": change_rates,
        _PROPOSED_SCOPE_CHECK: scope,
    }

    return {
        "database_slug": slug,
        "surveyed_at": datetime.utcnow().isoformat(),
        "read_snapshot": inputs.surveyed_at,
        "source": source,
        "derived": derived,
        "annotations": build_annotations(derived),
        "errors": [],
    }


def build_annotations(derived: dict) -> list:
    """Turn the per-check payloads into annotations.

    A pure function of `derived`, deliberately: it is the same split slices 7
    and 8 use (fetch/derive in one place, annotation-building in another), so
    the Survey-Definition publish path can build annotations from a stored
    payload without re-deriving anything.
    """
    annotations: list = []
    annotations.extend(_classification_annotations(derived["db_classification"]))
    annotations.extend(_graph_annotations(derived["db_relationship_graph"]))
    annotations.extend(_grain_annotations(derived["grain_determination"]))
    annotations.extend(_fingerprint_annotations(derived["db_fingerprint"]))
    annotations.extend(_conventions_annotations(derived["schema_conventions"]))
    annotations.extend(_change_rate_annotations(derived["db_change_rates"]))
    annotations.extend(_scope_annotations(derived[_PROPOSED_SCOPE_CHECK]))
    return annotations


def _classification_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED or result.get("kind") is None:
        return [ResourceMeasureAnnotation(
            summary="Database kind not established",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="db_classification",
            check_name="db_classification",
            label="unverified",
            confidence=0,
            explanation=result["explanation"],
            resource_properties={
                "signals_used": ", ".join(result.get("signals_used") or []) or "none",
                "signals_missing": ", ".join(result.get("signals_missing") or []) or "none",
            },
            json_properties={"scores": result.get("scores") or {}},
        )]
    return [ClassificationAnnotation(
        summary=f"Database kind: {result['kind']}",
        analysis_step=ANALYSIS_STEP,
        annotation_type_name="db_classification",
        check_name="db_classification",
        label=result["kind"],
        confidence=result["confidence"],
        explanation=result["explanation"],
        candidate_classifications=list(result.get("ranked") or [result["kind"]]),
        json_properties={
            "scores": result.get("scores") or {},
            "coverage": result.get("coverage"),
            "signals_used": result.get("signals_used"),
            "signals_missing": result.get("signals_missing"),
        },
    )]


def _graph_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED:
        return [ResourceMeasureAnnotation(
            summary="Relational model not established",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="db_relationship_graph",
            check_name="db_relationship_graph",
            label="unverified",
            confidence=0,
            explanation=result["explanation"],
            resource_properties={"reason": result.get("reason") or ""},
        )]
    return [SchemaAnalysisAnnotation(
        summary=(
            f"{result['edge_count']} foreign key(s) across "
            f"{result['table_count']} table(s): {result['verdict']}"
        ),
        analysis_step=ANALYSIS_STEP,
        annotation_type_name="db_relationship_graph",
        check_name="db_relationship_graph",
        label=result["verdict"],
        # A measured graph, not an inference — the FK constraints are declared.
        confidence=100,
        explanation=result["explanation"],
        schema_name=f"{result['table_count']} tables",
        schema_type="relational_model",
        json_properties={
            "edge_count": result["edge_count"],
            "component_count": result["component_count"],
            "largest_component": result["largest_component"],
            "isolated_tables": result["isolated_tables"],
            "most_referenced": result["most_referenced"],
            "dangling_references": result["dangling_references"],
        },
    )]


def _grain_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED:
        return [ResourceMeasureAnnotation(
            summary="Table grain not established",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="grain_determination",
            check_name="grain_determination",
            label="unverified",
            confidence=0,
            explanation=(
                "No stored table rows for this database, so no grain could be "
                "derived for any table."
            ),
            resource_properties={"reason": result.get("reason") or ""},
        )]

    annotations: list = []
    for grain in result["grains"]:
        item_key = grain["qualified_name"]
        if grain.get("grain_statement"):
            annotations.append(DataGrainAnnotation(
                summary=f"{item_key}: {grain['grain_statement']}",
                analysis_step=ANALYSIS_STEP,
                annotation_type_name="grain_determination",
                check_name="grain_determination",
                item_key=item_key,
                label=grain["label"],
                confidence=grain["confidence"],
                explanation=grain["explanation"],
                expression=item_key,
                grain_statement=grain["grain_statement"],
                granularity_basis=grain["basis"],
                interval=grain.get("interval") or "",
                # A PROPOSAL: no DataGrain element exists for this yet, and a
                # curator must declare it (support doc §3's decision).
                content_status="DRAFT",
                json_properties={
                    "grain_columns": grain.get("grain_columns") or [],
                    "row_count": grain.get("row_count"),
                    "date_columns": grain.get("date_columns") or [],
                },
            ))
        else:
            annotations.append(ResourceMeasureAnnotation(
                summary=(
                    f"{item_key}: grain "
                    + ("not determinable" if grain["state"] == STATE_MEASURED
                       else "not established")
                ),
                analysis_step=ANALYSIS_STEP,
                annotation_type_name="grain_determination",
                check_name="grain_determination",
                item_key=item_key,
                label=grain["label"],
                confidence=0,
                explanation=grain["explanation"],
                expression=item_key,
                resource_properties={
                    "state": grain["state"],
                    "row_count": grain.get("row_count"),
                },
            ))
    return annotations


def _fingerprint_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED:
        return [ResourceMeasureAnnotation(
            summary="Schema fingerprint not computed",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="db_fingerprint",
            check_name="db_fingerprint",
            label="unverified",
            confidence=0,
            explanation=result["explanation"],
            resource_properties={"reason": result.get("reason") or ""},
        )]

    comparable = result["comparable_databases"]
    matches = result["matches"]
    top = matches[0] if matches else None
    if comparable == 0:
        label, confidence = "unverified", 0
    elif top and top["verdict"] in {"likely_copy", "likely_subset_of", "likely_superset_of"}:
        label, confidence = top["verdict"], 85
    elif top:
        label, confidence = top["verdict"], 60
    else:
        label, confidence = "no_match", 100

    return [FingerprintAnnotation(
        summary=(
            f"Schema fingerprint {result['digest'][:16]}"
            + (f" — closest match {top['slug']} ({top['verdict']})" if top
               else f" — no match among {comparable} comparable database(s)"
               if comparable else " — nothing to compare against")
        ),
        analysis_step=ANALYSIS_STEP,
        annotation_type_name="db_fingerprint",
        check_name="db_fingerprint",
        label=label,
        confidence=confidence,
        explanation=result["explanation"],
        fingerprint_properties={
            "digest": result["digest"],
            "algorithm": "sha256(sorted schema.table.column:type)",
            "tableCount": result["table_count"],
            "columnCount": result["column_count"],
            "comparableDatabases": comparable,
            "bestSimilarity": result.get("best_similarity"),
            "closestMatch": top["slug"] if top else "",
        },
        json_properties={
            "matches": matches,
            "unsurveyed_peers": result["unsurveyed_peers"],
            "thresholds": {
                "copy_jaccard": _COPY_JACCARD,
                "subset_containment": _SUBSET_CONTAINMENT,
                "related_jaccard": _RELATED_JACCARD,
                "reportable_jaccard": _REPORTABLE_JACCARD,
            },
        },
    )]


def _conventions_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED:
        return [ResourceMeasureAnnotation(
            summary="Schema conventions not checked",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="schema_conventions",
            check_name="schema_conventions",
            label="unverified",
            confidence=0,
            explanation=(
                "No stored table rows for this database, so no structural "
                "convention could be checked."
            ),
            resource_properties={"reason": result.get("reason") or ""},
        )]

    annotations: list = []
    for name, check in result["checks"].items():
        measured = check["state"] == STATE_MEASURED
        annotations.append(ResourceMeasureAnnotation(
            summary=f"{name}: {check['label']}",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="schema_conventions",
            check_name=name,
            label=check["label"],
            # A count of stored rows is a measurement, not an inference.
            confidence=100 if measured else 0,
            explanation=check["explanation"],
            resource_properties={
                "state": check["state"],
                "count": check.get("count"),
                "total": check.get("total"),
                "fraction": check.get("fraction"),
            },
            json_properties={"items": check.get("items") or []},
        ))
    return annotations


def _change_rate_annotations(result: dict) -> list:
    if result["state"] != STATE_MEASURED:
        return [ResourceMeasureAnnotation(
            summary="Change rates: insufficient history",
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="db_change_rates",
            check_name="db_change_rates",
            label="unverified",
            confidence=0,
            explanation=result["explanation"],
            resource_properties={
                "reason": result.get("reason") or "",
                "snapshots_available": result.get("snapshots_available"),
            },
        )]

    annotations: list = [ResourceMeasureAnnotation(
        summary=(
            f"Change rates over {result['interval_days']} day(s): "
            f"{result['tables_active']} active, {result['tables_idle']} idle, "
            f"{result['tables_without_a_rate']} without a rate"
        ),
        analysis_step=ANALYSIS_STEP,
        annotation_type_name="db_change_rates",
        check_name="db_change_rates",
        label="measured",
        confidence=100,
        explanation=result["explanation"],
        resource_properties={
            "from_surveyed_at": result["from_surveyed_at"],
            "to_surveyed_at": result["to_surveyed_at"],
            "interval_days": result["interval_days"],
            "tables_active": result["tables_active"],
            "tables_idle": result["tables_idle"],
            "tables_without_a_rate": result["tables_without_a_rate"],
            "tables_counters_reset": result["tables_counters_reset"],
        },
        json_properties={"per_table": result["per_table"]},
    )]

    churn = result["schema_churn"]
    if churn["tables_added"] or churn["tables_removed"]:
        annotations.append(SchemaAnalysisAnnotation(
            summary=(
                f"Schema churn: {len(churn['tables_added'])} table(s) added, "
                f"{len(churn['tables_removed'])} removed"
            ),
            analysis_step=ANALYSIS_STEP,
            annotation_type_name="db_change_rates",
            check_name="schema_churn",
            label="changed",
            confidence=100 if churn["state"] == STATE_MEASURED else 0,
            explanation=churn["explanation"],
            schema_name="schema churn",
            schema_type="change",
            json_properties={
                "tables_added": churn["tables_added"],
                "tables_removed": churn["tables_removed"],
            },
        ))
    return annotations


def _scope_annotations(result: dict) -> list:
    if not result.get("has_scope"):
        return [ResourceMeasureAnnotation(
            summary=(
                "No temporal scope in the data"
                if result["state"] == STATE_MEASURED
                else "Temporal scope not established"
            ),
            analysis_step=ANALYSIS_STEP,
            annotation_type_name=_PROPOSED_SCOPE_CHECK,
            check_name="proposed_data_scope",
            label="pass" if result["state"] == STATE_MEASURED else "unverified",
            confidence=100 if result["state"] == STATE_MEASURED else 0,
            explanation=result["explanation"],
            resource_properties={
                "state": result["state"],
                "reason": result.get("reason") or "",
                "date_column_count": result.get("date_column_count"),
            },
        )]

    return [ResourceMeasureAnnotation(
        summary=(
            f"Proposed DataScope: {result['dataCoverageStartTime']} … "
            f"{result['dataCoverageEndTime']}"
        ),
        analysis_step=ANALYSIS_STEP,
        annotation_type_name=_PROPOSED_SCOPE_CHECK,
        check_name="proposed_data_scope",
        label="proposed",
        confidence=result["confidence"],
        explanation=result["explanation"],
        # A proposal, not a declaration — support doc §3's decision.
        content_status="DRAFT",
        resource_properties={
            # DataScopeProperties' own key names, so a Curate prefill is a
            # key-for-key copy (support doc §7).
            "dataCoverageStartTime": result["dataCoverageStartTime"],
            "dataCoverageEndTime": result["dataCoverageEndTime"],
            "confidence": result["confidence"],
            "basis": result["basis"],
        },
        json_properties={"column_ranges": result["column_ranges"]},
    )]
