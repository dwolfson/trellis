"""Tests for design §16.3's Scouting and Discovery rows — `subject_signals`,
`coverage_signals`, `grain_determination`'s time-grain extension, and
`preliminary_fit`.

Read `docs/multi-resource-questions-design.md` §16 for the model. What every
test here is really about is one sentence from §16.2, and it is the sentence
this whole file exists to hold the code to:

    `pg_stats.histogram_bounds` … gives min and max **without reading rows**
    (after `ANALYZE`) … **absent means "run ANALYZE", not "no dates"**

Those two states are one `if` apart in the data and opposite in meaning. A
database with no date column genuinely covers no period; a database whose
statistics were never populated covers an unknown period. Collapsing them
produces a confident wrong answer that no other test fails on — so
`TestTheAnalyzeDistinction` asserts they differ in state, in reason, in
confidence, in remedy and in what the annotation says, and
`test_the_two_states_share_no_field_a_reader_would_branch_on` fails if a later
edit merges them by any of those routes.

`preliminary_fit` has the same shape one level up: its `could_not_check`
verdict exists so an unknown input never renders as "does not fit" or as a
pass.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import (
    STATE_MEASURED,
    STATE_NOT_COLLECTED,
    STATE_NOT_MEASURED,
    DatabaseEntity,
    ProjectRegistry,
)
from resource_explorer.surveyors.database.db_derived import (
    COVERAGE_ANALYZE_REMEDY,
    COVERAGE_REASON_NO_DATE_COLUMNS,
    COVERAGE_REASON_MEASURED,
    COVERAGE_REASON_STATS_NOT_POPULATED,
    FIT_COULD_NOT_CHECK,
    FIT_DOES_NOT_FIT,
    FIT_FITS,
    FIT_NO_REQUIREMENT,
    FIT_NOTHING_MEASURED,
    GRAIN_INTERVAL_BASIS_COLUMN_NAME,
    GRAIN_INTERVAL_BASIS_COLUMN_NAME_UNTYPED,
    GRAIN_INTERVAL_BASIS_PARTITION_SUFFIX,
    GRAIN_INTERVAL_BASIS_PK,
    GRAIN_INTERVAL_BASIS_TABLE_NAME,
    SUBJECT_BASIS_BOTH,
    SUBJECT_BASIS_COMMENT,
    SUBJECT_BASIS_NAME,
    SUBJECT_REASON_NO_SUBJECT_NAMES,
    build_annotations,
    compute_preliminary_fit,
    derive_coverage_signals,
    derive_subject_signals,
    determine_grain,
    load_inputs,
    run_db_derived,
)

NOW = "2026-09-21T12:00:00"


@pytest.fixture
def registry(tmp_path):
    r = ProjectRegistry(db_path=str(tmp_path / "test.db"))
    r.register_database(DatabaseEntity(
        slug="coco_ods", display_name="Coco ODS", db_type="postgresql",
        host="localhost", port=5442, database_name="coco_ods",
    ))
    return r


# ── row builders (same shapes as test_db_derived_step.py's) ─────────────────

def _table(name, *, rows=1000, cols=8, desc="", ttype="BASE TABLE",
           schema="public"):
    return {
        "schema_name": schema, "table_name": name, "table_type": ttype,
        "row_count": rows, "column_count": cols, "size_bytes": 8192,
        "description": desc, "state": STATE_MEASURED,
    }


def _column(table, name, *, pk=False, dtype="integer", desc="", schema="public"):
    return {
        "schema_name": schema, "table_name": table, "column_name": name,
        "data_type": dtype, "base_type": dtype, "description": desc,
        "is_primary_key": 1 if pk else 0, "foreign_key_json": None,
        "state": STATE_MEASURED,
    }


def _profile(table, column, *, min_value="", max_value="", histogram=None,
             distinct=None, schema="public"):
    return {
        "schema_name": schema, "table_name": table, "column_name": column,
        "distinct_count": distinct, "min_value": min_value,
        "max_value": max_value, "histogram_bounds_json": histogram,
        "state": STATE_MEASURED,
    }


def _store(registry, slug, surveyed_at, *, tables=None, columns=None,
           profiles=None, source="local"):
    registry.record_database_survey(
        slug=slug, schema_count=1, table_count=len(tables or []),
        column_count=len(columns or []), survey_data={},
        source=source, surveyed_at=surveyed_at,
    )
    for table, rows in (("database_tables", tables),
                        ("database_columns", columns),
                        ("database_column_profiles", profiles)):
        if rows is not None:
            registry.write_detail_rows(table, slug, surveyed_at,
                                       source=source, rows=rows)


def _sales_schema(registry, *, profiles=None, comments=False):
    """A dated sales schema — the shape every §16 question is about."""
    tables = [
        _table("sales_order",
               desc="Customer sales orders, one per confirmed purchase."
                    if comments else ""),
        _table("sales_order_line"),
    ]
    columns = [
        _column("sales_order", "sales_order_id", pk=True),
        _column("sales_order", "ordered_at", dtype="timestamp without time zone",
                desc="When the customer placed the order." if comments else ""),
        _column("sales_order", "customer_id"),
        _column("sales_order_line", "sales_order_line_id", pk=True),
        _column("sales_order_line", "product_sku", dtype="text"),
    ]
    _store(registry, "coco_ods", NOW, tables=tables, columns=columns,
           profiles=profiles)


# ═══════════════════════════════════════════════════════════════════════════
# subject_signals  (§16.3 Scouting row 1)
# ═══════════════════════════════════════════════════════════════════════════

class TestSubjectSignals:
    def test_a_name_derived_term_is_lower_confidence_than_a_comment_derived_one(
        self, registry,
    ):
        """§16.2's "a name is a claim", as an ordering the code can be held to.

        `product` appears only in a column name; `purchase` only in a comment.
        The comment must outrank the name, and both must sit below a term that
        appears in both.
        """
        tables = [_table("sales_order",
                         desc="Customer purchase records for the sales team.")]
        columns = [
            _column("sales_order", "sales_order_id", pk=True),
            _column("sales_order", "product_sku", dtype="text"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)

        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        assert result["state"] == STATE_MEASURED
        by_term = {t["term"]: t for t in result["terms"]}

        assert by_term["product"]["basis"] == SUBJECT_BASIS_NAME
        assert by_term["purchase"]["basis"] == SUBJECT_BASIS_COMMENT
        # `sales` is in the table name AND in the table's comment.
        assert by_term["sales"]["basis"] == SUBJECT_BASIS_BOTH

        assert (by_term["product"]["confidence"]
                < by_term["purchase"]["confidence"]
                < by_term["sales"]["confidence"])
        # And none of them claims certainty: §16.2 grades this low–medium.
        assert by_term["sales"]["confidence"] <= 60

    def test_terms_are_ranked_strongest_first(self, registry):
        _sales_schema(registry, comments=True)
        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        confidences = [t["confidence"] for t in result["terms"]]
        assert confidences == sorted(confidences, reverse=True)

    def test_structural_columns_contribute_no_subject_term(self, registry):
        """`id`, `created_at`, `value` are plumbing, not subjects."""
        tables = [_table("sales_order")]
        columns = [
            _column("sales_order", "id", pk=True),
            _column("sales_order", "created_at", dtype="timestamp"),
            _column("sales_order", "updated_at", dtype="timestamp"),
            _column("sales_order", "value", dtype="numeric"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        terms = {t["term"] for t in
                 derive_subject_signals(load_inputs(registry, "coco_ods"))["terms"]}
        # Only the table name's own two tokens survive; `id`, `created`,
        # `updated`, `at` and `value` are all plumbing.
        assert terms == {"sales", "order"}, terms

    def test_wholly_structural_names_are_a_measured_finding_not_an_absence(
        self, registry,
    ):
        """The third state: measured, and the names really say nothing.

        Must NOT read like "nothing was surveyed" — the remedy is Enrichment,
        not a survey step, and the two point a reader in opposite directions.
        """
        tables = [_table("t1")]
        columns = [_column("t1", "id", pk=True), _column("t1", "value")]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)

        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        assert result["state"] == STATE_MEASURED
        assert result["reason"] == SUBJECT_REASON_NO_SUBJECT_NAMES
        assert result["terms"] == []
        assert "Enrichment" in result["explanation"]

    def test_nothing_surveyed_is_not_measured(self, registry):
        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        assert result["state"] == STATE_NOT_MEASURED
        assert result["reason"] == "no_schema_rows"

    def test_the_two_empty_states_do_not_render_alike(self, registry, tmp_path):
        """A measured "names say nothing" and an unsurveyed database are both
        term-less, and a reader must be able to tell them apart."""
        tables = [_table("t1")]
        columns = [_column("t1", "id", pk=True)]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        measured = derive_subject_signals(load_inputs(registry, "coco_ods"))

        other = ProjectRegistry(db_path=str(tmp_path / "empty.db"))
        other.register_database(DatabaseEntity(
            slug="empty", display_name="Empty", db_type="postgresql",
            host="h", port=1, database_name="empty"))
        unsurveyed = derive_subject_signals(load_inputs(other, "empty"))

        assert measured["state"] != unsurveyed["state"]
        assert measured["reason"] != unsurveyed["reason"]
        assert measured["explanation"] != unsurveyed["explanation"]

    def test_no_comment_anywhere_reads_as_not_captured(self, registry):
        """`check_conventions`' established distinction, reused here: a
        database where not one table or column carries a description is more
        likely one whose comments were never read than one that documents
        nothing, so no term may claim comment-level confidence."""
        _sales_schema(registry, comments=False)
        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        assert result["comments_captured"] is False
        assert all(t["basis"] == SUBJECT_BASIS_NAME for t in result["terms"])
        assert "comments never having been captured" in result["explanation"]

    def test_a_term_is_never_claimed_as_a_glossary_match(self, registry):
        """This step opens no connection, so it cannot have resolved anything
        against Egeria's glossary — and must say so rather than letting a
        candidate term read as a matched one."""
        _sales_schema(registry, comments=True)
        result = derive_subject_signals(load_inputs(registry, "coco_ods"))
        assert result["glossary_matched"] is False
        assert "glossary" in result["explanation"]


# ═══════════════════════════════════════════════════════════════════════════
# coverage_signals  (§16.3 Scouting row 3) — the ANALYZE distinction
# ═══════════════════════════════════════════════════════════════════════════

class TestTheAnalyzeDistinction:
    """§16.2: *absent means "run ANALYZE", not "no dates"*.

    The single most collapsible pair in this whole area.
    """

    def _no_dates(self, registry):
        tables = [_table("product")]
        columns = [
            _column("product", "product_id", pk=True),
            _column("product", "sku", dtype="text"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        return derive_coverage_signals(load_inputs(registry, "coco_ods"))["temporal"]

    def _dates_without_stats(self, registry):
        _sales_schema(registry, profiles=None)
        return derive_coverage_signals(load_inputs(registry, "coco_ods"))["temporal"]

    def test_no_date_column_is_a_measured_negative(self, registry):
        temporal = self._no_dates(registry)
        assert temporal["state"] == STATE_MEASURED
        assert temporal["reason"] == COVERAGE_REASON_NO_DATE_COLUMNS
        # No remedy, because there is nothing to fix: this IS the answer.
        assert "remedy" not in temporal

    def test_date_columns_without_statistics_are_not_measured(self, registry):
        temporal = self._dates_without_stats(registry)
        assert temporal["state"] == STATE_NOT_MEASURED
        assert temporal["reason"] == COVERAGE_REASON_STATS_NOT_POPULATED
        assert temporal["remedy"] == COVERAGE_ANALYZE_REMEDY
        assert "ANALYZE" in temporal["explanation"]
        assert temporal["date_column_count"] == 1

    def test_the_two_states_share_no_field_a_reader_would_branch_on(self, registry):
        """The regression guard. Every route by which a consumer could tell
        these apart must actually differ — merging them would have to break at
        least one of these, whichever route a future edit takes.
        """
        no_dates = self._no_dates(registry)
        no_stats = self._dates_without_stats(registry)

        assert no_dates["state"] != no_stats["state"]
        assert no_dates["reason"] != no_stats["reason"]
        assert no_dates["label"] != no_stats["label"]
        assert no_dates["explanation"] != no_stats["explanation"]
        # "run ANALYZE" must appear in exactly one of them. A measured
        # negative that told a user to run ANALYZE would send them off to fix
        # a database that is answering correctly.
        assert "ANALYZE" in no_stats["explanation"]
        assert "ANALYZE" not in no_dates["explanation"]

    def test_the_two_states_do_not_render_alike_in_the_annotation(self, registry):
        """Same distinction at the surface a person actually reads — the
        `explanation`/`summary` pair on the published annotation, not just the
        dict a test can see."""
        self._no_dates(registry)
        no_dates = self._temporal_annotation(registry)
        assert no_dates.summary == "Holds no dated data"
        # A real finding, so it carries real confidence.
        assert no_dates.confidence > 0

        registry2 = registry
        # Re-store with a date column and no statistics, same slug/snapshot.
        _sales_schema(registry2, profiles=None)
        no_stats = self._temporal_annotation(registry2)
        assert "run ANALYZE" in no_stats.summary
        # Not established, so confidence is zero — never a confident negative.
        assert no_stats.confidence == 0
        assert no_stats.summary != no_dates.summary

    @staticmethod
    def _temporal_annotation(registry):
        derived = run_db_derived(registry, "coco_ods")
        temporal = [
            a for a in derived["annotations"]
            if a.check_name == "coverage_signals_temporal"
        ]
        assert len(temporal) == 1, temporal
        return temporal[0]

    def test_histogram_bounds_alone_yield_a_range_at_reduced_confidence(
        self, registry,
    ):
        """The §16.2 pay-off: a range with no row read, labelled as the
        estimate it is."""
        _sales_schema(registry, profiles=[
            _profile("sales_order", "ordered_at",
                     histogram=["2025-01-04", "2025-06-01", "2025-12-30"]),
        ])
        temporal = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["temporal"]
        assert temporal["state"] == STATE_MEASURED
        assert temporal["reason"] == COVERAGE_REASON_MEASURED
        assert temporal["dataCoverageStartTime"] == "2025-01-04"
        assert temporal["dataCoverageEndTime"] == "2025-12-30"
        assert temporal["basis"] == "histogram_bounds"
        assert temporal["confidence"] < 80
        assert "estimate" in temporal["explanation"]

    def test_an_exact_min_max_outranks_a_histogram_estimate(self, registry):
        _sales_schema(registry, profiles=[
            _profile("sales_order", "ordered_at",
                     min_value="2025-01-01", max_value="2025-12-31"),
        ])
        temporal = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["temporal"]
        assert temporal["basis"] == "profile_min_max"
        assert temporal["confidence"] == 80

    def test_a_date_column_with_no_bounds_is_excluded_and_said_to_be(
        self, registry,
    ):
        """One profiled column and one unprofiled: the window comes from the
        one, and the other's range is reported as unknown rather than folded
        in as if it agreed."""
        tables = [_table("sales_order"), _table("shipment")]
        columns = [
            _column("sales_order", "ordered_at", dtype="date"),
            _column("shipment", "shipped_at", dtype="date"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns,
               profiles=[_profile("sales_order", "ordered_at",
                                  min_value="2025-01-01", max_value="2025-06-30")])
        temporal = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["temporal"]
        assert temporal["date_column_count"] == 2
        assert temporal["profiled_column_count"] == 1
        assert "unknown rather than empty" in temporal["explanation"]


class TestCoverageSpatialAndPartitions:
    def test_place_columns_are_candidates_and_never_an_extent(self, registry):
        tables = [_table("customer")]
        columns = [
            _column("customer", "customer_id", pk=True),
            _column("customer", "country_code", dtype="text"),
            _column("customer", "postcode", dtype="text"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        spatial = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["spatial"]
        assert spatial["verdict"] == "candidates_only"
        assert {c["column_name"] for c in spatial["place_columns"]} == {
            "country_code", "postcode"}
        # The whole point: names, not values.
        assert spatial["values_read"] is False
        assert spatial["next_analysis"] == "coverage_profile"

    def test_an_ambiguous_place_name_is_kept_apart_from_a_clear_one(self, registry):
        """`state` is a status at least as often as it is a place, and a
        column called `order_state` must not be counted as geography."""
        tables = [_table("orders")]
        columns = [
            _column("orders", "order_state", dtype="text"),
            _column("orders", "country", dtype="text"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        spatial = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["spatial"]
        assert [c["column_name"] for c in spatial["place_columns"]] == ["country"]
        assert [c["column_name"] for c in spatial["ambiguous_place_columns"]] == [
            "order_state"]

    def test_a_substring_is_not_a_place_match(self, registry):
        """`statement_id` contains `state`; it is not a place."""
        tables = [_table("billing")]
        columns = [_column("billing", "statement_id", pk=True)]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        spatial = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["spatial"]
        assert spatial["verdict"] == "no_place_columns"

    def test_no_place_column_is_not_proof_of_no_geography(self, registry):
        _sales_schema(registry)
        spatial = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["spatial"]
        assert spatial["verdict"] == "no_place_columns"
        assert "not proof" in spatial["explanation"]

    def test_partition_bounds_report_a_collection_gap_not_an_absence(self, registry):
        """§16.2 names partition bounds as free and exact; nothing in RE
        collects them. That must read as "nothing collects it", never as "this
        database is not partitioned"."""
        _sales_schema(registry)
        partitions = derive_coverage_signals(
            load_inputs(registry, "coco_ods"))["partitions"]
        assert partitions["state"] == STATE_NOT_COLLECTED
        assert partitions["reason"] == "partition_metadata_not_stored"
        assert partitions["remedy"]
        assert "NOT that this database is unpartitioned" in partitions["explanation"]


