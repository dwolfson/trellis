"""Prerequisites run themselves, within the budget the user chose (design §17.1).

The risk in this change is precisely the one §17.1's three conditions exist to
contain: a mechanism that runs things on the user's behalf can run the wrong
things, run them twice, run half a chain and then ask about the rest, or loop.
These tests pin each of those shut, and they use a constructed registry rather
than the real one wherever the point is the ALGORITHM — a test that can only
fail when `repo_manifest_parse`'s cost changes is a test of that declaration,
not of the resolver.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from resource_explorer.surveyors import prerequisite_resolver as pr
from resource_explorer.surveyors import step_preconditions as sp
from resource_explorer.surveyors import step_produces
from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo


# ── a tiny world, so the algorithm is what is under test ────────────────────

class _Reg:
    """A registry stand-in: it answers row counts and step_runs lookups."""

    def __init__(self, counts=None, step_runs=None, medians=None):
        self._counts = counts or {}
        self._step_runs = step_runs or []
        self._medians = medians or {}

    def _conn(self):
        counts = self._counts

        class _Conn:
            def execute(self, sql, params):
                import re
                table = re.search(r"FROM (\w+)", sql).group(1)
                return SimpleNamespace(fetchone=lambda: {"n": counts.get(table, 0)})

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _Conn()

    def query_step_runs(self, slug=None, step_key=None, surveyed_at=None,
                        entity_type=None, limit=5000):
        return [r for r in self._step_runs
                if (step_key is None or r["step_key"] == step_key)
                and (surveyed_at is None or r["surveyed_at"] == surveyed_at)]

    def median_step_wall_ms(self, step_key):
        return self._medians.get(step_key)


_ENTITY = SimpleNamespace(slug="p", display_name="P", github_url="")


def _precondition(name, table, monkeypatch):
    monkeypatch.setitem(sp.PRECONDITIONS, name, sp.Precondition(
        sp._needs_rows(table, name), table=table))


@pytest.fixture
def world(monkeypatch):
    """A three-step chain: `top` needs `mid`'s table, `mid` needs `base`'s.

    Costs deliberately all inside `top`'s own tier, so the DEFAULT outcome is
    a silent auto-run and each test that wants a proposal has to change
    exactly one thing. A fixture whose default is the cautious branch would
    let a bug that never auto-runs pass everything.
    """
    registry = {
        "top": StepInfo("top", None, "", [], fetch_cost="api", compute_cost="medium",
                        requires_context={"needs_mid": "top reads mid's rows"}),
        "mid": StepInfo("mid", None, "", [], fetch_cost="api", compute_cost="low",
                        produces=("mid_table",),
                        requires_context={"needs_base": "mid reads base's rows"}),
        "base": StepInfo("base", None, "", [], fetch_cost="none", compute_cost="low",
                         produces=("base_table",)),
    }
    _precondition("needs_mid", "mid_table", monkeypatch)
    _precondition("needs_base", "base_table", monkeypatch)
    monkeypatch.setattr(step_produces, "_registries", lambda: {"repo": registry})
    return registry


# ── PRODUCES and the derived inverse ────────────────────────────────────────

def test_a_declared_produces_resolves_back_from_a_precondition_name(world):
    """The whole reconciliation in one assertion: a precondition declares a
    TABLE, and the step that fills it is found from that step's own
    `produces`, with no producer string written down twice."""
    assert sp.PRECONDITIONS["needs_mid"].produced_by() == "mid"
    assert sp.PRECONDITIONS["needs_base"].produced_by() == "base"


def test_the_real_registries_invert_without_collision():
    """Two steps claiming one table cannot be resolved to "run which?" — so
    it raises rather than silently keeping the last writer."""
    step_produces.validate()
    index = step_produces.index()
    assert index["project_dependencies"] == "repo_manifest_parse"
    assert index["database_tables"] == "postgres_schema_and_stats"


def test_every_precondition_names_a_table_that_something_produces():
    """A precondition over a table no step declares is unsatisfiable by
    running anything. That is allowed — but it must be VISIBLE, because the
    remedy text is the only thing standing between a user and "run what?"."""
    orphans = {name: p.table for name, p in sp.PRECONDITIONS.items()
               if not p.produced_by()}
    assert not orphans, (
        f"preconditions whose table nothing declares `produces` for: {orphans}. "
        "Either declare it on the producing step or accept that the remedy "
        "text will say nothing can satisfy it.")


def test_a_precondition_with_no_producer_says_so_rather_than_naming_a_step(monkeypatch):
    monkeypatch.setattr(step_produces, "_registries", lambda: {})
    p = sp.Precondition(lambda *_: (False, ""), table="nobody_writes_this")
    assert "Nothing in this build declares" in p.remedy()
    assert "Run " not in p.remedy()


# ── the resolver ────────────────────────────────────────────────────────────

def test_a_chain_of_two_steps_auto_runs_within_tier(world):
    """`top` is api/medium; `mid` (api/low) and `base` (none/low) both fit
    inside it, so neither needs asking. Deepest first: `base` before `mid`,
    because running `mid` before its own input exists is the ordering bug
    this walk exists to prevent."""
    res = pr.resolve(_Reg(), _ENTITY, "top", world)
    assert res.status == pr.AUTO_RUN
    assert res.auto_run == ["base", "mid"]
    assert res.may_run is True
    assert res.proposal is None


def test_a_satisfied_precondition_resolves_to_nothing_at_all(world):
    res = pr.resolve(_Reg({"mid_table": 3}), _ENTITY, "top", world)
    assert res.status == pr.SATISFIED
    assert res.auto_run == [] and res.proposal is None


def test_a_chain_that_crosses_tier_becomes_one_proposal_with_summed_cost(world):
    """`base` is raised to `download`, which `top`'s api tier does not cover.

    The whole chain becomes ONE proposal — both steps, not just the crossing
    one — and the summed cost is the chain's, because that is what the user
    is being asked to spend.
    """
    world["base"] = StepInfo("base", None, "", [], fetch_cost="download",
                             compute_cost="low", produces=("base_table",))
    res = pr.resolve(_Reg(medians={"base": 30000.0, "mid": 10000.0}),
                     _ENTITY, "top", world)
    assert res.status == pr.PROPOSAL
    assert res.may_run is False
    assert res.proposal.steps == ["base", "mid"], (
        "the chain was split — a proposal naming only the crossing step would "
        "run the rest without asking, which is stop rule 2's whole point")
    assert res.proposal.fetch_cost == "download"
    assert res.proposal.estimated_seconds == pytest.approx(40.0)
    assert res.proposal.estimated_is_measured is True
    assert res.proposal.demanding_step == "top"
    assert "needs_mid" in res.proposal.preconditions
    assert "run it?" in res.proposal.sentence()


def test_an_unmeasured_chain_says_its_estimate_is_not_a_measurement(world):
    world["base"] = StepInfo("base", None, "", [], fetch_cost="download",
                             compute_cost="low", produces=("base_table",))
    res = pr.resolve(_Reg(), _ENTITY, "top", world)
    assert res.proposal.estimated_is_measured is False
    assert "never yet measured" in res.proposal.sentence(), (
        "a tier default was quoted as though it had been observed")


def test_a_compute_tier_crossing_also_proposes(world):
    """The two axes are independent and must stay so — a prerequisite that
    fetches nothing and computes for an hour is not free."""
    world["mid"] = StepInfo("mid", None, "", [], fetch_cost="api",
                            compute_cost="high", produces=("mid_table",))
    res = pr.resolve(_Reg(), _ENTITY, "top", world)
    assert res.status == pr.PROPOSAL
    assert any(r.kind == "tier" for r in res.proposal.reasons)


def test_a_producer_needing_an_unacquired_download_proposes_even_within_tier(world):
    """§17.1 names "needs a download or clone" as its own condition, and the
    sentence a user reads should say so rather than only "a more expensive
    tier" — a zipball this run already holds is not a download."""
    world["mid"] = StepInfo(
        "mid", None, "", [], fetch_cost="api", compute_cost="low",
        produces=("mid_table",), requires_resources={"zipball_root": "local_path"})
    res = pr.resolve(_Reg(), _ENTITY, "top", world)
    assert res.status == pr.PROPOSAL
    assert any(r.kind == "download" for r in res.proposal.reasons)

    # …and with the resource already acquired, it is not a download any more.
    res2 = pr.resolve(_Reg(), _ENTITY, "top", world,
                      resolved_resources={"zipball_root"})
    assert res2.status == pr.AUTO_RUN


