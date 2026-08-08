"""
pgvector (PostgreSQL) vector store backend for Egeria Advisor.
"""

import json
import math
import re
import threading
from typing import List, Dict, Any, Optional

import numpy as np
import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool
from pgvector.psycopg2 import register_vector
from loguru import logger

from advisor.config import settings
from advisor.embeddings import get_embedding_generator
from advisor.vector_store_base import BaseVectorStore, SearchResult


# ---------------------------------------------------------------------------
# Per-collection DDL
# ---------------------------------------------------------------------------

_BASE_DDL = """
    CREATE TABLE IF NOT EXISTS "{name}" (
        id        VARCHAR(256) PRIMARY KEY,
        embedding vector(384)  NOT NULL,
        text      TEXT         NOT NULL,
        metadata  JSONB        NOT NULL DEFAULT '{{}}'
    )
"""

_TABLE_DDL: Dict[str, str] = {
    "pyegeria": """
        CREATE TABLE IF NOT EXISTS "pyegeria" (
            id           VARCHAR(256) PRIMARY KEY,
            embedding    vector(384)  NOT NULL,
            text         TEXT         NOT NULL,
            metadata     JSONB        NOT NULL DEFAULT '{}',
            element_type VARCHAR(50)  NOT NULL DEFAULT '',
            class_name   VARCHAR(200) NOT NULL DEFAULT '',
            method_name  VARCHAR(200) NOT NULL DEFAULT '',
            module_path  VARCHAR(500) NOT NULL DEFAULT '',
            is_async     BOOLEAN      NOT NULL DEFAULT FALSE,
            is_private   BOOLEAN      NOT NULL DEFAULT FALSE
        )
    """,
    "pyegeria_cli": """
        CREATE TABLE IF NOT EXISTS "pyegeria_cli" (
            id           VARCHAR(256) PRIMARY KEY,
            embedding    vector(384)  NOT NULL,
            text         TEXT         NOT NULL,
            metadata     JSONB        NOT NULL DEFAULT '{}',
            main_command VARCHAR(100) NOT NULL DEFAULT '',
            subcommand   VARCHAR(200) NOT NULL DEFAULT '',
            full_command VARCHAR(500) NOT NULL DEFAULT ''
        )
    """,
}

# Extra scalar columns present in each collection (order must match INSERT)
_EXTRA_COLUMNS: Dict[str, List[str]] = {
    "pyegeria": ["element_type", "class_name", "method_name", "module_path", "is_async", "is_private"],
    "pyegeria_cli": ["main_command", "subcommand", "full_command"],
}

# Canonical name map: collection config names → pgvector table names.
# Handles the mixed-case legacy name and the old CLI collection name.
_TABLE_NAME_MAP: Dict[str, str] = {
    "pyegeria_drE": "pyegeria_dre",
    "cli_commands": "pyegeria_cli",
}

# Default values for extra scalar columns
_COL_DEFAULTS: Dict[str, Any] = {
    "element_type": "",
    "class_name": "",
    "method_name": "",
    "module_path": "",
    "main_command": "",
    "subcommand": "",
    "full_command": "",
    "is_async": False,
    "is_private": False,
}


