"""Base agent — BeeAI RequirementAgent wrapper for Egeria Advisor."""
from __future__ import annotations

import asyncio
import concurrent.futures
from abc import ABC, abstractmethod
from typing import Any


class BaseAdvisorAgent(ABC):
    """
    Wraps BeeAI RequirementAgent with standard Egeria Advisor configuration.

    Subclasses implement system_prompt() and tools() and call _run_agent(prompt).
    The BeeAI loop, retry logic, and streaming are handled here.
    """

    @abstractmethod
    def system_prompt(self) -> str: ...

    @abstractmethod
    def tools(self) -> list[Any]: ...

    def _build_agent(self):
        from beeai_framework.agents.requirement import RequirementAgent
        from advisor.config import get_full_config
        config = get_full_config()
        llm_cfg = config.get("llm")
        model = getattr(llm_cfg, "models", None)
        model_name = getattr(model, "conversation", "llama3.1:8b") if model else "llama3.1:8b"
        base_url = getattr(llm_cfg, "base_url", "http://localhost:11434")
        # BeeAI expects "ollama:model" for Ollama backends
        llm_id = f"ollama:{model_name}"
        return RequirementAgent(
            llm=llm_id,
            tools=self.tools(),
            instructions=self.system_prompt(),
        )

    def _run_agent(self, prompt: str) -> str:
        """Run the BeeAI RequirementAgent synchronously, handling nested event loops."""
        async def _inner():
            agent = self._build_agent()
            result = await agent.run(prompt)
            if hasattr(result, "output") and result.output:
                first = result.output[0]
                return first.text if hasattr(first, "text") else str(first)
            return str(result)

        try:
            asyncio.get_running_loop()
            # Already inside an async context (e.g. FastAPI executor thread) — spawn fresh loop
            def _in_thread():
                return asyncio.run(_inner())
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(_in_thread).result(timeout=60)
        except RuntimeError:
            return asyncio.run(_inner())


class BaseAgent(ABC):
    """Legacy base agent class for specialized agents not using BeeAI."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def process(self, query: str, context: Any = None) -> Any:
        pass

    def _format_response(
        self,
        response: str,
        sources: Any = None,
        confidence: float = 1.0
    ) -> Any:
        return {
            "agent": self.name,
            "response": response,
            "sources": sources or [],
            "confidence": confidence
        }

