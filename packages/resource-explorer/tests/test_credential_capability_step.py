"""Tests for the credential_capability step (design REPLY-DATABASE-
CREDENTIAL-CAPABILITY-VISIBILITY.md §3/§4, replying to
ASK-DATABASE-CREDENTIAL-CAPABILITY-VISIBILITY.md #251, "Piece 1"):
read-only catalog/privilege introspection of what the connecting credential
can see and do.

No live Postgres is used — `_FakeCredentialConnection` is a duck-typed
stand-in for `PostgreSQLConnection`, exercising the real
`DatabaseSurveyor._survey_credential_capability` /
`_create_credential_capability_annotations` code path end to end, same
pattern as `test_postgres_operations_step.py`.

Covered here, one class per concern:

* the visibility summary annotation — full coverage, and the incident's own
  worked numbers (3 of 26 tables, 6 of 8 schemas).
* the RFA fires when coverage is thin, and does not fire on full coverage.
* the capability-absent case renders "not supported", not "measured zero".
* `credential_capability` is opt-in, not part of a default survey().
* the third fact-envelope state (`_credential_scope_status`) is set exactly
  when coverage is thin, and stays silent otherwise.
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import patch

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.connection import EngineCapabilities
from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor
from resource_explorer.surveyors.database.survey_definition_adapter import (
    _credential_scope_status,
    _row_count_snapshot_results,
    _schema_inventory_results,
)
from resource_explorer.surveyors.result_status import MEASURED_WITHIN_CREDENTIAL_SCOPE
from resource_explorer.surveyors.survey_report import (
    RequestForActionAnnotation,
    ResourceMeasureAnnotation,
)


class _FakeCredentialConnection:
    """Duck-typed stand-in for PostgreSQLConnection covering exactly the
    methods DatabaseSurveyor's "credential_capability" step calls."""

    def __init__(self, capabilities: EngineCapabilities, credential_capability: dict | None = None):
        self._capabilities = capabilities
        self._credential_capability = credential_capability or {
            "connected_as": "",
            "schema_total": 0,
            "schema_visible": 0,
            "table_total": 0,
            "table_select": 0,
            "by_schema": {},
            "stats_role": False,
            "write_probed": True,
            "write_capable": False,
        }

    @property
    def capabilities(self):
        return self._capabilities

    def get_schema_info(self):
        return {"schemas": [], "total_tables": 0, "total_columns": 0}

    def get_statistics(self):
        return {}

    def get_credential_capability(self):
        return self._credential_capability


@contextmanager
def _patched_connection(conn):
    with patch(
        "resource_explorer.surveyors.database.database_surveyor.database_connection",
    ) as mock_ctx:
        mock_ctx.return_value.__enter__.return_value = conn
        mock_ctx.return_value.__exit__.return_value = False
        yield


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def db_entity(registry):
    entity = DatabaseEntity(
        slug="coco_pharma", display_name="Coco Pharma", db_type="postgresql",
        host="localhost", port=5432, database_name="coco_pharma",
        db_user="egeria_user", db_password="secret",
    )
    registry.register_database(entity)
    return entity


CAP_SUPPORTED = EngineCapabilities(credential_introspection=True)
CAP_UNSUPPORTED = EngineCapabilities()


def _run_credential_capability(db_entity, registry, conn):
    surveyor = DatabaseSurveyor(db_entity, {"user": "egeria_user", "password": "b"}, registry)
    with _patched_connection(conn):
        return surveyor.survey(steps=["credential_capability"])


def _by_type(annotations, cls):
    return [a for a in annotations if isinstance(a, cls)]


class TestVisibilitySummaryAnnotation:
    def test_full_coverage_states_the_fraction(self, registry, db_entity):
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "app_owner",
                "schema_total": 2, "schema_visible": 2,
                "table_total": 10, "table_select": 10,
                "by_schema": {
                    "public": {"usage_granted": True, "table_total": 10, "table_select": 10},
                },
                "stats_role": True, "write_probed": True, "write_capable": True,
            },
        )
        result = _run_credential_capability(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        summaries = [a for a in measures if "Connected as" in a.summary]
        assert len(summaries) == 1
        assert "app_owner" in summaries[0].summary
        assert "2 of 2" in summaries[0].summary
        assert "10 of 10" in summaries[0].summary
        assert summaries[0].confidence == 100
        assert result["credential_capability"]["connected_as"] == "app_owner"

    def test_coco_pharma_incidents_own_worked_numbers(self, registry, db_entity):
        """The real incident this probe was built to make visible: connected
        as egeria_user, visible 6 of 8 schemas, SELECT on 3 of 26 tables."""
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "egeria_user",
                "schema_total": 8, "schema_visible": 6,
                "table_total": 26, "table_select": 3,
                "by_schema": {
                    "coco_ods": {"usage_granted": True, "table_total": 23, "table_select": 0},
                    "eu_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                    "target_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                    "us_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                },
                "stats_role": False, "write_probed": True, "write_capable": False,
            },
        )
        result = _run_credential_capability(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        summary = [a for a in measures if "Connected as" in a.summary][0]
        assert "egeria_user" in summary.summary
        assert "6 of 8" in summary.summary
        assert "3 of 26" in summary.summary


class TestRfaOnThinCoverage:
    def test_rfa_fires_and_names_the_worst_schema(self, registry, db_entity):
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "egeria_user",
                "schema_total": 8, "schema_visible": 6,
                "table_total": 26, "table_select": 3,
                "by_schema": {
                    "coco_ods": {"usage_granted": True, "table_total": 23, "table_select": 0},
                    "eu_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                    "target_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                    "us_sales": {"usage_granted": True, "table_total": 1, "table_select": 1},
                },
                "stats_role": False, "write_probed": True, "write_capable": False,
            },
        )
        result = _run_credential_capability(db_entity, registry, conn)

        rfas = _by_type(result["annotations"], RequestForActionAnnotation)
        assert len(rfas) == 1
        assert "egeria_user" in rfas[0].summary
        assert "3 of 26" in rfas[0].summary
        assert rfas[0].action_target_name == "coco_ods.*"
        assert "grant select" in rfas[0].action_requested.lower()

    def test_no_rfa_on_full_coverage(self, registry, db_entity):
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "app_owner",
                "schema_total": 1, "schema_visible": 1,
                "table_total": 5, "table_select": 5,
                "by_schema": {"public": {"usage_granted": True, "table_total": 5, "table_select": 5}},
                "stats_role": True, "write_probed": True, "write_capable": True,
            },
        )
        result = _run_credential_capability(db_entity, registry, conn)

        assert not _by_type(result["annotations"], RequestForActionAnnotation)

    def test_no_rfa_when_no_tables_exist_at_all(self, registry, db_entity):
        """table_total == 0 must not divide by zero or fire a spurious RFA —
        an empty database is not a thin-coverage database."""
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "app_owner",
                "schema_total": 1, "schema_visible": 1,
                "table_total": 0, "table_select": 0,
                "by_schema": {},
                "stats_role": False, "write_probed": True, "write_capable": False,
            },
        )
        result = _run_credential_capability(db_entity, registry, conn)

        assert not _by_type(result["annotations"], RequestForActionAnnotation)