class PgVectorStore(BaseVectorStore):
    """pgvector implementation of BaseVectorStore."""

    def __init__(
        self,
        host: Optional[str] = None,
        port: Optional[int] = None,
        dbname: Optional[str] = None,
        user: Optional[str] = None,
        password: Optional[str] = None,
        max_connections: Optional[int] = None,
        ef_search: Optional[int] = None,
    ):
        self.host = host or settings.pgvector_host
        self.port = port or settings.pgvector_port
        self.dbname = dbname or settings.pgvector_dbname
        self.user = user or settings.pgvector_user
        self.password = password or settings.pgvector_password
        self._max_connections = max_connections or settings.pgvector_max_connections
        self._ef_search = ef_search or settings.pgvector_ef_search

        self.embedding_generator = get_embedding_generator()
        self._pool: Optional[ThreadedConnectionPool] = None
        self._connect_lock = threading.Lock()

        logger.info(f"Initialized PgVectorStore for {self.host}:{self.port}/{self.dbname}")

    @staticmethod
    def _table(collection_name: str) -> str:
        """Normalise collection name to the canonical pgvector table name."""
        return _TABLE_NAME_MAP.get(collection_name, collection_name)

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._pool is not None:
            return
        with self._connect_lock:
            if self._pool is not None:  # re-check inside lock
                return
            try:
                logger.info(f"Connecting to pgvector at {self.host}:{self.port}/{self.dbname}")
                self._pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=self._max_connections,
                    host=self.host,
                    port=self.port,
                    dbname=self.dbname,
                    user=self.user,
                    password=self.password,
                )
                # Ensure the vector extension exists (once per pool creation)
                with psycopg2.connect(
                    host=self.host, port=self.port, dbname=self.dbname,
                    user=self.user, password=self.password,
                ) as bootstrap:
                    self._ensure_extension(bootstrap)
                logger.info(f"✓ Connected to pgvector at {self.host}:{self.port}/{self.dbname}")
            except Exception as e:
                logger.error(f"Failed to connect to pgvector: {e}")
                raise

    def disconnect(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            logger.info("Disconnected from pgvector")

    def is_connected(self) -> bool:
        return self._pool is not None

    def _get_conn(self) -> psycopg2.extensions.connection:
        """Borrow a connection from the pool and register the vector type."""
        conn = self._pool.getconn()
        register_vector(conn)
        # Set ef_search for this session to improve HNSW recall
        with conn.cursor() as cur:
            cur.execute(f"SET hnsw.ef_search = {self._ef_search}")
        return conn

    def _put_conn(self, conn: psycopg2.extensions.connection) -> None:
        self._pool.putconn(conn)

    @staticmethod
    def _ensure_extension(conn: psycopg2.extensions.connection) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()

    # ------------------------------------------------------------------
    # Collection (table) management
    # ------------------------------------------------------------------

    def create_collection(
        self,
        collection_name: str,
        description: str = "",
        drop_if_exists: bool = False,
        extra_fields: Optional[Any] = None,
    ) -> str:
        collection_name = self._table(collection_name)
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if drop_if_exists:
                    cur.execute(f'DROP TABLE IF EXISTS "{collection_name}" CASCADE')
                    logger.warning(f"Dropped table: {collection_name}")

                ddl = _TABLE_DDL.get(collection_name) or _BASE_DDL.format(name=collection_name)
                cur.execute(ddl)
            conn.commit()
            logger.info(f"✓ Created/verified table: {collection_name}")
        finally:
            self._put_conn(conn)
        return collection_name

    def create_index(
        self,
        collection_name: str,
        index_type: str = "HNSW",
        metric_type: str = "L2",
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Create an HNSW index on the embedding column."""
        collection_name = self._table(collection_name)
        self.connect()

        ops = "vector_l2_ops" if metric_type.upper() == "L2" else "vector_cosine_ops"
        m = (params or {}).get("m", 16)
        ef_construction = (params or {}).get("ef_construction", 64)
        index_name = f"{collection_name}_embedding_idx"

        sql = (
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{collection_name}" '
            f"USING hnsw (embedding {ops}) "
            f"WITH (m = {m}, ef_construction = {ef_construction})"
        )

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            logger.info(f"✓ Created HNSW index on {collection_name} (m={m}, ef_construction={ef_construction})")
        finally:
            self._put_conn(conn)

    def _table_exists(self, collection_name: str) -> bool:
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    (collection_name,),
                )
                return cur.fetchone() is not None
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # Data insertion
    # ------------------------------------------------------------------

    def insert_data(
        self,
        collection_name: str,
        texts: List[str],
        ids: Optional[List[str]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1000,
    ) -> int:
        collection_name = self._table(collection_name)
        self.connect()

        if ids is None:
            ids = [f"{collection_name}_{i}" for i in range(len(texts))]
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]

        if len(texts) != len(ids) or len(texts) != len(metadata):
            raise ValueError("texts, ids, and metadata must have the same length")

        logger.info(f"Generating embeddings for {len(texts)} texts...")
        embeddings = self.embedding_generator.encode_batch(texts, show_progress=True)

        extra_cols = _EXTRA_COLUMNS.get(collection_name, [])
        all_cols = ["id", "embedding", "text", "metadata"] + extra_cols

        quoted_cols = ", ".join(f'"{c}"' for c in all_cols)
        upsert_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"'
            for c in all_cols if c != "id"
        )
        # execute_values uses a single %s as the VALUES placeholder (one tuple per row)
        sql = (
            f'INSERT INTO "{collection_name}" ({quoted_cols}) '
            f"VALUES %s "
            f"ON CONFLICT (id) DO UPDATE SET {upsert_set}"
        )

        total_inserted = 0
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for i in range(0, len(texts), batch_size):
                    end = min(i + batch_size, len(texts))
                    rows = []
                    for j in range(i, end):
                        row: List[Any] = [
                            ids[j],
                            embeddings[j].tolist(),
                            texts[j],
                            json.dumps(metadata[j]),
                        ]
                        for col in extra_cols:
                            row.append(metadata[j].get(col, _COL_DEFAULTS.get(col, "")))
                        rows.append(tuple(row))
                    psycopg2.extras.execute_values(cur, sql, rows)
                    total_inserted += end - i
                    logger.debug(f"Inserted batch {i // batch_size + 1}: {end - i} rows")
            conn.commit()
        finally:
            self._put_conn(conn)

        logger.info(f"✓ Inserted {total_inserted} rows into {collection_name}")
        return total_inserted

    def insert_with_embeddings(
        self,
        collection_name: str,
        texts: List[str],
        embeddings: List[List[float]],
        ids: Optional[List[str]] = None,
        metadata: Optional[List[Dict[str, Any]]] = None,
        batch_size: int = 1000,
    ) -> int:
        """
        Insert rows using pre-computed embeddings, skipping re-computation.
        """
        collection_name = self._table(collection_name)
        self.connect()

        if ids is None:
            ids = [f"{collection_name}_{i}" for i in range(len(texts))]
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]

        extra_cols = _EXTRA_COLUMNS.get(collection_name, [])
        all_cols = ["id", "embedding", "text", "metadata"] + extra_cols

        quoted_cols = ", ".join(f'"{c}"' for c in all_cols)
        upsert_set = ", ".join(
            f'"{c}" = EXCLUDED."{c}"'
            for c in all_cols if c != "id"
        )
        sql = (
            f'INSERT INTO "{collection_name}" ({quoted_cols}) '
            f"VALUES %s "
            f"ON CONFLICT (id) DO UPDATE SET {upsert_set}"
        )

        total_inserted = 0
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for i in range(0, len(texts), batch_size):
                    end = min(i + batch_size, len(texts))
                    rows = []
                    for j in range(i, end):
                        row: List[Any] = [
                            ids[j],
                            embeddings[j],
                            texts[j],
                            json.dumps(metadata[j]),
                        ]
                        for col in extra_cols:
                            row.append(metadata[j].get(col, _COL_DEFAULTS.get(col, "")))
                        rows.append(tuple(row))
                    psycopg2.extras.execute_values(cur, sql, rows)
                    total_inserted += end - i
            conn.commit()
        finally:
            self._put_conn(conn)

        logger.info(f"✓ Inserted {total_inserted} rows (pre-computed embeddings) into {collection_name}")
        return total_inserted

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        collection_name: str,
        query_text: Optional[str] = None,
        query_embedding: Optional[np.ndarray] = None,
        top_k: int = 5,
        filter_expr: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        output_fields: Optional[List[str]] = None,
    ) -> List[SearchResult]:
        collection_name = self._table(collection_name)
        if query_text is None and query_embedding is None:
            raise ValueError("Either query_text or query_embedding must be provided")

        self.connect()

        if query_embedding is None:
            query_embedding = self.embedding_generator.encode(query_text)

        vec = query_embedding.flatten().tolist()

        # Build WHERE clause
        where_parts: List[str] = []
        params: List[Any] = []

        if filters:
            for key, value in filters.items():
                where_parts.append(f'"{key}" = %s')
                params.append(value)

        if filter_expr:
            translated = _translate_filter_expr(filter_expr)
            if translated:
                where_parts.append(translated["clause"])
                params.extend(translated["params"])

        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        sql = (
            f'SELECT id, text, metadata, (embedding <-> %s::vector) AS distance '
            f'FROM "{collection_name}" '
            f"{where_sql} "
            f"ORDER BY distance "
            f"LIMIT %s"
        )
        final_params = [vec] + params + [top_k]

        logger.debug(f"Searching {collection_name}: top_k={top_k}, filter={filter_expr or filters}")

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, final_params)
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        results = []
        for row in rows:
            rid, text, meta_raw, distance = row
            meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw or "{}")
            score = math.exp(-float(distance))
            results.append(SearchResult(id=rid, score=score, text=text, metadata=meta))

        logger.debug(f"Found {len(results)} results in {collection_name}")
        return results

    # ------------------------------------------------------------------
    # Filter-only query
    # ------------------------------------------------------------------

    def query_by_filter(
        self,
        collection_name: str,
        filter_expr: str,
        output_fields: List[str],
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        collection_name = self._table(collection_name)
        self.connect()

        translated = _translate_filter_expr(filter_expr)
        col_list = ", ".join(f'"{f}"' for f in output_fields)
        sql = f'SELECT {col_list} FROM "{collection_name}"'
        params: List[Any] = []

        if translated:
            sql += f" WHERE {translated['clause']}"
            params = translated["params"]

        sql += f" LIMIT {limit}"

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                colnames = [desc[0] for desc in cur.description]
                return [dict(zip(colnames, row)) for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_entities(self, collection_name: str, ids: List[str]) -> int:
        collection_name = self._table(collection_name)
        if not ids:
            return 0
        self.connect()
        placeholders = ", ".join(["%s"] * len(ids))
        sql = f'DELETE FROM "{collection_name}" WHERE id IN ({placeholders})'
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, ids)
                deleted = cur.rowcount
            conn.commit()
        finally:
            self._put_conn(conn)
        logger.info(f"Deleted {deleted} rows from {collection_name}")
        return deleted

    # ------------------------------------------------------------------
    # Stats / admin
    # ------------------------------------------------------------------

    def get_collection_stats(self, collection_name: str) -> Dict[str, Any]:
        collection_name = self._table(collection_name)
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    'SELECT COUNT(*) FROM "{}"'.format(collection_name)  # noqa: S608
                )
                count = cur.fetchone()[0]

                cur.execute(
                    "SELECT column_name, data_type "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s "
                    "ORDER BY ordinal_position",
                    (collection_name,),
                )
                fields = [{"name": row[0], "type": row[1]} for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

        return {
            "name": collection_name,
            "num_entities": count,
            "schema": {"fields": fields},
        }

    def list_collections(self) -> List[str]:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
                return [row[0] for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

    def delete_collection(self, collection_name: str) -> None:
        collection_name = self._table(collection_name)
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{collection_name}" CASCADE')
            conn.commit()
            logger.info(f"Dropped table: {collection_name}")
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # Schema provisioning helper
    # ------------------------------------------------------------------

    def provision_schema(self, collection_names: Optional[List[str]] = None) -> None:
        """
        Create tables and HNSW indexes for all known collections.
        Called automatically on first connect; can also be called explicitly.
        """
        known = list(_TABLE_DDL.keys()) + [
            "pyegeria_dre",
            "egeria_java",
            "egeria_concepts",
            "egeria_types",
            "egeria_general",
            "egeria_workspaces",
            "egeria_templates",
        ]
        targets = collection_names or known
        for name in targets:
            self.create_collection(name)
            self.create_index(name)
        logger.info(f"✓ Provisioned schema for {len(targets)} collections")


# ---------------------------------------------------------------------------
# Filter expression DSL → SQL translator
# ---------------------------------------------------------------------------

def _translate_filter_expr(expr: str) -> Optional[Dict[str, Any]]:
    """
    Translate a scalar filter expression (see advisor.metadata_filters) to a
    parameterized SQL WHERE clause.

    Supported forms:
      - field == "value"
      - field == True / field == False
      - field like "%value%"
      - compound: A and B
    """
    conditions: List[str] = []
    params: List[Any] = []

    for part in re.split(r"\s+and\s+", expr.strip(), flags=re.IGNORECASE):
        part = part.strip()

        # Equality: field == "value"
        m = re.match(r'^(\w+)\s*==\s*"([^"]*)"$', part)
        if m:
            conditions.append(f'"{m.group(1)}" = %s')
            params.append(m.group(2))
            continue

        # Equality: field == True/False
        m = re.match(r"^(\w+)\s*==\s*(True|False)$", part)
        if m:
            conditions.append(f'"{m.group(1)}" = %s')
            params.append(m.group(2) == "True")
            continue

        # LIKE: field like "%value%"
        m = re.match(r'^(\w+)\s+like\s+"([^"]*)"$', part, re.IGNORECASE)
        if m:
            conditions.append(f'"{m.group(1)}" LIKE %s')
            params.append(m.group(2))
            continue

        logger.warning(f"Unrecognized filter expression fragment (skipped): {part!r}")

    if not conditions:
        return None
    return {"clause": " AND ".join(conditions), "params": params}
