"""
pgvector (PostgreSQL) vector store backend for Resource Explorer.

Replaces multi_collection_store.py's Milvus-backed MultiCollectionStore
(migration plan: Milvus → pgvector, shared with Egeria Advisor's own
egeria_advisor Postgres database). Structurally adapted from
egeria-advisor/advisor/vector_store_pg.py (connection pooling, HNSW
provisioning) per decision D3 — but RE uses one uniform per-collection
schema (id, embedding, text, metadata) for every collection, no
per-collection extra scalar columns, and cosine distance (not EA's L2
default) per decision D2, since RE's existing min_score threshold semantics
(collection_router.py, agents) were calibrated against Milvus's COSINE/FLAT
setup.

Two classes:
  - PgVectorStore: generic BaseVectorStore implementation, one Postgres
    table per collection, all living in the `resource_explorer` schema.
  - MultiCollectionStore: thin compatibility wrapper preserving the exact
    public method names/signatures the ~10 existing call sites already use
    (search/insert/drop_collection/count/list_source_files/collection_name),
    so this migration is a mechanical import swap at every call site rather
    than a rewrite of the callers themselves.
"""

import json
import re
import threading
from typing import Any

import numpy as np
import psycopg2
import psycopg2.extras
from pgvector.psycopg2 import register_vector
from psycopg2.pool import ThreadedConnectionPool

from resource_explorer.config import get_config
from resource_explorer.vector_store_base import BaseVectorStore, SearchResult

_DDL = """
    CREATE TABLE IF NOT EXISTS "{schema}"."{name}" (
        id        VARCHAR(256) PRIMARY KEY,
        embedding vector(384)  NOT NULL,
        text      TEXT         NOT NULL,
        metadata  JSONB        NOT NULL DEFAULT '{{}}'
    )
"""