class TestCapabilityAbsentRendersNotSupportedNotZero:
    def test_capability_absent(self, registry, db_entity):
        conn = _FakeCredentialConnection(CAP_UNSUPPORTED)
        result = _run_credential_capability(db_entity, registry, conn)

        measures = _by_type(result["annotations"], ResourceMeasureAnnotation)
        not_supported = [
            a for a in measures
            if a.resource_properties.get("capability") == "credential_introspection"
        ]
        assert len(not_supported) == 1
        assert not_supported[0].confidence == 0
        assert not_supported[0].resource_properties["supported"] is False
        # Never a bare "0 of 0" summary standing in for "not measured".
        assert not any("Connected as" in a.summary for a in measures)


class TestCredentialCapabilityIsOptInNotDefault:
    def test_default_survey_does_not_run_credential_capability(self, registry, db_entity):
        conn = _FakeCredentialConnection(CAP_SUPPORTED)
        surveyor = DatabaseSurveyor(db_entity, {"user": "egeria_user", "password": "b"}, registry)
        with _patched_connection(conn):
            result = surveyor.survey()

        assert result["credential_capability"] == {}


class TestSurveyedAsRecordedOnTheSurveyRow:
    def test_connected_as_is_persisted_as_surveyed_as(self, registry, db_entity):
        conn = _FakeCredentialConnection(
            CAP_SUPPORTED,
            credential_capability={
                "connected_as": "egeria_user",
                "schema_total": 1, "schema_visible": 1,
                "table_total": 1, "table_select": 1,
                "by_schema": {"public": {"usage_granted": True, "table_total": 1, "table_select": 1}},
                "stats_role": False, "write_probed": True, "write_capable": False,
            },
        )
        _run_credential_capability(db_entity, registry, conn)

        latest = registry.get_latest_database_survey(db_entity.slug)
        assert latest is not None
        assert latest["surveyed_as"] == "egeria_user"


class TestThirdFactEnvelopeState:
    def _seed_survey_with_capability(self, registry, slug, cap):
        registry.record_database_survey(
            slug=slug, schema_count=1, table_count=cap.get("table_total", 0),
            column_count=0,
            survey_data={"credential_capability": cap},
        )

    def _seed_tables(self, registry, slug, count):
        registry.write_detail_rows(
            "database_tables", slug, "2026-09-24T00:00:00",
            rows=[
                {"schema_name": "public", "table_name": f"t{i}", "table_type": "BASE TABLE",
                 "row_count": 0, "size_bytes": 0}
                for i in range(count)
            ],
        )

    def test_thin_coverage_sets_the_third_state(self, registry, db_entity):
        self._seed_tables(registry, db_entity.slug, 3)
        self._seed_survey_with_capability(registry, db_entity.slug, {
            "connected_as": "egeria_user",
            "schema_total": 8, "schema_visible": 6,
            "table_total": 26, "table_select": 3,
        })

        status = _credential_scope_status(registry, db_entity.slug)
        assert status is not None
        assert status["state"] == MEASURED_WITHIN_CREDENTIAL_SCOPE
        assert status["connected_as"] == "egeria_user"
        assert "3 of 26" in status["fraction"]
        assert "6 of 8" in status["fraction"]

        value = _schema_inventory_results(registry, db_entity.slug)
        assert value["_status"]["state"] == MEASURED_WITHIN_CREDENTIAL_SCOPE

        row_value = _row_count_snapshot_results(registry, db_entity.slug)
        assert row_value["_status"]["state"] == MEASURED_WITHIN_CREDENTIAL_SCOPE

    def test_full_coverage_stays_silent(self, registry, db_entity):
        self._seed_tables(registry, db_entity.slug, 5)
        self._seed_survey_with_capability(registry, db_entity.slug, {
            "connected_as": "app_owner",
            "schema_total": 1, "schema_visible": 1,
            "table_total": 5, "table_select": 5,
        })

        assert _credential_scope_status(registry, db_entity.slug) is None
        value = _schema_inventory_results(registry, db_entity.slug)
        assert "_status" not in value

    def test_no_probe_yet_stays_silent(self, registry, db_entity):
        self._seed_tables(registry, db_entity.slug, 5)
        assert _credential_scope_status(registry, db_entity.slug) is None
