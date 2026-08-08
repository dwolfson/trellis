"""Tests for database_connection()'s credential validation.

Regression coverage for a real bug: database_connection() used to do a raw
credentials["user"]/["password"] dict lookup with no validation, so a caller
passing an empty/incomplete credentials dict (as scheduler.py did) got a bare
KeyError instead of a clear, actionable error.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import DatabaseEntity
from resource_explorer.surveyors.database.connection import database_connection


@pytest.fixture
def db_entity():
    return DatabaseEntity(
        slug="test-db",
        display_name="Test DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="testdb",
    )


class TestCredentialValidation:
    def test_empty_credentials_raises_clear_valueerror(self, db_entity):
        with pytest.raises(ValueError, match="credentials are required"):
            with database_connection(db_entity, {}):
                pass

    def test_missing_password_raises_clear_valueerror(self, db_entity):
        with pytest.raises(ValueError, match="credentials are required"):
            with database_connection(db_entity, {"user": "admin"}):
                pass

    def test_missing_user_raises_clear_valueerror(self, db_entity):
        with pytest.raises(ValueError, match="credentials are required"):
            with database_connection(db_entity, {"password": "secret"}):
                pass

    def test_empty_string_credentials_also_rejected(self, db_entity):
        with pytest.raises(ValueError, match="credentials are required"):
            with database_connection(db_entity, {"user": "", "password": ""}):
                pass

    def test_unsupported_db_type_still_raises_its_own_error(self):
        entity = DatabaseEntity(
            slug="test-db", display_name="Test DB", db_type="oracle",
            host="localhost", port=1521, database_name="testdb",
        )
        with pytest.raises(ValueError, match="Unsupported database type"):
            with database_connection(entity, {"user": "a", "password": "b"}):
                pass
