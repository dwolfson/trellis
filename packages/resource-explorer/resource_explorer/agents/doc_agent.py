"""Documentation agent — conceptual Q&A from markdown and web docs."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent
from resource_explorer.prompt_templates import doc_agent_system_prompt


class DocAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return doc_agent_system_prompt()

    def tools(self) -> list:
        from resource_explorer.agents.tools import vector_search
        return [vector_search]

    def handle(self, query: str, resource_slug: str | None = None, **kwargs) -> str:
        slug = resource_slug or self._infer_project_slug(query)
        from resource_explorer.collection_router import CollectionRouter
        collections = CollectionRouter().select(query, slug)
        if not collections:
            return "No documentation collections are indexed for this project."

        context_lines = []
        if slug:
            context_lines.append(f"Project: {resource_slug}")
        context_lines.append(f"Available collections: {', '.join(collections)}")
        context_lines.append(f"\nQuestion: {query}")
        prompt = "\n".join(context_lines)

        try:
            return self._run_agent(prompt)
        except Exception:
            from resource_explorer.vector_store_pg import MultiCollectionStore
            from resource_explorer.prompt_templates import build_context, build_rag_prompt
            from resource_explorer.llm_client import get_llm
            results = MultiCollectionStore().search(query, collections)
            if not results:
                return "I couldn't find relevant documentation for that query."
            context = build_context(results, self.config.rag.budget_tokens)
            return get_llm().complete(build_rag_prompt(query, context, slug))
