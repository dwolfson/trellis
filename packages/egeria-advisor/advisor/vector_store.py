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
    return PgVectorStore(**resolve_pgvector_kwargs(pg_cfg))


def resolve_pgvector_kwargs(pg_cfg: dict) -> dict:
    """Connection settings for the vector store, env first, then advisor.yaml's
    `pgvector:` block, then the settings defaults.

    The yaml block used to win over the environment, so a container whose
    PGVECTOR_HOST pointed at the shared Postgres still connected to the yaml's
    `localhost` from any path that came through this factory (EA's corpus
    ingestion on trevor, 2026-09-04) while the web process, which reaches
    Postgres through db_consolidated and the settings object, was fine. Same
    precedence as the rest of EA now: an explicit env var is the deployment's
    word and beats a checked-in yaml value.
    """
    import os

    def pick(env_name: str, key: str, default, cast=lambda v: v):
        env_val = os.environ.get(env_name, "").strip()
        if env_val:
            return cast(env_val)
        if key in pg_cfg and pg_cfg[key] not in (None, ""):
            return cast(pg_cfg[key])
        return default

    return {
        "host": pick("PGVECTOR_HOST", "host", settings.pgvector_host),
        "port": pick("PGVECTOR_PORT", "port", settings.pgvector_port, int),
        "dbname": pick("PGVECTOR_DBNAME", "dbname", settings.pgvector_dbname),
        "user": pick("PGVECTOR_USER", "user", settings.pgvector_user),
        "password": pick("PGVECTOR_PASSWORD", "password", settings.pgvector_password),
        "max_connections": pick("PGVECTOR_MAX_CONNECTIONS", "max_connections", settings.pgvector_max_connections, int),
        "ef_search": pick("PGVECTOR_EF_SEARCH", "ef_search", settings.pgvector_ef_search, int),
    }
