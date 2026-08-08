"""
Vector store backend factory for Egeria Advisor.
"""

from advisor.config import settings
from advisor.vector_store_base import BaseVectorStore, SearchResult

# Backwards-compatibility alias — existing imports of VectorStoreManager as a
# type hint stay unchanged; this is never instantiated directly.
VectorStoreManager = BaseVectorStore


def get_vector_store() -> BaseVectorStore:
    """
    Factory: return the active vector store backend.

    Checks config/advisor.yaml first (vector_store_backend key), then falls
    back to the VECTOR_STORE_BACKEND environment variable, then defaults to
    'pgvector' — the only supported backend.
    """
    from advisor.config import load_config
    cfg = load_config()
    backend = cfg.get(
        "vector_store_backend",
        getattr(settings, "vector_store_backend", "pgvector"),
    ).lower()

    if backend != "pgvector":
        from loguru import logger
        logger.warning(f"Unknown vector_store_backend {backend!r} — defaulting to pgvector")

    from advisor.vector_store_pg import PgVectorStore
    pg_cfg = cfg.get("pgvector", {})
    return PgVectorStore(
        host=pg_cfg.get("host", settings.pgvector_host),
        port=int(pg_cfg.get("port", settings.pgvector_port)),
        dbname=pg_cfg.get("dbname", settings.pgvector_dbname),
        user=pg_cfg.get("user", settings.pgvector_user),
        password=pg_cfg.get("password", settings.pgvector_password),
        max_connections=int(pg_cfg.get("max_connections", settings.pgvector_max_connections)),
        ef_search=int(pg_cfg.get("ef_search", settings.pgvector_ef_search)),
    )