def test_an_explicit_run_ceiling_beats_the_demanding_steps_own_tier(world):
    """Reading (a) of "the tier the user's current action is operating at":
    when a run already declares what it will pay, that IS the budget, and a
    prerequisite inside the demanding step's tier but above the ceiling must
    still be asked about."""
    res = pr.resolve(_Reg(), _ENTITY, "top", world,
                     max_fetch_cost="none", max_compute_cost="low")
    assert res.status == pr.PROPOSAL
    assert "ceiling this run set" in res.proposal.reasons[0].detail


def test_the_cycle_guard_raises_rather_than_looping(world):
    """A step that transitively requires its own output. Constructed, because
    no resource state can produce one: it is always a declaration bug, and
    the only useful response is to say which steps are involved."""
    world["base"] = StepInfo(
        "base", None, "", [], fetch_cost="none", compute_cost="low",
        produces=("base_table",),
        requires_context={"needs_mid": "base reads mid's rows — the cycle"})
    with pytest.raises(pr.PrerequisiteCycleError) as exc:
        pr.resolve(_Reg(), _ENTITY, "top", world)
    assert "mid" in str(exc.value) and "base" in str(exc.value)


def test_a_self_referential_step_is_caught_too(world):
    world["mid"] = StepInfo(
        "mid", None, "", [], fetch_cost="api", compute_cost="low",
        produces=("mid_table",),
        requires_context={"needs_mid": "mid requires its own output"})
    with pytest.raises(pr.PrerequisiteCycleError):
        pr.resolve(_Reg(), _ENTITY, "top", world)


