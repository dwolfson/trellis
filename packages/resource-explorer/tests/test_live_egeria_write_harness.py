"""Tests for the phase-4 live-write harness itself (fixture + marker/gate).

Two tiers, deliberately kept apart:

  * `TestGateLogicIsMocked` — the marker/gate decision, exercised with
    mocked inputs. Runs unconditionally, in CI, with no Egeria anywhere
    nearby. This is what proves a plain `pytest tests/` invocation can never
    accidentally run a write-capable test just because Egeria happens to be
    reachable that day.
  * `TestLiveSmoke` — the one real end-to-end proof the harness itself
    works: catalogue, do nothing, tear down. Marked `live_egeria_writes`, so
    it is skipped by everything except a deliberate `--live-egeria-writes`
    run that has already gone through live-peer coordination (see
    tests/live_egeria_write_fixtures.py's module docstring). This is NOT a
    Path B2/Path A/C live test — those are phases 5-6, out of scope here.
"""
from __future__ import annotations

import pytest

from tests.conftest import _live_egeria_writes_should_skip


class TestGateLogicIsMocked:
    """`_live_egeria_writes_should_skip` is the pure function `pytest_
    collection_modifyitems` calls to decide whether to skip a
    `live_egeria_writes`-marked test. Testing it directly, with both inputs
    supplied by hand, is what "using mocks for the Egeria-facing calls"
    means for this piece of the harness — there is no Egeria-facing call
    here at all, which is the point: the gate must not need one to prove
    itself correct.
    """

    def test_unreachable_egeria_always_skips_even_with_the_flag(self):
        """The flag alone must never be read as "try anyway" — an unreachable
        platform has to skip cleanly, not attempt a write and blow up with a
        connection error mid-test."""
        assert _live_egeria_writes_should_skip(egeria_available=False, flag_enabled=True) is True

    def test_reachable_egeria_alone_still_skips_without_the_flag(self):
        """This is the property requires_egeria alone does NOT give you: a
        plain `pytest tests/` run, on a laptop where Egeria happens to be up,
        must not silently start writing to it."""
        assert _live_egeria_writes_should_skip(egeria_available=True, flag_enabled=False) is True

    def test_both_reachable_and_flagged_runs(self):
        assert _live_egeria_writes_should_skip(egeria_available=True, flag_enabled=True) is False

    def test_neither_condition_skips(self):
        assert _live_egeria_writes_should_skip(egeria_available=False, flag_enabled=False) is True

    def test_the_marker_is_registered(self, pytestconfig):
        """A registered marker with 'strict-markers' semantics would otherwise
        warn/fail on first use; confirm the marker line actually exists on
        this config rather than only in conftest.py's source."""
        lines = pytestconfig.getini("markers")
        assert any(line.startswith("live_egeria_writes:") for line in lines), (
            "live_egeria_writes must be registered via addinivalue_line in "
            "pytest_configure, or the marker on TestLiveSmoke below would warn "
            "as unknown"
        )


@pytest.mark.live_egeria_writes
class TestLiveSmoke:
    """The one live proof this phase asks for: catalogue a throwaway
    database + filesystem element in dev Egeria via `live_egeria_write_
    target`, assert the fixture actually gave back GUIDs, and let its own
    teardown tear down and verify absence. No Path B2/A/C behaviour is
    exercised — that is phases 5-6's job.
    """

    def test_catalogue_and_teardown_round_trip(self, live_egeria_write_target):
        target = live_egeria_write_target

        assert target.database_guid, "fixture did not return a database GUID"
        assert target.filesystem_guid, "fixture did not return a filesystem GUID"
        assert target.server_guid, "fixture did not return a server GUID"

        # Every catalogued name must carry the collision-proof prefix — this
        # is the property the module docstring's "collision safety" section
        # promises, checked rather than assumed.
        for name in (
            target.server_qualified_name,
            target.database_qualified_name,
            target.filesystem_qualified_name,
        ):
            assert name.startswith("test-fixture-phase4-"), (
                f"{name!r} does not carry the expected test-fixture prefix — "
                "a concurrent run could collide with a real element"
            )

        # Deliberately does nothing else with the elements: this test exists
        # to prove the harness (catalogue -> yield -> teardown -> verify
        # absence) is correct, not to run a survey against them.
