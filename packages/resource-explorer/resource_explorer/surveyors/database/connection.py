"""Database connection abstraction for different database types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Any

from resource_explorer.registry import DatabaseEntity


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

    def get_statistics(self) -> dict:
        """Get database statistics."""
        stats = {
            "database_size": self._get_database_size(),
            "table_stats": self._get_table_statistics(),
            "row_stats": self._get_table_row_stats(),
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

