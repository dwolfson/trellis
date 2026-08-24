"""A connection severed while idle in the pool must not fail the next caller.

Observed 2026-08-20: a background org-import batch died with
`psycopg2.OperationalError: server closed the connection unexpectedly` and failed
to register docling-graph. Nothing on the Postgres side closed it — the container
had been up 17 hours without restarting, `idle_session_timeout` is 0, and it was
at 25 of 1000 connections. This is known Egeria-side behaviour against the shared
instance and is being fixed upstream.

Which is exactly why this belongs here rather than being left to that fix. RE
cannot control when the drop happens, but it turned a transient drop into a lost
registration by handing out a pooled connection it had never checked. With
pre-ping the drop is a reconnect, and the upstream fix stops being load-bearing
for us.
"""
from __future__ import annotations

import pytest
import sqlalchemy

from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


def test_engine_validates_pooled_connections(registry):
    assert registry.engine.pool._pre_ping is True


def test_connections_do_not_outlive_the_recycle_window(registry):
    """A half-open connection can still answer a ping. Recycling bounds how long
    one may live regardless of whether it looks alive."""
    assert registry.engine.pool._recycle == 1800


def test_a_severed_connection_is_replaced_rather_than_handed_out(tmp_path):
    """The behaviour, not the flag: kill the pooled connection underneath the
    pool, then make an ordinary call and expect it to succeed.

    Uses SQLite (the pool machinery being exercised is SQLAlchemy's, not the
    driver's) and closes the real DBAPI connection out from under the pool,
    which is what a severed TCP connection looks like from here.
    """
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))

    # Take a connection, keep the underlying DBAPI handle, return it to the pool.
    conn = reg.engine.raw_connection()
    dbapi = conn.driver_connection
    conn.close()

    # Sever it while it sits in the pool.
    dbapi.close()

    # Without pre-ping this raises; with it, the pool discards and replaces.
    assert reg.get("p") is not None


def test_without_pre_ping_the_same_scenario_fails(tmp_path):
    """The control. If this ever stops raising, the test above proves nothing —
    the scenario would be surviving for some unrelated reason."""
    reg = ProjectRegistry(db_path=str(tmp_path / "t2.db"))
    reg.add(Project(slug="p", display_name="P", github_url="u", description=""))

    reg.engine = sqlalchemy.create_engine(reg.database_url)  # no pre_ping
    conn = reg.engine.raw_connection()
    dbapi = conn.driver_connection
    conn.close()
    dbapi.close()

    with pytest.raises(Exception):
        reg.get("p")
