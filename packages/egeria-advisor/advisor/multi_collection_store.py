"""
Multi-collection vector store operations for intelligent query routing.

This module extends VectorStoreManager to support searching across multiple
collections with result merging and re-ranking.
"""

from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, field
from concurrent.futures import ThreadPoolExecutor, as_completed
from loguru import logger
import math

from advisor.vector_store import VectorStoreManager, SearchResult, get_vector_store
from advisor.collection_router import get_collection_router
from advisor.collection_config import get_collection, get_enabled_collections


@dataclass
class MultiCollectionSearchResult:
    """Result from searching multiple collections."""
    results: List[SearchResult]
    collection_scores: Dict[str, float] = field(default_factory=dict)
    total_searched: int = 0
    collections_searched: List[str] = field(default_factory=list)
    routing_strategy: str = "default"
    #: collection_name -> str(exception) for any collection whose search
    #: raised (connection failure, etc.). Previously the per-collection
    #: try/except below swallowed these into a plain empty result list,
    #: which is exactly how "the store was unreachable" came to look
    #: identical to "the corpus has nothing" downstream in
    #: RAGRetriever.build_context() — see advisor/retrieval_outcome.py.
    errors: Dict[str, str] = field(default_factory=dict)


class MultiCollectionStore:
    """
    Manages searches across multiple collections.
    
    Provides intelligent routing, result merging, and re-ranking
    for multi-collection queries.
    """
    
    def __init__(self, vector_store: Optional[VectorStoreManager] = None):
        """
        Initialize multi-collection store.
        
        Args:
            vector_store: Optional VectorStoreManager instance
        """
        self.vector_store = vector_store or get_vector_store()
        self.router = get_collection_router()
        logger.info("Initialized MultiCollectionStore")
    
    def search_with_routing(
        self,
        query: str,
        top_k: Optional[int] = None,
        max_collections: int = 3,
        min_score: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None,
        intent: Optional[str] = None,
        boosted_collections: Optional[List[str]] = None,
        feedback_adjustments: Optional[Dict[str, float]] = None
    ) -> MultiCollectionSearchResult:
        """
        Search with intelligent collection routing.
        
        Args:
            query: Query text
            top_k: Number of results per collection (uses collection default if None)
            max_collections: Maximum collections to search
            min_score: Minimum similarity score threshold (uses collection default if None)
            filters: Optional metadata filters
            intent: Optional query intent
            boosted_collections: Collections to boost
            feedback_adjustments: Feedback loop adjustments
            
        Returns:
            MultiCollectionSearchResult with merged results
        """
        # Route query to collections
        collection_names = self.router.route_query(
            query,
            max_collections=max_collections,
            intent=intent,
            boosted_collections=boosted_collections,
            feedback_adjustments=feedback_adjustments
        )
        
        if not collection_names:
            logger.warning("No collections matched query, using defaults")
            collection_names = [c.name for c in get_enabled_collections()[:max_collections]]
        
        logger.info(f"Routing query to collections: {collection_names}")
        
        # Search collections in parallel for better performance
        all_results: List[Tuple[str, SearchResult]] = []  # (collection_name, result)
        collection_scores: Dict[str, float] = {}
        collection_errors: Dict[str, str] = {}

        def search_collection(collection_name: str) -> Tuple[str, List[SearchResult]]:
            """Search a single collection (for parallel execution)."""
            try:
                # Get collection-specific parameters
                collection_meta = get_collection(collection_name)
                collection_top_k = top_k if top_k is not None else (collection_meta.default_top_k if collection_meta else 5)
                collection_min_score = min_score if min_score is not None else (collection_meta.min_score if collection_meta else 0.0)

                logger.debug(f"Searching {collection_name} with top_k={collection_top_k}, min_score={collection_min_score}")

                results = self.vector_store.search(
                    collection_name=collection_name,
                    query_text=query,
                    top_k=collection_top_k,
                    filters=filters
                )

                # Filter by collection-specific min_score
                filtered_results = [r for r in results if r.score >= collection_min_score]
                return (collection_name, filtered_results)
            except Exception as e:
                logger.error(f"Error searching collection {collection_name}: {e}")
                # Recorded (not just logged) so a caller can distinguish "this
                # collection genuinely has nothing" from "this collection could
                # not be searched at all" — see MultiCollectionSearchResult.errors.
                collection_errors[collection_name] = str(e)
                return (collection_name, [])

        # Execute searches in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(len(collection_names), 4)) as executor:
            # Submit all search tasks
            future_to_collection = {
                executor.submit(search_collection, name): name
                for name in collection_names
            }

            # Collect results as they complete
            for future in as_completed(future_to_collection):
                collection_name, results = future.result()

                # Track results per collection (already filtered by collection-specific min_score)
                for result in results:
                    all_results.append((collection_name, result))

                # Calculate average score for this collection
                if results:
                    avg_score = sum(r.score for r in results) / len(results)
                    collection_scores[collection_name] = avg_score
                    logger.debug(f"Collection {collection_name}: {len(results)} results, avg score: {avg_score:.3f}")

        # Merge and re-rank results
        merged_results = self._merge_and_rerank(
            all_results,
            collection_scores,
            top_k=top_k or 5  # Use default if None
        )

        return MultiCollectionSearchResult(
            results=merged_results,
            errors=collection_errors,
            collection_scores=collection_scores,
            total_searched=len(all_results),
            collections_searched=collection_names
        )
    
    def search_specific_collections(
        self,
        query: str,
        collection_names: List[str],
        top_k: Optional[int] = None,
        min_score: Optional[float] = None,
        filters: Optional[Dict[str, Any]] = None
    ) -> MultiCollectionSearchResult:
        """
        Search specific collections (no routing).
        
        Args:
            query: Query text
            collection_names: List of collection names to search
            top_k: Number of results per collection (uses collection default if None)
            min_score: Minimum similarity score threshold (uses collection default if None)
            filters: Optional metadata filters
            
        Returns:
            MultiCollectionSearchResult with merged results
        """
        logger.info(f"Searching specific collections: {collection_names}")
        
        all_results: List[Tuple[str, SearchResult]] = []
        collection_scores: Dict[str, float] = {}
        collection_errors: Dict[str, str] = {}

        for collection_name in collection_names:
            try:
                # Get collection-specific parameters
                collection_meta = get_collection(collection_name)
                collection_top_k = top_k if top_k is not None else (collection_meta.default_top_k if collection_meta else 5)
                collection_min_score = min_score if min_score is not None else (collection_meta.min_score if collection_meta else 0.0)
                
                logger.debug(f"Searching {collection_name} with top_k={collection_top_k}, min_score={collection_min_score}")
                
                results = self.vector_store.search(
                    collection_name=collection_name,
                    query_text=query,
                    top_k=collection_top_k,
                    filters=filters
                )
                
                # Filter by collection-specific min_score
                for result in results:
                    if result.score >= collection_min_score:
                        all_results.append((collection_name, result))
                
                if results:
                    avg_score = sum(r.score for r in results) / len(results)
                    collection_scores[collection_name] = avg_score
                
            except Exception as e:
                logger.error(f"Error searching collection {collection_name}: {e}")
                collection_errors[collection_name] = str(e)
                continue

        merged_results = self._merge_and_rerank(
            all_results,
            collection_scores,
            top_k=top_k or 5  # Use default if None
        )
        
        return MultiCollectionSearchResult(
            results=merged_results,
            errors=collection_errors,
            collection_scores=collection_scores,
            total_searched=len(all_results),
            collections_searched=collection_names
        )

    def _merge_and_rerank(
        self,
        all_results: List[Tuple[str, SearchResult]],
        collection_scores: Dict[str, float],
        top_k: int = 5
    ) -> List[SearchResult]:
        """
        Merge results from multiple collections and re-rank.
        
        Uses a combination of:
        1. Individual result score
        2. Collection average score (collection quality)
        3. Collection priority from metadata
        
        Args:
            all_results: List of (collection_name, SearchResult) tuples
            collection_scores: Average scores per collection
            top_k: Number of results to return
            
        Returns:
            List of re-ranked SearchResult objects
        """
        if not all_results:
            return []
        
        # Calculate combined scores with file type boosting
        scored_results: List[Tuple[float, SearchResult, str]] = []
        
        for collection_name, result in all_results:
            # Get collection metadata
            collection_meta = get_collection(collection_name)
            collection_priority = collection_meta.priority if collection_meta else 1
            
            # Normalize priority to 0-1 range (assuming max priority is 10)
            priority_weight = collection_priority / 10.0
            
            # Get collection average score
            collection_avg = collection_scores.get(collection_name, 0.5)
            
            # File type boosting for code quality
            file_path = result.metadata.get("file_path", "")
            file_boost = 1.0
            
            # Boost test files significantly (best working examples)
            if "/test" in file_path.lower() or file_path.endswith("_test.py"):
                file_boost = 1.3
            # Boost Python code files
            elif file_path.endswith(".py"):
                file_boost = 1.15
            # Penalize markdown documentation (unless it's the only option)
            elif file_path.endswith(".md"):
                file_boost = 0.85
            
            # Combined score: 60% result score, 25% collection quality, 15% priority
            # Then apply file type boost
            combined_score = (
                0.60 * result.score +
                0.25 * collection_avg +
                0.15 * priority_weight
            ) * file_boost
            
            scored_results.append((combined_score, result, collection_name))
        
        # Sort by combined score (descending)
        scored_results.sort(key=lambda x: x[0], reverse=True)
        
        # Take top-k and add collection info to metadata
        final_results = []
        for combined_score, result, collection_name in scored_results[:top_k]:
            # Add collection info to metadata
            result.metadata["_collection"] = collection_name
            result.metadata["_combined_score"] = combined_score
            final_results.append(result)
        
        logger.debug(f"Merged {len(all_results)} results into top {len(final_results)}")
        
        return final_results
    
    def search_with_fallback(
        self,
        query: str,
        top_k: int = 5,
        min_results: int = 3,
        max_collections: int = 5,
        min_score: float = 0.0,
        filters: Optional[Dict[str, Any]] = None
    ) -> MultiCollectionSearchResult:
        """
        Search with fallback to related collections if insufficient results.
        
        Args:
            query: Query text
            top_k: Number of results per collection
            min_results: Minimum results before expanding search
            max_collections: Maximum total collections to search
            min_score: Minimum similarity score threshold
            filters: Optional metadata filters
            
        Returns:
            MultiCollectionSearchResult with merged results
        """
        # Get routing strategy with fallback
        routing = self.router.route_with_fallback(
            query,
            min_results_threshold=min_results,
            max_collections=max_collections
        )
        
        # Search primary collections first
        result = self.search_specific_collections(
            query,
            routing["primary"],
            top_k=top_k,
            min_score=min_score,
            filters=filters
        )
        
        # Check if we need to expand search
        if len(result.results) < min_results and routing["fallback"]:
            logger.info(f"Expanding search to fallback collections: {routing['fallback']}")
            
            # Search fallback collections
            fallback_result = self.search_specific_collections(
                query,
                routing["fallback"],
                top_k=top_k,
                min_score=min_score,
                filters=filters
            )
            
            # Merge results
            all_results = [
                (r.metadata.get("_collection", "unknown"), r)
                for r in result.results + fallback_result.results
            ]
            
            # Re-rank combined results
            merged = self._merge_and_rerank(
                all_results,
                {**result.collection_scores, **fallback_result.collection_scores},
                top_k=top_k
            )
            
            return MultiCollectionSearchResult(
                results=merged,
                collection_scores={**result.collection_scores, **fallback_result.collection_scores},
                total_searched=result.total_searched + fallback_result.total_searched,
                collections_searched=result.collections_searched + fallback_result.collections_searched
            )
        
        return result


# Singleton instance
_multi_store_instance: Optional[MultiCollectionStore] = None


def get_multi_collection_store() -> MultiCollectionStore:
    """Get singleton multi-collection store instance."""
    global _multi_store_instance
    if _multi_store_instance is None:
        _multi_store_instance = MultiCollectionStore()
    return _multi_store_instance