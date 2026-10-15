"""The reader a user step is handed (`survey_step_host.step_reader`): read-only on both backends, whatever the step
sends through it, and no connection reachable from it.

SQLite tests run everywhere. The Postgres tests are `requires_pgvector`: they create and drop ONLY their own schema,
`resource_explorer_test_stepreader_<pid>` (a name the conftest's orphan sweep never matches), and never construct a
ProjectRegistry.
"""
from __future__ import annotations

import os
import sqlite3

import pytest

from resource_explorer.surveyors.survey_step_host import step_reader
from trellis_analytics.readers.ods import OdsUnreadable

REFUSED = (
    "select 1; delete from t",
    "select 1;",
    "select set_config('default_transaction_read_only','off',false)",
    "SELECT * FROM t; SET default_transaction_read_only = off",
    "attach database 'x' as y",
    "select 1 /* hidden */",
    "select 1 -- trailing",
    "select a into t2 from t",
    "pragma query_only = off",
    "with d as (delete from t returning a) select * from d",
)


def _reachable(root, limit: int = 4000):
    from tests.test_engine_host_library_steps import _reachable as walk

    return walk(root, limit)


@pytest.fixture
def sqlite_url(tmp_path):
    path = tmp_path / "ods.sqlite"
    c = sqlite3.connect(path)
    c.execute("CREATE TABLE t (a INTEGER)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()
    return f"sqlite:///{path}"


def _count(url) -> int:
    c = sqlite3.connect(url.removeprefix("sqlite:///"))
    try:
        return c.execute("SELECT count(*) FROM t").fetchone()[0]
    finally:
        c.close()


def test_sqlite_reads(sqlite_url):
    with step_reader(sqlite_url) as ods:
        assert ods.query("SELECT a FROM t WHERE a = ?", (1,)) == [{"a": 1}]
        assert ods.query("select 'a;b' as s") == [{"s": "a;b"}]      # a ';' inside a literal is fine


@pytest.mark.parametrize("sql", REFUSED)
def test_sqlite_refuses_anything_but_one_plain_select(sqlite_url, sql):
    with step_reader(sqlite_url) as ods:
        with pytest.raises((ValueError, OdsUnreadable)):
            ods.query(sql)
    assert _count(sqlite_url) == 1


def test_sqlite_attach_read_write_is_refused_even_past_the_text_check(sqlite_url, tmp_path):
    """The connection's own guard (authorizer, query_only) refuses what the text check would have let through."""
    from resource_explorer.surveyors.survey_step_host import _execute_read_only, _open_read_only

    conn, pg = _open_read_only(sqlite_url)
    try:
        for sql in (f"ATTACH DATABASE 'file:{tmp_path / 'ods.sqlite'}?mode=rw' AS w", "PRAGMA query_only = OFF",
                    "DELETE FROM t", "CREATE TABLE z (a)"):
            with pytest.raises(Exception):
                _execute_read_only(conn, pg, sql, ())
    finally:
        conn.close()
    assert _count(sqlite_url) == 1


def test_sqlite_no_connection_registry_or_url_is_reachable(sqlite_url):
    from resource_explorer.registry import ProjectRegistry

    with step_reader(sqlite_url) as ods:
        objs = _reachable(ods)
    path = sqlite_url.removeprefix("sqlite:///")
    assert not [o for o in objs if isinstance(o, sqlite3.Connection)]
    assert not [o for o in objs if isinstance(o, ProjectRegistry)]
    assert not [o for o in objs if isinstance(o, str) and path in o]


def test_the_reader_stops_with_its_block(sqlite_url):
    import threading

    before = threading.active_count()
    with step_reader(sqlite_url) as ods:
        ods.query("select 1 as x")
    assert threading.active_count() == before
    with pytest.raises(OdsUnreadable):
        ods.query("select 1 as x")


# ── Postgres ──────────────────────────────────────────────────────────────────

@pytest.fixture
def pg_url():
    import psycopg2

    from tests.conftest import _PGVECTOR_AVAILABLE

    if not _PGVECTOR_AVAILABLE:
        pytest.skip("pgvector/Postgres not reachable")
    from resource_explorer.config import get_config

    cfg = get_config().pgvector
    schema = f"resource_explorer_test_stepreader_{os.getpid()}"
    admin = psycopg2.connect(host=cfg.host, port=cfg.port, dbname=cfg.dbname, user=cfg.db_user,
                             password=cfg.password, options=f"-csearch_path={schema}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        cur.execute(f'CREATE SCHEMA "{schema}"')
        cur.execute(f'CREATE TABLE "{schema}".t (a INTEGER)')
        cur.execute(f'INSERT INTO "{schema}".t VALUES (1)')
    url = (f"postgresql://{cfg.db_user}:{cfg.password}@{cfg.host}:{cfg.port}/{cfg.dbname}"
           f"?options=-csearch_path%3D{schema}")
    try:
        yield url, admin, schema
    finally:
        with admin.cursor() as cur:
            cur.execute(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def _pg_count(admin, schema) -> int:
    with admin.cursor() as cur:
        cur.execute(f'SELECT count(*) FROM "{schema}".t')
        return cur.fetchone()[0]


@pytest.mark.requires_pgvector
def test_pg_reads(pg_url):
    url, _admin, _schema = pg_url
    with step_reader(url) as ods:
        assert ods.query("SELECT a FROM t WHERE a = ?", (1,)) == [{"a": 1}]


@pytest.mark.requires_pgvector
@pytest.mark.parametrize("sql", REFUSED)
def test_pg_refuses_anything_but_one_plain_select(pg_url, sql):
    url, admin, schema = pg_url
    with step_reader(url) as ods:
        with pytest.raises((ValueError, OdsUnreadable)):
            ods.query(sql)
        # and the session is still read-only afterwards: the set_config sequence had no effect
        with pytest.raises((ValueError, OdsUnreadable)):
            ods.query("select 1; delete from t")
    assert _pg_count(admin, schema) == 1


@pytest.mark.requires_pgvector
def test_pg_set_config_then_a_write_has_no_effect_even_past_the_text_check(pg_url):
    """Each query runs in its own READ ONLY transaction that is rolled back, so a set_config that slipped past the
    text check is undone and a data-modifying statement fails."""
    from resource_explorer.surveyors.survey_step_host import _execute_read_only, _open_read_only

    url, admin, schema = pg_url
    conn, pg = _open_read_only(url)
    try:
        _execute_read_only(conn, pg, "select set_config('default_transaction_read_only','off',false)", ())
        with pytest.raises(Exception, match="read-only"):
            _execute_read_only(conn, pg, "with d as (delete from t returning a) select * from d", ())
        with pytest.raises(Exception, match="read-only"):
            _execute_read_only(conn, pg, "select 1; delete from t", ())
    finally:
        conn.close()
    assert _pg_count(admin, schema) == 1


@pytest.mark.requires_pgvector
def test_pg_no_connection_or_url_is_reachable(pg_url):
    import psycopg2.extensions

    url, _admin, _schema = pg_url
    with step_reader(url) as ods:
        objs = _reachable(ods)
    assert not [o for o in objs if isinstance(o, psycopg2.extensions.connection)]
    assert not [o for o in objs if isinstance(o, str) and ("advisor@" in o or "search_path" in o)]