class PgVectorStore(BaseVectorStore):
    """pgvector implementation of BaseVectorStore. One table per collection,
    all in the `resource_explorer` schema (decision D1)."""

    def __init__(
        self,
        host: str | None = None,
        port: int | None = None,
        dbname: str | None = None,
        user: str | None = None,
        password: str | None = None,
        schema: str | None = None,
        max_connections: int | None = None,
        ef_search: int | None = None,
    ):
        cfg = get_config().pgvector
        self.host = host or cfg.host
        self.port = port or cfg.port
        self.dbname = dbname or cfg.dbname
        self.user = user or cfg.db_user
        self.password = password or cfg.password
        self.schema = schema or cfg.schema_name
        self._max_connections = max_connections or cfg.max_connections
        self._ef_search = ef_search or cfg.ef_search

        self._pool: ThreadedConnectionPool | None = None
        self._connect_lock = threading.Lock()

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def connect(self) -> None:
        if self._pool is not None:
            return
        with self._connect_lock:
            if self._pool is not None:  # re-check inside lock
                return
            self._pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=self._max_connections,
                host=self.host,
                port=self.port,
                dbname=self.dbname,
                user=self.user,
                password=self.password,
            )
            with psycopg2.connect(
                host=self.host, port=self.port, dbname=self.dbname,
                user=self.user, password=self.password,
            ) as bootstrap:
                self._ensure_schema(bootstrap)

    def disconnect(self) -> None:
        if self._pool is not None:
            self._pool.closeall()
            self._pool = None

    def is_connected(self) -> bool:
        return self._pool is not None

    def _get_conn(self):
        conn = self._pool.getconn()
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute(f"SET hnsw.ef_search = {self._ef_search}")
        return conn

    def _put_conn(self, conn) -> None:
        self._pool.putconn(conn)

    def _ensure_schema(self, conn) -> None:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
        conn.commit()

    # ------------------------------------------------------------------
    # Collection (table) management
    # ------------------------------------------------------------------

    def create_collection(self, collection_name: str, drop_if_exists: bool = False) -> str:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                if drop_if_exists:
                    cur.execute(f'DROP TABLE IF EXISTS "{self.schema}"."{collection_name}" CASCADE')
                cur.execute(_DDL.format(schema=self.schema, name=collection_name))
            conn.commit()
        finally:
            self._put_conn(conn)
        return collection_name

    def create_index(
        self,
        collection_name: str,
        index_type: str = "HNSW",
        metric_type: str = "COSINE",
        params: dict[str, Any] | None = None,
    ) -> None:
        """Create an HNSW index on the embedding column.

        Deliberately defaults to COSINE (vector_cosine_ops), not EA's L2
        default — see migration plan decision D2. RE's existing min_score
        threshold semantics (collection_router.py, agents) were calibrated
        against Milvus's COSINE/FLAT setup; switching to L2 here would
        silently change what "score >= threshold" means. Do not "fix" this
        to match EA's pattern.
        """
        self.connect()
        ops = "vector_l2_ops" if metric_type.upper() == "L2" else "vector_cosine_ops"
        m = (params or {}).get("m", 16)
        ef_construction = (params or {}).get("ef_construction", 64)
        index_name = f"{collection_name}_embedding_idx"

        sql = (
            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
            f'ON "{self.schema}"."{collection_name}" '
            f"USING hnsw (embedding {ops}) "
            f"WITH (m = {m}, ef_construction = {ef_construction})"
        )
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql)
            conn.commit()
        finally:
            self._put_conn(conn)

    def collection_exists(self, collection_name: str) -> bool:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = %s",
                    (self.schema, collection_name),
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
        texts: list[str],
        ids: list[str] | None = None,
        metadata: list[dict[str, Any]] | None = None,
        batch_size: int = 1000,
    ) -> int:
        from resource_explorer.embeddings import embed_texts

        embeddings = embed_texts(texts)
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
        """Insert rows using pre-computed embeddings, skipping re-embedding.

        Used by the one-time Milvus→pgvector data migration script — both
        stacks use the same 384-dim all-MiniLM-L6-v2 model, so existing
        embeddings transplant directly without needing to be regenerated.
        insert_data() above is just this with embeddings computed on the fly.
        """
        self.create_collection(collection_name)
        self.create_index(collection_name)

        if ids is None:
            ids = [f"{collection_name}_{i}" for i in range(len(texts))]
        if metadata is None:
            metadata = [{} for _ in range(len(texts))]
        if len(texts) != len(ids) or len(texts) != len(metadata) or len(texts) != len(embeddings):
            raise ValueError("texts, ids, embeddings, and metadata must have the same length")

        sql = (
            f'INSERT INTO "{self.schema}"."{collection_name}" (id, embedding, text, metadata) '
            f"VALUES %s "
            f"ON CONFLICT (id) DO UPDATE SET "
            f"embedding = EXCLUDED.embedding, text = EXCLUDED.text, metadata = EXCLUDED.metadata"
        )

        total_inserted = 0
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                for i in range(0, len(texts), batch_size):
                    end = min(i + batch_size, len(texts))
                    rows = [
                        (
                            ids[j],
                            embeddings[j].tolist() if isinstance(embeddings[j], np.ndarray) else list(embeddings[j]),
                            texts[j],
                            json.dumps(metadata[j]),
                        )
                        for j in range(i, end)
                    ]
                    psycopg2.extras.execute_values(cur, sql, rows)
                    total_inserted += end - i
            conn.commit()
        finally:
            self._put_conn(conn)
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
    ) -> list[SearchResult]:
        from resource_explorer.embeddings import embed_one

        if query_text is None and query_embedding is None:
            raise ValueError("Either query_text or query_embedding must be provided")

        self.connect()
        if not self.collection_exists(collection_name):
            return []

        if query_embedding is None:
            query_embedding = embed_one(query_text)  # already list[float] (embeddings.py .tolist())
        # .tolist() only if it's actually an ndarray — calling list() on a
        # numpy array (rather than .tolist()) leaves np.float64 elements
        # behind, which psycopg2 cannot adapt into a vector literal.
        vec = query_embedding.tolist() if isinstance(query_embedding, np.ndarray) else list(query_embedding)

        # Cosine distance operator <=> ranges [0, 2]; convert to a
        # Milvus-COSINE-compatible similarity score in [-1, 1] (1 - distance)
        # so RE's existing min_score thresholds keep meaning unchanged.
        sql = (
            f'SELECT id, text, metadata, (embedding <=> %s::vector) AS distance '
            f'FROM "{self.schema}"."{collection_name}" '
            f"ORDER BY distance "
            f"LIMIT %s"
        )
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [vec, top_k])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)

        results = []
        for rid, text, meta_raw, distance in rows:
            meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw or "{}")
            score = 1.0 - float(distance)
            results.append(SearchResult(id=rid, score=score, text=text, metadata=meta))
        return results

    # ------------------------------------------------------------------
    # Filter-only query
    # ------------------------------------------------------------------

    def query_by_filter(
        self,
        collection_name: str,
        field: str,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Return {id, text, metadata} rows, no vector search — used by
        list_source_files()-style scans that only need the `field` metadata key."""
        self.connect()
        if not self.collection_exists(collection_name):
            return []
        sql = (
            f'SELECT id, text, metadata FROM "{self.schema}"."{collection_name}" '
            f"LIMIT %s"
        )
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, [limit])
                rows = cur.fetchall()
        finally:
            self._put_conn(conn)
        results = []
        for rid, text, meta_raw in rows:
            meta = meta_raw if isinstance(meta_raw, dict) else json.loads(meta_raw or "{}")
            results.append({"id": rid, "text": text, "metadata": meta})
        return results

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    def delete_entities(self, collection_name: str, ids: list[str]) -> int:
        if not ids:
            return 0
        self.connect()
        placeholders = ", ".join(["%s"] * len(ids))
        sql = f'DELETE FROM "{self.schema}"."{collection_name}" WHERE id IN ({placeholders})'
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(sql, ids)
                deleted = cur.rowcount
            conn.commit()
        finally:
            self._put_conn(conn)
        return deleted

    def delete_by_metadata(self, collection_name: str, field: str, values: list[str]) -> int:
        """Delete every row whose metadata->>field is in values. Backs the
        real row-level incremental-indexing rework (migration plan D4)."""
        if not values:
            return 0
        self.connect()
        if not self.collection_exists(collection_name):
            return 0
        sql = (
            f'DELETE FROM "{self.schema}"."{collection_name}" '
            f"WHERE metadata->>%s = ANY(%s)"
        )
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
        if not self.collection_exists(collection_name):
            return {"name": collection_name, "num_entities": 0}
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'SELECT COUNT(*) FROM "{self.schema}"."{collection_name}"')
                count = cur.fetchone()[0]
        finally:
            self._put_conn(conn)
        return {"name": collection_name, "num_entities": count}

    def list_collections(self) -> list[str]:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = %s ORDER BY table_name",
                    (self.schema,),
                )
                return [row[0] for row in cur.fetchall()]
        finally:
            self._put_conn(conn)

    def delete_collection(self, collection_name: str) -> None:
        self.connect()
        conn = self._get_conn()
        try:
            with conn.cursor() as cur:
                cur.execute(f'DROP TABLE IF EXISTS "{self.schema}"."{collection_name}" CASCADE')
            conn.commit()
        finally:
            self._put_conn(conn)


# ---------------------------------------------------------------------------
# Compatibility wrapper — preserves MultiCollectionStore's exact public
# interface so existing call sites (rag_system.py, ingestion/pipeline.py,
# agents/*.py, cli/*.py, tui/app.py, dashboard/terminal_dashboard.py,
# surveyors/file_classifier/file_classifier_surveyor.py, web/routes/projects.py)
# only need their import path changed, per migration plan Phase 1.
# ---------------------------------------------------------------------------

_shared_store: PgVectorStore | None = None
_shared_store_lock = threading.Lock()


def _get_shared_store() -> PgVectorStore:
    """A process-wide PgVectorStore singleton — connection pooling is meant
    to be shared, not re-established per MultiCollectionStore() instantiation
    (callers create one of these per call in several places)."""
    global _shared_store
    if _shared_store is None:
        with _shared_store_lock:
            if _shared_store is None:
                _shared_store = PgVectorStore()
    return _shared_store


class MultiCollectionStore:
    """
    Manages pgvector-backed collections namespaced as {project_slug}_{collection_type},
    one Postgres table per collection in the `resource_explorer` schema.

    Same public interface as the Milvus-backed version it replaces
    (multi_collection_store.py, now removed) — search/insert/drop_collection/
    count/list_source_files/collection_name — plus collection_exists(), which
    closes a leak where agents/tools.py previously reached past this
    interface to call Milvus-specific has_collection() directly, and
    delete_by_metadata(), which backs real row-level incremental re-indexing
    (migration plan decision D4 — ingestion/incremental.py) instead of the
    old collection-level drop+full-rebuild that existed specifically because
    Milvus made delete-by-filter awkward.
    """

    def __init__(self) -> None:
        self._cfg = get_config()
        self._store = _get_shared_store()

    def collection_name(self, project_slug: str, collection_type: str) -> str:
        safe_slug = re.sub(r"[^a-z0-9_]", "_", project_slug.lower())
        return f"{safe_slug}_{collection_type}"

    def collection_exists(self, collection: str) -> bool:
        return self._store.collection_exists(collection)

    def delete_by_metadata(self, collection: str, field: str, values: list[str]) -> int:
        return self._store.delete_by_metadata(collection, field, values)

    def search(
        self,
        query: str,
        collections: list[str],
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        k = top_k or self._cfg.rag.top_k
        threshold = min_score if min_score is not None else self._cfg.rag.min_score
        boosts = self._load_boosts()

        results: list[SearchResult] = []
        for collection in collections:
            for r in self._store.search(collection, query_text=query, top_k=k):
                if r.score < threshold:
                    continue
                ref = f"{collection}:{r.id}"
                boost = boosts.get(ref, 0.0)
                r.score = min(1.0, r.score + boost)
                r.collection = collection
                results.append(r)

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:k]

    def _load_boosts(self) -> dict[str, float]:
        """Load per-chunk feedback boosts from SQLite metrics DB."""
        try:
            import sqlite3
            db_path = self._cfg.observability.metrics_db
            conn = sqlite3.connect(db_path)
            rows = conn.execute(
                "SELECT chunk_ref, positive_count, total_count FROM chunk_feedback"
            ).fetchall()
            conn.close()
            boosts = {}
            for ref, pos, total in rows:
                if total > 0:
                    precision = pos / total
                    confidence = min(total / 5.0, 1.0)  # grows with 5+ votes
                    boosts[ref] = (precision - 0.5) * confidence * 0.3
            return boosts
        except Exception:
            return {}

    def insert(self, collection: str, texts: list[str], metadatas: list[dict]) -> int:
        # Deterministic ids (sha256 of collection+index+text), NOT Python's
        # built-in hash() — that's randomized per-process (PYTHONHASHSEED),
        # so re-running ingestion would mint a fresh id for the same chunk
        # every time and defeat the ON CONFLICT (id) upsert entirely.
        import hashlib
        ids = [
            hashlib.sha256(f"{collection}:{i}:{t}".encode()).hexdigest()[:32]
            for i, t in enumerate(texts)
        ]
        return self._store.insert_data(collection, texts, ids=ids, metadata=metadatas)

    def drop_collection(self, collection: str) -> None:
        self._store.delete_collection(collection)

    def count(self, collection: str) -> int:
        return int(self._store.get_collection_stats(collection).get("num_entities", 0))

    def list_source_files(self, collections: list[str], batch_size: int = 16384) -> list[str]:
        """Return unique file_path values from metadata across the given collections."""
        import logging
        _log = logging.getLogger(__name__)
        paths: set[str] = set()
        for collection in collections:
            try:
                rows = self._store.query_by_filter(collection, "file_path", limit=batch_size)
                _log.debug("list_source_files: %s → %d rows", collection, len(rows))
                for row in rows:
                    meta = row.get("metadata") or {}
                    fp = meta.get("file_path") or meta.get("source_url") or ""
                    if fp:
                        paths.add(fp)
            except Exception as exc:
                _log.warning("list_source_files: query failed for %s: %s", collection, exc)
        return list(paths)
