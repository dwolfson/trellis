"""
Tests for the model-tier concept added per docs/runtime-architecture-plan.md
§5: a `tier` (dev | demo-gpu | demo-cpu) that resolves per-slot Ollama
models, the `num_ctx` ceiling, and the RAG context token budget together.

Covers:
  - tier resolution (default, each named tier, unknown value falls back)
  - per-slot override wins over the tier preset
  - the OLLAMA_MODEL / OLLAMA_CODE_MODEL env aliases still work, as overrides
  - num_ctx is present in the Ollama options on every call OllamaClient makes
  - RAG context budget truncation keeps the highest-ranked chunks and stays
    under budget
"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import yaml

from advisor.config import (
    TIER_PRESETS,
    DEFAULT_MODEL_TIER,
    LLMModelConfig,
    resolve_model_tier,
    resolve_llm_tier_config,
)


def _write_yaml(tmp_path: Path, llm: dict) -> Path:
    path = tmp_path / "advisor.yaml"
    path.write_text(yaml.safe_dump({"llm": llm}))
    return path


# ---------------------------------------------------------------------------
# Tier resolution
# ---------------------------------------------------------------------------

class TestTierResolution:
    def test_default_tier_is_dev(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ADVISOR_MODEL_TIER", raising=False)
        path = _write_yaml(tmp_path, {})
        assert resolve_model_tier(path) == "dev" == DEFAULT_MODEL_TIER

    def test_yaml_llm_tier_is_honoured(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ADVISOR_MODEL_TIER", raising=False)
        path = _write_yaml(tmp_path, {"tier": "demo-gpu"})
        assert resolve_model_tier(path) == "demo-gpu"

    def test_env_tier_wins_over_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "demo-cpu")
        path = _write_yaml(tmp_path, {"tier": "demo-gpu"})
        assert resolve_model_tier(path) == "demo-cpu"

    def test_unknown_env_tier_falls_back_to_yaml(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "nonsense")
        path = _write_yaml(tmp_path, {"tier": "demo-gpu"})
        assert resolve_model_tier(path) == "demo-gpu"

    def test_unknown_yaml_tier_falls_back_to_default(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ADVISOR_MODEL_TIER", raising=False)
        path = _write_yaml(tmp_path, {"tier": "nonsense"})
        assert resolve_model_tier(path) == DEFAULT_MODEL_TIER

    @pytest.mark.parametrize("tier", sorted(TIER_PRESETS))
    def test_each_known_tier_round_trips(self, tmp_path, monkeypatch, tier):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", tier)
        path = _write_yaml(tmp_path, {})
        assert resolve_model_tier(path) == tier


# ---------------------------------------------------------------------------
# Per-tier resolved config: models / num_ctx / rag budget
# ---------------------------------------------------------------------------

class TestResolvedTierConfig:
    def test_dev_tier_num_ctx_and_budget(self, tmp_path, monkeypatch):
        monkeypatch.delenv("ADVISOR_MODEL_TIER", raising=False)
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_CODE_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.tier == "dev"
        assert cfg.num_ctx == 32768
        assert cfg.rag_context_budget_tokens is None
        # dev leaves models at class defaults when yaml specifies none
        assert cfg.models == LLMModelConfig()

    def test_demo_gpu_tier_models_num_ctx_budget(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "demo-gpu")
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_CODE_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.tier == "demo-gpu"
        assert cfg.num_ctx == 8192
        assert cfg.rag_context_budget_tokens == 2000
        assert cfg.models.query == "llama3.1:8b"
        assert cfg.models.code == "codellama:13b"
        assert cfg.models.conversation == "llama3.1:8b"
        assert cfg.models.maintenance == "codellama:13b"

    def test_demo_cpu_tier_uses_one_model_for_every_slot(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "demo-cpu")
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_CODE_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.tier == "demo-cpu"
        assert cfg.num_ctx == 8192
        assert cfg.rag_context_budget_tokens == 2000
        for slot in ("query", "code", "conversation", "maintenance", "planning"):
            assert getattr(cfg.models, slot) == "llama3.1:8b"

    def test_per_slot_yaml_override_wins_over_tier_preset(self, tmp_path, monkeypatch):
        """An operator-set llm.models.<slot> in advisor.yaml wins over
        whatever the active tier would otherwise pick for that slot."""
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "demo-gpu")
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.delenv("OLLAMA_CODE_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {"code": "my-custom-code-model:1b"}})
        cfg = resolve_llm_tier_config(path)
        # Explicit override wins...
        assert cfg.models.code == "my-custom-code-model:1b"
        # ...but slots not explicitly set still take the tier preset.
        assert cfg.models.query == "llama3.1:8b"

    def test_env_alias_ollama_model_overrides_general_slots(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "dev")
        monkeypatch.setenv("OLLAMA_MODEL", "mistral:7b")
        monkeypatch.delenv("OLLAMA_CODE_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.models.query == "mistral:7b"
        assert cfg.models.conversation == "mistral:7b"
        # code/maintenance untouched by OLLAMA_MODEL
        assert cfg.models.code == LLMModelConfig().code
        # planning is a dedicated slot (CLAUDE.md rule 16) — OLLAMA_MODEL
        # must never silently downgrade it away from whatever advisor.yaml
        # (or the tier preset) chose for narrative/refinement quality.
        assert cfg.models.planning == LLMModelConfig().planning

    def test_env_alias_ollama_code_model_overrides_code_slots(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "dev")
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        monkeypatch.setenv("OLLAMA_CODE_MODEL", "deepseek-coder:6.7b")
        path = _write_yaml(tmp_path, {"models": {}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.models.code == "deepseek-coder:6.7b"
        assert cfg.models.maintenance == "deepseek-coder:6.7b"
        assert cfg.models.query == LLMModelConfig().query

    def test_env_alias_wins_over_yaml_slot_override(self, tmp_path, monkeypatch):
        """Env aliases are the highest-priority override: they win even
        over an explicit advisor.yaml llm.models entry for the same slot."""
        monkeypatch.setenv("ADVISOR_MODEL_TIER", "demo-gpu")
        monkeypatch.setenv("OLLAMA_CODE_MODEL", "env-wins:1b")
        monkeypatch.delenv("OLLAMA_MODEL", raising=False)
        path = _write_yaml(tmp_path, {"models": {"code": "yaml-loses:1b"}})
        cfg = resolve_llm_tier_config(path)
        assert cfg.models.code == "env-wins:1b"


# ---------------------------------------------------------------------------
# num_ctx present on every Ollama call OllamaClient makes
# ---------------------------------------------------------------------------

def _make_client(num_ctx=8192, model="llama3.1:8b"):
    """Construct an OllamaClient without running its heavy __init__
    (which calls get_full_config()/get_metrics_collector()) — only the
    attributes the generate/chat/stream methods actually read are needed."""
    from advisor.llm_client import OllamaClient

    client = object.__new__(OllamaClient)
    client.base_url = "http://localhost:11434"
    client.default_model = model
    client.timeout = 60
    client.num_ctx = num_ctx
    client.default_params = {
        "temperature": 0.7,
        "top_p": 0.9,
        "top_k": 40,
        "repeat_penalty": 1.1,
    }
    client.mlflow_tracker = None
    client.metrics_collector = None
    return client


class TestNumCtxOnOllamaCalls:
    def test_generate_non_streaming_sends_num_ctx(self):
        client = _make_client(num_ctx=8192)
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"response": "hi"}
        with patch("advisor.llm_client.requests.post", return_value=fake_response) as post:
            client.generate("hello")
        sent = post.call_args.kwargs["json"]
        assert sent["options"]["num_ctx"] == 8192

    def test_chat_sends_num_ctx(self):
        client = _make_client(num_ctx=4096)
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"message": {"content": "hi"}}
        with patch("advisor.llm_client.requests.post", return_value=fake_response) as post:
            client.chat([{"role": "user", "content": "hello"}])
        sent = post.call_args.kwargs["json"]
        assert sent["options"]["num_ctx"] == 4096

    def test_stream_generate_sends_num_ctx(self):
        client = _make_client(num_ctx=32768)
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            json.dumps({"response": "hi", "done": True}).encode()
        ]
        with patch("advisor.llm_client.requests.post", return_value=fake_response) as post:
            list(client.stream_generate("hello"))
        sent = post.call_args.kwargs["json"]
        assert sent["options"]["num_ctx"] == 32768

    def test_stream_chat_sends_num_ctx(self):
        client = _make_client(num_ctx=2048)
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.iter_lines.return_value = [
            json.dumps({"message": {"content": "hi"}, "done": True}).encode()
        ]
        with patch("advisor.llm_client.requests.post", return_value=fake_response) as post:
            list(client.stream_chat([{"role": "user", "content": "hello"}]))
        sent = post.call_args.kwargs["json"]
        assert sent["options"]["num_ctx"] == 2048

    def test_explicit_kwarg_num_ctx_overrides_client_default(self):
        """A caller passing num_ctx explicitly still wins over the client's
        tier-resolved default — kwargs are applied last."""
        client = _make_client(num_ctx=8192)
        fake_response = MagicMock()
        fake_response.raise_for_status.return_value = None
        fake_response.json.return_value = {"response": "hi"}
        with patch("advisor.llm_client.requests.post", return_value=fake_response) as post:
            client.generate("hello", num_ctx=99999)
        sent = post.call_args.kwargs["json"]
        assert sent["options"]["num_ctx"] == 99999


# ---------------------------------------------------------------------------
# RAG context budget truncation
# ---------------------------------------------------------------------------

def _fake_result(text: str, score: float, name: str = "x"):
    return SimpleNamespace(
        text=text,
        score=score,
        metadata={"file_path": "f.py", "type": "function", "name": name},
    )


def _make_retriever(budget_tokens=None, max_context_length=100000):
    """Construct a RAGRetriever without running its heavy __init__ (vector
    store / embeddings / multi-collection store) — build_context() only
    needs the two budget attributes and the formatting helpers."""
    from advisor.rag_retrieval import RAGRetriever

    retriever = object.__new__(RAGRetriever)
    retriever.max_context_length = max_context_length
    retriever.rag_context_budget_tokens = budget_tokens
    return retriever


class TestRagContextBudget:
    def test_no_budget_keeps_all_results_under_char_limit(self):
        retriever = _make_retriever(budget_tokens=None, max_context_length=100000)
        # The identifying marker lives in the *code* text (`result.text`),
        # which build_context() always includes, so this doesn't depend on
        # include_metadata (which we disable to avoid a real DB call from
        # _format_detailed's relational-metadata lookup).
        results = [
            _fake_result(f"MARKER_r{i} " + "short chunk " * 5, score=0.9 - 0.1 * i, name=f"r{i}")
            for i in range(5)
        ]
        context = retriever.build_context(results, include_metadata=False)
        for i in range(5):
            assert f"MARKER_r{i}" in context

    def test_token_budget_truncates_and_keeps_highest_ranked(self):
        # Each chunk is ~250 chars => ~62 estimated tokens (4 chars/token).
        # A budget of 100 tokens should keep only the first (highest-ranked)
        # chunk, since results arrive pre-ranked by score.
        def _chunk(marker: str) -> str:
            return f"MARKER_{marker} " + "x" * 240

        results = [
            _fake_result(_chunk("top"), score=0.9, name="top"),
            _fake_result(_chunk("second"), score=0.8, name="second"),
            _fake_result(_chunk("third"), score=0.7, name="third"),
        ]
        retriever = _make_retriever(budget_tokens=100)
        context = retriever.build_context(results, include_metadata=False)
        assert "MARKER_top" in context
        assert "MARKER_second" not in context
        assert "MARKER_third" not in context

    def test_token_budget_is_respected_within_a_small_tolerance(self):
        from advisor.rag_retrieval import _estimate_tokens

        big_chunk = "y" * 400
        results = [_fake_result(big_chunk, score=1.0 - 0.01 * i, name=f"r{i}") for i in range(10)]
        budget = 300
        retriever = _make_retriever(budget_tokens=budget)
        context = retriever.build_context(results, include_metadata=False)
        # The loop stops *before* exceeding budget with the next chunk, so
        # the assembled context should not wildly overshoot it.
        assert _estimate_tokens(context) <= budget

    def test_empty_results_returns_placeholder(self):
        retriever = _make_retriever(budget_tokens=2000)
        assert retriever.build_context([]) == "No relevant code found."
