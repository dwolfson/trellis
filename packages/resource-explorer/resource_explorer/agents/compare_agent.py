"""Comparison agent — side-by-side analysis of two or more projects."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent
from resource_explorer.prompt_templates import compare_agent_system_prompt


class CompareAgent(BaseExplorerAgent):
    """
    Uses all four shared tools so the LLM can independently retrieve content
    and statistics for each project being compared.

    Handles two comparison modes:
      - Statistical: stars, commits, contributors, releases — uses query_project_stats,
        query_top_committers, query_commit_activity
      - Content/architecture: documentation and code differences — uses vector_search
    """

    def system_prompt(self) -> str:
        return compare_agent_system_prompt()

    def tools(self) -> list:
        from resource_explorer.agents.tools import (
            vector_search,
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_code_symbols,
            get_symbol_detail,
        )
        return [
            vector_search,
            query_project_stats,
            query_top_committers,
            query_commit_activity,
            query_code_symbols,
            get_symbol_detail,
        ]

    def handle(self, query: str, resource_slug: str | None = None, **kwargs) -> str:
        slugs = self._infer_all_project_slugs(query)

        if len(slugs) < 2:
            from resource_explorer.registry import ProjectRegistry
            available = ", ".join(p.slug for p in ProjectRegistry().list_all())
            return (
                "Please name at least two projects to compare "
                f"(e.g. 'compare project-a and project-b'). "
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

        # Tell the agent which mode to use based on query keywords
        q = query.lower()
        is_stat_comparison = any(w in q for w in (
            "star", "fork", "commit", "contributor", "release", "issue",
            "active", "popular", "growth", "download", "trend", "statistics",
            "stats", "number", "count", "how many",
        ))

        guidance = (
            "This is primarily a STATISTICAL comparison. Call query_project_stats for each "
            "project first, then query_top_committers and query_commit_activity if the user "
            "asks about contributors or activity trends. Do NOT call vector_search unless "
            "the user also asks about architecture or code."
            if is_stat_comparison else
            "This is primarily a CONTENT comparison. Call vector_search for each project "
            "to retrieve relevant documentation or code, then call query_project_stats for "
            "a brief stats snapshot to provide context."
        )

        prompt = (
            f"Compare these projects: {', '.join(slugs)}\n\n"
            f"Available collections per project:\n" + "\n".join(project_info) + "\n\n"
            f"Comparison guidance: {guidance}\n\n"
            f"Question: {query}\n\n"
            "Structure your response with:\n"
            "1. A summary table of key differences\n"
            "2. A section per comparison dimension (stats, architecture, use cases, etc.)\n"
            "3. A final recommendation or verdict if the user asked for one"
        )

        try:
            return self._run_agent(prompt)
        except Exception:
            return self._fallback(query, slugs)

    def _fallback(self, query: str, slugs: list[str]) -> str:
        """Direct tool-call fallback when BeeAI is unavailable."""
        from resource_explorer.agents.tools import query_project_stats, vector_search
        from resource_explorer.collection_router import CollectionRouter
        from resource_explorer.llm_client import get_llm

        sections: list[str] = []
        router = CollectionRouter()

        for slug in slugs:
            stat_text = query_project_stats(slug)
            collections = router.select(query, slug)
            if collections:
                doc_text = vector_search(query, ",".join(collections))
            else:
                doc_text = "(no indexed content)"
            sections.append(f"## {slug}\n\n### Stats\n{stat_text}\n\n### Content\n{doc_text}")

        combined = "\n\n---\n\n".join(sections)
        fallback_prompt = (
            f"{self.system_prompt()}\n\n"
            f"Data for projects being compared:\n\n{combined}\n\n"
            f"Question: {query}\n\nComparison:"
        )
        return get_llm().complete(fallback_prompt)

