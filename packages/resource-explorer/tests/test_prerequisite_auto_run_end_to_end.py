"""An auto-run is a RESULT, executed through the real dispatch loop.

`test_prerequisite_resolver.py` pins the decision; this pins the consequence,
and it runs the branch rather than reading the source for it — for the reason
`test_step_preconditions.py` already learned the hard way: a source-reading
test passed while the code it described raised `NameError` the first time a
step was actually skipped. A feature that works until the moment it does
something is the least useful failure timing available.

The chain under test is §17.4's own: `postgres_column_profile` needs
`has_schema_inventory`, which `postgres_schema_and_stats` produces, and which
sits inside the profile's tier — so it runs unasked. The runners are stubbed,
because what is under test is the dispatch loop's behaviour, not psycopg2's.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.registry import DatabaseEntity, ProjectRegistry
from resource_explorer.surveyors.survey_definition_executor import (
    SurveyDefinitionExecutor,
    get_adapter,
)


@pytest.fixture
def registry(tmp_path):
    reg = ProjectRegistry(db_path=str(tmp_path / "t.db"))
    reg.register_database(DatabaseEntity(
        slug="testdb", display_name="Test DB", db_type="postgresql",
        host="localhost", port=5432, database_name="testdb"))
    return reg


@pytest.fixture
def adapter():
    return get_adapter("database")


def _stub_runners(monkeypatch, adapter, registry, *, produces_rows=True):
    """Replace the two real runners with ones that record their calls and,
    for the producer, actually write the rows its `produces` claims."""
    calls: list[str] = []

    def schema_and_stats(entity, reg, **kwargs):
        calls.append("postgres_schema_and_stats")
        if produces_rows:
            reg.write_detail_rows(
                "database_tables", entity.slug, "SNAP", "local",
                [{"schema_name": "public", "table_name": "t1"}])
        return {"schema_info": {}, "statistics": {}}

    def column_profile(entity, reg, **kwargs):
        calls.append("postgres_column_profile")
        return {"column_profile": {"columns": []}}

    monkeypatch.setitem(adapter.re_analysis_steps,
                        "postgres_schema_and_stats", schema_and_stats)
    monkeypatch.setitem(adapter.re_analysis_steps,
                        "postgres_column_profile", column_profile)
    return calls


def _run(registry, step="postgres_column_profile"):
    return SurveyDefinitionExecutor(registry).run_synthetic_step(
        "database", "testdb", step, executes_at="resource-explorer")


def test_the_producer_runs_first_and_the_demanding_step_then_runs(
        registry, adapter, monkeypatch):
    calls = _stub_runners(monkeypatch, adapter, registry)
    result = _run(registry)
    assert calls == ["postgres_schema_and_stats", "postgres_column_profile"], (
        "the prerequisite did not run before the step that demanded it")
    statuses = {s["re_analysis_step"]: s["status"] for s in result["steps"]}
    assert statuses["postgres_column_profile"] == "ok"
    assert result["auto_ran_steps"] == ["postgres_schema_and_stats"]


def test_the_auto_run_is_reported_as_a_step_of_its_own_with_its_demander(
        registry, adapter, monkeypatch):
    """An auto-run that only showed up as extra seconds would be exactly the
    silent omission §17.1's condition 3 forbids."""
    _stub_runners(monkeypatch, adapter, registry)
    result = _run(registry)
    entry = next(s for s in result["steps"]
                 if s["re_analysis_step"] == "postgres_schema_and_stats")
    assert entry["auto_run"] is True
    assert entry["demanded_by"] == "postgres_column_profile"
    assert "because" in entry["detail"]


def test_an_activity_log_entry_is_written_for_the_auto_run(
        registry, adapter, monkeypatch):
    """CLAUDE.md rule 16: every operation gets one."""
    _stub_runners(monkeypatch, adapter, registry)
    _run(registry)
    entries = registry.list_activity(limit=50)
    auto = [e for e in entries
            if "prerequisite_auto_run" in (e.get("detail") or "")]
    assert auto, "the auto-run left no activity-log entry"
    detail = json.loads(auto[0]["detail"])
    assert detail["prerequisite_auto_run"] == "postgres_schema_and_stats"
    assert detail["demanded_by"] == "postgres_column_profile"


def test_the_cost_is_attributed_to_both_the_producer_and_the_demander(
        registry, adapter, monkeypatch):
    """§17.1 condition 3: "the cost is attributed to the *demanding* step as
    well as recorded on the producer".

    Two rows, and the producer's carries `demanded_by` — that is the
    separable half. The inclusive half is that the demanding step's own
    wall time contains the producer's, because the observation scopes nest;
    asserted here by the producer's row existing under the same snapshot.
    """
    _stub_runners(monkeypatch, adapter, registry)
    _run(registry)
    rows = {r["step_key"]: r for r in registry.query_step_runs(slug="testdb")}
    assert set(rows) == {"postgres_schema_and_stats", "postgres_column_profile"}
    assert rows["postgres_schema_and_stats"]["demanded_by"] == "postgres_column_profile"
    assert rows["postgres_column_profile"]["demanded_by"] == ""
    assert rows["postgres_schema_and_stats"]["surveyed_at"] == \
        rows["postgres_column_profile"]["surveyed_at"], (
        "the two rows are not in the same snapshot, so stop rule 1 could never "
        "see the producer's own result")
    assert rows["postgres_column_profile"]["declared"] == {
        "fetch_cost": "api_heavy", "compute_cost": "medium"}


