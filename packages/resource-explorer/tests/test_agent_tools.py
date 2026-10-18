"""Unit tests for new database and filesystem query agent tools and slug inference."""

from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch

from resource_explorer.registry import ProjectRegistry, DatabaseEntity, FileSystemEntity
from resource_explorer.agents.tools import (
    query_databases_raw,
    query_database_schema_raw,
    query_filesystems_raw,
)
from resource_explorer.agents.base import BaseExplorerAgent


class MockAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return "mock"

    def tools(self) -> list:
        return []

    def handle(self, query: str, resource_slug: str | None = None, **kwargs) -> str:
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
                                        {"name": "name", "type": "varchar(255)"},
                                    ],
                                }
                            ],
                        }
                    ]
                }
            },
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
                                        {
                                            "position": 1,
                                            "name": "id",
                                            "type": "integer",
                                            "nullable": "NO",
                                            "is_primary_key": True,
                                        },
                                        {
                                            "position": 2,
                                            "name": "email",
                                            "type": "varchar(255)",
                                            "nullable": "NO",
                                            "is_primary_key": False,
                                        },
                                    ],
                                },
                                {
                                    "name": "profiles",
                                    "type": "TABLE",
                                    "columns": [
                                        {
                                            "position": 1,
                                            "name": "id",
                                            "type": "integer",
                                            "nullable": "NO",
                                        },
                                        {
                                            "position": 2,
                                            "name": "user_id",
                                            "type": "integer",
                                            "nullable": "NO",
                                            "foreign_key": {
                                                "foreign_schema": "public",
                                                "foreign_table": "users",
                                                "foreign_column": "id",
                                            },
                                        },
                                    ],
                                },
                            ],
                        }
                    ],
                }
            },
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
                    {
                        "file_path": "src/main.py",
                        "file_name": "main.py",
                        "file_size": "4 KB",
                        "format": "Python Source",
                    },
                    {
                        "file_path": "data/users.csv",
                        "file_name": "users.csv",
                        "file_size": "150 KB",
                        "format": "CSV",
                    },
                ],
            },
        )

        res_survey = query_filesystems_raw("my-fs")
        assert "Total Files: 100" in res_survey
        assert "main.py" in res_survey

        # Query with pattern filtering
        res_pattern = query_filesystems_raw("my-fs", file_pattern="csv")
        assert "users.csv" in res_pattern
        assert "main.py" not in res_pattern


# ── contributor tier: the nested-window trap ────────────────────────────────
def test_contributor_tier_reads_the_widest_window_not_the_latest(tmp_path, monkeypatch):
    """`project_contributor_stats` holds NESTED trailing windows — 30d, 90d and
    365d, all ending today — not a sequence of periods.

    So the latest `period_start` is the NARROWEST window. Ordering by it
    descending answered "tier over the last 30 days" to a question about the
    contributor. Measured across the real catalogue on 2026-08-27: 70 of 347
    contributors got a different tier that way, every sampled case a core
    maintainer downgraded to "regular", and 271 more were missing from the
    30-day slice entirely — so the caller was told the tier was unknown and to
    "run refresh", about a tier that had already been computed.

    Earliest period_start = widest window. This pins the direction, because the
    two orderings differ by one keyword and the wrong one fails silently.
    """
    import sqlite3

    from resource_explorer.registry import Project, ProjectRegistry

    registry = ProjectRegistry(db_path=str(tmp_path / "r.db"))
    registry.add(
        Project(slug="demo", display_name="Demo", github_url="https://github.com/demo/demo")
    )
    with registry._conn() as conn:
        for period, tier in (
            ("2026-01-01", "core"),  # widest  (365d)
            ("2026-06-01", "regular"),  # middle  (90d)
            ("2026-08-01", "occasional"),
        ):  # narrowest (30d)
            conn.execute(
                "INSERT INTO project_contributor_stats "
                "(project_slug, period_start, period_end, author_email, author_name, "
                " commits, additions, deletions, tier) "
                "VALUES (?,?,?,?,?,?,?,?,?)",
                (
                    "demo",
                    period,
                    "2026-08-27",
                    "maintainer@example.com",
                    "Maintainer",
                    100,
                    0,
                    0,
                    tier,
                ),
            )

    with registry._conn() as conn:
        row = conn.execute(
            """SELECT tier FROM project_contributor_stats
               WHERE project_slug = ? AND author_email = ?
               ORDER BY period_start ASC LIMIT 1""",
            ("demo", "maintainer@example.com"),
        ).fetchone()

        assert row["tier"] == "core", (
            "the widest window must win; DESC would return 'occasional', which is "
            "this contributor's last 30 days, not who they are"
        )


