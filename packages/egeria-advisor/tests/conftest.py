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

import os
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
    config.addinivalue_line(
        "markers",
        'live(reason="..."): needs a running service (Postgres, Egeria, MLflow or Phoenix). The reason '
        "is required and names the service. With EA_SKIP_LIVE=1 (CI, the gate) every live test is "
        "SKIPPED with that reason, so -rs lists it; it is never deselected silently.",
    )


# Phase 1 Q1 (2026-11-10). A test outside tests/unit that needs a service is marked live with its
# reason. CI and the gate set EA_SKIP_LIVE=1 and run with -rs, so each such test shows up as
# "SKIPPED live: <reason>" -- skipped with its reason rather than `-m "not live"`, which would
# deselect it and print nothing. Locally, without EA_SKIP_LIVE, live tests run (requires_pgvector
# still skips them when Postgres is unreachable).
_SKIP_LIVE = os.environ.get("EA_SKIP_LIVE") == "1"

# Tests under tests/unit that WRITE the shared database, marked live here (by file) rather than in
# the test files, which belong to other briefs. Found by Q1 running tests/unit against a throwaway
# Postgres: these two seed and delete rows (under dummy names) in a real database, so in the gate on
# laz they wrote the shared Postgres -- one of them RE's resource_explorer schema. Moving them onto a
# throwaway schema is a follow-up; until then they are live, and skipped with this reason under
# EA_SKIP_LIVE=1.
_LIVE_BY_FILE = {
    "tests/unit/test_code_intel_agent.py":
        "Postgres with RE's resource_explorer schema; seeds and deletes rows in resource_explorer.projects / "
        "project_code_symbols / project_code_relationships (slug test_code_intel_dummy)",
    "tests/unit/test_code_symbol_store.py":
        "Postgres; seeds and deletes rows in EA's code_symbols / code_relationships "
        "(collection test_collection_dummy)",
}


def pytest_collection_modifyitems(config, items):
    for item in items:
        rel = Path(str(item.fspath)).resolve().relative_to(project_root.resolve()).as_posix() \
            if str(item.fspath).startswith(str(project_root.resolve())) else ""
        if rel in _LIVE_BY_FILE and item.get_closest_marker("live") is None:
            item.add_marker(pytest.mark.live(reason=_LIVE_BY_FILE[rel]))
        marker = item.get_closest_marker("live")
        if marker is None:
            continue
        reason = marker.kwargs.get("reason") or (marker.args[0] if marker.args else "")
        if not str(reason).strip():
            raise pytest.UsageError(f"{item.nodeid}: @pytest.mark.live needs a reason naming the service")
        if _SKIP_LIVE:
            item.add_marker(pytest.mark.skip(reason=f"live: {reason}"))

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
