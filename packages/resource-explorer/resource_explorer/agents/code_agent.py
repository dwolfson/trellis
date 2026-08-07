"""Code search agent — finds methods, classes, and usage examples in source code."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent
from resource_explorer.prompt_templates import code_agent_system_prompt


class CodeAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return code_agent_system_prompt()

    def tools(self) -> list:
        from resource_explorer.agents.tools import vector_search, query_code_symbols, get_symbol_detail
        return [vector_search, query_code_symbols, get_symbol_detail]

    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        slug = project_slug or self._infer_project_slug(query)
        from resource_explorer.collection_router import CollectionRouter
        collections = CollectionRouter().select(query, slug)
        if not collections:
            return "No code collections are indexed for this project."

        context_lines = []
        if slug:
            context_lines.append(f"Project: {slug}")
        context_lines.append(f"Available collections: {', '.join(collections)}")
        context_lines.append(f"\nQuestion: {query}")
        prompt = "\n".join(context_lines)

        try:
            return self._run_agent(prompt)
        except Exception:
            from resource_explorer.vector_store_pg import MultiCollectionStore
            from resource_explorer.prompt_templates import build_rag_prompt
            from resource_explorer.llm_client import get_llm
            results = MultiCollectionStore().search(query, collections)
            if not results:
                return "I couldn't find relevant code for that query in the indexed repositories."
            context = "\n\n---\n\n".join(
                f"[{r.collection} | score={r.score:.2f}]\n{r.text}" for r in results
            )
            return get_llm().complete(build_rag_prompt(query, context, slug))