def test_a_producer_that_found_nothing_leaves_the_demanding_step_skipped(
        registry, adapter, monkeypatch):
    """The producer ran and legitimately produced no rows — CLAUDE.md's
    Gradle/BOM shape. The demanding step must then be SKIPPED with a reason,
    not dispatched because a producer "succeeded"."""
    calls = _stub_runners(monkeypatch, adapter, registry, produces_rows=False)
    result = _run(registry)
    assert calls == ["postgres_schema_and_stats"], (
        "the demanding step ran with its precondition still unmet")
    entry = next(s for s in result["steps"]
                 if s["re_analysis_step"] == "postgres_column_profile")
    assert entry["status"] == "skipped_by_design"
    assert entry["detail"], "the skip carries no reason"


def test_a_prerequisite_is_not_run_twice_in_one_run(
        registry, adapter, monkeypatch):
    """Two demanding steps, one shared producer. The second must not re-run
    it — and, more to the point, must not re-run it after it has already
    found nothing."""
    calls = _stub_runners(monkeypatch, adapter, registry, produces_rows=False)

    def nested(entity, reg, **kwargs):
        calls.append("postgres_nested_columns")
        return {}

    monkeypatch.setitem(adapter.re_analysis_steps,
                        "postgres_nested_columns", nested)

    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinition,
        SurveyStep,
    )

    steps = [SurveyStep(guid="", display_name=k, qualified_name=f"q::{k}",
                        executes_at="resource-explorer", re_analysis_step=k)
             for k in ("postgres_column_profile", "postgres_nested_columns")]
    survey_def = SurveyDefinition(
        process_guid="", display_name="two", qualified_name="q::two",
        supported_technology_type=None, steps=steps)
    executor = SurveyDefinitionExecutor(registry)
    executor._execute(
        entity_type="database", slug="testdb",
        entity=registry.get_database("testdb"), survey_def=survey_def,
        process_guid="", process_qn="q::two", publish=None,
        engine_override="resource-explorer", runner_kwargs={})

    assert calls.count("postgres_schema_and_stats") == 1, (
        f"the shared prerequisite ran {calls.count('postgres_schema_and_stats')} "
        "times — its nothing_found is the answer, and re-running it is the loop")


def test_a_proposal_reaches_the_caller_rather_than_only_the_log(
        registry, adapter, monkeypatch):
    """`db_derived` is the zero-fetch step; filling its input crosses into
    `api`, so it must PROPOSE. The proposal has to travel out with the
    result — a proposal nobody can see is a skip with extra words."""
    calls = _stub_runners(monkeypatch, adapter, registry)

    def derived(entity, reg, **kwargs):
        calls.append("db_derived")
        return {"derived": {}}

    monkeypatch.setitem(adapter.re_analysis_steps, "db_derived", derived)
    result = _run(registry, step="db_derived")

    assert calls == [], "a zero-fetch step silently triggered a fetching prerequisite"
    assert result["proposals"], "the proposal was not returned to the caller"
    proposal = result["proposals"][0]
    assert proposal["steps"] == ["postgres_schema_and_stats"]
    assert proposal["demanding_step"] == "db_derived"
    # sentence() ends with a full stop, not the decision; question() -- also
    # on the serialised plan -- carries the actionable ask
    # (REPLY-COPY-REVIEW-CREDENTIAL-AND-FIT-LANGUAGE.md §1 defect 3).
    assert proposal["sentence"].endswith(".")
    assert proposal["question"] == "Run it?"
    entry = next(s for s in result["steps"] if s["re_analysis_step"] == "db_derived")
    assert entry["status"] == "skipped_by_design"
    assert entry["proposal"]["steps"] == ["postgres_schema_and_stats"]


def test_accepting_the_proposal_runs_exactly_what_was_offered(
        registry, adapter, monkeypatch):
    """The accept path (`/api/prerequisites/run`) goes through the ordinary
    executor, so an accepted proposal is measured like any other run rather
    than being a second, unobserved code path."""
    import asyncio

    from resource_explorer.web.routes import prerequisites as route

    calls = _stub_runners(monkeypatch, adapter, registry)
    monkeypatch.setattr(route, "_registry", lambda: registry)
    body = asyncio.run(route.run_prerequisites(route.RunRequest(
        entity_type="database", slug="testdb",
        steps=["postgres_schema_and_stats"], demanded_by="db_derived")))
    assert body["status"] == "ok"
    assert calls == ["postgres_schema_and_stats"]
    rows = registry.query_step_runs(step_key="postgres_schema_and_stats")
    assert rows, (
        "an accepted proposal produced no step_runs row — it bypassed the "
        "observation every other run gets")
    assert rows[0]["demanded_by"] == "db_derived", (
        "an accepted chain's cost landed on the board with no trace of the "
        "question that caused it")


def test_the_plan_endpoint_runs_nothing(registry, adapter, monkeypatch):
    import asyncio

    from resource_explorer.web.routes import prerequisites as route

    calls = _stub_runners(monkeypatch, adapter, registry)
    monkeypatch.setattr(route, "_registry", lambda: registry)
    plan = asyncio.run(route.plan_prerequisites(route.PlanRequest(
        entity_type="database", slug="testdb",
        step_key="postgres_column_profile")))
    assert calls == []
    assert plan["status"] == "auto_run"
    assert plan["auto_run"] == ["postgres_schema_and_stats"]