# ═══════════════════════════════════════════════════════════════════════════
# grain_determination's time-grain extension  (§16.3's grain row)
# ═══════════════════════════════════════════════════════════════════════════

class TestTimeGrainFromNaming:
    def _grain(self, registry, tables, columns):
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns)
        return {g["table_name"]: g
                for g in determine_grain(load_inputs(registry, "coco_ods"))["grains"]}

    def test_a_date_in_the_primary_key_is_the_strongest_basis(self, registry):
        """The half that already existed, now naming its basis. Asserted
        because the extension must not weaken it: the schema's own key
        outranks every naming signal, including a table name that disagrees.
        """
        grains = self._grain(
            registry,
            [_table("balance_monthly")],
            [_column("balance_monthly", "account_id", pk=True),
             _column("balance_monthly", "balance_date", pk=True, dtype="date")],
        )
        g = grains["balance_monthly"]
        assert g["interval"] == "per-date"
        assert g["interval_basis"] == GRAIN_INTERVAL_BASIS_PK
        # The disagreeing table-name signal is recorded, not discarded.
        assert g["interval_signals"][GRAIN_INTERVAL_BASIS_TABLE_NAME] == "monthly"
        assert "disagree" in g["interval_explanation"]

    def test_a_period_word_in_the_table_name_gives_a_time_grain(self, registry):
        grains = self._grain(
            registry,
            [_table("daily_sales"), _table("orders_hourly")],
            [_column("daily_sales", "row_id", pk=True),
             _column("orders_hourly", "row_id", pk=True)],
        )
        assert grains["daily_sales"]["interval"] == "daily"
        assert grains["daily_sales"]["interval_basis"] == \
            GRAIN_INTERVAL_BASIS_TABLE_NAME
        assert grains["orders_hourly"]["interval"] == "hourly"

    def test_a_date_shaped_table_suffix_reads_as_a_partition(self, registry):
        grains = self._grain(
            registry,
            [_table("events_202503"), _table("events_2025")],
            [_column("events_202503", "row_id", pk=True),
             _column("events_2025", "row_id", pk=True)],
        )
        assert grains["events_202503"]["interval"] == "monthly"
        assert grains["events_202503"]["interval_basis"] == \
            GRAIN_INTERVAL_BASIS_PARTITION_SUFFIX
        assert grains["events_2025"]["interval"] == "annual"

    def test_a_period_word_in_a_typed_date_column_is_weaker_than_the_table_name(
        self, registry,
    ):
        grains = self._grain(
            registry,
            [_table("shipment")],
            [_column("shipment", "shipment_id", pk=True),
             _column("shipment", "ship_month", dtype="date")],
        )
        g = grains["shipment"]
        assert g["interval"] == "monthly"
        assert g["interval_basis"] == GRAIN_INTERVAL_BASIS_COLUMN_NAME
        assert (g["interval_confidence"]
                < TestTimeGrainFromNaming._table_name_confidence(grains))

    @staticmethod
    def _table_name_confidence(_grains):
        from resource_explorer.surveyors.database.db_derived import (
            _INTERVAL_CONFIDENCE,
        )
        return _INTERVAL_CONFIDENCE[GRAIN_INTERVAL_BASIS_TABLE_NAME]

    def test_a_date_named_column_of_non_temporal_type_still_counts_weakly(
        self, registry,
    ):
        """The warehouse case: `day integer`. A type-only test reads this
        table as having no date column at all, which is why the name-derived
        list exists — at the lowest confidence of the five bases.
        """
        grains = self._grain(
            registry,
            [_table("fact_visits")],
            [_column("fact_visits", "visit_id", pk=True),
             _column("fact_visits", "day", dtype="integer")],
        )
        g = grains["fact_visits"]
        assert g["named_date_columns"] == ["day"]
        assert g["date_columns"] == []           # correctly typed: none
        assert g["interval"] == "daily"
        assert g["interval_basis"] == GRAIN_INTERVAL_BASIS_COLUMN_NAME_UNTYPED
        assert g["interval_confidence"] == 25

    def test_no_naming_signal_is_an_absence_not_an_aperiodic_finding(self, registry):
        grains = self._grain(
            registry,
            [_table("product")],
            [_column("product", "product_id", pk=True),
             _column("product", "sku", dtype="text")],
        )
        g = grains["product"]
        assert g["interval"] == ""
        assert g["interval_basis"] == ""
        assert g["interval_confidence"] == 0
        assert "NOT a finding that the data is not periodic" in \
            g["interval_explanation"]

    def test_the_rollup_counts_tables_with_a_derivable_interval(self, registry):
        _store(registry, "coco_ods", NOW,
               tables=[_table("daily_sales"), _table("product")],
               columns=[_column("daily_sales", "row_id", pk=True),
                        _column("product", "product_id", pk=True)])
        result = determine_grain(load_inputs(registry, "coco_ods"))
        assert result["timed_count"] == 1
        assert result["intervals"] == ["daily"]
        assert result["interval_bases"] == {GRAIN_INTERVAL_BASIS_TABLE_NAME: 1}

    def test_the_entity_grain_from_keys_half_is_unchanged(self, registry):
        """§16.2's "entity grain from keys" row was already built. Pinned here
        so the extension is visibly additive: the PK still IS the grain, with
        its own confidence, whether or not any time signal fires."""
        grains = self._grain(
            registry,
            [_table("product")],
            [_column("product", "product_id", pk=True),
             _column("product", "sku", dtype="text")],
        )
        g = grains["product"]
        assert g["grain_statement"] == "one row per product_id"
        assert g["basis"] == "primary_key"
        assert g["confidence"] == 90


