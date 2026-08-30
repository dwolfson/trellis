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

import os

import pytest

# Per-process, NOT a single shared name. The fixture below drops this schema
# CASCADE at session start and teardown, so a fixed name meant any two
# overlapping pytest runs destroyed each other's data mid-test — one session's
# startup DROP wiping the other's tables while it was still using them.
#
# That produced a flake with no stable signature: whichever test happened to be
# touching the schema when the DROP landed failed, so it looked like a different
# problem each time (test_alias_and_group_on_conflict_paths, then
# test_ingest_then_query..., then a fixture ERROR, then
# test_metrics_collector_portability) and passed on every re-run in isolation.
# Reproduced deliberately 2026-08-24 by starting a second run 45s into a full
# suite. CI runs one session so it never saw this; it is a local-development
# failure only, which is the kind that gets dismissed as noise.
_TEST_SCHEMA_PREFIX = "resource_explorer_test"
_TEST_SCHEMA = f"{_TEST_SCHEMA_PREFIX}_{os.getpid()}"


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except (OSError, ProcessLookupError, PermissionError) as exc:
        return isinstance(exc, PermissionError)  # exists, not ours
    return True


def _sweep_orphan_test_schemas(cur) -> list[str]:
    """Drop `<prefix>_<pid>` schemas whose process is gone.

    Per-process names fix the collision but leak on a hard crash, since the
    teardown that would drop them never runs. Swept at session start rather
    than accumulating — and only for dead PIDs, so a concurrent run is never
    the thing being cleaned up. The bare legacy name is included: it predates
    the suffix and cannot belong to a live session.
    """
    cur.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name = %s OR schema_name LIKE %s",
        (_TEST_SCHEMA_PREFIX, f"{_TEST_SCHEMA_PREFIX}\_%"),
    )
    dropped = []
    for (name,) in list(cur.fetchall()):
        if name == _TEST_SCHEMA:
            continue
        suffix = name[len(_TEST_SCHEMA_PREFIX) + 1:]
        if name != _TEST_SCHEMA_PREFIX and not suffix.isdigit():
            continue    # not a session schema at all — `..._backup` is someone's
                        # deliberate copy, and destroying data this fixture does
                        # not own is precisely the bug being fixed here
        if suffix.isdigit() and _pid_alive(int(suffix)):
            continue                       # a live concurrent session — leave it
        cur.execute(f'DROP SCHEMA IF EXISTS "{name}" CASCADE')
        dropped.append(name)
    return dropped


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


def _egeria_reachable() -> bool:
    """Same posture as _pgvector_reachable() — a real Egeria platform is an
    external dependency this test suite must run without. Only checks basic
    HTTP reachability (a 401/403 is still "reachable"); the actual
    requires_egeria-marked tests do their own bearer-token auth."""
    try:
        import httpx
        from resource_explorer.config import get_config

        cfg = get_config().egeria
        resp = httpx.get(f"{cfg.platform_url}/servers", timeout=2, verify=False)
        return resp.status_code < 500
    except Exception:
        return False


_EGERIA_AVAILABLE = _egeria_reachable()


def pytest_addoption(parser):
    parser.addoption(
        "--corpus", action="store_true", default=False,
        help="run tests that assert over the live shared registry's actual "
             "contents (skipped by default — a concurrent survey in another "
             "session can turn them red in files nobody touched)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "requires_pgvector: needs a live reachable Postgres/pgvector instance "
        "(auto-skipped when one isn't available)",
    )
    config.addinivalue_line(
        "markers",
        "requires_egeria: needs a live reachable Egeria platform "
        "(auto-skipped when one isn't available)",
    )
    config.addinivalue_line(
        "markers",
        "corpus: asserts over whatever the LIVE shared registry happens to "
        "contain (skipped by default; --corpus to run)",
    )


#: Set in CI. Auto-skipping is right on a developer laptop with no services
#: running — but it means a CI job whose Postgres service failed to start, or
#: whose credentials are wrong, reports a green suite having silently run none
#: of the integration tier. That is the same blind spot the tier exists to
#: close, one level up: the tests that check production behaviour quietly not
#: running is indistinguishable from them passing.
#:
#: With RE_REQUIRE_POSTGRES=1 an unreachable instance is a hard error instead.
_REQUIRE_POSTGRES = os.environ.get("RE_REQUIRE_POSTGRES", "").strip() not in ("", "0", "false")


def pytest_collection_modifyitems(config, items):
    if _REQUIRE_POSTGRES and not _PGVECTOR_AVAILABLE:
        marked = sum(1 for i in items if "requires_pgvector" in i.keywords)
        pytest.exit(
            f"RE_REQUIRE_POSTGRES is set but Postgres is not reachable at the "
            f"configured host:port, so {marked} requires_pgvector test(s) would "
            f"have been silently skipped. Check the service container and the "
            f"PGVECTOR_* environment variables.",
            returncode=1,
        )

    #: Corpus tests assert over whatever the live shared registry HOLDS, not
    #: over fixtures. That is their value — `security_features` rendering as a
    #: bare empty card on 58 of 60 real repos is a fact no fixture would have
    #: produced — and it is also why they cannot run by default now that five
    #: sessions share one Postgres.
    #:
    #: Measured 2026-08-30: a peer session surveying `egeria_workspaces_git`
    #: caught it mid-run, in a state the security-features reader classifies
    #: into none of its three causes, and turned this suite red in a file that
    #: session had never touched. The worktree split partitions FILES; the
    #: registry is still shared, so data contention is untouched by it.
    #:
    #: Skipped rather than deleted, and opt-in rather than removed: run them
    #: with `--corpus` when the corpus is quiet, which is exactly when their
    #: answer means anything.
    skip_corpus = pytest.mark.skip(
        reason="asserts over the live shared registry — run with --corpus when "
               "no other session is surveying"
    )
    run_corpus = config.getoption("--corpus")

    skip_pgvector = pytest.mark.skip(reason="pgvector/Postgres not reachable at the configured host:port")
    skip_egeria = pytest.mark.skip(reason="Egeria platform not reachable at the configured platform_url")
    for item in items:
        if not _PGVECTOR_AVAILABLE and "requires_pgvector" in item.keywords:
            item.add_marker(skip_pgvector)
        if not _EGERIA_AVAILABLE and "requires_egeria" in item.keywords:
            item.add_marker(skip_egeria)
        if not run_corpus and "corpus" in item.keywords:
            item.add_marker(skip_corpus)


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
        orphans = _sweep_orphan_test_schemas(cur)
        if orphans:
            print(f"\n[conftest] swept {len(orphans)} orphaned test schema(s): "
                  f"{', '.join(orphans)}")
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


@pytest.fixture
def ephemeral_prefect(monkeypatch):
    """Force Prefect to run flows in-process, ignoring any configured server.

    Prefect's client honours PREFECT_API_URL, and it loads that from `.env`
    itself — so clearing os.environ is not enough, and a checkout whose .env
    points at a Prefect server that is not running fails every Prefect test
    with "Failed to reach API at http://localhost:4200/api/", which says
    nothing about the behaviour under test.

    Found exactly that way on 2026-08-27: the same tests passed in one checkout
    and failed in another, on ambient environment alone. Both the flow tests
    and the older integration tests depended on it.

    Modules opt in with:
        pytestmark = pytest.mark.usefixtures("ephemeral_prefect")
    """
    from prefect.settings import PREFECT_API_URL, temporary_settings

    for var in ("PREFECT_API_URL", "PREFECT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    with temporary_settings({PREFECT_API_URL: None}):
        yield
