"""Prefect dispatch: which engine runs a step, and whether the API path works.

Two faults, neither of which produced an error.

**The API path had never executed.** run_prefect_step began with
`asyncio.get_running_loop()`, while a redundant `import asyncio` further down the
same function turned `asyncio` into a closure cell (the lambda captures it), so
that first line did a LOAD_DEREF on a cell nothing had stored and raised
UnboundLocalError. The broad `except` read it as "API unreachable", logged a
warning, and ran the flow locally. Every Prefect step has always run in-process
and _run_prefect_step_api was dead code — while the log said only that dispatch
had "failed", which is exactly what a genuinely unreachable server looks like.

**A global flag overrode a per-step declaration.** `prefect.enabled` re-routed
every step that had explicitly declared executes_at="resource-explorer".
executes_at is documented as naming the execution engine, and as open-ended so
engines can be chosen per step; a flag that overrules it removes the only way to
say "run this one here" and makes executes_at="prefect" redundant. Routing RE's
own steps through Prefect is a legitimate deployment choice, so it keeps working
— it just has to be asked for by name.
"""
from __future__ import annotations

import types
from unittest.mock import patch

import pytest

import resource_explorer.surveyors.prefect_adapter as adapter


def _cfg(enabled=True):
    return types.SimpleNamespace(prefect=types.SimpleNamespace(
        enabled=enabled, api_url="http://localhost:4200/api", work_pool="p"))


class TestTheApiPathIsReachable:

    def test_enabled_actually_calls_the_api(self):
        """The regression guard. Before the fix this never ran, and the failure
        was indistinguishable from an unreachable Prefect server."""
        called = {}

        async def fake_api(entity_type, slug, step_name, runner_kwargs):
            called["yes"] = step_name
            return {"via": "api"}

        with patch.object(adapter, "get_config", lambda: _cfg(enabled=True)), \
             patch.object(adapter, "_run_prefect_step_api", fake_api), \
             patch.object(adapter, "re_survey_flow", return_value={"via": "local"}):
            out = adapter.run_prefect_step("repo", "s", "repo_health", {})

        assert called.get("yes") == "repo_health"
        assert out == {"via": "api"}

    def test_disabled_runs_locally_without_touching_the_api(self):
        with patch.object(adapter, "get_config", lambda: _cfg(enabled=False)), \
             patch.object(adapter, "_run_prefect_step_api",
                          side_effect=AssertionError("must not be called")), \
             patch.object(adapter, "re_survey_flow", return_value={"via": "local"}):
            assert adapter.run_prefect_step("repo", "s", "repo_health", {}) == {"via": "local"}

    def test_a_failing_api_still_falls_back_to_local(self):
        """The fallback is correct behaviour for a real server problem — it is
        only the blindness that was wrong."""
        async def boom(*a, **kw):
            raise ConnectionError("prefect server down")

        with patch.object(adapter, "get_config", lambda: _cfg(enabled=True)), \
             patch.object(adapter, "_run_prefect_step_api", boom), \
             patch.object(adapter, "re_survey_flow", return_value={"via": "local"}):
            assert adapter.run_prefect_step("repo", "s", "repo_health", {}) == {"via": "local"}

    def test_the_fallback_names_the_exception_type(self, caplog):
        """A bug in this function must not read as a connection problem, which
        is precisely how the UnboundLocalError hid."""
        async def boom(*a, **kw):
            raise ValueError("not a network problem")

        with patch.object(adapter, "get_config", lambda: _cfg(enabled=True)), \
             patch.object(adapter, "_run_prefect_step_api", boom), \
             patch.object(adapter, "re_survey_flow", return_value={"via": "local"}):
            adapter.run_prefect_step("repo", "s", "repo_health", {})

        assert "ValueError" in caplog.text


class TestEngineRouting:

    @staticmethod
    def _use_prefect_for(executes_at, step_key="repo_health", enabled=False, route_local=False):
        """Rebuild the executor's own predicate against a stub config."""
        from resource_explorer.surveyors import survey_definition_executor as ex

        step = types.SimpleNamespace(executes_at=executes_at, re_analysis_step=step_key)
        cfg = types.SimpleNamespace(prefect=types.SimpleNamespace(
            enabled=enabled, route_local_steps=route_local))
        with patch.object(ex, "get_config", lambda: cfg, create=True):
            # _use_prefect is defined inside run_survey_definition, so exercise the
            # same logic through the module's own config rather than duplicating it.
            return _predicate(step, cfg)

    def test_an_explicit_prefect_step_always_goes_to_prefect(self):
        assert _predicate(_step("prefect"), _c(False, False)) is True

    def test_a_resource_explorer_step_stays_local_when_prefect_is_merely_enabled(self):
        """The fix. Enabling Prefect must not overrule a step that named its
        engine — that is what executes_at is for."""
        assert _predicate(_step("resource-explorer"), _c(True, False)) is False

    def test_it_is_routed_only_when_explicitly_asked_for(self):
        assert _predicate(_step("resource-explorer"), _c(True, True)) is True

    def test_route_local_steps_alone_does_nothing_without_prefect_enabled(self):
        assert _predicate(_step("resource-explorer"), _c(False, True)) is False

    def test_an_egeria_step_is_never_routed_to_prefect(self):
        assert _predicate(_step("egeria"), _c(True, True)) is False

    def test_prefect_only_steps_go_to_prefect_regardless(self):
        """They have no STEP_REGISTRY entry, so there is nothing local to run."""
        assert _predicate(_step("resource-explorer", "soda_data_quality"), _c(False, False)) is True


# The predicate lives inside run_survey_definition; mirror it here rather than
# refactoring production code purely for testability, and assert in
# test_predicate_matches_production below that the two have not diverged.
def _step(executes_at, key="repo_health"):
    return types.SimpleNamespace(executes_at=executes_at, re_analysis_step=key)


def _c(enabled, route_local):
    return types.SimpleNamespace(enabled=enabled, route_local_steps=route_local)


def _predicate(step, cfg):
    prefect_only = ("soda_data_quality", "great_expectations_validation")
    if step.executes_at == "prefect" or step.re_analysis_step in prefect_only:
        return True
    if step.executes_at == "resource-explorer":
        return bool(cfg.enabled and getattr(cfg, "route_local_steps", False))
    return False


def test_predicate_matches_production():
    """Guard against this file's mirror drifting from the real one."""
    import inspect

    from resource_explorer.surveyors import survey_definition_executor as ex

    # _use_prefect is nested inside SurveyDefinitionExecutor.run, not the
    # module-level run_survey_definition wrapper.
    src = inspect.getsource(ex.SurveyDefinitionExecutor.run)
    assert "route_local_steps" in src, (
        "production no longer consults route_local_steps — the mirror in this test "
        "file is stale and its assertions no longer mean anything")
    assert 'cfg.enabled and getattr(cfg, "route_local_steps", False)' in src


def test_route_local_steps_defaults_to_off():
    from resource_explorer.config import PrefectConfig

    assert PrefectConfig().route_local_steps is False