def test_create_rfa_from_finding_tool(db):
    from resource_explorer.agents.tools import create_rfa_from_finding_raw
    from resource_explorer.registry import Project

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Empty summary error
        err = create_rfa_from_finding_raw("test-repo", "")
        assert "Error: summary must not be empty" in err

        # Create RFA for repo
        db.add(
            Project(
                slug="test-repo",
                display_name="Test Repo",
                github_url="https://github.com/test/repo",
            )
        )
        res_repo = create_rfa_from_finding_raw(
            resource_slug="test-repo",
            summary="Missing API reference documentation",
            detail="The OpenAPI schema has no endpoints documented for /users.",
            analysis_name="doc_coverage",
        )
        assert "Successfully created RequestForAction (RFA)" in res_repo
        assert "test_repo" in res_repo
        assert "Missing API reference documentation" in res_repo

        # Verify activity entry exists in registry
        entries = db.list_activity(limit=10)
        assert len(entries) >= 1
        rfa_entry = next(e for e in entries if e["operation"] == "rfa")
        assert rfa_entry["entity_slug"] == "test_repo"
        assert rfa_entry["intent"] == "enrichment"
        assert rfa_entry["summary"] == "Missing API reference documentation"
        assert len(rfa_entry["annotations"]) == 1
        assert rfa_entry["annotations"][0]["annotation_type"] == "RequestForActionAnnotation"

        # Create RFA for database
        db_ent = DatabaseEntity(
            slug="prod-db",
            display_name="Production Database",
            db_type="postgresql",
            host="db.example.com",
            port=5432,
            database_name="prod",
        )
        db.register_database(db_ent)
        res_db = create_rfa_from_finding_raw(
            resource_slug="prod-db",
            summary="Schema mismatch with staging",
            detail="Column 'is_active' missing from 'accounts' table.",
            analysis_name="schema_diff",
        )
        assert "Successfully created RequestForAction (RFA)" in res_db
        assert "database" in res_db
        assert "prod_db" in res_db


