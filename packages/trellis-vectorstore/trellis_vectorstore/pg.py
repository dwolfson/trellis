"""pgvector (PostgreSQL) vector store — shared implementation extracted from
Resource Explorer's and Egeria Advisor's independently-evolved
PgVectorStore classes (see trellis_vectorstore/__init__.py's docstring for
the extraction's design rationale).

Every constructor knob below traces to a confirmed, deliberate behavioral
difference between the two apps' original implementations — see
docs/trellis-vectorstore-extraction.md and the design plan for the full
enumeration. Nothing here is a "sensible default guess"; each app's own
adapter (resource_explorer/vector_store_pg.py, advisor/vector_store_pg.py)
passes the exact values that reproduce its pre-extraction behavior.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from typing import Any, Mapping, Protocol, Sequence, runtime_checkable

import numpy as np
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from psycopg2.pool import ThreadedConnectionPool

from trellis_vectorstore.base import BaseVectorStore, SearchResult
from trellis_vectorstore.config import PgVectorStoreConfig
from trellis_vectorstore.embeddings import EmbeddingProvider
from trellis_vectorstore.filters import translate_filter_expr
from trellis_vectorstore.metrics import MetricStrategy, resolve_metric
from trellis_vectorstore.schemas import CollectionSchema, render_create_table_sql


@runtime_checkable
class LoggerLike(Protocol):
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


class _NullLogger:
    def debug(self, msg: str) -> None: ...
    def info(self, msg: str) -> None: ...
    def warning(self, msg: str) -> None: ...
    def error(self, msg: str) -> None: ...


@dataclass
class _InsertSql:
    """A testable seam — exposes the exact generated INSERT/upsert SQL text
    and the ordered extra-column names, so a unit test can assert the
    literal string without a live database."""
    sql: str
    extra_columns: tuple[str, ...]


class PgVectorStore(BaseVectorStore):
    """pgvector implementation of BaseVectorStore. One table per collection."""

    def __init__(
        self,
        config: PgVectorStoreConfig,
        *,
        metric: "str | MetricStrategy",
        embeddings: EmbeddingProvider,
        collection_schemas: Mapping[str, CollectionSchema] | None = None,
        table_name_map: Mapping[str, str] | None = None,
        auto_provision_on_insert: bool = False,
        logger: LoggerLike | None = None,
    ) -> None:
        self._config = config
        self._metric = resolve_metric(metric)
        self._embeddings = embeddings
        self._collection_schemas: dict[str, CollectionSchema] = dict(collection_schemas or {})
        self._table_name_map: dict[str, str] = dict(table_name_map or {})
        self._auto_provision_on_insert = auto_provision_on_insert
        self._logger: LoggerLike = logger or _NullLogger()

        self._pool: ThreadedConnectionPool | None = None
        self._connect_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Identifier / schema helpers
    # ------------------------------------------------------------------

    def _table(self, collection_name: str) -> str:
        """Normalize a collection name to its canonical table name (EA's
        _TABLE_NAME_MAP handles e.g. 'pyegeria_drE' -> 'pyegeria_dre'). A
        no-op for any app that passes no table_name_map."""
        return self._table_name_map.get(collection_name, collection_name)

    def _qualified(self, table: str) -> str:
        """schema=None => unqualified identifier (relies on Postgres
        search_path, effectively 'public' in both apps' deployments today —
        this is EA's exact current behavior). A non-None schema => always
        schema-qualified (RE's exact current behavior)."""
        return f'"{self._config.schema}"."{table}"' if self._config.schema else f'"{table}"'

    @property
    def _catalog_schema(self) -> str:
        """The table_schema value to filter information_schema queries by."""
        return self._config.schema or "public"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._pool is not None:
            return
        with self._connect_lock:
            if self._pool is not None:  # re-check inside lock
                return
            self._logger.info(f"Connecting to pgvector at {self._config.host}:{self._config.port}/{self._config.dbname}")
            self._pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=self._config.max_connections,
                host=self._config.host,
                port=self._config.port,
                dbname=self._config.dbname,
                user=self._config.user,
                password=self._config.password,
            )
            with psycopg2.connect(
                host=self._config.host, port=self._config.port, dbname=self._config.dbname,
                user=self._config.user, password=self._config.password,
            ) as bootstrap:
                self._ensure_extension(bootstrap)
                if self._config.schema:
                    self._ensure_schema(bootstrap)
            self._logger.info(f"✓ Connected to pgvector at {self._config.host}:{self._config.port}/{self._config.dbname}")

    def disconnect(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None
            self._logger.info("Disconnected from pgvector")

    def is_connected(self) -> bool:
        return self._pool is not None

    def _get_conn(self):
        conn = self._pool.getconn()
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(f"SET hnsw.ef_search = {self._config.ef_search}")
        return conn

    def _put_conn(self, conn) -> None:
        self._pool.putconn(conn)

    def _ensure_extension(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()

    def _ensure_schema(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self._config.schema}"')
        conn.commit()

    # ------------------------------------------------------------------
    # Collection (table) management
    # ------------------------------------------------------------------

    def create_collection(self, collection_name: str, drop_if_exists: bool = False) -> str:
        table = self._table(collection_name)
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if drop_if_exists:
                    cur.execute(f'DROP TABLE IF EXISTS {self._qualified(table)} CASCADE')
                    self._logger.warning(f"Dropped table: {table}")
                ddl = self._render_ddl(table)
                cur.execute(ddl)
            conn.commit()
            self._logger.info(f"✓ Created/verified table: {table}")
        finally:
            self._put_conn(conn)
        return table

    def _render_ddl(self, table: str) -> str:
        schema = self._collection_schemas.get(table)
        qualified = self._qualified(table)
        if schema is not None and schema.raw_ddl is not None:
            # Transitional escape hatch — the raw DDL string already names
            # some bare table name (e.g. `CREATE TABLE IF NOT EXISTS
            # "pyegeria" (...)`), matching each app's pre-extraction DDL
            # exactly. Substitute whatever quoted name follows "CREATE
            # TABLE IF NOT EXISTS" with the actual (possibly remapped,
            # possibly schema-qualified) target — NOT a literal replace of
            # `table`, since table_name_map can remap the canonical name
            # itself (e.g. a test fixture retargeting "pyegeria" to a
            # prefixed throwaway table), in which case `table` never
            # appears verbatim inside raw_ddl at all and a literal replace
            # would silently no-op, creating the wrong (real) table name.
            return re.sub(
                r'CREATE TABLE IF NOT EXISTS "[^"]+"',
                f"CREATE TABLE IF NOT EXISTS {qualified}",
                schema.raw_ddl, count=1,
            )
        extra_columns = schema.extra_columns if schema is not None else ()
        return render_create_table_sql(qualified, extra_columns, self._config.embedding_dim)

    def create_index(
        self,
        collection_name: str,
        index_type: str = "HNSW",
        metric_type: str | None = None,
        params: dict[str, Any] | None = None,
    ) -> None:
        """Create an HNSW index on the embedding column.

        metric_type=None (the default) uses this store's own configured
        metric strategy. An explicitly-passed metric_type that disagrees
        with the instance's strategy raises ValueError — a mismatched index
        (e.g. vector_l2_ops on a store whose search() always uses <=>)
        would build successfully and then silently full-scan forever, since
        pgvector can't use an index built for the wrong operator class.
        Neither app's real callers ever pass this explicitly today; this
        makes the mismatch a loud failure instead of a silent one, for free.
        """
        # Validated before connecting — this is a pure config check, no
        # reason to require a live database just to reject a bad call.
        if metric_type is not None and metric_type.upper() != self._metric.legacy_metric_type:
            raise ValueError(
                f"create_index metric_type={metric_type!r} disagrees with this store's "
                f"configured metric {self._metric.name!r} ({self._metric.legacy_metric_type}) — "
                "an index built for the wrong operator class silently can't be used by search()."
            )
        self.connect()
        table = self._table(collection_name)
        ops = self._metric.index_ops
        m = (params or {}).get("m", 16)
        ef_construction = (params or {}).get("ef_construction", 64)
        index_name = f"{table}_embedding_idx"

        sql = (
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON {self._qualified(table)} '
            f"USING hnsw (embedding {ops}) "
            f"WITH (m = {m}, ef_construction = {ef_construction})"
        )
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
            self._logger.info(f"✓ Created HNSW index on {table} (m={m}, ef_construction={ef_construction})")
        finally:
            self._put_conn(conn)

    def collection_exists(self, collection_name: str) -> bool:
        table = self._table(collection_name)
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s",
                    (self._catalog_schema, table),
                )
                return cur.fetchone() is not None
        finally:
            self._put_conn(conn)

    # ------------------------------------------------------------------
    # Data insertion
    # ------------------------------------------------------------------

    def _extra_columns_for(self, table: str) -> tuple[str, ...]:
        schema = self._collection_schemas.get(table)
        if schema is None:
            return ()
        return tuple(c.name for c in schema.extra_columns)

    def _extra_defaults_for(self, table: str) -> dict[str, Any]:
        schema = self._collection_schemas.get(table)
        if schema is None:
            return {}
        return {c.name: c.default for c in schema.extra_columns}

    def _build_insert_sql(self, collection_name: str) -> _InsertSql:
        """Exposed (not underscore-private in spirit, just Python-private by
        convention) as a testable seam — a unit test can assert this exact
        SQL text without a live database."""
        table = self._table(collection_name)
        extra_cols = self._extra_columns_for(table)
        all_cols = ("id", "embedding", "text", "metadata") + extra_cols
        quoted_cols = ", ".join(f'"{c}"' for c in all_cols)
        upsert_set = ", ".join(f'"{c}" = EXCLUDED."{c}"' for c in all_cols if c != "id")
        sql = (
            f'INSERT INTO {self._qualified(table)} ({quoted_cols}) '
            f"VALUES %s "
            f"ON CONFLICT (id) DO UPDATE SET {upsert_set}"
        )
        return _InsertSql(sql=sql, extra_columns=extra_cols)

    def insert_data(
        self,
        collection_name: str,
        texts: list[str],
        ids: list[str] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> int:
        embeddings = list(self._embeddings.embed_texts(texts))
        return self.insert_with_embeddings(collection_name, texts, embeddings, ids, metadata, batch_size)

    def insert_with_embeddings(
        self,
        collection_name: str,
        texts: list[str],
        embeddings: list[Any],
        ids: list[str] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> int:
        table = self._table(collection_name)
        if self._auto_provision_on_insert:
            self.create_collection(collection_name)
            self.create_index(collection_name)
        self.connect()

        if ids is None:
            ids = [f"{table}_{i}" for i in range(len(texts))]
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]
        if len(texts) != len(ids) or len(texts) != len(metadata) or len(texts) != len(embeddings):
            raise ValueError("texts, ids, embeddings, and metadata must have the same length")

        insert_sql = self._build_insert_sql(collection_name)
        defaults = self._extra_defaults_for(table)

        total_inserted = 0
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for i in range(0, len(texts), batch_size):
                    end = min(i + batch_size, len(texts))
                    rows = []
                    for j in range(i, end):
                        emb = embeddings[j]
                        emb_list = emb.tolist() if isinstance(emb, np.ndarray) else list(emb)
                        row: list[Any] = [ids[j], emb_list, texts[j], json.dumps(metadata[j])]
                        for col in insert_sql.extra_columns:
                            row.append(metadata[j].get(col, defaults.get(col, "")))
                        rows.append(tuple(row))
                    psycopg2.extras.execute_values(cur, insert_sql.sql, rows)
                    total_inserted += end - i
            conn.commit()
        finally:
            self._put_conn(conn)

        self._logger.info(f"✓ Inserted {total_inserted} rows into {table}")
        return total_inserted

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        collection_name: str,
        query_text: str | None = None,
        query_embedding: np.ndarray | None = None,
        top_k: int = 5,
        filter_expr: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        if query_text is None and query_embedding is None:
            raise ValueError("Either query_text or query_embedding must be provided")

        self.connect()
        table = self._table(collection_name)
        if not self.collection_exists(collection_name):
            return []

        if query_embedding is None:
            query_embedding = self._embeddings.embed_query(query_text)
        vec = np.asarray(query_embedding).flatten().tolist()

        where_parts: list[str] = []
        params: list[Any] = []
        if filters:
            for key, value in filters.items():
                where_parts.append(f'"{key}" = %s')
                params.append(value)
        if filter_expr:
            translated = translate_filter_expr(filter_expr, warn=self._logger.warning)
            if translated:
                where_parts.append(translated["clause"])
                params.extend(translated["params"])
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        sql = (
            f'SELECT id, text, metadata, (embedding {self._metric.distance_op} %s::vector) AS distance '
            f'FROM {self._qualified(table)} '
            f"{where_sql} "
            f"ORDER BY distance "
            f"LIMIT %s"
        )
        final_params = [vec] + params + [top_k]

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, final_params)
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        results = []
        for rid, text, meta_raw, distance in rows:
            meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw or "{}")
            score = self._metric.score_fn(float(distance))
            results.append(SearchResult(id=rid, score=score, text=text, metadata=meta))
        return results

    # ------------------------------------------------------------------
    # Filter-only query
    # ------------------------------------------------------------------

    def query_by_filter(
        self,
        collection_name: str,
        filter_expr: str | None = None,
        output_fields: Sequence[str] = ("id", "text", "metadata"),
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        self.connect()
        table = self._table(collection_name)
        if not self.collection_exists(collection_name):
            return []

        col_list = ", ".join(f'"{f}"' for f in output_fields)
        sql = f'SELECT {col_list} FROM {self._qualified(table)}'
        params: list[Any] = []

        if filter_expr:
            translated = translate_filter_expr(filter_expr, warn=self._logger.warning)
            if translated:
                sql += f" WHERE {translated['clause']}"
                params = translated["params"]

        sql += " LIMIT %s"
        params = params + [limit]

        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                colnames = [desc[0] for desc in cur.description]
                rows = [dict(zip(colnames, row)) for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

        # Normalize any returned "metadata" column to a dict — psycopg2
        # already returns JSONB as dict, but this guard is defensive
        # (matches RE's original behavior; a no-op for EA in practice).
        for row in rows:
            if "metadata" in row and not isinstance(row["metadata"], dict):
                row["metadata"] = json.loads(row["metadata"] or "{}")
        return rows

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_entities(self, collection_name: str, ids: list[str]) -> int:
        if not ids:
            return 0
        self.connect()
        table = self._table(collection_name)
        placeholders = ", ".join(["%s"] * len(ids))
        sql = f'DELETE FROM {self._qualified(table)} WHERE id IN ({placeholders})'
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, ids)
                deleted = cur.rowcount
            conn.commit()
        finally:
            self._put_conn(conn)
        self._logger.info(f"Deleted {deleted} rows from {table}")
        return deleted

    def delete_by_metadata(self, collection_name: str, field: str, values: list[str]) -> int:
        if not values:
            return 0
        self.connect()
        table = self._table(collection_name)
        if not self.collection_exists(collection_name):
            return 0
        sql = f'DELETE FROM {self._qualified(table)} WHERE metadata->>%s = ANY(%s)'
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [field, values])
                deleted = cur.rowcount
            conn.commit()
        finally:
            self._put_conn(conn)
        return deleted

    # ------------------------------------------------------------------
    # Stats / admin
    # ------------------------------------------------------------------

    def get_collection_stats(self, collection_name: str) -> dict[str, Any]:
        self.connect()
        table = self._table(collection_name)
        if not self.collection_exists(collection_name):
            return {"name": table, "num_entities": 0}
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM {self._qualified(table)}')
                count = cur.fetchone()[0]

                cur.execute(
                    "SELECT column_name, data_type FROM information_schema.columns "
                    "WHERE table_schema = %s AND table_name = %s ORDER BY ordinal_position",
                    (self._catalog_schema, table),
                )
                fields = [{"name": row[0], "type": row[1]} for row in cur.fetchall()]
        finally:
            self._put_conn(conn)
        return {"name": table, "num_entities": count, "schema": {"fields": fields}}

    def list_collections(self) -> list[str]:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name",
                    (self._catalog_schema,),
                )
                return [row[0] for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

    def delete_collection(self, collection_name: str) -> None:
        self.connect()
        table = self._table(collection_name)
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS {self._qualified(table)} CASCADE')
            conn.commit()
            self._logger.info(f"Dropped table: {table}")
        finally:
            self._put_conn(conn)