def test_stop_rule_1_a_producer_that_found_nothing_on_this_snapshot_is_not_rerun(world):
    """Its `nothing_found` IS the answer; re-running it is the loop.

    Snapshot-scoped, not a freshness window: the row below is keyed on THIS
    run's `surveyed_at`.
    """
    runs = [{"step_key": "mid", "surveyed_at": "SNAP-1",
             "metrics": {"annotations": 0, "wall_ms": 12.0}}]
    res = pr.resolve(_Reg(step_runs=runs), _ENTITY, "top", world,
                     surveyed_at="SNAP-1")
    assert res.status == pr.UNSATISFIABLE
    assert "mid" not in res.auto_run
    assert "already ran on this snapshot and found nothing" in res.reason


def test_stop_rule_1_is_snapshot_scoped_not_time_scoped(world):
    """The same producer, the same empty result, a DIFFERENT snapshot — that
    is a new question and it gets run again. A TTL would have answered this
    the other way and re-run the step in the same snapshot instead, which is
    exactly backwards."""
    runs = [{"step_key": "mid", "surveyed_at": "SNAP-0",
             "metrics": {"annotations": 0}}]
    res = pr.resolve(_Reg(step_runs=runs), _ENTITY, "top", world,
                     surveyed_at="SNAP-1")
    assert res.status == pr.AUTO_RUN
    assert "mid" in res.auto_run


def test_stop_rule_1_reads_the_no_signal_outcome_too(world):
    runs = [{"step_key": "mid", "surveyed_at": "S",
             "metrics": {"annotations": 4, "outcomes": ["no_signal"]}}]
    res = pr.resolve(_Reg(step_runs=runs), _ENTITY, "top", world, surveyed_at="S")
    assert res.status == pr.UNSATISFIABLE


def test_an_unreadable_step_runs_table_runs_the_producer(world):
    """Same direction `step_preconditions._needs_rows` already takes: on OUR
    failure, run the step. Mistaking an unreadable table for a
    `nothing_found` costs an answer."""
    class _Broken(_Reg):
        def query_step_runs(self, **kwargs):
            raise RuntimeError("no such table")

    res = pr.resolve(_Broken(), _ENTITY, "top", world, surveyed_at="S")
    assert res.status == pr.AUTO_RUN