# ═══════════════════════════════════════════════════════════════════════════
# preliminary_fit  (§16.3's Discovery gate, §16.5)
# ═══════════════════════════════════════════════════════════════════════════

def _signals(registry, **kw):
    """(subject, coverage, grain) for the stored snapshot."""
    inputs = load_inputs(registry, "coco_ods")
    return (derive_subject_signals(inputs), derive_coverage_signals(inputs),
            determine_grain(inputs))


class TestPreliminaryFit:
    def _fitting_database(self, registry):
        """Dated sales data at daily grain, with statistics populated."""
        tables = [_table("daily_sales")]
        columns = [
            _column("daily_sales", "sale_id", pk=True),
            _column("daily_sales", "sold_on", dtype="date"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns,
               profiles=[_profile("daily_sales", "sold_on",
                                  min_value="2025-01-01", max_value="2025-12-31")])

    def test_it_fits_when_every_checkable_criterion_is_satisfied(self, registry):
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry), lens={
            "subjectTerms": ["sales"],
            "interval": "monthly",
            "dataCoverageStartTime": "2025-03-01",
            "dataCoverageEndTime": "2025-09-30",
        })
        assert result["verdict"] == FIT_FITS
        assert result["label"] == "pass"
        assert set(result["passed_inputs"]) == {"subject", "coverage", "grain"}
        assert result["unchecked_inputs"] == []
        # Finer serves coarser: daily data answers a monthly requirement.
        assert result["inputs"]["grain"]["held_intervals"] == ["daily"]

    def test_a_disjoint_window_does_not_fit(self, registry):
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry), lens={
            "dataCoverageStartTime": "2019-01-01",
            "dataCoverageEndTime": "2019-12-31",
        })
        assert result["verdict"] == FIT_DOES_NOT_FIT
        assert result["failed_inputs"] == ["coverage"]
        assert result["label"] == "gap"

    def test_a_coarser_held_grain_cannot_serve_a_finer_requirement(self, registry):
        _store(registry, "coco_ods", NOW,
               tables=[_table("monthly_sales")],
               columns=[_column("monthly_sales", "row_id", pk=True)])
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"interval": "daily"})
        assert result["verdict"] == FIT_DOES_NOT_FIT
        assert result["inputs"]["grain"]["held_intervals"] == ["monthly"]

    def test_an_unpopulated_statistic_makes_the_verdict_could_not_check(
        self, registry,
    ):
        """THE case this verdict exists for. The date column is there and its
        statistics are not, so whether the lens's window is covered is
        unknown — and unknown must render as neither a fit nor a miss."""
        _sales_schema(registry, profiles=None)
        result = compute_preliminary_fit(*_signals(registry), lens={
            "dataCoverageStartTime": "2025-01-01",
            "dataCoverageEndTime": "2025-12-31",
        })
        assert result["verdict"] == FIT_COULD_NOT_CHECK
        assert result["unchecked_inputs"] == ["coverage"]
        assert result["failed_inputs"] == []
        assert result["label"] == "unverified"
        assert result["confidence"] == 0
        coverage = result["inputs"]["coverage"]
        assert coverage["reason"] == COVERAGE_REASON_STATS_NOT_POPULATED
        # The remedy travels all the way up to the verdict, so the person
        # reading the gate is told what would answer it.
        assert "ANALYZE" in coverage["remedy"]
        assert "ANALYZE" in result["explanation"]

    def test_could_not_check_is_distinct_from_does_not_fit(self, registry):
        """Two databases, one lens, and the difference between them is only
        whether ANALYZE ran. The verdicts must differ."""
        _sales_schema(registry, profiles=None)
        lens = {"dataCoverageStartTime": "2019-01-01",
                "dataCoverageEndTime": "2019-06-30"}
        unknown = compute_preliminary_fit(*_signals(registry), lens=lens)

        _sales_schema(registry, profiles=[
            _profile("sales_order", "ordered_at",
                     min_value="2025-01-01", max_value="2025-12-31")])
        measured = compute_preliminary_fit(*_signals(registry), lens=lens)

        assert unknown["verdict"] == FIT_COULD_NOT_CHECK
        assert measured["verdict"] == FIT_DOES_NOT_FIT
        assert unknown["label"] != measured["label"]
        assert unknown["explanation"] != measured["explanation"]

    def test_no_date_column_at_all_is_a_real_miss_not_a_gap(self, registry):
        """The mirror of the test above: a MEASURED absence of dates is enough
        to exclude a resource from a lens with a window, at real confidence."""
        _store(registry, "coco_ods", NOW,
               tables=[_table("product")],
               columns=[_column("product", "product_id", pk=True)])
        result = compute_preliminary_fit(*_signals(registry), lens={
            "dataCoverageStartTime": "2025-01-01",
            "dataCoverageEndTime": "2025-12-31",
        })
        assert result["verdict"] == FIT_DOES_NOT_FIT
        assert result["inputs"]["coverage"]["reason"] == \
            COVERAGE_REASON_NO_DATE_COLUMNS
        assert result["inputs"]["coverage"]["confidence"] > 50

    def test_a_definite_miss_outranks_an_unchecked_input_and_says_so(
        self, registry,
    ):
        """A lens that this database definitely fails on grain and cannot be
        checked on coverage: the verdict is the miss, and the gap is named as
        a caveat rather than swallowed."""
        _store(registry, "coco_ods", NOW,
               tables=[_table("monthly_sales")],
               columns=[_column("monthly_sales", "row_id", pk=True),
                        _column("monthly_sales", "sold_on", dtype="date")])
        result = compute_preliminary_fit(*_signals(registry), lens={
            "interval": "daily",
            "dataCoverageStartTime": "2025-01-01",
            "dataCoverageEndTime": "2025-12-31",
        })
        assert result["verdict"] == FIT_DOES_NOT_FIT
        assert result["unchecked_inputs"] == ["coverage"]
        assert "could not be checked" in result["explanation"]

    def test_no_lens_renders_no_requirement_declared_with_what_is_achievable(
        self, registry,
    ):
        """§16.5 point 2's degraded mode, and it must never be a pass."""
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry), lens=None)
        assert result["verdict"] == FIT_NO_REQUIREMENT
        assert result["lens_declared"] is False
        assert result["label"] == "unverified"
        assert result["confidence"] == 0
        assert result["inputs"] == {}
        assert "NOT a pass" in result["explanation"]
        # The descriptive half stands alone (§16.5 point 1).
        achievable = result["achievable"]
        assert "sales" in achievable["subject_terms"]
        assert achievable["coverage_window"] == ["2025-01-01", "2025-12-31"]
        assert achievable["intervals"] == ["daily"]

    def test_a_never_surveyed_database_is_not_measured_not_no_requirement(
        self, registry,
    ):
        """"No requirement declared" is a statement about the LENS. A database
        nobody has surveyed needs a statement about the RESOURCE, or its card
        renders an answer about something nobody has looked at.
        """
        result = compute_preliminary_fit(*_signals(registry), lens=None)
        assert result["state"] == STATE_NOT_MEASURED
        assert result["reason"] == "no_estimates_established"
        # Never a fit and never a miss, whatever a consumer reads. Its own
        # verdict, not `could_not_check` — a never-surveyed resource and a
        # lens whose named inputs weren't measured are different absences
        # (REPLY-COPY-REVIEW-CREDENTIAL-AND-FIT-LANGUAGE.md §4).
        assert result["verdict"] == FIT_NOTHING_MEASURED
        assert "has not been surveyed" in result["explanation"]

    def test_the_unsurveyed_state_hides_the_card_rather_than_answering(
        self, registry,
    ):
        """`_db_derived_field_reader` normalises `STATE_NOT_MEASURED` to `{}`,
        which is what keeps a never-surveyed database's dashboard empty. Pinned
        here because the coupling is invisible from either side alone."""
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )

        reader, _ = DATABASE_ANALYSIS_RESULTS_MAP["preliminary_fit"]
        assert reader(registry, "coco_ods") == {}

    def test_a_surveyed_database_with_no_lens_still_shows_its_card(self, registry):
        """The other half of the pair: once anything IS established, "no
        requirement declared" is a real answer and must reach the screen."""
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )

        self._fitting_database(registry)
        reader, _ = DATABASE_ANALYSIS_RESULTS_MAP["preliminary_fit"]
        payload = reader(registry, "coco_ods")
        assert payload["verdict"] == FIT_NO_REQUIREMENT

    def test_an_empty_lens_is_the_same_as_no_lens(self, registry):
        self._fitting_database(registry)
        assert compute_preliminary_fit(*_signals(registry), lens={})["verdict"] \
            == FIT_NO_REQUIREMENT

    def test_a_lens_of_only_deferred_criteria_is_not_a_pass(self, registry):
        """A lens asking only for regions: nothing at this tier can compare
        it, so the answer is "no requirement declared at this tier" and the
        criterion is reported with the analysis that would answer it."""
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"regions": ["EMEA"]})
        assert result["verdict"] == FIT_NO_REQUIREMENT
        assert [d["criterion"] for d in result["deferred_criteria"]] == ["regions"]
        assert "coverage_profile" in result["deferred_criteria"][0]["answered_by"]
        assert "Not a pass" in result["explanation"]

    def test_a_subject_miss_is_a_weak_disqualifier(self, registry):
        """§16.2 grades name-derived subject low–medium, so a non-overlap must
        carry low confidence rather than reading as a firm exclusion."""
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"subjectTerms": ["radiology"]})
        assert result["verdict"] == FIT_DOES_NOT_FIT
        assert result["inputs"]["subject"]["confidence"] <= 25
        assert "weak disqualifier" in result["inputs"]["subject"]["explanation"]

    def test_names_that_say_nothing_cannot_rule_a_subject_out(self, registry):
        """A database whose names are wholly structural cannot confirm OR deny
        a subject — `could_not_check`, not `does_not_fit`."""
        _store(registry, "coco_ods", NOW, tables=[_table("t1")],
               columns=[_column("t1", "id", pk=True)])
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"subjectTerms": ["sales"]})
        assert result["inputs"]["subject"]["verdict"] == FIT_COULD_NOT_CHECK
        assert result["verdict"] == FIT_COULD_NOT_CHECK

    def test_an_unknown_sought_interval_is_not_guessed_at(self, registry):
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"interval": "fortnightly"})
        assert result["inputs"]["grain"]["verdict"] == FIT_COULD_NOT_CHECK
        assert result["inputs"]["grain"]["reason"] == "unknown_sought_interval"

    def test_no_derivable_interval_is_unknown_not_a_miss(self, registry):
        _store(registry, "coco_ods", NOW, tables=[_table("product")],
               columns=[_column("product", "product_id", pk=True)])
        result = compute_preliminary_fit(*_signals(registry),
                                         lens={"interval": "daily"})
        assert result["inputs"]["grain"]["verdict"] == FIT_COULD_NOT_CHECK
        assert result["inputs"]["grain"]["reason"] == "no_interval_derived"

    def test_the_lens_version_is_recorded_and_empty_when_ad_hoc(self, registry):
        """§16.5 point 4: a verdict is only meaningful against the lens version
        it used. An ad-hoc lens has none, and empty is the honest answer rather
        than a fabricated version number."""
        self._fitting_database(registry)
        ad_hoc = compute_preliminary_fit(*_signals(registry),
                                         lens={"subjectTerms": ["sales"]})
        assert ad_hoc["lens_source"] == "ad_hoc"
        assert ad_hoc["lens_version"] == ""

        versioned = compute_preliminary_fit(*_signals(registry), lens={
            "subjectTerms": ["sales"], "lens_version": "3",
            "lens_source": "investigation:emea-study",
        })
        assert versioned["lens_version"] == "3"
        assert versioned["lens_source"] == "investigation:emea-study"

    def test_a_lens_field_this_tier_cannot_estimate_is_carried_not_dropped(
        self, registry,
    ):
        self._fitting_database(registry)
        result = compute_preliminary_fit(*_signals(registry), lens={
            "subjectTerms": ["sales"], "minLongitude": -10.0,
        })
        assert result["unused_criteria"] == ["minLongitude"]
        assert "minLongitude" in result["explanation"]


