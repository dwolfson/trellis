"""
Collection-level metrics tracking for RAG system.

This module tracks detailed metrics for each collection search,
enabling per-collection performance analysis and optimization.
"""

import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from loguru import logger

from advisor.query_classifier import QueryType, QueryTopic


@dataclass
class CollectionRetrievalMetrics:
    """Metrics for a single collection search."""
    
    # Collection identification
    collection_name: str
    query_type: QueryType
    query_topics: List[QueryTopic]
    
    # Search metrics
    search_time_ms: float
    chunks_retrieved: int
    chunks_above_threshold: int
    avg_score: float
    max_score: float
    min_score: float
    score_distribution: Dict[str, int] = field(default_factory=dict)  # score_range -> count
    
    # Ranking metrics
    chunks_in_final_context: int = 0
    avg_rank_in_final: float = 0.0
    best_rank_in_final: int = 0
    
    # Quality metrics (populated later from feedback)
    relevance_score: Optional[float] = None
    hallucination_detected: bool = False
    
    # Routing metrics
    was_primary_collection: bool = False
    routing_confidence: float = 0.0
    
    # Timestamp
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/logging."""
        data = asdict(self)
        # Convert enums to strings
        data['query_type'] = self.query_type.value
        data['query_topics'] = [t.value for t in self.query_topics]
        return data
    
    def get_precision(self) -> float:
        """
        Calculate precision (chunks above threshold / chunks retrieved).
        
        Returns:
            Precision score (0-1)
        """
        if self.chunks_retrieved == 0:
            return 0.0
        return self.chunks_above_threshold / self.chunks_retrieved
    
    def get_contribution_rate(self) -> float:
        """
        Calculate contribution rate (chunks in final / chunks above threshold).
        
        Returns:
            Contribution rate (0-1)
        """
        if self.chunks_above_threshold == 0:
            return 0.0
        return self.chunks_in_final_context / self.chunks_above_threshold


class CollectionMetricsTracker:
    """Track per-collection retrieval metrics."""
    
    def __init__(self):
        """Initialize collection metrics tracker."""
        self.metrics_history: List[CollectionRetrievalMetrics] = []
        logger.info("Initialized CollectionMetricsTracker")
    
    def track_collection_search(
        self,
        collection_name: str,
        query_type: QueryType,
        query_topics: List[QueryTopic],
        results: List[Any],  # SearchResult objects
        search_time_ms: float,
        min_score_threshold: float,
        was_primary: bool = False,
        routing_confidence: float = 0.0
    ) -> CollectionRetrievalMetrics:
        """
        Track metrics for a single collection search.
        
        Args:
            collection_name: Name of the collection
            query_type: Type of query
            query_topics: Topics detected in query
            results: List of SearchResult objects
            search_time_ms: Time taken for search
            min_score_threshold: Minimum score threshold used
            was_primary: Whether this was the primary collection
            routing_confidence: Confidence in routing decision
            
        Returns:
            CollectionRetrievalMetrics instance
        """
        # Calculate score statistics
        scores = [r.score for r in results] if results else []
        
        chunks_retrieved = len(results)
        chunks_above_threshold = len([s for s in scores if s >= min_score_threshold])
        
        avg_score = sum(scores) / len(scores) if scores else 0.0
        max_score = max(scores) if scores else 0.0
        min_score = min(scores) if scores else 0.0
        
        # Calculate score distribution
        score_distribution = self._calculate_score_distribution(scores)
        
        # Create metrics object
        metrics = CollectionRetrievalMetrics(
            collection_name=collection_name,
            query_type=query_type,
            query_topics=query_topics,
            search_time_ms=search_time_ms,
            chunks_retrieved=chunks_retrieved,
            chunks_above_threshold=chunks_above_threshold,
            avg_score=avg_score,
            max_score=max_score,
            min_score=min_score,
            score_distribution=score_distribution,
            was_primary_collection=was_primary,
            routing_confidence=routing_confidence
        )
        
        # Store in history
        self.metrics_history.append(metrics)
        
        logger.debug(
            f"Tracked {collection_name}: {chunks_retrieved} chunks, "
            f"avg_score={avg_score:.3f}, search_time={search_time_ms:.1f}ms"
        )
        
        return metrics
    
    def update_final_context_metrics(
        self,
        collection_name: str,
        chunks_in_final: int,
        ranks_in_final: List[int]
    ):
        """
        Update metrics with final context information.
        
        Args:
            collection_name: Name of the collection
            chunks_in_final: Number of chunks from this collection in final context
            ranks_in_final: List of ranks (positions) in final context
        """
        # Find most recent metrics for this collection
        for metrics in reversed(self.metrics_history):
            if metrics.collection_name == collection_name:
                metrics.chunks_in_final_context = chunks_in_final
                
                if ranks_in_final:
                    metrics.avg_rank_in_final = sum(ranks_in_final) / len(ranks_in_final)
                    metrics.best_rank_in_final = min(ranks_in_final)
                
                logger.debug(
                    f"Updated {collection_name}: {chunks_in_final} chunks in final, "
                    f"avg_rank={metrics.avg_rank_in_final:.1f}"
                )
                break
    
    def update_quality_metrics(
        self,
        collection_name: str,
        relevance_score: Optional[float] = None,
        hallucination_detected: bool = False
    ):
        """
        Update metrics with quality information from feedback.
        
        Args:
            collection_name: Name of the collection
            relevance_score: Relevance score from user feedback (0-1)
            hallucination_detected: Whether hallucination was detected
        """
        # Find most recent metrics for this collection
        for metrics in reversed(self.metrics_history):
            if metrics.collection_name == collection_name:
                if relevance_score is not None:
                    metrics.relevance_score = relevance_score
                metrics.hallucination_detected = hallucination_detected
                
                logger.debug(
                    f"Updated quality for {collection_name}: "
                    f"relevance={relevance_score}, hallucination={hallucination_detected}"
                )
                break
    
    def _calculate_score_distribution(self, scores: List[float]) -> Dict[str, int]:
        """
        Calculate score distribution in ranges.
        
        Args:
            scores: List of similarity scores
            
        Returns:
            Dict mapping score ranges to counts
        """
        distribution = {
            "0.9-1.0": 0,
            "0.8-0.9": 0,
            "0.7-0.8": 0,
            "0.6-0.7": 0,
            "0.5-0.6": 0,
            "0.4-0.5": 0,
            "0.3-0.4": 0,
            "0.0-0.3": 0,
        }
        
        for score in scores:
            if score >= 0.9:
                distribution["0.9-1.0"] += 1
            elif score >= 0.8:
                distribution["0.8-0.9"] += 1
            elif score >= 0.7:
                distribution["0.7-0.8"] += 1
            elif score >= 0.6:
                distribution["0.6-0.7"] += 1
            elif score >= 0.5:
                distribution["0.5-0.6"] += 1
            elif score >= 0.4:
                distribution["0.4-0.5"] += 1
            elif score >= 0.3:
                distribution["0.3-0.4"] += 1
            else:
                distribution["0.0-0.3"] += 1
        
        return distribution
    
    def get_collection_summary(
        self,
        collection_name: str,
        time_window_hours: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a collection.
        
        Args:
            collection_name: Name of the collection
            time_window_hours: Optional time window in hours
            
        Returns:
            Dict with summary statistics
        """
        # Filter metrics
        metrics_list = [
            m for m in self.metrics_history
            if m.collection_name == collection_name
        ]
        
        # Apply time window if specified
        if time_window_hours:
            cutoff = time.time() - (time_window_hours * 3600)
            metrics_list = [m for m in metrics_list if m.timestamp >= cutoff]
        
        if not metrics_list:
            return {
                "collection_name": collection_name,
                "total_searches": 0,
                "error": "No data available"
            }
        
        # Calculate statistics
        total_searches = len(metrics_list)
        avg_search_time = sum(m.search_time_ms for m in metrics_list) / total_searches
        avg_chunks_retrieved = sum(m.chunks_retrieved for m in metrics_list) / total_searches
        avg_chunks_above_threshold = sum(m.chunks_above_threshold for m in metrics_list) / total_searches
        avg_score = sum(m.avg_score for m in metrics_list) / total_searches
        avg_precision = sum(m.get_precision() for m in metrics_list) / total_searches
        
        # Quality metrics (if available)
        metrics_with_relevance = [m for m in metrics_list if m.relevance_score is not None]
        avg_relevance = None
        if metrics_with_relevance:
            # Type assertion: we know relevance_score is not None here
            relevance_scores = [m.relevance_score for m in metrics_with_relevance if m.relevance_score is not None]
            avg_relevance = sum(relevance_scores) / len(relevance_scores) if relevance_scores else None
        
        hallucination_rate = (
            sum(1 for m in metrics_list if m.hallucination_detected) / total_searches
            if total_searches > 0 else 0.0
        )
        
        # Primary collection rate
        primary_rate = (
            sum(1 for m in metrics_list if m.was_primary_collection) / total_searches
            if total_searches > 0 else 0.0
        )
        
        return {
            "collection_name": collection_name,
            "total_searches": total_searches,
            "avg_search_time_ms": avg_search_time,
            "avg_chunks_retrieved": avg_chunks_retrieved,
            "avg_chunks_above_threshold": avg_chunks_above_threshold,
            "avg_score": avg_score,
            "avg_precision": avg_precision,
            "avg_relevance_score": avg_relevance,
            "hallucination_rate": hallucination_rate,
            "primary_collection_rate": primary_rate,
        }
    
    def get_query_type_summary(
        self,
        query_type: QueryType,
        time_window_hours: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get summary statistics for a query type across all collections.
        
        Args:
            query_type: Type of query
            time_window_hours: Optional time window in hours
            
        Returns:
            Dict with summary statistics
        """
        # Filter metrics
        metrics_list = [
            m for m in self.metrics_history
            if m.query_type == query_type
        ]
        
        # Apply time window if specified
        if time_window_hours:
            cutoff = time.time() - (time_window_hours * 3600)
            metrics_list = [m for m in metrics_list if m.timestamp >= cutoff]
        
        if not metrics_list:
            return {
                "query_type": query_type.value,
                "total_searches": 0,
                "error": "No data available"
            }
        
        # Calculate statistics
        total_searches = len(metrics_list)
        avg_search_time = sum(m.search_time_ms for m in metrics_list) / total_searches
        avg_score = sum(m.avg_score for m in metrics_list) / total_searches
        
        # Collection distribution
        collection_counts = {}
        for m in metrics_list:
            collection_counts[m.collection_name] = collection_counts.get(m.collection_name, 0) + 1
        
        # Quality metrics
        hallucination_rate = (
            sum(1 for m in metrics_list if m.hallucination_detected) / total_searches
            if total_searches > 0 else 0.0
        )
        
        return {
            "query_type": query_type.value,
            "total_searches": total_searches,
            "avg_search_time_ms": avg_search_time,
            "avg_score": avg_score,
            "hallucination_rate": hallucination_rate,
            "collection_distribution": collection_counts,
        }
    
    def get_all_collections_summary(
        self,
        time_window_hours: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get summary for all collections.
        
        Args:
            time_window_hours: Optional time window in hours
            
        Returns:
            List of collection summaries
        """
        # Get unique collection names
        collection_names = set(m.collection_name for m in self.metrics_history)
        
        # Get summary for each collection
        summaries = []
        for collection_name in sorted(collection_names):
            summary = self.get_collection_summary(collection_name, time_window_hours)
            summaries.append(summary)
        
        return summaries
    
    def clear_history(self, older_than_hours: Optional[int] = None):
        """
        Clear metrics history.
        
        Args:
            older_than_hours: If specified, only clear metrics older than this
        """
        if older_than_hours:
            cutoff = time.time() - (older_than_hours * 3600)
            self.metrics_history = [
                m for m in self.metrics_history
                if m.timestamp >= cutoff
            ]
            logger.info(f"Cleared metrics older than {older_than_hours} hours")
        else:
            self.metrics_history.clear()
            logger.info("Cleared all metrics history")


# Global tracker instance
_tracker_instance: Optional[CollectionMetricsTracker] = None


def get_collection_metrics_tracker() -> CollectionMetricsTracker:
    """Get singleton collection metrics tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = CollectionMetricsTracker()
    return _tracker_instance