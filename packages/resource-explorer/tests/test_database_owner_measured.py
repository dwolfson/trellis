"""ENRICHMENT-E3: the database owner role (`pg_database.datdba`) is measured by
the schema step (which always runs and already holds the connection), stored on
the survey row, and surfaced on the `schema_inventory` fact as
`value["database_owner"]`. It is MATERIAL for Context's owner judgement row,
never a proposal. An existing database with no re-survey reads as "not measured
yet" (key absent), not as "no owner". Temp SQLite registry only."""
from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.database.connection import EngineCapabilities
from resource_explorer.surveyors.database.database_surveyor import DatabaseSurveyor
from resource_explorer.surveyors.database.survey_definition_adapter import (
    _database_owner_results,
    _schema_inventory_results,
)


class _Conn:
    capabilities = EngineCapabilities()

    def __init__(self, owner=None, raises=False, has_method=True):
        self._owner, self._raises = owner, raises
        if not has_method:
            self.get_database_owner = None

    def get_schema_info(self):
        return {"schemas": [], "total_tables": 0, "total_columns": 0}

    def get_statistics(self):
        return {}

    def get_database_owner(self):
        if self._raises:
            raise RuntimeError("permission denied")
        return {"owner": self._owner} if self._owner else {}


@contextmanager
def _patched(conn):
    with patch("resource_explorer.surveyors.database.database_surveyor.database_connection") as m:
        m.return_value.__enter__.return_value = conn
        m.return_value.__exit__.return_value = False
        yield


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


@pytest.fixture
def db(registry):
    e = DatabaseEntity(slug="coco_pharma", display_name="C", db_type="postgresql", host="h",
                       port=5432, database_name="coco_pharma", db_user="u", db_password="p")
    registry.register_database(e)
    return e


def _survey(db, registry, conn):
    with _patched(conn):
        return DatabaseSurveyor(db, {"user": "u", "password": "p"}, registry).survey(steps=["schema"])


def test_owner_is_measured_stored_and_read_back(registry, db):
    res = _survey(db, registry, _Conn(owner="pharma_owner"))
    assert res["database_owner"]["owner"] == "pharma_owner"
    assert res["database_owner"]["measured_at"]
    stored = json.loads(registry.get_latest_database_survey("coco_pharma")["survey_data"])
    assert stored["database_owner"]["owner"] == "pharma_owner"
    assert _database_owner_results(registry, "coco_pharma")["owner"] == "pharma_owner"


def test_never_measured_reads_as_absent_not_as_no_owner(registry, db):
    _survey(db, registry, _Conn(owner=None))
    assert _database_owner_results(registry, "coco_pharma") == {}


def test_a_failed_or_unsupported_read_is_nonfatal_and_absent(registry, db):
    failed = _survey(db, registry, _Conn(raises=True))
    assert failed["database_owner"] == {}
    assert any("database owner" in e for e in failed["errors"]), "a failed read must be observable, not silent"
    assert _survey(db, registry, _Conn(has_method=False))["database_owner"] == {}


def test_a_later_run_without_an_owner_keeps_the_prior_measurement(registry, db):
    _survey(db, registry, _Conn(owner="pharma_owner"))
    _survey(db, registry, _Conn(owner=None))
    assert _database_owner_results(registry, "coco_pharma")["owner"] == "pharma_owner"


def test_schema_inventory_value_carries_owner_only_when_measured(registry, db):
    tables = [{"schema_name": "public", "table_name": "t", "table_type": "BASE TABLE", "state": "measured"}]

    class Reg:
        def __init__(self, survey):
            self._s = survey

        def query_detail_rows(self, table, slug):
            return list(tables) if table == "database_tables" else []

        def get_latest_database_survey(self, slug):
            return {"survey_data": json.dumps(self._s)} if self._s is not None else None

        def get_database_surveys(self, slug):
            return [self.get_latest_database_survey(slug)] if self._s is not None else []

    measured = _schema_inventory_results(Reg({"database_owner": {"owner": "pharma_owner"}}), "x")
    assert measured["database_owner"]["owner"] == "pharma_owner"
    assert "database_owner" not in _schema_inventory_results(Reg({}), "x")
