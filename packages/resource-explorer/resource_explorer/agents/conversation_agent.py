"""Multi-turn conversation agent — persistent BeeAI agent with TokenMemory."""
from __future__ import annotations

import asyncio
import concurrent.futures

from resource_explorer.agents.base import BaseExplorerAgent


class ConversationAgent(BaseExplorerAgent):
    """
    Multi-turn chat agent that maintains conversation context across calls.

    Uses a single persistent BeeAI RequirementAgent instance with TokenMemory so
    that prior turns are available to the LLM without manual history injection.
    All explorer tools are wired in: the agent decides which to call based on the
    question, rather than routing through RAGSystem.

    Falls back to RAGSystem.query() if BeeAI is unavailable.
    """

    def __init__(
        self,
        resource_slug: str | None = None,
        rag_system=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.resource_slug = resource_slug
        self._rag = rag_system  # optional pre-warmed fallback; created lazily if None
        self._agent = None  # lazy-init; kept alive across turns

    def system_prompt(self) -> str:
        scope = f" for the {self.resource_slug} project/resource" if self.resource_slug else ""
        return (
            f"You are a knowledgeable assistant{scope} for exploring resources in the metadata catalog, including Git projects, databases, and filesystems. "
            "Use your available tools to answer questions about source code, documentation, "
            "repository health, database schemas, tables, columns, file structures, and data quality check results. "
            "Maintain context from the conversation — refer back to earlier questions "
            "and answers when relevant. "
            "When a question names a resource (project, database, or filesystem) explicitly, pass that slug/name to the tools. "
            "When it doesn't, infer it from context or ask the user."
        )

    def tools(self) -> list:
        from resource_explorer.agents.tools import (
            vector_search,
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_contributor_profile,
            query_code_symbols,
            get_symbol_detail,
            query_databases,
            query_database_schema,
            query_filesystems,
        )
        return [
            vector_search,
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_contributor_profile,
            query_code_symbols,
            get_symbol_detail,
            query_databases,
            query_database_schema,
            query_filesystems,
        ]

    def _get_agent(self):
        """Return the persistent agent, creating it once on first use."""
        if self._agent is None:
            from beeai_framework.agents.requirement import RequirementAgent
            from beeai_framework.memory.token_memory import TokenMemory
            self._agent = RequirementAgent(
                llm=self._llm_name(),
                tools=self.tools(),
                instructions=self.system_prompt(),
                memory=TokenMemory(max_tokens=8000),
            )
        return self._agent

    def load_history(self, turns: list[dict]) -> None:
        """Pre-populate the agent's TokenMemory from a list of saved turns.

        Each dict must have 'role' ('user'|'assistant') and 'content' keys.
        Silently skips if BeeAI is unavailable or memory injection fails.
        """
        if not turns:
            return
        try:
            from beeai_framework.backend.message import AssistantMessage, UserMessage

            async def _inject() -> None:
                agent = self._get_agent()
                for turn in turns:
                    if turn["role"] == "user":
                        await agent.memory.add(UserMessage(turn["content"]))
                    else:
                        await agent.memory.add(AssistantMessage(turn["content"]))

            try:
                asyncio.get_running_loop()
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                    ex.submit(lambda: asyncio.run(_inject())).result(timeout=10)
            except RuntimeError:
                asyncio.run(_inject())
        except Exception:
            pass

    def handle(self, query: str, resource_slug: str | None = None, **kwargs) -> str:
        slug = resource_slug or self.resource_slug or self._infer_project_slug(query)

        # Delegate example generation to the specialist — BeeAI + small models produce
        # incomplete responses for this intent without the dedicated context/fallback loop.
        from resource_explorer.query_processor import QueryProcessor, QueryIntent
        if QueryProcessor().classify(query) == QueryIntent.EXAMPLES:
            from resource_explorer.agents.examples_agent import ExamplesAgent
            return ExamplesAgent().handle(query, resource_slug=slug)

        lines: list[str] = []
        if slug:
            lines.append(f"Project: {slug}")
            # Tell the agent which collection names exist so it can call vector_search correctly
            from resource_explorer.collection_router import CollectionRouter
            collections = CollectionRouter().select(query, slug)
            if collections:
                lines.append(f"Available collections: {', '.join(collections)}")
        lines.append(f"Question: {query}")
        prompt = "\n".join(lines)

        try:
            return self._run_persistent(prompt)
        except Exception:
            if self._rag is None:
                from resource_explorer.rag_system import RAGSystem
                self._rag = RAGSystem()
            return self._rag.query(query, resource_slug=slug)

    def _run_persistent(self, prompt: str) -> str:
        """Run the persistent agent, reusing the same instance so TokenMemory accumulates."""
        async def _inner() -> str:
            agent = self._get_agent()
            result = await agent.run(prompt)
            if hasattr(result, "output") and result.output:
                first = result.output[0]
                return first.text if hasattr(first, "text") else str(first)
            return str(result)

        try:
            asyncio.get_running_loop()
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                return ex.submit(lambda: asyncio.run(_inner())).result()
        except RuntimeError:
            return asyncio.run(_inner())
