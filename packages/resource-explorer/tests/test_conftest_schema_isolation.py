"""The test schema must be per-process.

A single shared `resource_explorer_test` schema, dropped CASCADE at session
start and teardown, meant two overlapping pytest runs destroyed each other's
data mid-test. The flake had no stable signature — whichever test was touching
the schema when the other session's DROP landed failed — so it read as noise
and passed on every re-run in isolation.
"""
from __future__ import annotations

import os

from tests import conftest as C


class TestSchemaNameIsPerProcess:
    def test_the_schema_name_carries_this_pid(self):
        assert C._TEST_SCHEMA == f"{C._TEST_SCHEMA_PREFIX}_{os.getpid()}"
        assert C._TEST_SCHEMA != C._TEST_SCHEMA_PREFIX, (
            "a bare shared name is what two concurrent runs collided on"
        )


class TestTheSweepNeverEatsALiveSession:
    """Per-process names leak on a hard crash, so orphans are swept at session
    start. The sweep must distinguish 'process is gone' from 'process is busy'
    — dropping a live session's schema would recreate the original bug with
    extra steps."""

    class _Cur:
        def __init__(self, names):
            self._names, self.dropped = names, []

        def execute(self, sql, params=None):
            if sql.startswith("SELECT"):
                self._rows = [(n,) for n in self._names]
            elif "DROP SCHEMA" in sql:
                self.dropped.append(sql.split('"')[1])

        def fetchall(self):
            return self._rows

    def test_a_live_pids_schema_is_left_alone(self):
        mine = f"{C._TEST_SCHEMA_PREFIX}_{os.getpid()}"
        cur = self._Cur([mine])
        assert C._sweep_orphan_test_schemas(cur) == []
        assert cur.dropped == []

    def test_a_dead_pids_schema_is_dropped(self):
        dead = f"{C._TEST_SCHEMA_PREFIX}_999999"
        cur = self._Cur([dead])
        assert C._sweep_orphan_test_schemas(cur) == [dead]

    def test_the_legacy_bare_name_is_swept(self):
        """It predates the suffix, so it cannot belong to a live session."""
        cur = self._Cur([C._TEST_SCHEMA_PREFIX])
        assert C._sweep_orphan_test_schemas(cur) == [C._TEST_SCHEMA_PREFIX]

    def test_our_own_schema_is_never_swept(self):
        cur = self._Cur([C._TEST_SCHEMA])
        assert C._sweep_orphan_test_schemas(cur) == []

    def test_a_non_numeric_suffix_is_left_alone(self):
        """`..._backup` is not a dead process; it is someone's deliberate copy.
        Sweeping it would be this fixture destroying data it does not own —
        which is precisely the bug being fixed."""
        cur = self._Cur([f"{C._TEST_SCHEMA_PREFIX}_backup"])
        assert C._sweep_orphan_test_schemas(cur) == []
        assert cur.dropped == []
