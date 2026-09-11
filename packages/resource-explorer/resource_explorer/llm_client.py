"""LLM abstraction — Ollama default, OpenAI and Anthropic as drop-in alternatives."""
from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol, runtime_checkable

from resource_explorer.config import ExplorerConfig, get_config
from resource_explorer.observability import llm_usage


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
        # prompt_eval_count / eval_count are Ollama's names for prompt and
        # completion tokens; both are absent on some responses, and llm_usage
        # records a missing half as UNCOUNTED rather than as zero.
        llm_usage.record(response.get("prompt_eval_count"),
                         response.get("eval_count"), self._model)
        return response["message"]["content"]

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # Ollama carries the counts on the final `done` chunk only, whose
        # message content is empty — so they are picked up as the loop runs
        # rather than read off a return value.
        prompt_tokens = completion_tokens = None
        try:
            for chunk in self._client.chat(
                model=self._model,
                messages=messages,
                stream=True,
                options={"temperature": self._temperature, "num_ctx": self._num_ctx, **kwargs},
            ):
                if chunk.get("prompt_eval_count") is not None:
                    prompt_tokens = chunk.get("prompt_eval_count")
                    completion_tokens = chunk.get("eval_count")
                yield chunk["message"]["content"]
        finally:
            # try/finally, not a plain trailing call: a consumer that breaks out
            # of the loop closes this generator, GeneratorExit is raised AT the
            # yield, and anything after the loop never runs — the call would
            # vanish from the accounting entirely, which is worse than being
            # uncounted. Abandoned early, both counts are still None and
            # `record` books it as UNCOUNTED.
            llm_usage.record(prompt_tokens, completion_tokens, self._model)


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
        usage = getattr(response, "usage", None)
        llm_usage.record(getattr(usage, "prompt_tokens", None),
                         getattr(usage, "completion_tokens", None), self._model)
        return response.choices[0].message.content or ""

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        # `stream_options={"include_usage": True}` is a REQUEST change, not a
        # read: without it OpenAI sends no usage on a stream at all. It adds one
        # final chunk carrying `usage` and an EMPTY `choices` list, which is why
        # the guard below tests `chunk.choices` before indexing it — the old
        # `chunk.choices[0]` would raise IndexError on that chunk.
        prompt_tokens = completion_tokens = None
        try:
            for chunk in self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                temperature=self._temperature,
                stream=True,
                stream_options={"include_usage": True},
            ):
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    prompt_tokens = getattr(usage, "prompt_tokens", None)
                    completion_tokens = getattr(usage, "completion_tokens", None)
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            llm_usage.record(prompt_tokens, completion_tokens, self._model)


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
        usage = getattr(response, "usage", None)
        llm_usage.record(getattr(usage, "input_tokens", None),
                         getattr(usage, "output_tokens", None), self._model)
        return response.content[0].text

    def stream(self, prompt: str, system: str = "", **kwargs) -> Iterator[str]:
        # Anthropic reports usage through message_start/message_delta events,
        # which `text_stream` does not surface — `get_final_message()`
        # reassembles them once the stream is exhausted. Only reachable when the
        # stream actually finishes; an abandoned one falls through to the
        # `finally` with both counts still None and is booked as UNCOUNTED.
        prompt_tokens = completion_tokens = None
        try:
            with self._client.messages.stream(
                model=self._model,
                max_tokens=4096,
                system=system or "You are a helpful assistant.",
                messages=[{"role": "user", "content": prompt}],
                temperature=self._temperature,
            ) as stream:
                yield from stream.text_stream
                usage = getattr(stream.get_final_message(), "usage", None)
                prompt_tokens = getattr(usage, "input_tokens", None)
                completion_tokens = getattr(usage, "output_tokens", None)
        finally:
            llm_usage.record(prompt_tokens, completion_tokens, self._model)


def get_llm(config: ExplorerConfig | None = None) -> LLMBackend:
    cfg = config or get_config()
    backend = cfg.llm.backend
    if backend == "openai":
        return OpenAIBackend(cfg)
    if backend == "anthropic":
        return AnthropicBackend(cfg)
    return OllamaBackend(cfg)