def test_stop_rule_2_a_deep_proposal_collapses_the_whole_chain(world):
    """`base` needs consent; `mid` does not. The outcome must be ONE proposal
    covering both — never "auto-run `base`… now may I run `mid`?", and never
    a partial auto-run followed by a prompt, which would spend the user's
    time before asking."""
    world["base"] = StepInfo("base", None, "", [], fetch_cost="download",
                             compute_cost="high", produces=("base_table",))
    res = pr.resolve(_Reg(), _ENTITY, "top", world)
    assert res.status == pr.PROPOSAL
    assert res.auto_run == [], "a chain awaiting consent must have nothing queued to run"
    assert set(res.proposal.steps) == {"base", "mid"}


def test_an_already_run_producer_is_not_queued_twice(world):
    res = pr.resolve(_Reg(), _ENTITY, "top", world, already_ran={"base"})
    assert res.auto_run == ["mid"]


def test_a_resource_type_with_no_step_registry_resolves_to_satisfied():
    """NOT DECLARED is not "no prerequisites" — but the only safe behaviour
    for a type that has declared nothing is the behaviour it had before
    §17.1: dispatch, exactly as before."""
    assert pr.resolve(_Reg(), _ENTITY, "anything", None).status == pr.SATISFIED
    assert pr.resolve(_Reg(), _ENTITY, "not_in_registry", {}).status == pr.SATISFIED


def test_the_resolution_serialises_for_a_remote_executor(world):
    """Rule E constrains the step contract now even though its executors do
    not exist yet: the resolver's output has to be serialisable by
    reference."""
    import json

    world["base"] = StepInfo("base", None, "", [], fetch_cost="download",
                             compute_cost="low", produces=("base_table",))
    plan = pr.resolve(_Reg(), _ENTITY, "top", world).as_plan()
    assert json.loads(json.dumps(plan))["proposal"]["steps"] == ["base", "mid"]


def test_the_auto_run_annotation_names_all_three_things():
    """"ran X because Y required Z" — the producer, the demander and the
    precondition. Dropping any one leaves a reader unable to reconstruct why
    a step they did not ask for consumed their time."""
    ann = pr.auto_run_annotation("dependency_analysis", "cve_scan", "project_dependencies")
    assert ann["producer"] == "dependency_analysis"
    assert ann["demanded_by"] == "cve_scan"
    assert ann["cause"] == "project_dependencies"
    assert "ran `dependency_analysis` because `cve_scan` required" in ann["hint"]


# ── the real database chain §17.4 names ─────────────────────────────────────

def test_the_database_chain_from_the_design_is_declared_end_to_end():
    """§17.4: "`postgres_column_profile` is the first step with a real chain
    (needs `schema_inventory`, which needs the catalog read)". This asserts
    the declarations actually say that, since the resolver can only be as
    right as they are."""
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_STEP_REGISTRY,
    )

    profile = DATABASE_STEP_REGISTRY["postgres_column_profile"]
    assert "has_schema_inventory" in profile.requires_context
    assert sp.PRECONDITIONS["has_schema_inventory"].produced_by() == \
        "postgres_schema_and_stats"
    # …and the producer is inside the profile's own tier, so it auto-runs.
    assert pr._exceeds(
        pr.Budget.for_step(profile),
        DATABASE_STEP_REGISTRY["postgres_schema_and_stats"]) == ""


def test_the_zero_fetch_database_step_cannot_silently_open_a_connection():
    """`db_derived` declares `fetch_cost="none"` — the defining property of
    the tier. Its own input comes from a step that DOES fetch, so filling it
    has to be asked about; otherwise "zero-fetch" would be a label a run
    could quietly break."""
    from resource_explorer.surveyors.database.survey_definition_adapter import (
        DATABASE_STEP_REGISTRY,
    )

    assert pr._exceeds(
        pr.Budget.for_step(DATABASE_STEP_REGISTRY["db_derived"]),
        DATABASE_STEP_REGISTRY["postgres_schema_and_stats"]) != ""
