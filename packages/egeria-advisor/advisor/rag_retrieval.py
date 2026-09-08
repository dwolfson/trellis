"""
RAG retrieval module for combining vector search with context building.

This module handles retrieving relevant code snippets and building
context for LLM queries.
"""

from typing import List, Dict, Any, Optional, Tuple
from pathlib import Path
from loguru import logger
import asyncio

from advisor.vector_store import get_vector_store
from advisor.embeddings import get_embedding_generator
from advisor.config import get_full_config
from advisor.multi_collection_store import get_multi_collection_store
from advisor.query_cache import get_query_cache
from advisor.retrieval_outcome import RetrievalOutcome


def _estimate_tokens(text: str) -> int:
    """
    Cheap token-count approximation: ~4 characters per token.

    Not a real tokenizer call — good enough for a context-budget cutoff,
    not for anything that needs an exact count. See
    docs/runtime-architecture-plan.md §5: prompt tokens is the lever for
    time-to-first-token, and the demo tiers' RAG context budget is
    expressed in (approximate) tokens for that reason.
    """
    return max(1, len(text) // 4)


class RAGRetriever:
    """Retrieves and formats context for RAG queries."""

    def __init__(
        self,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        max_context_length: Optional[int] = None,
        use_multi_collection: bool = True,
        enable_cache: bool = True
    ):
        """
        Initialize RAG retriever.

        Args:
            top_k: Number of results to retrieve
            min_score: Minimum similarity score threshold
            max_context_length: Maximum context length in characters
            use_multi_collection: Use multi-collection search with routing
            enable_cache: Enable query result caching
        """
        config = get_full_config()
        rag_config = config.get("rag")

        self.vector_store = get_vector_store()
        self.multi_store = get_multi_collection_store() if use_multi_collection else None
        self.embedding_gen = get_embedding_generator()
        self.use_multi_collection = use_multi_collection
        self.enable_cache = enable_cache
        self.cache = get_query_cache() if enable_cache else None

        self.top_k = top_k or rag_config.retrieval.top_k
        self.min_score = min_score or rag_config.retrieval.min_score
        self.max_context_length = max_context_length or rag_config.context.max_length
        # Tier-resolved RAG context token budget (advisor/config.py
        # TIER_PRESETS). None (the `dev` tier) means the legacy
        # character-based max_context_length above is the only cutoff;
        # otherwise build_context() stops adding chunks once the estimated
        # token count would exceed this, keeping the highest-ranked chunks.
        self.rag_context_budget_tokens = rag_config.context.budget_tokens

        # Set by retrieve(), consulted by build_context() when results is
        # empty — distinguishes *why* there is nothing to build context from
        # (below threshold / empty collection / never ingested / store
        # unreachable). See advisor/retrieval_outcome.py.
        self._last_outcome: Optional[RetrievalOutcome] = None

        mode = "multi-collection" if use_multi_collection else "single-collection"
        cache_status = "with caching" if enable_cache else "no cache"
        logger.info(f"Initialized RAG retriever ({mode}, {cache_status}): top_k={self.top_k}, min_score={self.min_score}")

    def retrieve(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
        boosted_collections: Optional[List[str]] = None,
        feedback_adjustments: Optional[Dict[str, float]] = None
    ) -> List[Any]:  # Returns List[SearchResult]
        """
        Retrieve relevant code snippets for a query.

        Args:
            query: User query
            top_k: Number of results (overrides default)
            min_score: Minimum score (overrides default)
            filters: Optional metadata filters
            intent: Optional query intent
            boosted_collections: Collections to boost
            feedback_adjustments: Feedback loop adjustments

        Returns:
            List of retrieved SearchResult objects
        """
        top_k = top_k or self.top_k
        min_score = min_score or self.min_score

        # Reset every call — a stale outcome from a previous query must
        # never be attributed to this one's (possibly different) empty
        # result. build_context() only consults this when results is empty.
        self._last_outcome = None

        logger.info(f"Retrieving context for query: {query[:100]}...")

        # Check cache first
        if self.enable_cache and self.cache:
            cached_results = self.cache.get(
                query,
                top_k=top_k,
                min_score=min_score,
                use_multi=self.use_multi_collection
            )
            if cached_results is not None:
                logger.info(f"Retrieved {len(cached_results)} results from cache")
                return cached_results

        collections_searched: List[str] = []

        # Use multi-collection search if enabled
        try:
            if self.use_multi_collection and self.multi_store:
                logger.debug("Using multi-collection search with intelligent routing")

                # Search with routing
                multi_result = self.multi_store.search_with_routing(
                    query=query,
                    top_k=top_k,
                    min_score=min_score,
                    filters=filters,
                    intent=intent,
                    boosted_collections=boosted_collections,
                    feedback_adjustments=feedback_adjustments
                )

                results = multi_result.results
                collections_searched = list(multi_result.collections_searched)

                # Log routing info
                logger.info(f"Searched collections: {multi_result.collections_searched}")
                logger.debug(f"Collection scores: {multi_result.collection_scores}")

                # search_with_routing() catches each collection's own search
                # exception internally (so a broken collection cannot take
                # the whole query down) and records it in multi_result.errors
                # instead of raising. If EVERY searched collection failed,
                # that failure must not be reported as "the corpus has
                # nothing" — it is a fact about the store, not the corpus.
                if (
                    not results
                    and collections_searched
                    and multi_result.errors
                    and set(multi_result.errors) >= set(collections_searched)
                ):
                    detail = "; ".join(
                        f"{name}: {err}" for name, err in multi_result.errors.items()
                    )
                    self._last_outcome = RetrievalOutcome.store_unreachable(
                        detail, tuple(collections_searched)
                    )
                    logger.error(
                        f"All searched collections failed — treating as store "
                        f"unreachable, not as an empty corpus: {detail}"
                    )
                    return []

            else:
                logger.debug("Using single-collection search")

                # Generate query embedding
                query_embedding = self.embedding_gen.generate_embedding(query)

                collections_searched = ["code_elements"]
                # Search vector store
                results = self.vector_store.search(
                    collection_name="code_elements",
                    query_embedding=query_embedding,
                    top_k=top_k,
                    filters=filters
                )
        except Exception as exc:
            # Single-collection search (and query-embedding generation)
            # raise directly rather than swallowing, unlike the
            # multi-collection path above — either way, a connection
            # failure here is a fact about us, never about the corpus.
            logger.error(f"Retrieval failed — vector store unreachable: {exc}")
            self._last_outcome = RetrievalOutcome.store_unreachable(
                str(exc), tuple(collections_searched)
            )
            return []

        # Log scores for debugging
        if results:
            scores = [r.score for r in results]
            logger.debug(f"Result scores: {scores}")
            logger.debug(f"Min score threshold: {min_score}")

        # Filter by minimum score (multi-collection already filters, but double-check)
        filtered_results = [
            r for r in results
            if r.score >= min_score
        ]

        logger.info(f"Retrieved {len(filtered_results)} results (filtered from {len(results)})")

        if not filtered_results:
            self._last_outcome = self._diagnose_empty(results, collections_searched, min_score)

        # Cache the results for future queries
        if self.enable_cache and self.cache and filtered_results:
            self.cache.set(
                query,
                filtered_results,
                top_k=top_k,
                min_score=min_score,
                use_multi=self.use_multi_collection
            )
        
        return filtered_results

    def _diagnose_empty(
        self,
        raw_results: List[Any],
        collections_searched: List[str],
        min_score: float,
    ) -> RetrievalOutcome:
        """Why `filtered_results` came back empty, once the store itself was
        reachable and answered. `raw_results` is what came back *before* the
        final `min_score` cut (see the two call sites in `retrieve()`).

        - raw_results non-empty  -> case 1: below threshold.
        - raw_results empty      -> case 2 vs case 3, disambiguated by
          whether any searched collection has ever been ingested
          (`ingest_log`). If checking that itself fails, that failure is
          just as much a "fact about us" as the original search failing,
          so it is reported the same way rather than guessed at.
        """
        if raw_results:
            return RetrievalOutcome.below_threshold(min_score, tuple(collections_searched))

        try:
            ingested = self._any_collection_ingested(collections_searched)
        except Exception as exc:
            logger.error(f"Could not determine ingestion status: {exc}")
            return RetrievalOutcome.store_unreachable(str(exc), tuple(collections_searched))

        if not ingested:
            return RetrievalOutcome.never_ingested(tuple(collections_searched))
        return RetrievalOutcome.collection_empty(tuple(collections_searched))

    @staticmethod
    def _any_collection_ingested(collections: List[str]) -> bool:
        """True if `ingest_log` (advisor/db_consolidated.py) has a row for
        any of these collections — i.e. ingestion has run at least once.
        Raises on a DB problem rather than swallowing it, so the caller can
        tell "never ingested" apart from "could not check"."""
        if not collections:
            return False

        from advisor.db_consolidated import get_db_manager

        db_manager = get_db_manager()
        placeholders = ", ".join(["%s"] * len(collections))
        sql = f"SELECT collection_name FROM ingest_log WHERE collection_name IN ({placeholders})"
        rows = db_manager.execute_query(sql, tuple(collections))
        return bool(rows)

    async def retrieve_async(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Any]:  # Returns List[SearchResult]
        """
        Retrieve relevant code snippets for a query asynchronously.

        Args:
            query: User query
            top_k: Number of results (overrides default)
            min_score: Minimum score (overrides default)
            filters: Optional metadata filters

        Returns:
            List of retrieved SearchResult objects
        """
        # For now, run the sync version in an executor to avoid blocking
        # In the future, this could use true async vector store operations
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            self.retrieve,
            query,
            top_k,
            min_score,
            filters
        )

        return filtered_results

    def build_context(
        self,
        results: List[Any],  # SearchResult objects
        include_metadata: bool = True,
        format_style: str = "detailed"
    ) -> str:
        """
        Build formatted context from retrieval results.

        Args:
            results: Retrieved SearchResult objects
            include_metadata: Whether to include metadata
            format_style: "detailed" or "compact"

        Returns:
            Formatted context string. When `results` is empty this is one of
            the four distinguishing messages built from `self._last_outcome`
            (set by the `retrieve()` call that normally precedes this one) —
            never the single collapsed "No relevant code found." that used to
            cover all four. See advisor/retrieval_outcome.py.
        """
        if not results:
            outcome = getattr(self, "_last_outcome", None)
            if outcome is None:
                # build_context() was called directly, bypassing retrieve()
                # (e.g. get_file_context(), or a caller with its own result
                # list) — there is no diagnosis to consult. Say that,
                # rather than silently reporting one of the four specific
                # causes as if it were known.
                outcome = RetrievalOutcome.unknown()
            logger.info(f"No context to build ({outcome.reason}): {outcome.message}")
            return outcome.message

        context_parts = []
        total_length = 0
        total_tokens = 0
        budget_tokens = self.rag_context_budget_tokens

        # `results` arrives pre-ranked by retrieval score (highest first);
        # this loop only ever stops early, never reorders, so whichever
        # budget is active keeps the highest-ranked chunks and drops the
        # lowest-ranked ones. Retrieval ranking itself is untouched here.
        for i, result in enumerate(results, 1):
            # Extract fields from SearchResult object
            code = result.text
            # Access metadata dictionary
            metadata = result.metadata
            file_path = metadata.get("file_path", "unknown")
            element_type = metadata.get("type", "unknown")  # Note 'type' vs 'element_type'
            name = metadata.get("name", "unnamed")
            score = result.score

            # Format based on style
            if format_style == "detailed":
                part = self._format_detailed(
                    i, code, file_path, element_type, name, score, include_metadata
                )
            else:
                part = self._format_compact(
                    i, code, file_path, name, include_metadata
                )

            if budget_tokens is not None:
                # Tier RAG context budget (demo-gpu/demo-cpu): token-based.
                part_tokens = _estimate_tokens(part)
                if total_tokens + part_tokens > budget_tokens:
                    logger.warning(
                        f"RAG context token budget ({budget_tokens}) reached at "
                        f"{i}/{len(results)} results (~{total_tokens} tokens so far)"
                    )
                    break
            else:
                # Legacy character-based budget (dev tier / no tier budget set).
                if total_length + len(part) > self.max_context_length:
                    logger.warning(f"Context length limit reached at {i}/{len(results)} results")
                    break

            context_parts.append(part)
            total_length += len(part)
            total_tokens += _estimate_tokens(part)

        context = "\n\n".join(context_parts)
        logger.info(f"Built context: {len(context_parts)} snippets, {total_length} chars")
        logger.debug(
            f"Assembled RAG context token estimate (4 chars/token approximation): "
            f"~{_estimate_tokens(context)} tokens"
            + (f", budget={budget_tokens}" if budget_tokens is not None else "")
        )

        return context

    def _fetch_relational_metadata(self, name: str, file_path: str, element_type: str) -> str:
        """Fetch parent class, inheritance tree, and sibling methods from
        Resource Explorer's project_code_symbols/project_code_relationships
        tables (cross-schema, same Postgres instance — AST-ownership-transfer
        plan Phase 7; was EA's own code_symbols/code_relationships before).

        No explicit collection/project scoping was ever threaded through this
        call (name/file_path/element_type only) — the pre-migration version
        queried EA's whole code_symbols/code_relationships tables unscoped.
        Applying scope_clause(None) here bounds that same "no explicit scope"
        behavior to RE's egeria-group code-bearing projects specifically,
        rather than literally every project RE has ever ingested (which,
        unlike EA's old tables, can include projects with no relation to
        Egeria at all) — a safety improvement, not a behavior narrowing for
        this agent's actual use case.
        """
        try:
            from advisor.db_consolidated import get_db_manager
            from advisor.re_code_scope import scope_clause
            db_manager = get_db_manager()

            symbols_table = "resource_explorer.project_code_symbols"
            relationships_table = "resource_explorer.project_code_relationships"
            scope_sql, scope_params = scope_clause(None)

            relational_info = []

            # 1. If it's a method/function, find its parent class, sibling methods, and parent class inheritance
            if element_type in ("method", "function") or "method" in element_type:
                sql = (
                    f"SELECT parent_class FROM {symbols_table} "
                    f"WHERE name = %s AND (kind = 'method' OR kind = 'function') AND {scope_sql} LIMIT 1"
                )
                rows = db_manager.execute_query(sql, tuple([name] + scope_params))
                if rows and rows[0].get("parent_class"):
                    parent_class = rows[0]["parent_class"]
                    relational_info.append(f"**Parent Class:** `{parent_class}`")

                    # Find sibling methods
                    sql_siblings = (
                        f"SELECT name, signature FROM {symbols_table} "
                        f"WHERE parent_class = %s AND kind = 'method' AND name != %s AND {scope_sql} LIMIT 5"
                    )
                    sib_rows = db_manager.execute_query(sql_siblings, tuple([parent_class, name] + scope_params))
                    if sib_rows:
                        sib_names = [f"`{r['name']}{r['signature']}`" for r in sib_rows]
                        relational_info.append(f"**Sibling Methods:** {', '.join(sib_names)}")

                    # Find parent class inheritance
                    sql_parents = (
                        f"SELECT target_name FROM {relationships_table} "
                        f"WHERE source_name = %s AND relationship_type = 'inherits_from' AND {scope_sql}"
                    )
                    parent_rows = db_manager.execute_query(sql_parents, tuple([parent_class] + scope_params))
                    if parent_rows:
                        parents = [f"`{r['target_name']}`" for r in parent_rows]
                        relational_info.append(f"**Parent Class Inherits From:** {', '.join(parents)}")

            # 2. If it's a class, find its parent classes, child classes, and methods
            elif element_type == "class" or "class" in element_type:
                sql_parents = (
                    f"SELECT target_name FROM {relationships_table} "
                    f"WHERE source_name = %s AND relationship_type = 'inherits_from' AND {scope_sql}"
                )
                parent_rows = db_manager.execute_query(sql_parents, tuple([name] + scope_params))
                if parent_rows:
                    parents = [f"`{r['target_name']}`" for r in parent_rows]
                    relational_info.append(f"**Inherits From:** {', '.join(parents)}")

                sql_children = (
                    f"SELECT source_name FROM {relationships_table} "
                    f"WHERE target_name = %s AND relationship_type = 'inherits_from' AND {scope_sql}"
                )
                child_rows = db_manager.execute_query(sql_children, tuple([name] + scope_params))
                if child_rows:
                    children = [f"`{r['source_name']}`" for r in child_rows]
                    relational_info.append(f"**Subclasses:** {', '.join(children)}")

                sql_methods = (
                    f"SELECT name, signature FROM {symbols_table} "
                    f"WHERE parent_class = %s AND kind = 'method' AND {scope_sql} LIMIT 5"
                )
                method_rows = db_manager.execute_query(sql_methods, tuple([name] + scope_params))
                if method_rows:
                    methods = [f"`{r['name']}{r['signature']}`" for r in method_rows]
                    relational_info.append(f"**Defined Methods:** {', '.join(methods)}")

            if relational_info:
                return "\n".join(relational_info)
        except Exception as e:
            logger.debug(f"Failed to fetch relational metadata: {e}")
        return ""

    def _format_detailed(
        self,
        index: int,
        code: str,
        file_path: str,
        element_type: str,
        name: str,
        score: float,
        include_metadata: bool
    ) -> str:
        """Format result in detailed style."""
        parts = [f"### Result {index}"]

        if include_metadata:
            parts.append(f"**File:** `{file_path}`")
            parts.append(f"**Type:** {element_type}")
            parts.append(f"**Name:** {name}")
            parts.append(f"**Relevance:** {score:.3f}")
            
            # Fetch relational metadata
            rel_metadata = self._fetch_relational_metadata(name, file_path, element_type)
            if rel_metadata:
                parts.append(rel_metadata)

        parts.append("**Code:**")
        parts.append(f"```python\n{code}\n```")

        return "\n".join(parts)

    def _format_compact(
        self,
        index: int,
        code: str,
        file_path: str,
        name: str,
        include_metadata: bool
    ) -> str:
        """Format result in compact style."""
        if include_metadata:
            header = f"[{index}] {name} ({file_path})"
        else:
            header = f"[{index}]"

        return f"{header}\n```python\n{code}\n```"

    def retrieve_and_build_context(
        self,
        query: str,
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        format_style: str = "detailed",
        include_metadata: bool = True,
        prioritize_docs: bool = False,
        intent: Optional[str] = None,
        boosted_collections: Optional[List[str]] = None,
        feedback_adjustments: Optional[Dict[str, float]] = None
    ) -> Tuple[str, List[Dict[str, Any]]]:
        """
        Retrieve and build context in one step.

        Args:
            query: User query
            top_k: Number of results
            min_score: Minimum score
            filters: Metadata filters
            format_style: Context format style
            include_metadata: Include metadata in context
            prioritize_docs: Prioritize documentation collections over code
            intent: Optional query intent
            boosted_collections: Collections to boost
            feedback_adjustments: Feedback loop adjustments

        Returns:
            Tuple of (formatted_context, sources_as_dicts)
        """
        # If prioritizing docs, add collection filter for documentation
        if prioritize_docs and self.use_multi_collection and self.multi_store:
            logger.info("Prioritizing documentation collections for this query")
            # The multi-collection router will handle this via domain terms
            # We just need to pass the flag through
        
        results = self.retrieve(
            query=query,
            top_k=top_k,
            min_score=min_score,
            filters=filters,
            intent=intent,
            boosted_collections=boosted_collections,
            feedback_adjustments=feedback_adjustments
        )

        context = self.build_context(
            results=results,
            include_metadata=include_metadata,
            format_style=format_style
        )

        # Convert SearchResult objects to dictionaries for easier handling
        sources = []
        for result in results:
            source_dict = {
                "text": result.text,
                "score": result.score,
                "file_path": result.metadata.get("file_path", "unknown"),
                "name": result.metadata.get("name", "unnamed"),
                "type": result.metadata.get("type", "unknown"),
                "module": result.metadata.get("module", ""),
                "collection": result.metadata.get("_collection") or result.metadata.get("collection", "N/A"),
                "_collection": result.metadata.get("_collection") or result.metadata.get("collection", "N/A")
            }
            sources.append(source_dict)

        return context, sources

    def get_file_context(
        self,
        file_path: str,
        element_types: Optional[List[str]] = None
    ) -> str:
        """
        Get all code elements from a specific file.

        Args:
            file_path: Path to file
            element_types: Optional filter by element types

        Returns:
            Formatted context for the file
        """
        filters = {"file_path": file_path}

        if element_types:
            filters["element_type"] = {"$in": element_types}

        # Use a generic query to get all elements
        results = self.retrieve(
            query="code",
            top_k=100,  # Get many results
            min_score=0.0,  # No score filtering
            filters=filters
        )

        if not results:
            return f"No code found in {file_path}"

        context = self.build_context(
            results=results,
            include_metadata=True,
            format_style="detailed"
        )

        return context

    def get_similar_code(
        self,
        code_snippet: str,
        top_k: Optional[int] = None,
        exclude_exact_match: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Find code similar to a given snippet.

        Args:
            code_snippet: Code to find similar examples for
            top_k: Number of results
            exclude_exact_match: Exclude exact matches

        Returns:
            List of similar code snippets as dictionaries
        """
        results = self.retrieve(
            query=code_snippet,
            top_k=(top_k or self.top_k) + (1 if exclude_exact_match else 0),
            min_score=self.min_score
        )

        if exclude_exact_match and results:
            # Remove exact matches (score very close to 1.0)
            results = [r for r in results if r.score < 0.999]

        # Convert SearchResult objects to dictionaries
        similar_code = []
        for result in results[:top_k or self.top_k]:
            code_dict = {
                "text": result.text,
                "score": result.score,
                "file_path": result.metadata.get("file_path", "unknown"),
                "name": result.metadata.get("name", "unnamed"),
                "type": result.metadata.get("type", "unknown"),
                "module": result.metadata.get("module", ""),
            }
            similar_code.append(code_dict)

        return similar_code


# Global retriever instance
_rag_retriever: Optional[RAGRetriever] = None


def get_rag_retriever() -> RAGRetriever:
    """Get or create the global RAG retriever instance."""
    global _rag_retriever

    if _rag_retriever is None:
        _rag_retriever = RAGRetriever()

    return _rag_retriever
