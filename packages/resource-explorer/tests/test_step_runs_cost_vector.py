"""Every run records a cost vector, and yield is its denominator (design §17.2).

What existed measured one axis — seconds — which is the axis the funnel's
argument is not really about. These tests pin the vector, the row it is written
to, and the two derived metrics that test the funnel's premise.

The disagreement check is re-asserted here, not because it changed, but because
it is the one piece of §17.2 that already worked and the one most easily broken
by extending the Observation around it.
"""
from __future__ import annotations

import pytest

from resource_explorer.registry import Project, ProjectRegistry
from resource_explorer.surveyors import step_cost_observer as sco
from resource_explorer.surveyors import step_run_metrics as srm


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.add(Project(slug="p", display_name="P", github_url="https://x/y",
                    description=""))
    return reg


# ── the table ───────────────────────────────────────────────────────────────

def test_a_step_execution_writes_a_real_row_with_a_real_vector(registry):
    with sco.observe("step_a", "api", "low") as observed:
        pass
    obs = observed[0]
    obs.annotations, obs.outcomes = 3, ()
    sco.record(registry, "p", obs, "SNAP-1")

    rows = registry.query_step_runs(slug="p", step_key="step_a")
    assert len(rows) == 1
    row = rows[0]
    assert row["surveyed_at"] == "SNAP-1"
    assert row["declared"] == {"fetch_cost": "api", "compute_cost": "low"}
    metrics = row["metrics"]
    # Every §17.2 axis this phase builds is PRESENT, even at zero — an axis
    # missing from the row and an axis measured as zero are different facts,
    # and a query that `.get()`s a missing key cannot tell them apart.
    for axis in ("wall_ms", "cpu_ms", "bytes_fetched", "api_calls",
                 "egeria_calls", "llm_tokens_in", "llm_tokens_out",
                 "cache_hits", "acquisition", "annotations",
                 "questions_answered"):
        assert axis in metrics, f"{axis} is missing from the recorded vector"
    assert metrics["wall_ms"] >= 0
    assert metrics["annotations"] == 3
    # A step that consulted no source cache is `not-consulted`, NOT `warm` —
    # a database survey does no source acquisition at all, and filing it as
    # warm would put every one of them in the cheap bucket.
    assert metrics["acquisition"] == "not-consulted"


def test_the_deferred_axes_are_not_silently_reported_as_zero(registry):
    """`source_rows`/`source_queries` are "optional, sampled" in §17.2's own
    table and are NOT built in this phase. They must therefore be ABSENT from
    the vector rather than present at 0 — a zero would read as "this step
    scanned no rows", which is a measurement nobody made."""
    with sco.observe("step_b", "none", "low") as observed:
        pass
    sco.record(registry, "p", observed[0], "SNAP-1")
    metrics = registry.query_step_runs(step_key="step_b")[0]["metrics"]
    assert "source_rows" not in metrics
    assert "source_queries" not in metrics


def test_demanded_by_is_empty_for_a_requested_step_and_named_for_a_prerequisite(registry):
    with sco.observe("asked_for", "none", "low") as a:
        pass
    sco.record(registry, "p", a[0], "SNAP-1")
    with sco.observe("prerequisite", "none", "low", demanded_by="asked_for") as b:
        pass
    sco.record(registry, "p", b[0], "SNAP-1")

    by_key = {r["step_key"]: r for r in registry.query_step_runs(slug="p")}
    assert by_key["asked_for"]["demanded_by"] == ""
    assert by_key["prerequisite"]["demanded_by"] == "asked_for", (
        "an auto-run prerequisite's cost is unattributable without this — "
        "'why did Scouting take three minutes' has no answer")


def test_two_runs_of_one_step_in_one_snapshot_are_two_rows(registry):
    """Append-only on purpose: a step run once as a prerequisite and once on
    its own request is two facts, and collapsing them loses the attribution
    §17.1 exists to record."""
    for demanded_by in ("", "other_step"):
        with sco.observe("step_c", "none", "low", demanded_by=demanded_by) as o:
            pass
        sco.record(registry, "p", o[0], "SNAP-1")
    assert len(registry.query_step_runs(step_key="step_c")) == 2


def test_executor_and_ref_travel_with_the_row(registry):
    """§17.2: "Prefect flow-run ids and Egeria engine-action GUIDs go in
    `executor_ref` so the board can link out"."""
    with sco.observe("step_d", "none", "low", executor="prefect",
                     source="prefect", executor_ref="flow-run-123") as o:
        pass
    sco.record(registry, "p", o[0], "SNAP-1")
    row = registry.query_step_runs(step_key="step_d")[0]
    assert row["executor"] == "prefect" and row["executor_ref"] == "flow-run-123"


