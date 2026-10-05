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

## Addendum 2026-10-05: registry open log, CLI line, builder checklist

Trigger: a builder command in a worktree (no `.env`, so the default shared
Postgres) created `catalogue_commit_proofs` in the shared registry. The test
guard did not apply because it was a command, not a test.

- `resource_explorer/registry_label.py`: `describe_registry(url)` returns
  `registry: localhost:5442/egeria_advisor (shared) schema=resource_explorer`,
  `registry: host:port/db schema=...` or `registry: sqlite:///<basename>`.
  Host and database only; no user, password, query string or directory.
- `ProjectRegistry._log_open`: one INFO line per distinct registry URL per
  process (servers build a registry per request, so not per construction or
  query). Also fixed the pre-existing `registry_init` timing line, which logged
  the full `database_url` INCLUDING the default password; it now logs the label.
- CLI root callback prints the same line once per invocation to stderr (stdout
  stays clean for piping). It prints for every command, including ones that
  never open the registry. Not a refusal: 8810 and 8813 use the default.
- New guard test `test_default_config_without_env_file_fails_closed`: no env var,
  `.env` disabled, `ProjectRegistry()` with no arguments reaches the connect
  hook and is refused before schema migration (FAKE connect; never real).
  Red-run with the guard's `check()` disabled: 5 guard tests fail, including it.
- Tests: `tests/test_registry_open_log.py`, `tests/test_cli_registry_line.py`.
- Docs: `docs/BUILDER-BRIEF-CHECKLIST.md` and the same line in the package CLAUDE.md Setup (no file citation there: the design-note reference test treats an uppercase .md name as a design note).

Known limit, unchanged: the guard only protects pytest. A non-test command in a
worktree is only made visible (the `registry:` line), not blocked.

## Addendum 2026-10-05: PGVECTOR schema gap closed

The "known gap" above (a raw connection that writes the real schema by qualified
name) is closed for the one case that mattered: a `PgVectorStore` built on the
DEFAULT (shared) schema.

Audit table row: PGVECTOR_* raw psycopg2 vector store, default schema
`resource_explorer` -> COVERED.

- `tests/shared_registry_guard.py`: `install()` wraps `PgVectorStore.__init__`
  (construction only builds config, never connects) and `check_vector_schema`
  raises `SharedRegistryAccessError` naming `PGVECTOR_SCHEMA` and the test when
  the resolved schema equals `PgVectorConfig`'s declared default. An explicit
  `schema="resource_explorer"` is refused the same way. Any other name is a
  test's own override and is left alone. `RE_TESTS_ALLOW_SHARED_REGISTRY=1` and
  `GITHUB_ACTIONS=true` exempt it, as for the connect guard.
- `tests/conftest.py`: autouse `isolate_pgvector_schema` sets `PGVECTOR_SCHEMA`
  to `resource_explorer_test_<pid>_v<n>` per test. It is lazy: the env var
  connects to nothing; the store creates the schema itself on connect, and the
  fixture drops it at teardown only if a store was actually built on it and
  pgvector is reachable. The orphan sweeper now also recognises `<pid>_v<n>`.
- The raw-psycopg2 allowance for the setup connection (`pg_test_schema`) stays.
- Tests: `tests/test_shared_registry_guard.py` (FAKE connect only; refusal,
  explicit arg, scratch name, own override, opt-in/CI exemptions).

Not run by the builder (pgvector unreachable, PGVECTOR_PORT=1): per-test scratch
schema creation and DROP at teardown against a real Postgres, and a real default
store connecting under the scratch schema. The full suite on a pgvector-reachable
machine/CI verifies them.