# ═══════════════════════════════════════════════════════════════════════════
# The step: still zero-fetch, still one envelope per analysis
# ═══════════════════════════════════════════════════════════════════════════

class TestStepIntegration:
    def test_the_three_new_analyses_are_produced_by_the_step(self, registry):
        _sales_schema(registry, comments=True)
        derived = run_db_derived(registry, "coco_ods")["derived"]
        for key in ("subject_signals", "coverage_signals", "preliminary_fit"):
            assert key in derived, key

    def test_no_connection_is_opened(self, registry, monkeypatch):
        import resource_explorer.surveyors.database.connection as conn_mod

        def _explode(*args, **kwargs):
            raise AssertionError(
                "the §16 signals opened a database connection — they are "
                "zero-fetch and must read stored rows only"
            )

        monkeypatch.setattr(conn_mod, "database_connection", _explode)
        _sales_schema(registry, comments=True)
        assert run_db_derived(registry, "coco_ods")["annotations"]

    def test_the_step_defaults_to_no_lens(self, registry):
        """Nothing in RE stores a lens yet, so the default path must render
        "no requirement declared" rather than a pass — the exact reason §16.6
        says `preliminary_fit` works before the `DataLens` exists."""
        _sales_schema(registry, comments=True)
        fit = run_db_derived(registry, "coco_ods")["derived"]["preliminary_fit"]
        assert fit["verdict"] == FIT_NO_REQUIREMENT

    def test_a_lens_passed_to_the_step_reaches_the_verdict(self, registry):
        _sales_schema(registry, comments=True, profiles=[
            _profile("sales_order", "ordered_at",
                     min_value="2025-01-01", max_value="2025-12-31")])
        fit = run_db_derived(registry, "coco_ods", lens={
            "subjectTerms": ["sales"],
        })["derived"]["preliminary_fit"]
        assert fit["verdict"] == FIT_FITS
        assert fit["lens_declared"] is True

    def test_every_new_annotation_carries_a_check_name_and_explanation(
        self, registry,
    ):
        _sales_schema(registry, comments=True)
        annotations = run_db_derived(registry, "coco_ods")["annotations"]
        new = [a for a in annotations
               if (a.annotation_type_name or "") in
               {"subject_signals", "coverage_signals", "preliminary_fit"}]
        # subject + 3 coverage blocks + fit
        assert len(new) == 5, [a.check_name for a in new]
        for ann in new:
            assert ann.analysis_step == "db_derived"
            assert ann.check_name, ann.summary
            assert ann.explanation, ann.summary

    def test_the_new_annotations_have_unique_check_names(self, registry):
        """The three coverage blocks share one annotation_type_name and must
        not share a check_name, or one would overwrite another on publish."""
        _sales_schema(registry, comments=True)
        derived = run_db_derived(registry, "coco_ods")
        names = [a.check_name for a in derived["annotations"]
                 if (a.annotation_type_name or "") == "coverage_signals"]
        assert sorted(names) == [
            "coverage_signals_partitions", "coverage_signals_spatial",
            "coverage_signals_temporal",
        ]

    def test_all_three_are_in_the_analysis_catalog_for_databases(self):
        from resource_explorer.surveyors import analysis_catalog_reader as acr

        ids = {a["id"] for a in acr.get_analyses("database",
                                                 include_egeria_live=False)}
        assert {"subject_signals", "coverage_signals", "preliminary_fit"} <= ids

    def test_all_three_have_a_results_reader(self):
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_ANALYSIS_RESULTS_MAP,
        )

        for analysis_id in ("subject_signals", "coverage_signals",
                            "preliminary_fit"):
            assert analysis_id in DATABASE_ANALYSIS_RESULTS_MAP, analysis_id

    def test_db_derived_still_declares_no_capability_requirement(self):
        """These three add no fetch, so the step's `requires_capability` must
        stay UNDECLARED. `catalog` — the weakest tier — still implies a live
        connection, and declaring it would state a requirement this step does
        not have (DATABASE-STEP-CAPABILITY-AUDIT.md §4)."""
        from resource_explorer.surveyors.database.survey_definition_adapter import (
            DATABASE_STEP_REGISTRY,
        )

        assert DATABASE_STEP_REGISTRY["db_derived"].requires_capability == ""
        assert DATABASE_STEP_REGISTRY["db_derived"].fetch_cost == "none"