def test_a_failed_vector_write_is_branchable_not_only_logged(registry, monkeypatch):
    """An observer whose own writes fail quietly stops being evidence — the
    same reason `record` already distinguishes NOT_RECORDED for the legacy
    metrics."""
    monkeypatch.setattr(
        registry, "record_step_run",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no table")))
    with sco.observe("step_e", "none", "low") as o:
        pass
    assert sco.record(registry, "p", o[0], "SNAP-1") == sco.NOT_RECORDED


# ── the disagreement check still works ──────────────────────────────────────

def test_a_zero_fetch_step_that_opened_a_connection_is_still_flagged():
    obs = sco.Observation("s", 0.1, 2, "none", "low", annotations=1)
    assert "declares fetch_cost='none'" in sco._disagreement(obs)


def test_the_disagreement_lands_on_the_row(registry):
    obs = sco.Observation("step_f", 0.1, 2, "none", "low", annotations=1)
    obs.disagreement = sco._disagreement(obs)
    sco.record(registry, "p", obs, "SNAP-1")
    assert "fetch_cost='none'" in registry.query_step_runs(step_key="step_f")[0]["disagreement"]


def test_an_uninterpretable_timing_still_abstains():
    """A step that produced nothing was not exercised; flagging its speed
    would be reading a number taken while the thing being measured was not
    happening."""
    obs = sco.Observation("s", 300.0, 0, "none", "medium", annotations=0)
    assert sco._disagreement(obs) == ""


# ── yield's denominator ─────────────────────────────────────────────────────

def test_questions_answered_is_counted_from_the_catalogs_real_shape():
    """The inverse of the catalog's `analysis_ids`, over the resource type's
    own questions.

    Pinned against real catalog data, because the first implementation read
    `entry.answering.analysis_ids` off a dataclass while `get_questions`
    returns plain dicts — every step came back answering 0 questions, which
    looks exactly like a step that earns nothing and would have made
    cost-per-question silently useless on every row.
    """
    assert sco.count_questions_answered("postgres_schema_and_stats", "database") > 0
    assert sco.count_questions_answered("repo_cve_scan", "repo") > 0


def test_a_step_no_question_names_answers_zero_not_minus_one():
    """0 and -1 are different facts: "authored, and none of them need this
    step" versus "could not be determined"."""
    assert sco.count_questions_answered("not_a_real_step", "database") == 0


def test_an_undeclared_resource_type_cannot_say_and_says_so():
    assert sco.count_questions_answered("whatever", "not_a_resource_type") == -1


# ── median, for a proposal's estimate ───────────────────────────────────────

def test_a_never_measured_step_has_no_median_rather_than_a_zero(registry):
    assert registry.median_step_wall_ms("never_run_anywhere") is None


def test_the_median_is_taken_across_resources(registry):
    for i, ms in enumerate((100.0, 300.0, 200.0)):
        registry.record_step_run("p", "step_g", f"SNAP-{i}",
                                 metrics={"wall_ms": ms})
    assert registry.median_step_wall_ms("step_g") == 200.0


# ── the two derived metrics ─────────────────────────────────────────────────

def _row(step_key, slug="p", **metrics):
    base = {"wall_ms": 0.0, "cpu_ms": 0.0, "bytes_fetched": 0, "api_calls": 0,
            "egeria_calls": 0, "llm_tokens_in": 0, "llm_tokens_out": 0,
            "questions_answered": 0}
    base.update(metrics)
    return {"step_key": step_key, "slug": slug, "metrics": base}


def test_cost_per_question_divides_by_yield_not_by_runs():
    """§17.2's example: "a Scouting definition that answers five questions for
    2s and 0 API calls, and an Analysis definition that answers twelve for 90s
    and 340 calls, are both fine; the same Analysis definition answering three
    is the one to look at"."""
    rows = [
        _row("scout", wall_ms=2000.0, api_calls=0, questions_answered=5),
        _row("deep", wall_ms=90000.0, api_calls=340, questions_answered=12),
    ]
    out = srm.cost_per_question(rows)
    assert out["scout"].per_question["wall_ms"] == pytest.approx(400.0)
    assert out["scout"].per_question["api_calls"] == 0.0
    assert out["deep"].per_question["wall_ms"] == pytest.approx(7500.0)
    assert out["deep"].per_question["api_calls"] == pytest.approx(28.3333, rel=1e-3)


def test_cost_per_question_sums_across_runs_of_one_step():
    rows = [_row("s", wall_ms=100.0, questions_answered=2),
            _row("s", wall_ms=300.0, questions_answered=2)]
    out = srm.cost_per_question(rows)
    assert out["s"].runs == 2 and out["s"].questions == 4
    assert out["s"].per_question["wall_ms"] == pytest.approx(100.0)


def test_a_step_that_answered_nothing_has_no_cost_per_question_not_infinity():
    """"a step that produces nothing was not cheap at any price" is a
    sentence a reader writes. None forces them to; 0.0 and inf both quietly
    answer the question wrongly."""
    out = srm.cost_per_question([_row("s", wall_ms=5000.0, questions_answered=0)])
    assert out["s"].per_question["wall_ms"] is None


def test_a_run_that_could_not_count_its_questions_marks_the_group_partial():
    """-1 is "never determined", which is not 0 — it is excluded from the
    denominator and the group says so, rather than dragging the per-question
    figure down with a measurement nobody made."""
    rows = [_row("s", wall_ms=100.0, questions_answered=2),
            _row("s", wall_ms=100.0, questions_answered=-1)]
    out = srm.cost_per_question(rows)
    assert out["s"].partial is True
    assert out["s"].questions == 2


def test_cost_per_question_groups_by_any_column():
    rows = [_row("a", slug="one", wall_ms=100.0, questions_answered=1),
            _row("b", slug="one", wall_ms=300.0, questions_answered=1)]
    out = srm.cost_per_question(rows, group_by="slug")
    assert set(out) == {"one"}
    assert out["one"].per_question["wall_ms"] == pytest.approx(200.0)


def test_tier_ratio_reports_the_cheap_tier_as_a_fraction_of_the_expensive_one():
    """The funnel promises this is small. Where it is not, a step is
    mis-tiered or under-declared."""
    tiers = {"scout_step": "scouting", "deep_step": "analysis"}
    rows = [_row("scout_step", wall_ms=2000.0, api_calls=1),
            _row("deep_step", wall_ms=80000.0, api_calls=100)]
    out = srm.tier_ratio(rows, tiers.get)
    assert out["p"].ratios["wall_ms"] == pytest.approx(0.025)
    assert out["p"].ratios["api_calls"] == pytest.approx(0.01)
    assert out["p"].measurable is True


def test_a_resource_surveyed_at_only_one_tier_has_no_ratio():
    """Reporting 0.0 would put the funnel's best-looking number on exactly
    the resources that never tested it."""
    tiers = {"scout_step": "scouting"}
    out = srm.tier_ratio([_row("scout_step", wall_ms=2000.0)], tiers.get)
    assert out["p"].measurable is False
    assert out["p"].ratios["wall_ms"] is None


def test_a_step_of_unknown_tier_is_excluded_from_both_sides():
    """Guessing it into one would move the ratio in a direction nothing
    measured."""
    tiers = {"scout_step": "scouting", "deep_step": "analysis"}
    rows = [_row("scout_step", wall_ms=1000.0),
            _row("deep_step", wall_ms=10000.0),
            _row("mystery_step", wall_ms=999999.0)]
    out = srm.tier_ratio(rows, tiers.get)
    assert out["p"].ratios["wall_ms"] == pytest.approx(0.1)


def test_a_not_captured_axis_is_not_summed_as_a_refund():
    """-1 means "not captured" on several axes. Adding it would make an
    unmeasured run look like it gave time back."""
    rows = [_row("s", wall_ms=100.0, cpu_ms=-1, questions_answered=1)]
    out = srm.cost_per_question(rows)
    assert out["s"].totals["cpu_ms"] == 0.0


def test_the_metrics_are_computable_straight_off_stored_rows(registry):
    """End to end: what `query_step_runs` returns is what the metric
    functions take, with no adapter in between. A derived metric that needed
    a reshaping step would be a second place for the vector's shape to be
    written down."""
    registry.record_step_run("p", "cheap", "S", metrics={
        "wall_ms": 1000.0, "api_calls": 0, "questions_answered": 4})
    registry.record_step_run("p", "dear", "S", metrics={
        "wall_ms": 50000.0, "api_calls": 200, "questions_answered": 4})
    rows = registry.query_step_runs(slug="p")
    per_q = srm.cost_per_question(rows)
    assert per_q["cheap"].per_question["wall_ms"] == pytest.approx(250.0)
    ratios = srm.tier_ratio(rows, {"cheap": "scouting", "dear": "analysis"}.get)
    assert ratios["p"].ratios["wall_ms"] == pytest.approx(0.02)
