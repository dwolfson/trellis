"""
pgvector (PostgreSQL) vector store backend for Resource Explorer.

PgVectorStore is now a thin adapter over the shared trellis-vectorstore
package (packages/trellis-vectorstore/) — extracted alongside Egeria
Advisor's independently-evolved equivalent (advisor/vector_store_pg.py).
See docs/trellis-vectorstore-extraction.md for the full design rationale.
This adapter's entire job is reproducing RE's exact pre-extraction
behavior: cosine distance (not EA's L2 default — RE's existing min_score
threshold semantics were calibrated against Milvus's COSINE/FLAT setup,
migration plan decision D2), a named Postgres schema (not EA's unqualified
`public`, decision D1), and no per-collection extra scalar columns (RE's
uniform 4-column schema, unlike EA's `pyegeria`/`pyegeria_cli`).

MultiCollectionStore below is unchanged — it stays package-local per the
extraction design (RE's and EA's MultiCollectionStore are different
abstractions wearing the same name; only BaseVectorStore/SearchResult/
PgVectorStore moved to the shared package).

Two classes:
  - PgVectorStore: RE's adapter over the shared implementation, same public
    constructor signature as before extraction — every existing call site
    (`PgVectorStore(schema=...)` in tests/conftest.py, the migration
    script) keeps working unmodified.
  - MultiCollectionStore: thin compatibility wrapper preserving the exact
    public method names/signatures the ~15 existing call sites already use
    (search/insert/drop_collection/count/list_source_files/collection_name),
    so this migration is a mechanical import swap at every call site rather
    than a rewrite of the callers themselves.
"""

import re
import threading

from trellis_vectorstore import PgVectorStoreConfig, SearchResult
from trellis_vectorstore.pg import PgVectorStore as _SharedPgVectorStore

from resource_explorer.config import get_config


class _ReEmbeddingProvider:
    """Satisfies trellis_vectorstore.EmbeddingProvider by wrapping RE's
    existing module-level embed_texts/embed_one functions. The import stays
    inside these methods (not at module top) deliberately — same reasoning
    as the pre-extraction code: keeps heavy ML imports (sentence-
    transformers) off this module's import path until an embedding is
    actually needed."""

    def embed_texts(self, texts):
        from resource_explorer.embeddings import embed_texts
        return embed_texts(list(texts))

    def embed_query(self, text):
        from resource_explorer.embeddings import embed_one
        return embed_one(text)


class PgVectorStore(_SharedPgVectorStore):
    """pgvector implementation of BaseVectorStore. One table per collection,
    all in the `resource_explorer` schema (migration plan decision D1).

    Same public constructor signature RE had before the shared-package
    extraction — host/port/dbname/user/password/schema/max_connections/
    ef_search, each defaulting to get_config().pgvector's value — so every
    existing call site (tests/conftest.py's `PgVectorStore(schema=...)`,
    scripts/migrate_vectors_milvus_to_pg.py) keeps working unmodified.
    """

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
        config = PgVectorStoreConfig(
            host=host or cfg.host,
            port=port or cfg.port,
            dbname=dbname or cfg.dbname,
            user=user or cfg.db_user,
            password=password or cfg.password,
            schema=schema or cfg.schema_name,
            max_connections=max_connections or cfg.max_connections,
            ef_search=ef_search or cfg.ef_search,
        )
        super().__init__(
            config,
            metric="cosine",  # decision D2 — do not "fix" to match EA's L2 default
            embeddings=_ReEmbeddingProvider(),
            auto_provision_on_insert=True,  # RE's insert_with_embeddings always self-provisions
        )


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

    def rename_collection(self, old_collection: str, new_collection: str) -> None:
        """Rename a collection's pgvector table in place, preserving its rows
        — used by the repo-rename repair operation. See
        PgVectorStore.rename_collection's docstring (trellis-vectorstore) for
        why this is a rename rather than a drop+reingest."""
        self._store.rename_collection(old_collection, new_collection)

    def count(self, collection: str) -> int:
        return int(self._store.get_collection_stats(collection).get("num_entities", 0))

    def list_source_files(self, collections: list[str], batch_size: int = 16384) -> list[str]:
        """Return unique file_path values from metadata across the given collections."""
        import logging
        _log = logging.getLogger(__name__)
        paths: set[str] = set()
        for collection in collections:
            try:
                rows = self._store.query_by_filter(collection, limit=batch_size)
                _log.debug("list_source_files: %s → %d rows", collection, len(rows))
                for row in rows:
                    meta = row.get("metadata") or {}
                    fp = meta.get("file_path") or meta.get("source_url") or ""
                    if fp:
                        paths.add(fp)
            except Exception as exc:
                _log.warning("list_source_files: query failed for %s: %s", collection, exc)
        return list(paths)
