"""The freshness gate on user-initiated analysis runs.

Measured 2026-09-10 over the 1,207 successful runs in `activity_log`: 20.7%
happened within five minutes of an identical prior run of the same analysis on
the same repo, and ~95% of those produced no different findings — a fifth of all
runs buying nothing, at up to 110s each.

Two decisions from the project owner shape what is tested here: **skip by
default** (not warn-and-run), and **leave the scheduler alone** — gating nightly
sweeps changes what "nightly" means, which is a different decision from sparing
someone a redundant click.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from resource_explorer.registry import Project
from resource_explorer.workflows.analysis import (
    _humanise_age, assess_freshness)


@pytest.fixture
def slug(request):
    import re as _re
    return "fr_" + _re.sub(r"[^a-z0-9]+", "_", request.node.name.lower())[:48]


@pytest.fixture
def reg(pg_registry, slug):
    pg_registry.add(Project(slug=slug, display_name=slug,
                            github_url=f"https://github.com/x/{slug}"))
    return pg_registry


def _log_run(reg, slug, analysis_id, *, minutes_ago=0, status="ok"):
    """One activity_log analysis_run row, back-dated."""
    from resource_explorer.activity_logger import log_analysis_run
    entry_id = log_analysis_run(reg, "repo", slug, slug, status,
                                f"ran {analysis_id}", analysis_id, published=None)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()
    with reg._conn() as c:
        c.execute("UPDATE activity_log SET ts = %s WHERE id = %s", (ts, entry_id))
    return entry_id


class TestTheThreeStates:
    def test_never_run_is_not_fresh(self, reg, slug):
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh and f.state == "never-run"
        assert "no recorded run" in f.reason("security_scan")

    def test_a_recent_run_is_fresh(self, reg, slug):
        _log_run(reg, slug, "security_scan", minutes_ago=5)
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert f.fresh and f.state == "fresh"
        assert "not running it again" in f.reason("security_scan")
        assert "force=true" in f.reason("security_scan")

    def test_an_old_run_is_stale(self, reg, slug):
        _log_run(reg, slug, "security_scan", minutes_ago=180)
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh and f.state == "stale"

    def test_the_threshold_is_the_boundary(self, reg, slug):
        _log_run(reg, slug, "security_scan", minutes_ago=30)
        assert assess_freshness(reg, "repo", slug, "security_scan",
                                max_age_seconds=3600).fresh
        assert not assess_freshness(reg, "repo", slug, "security_scan",
                                    max_age_seconds=600).fresh


class TestWhatMustNeverCountAsFresh:
    def test_a_failed_run_is_not_freshness(self, reg, slug):
        """Its data is the OLD data. Refusing to re-run after a failure is the
        one behaviour nobody would want."""
        _log_run(reg, slug, "security_scan", minutes_ago=1, status="error")
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh, "an errored run is being treated as fresh data"

    def test_a_recent_failure_re_runs_even_with_an_older_success(self, reg, slug):
        """The behaviour, stated deliberately rather than discovered.

        `get_analysis_last_run` keeps only the MOST RECENT run per analysis
        ("newest-first, so the first win stands"), so a failure hides the
        older success entirely and freshness cannot see it. Two readings are
        defensible — the 30-minute-old data IS still there — and this picks
        RE-RUN, because the action a person takes after a failure is to press
        Run, and a gate that answered "no need, it succeeded half an hour ago"
        would be refusing the one request that is obviously legitimate.

        Written the other way round first, asserting the older success should
        keep the gate closed; the failure of that test is what surfaced the
        choice.
        """
        _log_run(reg, slug, "security_scan", minutes_ago=30)
        _log_run(reg, slug, "security_scan", minutes_ago=1, status="error")
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh, (
            "a run whose latest attempt FAILED is being skipped as fresh — "
            "pressing Run after a failure must run")

    def test_a_future_timestamp_is_stale_not_infinitely_fresh(self, reg, slug):
        """Clock skew, or a future-dated row. Treating it as fresh would wedge
        the analysis into never running again, with no way to notice."""
        _log_run(reg, slug, "security_scan", minutes_ago=-600)
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh and f.state == "stale"

    def test_an_unparseable_timestamp_does_not_crash_or_grant_freshness(self, reg, slug):
        entry = _log_run(reg, slug, "security_scan", minutes_ago=5)
        with reg._conn() as c:
            c.execute("UPDATE activity_log SET ts = %s WHERE id = %s",
                      ("not-a-timestamp", entry))
        f = assess_freshness(reg, "repo", slug, "security_scan")
        assert not f.fresh and f.state == "never-run"


class TestDerivedAnalysesInheritFreshness:
    def test_the_diagram_is_fresh_because_the_recovery_ran(self, reg, slug):
        """`architecture_diagram` owns no steps — it derives from
        `architecture_recovery`'s. A recent run of the recovery makes the
        diagram's data current even though the diagram has never been run."""
        _log_run(reg, slug, "architecture_recovery", minutes_ago=3)
        f = assess_freshness(reg, "repo", slug, "architecture_diagram")
        assert f.fresh, "a derived analysis is not seeing its source's run"
        assert f.via == "architecture_recovery"
        assert "via 'architecture_recovery'" in f.reason("architecture_diagram")

    def test_a_stale_source_leaves_the_derived_stale(self, reg, slug):
        _log_run(reg, slug, "architecture_recovery", minutes_ago=300)
        assert not assess_freshness(reg, "repo", slug, "architecture_diagram").fresh

    def test_the_most_recent_of_the_two_wins(self, reg, slug):
        _log_run(reg, slug, "architecture_recovery", minutes_ago=300)
        _log_run(reg, slug, "architecture_diagram", minutes_ago=2)
        f = assess_freshness(reg, "repo", slug, "architecture_diagram")
        assert f.fresh and f.via == "architecture_diagram"

    def test_an_ordinary_analysis_does_not_inherit_from_anything(self, reg, slug):
        _log_run(reg, slug, "architecture_recovery", minutes_ago=1)
        assert not assess_freshness(reg, "repo", slug, "security_scan").fresh


