"""Shared pytest configuration — real (non-mocked) integration test tier.

Neither Resource Explorer nor Egeria Advisor had any real test coverage of
their data-store code before this (both fully mock/manual-script-only) —
migration plan Phase 8 fixes that here. `requires_pgvector`-marked tests need
a live reachable Postgres/pgvector instance; they're auto-skipped (not
errored) when one isn't available, so the rest of the suite stays runnable
with no external services, exactly like every other test in this repo.

Integration tests never touch the real `resource_explorer` schema — that
holds real migrated production data (registry + vectors for the 7 real
projects). Everything here runs against a dedicated, throwaway
`resource_explorer_test` schema, dropped and recreated once per test
session.
"""
from __future__ import annotations

import pytest

_TEST_SCHEMA = "resource_explorer_test"


def _pgvector_reachable() -> bool:
    try:
        import psycopg2
        from resource_explorer.config import get_config

        cfg = get_config().pgvector
        conn = psycopg2.connect(
            host=cfg.host, port=cfg.port, dbname=cfg.dbname,
            user=cfg.db_user, password=cfg.password, connect_timeout=2,
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


@pytest.fixture(scope="session")
def pg_test_schema():
    """The throwaway schema name integration tests write to — created fresh
    (drop-then-create) once per test session, dropped again at teardown."""
    if not _PGVECTOR_AVAILABLE:
        pytest.skip("pgvector/Postgres not reachable")

    import psycopg2
    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    conn = psycopg2.connect(
        host=cfg.host, port=cfg.port, dbname=cfg.dbname,
        user=cfg.db_user, password=cfg.password,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{_TEST_SCHEMA}"')
    conn.close()

    yield _TEST_SCHEMA

    conn = psycopg2.connect(
        host=cfg.host, port=cfg.port, dbname=cfg.dbname,
        user=cfg.db_user, password=cfg.password,
    )
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{_TEST_SCHEMA}" CASCADE')
    conn.close()


@pytest.fixture
def pg_store(pg_test_schema):
    """A PgVectorStore pointed at the throwaway test schema — never the real
    resource_explorer schema."""
    from resource_explorer.vector_store_pg import PgVectorStore

    store = PgVectorStore(schema=pg_test_schema)
    store.connect()
    yield store
    store.disconnect()


@pytest.fixture
def pg_registry(pg_test_schema):
    """A ProjectRegistry backed by the throwaway test schema — uses the
    database_url override (added for this fixture; see registry.py) rather
    than the real config default, so it never touches production data."""
    from resource_explorer.config import get_config
    from resource_explorer.registry import ProjectRegistry

    cfg = get_config().pgvector
    url = (
        f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.dbname}"
        f"?options=-csearch_path%3D{pg_test_schema}"
    )
    return ProjectRegistry(database_url=url)