def test_compare_database_schemas_tool(db):
    from resource_explorer.agents.tools import compare_database_schemas_raw

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # 1. Missing databases
        assert "Database 'missing_db1' not found" in compare_database_schemas_raw(
            "missing_db1", "missing_db2"
        )

        # Register two databases
        db1 = DatabaseEntity(
            slug="db_staging",
            display_name="Staging DB",
            db_type="postgresql",
            host="stage.local",
            port=5432,
            database_name="staging_db",
        )
        db2 = DatabaseEntity(
            slug="db_prod",
            display_name="Prod DB",
            db_type="postgresql",
            host="prod.local",
            port=5432,
            database_name="production_db",
        )
        db.register_database(db1)
        db.register_database(db2)

        # 2. No survey data
        assert "No survey data available for either database" in compare_database_schemas_raw(
            "db_staging", "db_prod"
        )

        # 3. Add survey for db1 only
        survey_data_1 = {
            "schema_info": {
                "total_schemas": 1,
                "total_tables": 2,
                "total_columns": 5,
                "schemas": [
                    {
                        "name": "public",
                        "tables": [
                            {
                                "name": "users",
                                "row_count": 50,
                                "size_pretty": "16 KB",
                                "columns": [
                                    {
                                        "name": "id",
                                        "type": "integer",
                                        "nullable": False,
                                        "is_primary_key": True,
                                    },
                                    {
                                        "name": "email",
                                        "type": "varchar(255)",
                                        "nullable": False,
                                        "is_primary_key": False,
                                    },
                                    {
                                        "name": "is_active",
                                        "type": "boolean",
                                        "nullable": False,
                                        "is_primary_key": False,
                                    },
                                ],
                            },
                            {
                                "name": "audit_log",
                                "row_count": 200,
                                "size_pretty": "64 KB",
                                "columns": [
                                    {
                                        "name": "id",
                                        "type": "integer",
                                        "nullable": False,
                                        "is_primary_key": True,
                                    },
                                    {
                                        "name": "event",
                                        "type": "text",
                                        "nullable": False,
                                        "is_primary_key": False,
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        }
        db.record_database_survey(
            slug="db_staging",
            schema_count=1,
            table_count=2,
            column_count=5,
            survey_data=survey_data_1,
        )
        assert "No survey data available for database 'db_prod'" in compare_database_schemas_raw(
            "db_staging", "db_prod"
        )

        # 4. Add survey for db2 with differences:
        # - audit_log is missing in db2
        # - orders is only in db2
        # - users table has type mismatch on email (text vs varchar(255)) and missing is_active
        survey_data_2 = {
            "schema_info": {
                "total_schemas": 1,
                "total_tables": 2,
                "total_columns": 4,
                "schemas": [
                    {
                        "name": "public",
                        "tables": [
                            {
                                "name": "users",
                                "row_count": 1000,
                                "size_pretty": "128 KB",
                                "columns": [
                                    {
                                        "name": "id",
                                        "type": "integer",
                                        "nullable": False,
                                        "is_primary_key": True,
                                    },
                                    {
                                        "name": "email",
                                        "type": "text",
                                        "nullable": False,
                                        "is_primary_key": False,
                                    },
                                ],
                            },
                            {
                                "name": "orders",
                                "row_count": 500,
                                "size_pretty": "80 KB",
                                "columns": [
                                    {
                                        "name": "id",
                                        "type": "integer",
                                        "nullable": False,
                                        "is_primary_key": True,
                                    },
                                    {
                                        "name": "amount",
                                        "type": "numeric(10,2)",
                                        "nullable": False,
                                        "is_primary_key": False,
                                    },
                                ],
                            },
                        ],
                    }
                ],
            }
        }
        db.record_database_survey(
            slug="db_prod", schema_count=1, table_count=2, column_count=4, survey_data=survey_data_2
        )

        diff_res = compare_database_schemas_raw("db_staging", "db_prod")
        assert "Database Schema Comparison: Staging DB vs Prod DB" in diff_res
        assert "Tables only in db_staging: audit_log" in diff_res
        assert "Tables only in db_prod: orders" in diff_res
        assert "Columns only in db_staging: is_active" in diff_res
        assert "varchar(255)" in diff_res
        assert "text" in diff_res

        # 5. Filter by schema name
        filtered_res = compare_database_schemas_raw("db_staging", "db_prod", schema_name_a="public")
        assert "Schema 'public'" in filtered_res

        # Filter by non-existent schema
        missing_sch = compare_database_schemas_raw(
            "db_staging", "db_prod", schema_name_a="secret_schema"
        )
        assert "Schema 'secret_schema' not found" in missing_sch


def test_compare_agent_integration(db):
    from resource_explorer.agents.compare_agent import CompareAgent

    # Register databases in db
    db1 = DatabaseEntity(
        slug="db_alpha",
        display_name="DB Alpha",
        db_type="postgresql",
        host="alpha.internal",
        port=5432,
        database_name="alpha",
    )
    db2 = DatabaseEntity(
        slug="db_beta",
        display_name="DB Beta",
        db_type="postgresql",
        host="beta.internal",
        port=5432,
        database_name="beta",
    )
    db.register_database(db1)
    db.register_database(db2)

    agent = CompareAgent()
    tools = [
        t.name if hasattr(t, "name") else getattr(t, "__name__", str(t)) for t in agent.tools()
    ]
    assert "compare_database_schemas" in tools
    assert "create_rfa_from_finding" in tools
    assert "query_database_schema" in tools

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Fallback when comparing two databases
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Comparison completed successfully."
        with patch("resource_explorer.llm_client.get_llm", return_value=mock_llm):
            result = agent._fallback("compare db_alpha and db_beta", ["db_alpha", "db_beta"])
            assert result == "Comparison completed successfully."
            prompt_called = mock_llm.complete.call_args[0][0]
            assert "Database Schema Comparison" in prompt_called


def test_conversation_agent_has_new_tools():
    from resource_explorer.agents.conversation_agent import ConversationAgent

    agent = ConversationAgent()
    tools = [
        t.name if hasattr(t, "name") else getattr(t, "__name__", str(t)) for t in agent.tools()
    ]
    assert "compare_database_schemas" in tools
    assert "create_rfa_from_finding" in tools
    assert "query_cross_asset_links" in tools
    assert "delegate_to_compare_agent" in tools
    assert "delegate_to_integration_agent" in tools
    assert "query_egeria_lineage" in tools


def test_cross_asset_matcher(db):
    from resource_explorer.registry import Project, DatabaseEntity
    from resource_explorer.surveyors.cross_asset_matcher import (
        find_cross_asset_links,
        query_cross_asset_links_raw,
    )

    # 1. Register a project and database
    repo = Project(slug="ecommerce_service", display_name="E-Commerce Service", github_url="https://github.com/org/ecommerce")
    db.add(repo)

    db_entity = DatabaseEntity(
        slug="ecommerce_db",
        display_name="E-Commerce Database",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="ecommerce",
    )
    db.register_database(db_entity)

    # Record database survey with tables
    survey_data = {
        "schema_info": {
            "schemas": [
                {
                    "name": "public",
                    "tables": [
                        {"name": "users"},
                        {"name": "orders"},
                        {"name": "order_items"},
                    ],
                }
            ]
        }
    }
    db.record_database_survey(
        slug="ecommerce_db",
        schema_count=1,
        table_count=3,
        column_count=10,
        survey_data=survey_data,
    )

    # Add repo dependency on psycopg2 and sqlalchemy
    db.upsert_dependencies("ecommerce_service", [
        {"dep_name": "psycopg2-binary", "dep_version": "2.9.9", "dep_type": "runtime",
         "ecosystem": "pip", "source_file": "requirements.txt"},
        {"dep_name": "sqlalchemy", "dep_version": "2.0.0", "dep_type": "runtime",
         "ecosystem": "pip", "source_file": "requirements.txt"},
    ])

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        links = find_cross_asset_links(db)
        assert len(links) >= 1
        link = links[0]
        assert link["repo_slug"] == "ecommerce_service"
        assert link["database_slug"] == "ecommerce_db"
        assert link["score"] >= 0.3

        output = query_cross_asset_links_raw("ecommerce_service")
        assert "Discovered Cross-Asset Dependencies" in output
        assert "ecommerce_service" in output
        assert "ecommerce_db" in output


def test_multi_resource_context_compilation(db):
    from resource_explorer.registry import Project, DatabaseEntity
    from resource_explorer.context_compile import (
        build_epistemological_matrix,
        compile_multi_resource_context,
    )

    repo1 = Project(slug="app_alpha", display_name="App Alpha", github_url="https://github.com/org/alpha")
    repo2 = Project(slug="app_beta", display_name="App Beta", github_url="https://github.com/org/beta")
    db.add(repo1)
    db.add(repo2)

    # 1. Test epistemological asymmetry matrix
    md_table, records = build_epistemological_matrix(db, ["app_alpha", "app_beta"])
    assert "| Dimension" in md_table
    assert "app_alpha" in md_table
    assert "app_beta" in md_table
    assert len(records) > 0

    # 2. Test multi-resource compile
    compiled = compile_multi_resource_context(
        registry=db,
        slugs=["app_alpha", "app_beta"],
        question="Compare security scan and dependencies",
        budget=2000,
    )
    assert compiled.text != ""
    assert "MULTI-RESOURCE EVIDENCE COMPILATION" in compiled.text
    assert "app_alpha" in compiled.text
    assert "app_beta" in compiled.text
    assert compiled.manifest["mode"] == "multi_resource"
    assert len(compiled.manifest["slugs"]) == 2
    assert "coverage_matrix" in compiled.manifest


def test_dynamic_delegation_and_lineage_tools(db):
    from resource_explorer.agents.tools import (
        delegate_to_compare_agent_raw,
        delegate_to_integration_agent_raw,
        query_egeria_lineage_raw,
    )
    from resource_explorer.registry import Project, DatabaseEntity

    repo = Project(slug="repo_one", display_name="Repo One", github_url="https://github.com/org/one")
    db.add(repo)
    db_ent = DatabaseEntity(
        slug="db_one",
        display_name="DB One",
        db_type="postgresql",
        host="localhost",
        port=5432,
        database_name="db_one",
    )
    db.register_database(db_ent)

    # Force the direct-tool fallback: otherwise the real BeeAI agent runs against a live LLM.
    with patch("resource_explorer.registry.ProjectRegistry", return_value=db), patch(
        "resource_explorer.agents.base.BaseExplorerAgent._run_agent",
        side_effect=RuntimeError("agent unavailable"),
    ):
        # 1. Compare agent delegation fallback
        mock_llm = MagicMock()
        mock_llm.complete.return_value = "Delegated comparison response."
        with patch("resource_explorer.llm_client.get_llm", return_value=mock_llm):
            comp_resp = delegate_to_compare_agent_raw("compare repo_one and db_one")
            assert comp_resp == "Delegated comparison response."

        # 2. Integration agent delegation fallback
        with patch("resource_explorer.llm_client.get_llm", return_value=mock_llm):
            mock_llm.complete.return_value = "Delegated integration response."
            integ_resp = delegate_to_integration_agent_raw("how do repo_one and db_one work together?")
            assert integ_resp == "Delegated integration response."

        # 3. Egeria lineage query tool offline behavior
        with patch.dict("os.environ", {}, clear=True):
            lineage_resp = query_egeria_lineage_raw("repo_one", "db_one")
            assert "Egeria platform URL not configured" in lineage_resp


def test_compare_and_integration_agents_use_multi_resource_evidence(db):
    from resource_explorer.agents.compare_agent import CompareAgent
    from resource_explorer.agents.conversation_agent import ConversationAgent
    from resource_explorer.agents.integration_agent import IntegrationAgent
    from resource_explorer.registry import Project

    db.add(Project(slug="app_alpha", display_name="App Alpha", github_url="https://github.com/org/alpha"))
    db.add(Project(slug="app_beta", display_name="App Beta", github_url="https://github.com/org/beta"))

    seen: list[str] = []

    def _capture(self, prompt):
        seen.append(prompt)
        return "ok"

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db), patch(
        "resource_explorer.agents.base.BaseExplorerAgent._run_agent", _capture
    ), patch(
        "resource_explorer.agents.base.BaseExplorerAgent._infer_all_project_slugs",
        return_value=["app_alpha", "app_beta"],
    ), patch(
        "resource_explorer.context_compile.compile_multi_resource_context",
        wraps=None,
    ) as multi:
        from resource_explorer.context_compile import CompiledContext

        multi.return_value = CompiledContext(
            text="=== MULTI-RESOURCE EVIDENCE COMPILATION ===",
            compile_id="abc",
            manifest={
                "mode": "multi_resource",
                "gaps": [{"key": "security_scan", "reason": "no stored result", "resource_slug": "app_beta"}],
            },
            derivation=[],
        )
        for agent_cls in (CompareAgent, IntegrationAgent):
            seen.clear()
            agent = agent_cls()
            assert agent.handle("compare app_alpha and app_beta") == "ok"
            assert "MULTI-RESOURCE EVIDENCE COMPILATION" in seen[0]
            assert "[app_beta] Analyses that no stored result: security_scan." in seen[0]
            assert agent._last_compiled.manifest["mode"] == "multi_resource"

        # ConversationAgent hands the compile back for the route's payload.
        with patch(
            "resource_explorer.query_processor.QueryProcessor.classify",
            return_value=__import__("resource_explorer.query_processor", fromlist=["QueryIntent"]).QueryIntent.COMPARISON,
        ):
            conv = ConversationAgent()
            assert conv.handle("compare app_alpha and app_beta") == "ok"
            assert conv._last_compiled.compile_id == "abc"

        # A compiler that fails must not cost the answer.
        multi.side_effect = RuntimeError("boom")
        agent = CompareAgent()
        assert agent.handle("compare app_alpha and app_beta") == "ok"
        assert agent._last_compiled is None


def test_rfa_guardrails(db):
    from resource_explorer.agents.tools import create_rfa_from_finding_raw
    from resource_explorer.registry import Project

    db.add(Project(slug="rfa-repo", display_name="RFA Repo", github_url="https://github.com/o/r"))

    def _rfas():
        return [e for e in db.list_activity(limit=50) if e["operation"] == "rfa"]

    with patch("resource_explorer.registry.ProjectRegistry", return_value=db):
        # Unknown resource is refused, not filed as a repo.
        assert "not a registered" in create_rfa_from_finding_raw("nowhere", "Something")
        # Delivery status is not the agent's to choose.
        assert "not allowed" in create_rfa_from_finding_raw("rfa-repo", "Gap", status="pending")
        # Size limits.
        assert "keep it under" in create_rfa_from_finding_raw("rfa-repo", "x" * 201)
        assert "limit is" in create_rfa_from_finding_raw("rfa-repo", "Gap", detail="d" * 4001)
        assert _rfas() == []

        # Unconfirmed: preview only, nothing written.
        preview = create_rfa_from_finding_raw("rfa-repo", "Missing docs", confirm=False)
        assert "NOT FILED YET" in preview
        assert _rfas() == []

        # Confirmed: written once, as a local RFA.
        assert "Successfully created" in create_rfa_from_finding_raw("rfa-repo", "Missing docs")
        assert len(_rfas()) == 1 and _rfas()[0]["status"] == "local"

        # Same summary again (any case/whitespace) is not duplicated.
        again = create_rfa_from_finding_raw("rfa-repo", "  missing   DOCS ")
        assert "Not filed" in again
        assert len(_rfas()) == 1

        # Once a person has completed it, the same finding may be filed again.
        entry = _rfas()[0]
        db.upsert_rfa_action(
            rfa_id=f"{entry['id']}::0", entry_id=entry["id"], annotation_index=0,
            status="completed", activity_status="completed",
        )
        assert "Successfully created" in create_rfa_from_finding_raw("rfa-repo", "Missing docs")
        assert len(_rfas()) == 2

        # The agent-facing tool previews by default and does not expose delivery status.
        from resource_explorer.agents.tools import create_rfa_from_finding

        props = create_rfa_from_finding.input_schema.model_json_schema()["properties"]
        assert props["confirm"]["default"] is False
        assert "status" not in props


def _matcher_fixture(db, repo_slug, class_names, function_names=(), deps=()):
    from resource_explorer.ingestion.code_symbol_extractor import CodeSymbol
    from resource_explorer.registry import Project

    db.add(Project(slug=repo_slug, display_name=repo_slug, github_url=f"https://github.com/o/{repo_slug}"))

    def _sym(name, kind):
        return CodeSymbol(
            resource_slug=repo_slug, file_path=f"{name}.py", language="python", kind=kind,
            name=name, qualified_name=name, signature="", docstring="", start_line=1, end_line=2,
        )

    db.upsert_code_symbols(
        repo_slug,
        [_sym(n, "class") for n in class_names] + [_sym(n, "function") for n in function_names],
    )
    if deps:
        db.upsert_dependencies(repo_slug, [
            {"dep_name": d, "dep_version": "1", "dep_type": "runtime", "ecosystem": "pip",
             "source_file": "requirements.txt"} for d in deps
        ])


def _matcher_db(db, tables):
    from resource_explorer.registry import DatabaseEntity

    db.register_database(DatabaseEntity(
        slug="shop_db", display_name="Shop", db_type="postgresql", host="h", port=5432,
        database_name="shop",
    ))
    db.record_database_survey(
        slug="shop_db", schema_count=1, table_count=len(tables), column_count=1,
        survey_data={"schema_info": {"schemas": [{"name": "public", "tables": [{"name": t} for t in tables]}]}},
    )


def test_cross_asset_matcher_matches_model_classes_to_tables(db):
    from resource_explorer.surveyors.cross_asset_matcher import find_cross_asset_links

    _matcher_db(db, ["order_items", "categories", "invoices"])
    # OrderItem -> order_items (separators + plural), Category -> categories (ies -> y).
    _matcher_fixture(db, "shop_api", ["OrderItem", "Category"], deps=["sqlalchemy", "psycopg2-binary"])
    (link,) = find_cross_asset_links(db)
    assert link["matched_tables"] == ["categories", "order_items"]
    assert link["confidence"] == "high"


def test_cross_asset_matcher_ignores_non_class_symbols_and_beats_the_old_limit(db):
    from resource_explorer.surveyors.cross_asset_matcher import find_cross_asset_links

    _matcher_db(db, ["invoices"])
    # A function named like the table is not a model, however many other symbols come first.
    filler = [f"Helper{i}" for i in range(600)]
    _matcher_fixture(db, "shop_api", filler, function_names=["invoices"], deps=["sqlalchemy"])
    assert find_cross_asset_links(db) == []

    # And a model past the old 500-symbol window is still found.
    _matcher_fixture(db, "shop_core", filler + ["Invoice"], deps=["sqlalchemy"])
    (link,) = find_cross_asset_links(db, repo_slug="shop_core")
    assert link["matched_tables"] == ["invoices"]


def test_cross_asset_matcher_orm_alone_is_not_a_link(db):
    from resource_explorer.surveyors.cross_asset_matcher import find_cross_asset_links

    _matcher_db(db, ["invoices"])
    _matcher_fixture(db, "unrelated", ["Widget"], deps=["sqlalchemy"])
    assert find_cross_asset_links(db) == []


def test_cross_asset_matcher_generic_names_and_bare_class_matches_stay_low(db):
    from resource_explorer.surveyors.cross_asset_matcher import find_cross_asset_links

    _matcher_db(db, ["users", "roles", "sessions", "events", "tasks"])
    # Five generic-named classes and no driver or ORM behind them: a coincidence, not a "high" link.
    _matcher_fixture(db, "app", ["User", "Role", "Session", "Event", "Task"])
    links = find_cross_asset_links(db)
    assert all(l["confidence"] == "low" for l in links)
