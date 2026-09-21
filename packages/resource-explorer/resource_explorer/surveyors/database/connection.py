"""Database connection abstraction for different database types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Any

from resource_explorer.registry import DatabaseEntity


@dataclass(frozen=True)
class EngineCapabilities:
    """What this connection's engine can report, declared per capability
    rather than as one blanket "native support" flag.

    Design doc §5.1: "the connection layer gains a capability declaration per
    engine (`supports: {column_stats, tuple_counters, replication_status,
    query_stats, ...}`), and each catalog-fed analysis states which capability
    it needs. A finding whose capability is absent is `not_established`, not
    `nothing_found`."

    Only the capabilities a build actually extracts are declared True.
    `replication_status`, `query_stats`, `resilience` and
    `external_dependencies` stay False on every engine as of this slice — no
    step reads `pg_stat_replication`, `pg_stat_statements`, backup evidence or
    FDWs/publications yet (Phase 1 slices 8/9 in
    `COORDINATOR-BRIEF-MULTI-RESOURCE.md` add those). Declaring them True here
    ahead of any code that reads them would make "not yet implemented"
    indistinguishable from "measured, and there was nothing" — the exact
    collapse this field exists to prevent.
    """

    column_stats: bool = False
    tuple_counters: bool = False
    index_stats: bool = False
    replication_status: bool = False
    query_stats: bool = False
    resilience: bool = False
    external_dependencies: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


#: No capability beyond the generic information_schema reads every
#: DatabaseConnection subclass already does via get_schema_info(). The
#: default for any engine that has not declared otherwise.
NO_CAPABILITIES = EngineCapabilities()


class DatabaseConnection(ABC):
    """Abstract base class for database connections."""

    @abstractmethod
    def connect(self) -> Any:
        """Establish connection to the database."""

    @abstractmethod
    def execute_query(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return results as list of dicts."""

    @abstractmethod
    def get_schema_info(self) -> dict:
        """Get database schema information (schemas, tables, columns)."""

    @abstractmethod
    def get_statistics(self) -> dict:
        """Get database statistics (row counts, sizes, etc.)."""

    @abstractmethod
    def close(self) -> None:
        """Close the connection."""

    @property
    def capabilities(self) -> EngineCapabilities:
        """This engine's capability declaration (design §5.1).

        Not abstract: an engine that adds no capability beyond the schema
        read needs no boilerplate override, and a caller that has not been
        taught about a given engine gets an honest "nothing declared" rather
        than an AttributeError.
        """
        return NO_CAPABILITIES


