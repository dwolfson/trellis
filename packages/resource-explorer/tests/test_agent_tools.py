"""Unit tests for new database and filesystem query agent tools and slug inference."""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from resource_explorer.registry import ProjectRegistry, DatabaseEntity, FileSystemEntity
from resource_explorer.agents.tools import query_databases_raw, query_database_schema_raw, query_filesystems_raw
from resource_explorer.agents.base import BaseExplorerAgent


class MockAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return "mock"
    def tools(self) -> list:
        return []
    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        return "mock"


@pytest.fixture
def db(tmp_path):
    """Isolated SQLite registry fixture for testing."""
    return ProjectRegistry(db_path=str(tmp_path / "test_agent_tools.db"))


def test_infer_database_and_filesystem_slugs(db):
    # Register a project, database, and filesystem
    db_entity = DatabaseEntity(
        slug="test-postgres-db",
        display_name="Test Postgres DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="test_db",
    )
    db.register_database(db_entity)

    fs_entity = FileSystemEntity(
        slug="my-files-share",
        display_name="My Files Share",
        local_mount_point="/tmp/my-files-share",
    )
    db.register_filesystem(fs_entity)

    agent = MockAgent()

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Test direct matching
        slugs_db = agent._infer_all_project_slugs("tell me about test-postgres-db")
        assert "test_postgres_db" in slugs_db

        slugs_fs = agent._infer_all_project_slugs("list files in my-files-share")
        assert "my_files_share" in slugs_fs


def test_query_databases_tool(db):
    # Empty registry
    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        res_empty = query_databases_raw()
        assert "No databases registered" in res_empty

        # Register a database
        db_entity = DatabaseEntity(
            slug="test-db",
            display_name="Test DB",
            db_type="postgresql",
            host="localhost",
            port=5432,
            database_name="test_db",
            governance_state="certified",
        )
        db.register_database(db_entity)

        res_list = query_databases_raw()
        assert "test_db" in res_list
        assert "Test DB" in res_list

        # Test single query without survey
        res_single = query_databases_raw("test-db")
        assert "Database: test_db" in res_single
        assert "No survey data available" in res_single

        # Add mock survey
        db.record_database_survey(
            slug="test-db",
            schema_count=1,
            table_count=1,
            column_count=2,
            survey_data={
                "schema_info": {
                    "schemas": [
                        {
                            "name": "public",
                            "tables": [
                                {
                                    "name": "users",
                                    "columns": [
                                        {"name": "id", "type": "integer"},
                                        {"name": "name", "type": "varchar(255)"}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        )

        res_survey = query_databases_raw("test-db")
        assert "Schema Count: 1" in res_survey
        assert "users" in res_survey


def test_query_database_schema_tool(db):
    # Register a database
    db_entity = DatabaseEntity(
        slug="test-db",
        display_name="Test DB",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="test_db",
    )
    db.register_database(db_entity)

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Query with no survey data
        assert "No survey data available" in query_database_schema_raw("test-db")

        # Add survey data
        db.record_database_survey(
            slug="test-db",
            schema_count=1,
            table_count=2,
            column_count=4,
            survey_data={
                "schema_info": {
                    "total_tables": 2,
                    "total_columns": 4,
                    "schemas": [
                        {
                            "name": "public",
                            "tables": [
                                {
                                    "name": "users",
                                    "type": "TABLE",
                                    "description": "User accounts table",
                                    "row_count": 120,
                                    "size_pretty": "16 KB",
                                    "columns": [
                                        {"position": 1, "name": "id", "type": "integer", "nullable": "NO", "is_primary_key": True},
                                        {"position": 2, "name": "email", "type": "varchar(255)", "nullable": "NO", "is_primary_key": False}
                                    ]
                                },
                                {
                                    "name": "profiles",
                                    "type": "TABLE",
                                    "columns": [
                                        {"position": 1, "name": "id", "type": "integer", "nullable": "NO"},
                                        {"position": 2, "name": "user_id", "type": "integer", "nullable": "NO", "foreign_key": {
                                            "foreign_schema": "public", "foreign_table": "users", "foreign_column": "id"
                                        }}
                                    ]
                                }
                            ]
                        }
                    ]
                }
            }
        )

        # 1. Query database summary
        db_summary = query_database_schema_raw("test-db")
        assert "Database Schema Summary for 'test-db'" in db_summary
        assert "users" in db_summary
        assert "profiles" in db_summary

        # 2. Query schema tables
        schema_summary = query_database_schema_raw("test-db", schema_name="public")
        assert "Schema: public" in schema_summary
        assert "users" in schema_summary

        # 3. Query table details
        table_summary = query_database_schema_raw("test-db", table_name="users")
        assert "Table: public.users" in table_summary
        assert "User accounts table" in table_summary
        assert "120" in table_summary
        assert "email" in table_summary
        assert "PK" in table_summary


def test_query_filesystems_tool(db):
    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Empty registry
        assert "No filesystems registered" in query_filesystems_raw()

        # Register a filesystem
        fs_entity = FileSystemEntity(
            slug="my-fs",
            display_name="My FS",
            local_mount_point="/tmp/my-fs",
            governance_state="qualified_candidate",
        )
        db.register_filesystem(fs_entity)

        assert "my_fs" in query_filesystems_raw()

        # Single filesystem without survey
        assert "No survey data available" in query_filesystems_raw("my-fs")

        # Add filesystem survey
        db.add_filesystem_survey(
            fs_slug="my-fs",
            surveyed_at="2026-07-27T16:00:00",
            survey_data={
                "total_files": 100,
                "total_data_files": 15,
                "total_size": "2.4 MB",
                "files": [
                    {"file_path": "src/main.py", "file_name": "main.py", "file_size": "4 KB", "format": "Python Source"},
                    {"file_path": "data/users.csv", "file_name": "users.csv", "file_size": "150 KB", "format": "CSV"}
                ]
            }
        )

        res_survey = query_filesystems_raw("my-fs")
        assert "Total Files: 100" in res_survey
        assert "main.py" in res_survey

        # Query with pattern filtering
        res_pattern = query_filesystems_raw("my-fs", file_pattern="csv")
        assert "users.csv" in res_pattern
        assert "main.py" not in res_pattern
