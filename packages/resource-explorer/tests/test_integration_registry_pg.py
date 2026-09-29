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


class TestRegistryConstructionIsCheapOnAWarmProcess:
    """2026-09-29 per-request-latency investigation
    (docs/design-notes/PER-REQUEST-SERVER-LATENCY-IMPLEMENTED.md): every
    `ProjectRegistry()` construction re-ran `_init_schema` — ~150
    CREATE TABLE/ALTER TABLE/CREATE INDEX statements — against Postgres,
    measured directly at 250-470ms EVERY time, not just cold. Almost every
    web route does `registry = ProjectRegistry()` fresh, so this landed on
    every request. Fixed by caching the Engine and an "already verified"
    flag per `database_url` at the class level, so a process only pays this
    once per URL. These tests pin that behaviour directly against real
    Postgres rather than timing it, which would be flaky."""

    def test_second_construction_for_the_same_url_skips_schema_init(self, pg_test_schema, monkeypatch):
        from resource_explorer.config import get_config
        from resource_explorer.registry import ProjectRegistry

        cfg = get_config().pgvector
        url = (f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}"
               f"/{cfg.dbname}?options=-csearch_path%3D{pg_test_schema}")

        # `pg_test_schema` is session-scoped (one throwaway schema, reused by
        # every integration test), so an earlier test in this same session
        # may already have constructed a `ProjectRegistry` against this exact
        # URL and populated the class-level cache. Clear this URL's entries
        # so "first ever construction" is deterministic regardless of test
        # order, rather than asserting the process-wide cache is untouched.
        ProjectRegistry._pg_engine_cache.pop(url, None)
        ProjectRegistry._pg_schema_ready.discard(url)

        calls = []
        real_init_schema = ProjectRegistry._init_schema

        def _counting_init_schema(self):
            calls.append(1)
            return real_init_schema(self)

        monkeypatch.setattr(ProjectRegistry, "_init_schema", _counting_init_schema)

        first = ProjectRegistry(database_url=url)
        second = ProjectRegistry(database_url=url)

        assert len(calls) == 1, "second construction re-ran _init_schema"
        assert first.engine is second.engine, "second construction opened its own pool"
        assert url in ProjectRegistry._pg_schema_ready


class TestDatabaseSurveysCacheIsInstanceScopedAndWriteInvalidated:
    """2026-09-29: profiling one board's `/survey-results` request showed
    `get_database_surveys` (fetches every historical survey's full
    `survey_data` blob) called 5 times for the same slug within a single
    request — `_credential_capability_results` deliberately searches every
    stored survey (its own docstring explains why), but nothing stopped
    five separate callers each re-running that same full fetch. Cached
    per-`ProjectRegistry`-instance; these tests pin the two properties that
    matter: repeat reads within one instance don't re-query, and a write
    through the same instance is never served stale."""

    @pytest.fixture
    def pg_surveyed_database(self, pg_registry):
        from resource_explorer.registry import DatabaseEntity

        slug = "pg_itest_survey_cache_db"
        if pg_registry.get_database(slug) is None:
            pg_registry.register_database(DatabaseEntity(
                slug=slug, display_name="Survey Cache Test DB", db_type="postgresql",
                host="localhost", port=5432, database_name=slug,
            ))
        yield slug
        pg_registry.remove_database(slug)

    def test_repeat_reads_within_one_instance_do_not_requery(self, pg_registry, pg_surveyed_database, monkeypatch):
        from resource_explorer.registry import ConnectionWrapper

        pg_registry.record_database_survey(
            pg_surveyed_database, schema_count=1, table_count=1, column_count=1,
            survey_data={"credential_capability": {"visible": True}},
        )

        calls = []
        real_execute = ConnectionWrapper.execute

        def _counting_execute(self, sql, params=None):
            if "FROM database_surveys" in sql:
                calls.append(1)
            return real_execute(self, sql, params)

        monkeypatch.setattr(ConnectionWrapper, "execute", _counting_execute)

        first = pg_registry.get_database_surveys(pg_surveyed_database)
        second = pg_registry.get_database_surveys(pg_surveyed_database)

        assert len(calls) == 1, "second get_database_surveys() call re-queried Postgres"
        assert first == second

    def test_write_through_the_same_instance_is_not_served_stale(self, pg_registry, pg_surveyed_database):
        first = pg_registry.get_database_surveys(pg_surveyed_database)
        assert first == []
        pg_registry.record_database_survey(
            pg_surveyed_database, schema_count=1, table_count=2, column_count=3,
            survey_data={"credential_capability": {"visible": True}},
        )
        second = pg_registry.get_database_surveys(pg_surveyed_database)
        assert len(second) == 1, (
            "get_database_surveys served a cached empty result after a "
            "write through the same ProjectRegistry instance"
        )

    def test_get_latest_database_survey_uses_a_limit_1_query(self, pg_registry, pg_surveyed_database):
        """A dedicated query, not `get_database_surveys(...)[0]` — see that
        method's own docstring for why (profiled: 700-900ms vs ~30ms on a
        heavily-surveyed database)."""
        pg_registry.record_database_survey(
            pg_surveyed_database, schema_count=1, table_count=1, column_count=1,
            survey_data={"a": 1}, surveyed_at="2026-01-01T00:00:00",
        )
        pg_registry.record_database_survey(
            pg_surveyed_database, schema_count=2, table_count=2, column_count=2,
            survey_data={"b": 2}, surveyed_at="2026-01-02T00:00:00",
        )
        latest = pg_registry.get_latest_database_survey(pg_surveyed_database)
        assert latest["surveyed_at"] == "2026-01-02T00:00:00"