class TestSchemaContainmentGrain:
    """#266's ruling, applied to the new analyses: a database's structural
    output aggregates at the wrong grain when it reads every schema as one
    flat bag."""

    def _two_schemas(self, registry):
        tables = [
            _table("daily_sales", schema="sales"),
            _table("employee", schema="hr"),
        ]
        columns = [
            _column("daily_sales", "sale_id", pk=True, schema="sales"),
            _column("daily_sales", "sold_on", dtype="date", schema="sales"),
            _column("employee", "employee_id", pk=True, schema="hr"),
        ]
        profiles = [
            _profile("daily_sales", "sold_on", min_value="2025-01-01",
                     max_value="2025-12-31", schema="sales"),
        ]
        _store(registry, "coco_ods", NOW, tables=tables, columns=columns,
               profiles=profiles)

    def test_subject_terms_are_broken_down_per_schema(self, registry):
        self._two_schemas(registry)
        payload = run_db_derived(registry, "coco_ods")["derived"]["subject_signals"]
        by_schema = payload["by_schema"]
        assert {t["term"] for t in by_schema["sales"]["terms"]} >= {"sales"}
        assert {t["term"] for t in by_schema["hr"]["terms"]} >= {"employee"}
        assert payload["aggregation"]["is_rollup"] is True
        assert payload["aggregation"]["averaged"] is False

    def test_a_whole_database_window_is_labelled_as_the_widest_span(self, registry):
        """One schema is dated and one is not, so the database-wide window is
        a span no single schema covers — and the rollup must say so instead of
        letting it read as a per-schema fact."""
        self._two_schemas(registry)
        payload = run_db_derived(registry, "coco_ods")["derived"]["coverage_signals"]
        agg = payload["aggregation"]
        assert agg["rollup_kind"] == "widest_span"
        assert list(agg["windows_by_container"]) == ["sales"]
        assert [u["container"] for u in agg["containers_without_window"]] == ["hr"]
        assert payload["by_schema"]["hr"]["temporal"]["reason"] == \
            COVERAGE_REASON_NO_DATE_COLUMNS

    def test_fit_is_counted_per_schema_never_averaged(self, registry):
        """The gate's unit is the schema: "one of two schemas fits" is a
        different answer from "the database fits"."""
        self._two_schemas(registry)
        payload = run_db_derived(registry, "coco_ods", lens={
            "subjectTerms": ["sales"], "interval": "daily",
        })["derived"]["preliminary_fit"]
        by_schema = payload["by_schema"]
        assert by_schema["sales"]["verdict"] == FIT_FITS
        assert by_schema["hr"]["verdict"] == FIT_DOES_NOT_FIT
        agg = payload["aggregation"]
        assert agg["averaged"] is False
        assert agg["verdict_counts"] == {FIT_FITS: 1, FIT_DOES_NOT_FIT: 1}
        assert agg["fitting_containers"] == ["sales"]
