"""Project Registry — SQLite-backed store for registered GitHub projects and databases."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from sqlalchemy import create_engine


class ProjectStatus(str, Enum):
    ACTIVE = "active"
    INDEXING = "indexing"
    PAUSED = "paused"
    ERROR = "error"


@dataclass
class ProjectGroup:
    """An umbrella grouping of related resources (repos, databases, filesystems)."""
    slug: str
    display_name: str
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class Project:
    slug: str
    display_name: str
    github_url: str
    description: str = ""
    homepage_url: str = ""
    docs_url: str = ""
    github_token_encrypted: str = ""  # encrypted; "" means use global token
    collections: list[str] = field(default_factory=list)
    status: ProjectStatus = ProjectStatus.ACTIVE
    last_indexed_at: str = ""
    last_stats_fetched_at: str = ""
    last_commit_sha: str = ""
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error_message: str = ""
    subproject_path: str = ""   # relative subdir to index, e.g. "commands" — "" means full repo
    parent_slug: str = ""       # slug of the parent project when this is a sub-project
    extra_docs_paths: list[str] = field(default_factory=list)  # repo-relative paths outside subproject_path to ingest as docs/examples
    egeria_asset_guid: str = ""  # GUID of the SourceControlLibrary asset in Egeria; "" = not yet published
    governance_state: str = "certified"
    group_slug: str = ""  # slug of the umbrella project group this repo belongs to; "" = ungrouped


@dataclass
class DatabaseServer:
    """Represents a PostgreSQL (or other) database server connection."""
    slug: str
    display_name: str
    db_type: str = "postgresql"
    host: str = "localhost"
    port: int = 5432
    description: str = ""
    db_user: str = ""
    db_password: str = ""
    egeria_host: str = ""   # hostname Egeria uses (e.g. host.docker.internal)
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    error_message: str = ""
    group_slug: str = ""  # slug of the umbrella project group this server belongs to


@dataclass
class DatabaseEntity:
    """Represents a database in the registry."""
    slug: str
    display_name: str
    db_type: str  # "postgresql", "mysql", "oracle", etc.
    host: str       # hostname as seen from the local machine
    port: int
    database_name: str
    description: str = ""
    connection_ref: str = ""  # Reference to secrets store or connection config
    status: ProjectStatus = ProjectStatus.ACTIVE
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_surveyed_at: str = ""
    egeria_asset_guid: str = ""  # GUID of the Database asset in Egeria
    error_message: str = ""
    # Stored connection credentials (plaintext — local dev tool)
    db_user: str = ""
    db_password: str = ""
    # Egeria-visible hostname for the DB server (e.g. host.docker.internal when DB is in Docker)
    egeria_host: str = ""
    # Stored Egeria connection details
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    # Server this database belongs to (if registered via server discovery)
    server_slug: str = ""
    governance_state: str = "certified"
    group_slug: str = ""  # slug of the umbrella project group this database belongs to


@dataclass
class FileSystemEntity:
    """Represents a filesystem in the registry."""
    slug: str
    display_name: str
    local_mount_point: str
    canonical_mount_point: str = ""
    description: str = ""
    status: ProjectStatus = ProjectStatus.ACTIVE
    registered_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    last_surveyed_at: str = ""
    egeria_asset_guid: str = ""  # GUID of the FileSystem asset in Egeria
    error_message: str = ""
    # Stored Egeria connection details
    egeria_url: str = ""
    egeria_server: str = ""
    egeria_user: str = ""
    egeria_password: str = ""
    file_count: int = 0
    data_file_count: int = 0
    governance_state: str = "certified"
    group_slug: str = ""  # slug of the umbrella project group this filesystem belongs to


@dataclass
class ActivityEntry:
    id: str
    ts: str
    operation: str    # 'scout' | 'survey' | 'catalog' | 'publish' | 'discover' | 'rfa' | 'refresh'
    intent: str       # 'scouting' | 'assessment' | 'discovery' | 'enrichment'
    entity_type: str  # 'repo' | 'database' | 'server' | 'filesystem' | 'file'
    entity_slug: str
    entity_name: str = ""
    entity_location: str = ""
    status: str = "ok"  # 'running' | 'ok' | 'error' | 'pending'
    summary: str = ""
    detail: str = ""
    items: list[dict] = field(default_factory=list)
    annotations: list[dict] = field(default_factory=list)


def _json_sanitize(obj):
    """Replace NaN/Infinity with None recursively.

    Survey data computed with pandas (e.g. null-rate stats) can contain NaN,
    which json.dumps accepts by default but Starlette's JSONResponse rejects
    (allow_nan=False) — so a value that round-tripped fine into SQLite would
    500 on the way back out over the API. Applied on read so already-stored
    rows self-heal without needing a re-survey.
    """
    if isinstance(obj, dict):
        return {k: _json_sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_sanitize(v) for v in obj]
    if isinstance(obj, float) and not math.isfinite(obj):
        return None
    return obj


class RowWrapper:
    def __init__(self, description, row_tuple):
        self._keys = [col[0] for col in description] if description else []
        self._values = row_tuple
        self._dict = dict(zip(self._keys, self._values))

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._dict[key]

    def keys(self):
        return self._keys

    def values(self):
        return self._values

    def items(self):
        return self._dict.items()

    def __iter__(self):
        return iter(self._keys)

    def get(self, key, default=None):
        return self._dict.get(key, default)

    def __repr__(self):
        return repr(self._dict)


class ConnectionWrapper:
    def __init__(self, raw_conn, is_postgres: bool):
        self.raw_conn = raw_conn
        self.is_postgres = is_postgres

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.raw_conn.rollback()
        else:
            self.raw_conn.commit()

    def execute(self, sql: str, params: Any = None):
        cursor = self.cursor()
        cursor.execute(sql, params)
        return cursor

    def executemany(self, sql: str, param_list: list):
        cursor = self.cursor()
        cursor.executemany(sql, param_list)
        return cursor

    def commit(self):
        self.raw_conn.commit()

    def close(self):
        self.raw_conn.close()

    def cursor(self):
        raw_cursor = self.raw_conn.cursor()
        if self.is_postgres:
            return PostgresCursorWrapper(raw_cursor)
        else:
            return SQLiteCursorWrapper(raw_cursor)


class SQLiteCursorWrapper:
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor

    def execute(self, sql: str, params: Any = None):
        if params is None:
            self.raw_cursor.execute(sql)
        else:
            self.raw_cursor.execute(sql, params)
        return self

    def executemany(self, sql: str, param_list: list):
        self.raw_cursor.executemany(sql, param_list)
        return self

    def fetchone(self):
        row = self.raw_cursor.fetchone()
        if row is None:
            return None
        return RowWrapper(self.raw_cursor.description, row)

    def fetchall(self):
        rows = self.raw_cursor.fetchall()
        desc = self.raw_cursor.description
        return [RowWrapper(desc, r) for r in rows]

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount


class PostgresCursorWrapper:
    def __init__(self, raw_cursor):
        self.raw_cursor = raw_cursor

    def _translate_sql(self, sql: str) -> str:
        sql_trans = sql.replace('?', '%s')
        sql_trans = re.sub(r'(?<!:):([a-zA-Z_][a-zA-Z0-9_]*)', r'%(\1)s', sql_trans)
        sql_trans = re.sub(r'(?i)\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b', 'SERIAL PRIMARY KEY', sql_trans)
        # GROUP_CONCAT(expr[, sep]) -> STRING_AGG(expr, sep) — Postgres has no
        # GROUP_CONCAT. Assumes a single, non-nested-comma argument (true of
        # every current call site); SQLite's default separator is ',',
        # matching STRING_AGG's required (no-default) separator argument.
        def _group_concat_to_string_agg(m):
            expr, sep = m.group(1), m.group(2) or "','"
            return f"STRING_AGG({expr}, {sep})"

        sql_trans = re.sub(
            r'(?i)\bGROUP_CONCAT\(\s*([^,()]+?)\s*(?:,\s*([^()]+?)\s*)?\)',
            _group_concat_to_string_agg,
            sql_trans,
        )
        return sql_trans

    def execute(self, sql: str, params: Any = None):
        sql_trans = self._translate_sql(sql)
        if params is None:
            self.raw_cursor.execute(sql_trans)
        else:
            self.raw_cursor.execute(sql_trans, params)
        return self

    def executemany(self, sql: str, param_list: list):
        if not param_list:
            return self
        sql_trans = self._translate_sql(sql)
        self.raw_cursor.executemany(sql_trans, param_list)
        return self

    def fetchone(self):
        row = self.raw_cursor.fetchone()
        if row is None:
            return None
        return RowWrapper(self.raw_cursor.description, row)

    def fetchall(self):
        rows = self.raw_cursor.fetchall()
        desc = self.raw_cursor.description
        return [RowWrapper(desc, r) for r in rows]

    @property
    def rowcount(self):
        return self.raw_cursor.rowcount


class ProjectRegistry:
    def __init__(self, db_path: str = "data/registry.db", database_url: str | None = None) -> None:
        """database_url, when given, is used verbatim — bypassing the
        db_path sentinel/config-lookup logic below entirely. Added for the
        real-Postgres integration test tier (Phase 8): db_path's own
        sentinel special-casing has no way to point a ProjectRegistry at an
        explicit, isolated Postgres URL (e.g. a throwaway test schema)
        without either mutating global config or forcing SQLite.
        """
        self.db_path = db_path
        if database_url is not None:
            self.database_url = database_url
        elif db_path == "data/registry.db":
            from resource_explorer.config import get_config
            try:
                config = get_config()
                self.database_url = config.registry.database_url
            except Exception:
                import os
                self.database_url = os.environ.get("REGISTRY_DATABASE_URL", f"sqlite:///{db_path}")
        else:
            self.database_url = f"sqlite:///{db_path}"

        if self.database_url.startswith("sqlite:///"):
            path_str = self.database_url[len("sqlite:///"):]
            if path_str and path_str != ":memory:":
                Path(path_str).parent.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(self.database_url)
        self._init_schema()

    @contextmanager
    def _conn(self):
        is_postgres = self.database_url.startswith("postgresql")
        raw_conn = self.engine.raw_connection()
        if not is_postgres:
            raw_conn.row_factory = sqlite3.Row
        conn = ConnectionWrapper(raw_conn, is_postgres)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _get_table_columns(self, conn, table_name: str) -> set[str]:
        """Columns currently on table_name, read through the SAME open
        transaction as the caller's CREATE TABLE — not a fresh connection via
        inspect(self.engine). That distinction matters on Postgres: a table
        just CREATEd in this transaction is invisible to a separate
        connection/inspector until commit, which made every "add column if
        missing" migration below think a brand-new table was missing columns
        it had literally just been created with, and crash trying to
        ALTER TABLE ADD a column that already existed. SQLite's PRAGMA
        table_info happened to dodge this (same-connection visibility), which
        is why the bug was invisible until this ran against real Postgres.
        """
        try:
            if conn.is_postgres:
                rows = conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_name = ? AND table_schema = current_schema()",
                    (table_name,),
                ).fetchall()
                return {r["column_name"] for r in rows}
            else:
                rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
                return {r["name"] for r in rows}
        except Exception:
            return set()

    def _init_schema(self) -> None:
        with self._conn() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    slug TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    github_url TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    homepage_url TEXT DEFAULT '',
                    docs_url TEXT DEFAULT '',
                    github_token_encrypted TEXT DEFAULT '',
                    collections TEXT DEFAULT '[]',
                    status TEXT DEFAULT 'active',
                    last_indexed_at TEXT DEFAULT '',
                    last_stats_fetched_at TEXT DEFAULT '',
                    last_commit_sha TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    error_message TEXT DEFAULT '',
                    subproject_path TEXT DEFAULT '',
                    parent_slug TEXT DEFAULT '',
                    extra_docs_paths TEXT DEFAULT '[]',
                    egeria_asset_guid TEXT DEFAULT NULL,
                    governance_state TEXT DEFAULT 'certified',
                    group_slug TEXT DEFAULT ''
                )
            """)
            # Migrations: add new columns to existing databases
            existing = self._get_table_columns(conn, "projects")
            for col, defn in [
                ("last_commit_sha", "TEXT DEFAULT ''"),
                ("subproject_path", "TEXT DEFAULT ''"),
                ("parent_slug", "TEXT DEFAULT ''"),
                ("extra_docs_paths", "TEXT DEFAULT '[]'"),
                ("egeria_asset_guid", "TEXT DEFAULT NULL"),
                ("governance_state", "TEXT DEFAULT 'certified'"),
                ("group_slug", "TEXT DEFAULT ''"),
            ]:
                if col not in existing:
                    conn.execute(f"ALTER TABLE projects ADD COLUMN {col} {defn}")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_groups (
                    slug TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_stats (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    stars INTEGER,
                    forks INTEGER,
                    watchers INTEGER,
                    open_issues INTEGER,
                    contributors_count INTEGER,
                    commits_30d INTEGER,
                    commits_90d INTEGER,
                    releases_count INTEGER,
                    latest_release TEXT,
                    latest_release_at TEXT,
                    avg_release_interval_days INTEGER,
                    lines_of_code INTEGER,
                    file_count INTEGER,
                    repo_size_kb INTEGER,
                    primary_language TEXT,
                    language_breakdown TEXT DEFAULT '{}',
                    license TEXT DEFAULT '',
                    topics TEXT DEFAULT '',
                    repo_created_at TEXT DEFAULT '',
                    last_pushed_at TEXT DEFAULT '',
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            # Migrations: add new columns to existing databases
            existing_stats = self._get_table_columns(conn, "project_stats")
            for col, defn in [
                ("avg_release_interval_days", "INTEGER DEFAULT 0"),
                ("repo_size_kb", "INTEGER DEFAULT 0"),
                ("license", "TEXT DEFAULT ''"),
                ("topics", "TEXT DEFAULT ''"),
                ("repo_created_at", "TEXT DEFAULT ''"),
                ("last_pushed_at", "TEXT DEFAULT ''"),
                ("ingestion_file_count", "INTEGER DEFAULT NULL"),
                ("ingestion_lines_of_code", "INTEGER DEFAULT NULL"),
                ("commits_365d", "INTEGER DEFAULT NULL"),
            ]:
                if col not in existing_stats:
                    conn.execute(f"ALTER TABLE project_stats ADD COLUMN {col} {defn}")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_commits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug TEXT NOT NULL,
                    sha TEXT NOT NULL,
                    message TEXT DEFAULT '',
                    author_name TEXT DEFAULT '',
                    author_email TEXT DEFAULT '',
                    committed_at TEXT NOT NULL,
                    UNIQUE(project_slug, sha),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_code_symbols (
                    id             INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug   TEXT NOT NULL,
                    file_path      TEXT NOT NULL,
                    language       TEXT NOT NULL,
                    kind           TEXT NOT NULL,
                    name           TEXT NOT NULL,
                    qualified_name TEXT NOT NULL,
                    signature      TEXT DEFAULT '',
                    docstring      TEXT DEFAULT '',
                    summary        TEXT DEFAULT '',
                    start_line     INTEGER DEFAULT 0,
                    end_line       INTEGER DEFAULT 0,
                    parent_class   TEXT DEFAULT '',
                    return_type    TEXT DEFAULT '',
                    is_private     INTEGER DEFAULT 0,
                    is_async       INTEGER DEFAULT 0,
                    complexity     INTEGER DEFAULT 0,
                    UNIQUE(project_slug, file_path, qualified_name),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            # Migrations: add new columns to existing databases (AST-ownership-
            # transfer plan Phase 3 — these five didn't exist before)
            existing_symbol_cols = self._get_table_columns(conn, "project_code_symbols")
            for col, defn in [
                ("parent_class", "TEXT DEFAULT ''"),
                ("return_type", "TEXT DEFAULT ''"),
                ("is_private", "INTEGER DEFAULT 0"),
                ("is_async", "INTEGER DEFAULT 0"),
                ("complexity", "INTEGER DEFAULT 0"),
            ]:
                if col not in existing_symbol_cols:
                    conn.execute(f"ALTER TABLE project_code_symbols ADD COLUMN {col} {defn}")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_slug_kind "
                "ON project_code_symbols(project_slug, kind)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_name "
                "ON project_code_symbols(project_slug, name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_symbols_parent_class "
                "ON project_code_symbols(project_slug, parent_class)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_code_relationships (
                    id                INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug      TEXT NOT NULL,
                    relationship_type TEXT NOT NULL DEFAULT 'inherits_from',
                    source_name       TEXT NOT NULL,
                    target_name       TEXT NOT NULL,
                    UNIQUE(project_slug, relationship_type, source_name, target_name),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_source "
                "ON project_code_relationships(project_slug, source_name)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_relationships_target "
                "ON project_code_relationships(project_slug, target_name)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_aliases (
                    alias        TEXT PRIMARY KEY,
                    project_slug TEXT NOT NULL,
                    confirmed_by TEXT DEFAULT 'user',
                    created_at   TEXT NOT NULL,
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            # Migrations: add additions / deletions to existing project_commits rows
            existing_commits = self._get_table_columns(conn, "project_commits")
            for col, defn in [
                ("additions", "INTEGER DEFAULT NULL"),
                ("deletions", "INTEGER DEFAULT NULL"),
            ]:
                if col not in existing_commits:
                    conn.execute(f"ALTER TABLE project_commits ADD COLUMN {col} {defn}")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_contributor_stats (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug  TEXT NOT NULL,
                    period_start  TEXT NOT NULL,
                    period_end    TEXT NOT NULL,
                    author_email  TEXT NOT NULL,
                    author_name   TEXT NOT NULL,
                    commits       INTEGER DEFAULT 0,
                    additions     INTEGER DEFAULT 0,
                    deletions     INTEGER DEFAULT 0,
                    tier          TEXT DEFAULT '',
                    UNIQUE(project_slug, period_start, period_end, author_email),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_contributor_stats_slug "
                "ON project_contributor_stats(project_slug, period_start)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS conversation_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    turn_idx INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    project_slug TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_conv_session "
                "ON conversation_history(session_id, turn_idx)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_dependencies (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug TEXT NOT NULL,
                    dep_name TEXT NOT NULL,
                    dep_version TEXT DEFAULT '',
                    dep_type TEXT DEFAULT 'runtime',
                    ecosystem TEXT DEFAULT '',
                    source_file TEXT DEFAULT '',
                    indexed_at TEXT NOT NULL,
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_deps_slug "
                "ON project_dependencies(project_slug)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_deps_name "
                "ON project_dependencies(dep_name)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_file_type_counts (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug TEXT NOT NULL,
                    surveyed_at  TEXT NOT NULL,
                    type_label   TEXT NOT NULL,
                    file_count   INTEGER NOT NULL,
                    source       TEXT DEFAULT 'extension',
                    details_json TEXT DEFAULT NULL,
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_type_slug "
                "ON project_file_type_counts(project_slug)"
            )
            # Migration: add details_json if not present (existing databases)
            existing_ftc = self._get_table_columns(conn, "project_file_type_counts")
            if "details_json" not in existing_ftc:
                conn.execute(
                    "ALTER TABLE project_file_type_counts ADD COLUMN details_json TEXT DEFAULT NULL"
                )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_file_inventory (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug     TEXT NOT NULL,
                    file_path        TEXT NOT NULL,
                    file_size_bytes  INTEGER DEFAULT 0,
                    indexed_at       TEXT NOT NULL,
                    UNIQUE(project_slug, file_path),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_file_inventory_slug "
                "ON project_file_inventory(project_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_egeria_surveys (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug       TEXT NOT NULL,
                    surveyed_at        TEXT NOT NULL,
                    egeria_report_guid TEXT NOT NULL,
                    published_at       TEXT NOT NULL,
                    annotation_count   INTEGER DEFAULT NULL,
                    UNIQUE(project_slug, surveyed_at),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            # Migration: add annotation_count if not present (existing databases)
            existing_es = self._get_table_columns(conn, "project_egeria_surveys")
            if "annotation_count" not in existing_es:
                conn.execute(
                    "ALTER TABLE project_egeria_surveys ADD COLUMN annotation_count INTEGER DEFAULT NULL"
                )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_egeria_surveys_slug "
                "ON project_egeria_surveys(project_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS project_data_profiles (
                    id               INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_slug     TEXT NOT NULL,
                    file_path        TEXT NOT NULL,
                    profiled_at      TEXT NOT NULL,
                    format           TEXT NOT NULL,
                    row_count        INTEGER DEFAULT NULL,
                    col_count        INTEGER DEFAULT NULL,
                    schema_json      TEXT DEFAULT NULL,
                    null_summary     TEXT DEFAULT '',
                    file_size_bytes  INTEGER DEFAULT 0,
                    UNIQUE(project_slug, file_path),
                    FOREIGN KEY (project_slug) REFERENCES projects(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_data_profiles_slug "
                "ON project_data_profiles(project_slug)"
            )
            # Database entities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS databases (
                    slug TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    db_type TEXT NOT NULL,
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL,
                    database_name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    connection_ref TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    registered_at TEXT NOT NULL,
                    last_surveyed_at TEXT DEFAULT '',
                    egeria_asset_guid TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    db_user TEXT DEFAULT '',
                    db_password TEXT DEFAULT '',
                    egeria_host TEXT DEFAULT '',
                    egeria_url TEXT DEFAULT '',
                    egeria_server TEXT DEFAULT '',
                    egeria_user TEXT DEFAULT '',
                    egeria_password TEXT DEFAULT '',
                    schema_count INTEGER DEFAULT 0,
                    table_count INTEGER DEFAULT 0,
                    column_count INTEGER DEFAULT 0,
                    governance_state TEXT DEFAULT 'certified',
                    group_slug TEXT DEFAULT ''
                )
            """)
            # Migration: add credential/egeria/survey-count columns to existing databases tables
            existing_db = self._get_table_columns(conn, "databases")
            for col, defval in [
                ("db_user", "''"),
                ("db_password", "''"),
                ("egeria_host", "''"),
                ("egeria_url", "''"),
                ("egeria_server", "''"),
                ("egeria_user", "''"),
                ("egeria_password", "''"),
                ("server_slug", "''"),
                ("schema_count", "0"),
                ("table_count", "0"),
                ("column_count", "0"),
                ("governance_state", "'certified'"),
                ("group_slug", "''"),
            ]:
                if col not in existing_db:
                    deftype = "INTEGER" if defval == "0" else "TEXT"
                    conn.execute(f"ALTER TABLE databases ADD COLUMN {col} {deftype} DEFAULT {defval}")
            # Database servers table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS db_servers (
                    slug TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    db_type TEXT NOT NULL DEFAULT 'postgresql',
                    host TEXT NOT NULL,
                    port INTEGER NOT NULL DEFAULT 5432,
                    description TEXT DEFAULT '',
                    db_user TEXT DEFAULT '',
                    db_password TEXT DEFAULT '',
                    egeria_host TEXT DEFAULT '',
                    egeria_url TEXT DEFAULT '',
                    egeria_server TEXT DEFAULT '',
                    egeria_user TEXT DEFAULT '',
                    egeria_password TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    registered_at TEXT NOT NULL,
                    error_message TEXT DEFAULT '',
                    group_slug TEXT DEFAULT ''
                )
            """)
            # Migration: add group_slug to db_servers
            existing_srv = self._get_table_columns(conn, "db_servers")
            if "group_slug" not in existing_srv:
                conn.execute("ALTER TABLE db_servers ADD COLUMN group_slug TEXT DEFAULT ''")
            # Database survey results table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS database_surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    database_slug TEXT NOT NULL,
                    surveyed_at TEXT NOT NULL,
                    egeria_report_guid TEXT DEFAULT '',
                    schema_count INTEGER DEFAULT 0,
                    table_count INTEGER DEFAULT 0,
                    column_count INTEGER DEFAULT 0,
                    survey_data TEXT DEFAULT '{}',
                    source TEXT DEFAULT 'local',
                    FOREIGN KEY (database_slug) REFERENCES databases(slug)
                )
            """)
            # Migration: add source column to existing database_surveys tables
            existing_ds = self._get_table_columns(conn, "database_surveys")
            if "source" not in existing_ds:
                conn.execute("ALTER TABLE database_surveys ADD COLUMN source TEXT DEFAULT 'local'")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_database_surveys_slug "
                "ON database_surveys(database_slug)"
            )
            # File system entities table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS file_systems (
                    slug TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    local_mount_point TEXT NOT NULL,
                    canonical_mount_point TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    status TEXT DEFAULT 'active',
                    registered_at TEXT NOT NULL,
                    last_surveyed_at TEXT DEFAULT '',
                    egeria_asset_guid TEXT DEFAULT '',
                    error_message TEXT DEFAULT '',
                    egeria_url TEXT DEFAULT '',
                    egeria_server TEXT DEFAULT '',
                    egeria_user TEXT DEFAULT '',
                    egeria_password TEXT DEFAULT '',
                    file_count INTEGER DEFAULT 0,
                    data_file_count INTEGER DEFAULT 0,
                    governance_state TEXT DEFAULT 'certified',
                    group_slug TEXT DEFAULT ''
                )
            """)
            # Migration: add new columns to existing file_systems tables
            existing_fs = self._get_table_columns(conn, "file_systems")
            for col, defval in [
                ("egeria_url", "''"),
                ("egeria_server", "''"),
                ("egeria_user", "''"),
                ("egeria_password", "''"),
                ("file_count", "0"),
                ("data_file_count", "0"),
                ("governance_state", "'certified'"),
                ("group_slug", "''"),
            ]:
                if col not in existing_fs:
                    deftype = "INTEGER" if defval == "0" else "TEXT"
                    conn.execute(f"ALTER TABLE file_systems ADD COLUMN {col} {deftype} DEFAULT {defval}")

            # File system survey results table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS filesystem_surveys (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    filesystem_slug TEXT NOT NULL,
                    surveyed_at TEXT NOT NULL,
                    egeria_report_guid TEXT DEFAULT '',
                    file_count INTEGER DEFAULT 0,
                    data_file_count INTEGER DEFAULT 0,
                    total_size_bytes INTEGER DEFAULT 0,
                    survey_data TEXT DEFAULT '{}',
                    source TEXT DEFAULT 'local',
                    FOREIGN KEY (filesystem_slug) REFERENCES file_systems(slug)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_filesystem_surveys_slug "
                "ON filesystem_surveys(filesystem_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_log (
                    id               TEXT PRIMARY KEY,
                    ts               TEXT NOT NULL,
                    operation        TEXT NOT NULL,
                    intent           TEXT NOT NULL,
                    entity_type      TEXT NOT NULL,
                    entity_slug      TEXT NOT NULL,
                    entity_name      TEXT DEFAULT '',
                    entity_location  TEXT DEFAULT '',
                    status           TEXT NOT NULL DEFAULT 'ok',
                    summary          TEXT DEFAULT '',
                    detail           TEXT DEFAULT '',
                    items_json       TEXT DEFAULT '[]',
                    annotations_json TEXT DEFAULT '[]'
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_log_ts "
                "ON activity_log(ts DESC)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_activity_log_entity "
                "ON activity_log(entity_slug, entity_type)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resource_context (
                    entity_type  TEXT NOT NULL,
                    entity_slug  TEXT NOT NULL,
                    ts           TEXT NOT NULL,
                    context_json TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (entity_type, entity_slug)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resource_tags (
                    entity_type  TEXT NOT NULL,
                    entity_slug  TEXT NOT NULL,
                    tag          TEXT NOT NULL,
                    created_at   TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_slug, tag)
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resource_tags_tag ON resource_tags(tag)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resource_feedback (
                    id           TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    entity_slug  TEXT NOT NULL,
                    rating       INTEGER DEFAULT NULL,
                    category     TEXT DEFAULT '',
                    message      TEXT NOT NULL DEFAULT '',
                    created_at   TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resource_feedback_entity "
                "ON resource_feedback(entity_type, entity_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resource_curator_notes (
                    id           TEXT PRIMARY KEY,
                    entity_type  TEXT NOT NULL,
                    entity_slug  TEXT NOT NULL,
                    note         TEXT NOT NULL,
                    created_at   TEXT NOT NULL
                )
            """)
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_resource_curator_notes_entity "
                "ON resource_curator_notes(entity_type, entity_slug)"
            )
            conn.execute("""
                CREATE TABLE IF NOT EXISTS resource_schedules (
                    entity_type  TEXT NOT NULL,
                    entity_slug  TEXT NOT NULL,
                    analysis_id  TEXT NOT NULL,
                    schedule     TEXT NOT NULL DEFAULT 'manual',
                    enabled      INTEGER NOT NULL DEFAULT 1,
                    last_run     TEXT DEFAULT '',
                    next_run     TEXT DEFAULT '',
                    PRIMARY KEY (entity_type, entity_slug, analysis_id)
                )
            """)
            # Migration: last_run_status/last_run_activity_id — added so the
            # Admin Schedules overview can show success/error at a glance
            # without scanning activity_log. Populated by
            # update_schedule_after_run(), written by scheduler.py's
            # _run_due(), which now also writes a real ActivityEntry for
            # every scheduled run (previously only logged to Python's own
            # logger — a real gap, not by design; see scheduler.py).
            existing_sched = self._get_table_columns(conn, "resource_schedules")
            if "last_run_status" not in existing_sched:
                conn.execute("ALTER TABLE resource_schedules ADD COLUMN last_run_status TEXT DEFAULT ''")
            if "last_run_activity_id" not in existing_sched:
                conn.execute("ALTER TABLE resource_schedules ADD COLUMN last_run_activity_id TEXT DEFAULT ''")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS survey_definition_cache (
                    entity_type            TEXT NOT NULL,
                    entity_slug            TEXT NOT NULL,
                    technology_type        TEXT NOT NULL,
                    process_guid           TEXT NOT NULL,
                    process_qualified_name TEXT DEFAULT '',
                    cached_at              TEXT NOT NULL,
                    PRIMARY KEY (entity_type, entity_slug, technology_type)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rfa_actions (
                    id                TEXT PRIMARY KEY,
                    entry_id          TEXT NOT NULL,
                    annotation_index  INTEGER NOT NULL,
                    rfa_status        TEXT NOT NULL DEFAULT 'open',
                    assignee          TEXT DEFAULT '',
                    defer_until       TEXT DEFAULT '',
                    resolution_note   TEXT DEFAULT '',
                    updated_at        TEXT NOT NULL DEFAULT ''
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS annotation_types (
                    annotation_type TEXT PRIMARY KEY,
                    display_name    TEXT NOT NULL,
                    description     TEXT DEFAULT '',
                    properties      TEXT DEFAULT '[]',
                    egeria_type     TEXT DEFAULT '',
                    python_class    TEXT DEFAULT ''
                )
            """)
            count = conn.execute("SELECT COUNT(*) FROM annotation_types").fetchone()[0]
            if count == 0:
                from resource_explorer.surveyors.survey_report import ANNOTATION_TYPES_REGISTRY
                for item in ANNOTATION_TYPES_REGISTRY:
                    conn.execute(
                        """INSERT INTO annotation_types (
                            annotation_type, display_name, description, properties, egeria_type, python_class
                        ) VALUES (?, ?, ?, ?, ?, ?)""",
                        (
                            item["type"],
                            item["display_name"],
                            item["description"],
                            json.dumps(item["properties"]),
                            item["egeria_type"],
                            item["python_class"],
                        ),
                    )

    def get_survey_definition_guid(
        self, entity_type: str, entity_slug: str, technology_type: str
    ) -> dict | None:
        """Return the cached {process_guid, process_qualified_name, cached_at} for a
        resource + technology type, or None if nothing is cached yet."""
        entity_slug = self._normalize_slug(entity_slug)
        with self._conn() as conn:
            row = conn.execute(
                """SELECT process_guid, process_qualified_name, cached_at
                   FROM survey_definition_cache
                   WHERE entity_type = ? AND entity_slug = ? AND technology_type = ?""",
                (entity_type, entity_slug, technology_type),
            ).fetchone()
        if row is None:
            return None
        return {
            "process_guid": row["process_guid"],
            "process_qualified_name": row["process_qualified_name"],
            "cached_at": row["cached_at"],
        }

    def set_survey_definition_guid(
        self,
        entity_type: str,
        entity_slug: str,
        technology_type: str,
        process_guid: str,
        process_qualified_name: str = "",
    ) -> None:
        """Cache the resolved GovernanceActionProcess GUID for a resource + technology type."""
        entity_slug = self._normalize_slug(entity_slug)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO survey_definition_cache
                       (entity_type, entity_slug, technology_type, process_guid,
                        process_qualified_name, cached_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_slug, technology_type) DO UPDATE SET
                       process_guid = excluded.process_guid,
                       process_qualified_name = excluded.process_qualified_name,
                       cached_at = excluded.cached_at""",
                (
                    entity_type,
                    entity_slug,
                    technology_type,
                    process_guid,
                    process_qualified_name,
                    datetime.utcnow().isoformat(),
                ),
            )

    def save_context(self, entity_type: str, entity_slug: str, context: dict) -> None:
        from datetime import timezone
        ts = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_context (entity_type, entity_slug, ts, context_json)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_slug) DO UPDATE SET
                     ts=excluded.ts, context_json=excluded.context_json""",
                (entity_type, entity_slug, ts, json.dumps(context)),
            )

    def get_context(self, entity_type: str, entity_slug: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT context_json, ts FROM resource_context WHERE entity_type=? AND entity_slug=?",
                (entity_type, entity_slug),
            ).fetchone()
        if not row:
            return None
        ctx = json.loads(row["context_json"] or "{}")
        ctx["_saved_at"] = row["ts"]
        return ctx

    # ── Curate — tags, resource-level feedback, curator notes ──────────────────
    # Discoverability/reuse-readiness for a resource, distinct from Enrichment's
    # resource_context (facts about the resource). See web/routes/curate.py.

    def add_resource_tag(self, entity_type: str, entity_slug: str, tag: str) -> None:
        from datetime import timezone
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_tags (entity_type, entity_slug, tag, created_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_slug, tag) DO NOTHING""",
                (entity_type, entity_slug, tag, datetime.now(timezone.utc).isoformat()),
            )

    def remove_resource_tag(self, entity_type: str, entity_slug: str, tag: str) -> None:
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM resource_tags WHERE entity_type=? AND entity_slug=? AND tag=?",
                (entity_type, entity_slug, tag),
            )

    def list_resource_tags(self, entity_type: str, entity_slug: str) -> list[str]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tag FROM resource_tags WHERE entity_type=? AND entity_slug=? ORDER BY tag",
                (entity_type, entity_slug),
            ).fetchall()
        return [r["tag"] for r in rows]

    def list_all_tags(self) -> list[dict]:
        """Distinct tags across all resources with their usage count — backs
        autocomplete and browse-by-tag ("making the resource easier to find")."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT tag, COUNT(*) as count FROM resource_tags GROUP BY tag ORDER BY tag"
            ).fetchall()
        return [{"tag": r["tag"], "count": r["count"]} for r in rows]

    def list_resources_by_tag(self, tag: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT entity_type, entity_slug FROM resource_tags WHERE tag=? ORDER BY entity_type, entity_slug",
                (tag,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_resource_feedback(
        self, entity_type: str, entity_slug: str, rating: int | None, category: str, message: str
    ) -> dict:
        from datetime import timezone
        entry = {
            "id": str(uuid.uuid4()),
            "entity_type": entity_type,
            "entity_slug": entity_slug,
            "rating": rating,
            "category": category,
            "message": message,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_feedback
                   (id, entity_type, entity_slug, rating, category, message, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                tuple(entry.values()),
            )
        return entry

    def list_resource_feedback(self, entity_type: str, entity_slug: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM resource_feedback WHERE entity_type=? AND entity_slug=?
                   ORDER BY created_at DESC""",
                (entity_type, entity_slug),
            ).fetchall()
        return [dict(r) for r in rows]

    def add_curator_note(self, entity_type: str, entity_slug: str, note: str) -> dict:
        """Ongoing curator commentary (discoverability, quality, readiness) —
        deliberately a separate stream from resource_context's 'notes' field,
        which is a one-time context-gathering fact, not a running log."""
        from datetime import timezone
        entry = {
            "id": str(uuid.uuid4()),
            "entity_type": entity_type,
            "entity_slug": entity_slug,
            "note": note,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_curator_notes (id, entity_type, entity_slug, note, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                tuple(entry.values()),
            )
        return entry

    def list_curator_notes(self, entity_type: str, entity_slug: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM resource_curator_notes WHERE entity_type=? AND entity_slug=?
                   ORDER BY created_at DESC""",
                (entity_type, entity_slug),
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_curator_note(self, note_id: str) -> bool:
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM resource_curator_notes WHERE id=?", (note_id,))
        return cur.rowcount > 0

    _SCHEDULE_DAYS: dict[str, int] = {"daily": 1, "weekly": 7, "monthly": 30}

    def _next_run_iso(self, schedule: str, enabled: bool) -> str:
        """Compute the ISO timestamp for the next scheduled run, or '' for manual/disabled."""
        from datetime import timezone, timedelta
        if not enabled or schedule not in self._SCHEDULE_DAYS:
            return ""
        return (datetime.now(timezone.utc) + timedelta(days=self._SCHEDULE_DAYS[schedule])).isoformat()

    def save_schedule(
        self,
        entity_type: str,
        entity_slug: str,
        analysis_id: str,
        schedule: str,
        enabled: bool = True,
    ) -> None:
        next_run = self._next_run_iso(schedule, enabled)
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO resource_schedules
                   (entity_type, entity_slug, analysis_id, schedule, enabled, next_run)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_slug, analysis_id) DO UPDATE SET
                     schedule=excluded.schedule, enabled=excluded.enabled,
                     next_run=excluded.next_run""",
                (entity_type, entity_slug, analysis_id, schedule, int(enabled), next_run),
            )

    def update_schedule_after_run(
        self,
        entity_type: str,
        entity_slug: str,
        analysis_id: str,
        status: str = "ok",
        activity_id: str = "",
    ) -> None:
        """Record last_run = now, advance next_run by the configured interval,
        and record the outcome (status/activity_id) of that run — see the
        resource_schedules migration comment for why."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT schedule FROM resource_schedules "
                "WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
                (entity_type, entity_slug, analysis_id),
            ).fetchone()
            if not row:
                return
            next_run = self._next_run_iso(row["schedule"], enabled=True)
            conn.execute(
                "UPDATE resource_schedules SET last_run=?, next_run=?, "
                "last_run_status=?, last_run_activity_id=? "
                "WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
                (now, next_run, status, activity_id, entity_type, entity_slug, analysis_id),
            )

    def get_schedules(self, entity_type: str, entity_slug: str) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM resource_schedules WHERE entity_type=? AND entity_slug=?",
                (entity_type, entity_slug),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all_schedules(self) -> list[dict]:
        """Every scheduled analysis across every resource — backs the Admin
        Schedules overview. Errors first (whatever needs follow-up surfaces
        immediately), then soonest-due, so the dashboard reads as a triage
        list rather than an alphabetical dump."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT * FROM resource_schedules
                   ORDER BY CASE WHEN last_run_status = 'error' THEN 0 ELSE 1 END,
                            next_run ASC"""
            ).fetchall()
        return [dict(r) for r in rows]

    def delete_schedule(self, entity_type: str, entity_slug: str, analysis_id: str) -> bool:
        """Remove a schedule entirely — returns False if none existed."""
        with self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM resource_schedules WHERE entity_type=? AND entity_slug=? AND analysis_id=?",
                (entity_type, entity_slug, analysis_id),
            )
        return cur.rowcount > 0

    def get_due_schedules(self) -> list[dict]:
        """Return all enabled schedules that are past their next_run time."""
        from datetime import timezone
        now = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM resource_schedules WHERE enabled=1 AND next_run != '' AND next_run <= ?",
                (now,),
            ).fetchall()
        return [dict(r) for r in rows]

    def add(self, project: Project) -> None:
        data = {
            **asdict(project),
            "collections": json.dumps(project.collections),
            "extra_docs_paths": json.dumps(project.extra_docs_paths),
        }
        data["slug"] = self._normalize_slug(data["slug"])
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO projects (
                    slug, display_name, github_url, description, homepage_url,
                    docs_url, github_token_encrypted, collections, status,
                    last_indexed_at, last_stats_fetched_at, last_commit_sha,
                    created_at, error_message, subproject_path, parent_slug,
                    extra_docs_paths, egeria_asset_guid, governance_state,
                    group_slug
                ) VALUES (
                    :slug, :display_name, :github_url, :description, :homepage_url,
                    :docs_url, :github_token_encrypted, :collections, :status,
                    :last_indexed_at, :last_stats_fetched_at, :last_commit_sha,
                    :created_at, :error_message, :subproject_path, :parent_slug,
                    :extra_docs_paths, :egeria_asset_guid, :governance_state,
                    :group_slug
                )""",
                data,
            )

    @staticmethod
    def _normalize_slug(slug: str) -> str:
        return slug.replace("-", "_").lower()

    def get(self, slug: str) -> Project | None:
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM projects WHERE slug = ?", (normalized,)).fetchone()
        return self._row_to_project(row) if row else None

    def list_all(self, governance_state: str | None = None) -> list[Project]:
        with self._conn() as conn:
            query = "SELECT * FROM projects WHERE 1=1"
            params = []
            if governance_state:
                query += " AND governance_state = ?"
                params.append(governance_state)
            query += " ORDER BY display_name"
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_project(r) for r in rows]

    def update_status(self, slug: str, status: ProjectStatus, error: str = "") -> None:
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET status = ?, error_message = ? WHERE slug = ?",
                (status.value, error, slug),
            )

    def update_indexed_at(self, slug: str, collections: list[str]) -> None:
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET last_indexed_at = ?, collections = ? WHERE slug = ?",
                (datetime.utcnow().isoformat(), json.dumps(collections), slug),
            )

    def update_extra_docs_paths(self, slug: str, paths: list[str]) -> None:
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET extra_docs_paths = ? WHERE slug = ?",
                (json.dumps(paths), slug),
            )

    def update_commit_sha(self, slug: str, sha: str) -> None:
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET last_commit_sha = ? WHERE slug = ?",
                (sha, slug),
            )

    def update_ingestion_stats(self, slug: str, file_count: int, lines_of_code: int) -> None:
        """Update the most recent project_stats row with counts from actual ingestion."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT id FROM project_stats WHERE project_slug = ? ORDER BY id DESC LIMIT 1",
                (slug,),
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE project_stats SET ingestion_file_count = ?, ingestion_lines_of_code = ? WHERE id = ?",
                    (file_count, lines_of_code, row["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO project_stats (project_slug, fetched_at, ingestion_file_count, ingestion_lines_of_code) "
                    "VALUES (?, ?, ?, ?)",
                    (slug, datetime.utcnow().isoformat(), file_count, lines_of_code),
                )

    def upsert_code_symbols(self, project_slug: str, symbols: list) -> None:
        """Insert or replace extracted code symbols, and derive+write
        inherits_from relationship rows from each class-kind symbol's
        `bases` list in the same call — mirroring Egeria Advisor's own
        CodeSymbolStore.upsert_symbols(), which does both in one pass (see
        AST-ownership-transfer plan Phase 3). symbols is a list of
        CodeSymbol dataclasses (resource_explorer/ingestion/code_symbol_extractor.py).
        """
        if not symbols:
            return
        slug = self._normalize_slug(project_slug)
        rows = [
            (
                slug, s.file_path, s.language, s.kind, s.name, s.qualified_name,
                s.signature, s.docstring, "", s.start_line, s.end_line,
                s.parent_class, s.return_type, int(s.is_private), int(s.is_async), s.complexity,
            )
            for s in symbols
        ]
        relationships = [
            (slug, "inherits_from", s.qualified_name, base)
            for s in symbols if s.kind == "class"
            for base in (s.bases or [])
        ]
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO project_code_symbols
                   (project_slug, file_path, language, kind, name, qualified_name,
                    signature, docstring, summary, start_line, end_line,
                    parent_class, return_type, is_private, is_async, complexity)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_slug, file_path, qualified_name)
                   DO UPDATE SET
                     language=excluded.language, kind=excluded.kind, name=excluded.name,
                     signature=excluded.signature, docstring=excluded.docstring,
                     start_line=excluded.start_line, end_line=excluded.end_line,
                     parent_class=excluded.parent_class, return_type=excluded.return_type,
                     is_private=excluded.is_private, is_async=excluded.is_async,
                     complexity=excluded.complexity""",
                rows,
            )
            if relationships:
                conn.executemany(
                    """INSERT INTO project_code_relationships
                       (project_slug, relationship_type, source_name, target_name)
                       VALUES (?, ?, ?, ?)
                       ON CONFLICT(project_slug, relationship_type, source_name, target_name)
                       DO NOTHING""",
                    relationships,
                )

    def clear_code_symbols(self, project_slug: str, language: str | None = None) -> None:
        """Remove symbol (and, when clearing a whole project, relationship)
        entries. Relationships aren't language-tagged themselves, so a
        language-filtered clear leaves them alone — they get reconciled
        naturally on the next full upsert_code_symbols() call for that
        project via ON CONFLICT DO NOTHING (stale target names, e.g. from a
        renamed/removed base class, are a known accepted gap — see migration
        plan decision D3, matching Egeria Advisor's own equivalent behavior)."""
        slug = self._normalize_slug(project_slug)
        with self._conn() as conn:
            if language:
                conn.execute(
                    "DELETE FROM project_code_symbols WHERE project_slug = ? AND language = ?",
                    (slug, language),
                )
            else:
                conn.execute(
                    "DELETE FROM project_code_symbols WHERE project_slug = ?", (slug,)
                )
                conn.execute(
                    "DELETE FROM project_code_relationships WHERE project_slug = ?", (slug,)
                )

    def get_code_relationships(
        self, project_slug: str, relationship_type: str = "inherits_from"
    ) -> list[dict]:
        """All relationship rows for a project, e.g. for CodeIntelAgent-style
        inheritance/hierarchy queries."""
        slug = self._normalize_slug(project_slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT source_name, target_name FROM project_code_relationships "
                "WHERE project_slug = ? AND relationship_type = ?",
                (slug, relationship_type),
            ).fetchall()
        return [dict(r) for r in rows]

    def upsert_contributor_stats(self, project_slug: str, rows: list[dict]) -> None:
        """Insert or replace aggregated per-contributor stats for a time period."""
        if not rows:
            return
        slug = self._normalize_slug(project_slug)
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO project_contributor_stats
                   (project_slug, period_start, period_end, author_email, author_name,
                    commits, additions, deletions, tier)
                   VALUES (:project_slug, :period_start, :period_end, :author_email, :author_name,
                           :commits, :additions, :deletions, :tier)
                   ON CONFLICT(project_slug, period_start, period_end, author_email)
                   DO UPDATE SET
                     author_name=excluded.author_name,
                     commits=excluded.commits,
                     additions=excluded.additions,
                     deletions=excluded.deletions,
                     tier=excluded.tier""",
                [{**r, "project_slug": slug} for r in rows],
            )

    def remove(self, slug: str) -> None:
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            # Children before parent — every table below has a real FK to
            # projects.slug, which SQLite silently ignores by default
            # (foreign_keys pragma is off) but Postgres enforces. This was
            # ALSO incomplete on SQLite itself: project_dependencies,
            # project_file_type_counts, project_file_inventory,
            # project_egeria_surveys, and project_data_profiles were never
            # cleaned up here at all, silently leaking orphaned rows on every
            # remove() — invisible on SQLite (no FK enforcement to surface
            # it), a hard FK-violation crash on Postgres. Found live during
            # Phase 4 Postgres cutover testing; fixed for both backends.
            conn.execute("DELETE FROM project_stats WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_commits WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_code_symbols WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_code_relationships WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_aliases WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_contributor_stats WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_dependencies WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_file_type_counts WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_file_inventory WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_egeria_surveys WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM project_data_profiles WHERE project_slug = ?", (normalized,))
            conn.execute("DELETE FROM projects WHERE slug = ?", (normalized,))

    # ── alias management ──────────────────────────────────────────────────────

    def add_alias(self, alias: str, slug: str, confirmed_by: str = "user") -> None:
        """Store an alias → slug mapping. Alias is normalized (lowercase, spaces→underscores)."""
        normalized = alias.lower().replace(" ", "_").replace("-", "_")
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO project_aliases (alias, project_slug, confirmed_by, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (alias) DO UPDATE SET "
                "project_slug = excluded.project_slug, confirmed_by = excluded.confirmed_by, "
                "created_at = excluded.created_at",
                (normalized, self._normalize_slug(slug), confirmed_by, datetime.utcnow().isoformat()),
            )

    def remove_alias(self, alias: str) -> bool:
        """Delete an alias. Returns True if a row was deleted."""
        normalized = alias.lower().replace(" ", "_").replace("-", "_")
        with self._conn() as conn:
            cursor = conn.execute("DELETE FROM project_aliases WHERE alias = ?", (normalized,))
            return cursor.rowcount > 0

    def resolve_alias(self, term: str) -> str | None:
        """Look up a term in the alias table; return the project slug or None."""
        normalized = term.lower().replace(" ", "_").replace("-", "_")
        with self._conn() as conn:
            row = conn.execute(
                "SELECT project_slug FROM project_aliases WHERE alias = ?", (normalized,)
            ).fetchone()
        return row["project_slug"] if row else None

    def list_aliases(self, slug: str | None = None) -> list[dict]:
        """Return all aliases, optionally filtered to a single project."""
        with self._conn() as conn:
            if slug:
                rows = conn.execute(
                    "SELECT alias, project_slug, confirmed_by, created_at FROM project_aliases "
                    "WHERE project_slug = ? ORDER BY alias",
                    (self._normalize_slug(slug),),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT alias, project_slug, confirmed_by, created_at FROM project_aliases "
                    "ORDER BY project_slug, alias"
                ).fetchall()
        return [dict(r) for r in rows]

    def fuzzy_candidate(self, query: str) -> tuple[str, str] | None:
        """
        Return (display_term, project_slug) if a phrase in the query fuzzy-matches a project.
        Uses difflib at 0.70 cutoff. Tries 1–4-word ngrams ordered longest-first.
        Returns None when no confident match exists.
        """
        import difflib
        q = query.lower()
        projects = self.list_all()
        candidates: dict[str, str] = {}  # normalized_name → slug
        for p in projects:
            candidates[p.slug.lower()] = p.slug
            if p.display_name:
                key = p.display_name.lower().replace("-", "_").replace(" ", "_")
                candidates[key] = p.slug
        if not candidates:
            return None
        words = q.split()
        for n in range(min(4, len(words)), 0, -1):
            for i in range(len(words) - n + 1):
                term = "_".join(words[i:i + n])
                matches = difflib.get_close_matches(term, list(candidates.keys()), n=1, cutoff=0.70)
                if matches:
                    display_term = " ".join(words[i:i + n])
                    return display_term, candidates[matches[0]]
        return None

    # ── file type counts (from surveyor) ─────────────────────────────────────

    def upsert_file_type_counts(
        self,
        slug: str,
        counts: dict[str, int],
        source: str = "extension",
        details: dict[str, dict] | None = None,
    ) -> None:
        """Append a new survey run's file-type counts. Historical runs are kept for trending.

        details: optional per-label breakdown dict (e.g. {"Other": {".toml": 5, ".yaml": 3}})
        """
        slug = self._normalize_slug(slug)
        surveyed_at = datetime.utcnow().isoformat()
        details = details or {}
        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO project_file_type_counts "
                "(project_slug, surveyed_at, type_label, file_count, source, details_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (slug, surveyed_at, label, count, source,
                     json.dumps(details[label]) if label in details else None)
                    for label, count in counts.items()
                ],
            )

    def query_file_type_counts(self, slug: str) -> list[dict]:
        """Return the most recent survey run's file-type counts, ordered by count desc.
        Each row includes surveyed_at so callers can display when the survey ran."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            latest_ts = conn.execute(
                "SELECT MAX(surveyed_at) FROM project_file_type_counts WHERE project_slug = ?",
                (slug,),
            ).fetchone()[0]
            if not latest_ts:
                return []
            rows = conn.execute(
                "SELECT type_label, file_count, source, surveyed_at, details_json "
                "FROM project_file_type_counts "
                "WHERE project_slug = ? AND surveyed_at = ? ORDER BY file_count DESC",
                (slug, latest_ts),
            ).fetchall()
        return [dict(r) for r in rows]

    def query_file_type_history(self, slug: str) -> list[dict]:
        """Return one row per survey run with total file count and timestamp, for trending."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            # MAX(source), not a bare `source` — SQLite's lax GROUP BY (any
            # selected column not in GROUP BY silently picks *a* row's value)
            # let this slide; Postgres correctly rejects it. source is
            # expected constant per surveyed_at run, so MAX just reproduces
            # SQLite's old behavior explicitly, without changing the
            # docstring's "one row per survey run" grouping granularity by
            # also grouping on source.
            rows = conn.execute(
                "SELECT surveyed_at, SUM(file_count) as total_files, MAX(source) as source "
                "FROM project_file_type_counts WHERE project_slug = ? "
                "GROUP BY surveyed_at ORDER BY surveyed_at ASC",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ── full file inventory ───────────────────────────────────────────────────

    def upsert_file_inventory(
        self, slug: str, paths_with_sizes: list[tuple[str, int]]
    ) -> None:
        """Replace the file inventory for a project (called during add/refresh)."""
        slug = self._normalize_slug(slug)
        indexed_at = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM project_file_inventory WHERE project_slug = ?", (slug,)
            )
            conn.executemany(
                "INSERT INTO project_file_inventory "
                "(project_slug, file_path, file_size_bytes, indexed_at) VALUES (?, ?, ?, ?)",
                [(slug, path, size, indexed_at) for path, size in paths_with_sizes],
            )

    def get_file_inventory(self, slug: str) -> list[str]:
        """Return all file paths from the stored inventory for a project."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT file_path FROM project_file_inventory WHERE project_slug = ?",
                (slug,),
            ).fetchall()
        return [r["file_path"] for r in rows]

    def store_data_profiles(self, slug: str, profiles: list[dict]) -> None:
        """Upsert data-file profiles produced during ingestion.

        Each profile dict must have: file_path, format, row_count (int|None),
        col_count (int|None), schema_json (str|None), null_summary (str),
        file_size_bytes (int).
        """
        slug = self._normalize_slug(slug)
        profiled_at = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.executemany(
                """INSERT INTO project_data_profiles
                   (project_slug, file_path, profiled_at, format,
                    row_count, col_count, schema_json, null_summary, file_size_bytes)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(project_slug, file_path) DO UPDATE SET
                     profiled_at=excluded.profiled_at,
                     format=excluded.format,
                     row_count=excluded.row_count,
                     col_count=excluded.col_count,
                     schema_json=excluded.schema_json,
                     null_summary=excluded.null_summary,
                     file_size_bytes=excluded.file_size_bytes""",
                [
                    (
                        slug,
                        p["file_path"],
                        profiled_at,
                        p["format"],
                        p.get("row_count"),
                        p.get("col_count"),
                        p.get("schema_json"),
                        p.get("null_summary", ""),
                        p.get("file_size_bytes", 0),
                    )
                    for p in profiles
                ],
            )

    def get_data_profiles(self, slug: str) -> list[dict]:
        """Return all stored data-file profiles for a project."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT file_path, format, row_count, col_count,
                          schema_json, null_summary, file_size_bytes, profiled_at
                   FROM project_data_profiles WHERE project_slug = ?
                   ORDER BY file_size_bytes DESC""",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_file_inventory_with_sizes(self, slug: str) -> list[dict]:
        """Return file paths and sizes from the inventory for a project.

        Each dict has keys: ``file_path`` (str) and ``file_size_bytes`` (int).
        """
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT file_path, file_size_bytes FROM project_file_inventory WHERE project_slug = ?",
                (slug,),
            ).fetchall()
        return [{"file_path": r["file_path"], "file_size_bytes": r["file_size_bytes"] or 0} for r in rows]

    # ── Egeria integration ────────────────────────────────────────────────────

    def get_egeria_asset_guid(self, slug: str) -> str | None:
        """Return the cached Egeria SourceControlLibrary GUID for a project, or None."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT egeria_asset_guid FROM projects WHERE slug = ?", (slug,)
            ).fetchone()
        if row:
            return row["egeria_asset_guid"] or None
        return None

    def set_egeria_asset_guid(self, slug: str, guid: str) -> None:
        """Persist the Egeria SourceControlLibrary GUID for a project."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE projects SET egeria_asset_guid = ? WHERE slug = ?",
                (guid, slug),
            )

    def clear_egeria_registration(self, slug: str) -> dict:
        """Clear the cached Egeria GUID and all published survey records for a project.

        Returns {"asset_guid_cleared": bool, "surveys_deleted": int} so callers
        can report what was removed.  Safe to call when the project is not registered.
        """
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT egeria_asset_guid FROM projects WHERE slug = ?", (slug,)
            ).fetchone()
            had_guid = bool(row and row["egeria_asset_guid"])
            conn.execute(
                "UPDATE projects SET egeria_asset_guid = NULL WHERE slug = ?", (slug,)
            )
            deleted = conn.execute(
                "DELETE FROM project_egeria_surveys WHERE project_slug = ?", (slug,)
            ).rowcount
        return {"asset_guid_cleared": had_guid, "surveys_deleted": deleted}

    def record_egeria_survey(
        self,
        slug: str,
        surveyed_at: str,
        report_guid: str,
        annotation_count: int | None = None,
    ) -> None:
        """Record a published Egeria SurveyReport GUID for a project survey run."""
        slug = self._normalize_slug(slug)
        published_at = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO project_egeria_surveys
                   (project_slug, surveyed_at, egeria_report_guid, published_at, annotation_count)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(project_slug, surveyed_at)
                   DO UPDATE SET egeria_report_guid = excluded.egeria_report_guid,
                                 published_at = excluded.published_at,
                                 annotation_count = excluded.annotation_count""",
                (slug, surveyed_at, report_guid, published_at, annotation_count),
            )

    def get_egeria_surveys(self, slug: str) -> list[dict]:
        """Return all published Egeria survey records for a project, newest first."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT project_slug, surveyed_at, egeria_report_guid, published_at, annotation_count
                   FROM project_egeria_surveys
                   WHERE project_slug = ?
                   ORDER BY surveyed_at DESC""",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_egeria_survey(self, slug: str) -> dict | None:
        """Return the most recent published Egeria survey record, or None."""
        surveys = self.get_egeria_surveys(slug)
        return surveys[0] if surveys else None

    def get_latest_project_stats(self, slug: str) -> dict | None:
        """Return the most recent project_stats row as a dict, or None."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM project_stats WHERE project_slug = ? ORDER BY id DESC LIMIT 1",
                (slug,),
            ).fetchone()
        return dict(row) if row else None

    # ── dependency graph ──────────────────────────────────────────────────────

    def upsert_dependencies(self, slug: str, deps: list[dict]) -> None:
        """Store parsed dependency list for a project, replacing any prior data."""
        if not deps:
            return
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM project_dependencies WHERE project_slug = ?", (slug,)
            )
            conn.executemany(
                "INSERT INTO project_dependencies "
                "(project_slug, dep_name, dep_version, dep_type, ecosystem, source_file, indexed_at) "
                "VALUES (:project_slug, :dep_name, :dep_version, :dep_type, :ecosystem, :source_file, :indexed_at)",
                [{**d, "project_slug": slug, "indexed_at": datetime.utcnow().isoformat()} for d in deps],
            )

    def query_dependencies(
        self,
        slug: str,
        dep_type: str | None = None,
        ecosystem: str | None = None,
    ) -> list[dict]:
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            filters = ["project_slug = ?"]
            params: list = [slug]
            if dep_type and dep_type != "all":
                filters.append("dep_type = ?")
                params.append(dep_type)
            if ecosystem:
                filters.append("ecosystem = ?")
                params.append(ecosystem)
            where = " AND ".join(filters)
            rows = conn.execute(
                f"SELECT dep_name, dep_version, dep_type, ecosystem, source_file "  # noqa: S608
                f"FROM project_dependencies WHERE {where} ORDER BY ecosystem, dep_type, dep_name",
                params,
            ).fetchall()
        return [dict(r) for r in rows]

    def query_shared_dependencies(self, slugs: list[str], dep_name: str | None = None) -> list[dict]:
        """Find dependencies shared across the given list of projects."""
        norms = [self._normalize_slug(s) for s in slugs]
        with self._conn() as conn:
            placeholders = ",".join("?" * len(norms))
            # HAVING references COUNT(*) directly, not the project_count
            # alias — SQLite allows referencing a SELECT-list alias in
            # HAVING, Postgres does not (HAVING is evaluated before aliases
            # are available in standard SQL semantics).
            rows = conn.execute(
                f"SELECT dep_name, ecosystem, GROUP_CONCAT(project_slug) as projects, COUNT(*) as project_count "  # noqa: S608
                f"FROM project_dependencies WHERE project_slug IN ({placeholders}) "
                f"GROUP BY dep_name, ecosystem HAVING COUNT(*) >= 2 ORDER BY project_count DESC, dep_name",
                norms,
            ).fetchall()
        return [dict(r) for r in rows]

    # ── conversation history ──────────────────────────────────────────────────

    def append_turn(
        self,
        session_id: str,
        role: str,
        content: str,
        project_slug: str | None = None,
    ) -> None:
        """Append a single turn (user or assistant) to the conversation log."""
        with self._conn() as conn:
            next_idx = (
                conn.execute(
                    "SELECT COALESCE(MAX(turn_idx), -1) + 1 FROM conversation_history WHERE session_id = ?",
                    (session_id,),
                ).fetchone()[0]
            )
            conn.execute(
                "INSERT INTO conversation_history (session_id, turn_idx, role, content, project_slug, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (session_id, next_idx, role, content, project_slug or "", datetime.utcnow().isoformat()),
            )

    def load_turns(self, session_id: str, limit: int = 40) -> list[dict]:
        """Return up to `limit` most-recent turns for a session, in chronological order."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT role, content, project_slug FROM conversation_history "
                "WHERE session_id = ? ORDER BY turn_idx DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def list_sessions(self) -> list[dict]:
        """Return a summary of all stored sessions (id, turn count, last activity)."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT session_id, COUNT(*) as turns, MAX(created_at) as last_at "
                "FROM conversation_history GROUP BY session_id ORDER BY last_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_by_github_url(self, url: str) -> "Project | None":
        """Look up a project by GitHub URL, normalizing away .git suffix and case."""
        normalized = url.lower().rstrip("/").removesuffix(".git")
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM projects").fetchall()
        for row in rows:
            stored = row["github_url"].lower().rstrip("/").removesuffix(".git")
            if stored == normalized:
                return self._row_to_project(row)
        return None

    def exists(self, slug: str) -> bool:
        return self.get(slug) is not None

    def _row_to_project(self, row: sqlite3.Row) -> Project:
        import dataclasses
        d = dict(row)
        d["collections"] = json.loads(d.get("collections") or "[]")
        d["extra_docs_paths"] = json.loads(d.get("extra_docs_paths") or "[]")
        d["status"] = ProjectStatus(d["status"])
        # Filter to only known Project fields to stay forward-compatible with schema changes
        known = {f.name for f in dataclasses.fields(Project)}
        return Project(**{k: v for k, v in d.items() if k in known})


    # ── database entity management ────────────────────────────────────────────

    def register_database(self, database: DatabaseEntity) -> None:
        """Register a database entity in the registry."""
        data = asdict(database)
        data["slug"] = self._normalize_slug(data["slug"])
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO databases (
                    slug, display_name, db_type, host, port, database_name,
                    description, connection_ref, status, registered_at,
                    last_surveyed_at, egeria_asset_guid, error_message,
                    db_user, db_password, egeria_host,
                    egeria_url, egeria_server, egeria_user, egeria_password,
                    server_slug, governance_state, group_slug
                ) VALUES (
                    :slug, :display_name, :db_type, :host, :port, :database_name,
                    :description, :connection_ref, :status, :registered_at,
                    :last_surveyed_at, :egeria_asset_guid, :error_message,
                    :db_user, :db_password, :egeria_host,
                    :egeria_url, :egeria_server, :egeria_user, :egeria_password,
                    :server_slug, :governance_state, :group_slug
                )""",
                data,
            )

    def get_database(self, slug: str) -> DatabaseEntity | None:
        """Retrieve a database entity by slug."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM databases WHERE slug = ?", (normalized,)).fetchone()
        return self._row_to_database(row) if row else None

    def list_databases(self, db_type: str | None = None, server_slug: str | None = None, governance_state: str | None = None) -> list[DatabaseEntity]:
        """List all registered databases, optionally filtered by type, server slug, or governance state."""
        with self._conn() as conn:
            query = "SELECT * FROM databases WHERE 1=1"
            params = []
            if server_slug:
                query += " AND server_slug = ?"
                params.append(self._normalize_slug(server_slug))
            if db_type:
                query += " AND db_type = ?"
                params.append(db_type)
            if governance_state:
                query += " AND governance_state = ?"
                params.append(governance_state)
            query += " ORDER BY display_name"
            
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_database(r) for r in rows]

    def update_database_status(self, slug: str, status: ProjectStatus, error: str = "") -> None:
        """Update the status of a database entity."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE databases SET status = ?, error_message = ? WHERE slug = ?",
                (status.value, error, slug),
            )

    def update_database_surveyed_at(self, slug: str) -> None:
        """Update the last_surveyed_at timestamp for a database."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE databases SET last_surveyed_at = ? WHERE slug = ?",
                (datetime.utcnow().isoformat(), slug),
            )

    def set_database_egeria_guid(self, slug: str, guid: str) -> None:
        """Set the Egeria asset GUID for a database."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "UPDATE databases SET egeria_asset_guid = ? WHERE slug = ?",
                (guid, slug),
            )

    def remove_database(self, slug: str) -> None:
        """Remove a database entity and all its survey records."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            # Child before parent — database_surveys has a real FK to
            # databases.slug; SQLite silently allows the reverse order
            # (foreign_keys pragma off by default), Postgres does not.
            conn.execute("DELETE FROM database_surveys WHERE database_slug = ?", (normalized,))
            conn.execute("DELETE FROM databases WHERE slug = ?", (normalized,))

    def record_database_survey(
        self,
        slug: str,
        schema_count: int,
        table_count: int,
        column_count: int,
        survey_data: dict,
        egeria_report_guid: str = "",
        source: str = "local",
    ) -> None:
        """Record a database survey result."""
        slug = self._normalize_slug(slug)
        surveyed_at = datetime.utcnow().isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO database_surveys
                   (database_slug, surveyed_at, egeria_report_guid, schema_count,
                    table_count, column_count, survey_data, source)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (slug, surveyed_at, egeria_report_guid, schema_count,
                 table_count, column_count, json.dumps(survey_data), source),
            )
            # Keep the databases row in sync so API responses reflect current counts
            conn.execute(
                """UPDATE databases
                   SET schema_count=?, table_count=?, column_count=?,
                       last_surveyed_at=?
                   WHERE slug=?""",
                (schema_count, table_count, column_count, surveyed_at, slug),
            )

    def get_database_surveys(self, slug: str) -> list[dict]:
        """Return all survey records for a database, newest first."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT database_slug, surveyed_at, egeria_report_guid,
                          schema_count, table_count, column_count, survey_data, source
                   FROM database_surveys
                   WHERE database_slug = ?
                   ORDER BY surveyed_at DESC""",
                (slug,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_latest_database_survey(self, slug: str) -> dict | None:
        """Return the most recent survey record for a database, or None."""
        surveys = self.get_database_surveys(slug)
        return surveys[0] if surveys else None

    def database_exists(self, slug: str) -> bool:
        """Check if a database entity exists."""
        return self.get_database(slug) is not None

    def _row_to_database(self, row: sqlite3.Row) -> DatabaseEntity:
        """Convert a database row to a DatabaseEntity dataclass."""
        import dataclasses
        d = dict(row)
        d["status"] = ProjectStatus(d["status"])
        # Filter to only known DatabaseEntity fields
        known = {f.name for f in dataclasses.fields(DatabaseEntity)}
        return DatabaseEntity(**{k: v for k, v in d.items() if k in known})

    # ── database server management ────────────────────────────────────────────

    def register_server(self, server: DatabaseServer) -> None:
        """Register a database server in the registry."""
        data = asdict(server)
        data["slug"] = self._normalize_slug(data["slug"])
        data["status"] = data["status"] if isinstance(data["status"], str) else data["status"]
        with self._conn() as conn:
            conn.execute("""INSERT INTO db_servers (
                slug, display_name, db_type, host, port, description,
                db_user, db_password, egeria_host,
                egeria_url, egeria_server, egeria_user, egeria_password,
                status, registered_at, error_message, group_slug
            ) VALUES (
                :slug, :display_name, :db_type, :host, :port, :description,
                :db_user, :db_password, :egeria_host,
                :egeria_url, :egeria_server, :egeria_user, :egeria_password,
                :status, :registered_at, :error_message, :group_slug
            )""", data)

    def get_server(self, slug: str) -> DatabaseServer | None:
        """Retrieve a database server by slug."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM db_servers WHERE slug = ?", (normalized,)).fetchone()
        return self._row_to_server(row) if row else None

    def list_servers(self) -> list[DatabaseServer]:
        """List all registered database servers."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM db_servers ORDER BY display_name").fetchall()
        return [self._row_to_server(r) for r in rows]

    def remove_server(self, slug: str) -> None:
        """Remove a database server and all its linked databases."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM database_surveys WHERE database_slug IN "
                "(SELECT slug FROM databases WHERE server_slug = ?)",
                (normalized,),
            )
            conn.execute("DELETE FROM databases WHERE server_slug = ?", (normalized,))
            conn.execute("DELETE FROM db_servers WHERE slug = ?", (normalized,))

    def _row_to_server(self, row: sqlite3.Row) -> DatabaseServer:
        """Convert a db_servers row to a DatabaseServer dataclass."""
        import dataclasses
        d = dict(row)
        d["status"] = ProjectStatus(d.get("status", "active"))
        known = {f.name for f in dataclasses.fields(DatabaseServer)}
        return DatabaseServer(**{k: v for k, v in d.items() if k in known})

    # ── file system entity management ──────────────────────────────────────────

    def register_filesystem(self, fs: FileSystemEntity) -> None:
        """Register a filesystem entity in the registry."""
        data = asdict(fs)
        data["slug"] = self._normalize_slug(data["slug"])
        data["status"] = data["status"].value if not isinstance(data["status"], str) else data["status"]
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO file_systems (
                    slug, display_name, local_mount_point, canonical_mount_point,
                    description, status, registered_at, last_surveyed_at,
                    egeria_asset_guid, error_message, egeria_url, egeria_server,
                    egeria_user, egeria_password, governance_state, group_slug
                ) VALUES (
                    :slug, :display_name, :local_mount_point, :canonical_mount_point,
                    :description, :status, :registered_at, :last_surveyed_at,
                    :egeria_asset_guid, :error_message, :egeria_url, :egeria_server,
                    :egeria_user, :egeria_password, :governance_state, :group_slug
                )""",
                data,
            )

    def get_filesystem(self, slug: str) -> FileSystemEntity | None:
        """Retrieve a filesystem entity by slug."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM file_systems WHERE slug = ?", (normalized,)).fetchone()
        return self._row_to_filesystem(row) if row else None

    def list_filesystems(self, governance_state: str | None = None) -> list[FileSystemEntity]:
        """List all registered filesystems, optionally filtered by governance state."""
        with self._conn() as conn:
            query = "SELECT * FROM file_systems WHERE 1=1"
            params = []
            if governance_state:
                query += " AND governance_state = ?"
                params.append(governance_state)
            query += " ORDER BY display_name"
            rows = conn.execute(query, tuple(params)).fetchall()
        return [self._row_to_filesystem(r) for r in rows]

    def filesystem_exists(self, slug: str) -> bool:
        """Check if a filesystem entity exists."""
        return self.get_filesystem(slug) is not None

    def remove_filesystem(self, slug: str) -> None:
        """Remove a filesystem and all its linked surveys."""
        normalized = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute("DELETE FROM filesystem_surveys WHERE filesystem_slug = ?", (normalized,))
            conn.execute("DELETE FROM file_systems WHERE slug = ?", (normalized,))

    def update_filesystem_status(self, slug: str, status: ProjectStatus, error_message: str = "") -> None:
        """Update status and last error message for a filesystem."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE file_systems SET status = ?, error_message = ? WHERE slug = ?",
                (status.value, error_message, self._normalize_slug(slug)),
            )

    def update_filesystem_surveyed_at(self, slug: str, surveyed_at: str) -> None:
        """Update last surveyed timestamp of a filesystem."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE file_systems SET last_surveyed_at = ? WHERE slug = ?",
                (surveyed_at, self._normalize_slug(slug)),
            )

    def set_filesystem_egeria_guid(self, slug: str, guid: str) -> None:
        """Set Egeria asset GUID for a filesystem."""
        with self._conn() as conn:
            conn.execute(
                "UPDATE file_systems SET egeria_asset_guid = ? WHERE slug = ?",
                (guid, self._normalize_slug(slug)),
            )

    def add_filesystem_survey(
        self,
        fs_slug: str,
        surveyed_at: str,
        survey_data: dict,
        egeria_report_guid: str = "",
        source: str = "local",
    ) -> None:
        """Add a survey run to the database and update file counts on the filesystem row."""
        normalized = self._normalize_slug(fs_slug)
        file_count = survey_data.get("total_files", 0)
        data_file_count = survey_data.get("total_data_files", 0)
        total_size_bytes = survey_data.get("total_size_bytes", 0)

        with self._conn() as conn:
            conn.execute(
                """INSERT INTO filesystem_surveys (
                    filesystem_slug, surveyed_at, egeria_report_guid,
                    file_count, data_file_count, total_size_bytes,
                    survey_data, source
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    normalized,
                    surveyed_at,
                    egeria_report_guid,
                    file_count,
                    data_file_count,
                    total_size_bytes,
                    json.dumps(survey_data),
                    source,
                ),
            )
            # Keep the file_systems row in sync so API responses reflect current counts
            conn.execute(
                """UPDATE file_systems
                   SET file_count = ?, data_file_count = ?, last_surveyed_at = ?
                   WHERE slug = ?""",
                (file_count, data_file_count, surveyed_at, normalized),
            )

    def get_latest_filesystem_survey(self, fs_slug: str) -> dict | None:
        """Retrieve the latest filesystem survey run."""
        normalized = self._normalize_slug(fs_slug)
        with self._conn() as conn:
            row = conn.execute(
                """SELECT * FROM filesystem_surveys
                   WHERE filesystem_slug = ?
                   ORDER BY surveyed_at DESC LIMIT 1""",
                (normalized,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["survey_data"] = _json_sanitize(json.loads(d.pop("survey_data") or "{}"))
        return d

    def list_filesystem_surveys(self, fs_slug: str) -> list[dict]:
        """List all survey runs for a filesystem ordered by timestamp."""
        normalized = self._normalize_slug(fs_slug)
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, filesystem_slug, surveyed_at, egeria_report_guid,
                          file_count, data_file_count, total_size_bytes, source, survey_data
                   FROM filesystem_surveys
                   WHERE filesystem_slug = ?
                   ORDER BY surveyed_at DESC""",
                (normalized,),
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["survey_data"] = _json_sanitize(json.loads(d.pop("survey_data") or "{}"))
            result.append(d)
        return result

    def _row_to_filesystem(self, row: sqlite3.Row) -> FileSystemEntity:
        """Convert a file_systems row to a FileSystemEntity dataclass."""
        import dataclasses
        d = dict(row)
        d["status"] = ProjectStatus(d["status"])
        known = {f.name for f in dataclasses.fields(FileSystemEntity)}
        return FileSystemEntity(**{k: v for k, v in d.items() if k in known})

    # ── activity log ──────────────────────────────────────────────────────────

    def write_activity(self, entry: ActivityEntry) -> None:
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO activity_log
                   (id, ts, operation, intent, entity_type, entity_slug,
                    entity_name, entity_location, status, summary, detail,
                    items_json, annotations_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     status=excluded.status,
                     summary=excluded.summary,
                     detail=excluded.detail,
                     items_json=excluded.items_json,
                     annotations_json=excluded.annotations_json""",
                (
                    entry.id, entry.ts, entry.operation, entry.intent,
                    entry.entity_type, entry.entity_slug, entry.entity_name,
                    entry.entity_location, entry.status, entry.summary, entry.detail,
                    json.dumps(entry.items), json.dumps(entry.annotations),
                ),
            )

    def list_activity(
        self,
        entity_type: str | None = None,
        entity_slug: str | None = None,
        intent: str | None = None,
        operation: str | None = None,
        status: str | None = None,
        since: str | None = None,
        limit: int = 200,
    ) -> list[dict]:
        filters: list[str] = []
        params: list = []
        if entity_type:
            filters.append("entity_type = ?")
            params.append(entity_type)
        if entity_slug:
            filters.append("entity_slug = ?")
            params.append(entity_slug)
        if intent:
            filters.append("intent = ?")
            params.append(intent)
        if operation:
            filters.append("operation = ?")
            params.append(operation)
        if status:
            filters.append("status = ?")
            params.append(status)
        if since:
            filters.append("ts >= ?")
            params.append(since)
        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        params.append(limit)
        with self._conn() as conn:
            rows = conn.execute(
                f"SELECT * FROM activity_log {where} ORDER BY ts DESC LIMIT ?",  # noqa: S608
                params,
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["items"] = json.loads(d.pop("items_json") or "[]")
            d["annotations"] = json.loads(d.pop("annotations_json") or "[]")
            result.append(d)
        return result

    def get_activity(self, entry_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM activity_log WHERE id = ?", (entry_id,)
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        d["items"] = json.loads(d.pop("items_json") or "[]")
        d["annotations"] = json.loads(d.pop("annotations_json") or "[]")
        return d

    def update_activity_status(
        self,
        entry_id: str,
        status: str,
        summary: str = "",
        detail: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "UPDATE activity_log SET status = ?, "
                "summary = CASE WHEN ? != '' THEN ? ELSE summary END, "
                "detail  = CASE WHEN ? != '' THEN ? ELSE detail  END "
                "WHERE id = ?",
                (status, summary, summary, detail, detail, entry_id),
            )

    # ── RFA actions (local response tracking — see PATCH /api/activity/rfas/{rfa_id}
    # in web/routes/activity.py) ─────────────────────────────────────────────
    #
    # RFAs themselves aren't first-class rows — GET /rfas flattens
    # RequestForAction-tagged entries out of each activity_log row's
    # annotations_json at read time. This table is keyed on the same
    # synthetic id that flatten step mints positionally
    # (f"{entry_id}::{annotation_index}"), and overlays a real, updatable
    # status/assignee/defer/resolution onto each flattened RFA. This is a
    # stepping stone toward real Egeria ToDo/governance actions, not that
    # integration itself — full alignment with Egeria's native action model
    # is deliberately out of scope for this slice. See
    # docs/rfa-egeria-todo-followup.md for what that integration would
    # actually require, confirmed against pyegeria's real ToDo/PersonAction
    # API (assign_action/reassign_action/add_action_target) — not built yet.

    def upsert_rfa_action(
        self,
        rfa_id: str,
        entry_id: str,
        annotation_index: int,
        status: str,
        assignee: str = "",
        defer_until: str = "",
        resolution_note: str = "",
    ) -> None:
        updated_at = datetime.now(timezone.utc).isoformat()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO rfa_actions
                   (id, entry_id, annotation_index, rfa_status, assignee, defer_until, resolution_note, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     rfa_status=excluded.rfa_status,
                     assignee=excluded.assignee,
                     defer_until=excluded.defer_until,
                     resolution_note=excluded.resolution_note,
                     updated_at=excluded.updated_at""",
                (rfa_id, entry_id, annotation_index, status, assignee, defer_until, resolution_note, updated_at),
            )

    def get_rfa_action(self, rfa_id: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM rfa_actions WHERE id = ?", (rfa_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_rfa_action_overrides(self) -> dict[str, dict]:
        """All rfa_actions rows, keyed by id — used to overlay live status
        onto the read-time-flattened RFA list without a per-row query."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM rfa_actions").fetchall()
        return {r["id"]: dict(r) for r in rows}

    def update_governance_state(self, entity_type: str, slug: str, state: str) -> None:
        """Update the governance state of a registered resource."""
        slug = self._normalize_slug(slug)
        table_map = {
            "repo": "projects",
            "database": "databases",
            "filesystem": "file_systems"
        }
        table = table_map.get(entity_type)
        if not table:
            raise ValueError(f"Unknown entity_type: {entity_type}")
        with self._conn() as conn:
            conn.execute(f"UPDATE {table} SET governance_state = ? WHERE slug = ?", (state, slug))

    def list_annotation_types(self) -> list[dict]:
        """List all annotation types in the registry."""
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT annotation_type, display_name, description, properties, egeria_type, python_class
                   FROM annotation_types
                   ORDER BY annotation_type"""
            ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            try:
                d["properties"] = json.loads(d["properties"] or "[]")
            except Exception:
                d["properties"] = []
            result.append(d)
        return result

    def get_annotation_type(self, annotation_type: str) -> dict | None:
        """Get a single annotation type by name."""
        with self._conn() as conn:
            row = conn.execute(
                """SELECT annotation_type, display_name, description, properties, egeria_type, python_class
                   FROM annotation_types
                   WHERE annotation_type = ?""",
                (annotation_type,),
            ).fetchone()
        if not row:
            return None
        d = dict(row)
        try:
            d["properties"] = json.loads(d["properties"] or "[]")
        except Exception:
            d["properties"] = []
        return d

    def register_annotation_type(
        self,
        annotation_type: str,
        display_name: str,
        description: str = "",
        properties: list[str] | str = "[]",
        egeria_type: str = "",
        python_class: str = "",
    ) -> None:
        """Register a new annotation type."""
        if isinstance(properties, list):
            properties_str = json.dumps(properties)
        else:
            properties_str = properties
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO annotation_types (
                    annotation_type, display_name, description, properties, egeria_type, python_class
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (annotation_type, display_name, description, properties_str, egeria_type, python_class),
            )

    def update_annotation_type(
        self,
        annotation_type: str,
        display_name: str,
        description: str = "",
        properties: list[str] | str = "[]",
        egeria_type: str = "",
        python_class: str = "",
    ) -> None:
        """Update an existing annotation type."""
        if isinstance(properties, list):
            properties_str = json.dumps(properties)
        else:
            properties_str = properties
        with self._conn() as conn:
            conn.execute(
                """UPDATE annotation_types
                   SET display_name = ?, description = ?, properties = ?, egeria_type = ?, python_class = ?
                   WHERE annotation_type = ?""",
                (display_name, description, properties_str, egeria_type, python_class, annotation_type),
            )

    def delete_annotation_type(self, annotation_type: str) -> None:
        """Delete an annotation type from the registry."""
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM annotation_types WHERE annotation_type = ?",
                (annotation_type,),
            )

    # ── project group management ─────────────────────────────────────────────

    def create_group(self, slug: str, display_name: str, description: str = "") -> None:
        """Create (or rename) an umbrella project group."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO project_groups (slug, display_name, description, created_at) "
                "VALUES (?, ?, ?, ?) "
                "ON CONFLICT (slug) DO UPDATE SET "
                "display_name = excluded.display_name, description = excluded.description, "
                "created_at = excluded.created_at",
                (slug, display_name, description, datetime.utcnow().isoformat()),
            )

    def get_group(self, slug: str) -> ProjectGroup | None:
        """Retrieve a project group by slug."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM project_groups WHERE slug = ?", (slug,)).fetchone()
        return ProjectGroup(**dict(row)) if row else None

    def list_groups(self) -> list[ProjectGroup]:
        """List all project groups."""
        with self._conn() as conn:
            rows = conn.execute("SELECT * FROM project_groups ORDER BY display_name").fetchall()
        return [ProjectGroup(**dict(r)) for r in rows]

    def delete_group(self, slug: str) -> int:
        """Delete a group. Member resources are ungrouped, not removed."""
        slug = self._normalize_slug(slug)
        with self._conn() as conn:
            # Ungroup all resources in this group
            conn.execute("UPDATE projects SET group_slug = '' WHERE group_slug = ?", (slug,))
            conn.execute("UPDATE databases SET group_slug = '' WHERE group_slug = ?", (slug,))
            conn.execute("UPDATE file_systems SET group_slug = '' WHERE group_slug = ?", (slug,))
            cursor = conn.execute("DELETE FROM project_groups WHERE slug = ?", (slug,))
            return cursor.rowcount

    def set_project_group(self, project_slug: str, group_slug: str) -> None:
        """Assign a repository to a group."""
        project_slug = self._normalize_slug(project_slug)
        group_slug = self._normalize_slug(group_slug) if group_slug else ""
        with self._conn() as conn:
            conn.execute("UPDATE projects SET group_slug = ? WHERE slug = ?", (group_slug, project_slug))

    def set_database_group(self, database_slug: str, group_slug: str) -> None:
        """Assign a database to a group."""
        database_slug = self._normalize_slug(database_slug)
        group_slug = self._normalize_slug(group_slug) if group_slug else ""
        with self._conn() as conn:
            conn.execute("UPDATE databases SET group_slug = ? WHERE slug = ?", (group_slug, database_slug))

    def set_filesystem_group(self, filesystem_slug: str, group_slug: str) -> None:
        """Assign a filesystem to a group."""
        filesystem_slug = self._normalize_slug(filesystem_slug)
        group_slug = self._normalize_slug(group_slug) if group_slug else ""
        with self._conn() as conn:
            conn.execute("UPDATE file_systems SET group_slug = ? WHERE slug = ?", (group_slug, filesystem_slug))

    def list_projects_in_group(self, group_slug: str) -> list[Project]:
        """List all repositories assigned to a group."""
        group_slug = self._normalize_slug(group_slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE group_slug = ? ORDER BY display_name",
                (group_slug,),
            ).fetchall()
        return [self._row_to_project(r) for r in rows]

    def list_databases_in_group(self, group_slug: str) -> list[DatabaseEntity]:
        """List all databases assigned to a group."""
        group_slug = self._normalize_slug(group_slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM databases WHERE group_slug = ? ORDER BY display_name",
                (group_slug,),
            ).fetchall()
        return [self._row_to_database(r) for r in rows]

    def list_filesystems_in_group(self, group_slug: str) -> list[FileSystemEntity]:
        """List all filesystems assigned to a group."""
        group_slug = self._normalize_slug(group_slug)
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM file_systems WHERE group_slug = ? ORDER BY display_name",
                (group_slug,),
            ).fetchall()
        return [self._row_to_filesystem(r) for r in rows]

    def get_group_aggregate_stats(self, group_slug: str) -> dict:
        """Sum the latest stats snapshot across every member of a group."""
        group_slug = self._normalize_slug(group_slug)
        repos = self.list_projects_in_group(group_slug)
        dbs = self.list_databases_in_group(group_slug)
        fss = self.list_filesystems_in_group(group_slug)

        totals = {
            "project_count": len(repos),
            "database_count": len(dbs),
            "filesystem_count": len(fss),
            "stars": 0, "forks": 0, "watchers": 0, "open_issues": 0,
            "commits_30d": 0, "commits_90d": 0,
            "contributors_count": 0,
            "languages": {},
            "db_schema_count": 0, "db_table_count": 0, "db_column_count": 0,
            "fs_file_count": 0, "fs_data_file_count": 0,
        }
        for r in repos:
            snap = self.get_latest_project_stats(r.slug)
            if snap:
                for key in ("stars", "forks", "watchers", "open_issues", "commits_30d", "commits_90d"):
                    totals[key] += snap.get(key) or 0
                totals["contributors_count"] = max(totals["contributors_count"], snap.get("contributors_count") or 0)
                lang = snap.get("primary_language")
                if lang:
                    totals["languages"][lang] = totals["languages"].get(lang, 0) + 1
        
        for db in dbs:
            totals["db_schema_count"] += getattr(db, "schema_count", 0) or 0
            totals["db_table_count"] += getattr(db, "table_count", 0) or 0
            totals["db_column_count"] += getattr(db, "column_count", 0) or 0

        for fs in fss:
            totals["fs_file_count"] += getattr(fs, "file_count", 0) or 0
            totals["fs_data_file_count"] += getattr(fs, "data_file_count", 0) or 0

        return totals
