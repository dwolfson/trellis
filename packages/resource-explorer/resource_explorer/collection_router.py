"""Selects which Milvus collections to search for a given query and project."""
from __future__ import annotations

from resource_explorer.configdata.collection_config import AGENT_COLLECTION_MAP
from resource_explorer.query_processor import QueryIntent
from resource_explorer.registry import ProjectRegistry


class CollectionRouter:
    """
    Given a query intent and optional project scope, returns the list of
    collection names (e.g. ['myproject_python_code', 'myproject_examples'])
    to pass to MultiCollectionStore.search().

    Capped at config.rag.max_collections_per_query — more collections means
    more latency and more noise; 2-3 targeted collections outperform searching all.
    """

    def __init__(self) -> None:
        self._registry = ProjectRegistry()

    def select(self, query: str, project_slug: str | None = None) -> list[str]:
        from resource_explorer.config import get_config
        cfg = get_config()
        max_collections = cfg.rag.max_collections_per_query

        intent = self._infer_agent_type(query)
        base_types = AGENT_COLLECTION_MAP.get(intent, AGENT_COLLECTION_MAP["general"])

        if project_slug:
            project_slug = self._registry._normalize_slug(project_slug)
            projects = [self._registry.get(project_slug)]
            projects = [p for p in projects if p is not None]
        else:
            projects = self._registry.list_all()

        collections = []
        for project in projects:
            for ctype in base_types:
                name = f"{project.slug}_{ctype}"
                if name in project.collections:
                    collections.append(name)

        return collections[:max_collections]

    def _infer_agent_type(self, query: str) -> str:
        from resource_explorer.query_processor import QueryProcessor
        intent = QueryProcessor().classify(query)
        mapping = {
            QueryIntent.CODE_SEARCH: "code",
            QueryIntent.CONCEPTUAL: "doc",
            QueryIntent.COMPARISON: "compare",
            QueryIntent.STATISTICAL: "stats",
            QueryIntent.HEALTH: "health",
            QueryIntent.GENERAL: "general",
        }
        return mapping.get(intent, "general")