class PostgreSQLConnection(DatabaseConnection):
    """PostgreSQL-specific connection implementation."""

    def __init__(
        self,
        host: str,
        port: int,
        database: str,
        user: str,
        password: str,
    ) -> None:
        self.host = host
        self.port = port
        self.database = database
        self.user = user
        self.password = password
        self._conn = None

    def connect(self) -> Any:
        """Establish PostgreSQL connection."""
        try:
            import psycopg2
        except ImportError as e:
            raise ImportError(
                "psycopg2 is required for PostgreSQL connections. "
                "Install it with: pip install psycopg2-binary"
            ) from e

        self._conn = psycopg2.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            user=self.user,
            password=self.password,
        )
        return self._conn

    def execute_query(self, query: str, params: tuple = ()) -> list[dict]:
        """Execute a query and return results as list of dicts."""
        if not self._conn:
            raise RuntimeError("Not connected to database")

        with self._conn.cursor() as cur:
            cur.execute(query, params)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                return [dict(zip(columns, row)) for row in cur.fetchall()]
            return []

    def get_schema_info(self) -> dict:
        """Get PostgreSQL schema information."""
        # Query information_schema for schemas (excluding system schemas)
        schemas_query = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schema_name
        """
        schemas = self.execute_query(schemas_query)
        schema_descriptions = self._get_schema_descriptions()

        result = {"schemas": [], "total_tables": 0, "total_columns": 0}
        for schema in schemas:
            schema_name = schema["schema_name"]
            tables = self._get_tables_for_schema(schema_name)
            result["schemas"].append({
                "name": schema_name,
                "description": schema_descriptions.get(schema_name, ""),
                "tables": tables,
            })
            result["total_tables"] += len(tables)
            result["total_columns"] += sum(len(t["columns"]) for t in tables)

        return result

    def _get_schema_descriptions(self) -> dict[str, str]:
        """Return {schema_name: description} from pg_namespace."""
        try:
            rows = self.execute_query("""
                SELECT n.nspname AS schema_name,
                       obj_description(n.oid, 'pg_namespace') AS description
                FROM pg_namespace n
                WHERE n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
                ORDER BY n.nspname
            """)
            return {r["schema_name"]: r.get("description") or "" for r in rows}
        except Exception:
            return {}

    def _get_tables_for_schema(self, schema_name: str) -> list[dict]:
        """Get tables and columns for a schema, including PK/FK info and pg_description comments."""
        # Get primary keys for the schema
        pk_query = """
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name
                AND tc.table_schema = kcu.table_schema
            WHERE tc.constraint_type = 'PRIMARY KEY'
            AND tc.table_schema = %s
        """
        pk_rows = self.execute_query(pk_query, (schema_name,))
        pk_lookup: dict[str, set] = {}
        for r in pk_rows:
            pk_lookup.setdefault(r["table_name"], set()).add(r["column_name"])

        # Get foreign keys for the schema
        fk_query = """
            SELECT
                kcu.table_name, kcu.column_name,
                ccu.table_schema AS foreign_schema,
                ccu.table_name AS foreign_table,
                ccu.column_name AS foreign_column
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON tc.constraint_name = kcu.constraint_name AND tc.table_schema = kcu.table_schema
            JOIN information_schema.constraint_column_usage ccu
                ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema
            WHERE tc.constraint_type = 'FOREIGN KEY'
            AND tc.table_schema = %s
        """
        fk_rows = self.execute_query(fk_query, (schema_name,))
        fk_lookup: dict[tuple, dict] = {}
        for r in fk_rows:
            fk_lookup[(r["table_name"], r["column_name"])] = {
                "foreign_schema": r["foreign_schema"],
                "foreign_table": r["foreign_table"],
                "foreign_column": r["foreign_column"],
            }

        # Main query: tables + columns with descriptions
        query = """
            SELECT
                t.table_name,
                t.table_type,
                obj_description(
                    (quote_ident(t.table_schema)||'.'||quote_ident(t.table_name))::regclass,
                    'pg_class'
                ) AS table_description,
                c.column_name,
                c.data_type,
                c.udt_name,
                c.is_nullable,
                c.column_default,
                c.ordinal_position,
                c.character_maximum_length,
                c.numeric_precision,
                c.numeric_scale,
                col_description(
                    (quote_ident(t.table_schema)||'.'||quote_ident(t.table_name))::regclass,
                    c.ordinal_position
                ) AS column_description
            FROM information_schema.tables t
            LEFT JOIN information_schema.columns c
                ON t.table_name = c.table_name AND t.table_schema = c.table_schema
            WHERE t.table_schema = %s
            ORDER BY t.table_name, c.ordinal_position
        """
        rows = self.execute_query(query, (schema_name,))

        tables: dict[str, dict] = {}
        for row in rows:
            table_name = row["table_name"]
            if table_name not in tables:
                tables[table_name] = {
                    "name": table_name,
                    "type": row["table_type"],
                    "description": row.get("table_description") or "",
                    "columns": [],
                }
            if row["column_name"]:
                col_name = row["column_name"]
                is_pk = col_name in pk_lookup.get(table_name, set())
                fk = fk_lookup.get((table_name, col_name))

                # Build a human-friendly type display
                data_type = row["data_type"] or ""
                max_len = row.get("character_maximum_length")
                num_prec = row.get("numeric_precision")
                num_scale = row.get("numeric_scale")
                if max_len:
                    type_display = f"{data_type}({max_len})"
                elif num_prec and num_scale:
                    type_display = f"{data_type}({num_prec},{num_scale})"
                elif num_prec:
                    type_display = f"{data_type}({num_prec})"
                else:
                    type_display = data_type

                tables[table_name]["columns"].append({
                    "name": col_name,
                    "type": type_display,
                    "base_type": data_type,
                    "nullable": row["is_nullable"] == "YES",
                    "default": row.get("column_default"),
                    "position": row["ordinal_position"],
                    "description": row.get("column_description") or "",
                    "is_primary_key": is_pk,
                    "foreign_key": fk,
                })

        return list(tables.values())

    def list_databases(self) -> list[dict]:
        """List all databases on this server that the current user can connect to."""
        query = """
            SELECT
                d.datname                                    AS name,
                pg_size_pretty(pg_database_size(d.datname)) AS size_pretty,
                pg_database_size(d.datname)                 AS size_bytes,
                d.datdba::regrole::text                     AS owner,
                shobj_description(d.oid, 'pg_database')     AS description,
                pg_encoding_to_char(d.encoding)             AS encoding
            FROM pg_database d
            WHERE d.datistemplate = false
            AND has_database_privilege(d.datname, 'CONNECT')
            ORDER BY d.datname
        """
        try:
            rows = self.execute_query(query)
            result = []
            for r in rows:
                result.append({
                    "name": r["name"],
                    "size_pretty": r.get("size_pretty") or "",
                    "size_bytes": int(r.get("size_bytes") or 0),
                    "owner": r.get("owner") or "",
                    "description": r.get("description") or "",
                    "encoding": r.get("encoding") or "",
                })
            return result
        except Exception as e:
            raise RuntimeError(f"Could not list databases: {e}") from e

    @property
    def capabilities(self) -> EngineCapabilities:
        """Postgres declares the three capabilities this slice extracts.

        `replication_status`/`query_stats`/`resilience`/`external_dependencies`
        stay False deliberately — see EngineCapabilities' docstring. Postgres
        genuinely has `pg_stat_replication` etc. available, but nothing in
        this class reads them yet, so declaring True would be a promise this
        code does not keep.
        """
        return EngineCapabilities(
            column_stats=True,
            tuple_counters=True,
            index_stats=True,
        )

    def get_column_stats(self) -> list[dict]:
        """Per-column `pg_stats` — populated only after `ANALYZE` has run.

        Design §5.1: null_frac, n_distinct, most_common_vals,
        most_common_freqs, histogram_bounds, avg_width, correlation — column
        profiling without sampling.

        A column with no matching row here has not been measured as "having
        no values" — it has never been analyzed. That distinction is made by
        the caller, which knows the full column catalog from
        `get_schema_info()` and can tell "in the catalog, absent from
        pg_stats" from "genuinely profiled". This method only reports what
        pg_stats has; it never fabricates a row for a column ANALYZE has not
        reached.
        """
        query = """
            SELECT
                schemaname, tablename, attname,
                null_frac, n_distinct, avg_width, correlation,
                most_common_vals::text  AS most_common_vals,
                most_common_freqs::text AS most_common_freqs,
                histogram_bounds::text  AS histogram_bounds
            FROM pg_stats
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY schemaname, tablename, attname
        """
        try:
            return self.execute_query(query)
        except Exception:
            return []

    def get_table_activity(self) -> list[dict]:
        """Per-table tuple counters, live/dead rows, scan counts and
        vacuum/analyze recency from `pg_stat_user_tables` (design §5.1) —
        the full set `database_table_activity` has columns for, not just the
        row-count/last-analyzed subset `_get_table_row_stats` already feeds
        into `schema_info` for display.

        A table absent from this result (present in the catalog but missing
        here) has not been reported as inactive — Postgres has not
        accumulated a statistics-collector row for it yet, which is rare but
        distinct from "zero activity" (a real row with all-zero counters).
        """
        query = """
            SELECT
                schemaname, relname AS tablename,
                n_tup_ins, n_tup_upd, n_tup_del, n_tup_hot_upd,
                n_live_tup, n_dead_tup,
                seq_scan, idx_scan,
                last_vacuum, last_autovacuum, last_analyze, last_autoanalyze,
                n_mod_since_analyze AS pending_changes
            FROM pg_stat_user_tables
            ORDER BY schemaname, relname
        """
        try:
            rows = self.execute_query(query)
        except Exception:
            return []
        result = []
        for r in rows:
            result.append({
                "schemaname": r.get("schemaname", ""),
                "tablename": r.get("tablename", ""),
                "rows_inserted": r.get("n_tup_ins"),
                "rows_updated": r.get("n_tup_upd"),
                "rows_deleted": r.get("n_tup_del"),
                "hot_updates": r.get("n_tup_hot_upd"),
                "live_tuples": r.get("n_live_tup"),
                "dead_tuples": r.get("n_dead_tup"),
                "seq_scan": r.get("seq_scan"),
                "idx_scan": r.get("idx_scan"),
                "last_vacuum": str(r["last_vacuum"]) if r.get("last_vacuum") else "",
                "last_autovacuum": str(r["last_autovacuum"]) if r.get("last_autovacuum") else "",
                "last_analyze": str(r["last_analyze"]) if r.get("last_analyze") else "",
                "last_autoanalyze": str(r["last_autoanalyze"]) if r.get("last_autoanalyze") else "",
                "pending_changes": r.get("pending_changes"),
            })
        return result

    def get_stats_reset(self) -> str:
        """When `pg_stat_database` last reset this database's counters.

        The evidence `database_table_activity.stats_reset` exists to carry
        (see `result_materializer.py`'s identical comment on the native
        path) — a change comparator (design §9.1, Phase 1 slice 14) needs
        this to tell a real rate from the negative delta a reset produces.
        """
        try:
            rows = self.execute_query(
                "SELECT stats_reset FROM pg_stat_database WHERE datname = current_database()"
            )
            value = rows[0].get("stats_reset") if rows else None
            return str(value) if value else ""
        except Exception:
            return ""

    def get_index_stats(self) -> list[dict]:
        """Per-index usage from `pg_stat_user_indexes`, joined to `pg_index`
        for uniqueness/primary-key — design §5.1's "index usage and
        unused-index detection".

        `idx_scan == 0` is the unused-index signal, with the same staleness
        caveat as the tuple counters: it is a count since the last stats
        reset (`get_stats_reset()`), not since the index was created.
        """
        query = """
            SELECT
                s.schemaname, s.relname AS tablename, s.indexrelname,
                s.idx_scan, s.idx_tup_read, s.idx_tup_fetch,
                i.indisunique  AS is_unique,
                i.indisprimary AS is_primary,
                pg_relation_size(s.indexrelid) AS index_size_bytes
            FROM pg_stat_user_indexes s
            JOIN pg_index i ON i.indexrelid = s.indexrelid
            ORDER BY s.schemaname, s.relname, s.indexrelname
        """
        try:
            return self.execute_query(query)
        except Exception:
            return []

    def get_statistics(self) -> dict:
        """Get database statistics."""
        stats = {
            "database_size": self._get_database_size(),
            "table_stats": self._get_table_statistics(),
            "row_stats": self._get_table_row_stats(),
            "column_stats": self.get_column_stats(),
            "table_activity": self.get_table_activity(),
            "index_stats": self.get_index_stats(),
            "stats_reset": self.get_stats_reset(),
        }
        return stats

    def _get_database_size(self) -> dict:
        """Get database size information."""
        query = """
            SELECT 
                pg_database_size(current_database()) as size_bytes,
                pg_size_pretty(pg_database_size(current_database())) as size_pretty
        """
        result = self.execute_query(query)
        return result[0] if result else {"size_bytes": 0, "size_pretty": "0 bytes"}

    def _get_table_statistics(self) -> list[dict]:
        """Get statistics for all tables."""
        query = """
            SELECT 
                schemaname,
                tablename,
                pg_total_relation_size(quote_ident(schemaname)||'.'||quote_ident(tablename)) as total_bytes,
                pg_size_pretty(pg_total_relation_size(quote_ident(schemaname)||'.'||quote_ident(tablename))) as total_size
            FROM pg_tables
            WHERE schemaname NOT IN ('pg_catalog', 'information_schema')
              AND has_schema_privilege(schemaname, 'USAGE')
            ORDER BY total_bytes DESC
            LIMIT 100
        """
        return self.execute_query(query)

    def _get_table_row_stats(self) -> list[dict]:
        """Get row counts and last-activity timestamps from pg_stat_user_tables."""
        query = """
            SELECT
                schemaname,
                relname                                              AS tablename,
                n_live_tup                                          AS row_count,
                GREATEST(last_analyze, last_autoanalyze)            AS last_analyzed,
                GREATEST(last_vacuum,  last_autovacuum)             AS last_vacuumed,
                n_mod_since_analyze                                  AS pending_changes
            FROM pg_stat_user_tables
            ORDER BY schemaname, relname
        """
        try:
            rows = self.execute_query(query)
            # Cast timestamps to ISO strings so they survive JSON serialisation
            result = []
            for r in rows:
                result.append({
                    "schemaname": r.get("schemaname", ""),
                    "tablename":  r.get("tablename", ""),
                    "row_count":  int(r.get("row_count") or 0),
                    "last_analyzed": str(r["last_analyzed"]) if r.get("last_analyzed") else "",
                    "last_vacuumed": str(r["last_vacuumed"]) if r.get("last_vacuumed") else "",
                    "pending_changes": int(r.get("pending_changes") or 0),
                })
            return result
        except Exception:
            return []

    def close(self) -> None:
        """Close the PostgreSQL connection."""
        if self._conn:
            self._conn.close()
            self._conn = None


@contextmanager
def server_connection(host: str, port: int, user: str, password: str, db_type: str = "postgresql"):
    """Context manager for connecting to a database server (uses 'postgres' DB to list databases).

    Args:
        host: Server hostname
        port: Server port
        user: Database user
        password: Database password
        db_type: Database type (only 'postgresql' supported)

    Yields:
        PostgreSQLConnection connected to the 'postgres' system database
    """
    if db_type == "postgresql":
        conn = PostgreSQLConnection(
            host=host,
            port=port,
            database="postgres",  # system DB to list all databases
            user=user,
            password=password,
        )
    else:
        raise ValueError(f"Unsupported database type: {db_type}")

    try:
        conn.connect()
        yield conn
    finally:
        conn.close()


@contextmanager
def database_connection(db_entity: DatabaseEntity, credentials: dict):
    """Context manager for database connections.
    
    Args:
        db_entity: DatabaseEntity with connection details
        credentials: Dict with 'user' and 'password' keys
        
    Yields:
        DatabaseConnection instance
        
    Example:
        with database_connection(db_entity, {"user": "admin", "password": "secret"}) as conn:
            schema = conn.get_schema_info()
    """
    if db_entity.db_type == "postgresql":
        if not credentials.get("user") or not credentials.get("password"):
            raise ValueError(
                "Database credentials are required to connect ('user'/'password' both "
                "missing or empty) — there is no other fallback (env vars, config) inside "
                "this function; callers must resolve credentials themselves first "
                "(e.g. from DatabaseEntity.db_user/db_password)."
            )
        conn = PostgreSQLConnection(
            host=db_entity.host,
            port=db_entity.port,
            database=db_entity.database_name,
            user=credentials["user"],
            password=credentials["password"],
        )
    else:
        raise ValueError(f"Unsupported database type: {db_entity.db_type}")

    try:
        conn.connect()
        yield conn
    finally:
        conn.close()

