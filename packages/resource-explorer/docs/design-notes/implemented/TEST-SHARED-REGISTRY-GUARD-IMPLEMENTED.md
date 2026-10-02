# Test guard: no pytest test may reach the shared registry (implemented 2026-10-02)

## Incident

A new test file set `REGISTRY_DATABASE_URL` (a temp SQLite file) in a fixture.
`resource_explorer.config.get_config()` had already been cached, so the env var
was ignored and the test opened the shared development Postgres
(`localhost:5442`, database `egeria_advisor`, schema `resource_explorer`), ran
the schema init and inserted two fake rows (`db_a`, `db_b`) into the real
`databases` table. `list_databases()` broke for the whole app until the rows
were deleted by hand.

## What was added

- `tests/shared_registry_guard.py`, installed from the top of `tests/conftest.py`
  at import (before conftest's own reachability probe). Two hooks, both at the
  connection itself, so a cached config cannot defeat them:
  - SQLAlchemy `do_connect` event on the `Engine` class: covers every engine in
    the process (registry, feedback store, metrics collector, leader election,
    Prefect flows), immediately before the DBAPI connect. Strict.
  - A `psycopg2.connect` wrapper for direct connections. Lenient (see below).
- `reset_cached_config` autouse fixture in conftest: `config._config = None`
  before and after every test, so a per-test `monkeypatch.setenv` is honoured.
- `tests/test_shared_registry_guard.py`: guard tests using a FAKE connect only.

## What counts as the shared registry

Derived from the config classes' declared defaults (`PgVectorConfig`,
`RegistryConfig`), never from the cached config or env, which is what failed:
a loopback host, port 5442, database `egeria_advisor`, with `search_path` other
than a throwaway test schema (`resource_explorer_test*`).

- SQLAlchemy path: a URL with no `search_path` also counts as shared.
- Raw `psycopg2.connect` with no `search_path` is allowed: conftest's probe and
  `pg_test_schema` fixture connect that way to create and drop the throwaway
  schema, and `--corpus` tests read through it. This is a known gap: a raw
  connection that then writes to the real schema by qualified name is not
  caught. The registry path, where the damage happened, is closed.

A refusal raises `SharedRegistryAccessError` naming the test
(`PYTEST_CURRENT_TEST`) and the opt-in.

## Opt-in and CI

- `RE_TESTS_ALLOW_SHARED_REGISTRY=1` lets a deliberate run through. Nobody sets
  it by default; coordinate with live peers first.
- CI (`.github/workflows/resource-explorer.yml`) is exempt via
  `GITHUB_ACTIONS=true`. Its Postgres service container uses the same
  `localhost:5442 / egeria_advisor / resource_explorer` coordinates as the dev
  instance and sets `REGISTRY_DATABASE_URL` to the real schema name, so the
  address alone cannot tell them apart; the container is created empty for the
  run and discarded. The workflow file is unchanged. Per-test schemas
  (`pg_registry`, `pg_store`) on a developer machine pass on their own, since
  their schema starts with `resource_explorer_test`.

## Not verified

A real CI run. The exemption relies on GitHub setting `GITHUB_ACTIONS=true`.