class TestAgeIsReadable:
    @pytest.mark.parametrize("seconds,expected", [
        (5, "less than a minute ago"), (60, "1 minute ago"),
        (3599, "59 minutes ago"), (3600, "1 hour ago"),
        (86399, "23 hours ago"), (86400, "1 day ago"), (259200, "3 days ago"),
    ])
    def test_units_change_at_the_right_boundaries(self, seconds, expected):
        """The first version printed minutes at every scale and produced
        '1827 minutes ago', which a reader has to do arithmetic on."""
        assert _humanise_age(seconds) == expected


class TestTheGateIsWiredAndScopedCorrectly:
    @staticmethod
    def _route_uses(monkeypatch, reg):
        """Point the route's own `ProjectRegistry()` at the test schema.

        The route constructs its registry itself, and `pg_registry` is a
        throwaway schema reached through a `database_url` override — so without
        this the route looks in the real database and 404s on a project the
        fixture created. Patched at `resource_explorer.registry` because the
        route imports the name inside the function, so the lookup happens at
        call time.
        """
        import resource_explorer.registry as reg_mod
        monkeypatch.setattr(reg_mod, "ProjectRegistry", lambda *a, **k: reg)

    def test_the_run_route_declines_a_fresh_analysis(self, reg, slug, monkeypatch):
        """Behavioural, not structural. The first version of this asserted that
        `_assess_freshness` and `"skipped"` appeared in the route's SOURCE —
        which stayed true when the gate was disabled with `if False:`, so it
        passed against a completely ungated route. Found by sabotage."""
        import asyncio
        from resource_explorer.web.routes import projects

        self._route_uses(monkeypatch, reg)
        _log_run(reg, slug, "security_scan", minutes_ago=2)
        out = asyncio.run(projects.run_single_analysis(slug, "security_scan"))
        assert out["status"] == "skipped", (
            f"a run 2 minutes old was not declined: {out}")
        assert out["reason"] == "already-fresh"
        assert out["activity_id"] is None and out["run_id"] is None, (
            "a declined run still handed back ids, so the caller will poll for "
            "a run that was never started")
        assert "security_scan" in out["detail"]

    def test_force_runs_anyway(self, reg, slug, monkeypatch):
        """The override has to actually reach the queue, or the gate is a wall."""
        import asyncio
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.web.routes import projects

        enqueued = []
        monkeypatch.setattr(ProjectRegistry, "enqueue_run",
                            lambda self, kind, target, **kw: enqueued.append((kind, target))
                            or "run-forced")
        self._route_uses(monkeypatch, reg)
        _log_run(reg, slug, "security_scan", minutes_ago=2)
        out = asyncio.run(projects.run_single_analysis(slug, "security_scan", force=True))
        assert out["status"] == "started", f"force=true was still declined: {out}"
        assert enqueued, "force=true returned started but enqueued nothing"

    def test_a_stale_analysis_is_not_declined(self, reg, slug, monkeypatch):
        """The gate must not simply refuse everything."""
        import asyncio
        from resource_explorer.registry import ProjectRegistry
        from resource_explorer.web.routes import projects

        monkeypatch.setattr(ProjectRegistry, "enqueue_run",
                            lambda self, kind, target, **kw: "run-stale")
        self._route_uses(monkeypatch, reg)
        _log_run(reg, slug, "security_scan", minutes_ago=600)
        out = asyncio.run(projects.run_single_analysis(slug, "security_scan"))
        assert out["status"] == "started", f"a 10-hour-old run was declined: {out}"

    def test_the_scheduler_is_not_gated(self):
        """A project-owner decision, 2026-09-10. Gating nightly sweeps changes
        what 'nightly' means."""
        import inspect
        from resource_explorer import scheduler
        assert "assess_freshness" not in inspect.getsource(scheduler), (
            "the scheduler now consults freshness — scheduled sweeps were "
            "deliberately left ungated")

    def test_every_frontend_caller_of_the_run_route_handles_a_skip(self):
        """Derived, not listed. `activity_id` is null on a skip, so a caller
        that polls it regardless hangs forever. THREE functions reach this
        route and two of them share a byte-identical fetch block — the first
        version of this change patched one of that pair and would have left the
        other hanging."""
        import pathlib
        import re
        html = (pathlib.Path(__file__).resolve().parent.parent
                / "resource_explorer" / "web" / "static" / "index.html").read_text()
        html = re.sub(r"^\s*//.*$", "", html, flags=re.M)
        starts = [(m.start(), m.group(1))
                  for m in re.finditer(r"^(?:async )?function (\w+)\s*\(", html, re.M)]
        bodies = {}
        for i, (pos, name) in enumerate(starts):
            end = starts[i + 1][0] if i + 1 < len(starts) else len(html)
            bodies[name] = html[pos:end]

        callers = {n for n, b in bodies.items()
                   if re.search(r"/analyses/\$\{[^}]+\}/run", b)
                   and "_pollActivityUntilDone" in b}
        assert callers, "found no frontend callers of the run route — derivation broke"
        missing = sorted(n for n in callers if "_handleFreshnessSkip" not in bodies[n])
        assert not missing, (
            f"these poll activity_id without handling a skipped run, so a "
            f"declined run leaves the UI polling null forever: {missing}")

    def test_the_skip_offers_a_way_through(self):
        import pathlib
        html = (pathlib.Path(__file__).resolve().parent.parent
                / "resource_explorer" / "web" / "static" / "index.html").read_text()
        assert "force=true" in html, (
            "the frontend never sends force=true, so a reader who genuinely "
            "wants a re-run has no way to ask for one")
