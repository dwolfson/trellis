"""Examples agent — generates complete, runnable Python code examples for indexed projects."""
from __future__ import annotations

from resource_explorer.agents.base import BaseExplorerAgent


class ExamplesAgent(BaseExplorerAgent):
    def system_prompt(self) -> str:
        return (
            "You are an expert Python developer who generates clear, complete, runnable code examples "
            "for open-source projects. Your job is to produce working code, not describe how to write it.\n\n"
            "Workflow:\n"
            "1. Call build_example_context with the project slug and a specific topic derived from the question.\n"
            "2. Call query_code_symbols to discover the relevant classes and methods.\n"
            "3. If you need detail on a specific symbol, call get_symbol_detail.\n"
            "4. Generate a complete Python example that includes:\n"
            "   - All necessary imports\n"
            "   - Setup / initialisation (client creation, auth, config)\n"
            "   - The core demonstration requested\n"
            "   - Brief inline comments on non-obvious steps\n\n"
            "Rules:\n"
            "- Return the example inside a fenced ```python block.\n"
            "- Follow the example with a short explanation (2-4 sentences).\n"
            "- Only use class names, method names, and parameters you saw in the retrieved context. "
            "  If a detail is unclear, use a clearly labelled placeholder like `YOUR_HOST` or `YOUR_TOKEN`.\n"
            "- Never invent API methods. If you cannot find the right API, say so and show the closest "
            "  available alternative.\n"
            "- Prefer idiomatic Python: context managers, type hints where they add clarity, "
            "  f-strings over concatenation."
        )

    def tools(self) -> list:
        from resource_explorer.agents.tools import (
            build_example_context,
            query_code_symbols,
            get_symbol_detail,
            vector_search,
        )
        return [build_example_context, query_code_symbols, get_symbol_detail, vector_search]

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

        prompt = f"Project: {slug}\n\nRequest: {query}"
        try:
            response = self._run_agent(prompt)
            # Only accept a BeeAI response that contains an actual fenced code
            # block — inline backticks or a plain-text method list don't count
            if "```python" in response:
                return response
            return self._fallback(query, slug)
        except Exception:
            return self._fallback(query, slug)

    # ── fallback: direct retrieval + LLM if BeeAI fails ──────────────────────

    def _fallback(self, query: str, slug: str) -> str:
        """Search relevant collections and ask the LLM directly to generate an example."""
        try:
            from resource_explorer.agents.tools import _build_example_context_raw, _query_code_symbols_raw
            from resource_explorer.llm_client import get_llm

            context = _build_example_context_raw(project_slug=slug, topic=query)
            # Cap context to avoid overwhelming small models
            if len(context) > 4000:
                context = context[:4000] + "\n...[truncated]"

            # Extract key terms from query for a targeted symbol search
            topic_words = " ".join(w for w in query.lower().split() if len(w) > 3)
            symbols_raw = _query_code_symbols_raw(
                project_slug=slug, kind="class", pattern=topic_words, limit=10
            )

            system = (
                "You are an expert Python developer. Your task is to write a complete, "
                "runnable Python code example based ONLY on the retrieved context below. "
                "IMPORTANT: Use ONLY the class names, imports, and method signatures that "
                "appear verbatim in the context — do NOT invent class names or module paths. "
                "Your response MUST contain a fenced ```python code block with complete, "
                "runnable code. Do NOT respond with only a text description."
            )
            user_prompt = (
                f"Write a complete Python code example for: {query}\n"
                f"Project: {slug}\n\n"
                f"Retrieved context (use ONLY these imports, class names, method signatures):\n"
                f"{context}\n\n"
                f"Relevant classes:\n{symbols_raw}\n\n"
                f"Respond with a ```python code block containing ALL necessary imports, "
                f"client setup (including constructor arguments visible in the context), "
                f"the requested operations, and error handling. Then add a brief explanation."
            )
            return get_llm().complete(user_prompt, system=system)
        except Exception as exc:
            return (
                f"Could not generate an example for '{query}' in '{slug}': {exc}\n\n"
                "Try running `project-explorer refresh <slug>` to ensure the project is fully indexed."
            )

    def _list_all_slugs(self) -> list[str]:
        from resource_explorer.registry import ProjectRegistry
        return [p.slug for p in ProjectRegistry().list_all()]
