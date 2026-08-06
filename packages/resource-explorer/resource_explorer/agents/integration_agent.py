"""Integration agent — answers 'how do X and Y work together?' queries."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent


class IntegrationAgent(BaseExplorerAgent):
    """
    Answers ecosystem-fit and integration queries spanning two or more projects.

    Distinct from CompareAgent: instead of 'which is better?', the question is
    'can these be used together, and how?'  The agent looks for:
      - Explicit cross-project references in docs (does project A mention B?)
      - Shared contributors (active collaboration signal)
      - Compatible languages, interfaces, and data formats
      - Architectural fit from documentation excerpts

    Requires at least two project slugs resolvable from the query.
    Falls back to clarification if fewer than two can be inferred.
    """

    def system_prompt(self) -> str:
        return (
            "You are an expert on LF AI & Data projects and their ecosystem relationships. "
            "Your job is to determine whether two or more projects can be used together and how. "
            "Focus on: explicit integration documentation, shared contributors (collaboration signal), "
            "compatible data formats and interfaces, complementary feature sets, and architectural fit. "
            "Be concrete — cite specific APIs, data formats, or documentation passages. "
            "If integration is not well-documented, say so clearly rather than speculating. "
            "Structure your response as: (1) Integration summary, (2) How they connect technically, "
            "(3) Shared contributors if any, (4) Getting started recommendation."
        )

    def tools(self) -> list:
        from resource_explorer.agents.tools import (
            vector_search,
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_code_symbols,
        )
        return [
            vector_search,
            query_project_stats,
            query_top_committers,
            query_code_symbols,
        ]

    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        slugs = self._infer_all_project_slugs(query)

        if len(slugs) < 2:
            from resource_explorer.registry import ProjectRegistry
            available = ", ".join(p.slug for p in ProjectRegistry().list_all())
            return (
                "Please name at least two projects to explore integration "
                f"(e.g. 'Can I use egeria with agentstack?'). "
                f"Available: {available or 'none indexed yet'}."
            )

        from resource_explorer.registry import ProjectRegistry
        all_projects = {p.slug: p for p in ProjectRegistry().list_all()}

        project_info = []
        for slug in slugs:
            project = all_projects.get(slug)
            if project and project.collections:
                cols = ", ".join(sorted(project.collections))
                project_info.append(f"  {slug}: {cols}")
            else:
                project_info.append(f"  {slug}: (no collections indexed — stats only)")

        prompt = (
            f"Investigate whether these projects can be integrated: {', '.join(slugs)}\n\n"
            f"Available collections per project:\n" + "\n".join(project_info) + "\n\n"
            "Steps to follow:\n"
            "1. For each project, search its docs/README for any mention of the other project(s).\n"
            "2. Compare primary languages and data interfaces (query_project_stats).\n"
            "3. Check for shared contributors (query_top_committers for each project, compare names/emails).\n"
            "4. Search for integration keywords: 'plugin', 'connector', 'adapter', 'compatible', 'together'.\n\n"
            f"Question: {query}\n\n"
            "Respond with: integration summary, technical connection points, "
            "shared contributors (if any), and a concrete getting-started recommendation."
        )

        try:
            return self._run_agent(prompt)
        except Exception:
            return self._fallback(query, slugs)

    def _fallback(self, query: str, slugs: list[str]) -> str:
        """Direct tool-call fallback when BeeAI is unavailable."""
        from resource_explorer.agents.tools import query_project_stats, vector_search, query_top_committers
        from resource_explorer.collection_router import CollectionRouter
        from resource_explorer.llm_client import get_llm

        router = CollectionRouter()
        sections: list[str] = []
        for slug in slugs:
            stat_text = query_project_stats(slug)
            committers = query_top_committers(slug, 5)
            collections = router.select("integration documentation connector", slug)
            doc_text = vector_search("integration connector compatible together", ",".join(collections)) if collections else "(no content)"
            sections.append(f"## {slug}\n{stat_text}\n\n### Top contributors\n{committers}\n\n### Docs\n{doc_text}")

        combined = "\n\n---\n\n".join(sections)
        prompt = (
            f"{self.system_prompt()}\n\n"
            f"Project data:\n\n{combined}\n\n"
            f"Question: {query}\n\nIntegration analysis:"
        )
        return get_llm().complete(prompt)
