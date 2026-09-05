"""Main orchestrator — entry point for all queries."""
from __future__ import annotations

import threading
import time

from resource_explorer.collection_router import CollectionRouter
from resource_explorer.config import get_config
from resource_explorer.llm_client import get_llm
from resource_explorer.vector_store_pg import MultiCollectionStore
from resource_explorer.prompt_templates import build_context, build_rag_prompt
from resource_explorer.query_cache import QueryCache
from resource_explorer.query_processor import QueryIntent, QueryProcessor
from resource_explorer.registry import ProjectRegistry


class RAGSystem:
    """
    Orchestrates the full query pipeline:
      cache check → intent classify → agent or RAG → LLM → async observability
    """

    def __init__(self) -> None:
        self.config = get_config()
        self.registry = ProjectRegistry()
        self.processor = QueryProcessor()
        self.cache = QueryCache()
        self.store = MultiCollectionStore()
        self.router = CollectionRouter()
        self.llm = get_llm()
        self._init_observability()

    def query(self, query: str, resource_slug: str | None = None) -> str:
        intent = self.processor.classify(query)

        cached = self.cache.get(query, resource_slug, intent.value)
        if cached:
            threading.Thread(
                target=self._track,
                args=(query, intent, resource_slug, cached, 0, True, []),
                daemon=True,
            ).start()
            return cached

        t0 = time.monotonic()
        response, chunk_refs = self._route(query, intent, resource_slug)
        latency_ms = int((time.monotonic() - t0) * 1000)

        self.cache.set(query, resource_slug, intent.value, response)

        threading.Thread(
            target=self._track,
            args=(query, intent, resource_slug, response, latency_ms, False, chunk_refs),
            daemon=True,
        ).start()

        return response

    def _route(self, query: str, intent: QueryIntent, resource_slug: str | None) -> tuple[str, list[str]]:
        """Returns (response, chunk_refs) — chunk_refs empty for non-RAG agents."""
        if intent == QueryIntent.STATISTICAL:
            from resource_explorer.agents.stats_agent import StatsAgent
            return StatsAgent().handle(query, resource_slug), []

        if intent == QueryIntent.DEPENDENCY:
            from resource_explorer.agents.dependency_agent import DependencyAgent
            return DependencyAgent().handle(query, resource_slug), []

        if intent == QueryIntent.INTEGRATION:
            from resource_explorer.agents.integration_agent import IntegrationAgent
            return IntegrationAgent().handle(query, resource_slug), []

        if intent == QueryIntent.COMPARISON:
            from resource_explorer.agents.compare_agent import CompareAgent
            return CompareAgent().handle(query, resource_slug), []

        if intent == QueryIntent.HEALTH:
            from resource_explorer.agents.health_agent import HealthAgent
            return HealthAgent().handle(query, resource_slug), []

        if intent == QueryIntent.CODE_INVENTORY:
            from resource_explorer.agents.code_agent import CodeAgent
            return CodeAgent().handle(query, resource_slug), []

        if intent == QueryIntent.EXAMPLES:
            from resource_explorer.agents.examples_agent import ExamplesAgent
            return ExamplesAgent().handle(query, resource_slug), []

        if intent == QueryIntent.CODE_SEARCH:
            from resource_explorer.agents.code_agent import CodeAgent
            return CodeAgent().handle(query, resource_slug), []

        if intent == QueryIntent.CONCEPTUAL:
            from resource_explorer.agents.doc_agent import DocAgent
            return DocAgent().handle(query, resource_slug), []

        if intent == QueryIntent.SURVEY_META:
            from resource_explorer.agents.survey_meta_agent import SurveyMetaAgent
            return SurveyMetaAgent().handle(query, resource_slug), []

        return self._rag(query, resource_slug)

    def stream(self, query: str, resource_slug: str | None = None):
        """
        Streaming variant of query(). Yields text chunks as they are generated.

        For agent-routed intents (statistical, health, etc.) the agent runs to
        completion first and the full response is yielded as one chunk — those
        paths are fast SQL reads, not LLM-heavy.

        For general RAG the LLM synthesis step is streamed token-by-token via
        LLMBackend.stream().

        Always yields a final sentinel dict {"_done": True, ...} so the caller
        can attach metadata (intent, hash, chart) after the text stream ends.
        """
        import hashlib

        intent = self.processor.classify(query)
        query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]

        cached = self.cache.get(query, resource_slug, intent.value)
        if cached:
            yield cached
            yield {"_done": True, "intent": intent.value, "hash": query_hash, "cached": True}
            return

        if intent != QueryIntent.GENERAL:
            # Agent paths: run to completion, then yield
            response, chunk_refs = self._route(query, intent, resource_slug)
            self.cache.set(query, resource_slug, intent.value, response)
            threading.Thread(
                target=self._track,
                args=(query, intent, resource_slug, response, 0, False, chunk_refs),
                daemon=True,
            ).start()
            yield response
            yield {"_done": True, "intent": intent.value, "hash": query_hash, "cached": False}
            return

        # General RAG — stream the LLM synthesis
        collections = self.router.select(query, resource_slug)
        results = self.store.search(query, collections)
        if not results:
            msg = "I don't have enough information in the indexed content to answer that."
            yield msg
            yield {"_done": True, "intent": intent.value, "hash": query_hash, "cached": False}
            return

        chunk_refs = [f"{r.collection}:{r.id}" for r in results]
        context = build_context(results, self.config.rag.budget_tokens)
        prompt = build_rag_prompt(query, context, resource_slug)

        full_response: list[str] = []
        for chunk in self.llm.stream(prompt):
            full_response.append(chunk)
            yield chunk

        response = "".join(full_response)
        self.cache.set(query, resource_slug, intent.value, response)
        threading.Thread(
            target=self._track,
            args=(query, intent, resource_slug, response, 0, False, chunk_refs),
            daemon=True,
        ).start()
        yield {"_done": True, "intent": intent.value, "hash": query_hash, "cached": False}

    def _rag(self, query: str, resource_slug: str | None) -> tuple[str, list[str]]:
        collections = self.router.select(query, resource_slug)
        results = self.store.search(query, collections)
        if not results:
            return "I don't have enough information in the indexed content to answer that.", []
        chunk_refs = [f"{r.collection}:{r.id}" for r in results]
        context = build_context(results, self.config.rag.budget_tokens)
        prompt = build_rag_prompt(query, context, resource_slug)
        return self.llm.complete(prompt), chunk_refs

    def _init_observability(self) -> None:
        from resource_explorer.observability.phoenix_client import init_phoenix
        from resource_explorer.observability.metrics_collector import MetricsCollector
        init_phoenix()
        self.metrics = MetricsCollector()

    def _track(
        self,
        query: str,
        intent: QueryIntent,
        resource_slug: str | None,
        response: str,
        latency_ms: int = 0,
        cache_hit: bool = False,
        chunk_refs: list[str] | None = None,
    ) -> None:
        try:
            self.metrics.record_query(
                query, intent.value, resource_slug, response,
                latency_ms=latency_ms, cache_hit=cache_hit,
                chunk_refs=chunk_refs or [],
            )
        except Exception:
            pass
