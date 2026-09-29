"""The registry, against real Postgres — the divergences the FK pragma can't close.

Why this tier exists. Production runs the registry on Postgres; every other
registry test runs it on SQLite. That made SQLite a strictly *weaker* mirror of
production: a write SQLite accepts and Postgres rejects passes the whole suite
and fails live. Three incidents on record, all the same shape —

  * `remove()` never deleted five child tables; invisible on SQLite (no FK
    enforcement), a hard FK crash on Postgres (see registry.remove()'s comment)
  * `remove_database()` had the same deletion-order bug (its own comment)
  * 2026-08-23: three orphaned project_analysis_findings rows in the live
    Postgres for an unregistered slug, absorbed by a caller's broad
    except+log.warning so nothing surfaced

`PRAGMA foreign_keys=ON` (added 2026-08-23) closes the FK half on SQLite. It
cannot close the rest: Postgres has static column types where SQLite has
dynamic affinity, and stricter GROUP BY rules. Those need real Postgres, which
is what this file is.

Auto-skipped when Postgres isn't reachable, same posture as every other
integration test here — the suite still runs with no external services.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry

pytestmark = pytest.mark.requires_pgvector


@pytest.fixture
def pg_registry(pg_test_schema):
    """A registry pointed at the throwaway integration schema, never the real
    `resource_explorer` one (which holds live production data)."""
    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    url = (f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}"
           f"/{cfg.dbname}?options=-csearch_path%3D{pg_test_schema}")
    return ProjectRegistry(database_url=url)


@pytest.fixture
def pg_project(pg_registry):
    slug = "pg_itest_proj"
    if pg_registry.get(slug) is None:
        pg_registry.add(Project(slug=slug, display_name="PG Integration Test",
                                github_url="https://github.com/test/pg-itest",
                                collections=[]))
    yield slug
    pg_registry.remove(slug)


class TestForeignKeysAreReallyEnforced:
    """The SQLite pragma should now make these behave identically in both
    backends. That is the claim; this is where it is checked against the
    backend that was always strict."""

    def test_findings_for_an_unregistered_slug_are_refused(self, pg_registry):
        with pytest.raises(ValueError, match="no such project"):
            pg_registry.upsert_finding(
                "definitely_not_a_project", "ci_quality",
                [{"check_name": "x", "label": "y", "summary": "z"}])

    def test_metrics_for_an_unregistered_slug_are_refused(self, pg_registry):
        """The sibling guard, added after the FK pragma surfaced its absence."""
        with pytest.raises(ValueError, match="no such project"):
            pg_registry.upsert_metric(
                "definitely_not_a_project", "api_structure", {"symbol_count": 1})


class TestRemoveDeletesEveryChild:
    """registry.remove()'s own comment records five child tables it once failed
    to clean up — silently leaking orphans on SQLite, crashing on Postgres. On
    Postgres the FK is the assertion: if any child row survived, the parent
    DELETE would raise."""

    def test_remove_succeeds_with_children_in_every_table(self, pg_registry):
        slug = "pg_itest_cascade"
        pg_registry.add(Project(slug=slug, display_name="Cascade",
                                github_url="https://github.com/test/cascade",
                                collections=[]))
        pg_registry.upsert_file_inventory(slug, [("README.md", 10), ("src/a.py", 20)])
        pg_registry.upsert_dependencies(slug, [
            {"dep_name": "requests", "dep_version": "2.0", "ecosystem": "PyPI",
             "dep_type": "runtime", "source_file": "pyproject.toml"}])
        pg_registry.upsert_finding(slug, "ci_quality",
                                   [{"check_name": "c", "label": "pass", "summary": "s"}])
        pg_registry.upsert_metric(slug, "api_structure", {"symbol_count": 3})

        pg_registry.remove(slug)   # would raise on a missed child table

        assert pg_registry.get(slug) is None
        assert pg_registry.get_file_inventory(slug) == []
        assert pg_registry.query_dependencies(slug) == []


class TestPostgresStrictnessSqliteDoesNotHave:

    def test_history_group_by_runs_on_postgres(self, pg_registry, pg_project):
        """Postgres requires every selected column to be grouped or aggregated;
        SQLite does not. The history queries are the ones that GROUP BY, so
        they can parse and run on SQLite while being invalid Postgres — this
        executes them where that is actually checked."""
        pg_registry.upsert_metric(pg_project, "api_structure", {"symbol_count": 10},
                                  surveyed_at="2026-08-01T00:00:00")
        pg_registry.upsert_metric(pg_project, "api_structure", {"symbol_count": 20},
                                  surveyed_at="2026-08-02T00:00:00")
        history = pg_registry.query_metrics_history(pg_project, "api_structure", "symbol_count")
        assert [h["metric_value"] for h in history] == [10.0, 20.0]

    def test_a_non_numeric_metric_value_is_rejected(self, pg_registry, pg_project):
        """Static column types, the divergence no pragma can close: SQLite's
        dynamic affinity stores 'not-a-number' in a numeric column quite
        happily, Postgres refuses it."""
        with pytest.raises(Exception) as exc:
            with pg_registry._conn() as conn:
                conn.execute(
                    "INSERT INTO project_analysis_metrics "
                    "(project_slug, kind, surveyed_at, metric_name, metric_value) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    (pg_project, "k", "2026-01-01", "m", "not-a-number"))
        assert "ValueError" not in type(exc.value).__name__


class TestRemoveCannotForgetANewTable:
    """The structural guard for the bug above.

    remove() hand-lists its child DELETEs, so every table added later is one
    someone has to remember. Twice now nobody did. Rather than trust the list,
    ask Postgres which tables actually carry a foreign key to projects.slug and
    require remove() to handle all of them — the same "compare the registry
    against the surface that must expose it" shape as
    tests/test_reachability_audit.py.
    """

    def test_remove_deletes_from_every_table_with_a_fk(self, pg_registry, pg_test_schema):
        with pg_registry._conn() as conn:
            rows = conn.execute("""
                SELECT tc.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name
                 AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s
                  AND ccu.table_name = 'projects'
            """, (pg_test_schema,)).fetchall()
        referencing = sorted({r["table_name"] for r in rows})
        assert referencing, "no FKs found — the schema was not created as expected"

        import inspect
        from resource_explorer.registry import ProjectRegistry
        source = inspect.getsource(ProjectRegistry.remove)
        missing = [t for t in referencing if f"DELETE FROM {t} " not in source]
        assert not missing, (
            f"remove() does not delete from {missing}, which hold a foreign key to "
            "projects.slug — on Postgres removing a project with rows in those "
            "tables raises ForeignKeyViolation."
        )

    def test_rename_project_slug_covers_every_table_with_a_fk(self, pg_registry, pg_test_schema):
        """The same structural guard, for rename_project_slug()'s own
        enumeration (_PROJECT_SLUG_TABLES) — a table added later needs to be
        in both lists, and this catches the rename side forgetting one just
        as directly as the test above catches remove() forgetting one."""
        with pg_registry._conn() as conn:
            rows = conn.execute("""
                SELECT tc.table_name
                FROM information_schema.table_constraints tc
                JOIN information_schema.constraint_column_usage ccu
                  ON tc.constraint_name = ccu.constraint_name
                 AND tc.table_schema = ccu.table_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                  AND tc.table_schema = %s
                  AND ccu.table_name = 'projects'
            """, (pg_test_schema,)).fetchall()
        referencing = sorted({r["table_name"] for r in rows})
        assert referencing, "no FKs found — the schema was not created as expected"

        from resource_explorer.registry import ProjectRegistry
        missing = [t for t in referencing if t not in ProjectRegistry._PROJECT_SLUG_TABLES]
        assert not missing, (
            f"rename_project_slug()'s _PROJECT_SLUG_TABLES is missing {missing}, which "
            "hold a foreign key to projects.slug — a rename would leave those rows "
            "pointing at a slug that no longer exists."
        )


class TestRenameProjectSlugOnRealPostgres:
    """rename_project_slug()'s insert-new/update-children/delete-old
    ordering exists specifically to satisfy Postgres' FK enforcement
    (SQLite's PRAGMA mirrors it, but this is the backend the ordering was
    actually designed against)."""

    def test_rename_succeeds_with_fk_children_present(self, pg_registry):
        slug = "pg_itest_rename_src"
        new_slug = "pg_itest_rename_dst"
        for s in (slug, new_slug):
            existing = pg_registry.get(s)
            if existing:
                pg_registry.remove(s)
        pg_registry.add(Project(slug=slug, display_name="Rename Me",
                                github_url="https://github.com/test/rename-me",
                                collections=[]))
        pg_registry.upsert_file_inventory(slug, [("README.md", 10)])
        pg_registry.upsert_finding(slug, "ci_quality",
                                   [{"check_name": "c", "label": "pass", "summary": "s"}])

        try:
            pg_registry.rename_project_slug(slug, new_slug)  # would raise on FK violation
            assert pg_registry.get(slug) is None
            assert pg_registry.get(new_slug) is not None
            assert pg_registry.get_file_inventory(new_slug) == ["README.md"]
        finally:
            pg_registry.remove(new_slug) if pg_registry.get(new_slug) else None
            pg_registry.remove(slug) if pg_registry.get(slug) else None


class TestFindLatestDetailSurveyedAt:
    """2026-09-29 round 3 (docs/design-notes/PER-REQUEST-SERVER-LATENCY-
    ROUND-3-IMPLEMENTED.md): `find_latest_detail_surveyed_at` replaces
    `db_derived.py`'s `_resolve_table_surveyed_at` walk (one `query_detail_
    rows` call per candidate `surveyed_at`, newest first, until one is
    non-empty) with a single `MAX(surveyed_at)` query — provably
    equivalent per that method's own docstring, pinned here directly
    against real Postgres."""

    @pytest.fixture
    def pg_database(self, pg_registry):
        from resource_explorer.registry import DatabaseEntity

        slug = "pg_itest_find_latest_detail_db"
        if pg_registry.get_database(slug) is None:
            pg_registry.register_database(DatabaseEntity(
                slug=slug, display_name="Find Latest Detail Test DB", db_type="postgresql",
                host="localhost", port=5432, database_name=slug,
            ))
        yield slug
        pg_registry.remove_database(slug)

    def test_returns_none_when_the_table_has_no_rows_for_this_slug(self, pg_registry, pg_database):
        assert pg_registry.find_latest_detail_surveyed_at("database_tables", pg_database) is None

    def test_finds_the_only_surveyed_at(self, pg_registry, pg_database):
        pg_registry.write_detail_rows(
            "database_tables", pg_database, "2026-09-29T00:00:00", "local",
            [{"schema_name": "public", "table_name": "t1"}],
        )
        at = pg_registry.find_latest_detail_surveyed_at("database_tables", pg_database)
        assert at == "2026-09-29T00:00:00"

    def test_finds_the_newest_of_several_surveyed_ats(self, pg_registry, pg_database):
        for at in ("2026-09-27T00:00:00", "2026-09-29T00:00:00", "2026-09-28T00:00:00"):
            pg_registry.write_detail_rows(
                "database_tables", pg_database, at, "local",
                [{"schema_name": "public", "table_name": "t1"}],
            )
        found = pg_registry.find_latest_detail_surveyed_at("database_tables", pg_database)
        assert found == "2026-09-29T00:00:00"

    def test_a_run_that_never_touched_this_table_is_correctly_skipped(self, pg_registry, pg_database):
        """The exact property `_resolve_table_surveyed_at`'s walk existed
        for: a later run's own steps can genuinely never touch a structured
        table at all (a schema-only run writes no `database_table_activity`
        rows), and that must not shadow an earlier run that DID."""
        pg_registry.write_detail_rows(
            "database_table_activity", pg_database, "2026-09-27T00:00:00", "local",
            [{"schema_name": "public", "table_name": "t1", "rows_inserted": 5}],
        )
        # A later survey ran, but this particular table was never touched by
        # it — no row exists for "2026-09-29" in database_table_activity at all.
        found = pg_registry.find_latest_detail_surveyed_at("database_table_activity", pg_database)
        assert found == "2026-09-27T00:00:00"

    def test_require_any_non_null_skips_a_row_with_every_counter_null(self, pg_registry, pg_database):
        """The `database_table_activity`-specific case `require_measured_
        counter` exists for: a row can be written (the step ran) with every
        counter NULL (nothing was actually measured). That must not count
        as "this run has the answer" — the newer, unmeasured row must be
        skipped in favour of the older, real one."""
        pg_registry.write_detail_rows(
            "database_table_activity", pg_database, "2026-09-27T00:00:00", "local",
            [{"schema_name": "public", "table_name": "t1", "rows_inserted": 5}],
        )
        pg_registry.write_detail_rows(
            "database_table_activity", pg_database, "2026-09-29T00:00:00", "local",
            [{"schema_name": "public", "table_name": "t1"}],  # every counter NULL
        )
        found = pg_registry.find_latest_detail_surveyed_at(
            "database_table_activity", pg_database,
            require_any_non_null=("rows_inserted", "rows_updated", "rows_deleted",
                                   "seq_scan", "idx_scan"),
        )
        assert found == "2026-09-27T00:00:00", (
            "the newer, all-NULL-counter row was accepted as measured"
        )

    def test_resolve_table_surveyed_at_gives_identical_answers_to_the_old_walk(
        self, pg_registry, pg_database,
    ):
        """End to end through `db_derived._resolve_table_surveyed_at` itself
        (not just the registry method it now calls) — the exact bug shape
        the walk existed for, reproduced: an older run wrote
        `database_table_activity` rows with real counters; a newer run
        wrote NONE for this table at all (a schema-only run). The newer
        run's absence here must not shadow the older run's real answer."""
        from resource_explorer.surveyors.database.db_derived import _resolve_table_surveyed_at

        pg_registry.write_detail_rows(
            "database_table_activity", pg_database, "2026-09-27T00:00:00", "local",
            [{"schema_name": "public", "table_name": "t1", "rows_inserted": 5}],
        )
        at, rows = _resolve_table_surveyed_at(
            pg_registry, pg_database, "database_table_activity", None,
            require_measured_counter=True,
        )
        assert at == "2026-09-27T00:00:00"
        assert len(rows) == 1
        assert rows[0]["rows_inserted"] == 5
