"""The compile's evidence budget and section cap are tier settings with env overrides."""
from __future__ import annotations

import pytest

from resource_explorer import config
from resource_explorer.config import TIER_PRESETS, resolve_llm_tier_config

_ENVS = ("EXPLORER_MODEL_TIER", "EXPLORER_COMPILE_EVIDENCE_BUDGET_CHARS", "EXPLORER_COMPILE_MAX_SECTIONS")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in _ENVS:
        monkeypatch.delenv(k, raising=False)


@pytest.mark.parametrize("tier", sorted(TIER_PRESETS))
def test_every_tier_defaults_to_todays_values(tier, monkeypatch):
    monkeypatch.setenv("EXPLORER_MODEL_TIER", tier)
    cfg = resolve_llm_tier_config()
    assert (cfg.compile_evidence_budget_chars, cfg.compile_max_sections) == (6000, 12)


def test_env_overrides_the_tier_preset(monkeypatch):
    monkeypatch.setenv("EXPLORER_MODEL_TIER", "demo-gpu")
    monkeypatch.setenv("EXPLORER_COMPILE_EVIDENCE_BUDGET_CHARS", "4000")
    monkeypatch.setenv("EXPLORER_COMPILE_MAX_SECTIONS", "0")
    cfg = resolve_llm_tier_config()
    assert (cfg.compile_evidence_budget_chars, cfg.compile_max_sections) == (4000, 0)


def test_the_preset_applies_when_the_env_is_unset(monkeypatch):
    monkeypatch.setenv("EXPLORER_MODEL_TIER", "demo-cpu")
    monkeypatch.setitem(TIER_PRESETS["demo-cpu"], "compile_max_sections", 9)
    assert resolve_llm_tier_config().compile_max_sections == 9


@pytest.mark.parametrize("bad", ["lots", "-1", "1.5"])
def test_an_unusable_override_falls_back_to_the_preset(bad, monkeypatch):
    monkeypatch.setenv("EXPLORER_COMPILE_MAX_SECTIONS", bad)
    assert resolve_llm_tier_config().compile_max_sections == 12


def test_a_zero_budget_is_refused(monkeypatch):
    monkeypatch.setenv("EXPLORER_COMPILE_EVIDENCE_BUDGET_CHARS", "0")
    assert resolve_llm_tier_config().compile_evidence_budget_chars == 6000


def test_the_resolved_values_are_logged_with_the_tier_line(monkeypatch, caplog):
    monkeypatch.setenv("EXPLORER_COMPILE_MAX_SECTIONS", "7")
    with caplog.at_level("INFO", logger=config.log.name):
        config.get_llm_tier_config(force_refresh=True)
    line = next(r.getMessage() for r in caplog.records if "LLM tier resolved" in r.getMessage())
    assert "compile_evidence_budget_chars=6000" in line and "compile_max_sections=7" in line
    monkeypatch.delenv("EXPLORER_COMPILE_MAX_SECTIONS")
    config.get_llm_tier_config(force_refresh=True)


def test_the_agents_read_the_budget_from_the_tier(monkeypatch):
    import inspect
    from resource_explorer.agents import base, conversation_agent
    assert "budget=6000" not in inspect.getsource(conversation_agent)
    assert "budget: int = 6000" not in inspect.getsource(base)
