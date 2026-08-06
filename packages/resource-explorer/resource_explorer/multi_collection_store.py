"""Milvus multi-tenant vector store — one namespace per project."""
from __future__ import annotations

import json
from dataclasses import dataclass

from resource_explorer.config import get_config


@dataclass
class SearchResult:
    text: str
    score: float
    metadata: dict
    collection: str
    chunk_id: int = 0  # Milvus auto-id, used for feedback reranking


class MultiCollectionStore:
    """
    Manages Milvus collections namespaced as {project_slug}_{collection_type}.

    Uses MilvusClient directly (compatible with both Milvus Lite and standalone).
    Each collection uses COSINE similarity with 384-dim sentence-transformer embeddings.
    Schema: auto_id int pk + "vector" float array + "text" varchar + "metadata_json" varchar.
    """

    _TEXT_MAX_LEN = 65_535
    _META_MAX_LEN = 65_535

    @staticmethod
    def _trunc(s: str, max_bytes: int) -> str:
        """Truncate to max_bytes UTF-8 bytes without splitting a multi-byte character."""
        encoded = s.encode("utf-8")
        if len(encoded) <= max_bytes:
            return s
        return encoded[:max_bytes].decode("utf-8", errors="ignore")

    def __init__(self) -> None:
        self._cfg = get_config()
        self._client = None  # lazy-initialized on first use

    def _get_client(self):
        if self._client is None:
            from pymilvus import MilvusClient
            self._client = MilvusClient(
                uri=self._cfg.milvus.uri,
                token=self._cfg.milvus.token or None,
            )
        return self._client

    def collection_name(self, project_slug: str, collection_type: str) -> str:
        import re as _re
        safe_slug = _re.sub(r"[^a-z0-9_]", "_", project_slug.lower())
        return f"{safe_slug}_{collection_type}"

    def _ensure_collection(self, collection: str) -> None:
        client = self._get_client()
        if client.has_collection(collection):
            return
        from pymilvus import DataType
        # Simple API: auto_id pk + "vector" field created automatically
        schema = client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=self._cfg.embeddings.dimension)
        schema.add_field("text", DataType.VARCHAR, max_length=self._TEXT_MAX_LEN)
        schema.add_field("metadata_json", DataType.VARCHAR, max_length=self._META_MAX_LEN)
        # FLAT index: compatible with both Milvus Lite and standalone
        index_params = client.prepare_index_params()
        index_params.add_index(field_name="vector", metric_type="COSINE", index_type="FLAT")
        client.create_collection(
            collection_name=collection,
            schema=schema,
            index_params=index_params,
        )
        client.load_collection(collection)

    def search(
        self,
        query: str,
        collections: list[str],
        top_k: int | None = None,
        min_score: float | None = None,
    ) -> list[SearchResult]:
        from resource_explorer.embeddings import embed_one
        k = top_k or self._cfg.rag.top_k
        threshold = min_score or self._cfg.rag.min_score
        client = self._get_client()
        q_vec = embed_one(query)
        results: list[SearchResult] = []
        boosts = self._load_boosts()
        for collection in collections:
            if not client.has_collection(collection):
                continue
            hits = client.search(
                collection_name=collection,
                data=[q_vec],
                limit=k,
                output_fields=["text", "metadata_json"],
                search_params={"metric_type": "COSINE"},
            )
            for hit in hits[0]:
                base_score = hit.get("distance", 0.0)
                if base_score < threshold:
                    continue
                chunk_id = hit.get("id", 0)
                ref = f"{collection}:{chunk_id}"
                boost = boosts.get(ref, 0.0)
                score = min(1.0, base_score + boost)
                entity = hit.get("entity", {})
                text = entity.get("text", "")
                try:
                    metadata = json.loads(entity.get("metadata_json", "{}"))
                except Exception:
                    metadata = {}
                results.append(SearchResult(text=text, score=score,
                                            metadata=metadata, collection=collection,
                                            chunk_id=chunk_id))
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
        from resource_explorer.embeddings import embed_texts
        self._ensure_collection(collection)
        client = self._get_client()
        vectors = embed_texts(texts)
        data = [
            {
                "vector": vec,
                "text": self._trunc(text, self._TEXT_MAX_LEN),
                "metadata_json": self._trunc(json.dumps(meta), self._META_MAX_LEN),
            }
            for vec, text, meta in zip(vectors, texts, metadatas)
        ]
        result = client.insert(collection_name=collection, data=data)
        client.flush(collection)
        return result.get("insert_count", len(data))

    def drop_collection(self, collection: str) -> None:
        client = self._get_client()
        if client.has_collection(collection):
            client.drop_collection(collection)

    def count(self, collection: str) -> int:
        client = self._get_client()
        if not client.has_collection(collection):
            return 0
        stats = client.get_collection_stats(collection)
        return int(stats.get("row_count", 0))

    def list_source_files(self, collections: list[str], batch_size: int = 16384) -> list[str]:
        """Return unique file_path values from metadata_json across the given collections.

        Uses MilvusClient.query() (no vector required).  For very large collections
        only the first `batch_size` records are scanned — sufficient for file-type
        classification because the goal is coverage of types, not an exact manifest.
        """
        import logging
        _log = logging.getLogger(__name__)
        client = self._get_client()
        paths: set[str] = set()
        for collection in collections:
            if not client.has_collection(collection):
                continue
            try:
                rows = client.query(
                    collection_name=collection,
                    filter="id >= 0",
                    output_fields=["metadata_json"],
                    limit=batch_size,
                )
                _log.debug("list_source_files: %s → %d rows", collection, len(rows))
                for row in rows:
                    try:
                        meta = json.loads(row.get("metadata_json") or "{}")
                        fp = meta.get("file_path") or meta.get("source_url") or ""
                        if fp:
                            paths.add(fp)
                    except Exception:
                        pass
            except Exception as exc:
                _log.warning("list_source_files: query failed for %s: %s", collection, exc)
        return list(paths)
