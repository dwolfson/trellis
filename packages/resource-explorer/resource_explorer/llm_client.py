"""LLM abstraction — Ollama default, OpenAI and Anthropic as drop-in alternatives."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from resource_explorer.config import ExplorerConfig, get_config


@runtime_checkable
class LLMBackend(Protocol):
    def complete(self, prompt: str, system: str = "", **kwargs) -> str: ...
    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]: ...


class OllamaBackend:
    """Default — local, Metal/CUDA accelerated, no API key required."""

    def __init__(self, config: ExplorerConfig | None = None) -> None:
        cfg = (config or get_config()).llm.ollama
        import ollama
        self._client = ollama.Client(host=cfg.base_url)
        self._model = cfg.model
        self._temperature = cfg.temperature
        # Resolved from the active model tier (resource_explorer/config.py
        # TIER_PRESETS) — passed as the Ollama `num_ctx` option on every
        # chat call so a model is never loaded at its full default context
        # window. An explicit num_ctx in **kwargs still wins (dict union
        # below keeps kwargs last).
        self._num_ctx = cfg.num_ctx

    def complete(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat(
            model=self._model,
            messages=messages,
            options={"temperature": self._temperature, "num_ctx": self._num_ctx, **kwargs},
        )
        return response["message"]["content"]

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        for chunk in self._client.chat(
            model=self._model,
            messages=messages,
            stream=True,
            options={"temperature": self._temperature, "num_ctx": self._num_ctx, **kwargs},
        ):
            yield chunk["message"]["content"]


class OpenAIBackend:
    def __init__(self, config: ExplorerConfig | None = None) -> None:
        cfg = (config or get_config()).llm.openai
        from openai import OpenAI
        self._client = OpenAI()
        self._model = cfg.model
        self._temperature = cfg.temperature

    def complete(self, prompt: str, system: str = "", **kwargs) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        response = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
        )
        return response.choices[0].message.content or ""

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        for chunk in self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            temperature=self._temperature,
            stream=True,
        ):
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


class AnthropicBackend:
    def __init__(self, config: ExplorerConfig | None = None) -> None:
        cfg = (config or get_config()).llm.anthropic
        from anthropic import Anthropic
        self._client = Anthropic()
        self._model = cfg.model
        self._temperature = cfg.temperature

    def complete(self, prompt: str, system: str = "", **kwargs) -> str:
        response = self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=system or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
        )
        return response.content[0].text

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        with self._client.messages.stream(
            model=self._model,
            max_tokens=4096,
            system=system or "You are a helpful assistant.",
            messages=[{"role": "user", "content": prompt}],
            temperature=self._temperature,
        ) as stream:
            yield from stream.text_stream


def get_llm(config: ExplorerConfig | None = None) -> LLMBackend:
    cfg = config or get_config()
    backend = cfg.llm.backend
    if backend == "openai":
        return OpenAIBackend(cfg)
    if backend == "anthropic":
        return AnthropicBackend(cfg)
    return OllamaBackend(cfg)
