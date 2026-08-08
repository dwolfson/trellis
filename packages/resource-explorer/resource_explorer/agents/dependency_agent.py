"""Dependency agent — answers questions about project dependencies and shared packages."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent


class DependencyAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return (
            "You are an expert at analyzing software dependency graphs. "
            "Use your tools to answer questions about what packages or libraries a project depends on, "
            "version constraints, dependency types (runtime, dev, optional), "
            "and shared dependencies between projects. "
            "When asked about multiple projects, compare their dependency lists. "
            "Format your answers clearly — prefer markdown tables for lists of dependencies."
        )

    def tools(self) -> list:
        from resource_explorer.agents.tools import query_dependencies, query_project_stats
        return [query_dependencies, query_project_stats]

    def handle(self, query: str, project_slug: str | None = None, **kwargs) -> str:
        slug = project_slug or self._infer_project_slug(query)

        if not slug:
            projects = self._list_all_slugs()
            if len(projects) == 1:
                slug = projects[0]
            elif not projects:
                return "No projects are indexed yet. Run 'project-explorer add <url>' to get started."
            else:
                return self._clarification_response(query)

        prompt_lines = [f"Project: {slug}", f"Question: {query}"]
        prompt = "\n".join(prompt_lines)

        try:
            return self._run_agent(prompt)
        except Exception:
            return self._fallback(query, slug)

    def _fallback(self, query: str, slug: str) -> str:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()

        q = query.lower()

        # Cross-project shared-dependency query
        slugs_in_query = self._infer_all_project_slugs(query)
        if len(slugs_in_query) >= 2:
            shared = registry.query_shared_dependencies(slugs_in_query)
            if not shared:
                return f"No shared dependencies found between {' and '.join(slugs_in_query)}."
            lines = [f"Shared dependencies between {' and '.join(slugs_in_query)}:", "",
                     "| Package | Ecosystem | Projects |",
                     "|---------|-----------|---------|"]
            for d in shared:
                lines.append(f"| {d['dep_name']} | {d['ecosystem']} | {d['projects']} |")
            return "\n".join(lines)

        dep_type = None
        if "dev" in q or "development" in q:
            dep_type = "dev"
        elif "optional" in q:
            dep_type = "optional"
        elif "runtime" in q or "production" in q:
            dep_type = "runtime"

        deps = registry.query_dependencies(slug, dep_type=dep_type)
        if not deps:
            return (
                f"No dependencies are indexed for '{slug}'. "
                f"Run 'project-explorer refresh {slug}' to parse manifests."
            )

        filter_label = dep_type or "all"
        lines = [
            f"Dependencies for **{slug}** ({filter_label}):", "",
            "| Package | Version | Type | Ecosystem |",
            "|---------|---------|------|-----------|",
        ]
        for d in deps[:50]:
            lines.append(
                f"| {d['dep_name']} | {d['dep_version'] or '—'} | {d['dep_type']} | {d['ecosystem']} |"
            )
        if len(deps) > 50:
            lines.append(f"\n_…and {len(deps) - 50} more. Use dep_type filter to narrow results._")
        return "\n".join(lines)

    def _infer_all_project_slugs(self, query: str) -> list[str]:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
        q_lower = query.lower()
        return [
            p.slug for p in registry.list_all()
            if p.slug in q_lower or (p.display_name and p.display_name.lower() in q_lower)
        ]

    def _list_all_slugs(self) -> list[str]:
        from resource_explorer.registry import ProjectRegistry
        return [p.slug for p in ProjectRegistry().list_all()]
