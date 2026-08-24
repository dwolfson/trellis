"""Observed cost against declared cost — the check for a class of bug no test caught.

Three cost mis-declarations surfaced in one week and every one was a
*declaration* disagreeing with *behaviour*, which no unit test can see:

  * repo_classification declared fetch_cost="none" and called the GitHub API
    (~10 min/repo), against a tier whose defining property is zero fetch.
  * repo_manifest_parse declared compute_cost="medium" and measures "low", so
    max_compute_cost="low" runs excluded it from the tier it was built for.
  * A timing was reported for resolve_doc_locations() when the thing that runs
    is build_report() — out by 8x, in the flattering direction.

The existing zero-fetch guard could not catch the first: it checks
`requires_resources`, not `fetch_cost`, so a step satisfies it while opening
sockets.
"""
from __future__ import annotations

import socket
import time

import pytest

from resource_explorer.surveyors import step_cost_observer as sco
from resource_explorer.surveyors.step_cost_observer import Observation, _disagreement


class TestTheUnarguableCase:
    def test_a_zero_fetch_step_that_connects_is_flagged(self):
        d = _disagreement(Observation("s", 0.5, 1, "none", "low"))
        assert "fetch_cost='none'" in d and "1 connection" in d

    def test_a_zero_fetch_step_that_does_not_connect_agrees(self):
        assert _disagreement(Observation("s", 0.5, 0, "none", "low")) == ""

    def test_an_honest_fetching_declaration_agrees(self):
        assert _disagreement(Observation("s", 20.0, 5, "api_heavy", "medium")) == ""


class TestWallClockIsOnlyComputeWhenNothingFetched:
    """Caught by running the check against repo_classification: 20.1s, flagged
    for declaring compute_cost='low', when ~all of it was five GitHub round
    trips. Wall clock proxies compute only when nothing was fetched. A check
    that cries wolf on an honest declaration is a check that gets switched
    off."""

    def test_a_slow_fetching_step_is_not_flagged_for_compute(self):
        d = _disagreement(Observation("s", 20.1, 5, "api_heavy", "low"))
        assert "compute_cost" not in d, (
            "20s of network wait is not evidence about compute_cost — this was a "
            "real false positive on an honest declaration"
        )

    def test_a_slow_step_with_no_connections_is_flagged(self):
        d = _disagreement(Observation("s", 20.1, 0, "none", "low"))
        assert "compute_cost='low'" in d and "no connections" in d

    def test_over_declaring_is_reported_too(self):
        """repo_manifest_parse's 'medium' excluded it from the cheap tier it was
        added to serve, so over-declaring is not the harmless direction."""
        d = _disagreement(Observation("s", 0.2, 0, "none", "medium"))
        assert "over-declar" in d


class TestItObservesRatherThanCorrects:
    def test_the_observation_carries_both_numbers(self):
        """Recording only the observed value would erase the disagreement,
        which is the finding."""
        obs = Observation("s", 1.0, 3, "none", "low")
        assert obs.declared_fetch == "none" and obs.connects == 3

    def test_nothing_in_the_module_writes_a_declaration(self):
        """Auto-correcting would have silently absorbed the repo_classification
        bug — a step that suddenly fetches is sometimes a regression to see,
        not a label to rewrite."""
        import pathlib
        src = pathlib.Path(sco.__file__).read_text()
        for writer in ("STEP_REGISTRY[", "fetch_cost =", "compute_cost ="):
            assert writer not in src, f"the observer must not write declarations: {writer}"


class TestMeasurement:
    def test_it_times_the_block(self):
        with sco.observe("s", "none", "low") as out:
            time.sleep(0.05)
        assert out[0].elapsed >= 0.05

    def test_it_counts_a_real_connection(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        try:
            with sco.observe("s", "none", "low") as out:
                socket.create_connection(("127.0.0.1", port), timeout=2).close()
        finally:
            srv.close()
        assert out[0].connects >= 1
        assert "fetch_cost='none'" in out[0].disagreement

    def test_a_raising_step_is_still_measured(self):
        """A step that fails after 90 seconds of network calls is exactly the
        case worth having a number for."""
        with pytest.raises(ValueError):
            with sco.observe("s", "none", "low") as out:
                raise ValueError("boom")
        assert out and out[0].elapsed >= 0


class TestFirstIsAboutTheStepNotTheRepo:
    """Scoped per-slug, the loud first-observation fired for every repo in a
    corpus run — 189 lines across 21 repos, heading for ~540. A check that
    shouts on every row gets switched off, which is the failure this module's
    own docstring warns about. "Nobody has ever measured this step" is a fact
    about the step."""

    def test_a_never_measured_step_is_first(self, tmp_path):
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.surveyors import step_cost_observer as sco

        reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
        assert sco._step_ever_measured(reg, "some_new_step") is False

    def test_it_does_not_re_announce_for_a_second_repo(self, tmp_path):
        from resource_explorer.registry import Project, ProjectRegistry
        from resource_explorer.surveyors import step_cost_observer as sco

        reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
        for slug in ("a", "b"):
            reg.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/t/{slug}", collections=[]))
        obs = Observation("step_x", 0.1, 0, "none", "low")
        assert sco.record(reg, "a", obs) == sco.FIRST
        # Same step, different resource — no longer news.
        assert sco.record(reg, "b", obs) == sco.RECORDED
