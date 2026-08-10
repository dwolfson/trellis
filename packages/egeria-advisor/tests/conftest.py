"""
Pytest configuration and shared fixtures for Egeria Advisor tests.

Also home to the real (non-mocked) pgvector integration tier for EA's
vector store — mirrors Resource Explorer's tests/conftest.py pattern
(requires_pgvector marker + auto-skip when Postgres isn't reachable), added
as part of the trellis-vectorstore extraction to close a real, confirmed
gap: EA previously had zero pytest coverage of PgVectorStore/BaseVectorStore
at all, only non-pytest standalone scripts.

Isolation note: RE's equivalent fixture uses a throwaway Postgres *schema*
(RE's tables are always schema-qualified). EA's tables are always
unqualified/`public` — testing in a separate schema would test a
configuration EA never actually runs in. The originally-preferred isolation
(a throwaway *database*, `egeria_advisor_vs_test`) needs CREATEDB, which
the `egeria_advisor` role does not have (confirmed live) — falls back to
the documented contingency: prefixed throwaway tables (`zzz_vstest_*`) in
the real `public` schema, dropped in teardown. This means list_collections()
assertions in these tests must be superset-style ("in", not "=="), since
real EA production tables are also present in the same schema.
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def sample_query():
    """Sample user query for testing."""
    return "How do I create a glossary?"


@pytest.fixture
def sample_code_query():
    """Sample code search query."""
    return "Show me examples of using the collection manager"


@pytest.fixture
def sample_quantitative_query():
    """Sample quantitative query."""
    return "How many lines of code are in the project?"


# ---------------------------------------------------------------------------
# pgvector integration tier (trellis-vectorstore extraction, Phase 4)
# ---------------------------------------------------------------------------

_VS_TEST_PREFIX = "zzz_vstest_"


def _pgvector_reachable() -> bool:
    try:
        import psycopg2
        from advisor.config import settings

        conn = psycopg2.connect(
            host=settings.pgvector_host, port=settings.pgvector_port,
            dbname=settings.pgvector_dbname, user=settings.pgvector_user,
            password=settings.pgvector_password, connect_timeout=2,
        )
        conn.close()
        return True
    except Exception:
        return False


_PGVECTOR_AVAILABLE = _pgvector_reachable()


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_pgvector: needs a live reachable Postgres/pgvector instance "
        "(auto-skipped when one isn't available)",
    )


def pytest_collection_modifyitems(config, items):
    if _PGVECTOR_AVAILABLE:
        return
    skip = pytest.mark.skip(reason="pgvector/Postgres not reachable at the configured host:port")
    for item in items:
        if "requires_pgvector" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def vs_test_prefix():
    """The throwaway-table prefix these tests write under — never a real
    EA collection name. Drops any leftover zzz_vstest_* tables before and
    after, so a previous crashed run can't leave stale state behind."""
    if not _PGVECTOR_AVAILABLE:
        pytest.skip("pgvector/Postgres not reachable")

    import psycopg2
    from advisor.config import settings

    def _drop_all():
        conn = psycopg2.connect(
            host=settings.pgvector_host, port=settings.pgvector_port,
            dbname=settings.pgvector_dbname, user=settings.pgvector_user,
            password=settings.pgvector_password,
        )
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_name LIKE %s",
                (f"{_VS_TEST_PREFIX}%",),
            )
            for (name,) in cur.fetchall():
                cur.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
        conn.close()

    _drop_all()
    yield _VS_TEST_PREFIX
    _drop_all()


class _FakeEmbeddingProvider:
    """A tiny deterministic EmbeddingProvider — avoids loading EA's real
    sentence-transformers model (slow, and irrelevant to what these tests
    verify: DDL/SQL shape, extra-column round-tripping, filter DSL
    behavior — none of which depend on real embedding quality)."""

    def embed_texts(self, texts):
        import numpy as np
        return np.array([self._vec(t) for t in texts], dtype="float32")

    def embed_query(self, text):
        import numpy as np
        return np.array(self._vec(text), dtype="float32")

    @staticmethod
    def _vec(text: str):
        # A cheap hash-based pseudo-embedding — distinct texts get distinct
        # (deterministic) vectors, enough to exercise real ORDER BY distance
        # behavior without a real model.
        import hashlib
        h = hashlib.sha256(text.encode()).digest()
        return [b / 255.0 for b in h[:32]] * 12  # 32*12 = 384 dims


@pytest.fixture
def ea_vs_store(vs_test_prefix):
    """A real PgVectorStore, EA-shaped (schema=None/unqualified, metric=l2)
    but scoped to zzz_vstest_-prefixed tables via table_name_map — so it
    exercises EA's exact configuration against the real live database
    without ever touching a real production collection name."""
    from trellis_vectorstore import PgVectorStoreConfig
    from trellis_vectorstore.pg import PgVectorStore
    from advisor.config import settings
    from advisor.vector_store_pg import EA_COLLECTION_SCHEMAS

    config = PgVectorStoreConfig(
        host=settings.pgvector_host, port=settings.pgvector_port,
        dbname=settings.pgvector_dbname, user=settings.pgvector_user,
        password=settings.pgvector_password, schema=None,
        max_connections=5, ef_search=settings.pgvector_ef_search,
    )
    table_name_map = {
        "pyegeria": f"{vs_test_prefix}pyegeria",
        "pyegeria_cli": f"{vs_test_prefix}pyegeria_cli",
        "plain": f"{vs_test_prefix}plain",
    }
    collection_schemas = {
        f"{vs_test_prefix}pyegeria": EA_COLLECTION_SCHEMAS["pyegeria"],
        f"{vs_test_prefix}pyegeria_cli": EA_COLLECTION_SCHEMAS["pyegeria_cli"],
    }
    store = PgVectorStore(
        config, metric="l2", embeddings=_FakeEmbeddingProvider(),
        collection_schemas=collection_schemas, table_name_map=table_name_map,
    )
    store.connect()
    yield store
    store.disconnect()
