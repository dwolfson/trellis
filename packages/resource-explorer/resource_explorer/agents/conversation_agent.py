"""Multi-turn conversation agent — persistent BeeAI agent with TokenMemory."""
from __future__ import annotations

import logging

import asyncio
import concurrent.futures

from resource_explorer.agents.base import BaseExplorerAgent


logger = logging.getLogger(__name__)


def _registry():
    from resource_explorer.registry import ProjectRegistry

    return ProjectRegistry()


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
        project_slug: str | None = None,
        rag_system=None,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.project_slug = project_slug
        self._rag = rag_system  # optional pre-warmed fallback; created lazily if None
        self._agent = None  # lazy-init; kept alive across turns
        #: The CompiledContext behind the most recent handle() call, or None.
        #: _compiled_evidence() computes this on every turn and previously
        #: discarded it once the prompt lines were built -- the caller (the
        #: HTTP route) had no way to show a user the same manifest/gaps/
        #: pointers that shaped the answer without a second, separate compile
        #: call. Read-after-handle() by the route, same pattern _sessions
        #: already uses to treat this agent as a stateful, reused object.
        self._last_compiled = None

    def system_prompt(self) -> str:
        scope = f" for the {self.project_slug} project/resource" if self.project_slug else ""
        return (
            f"You are a knowledgeable assistant{scope} for exploring resources in the metadata catalog, including Git projects, databases, and filesystems. "
            "Use your available tools to answer questions about source code, documentation, "
            "repository health, database schemas, tables, columns, file structures, and data quality check results. "
            "Maintain context from the conversation — refer back to earlier questions "
            "and answers when relevant. "
            "When a question names a resource (project, database, or filesystem) explicitly, pass that slug/name to the tools. "
            "When it doesn't, infer it from context or ask the user. "
            "\n\n"
            # Added 2026-08-31 after a measured failure: asked about this
            # repository's documentation survey results, the model instead
            # called vector_search and answered from Egeria's OWN
            # documentation about its unrelated Survey Framework feature — a
            # keyword match ("survey"), not an answer about this resource.
            # An "Evidence" block was present and DID address the question by
            # the time this was diagnosed; nothing told the model to prefer
            # it over a general-corpus tool call it was equally free to make.
            "When a message includes an 'Evidence (compiled from stored analysis results)' "
            "block, that block is the authoritative material for THIS resource — prefer it "
            "over vector_search, whose corpus is general documentation and can return content "
            "that matches a keyword in the question while being about something else entirely "
            "(a different feature, a different project) rather than about this resource. If the "
            "evidence does not cover what was asked, say so plainly and either ask a clarifying "
            "question or name what analysis would need to run — do not fall back to a broader "
            "search and present its results as though they answered the question. A confident "
            "answer built from the wrong source is a worse outcome than admitting the evidence "
            "doesn't cover it."
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

    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        slug = project_slug or self.project_slug or self._infer_project_slug(query)

        # Delegate example generation to the specialist — BeeAI + small models produce
        # incomplete responses for this intent without the dedicated context/fallback loop.
        from resource_explorer.query_processor import QueryProcessor, QueryIntent
        if QueryProcessor().classify(query) == QueryIntent.EXAMPLES:
            from resource_explorer.agents.examples_agent import ExamplesAgent
            return ExamplesAgent().handle(query, project_slug=slug)

        # Reset per turn, not just on failure -- a question with no resource
        # in scope must not show the previous turn's compiled evidence as if
        # it belonged to this answer.
        self._last_compiled = None

        lines: list[str] = []
        if slug:
            lines.append(f"Project: {slug}")
            # Tell the agent which collection names exist so it can call vector_search correctly
            from resource_explorer.collection_router import CollectionRouter
            collections = CollectionRouter().select(query, slug)
            if collections:
                lines.append(f"Available collections: {', '.join(collections)}")
            lines.extend(self._compiled_evidence(query, slug, kwargs.get("perspectives")))
        lines.append(f"Question: {query}")
        prompt = "\n".join(lines)

        try:
            return self._run_persistent(prompt)
        except Exception:
            if self._rag is None:
                from resource_explorer.rag_system import RAGSystem
                self._rag = RAGSystem()
            return self._rag.query(query, project_slug=slug)

    def _compiled_evidence(self, query: str, slug: str, perspectives) -> list[str]:
        """Packed evidence for the prompt, plus the names of what is missing.

        This is the difference between naming collections and supplying evidence.
        Previously the agent was told which collections exist and left to search
        them; now the analyses that the question catalog says answer this
        question are resolved from stored results, packed to a budget, and put
        in the prompt directly -- deterministic, and carrying which analysis
        produced each part.

        **Naming the gaps is the point, not a footnote.** An analysis with no
        stored result looks, from inside a prompt, exactly like one that ran and
        found nothing. Saying which analyses are missing is what stops the model
        answering "no CVEs" when the truth is that nothing was checked.

        **"No stored result", NOT "has not run".** An earlier version said the
        latter and was false for two of egeria_git's three gaps: repo_dependency
        and repo_cve_scan both RUN, cleanly, and each emits an annotation saying
        why it found nothing -- "1 manifest(s) are present" and "no dependencies
        are recorded, so nothing could be checked". project_dependencies is
        written only by IngestionPipeline and by no survey step, so re-running
        cannot change either. The old wording would have sent a reader to run
        something that had already run and could not help.

        The distinction that WOULD be actionable -- could-not-run versus
        ran-and-found-nothing -- already exists as step_outcome.py's UNVERIFIED,
        and DependencySurveyor already computes it correctly. It is embedded in
        an annotation and never persisted, so query time cannot see it. Surface
        that rather than inventing a second vocabulary for the same idea; a
        second vocabulary is how four RE perspectives ended up beside Egeria's
        twelve. Until it is retrievable, this sentence claims nothing about why.

        Fail-soft: any problem here returns nothing and the agent proceeds as it
        did before, searching collections itself. A compiler that cannot compile
        must not cost you the answer.
        """
        try:
            from resource_explorer.context_compile import compile_context

            compiled = compile_context(
                self.registry if hasattr(self, "registry") else _registry(),
                slug, query, perspectives=list(perspectives or []),
                # Deliberately a fraction of the model window: this is evidence
                # to reason over, not the whole prompt, and the agent still has
                # tools for anything the compile could not reach.
                budget=6000,
            )
        except Exception:
            logger.debug("compiled evidence unavailable for %s", slug, exc_info=True)
            return []

        self._last_compiled = compiled

        out: list[str] = []
        if compiled.text.strip():
            out.append("Evidence (compiled from stored analysis results):")
            out.append(compiled.text)
        # Grouped by what the fact layer judged, because these are opposite
        # answers to the same question and a single sentence cannot carry both.
        # "ran and found nothing" is a result; "has not run" is an absence.
        by_state: dict[str, list[str]] = {}
        for gap in compiled.manifest.get("gaps", []):
            by_state.setdefault(gap.get("reason", "no stored result"), []).append(gap["key"])
        for reason, keys in sorted(by_state.items()):
            out.append(f"Analyses that {reason}: " + ", ".join(sorted(keys)) + ".")
        if by_state:
            out.append(
                "Say so if the question depends on one of them. An analysis that "
                "ran and found nothing has answered; one that has not run has not. "
                "Do not read the first as the second."
            )
        return out

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
