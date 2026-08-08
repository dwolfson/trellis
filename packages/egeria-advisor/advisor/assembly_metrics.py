"""
Document assembly metrics tracking for RAG system.

This module tracks how chunks from multiple collections are combined
into the final context sent to the LLM.
"""

import time
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
from collections import Counter
from loguru import logger

from advisor.query_classifier import QueryType, QueryTopic


@dataclass
class DocumentAssemblyMetrics:
    """Metrics for document assembly from multiple collections."""
    
    # Query identification
    query_type: QueryType
    query_topics: List[QueryTopic]
    
    # Collection distribution
    collections_searched: List[str]
    collections_contributed: Dict[str, int] = field(default_factory=dict)  # collection -> chunk count
    
    # Re-ranking metrics
    reranking_time_ms: float = 0.0
    file_type_boosts_applied: Dict[str, float] = field(default_factory=dict)  # file_type -> avg boost
    
    # Context building
    total_chunks_retrieved: int = 0
    total_chunks_used: int = 0
    context_length_chars: int = 0
    context_truncated: bool = False
    
    # Cross-collection metrics
    chunk_diversity_score: float = 0.0  # How diverse are sources?
    collection_overlap_score: float = 0.0  # How much overlap between collections?
    
    # File type distribution
    file_type_distribution: Dict[str, int] = field(default_factory=dict)  # file_type -> count
    
    # Timestamp
    timestamp: float = field(default_factory=time.time)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage/logging."""
        data = asdict(self)
        # Convert enums to strings
        data['query_type'] = self.query_type.value
        data['query_topics'] = [t.value for t in self.query_topics]
        return data
    
    def get_utilization_rate(self) -> float:
        """
        Calculate utilization rate (chunks used / chunks retrieved).
        
        Returns:
            Utilization rate (0-1)
        """
        if self.total_chunks_retrieved == 0:
            return 0.0
        return self.total_chunks_used / self.total_chunks_retrieved
    
    def get_primary_collection(self) -> Optional[str]:
        """
        Get the collection that contributed most chunks.
        
        Returns:
            Collection name or None
        """
        if not self.collections_contributed:
            return None
        return max(self.collections_contributed.items(), key=lambda x: x[1])[0]


class AssemblyMetricsTracker:
    """Track document assembly metrics."""
    
    def __init__(self):
        """Initialize assembly metrics tracker."""
        self.metrics_history: List[DocumentAssemblyMetrics] = []
        logger.info("Initialized AssemblyMetricsTracker")
    
    def track_assembly(
        self,
        query_type: QueryType,
        query_topics: List[QueryTopic],
        collections_searched: List[str],
        collection_results: Dict[str, List[Any]],  # collection -> SearchResult list
        final_results: List[Any],  # Final merged SearchResult list
        reranking_time_ms: float,
        context_length_chars: int,
        max_context_length: int
    ) -> DocumentAssemblyMetrics:
        """
        Track metrics for document assembly.
        
        Args:
            query_type: Type of query
            query_topics: Topics detected in query
            collections_searched: List of collections searched
            collection_results: Dict mapping collection names to their results
            final_results: Final merged and re-ranked results
            reranking_time_ms: Time taken for re-ranking
            context_length_chars: Length of final context
            max_context_length: Maximum allowed context length
            
        Returns:
            DocumentAssemblyMetrics instance
        """
        # Calculate total chunks retrieved
        total_chunks_retrieved = sum(len(results) for results in collection_results.values())
        total_chunks_used = len(final_results)
        
        # Calculate collection contributions
        collections_contributed = self._calculate_collection_contributions(
            final_results,
            collection_results
        )
        
        # Calculate file type boosts
        file_type_boosts = self._calculate_file_type_boosts(final_results)
        
        # Calculate file type distribution
        file_type_distribution = self._calculate_file_type_distribution(final_results)
        
        # Calculate diversity score
        chunk_diversity_score = self._calculate_diversity_score(
            final_results,
            collections_contributed
        )
        
        # Calculate overlap score
        collection_overlap_score = self._calculate_overlap_score(collection_results)
        
        # Check if context was truncated
        context_truncated = context_length_chars >= max_context_length
        
        # Create metrics object
        metrics = DocumentAssemblyMetrics(
            query_type=query_type,
            query_topics=query_topics,
            collections_searched=collections_searched,
            collections_contributed=collections_contributed,
            reranking_time_ms=reranking_time_ms,
            file_type_boosts_applied=file_type_boosts,
            total_chunks_retrieved=total_chunks_retrieved,
            total_chunks_used=total_chunks_used,
            context_length_chars=context_length_chars,
            context_truncated=context_truncated,
            chunk_diversity_score=chunk_diversity_score,
            collection_overlap_score=collection_overlap_score,
            file_type_distribution=file_type_distribution
        )
        
        # Store in history
        self.metrics_history.append(metrics)
        
        logger.debug(
            f"Tracked assembly: {total_chunks_retrieved} retrieved, "
            f"{total_chunks_used} used, diversity={chunk_diversity_score:.2f}"
        )
        
        return metrics
    
    def _calculate_collection_contributions(
        self,
        final_results: List[Any],
        collection_results: Dict[str, List[Any]]
    ) -> Dict[str, int]:
        """
        Calculate how many chunks each collection contributed to final context.
        
        Args:
            final_results: Final merged results
            collection_results: Original results per collection
            
        Returns:
            Dict mapping collection names to chunk counts
        """
        contributions: Dict[str, int] = {}
        
        # Create a mapping of result IDs to collections
        result_to_collection: Dict[int, str] = {}
        for collection_name, results in collection_results.items():
            for result in results:
                result_id = id(result)
                result_to_collection[result_id] = collection_name
        
        # Count contributions in final results
        for result in final_results:
            result_id = id(result)
            collection_name = result_to_collection.get(result_id)
            if collection_name:
                contributions[collection_name] = contributions.get(collection_name, 0) + 1
            else:
                # Try to match by file_path and text (for re-created objects)
                file_path = result.metadata.get('file_path', '')
                text = result.text
                
                for collection_name, results in collection_results.items():
                    for orig_result in results:
                        if (orig_result.metadata.get('file_path', '') == file_path and
                            orig_result.text == text):
                            contributions[collection_name] = contributions.get(collection_name, 0) + 1
                            break
        
        return contributions
    
    def _calculate_file_type_boosts(
        self,
        final_results: List[Any]
    ) -> Dict[str, float]:
        """
        Calculate average file type boosts applied.
        
        Args:
            final_results: Final merged results
            
        Returns:
            Dict mapping file types to average boosts
        """
        file_type_boosts: Dict[str, List[float]] = {}
        
        for result in final_results:
            file_path = result.metadata.get('file_path', '')
            
            # Determine file type
            if '/test' in file_path.lower():
                file_type = 'test'
                boost = 1.3
            elif file_path.endswith('.py'):
                file_type = 'code'
                boost = 1.15
            elif file_path.endswith('.md'):
                file_type = 'markdown'
                boost = 0.85
            else:
                file_type = 'other'
                boost = 1.0
            
            if file_type not in file_type_boosts:
                file_type_boosts[file_type] = []
            file_type_boosts[file_type].append(boost)
        
        # Calculate averages
        avg_boosts = {
            file_type: sum(boosts) / len(boosts)
            for file_type, boosts in file_type_boosts.items()
        }
        
        return avg_boosts
    
    def _calculate_file_type_distribution(
        self,
        final_results: List[Any]
    ) -> Dict[str, int]:
        """
        Calculate distribution of file types in final results.
        
        Args:
            final_results: Final merged results
            
        Returns:
            Dict mapping file types to counts
        """
        file_types = []
        
        for result in final_results:
            file_path = result.metadata.get('file_path', '')
            
            # Determine file type
            if '/test' in file_path.lower():
                file_types.append('test')
            elif file_path.endswith('.py'):
                file_types.append('python')
            elif file_path.endswith('.java'):
                file_types.append('java')
            elif file_path.endswith('.md'):
                file_types.append('markdown')
            elif file_path.endswith('.yaml') or file_path.endswith('.yml'):
                file_types.append('yaml')
            elif file_path.endswith('.json'):
                file_types.append('json')
            else:
                file_types.append('other')
        
        return dict(Counter(file_types))
    
    def _calculate_diversity_score(
        self,
        final_results: List[Any],
        collections_contributed: Dict[str, int]
    ) -> float:
        """
        Calculate diversity score based on source variety.
        
        Higher score means more diverse sources (files, collections).
        
        Args:
            final_results: Final merged results
            collections_contributed: Collection contributions
            
        Returns:
            Diversity score (0-1)
        """
        if not final_results:
            return 0.0
        
        # Count unique files
        unique_files = set(
            result.metadata.get('file_path', '')
            for result in final_results
        )
        
        # Count collections that contributed
        num_collections = len(collections_contributed)
        
        # Calculate diversity components
        file_diversity = min(1.0, len(unique_files) / len(final_results))
        collection_diversity = min(1.0, num_collections / 3.0)  # Assume max 3 collections is ideal
        
        # Weighted average
        diversity_score = (file_diversity * 0.6) + (collection_diversity * 0.4)
        
        return diversity_score
    
    def _calculate_overlap_score(
        self,
        collection_results: Dict[str, List[Any]]
    ) -> float:
        """
        Calculate overlap score between collections.
        
        Higher score means more overlap (same files/content in multiple collections).
        
        Args:
            collection_results: Results per collection
            
        Returns:
            Overlap score (0-1)
        """
        if len(collection_results) < 2:
            return 0.0
        
        # Get file paths from each collection
        collection_files: Dict[str, set] = {}
        for collection_name, results in collection_results.items():
            files = set(
                result.metadata.get('file_path', '')
                for result in results
            )
            collection_files[collection_name] = files
        
        # Calculate pairwise overlaps
        overlaps = []
        collection_names = list(collection_files.keys())
        
        for i in range(len(collection_names)):
            for j in range(i + 1, len(collection_names)):
                files_i = collection_files[collection_names[i]]
                files_j = collection_files[collection_names[j]]
                
                if not files_i or not files_j:
                    continue
                
                intersection = len(files_i & files_j)
                union = len(files_i | files_j)
                
                if union > 0:
                    overlap = intersection / union
                    overlaps.append(overlap)
        
        # Return average overlap
        return sum(overlaps) / len(overlaps) if overlaps else 0.0
    
    def get_summary(
        self,
        query_type: Optional[QueryType] = None,
        time_window_hours: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Get summary statistics for assembly metrics.
        
        Args:
            query_type: Optional filter by query type
            time_window_hours: Optional time window in hours
            
        Returns:
            Dict with summary statistics
        """
        # Filter metrics
        metrics_list = self.metrics_history
        
        if query_type:
            metrics_list = [m for m in metrics_list if m.query_type == query_type]
        
        if time_window_hours:
            cutoff = time.time() - (time_window_hours * 3600)
            metrics_list = [m for m in metrics_list if m.timestamp >= cutoff]
        
        if not metrics_list:
            return {
                "total_assemblies": 0,
                "error": "No data available"
            }
        
        # Calculate statistics
        total_assemblies = len(metrics_list)
        avg_reranking_time = sum(m.reranking_time_ms for m in metrics_list) / total_assemblies
        avg_chunks_retrieved = sum(m.total_chunks_retrieved for m in metrics_list) / total_assemblies
        avg_chunks_used = sum(m.total_chunks_used for m in metrics_list) / total_assemblies
        avg_utilization = sum(m.get_utilization_rate() for m in metrics_list) / total_assemblies
        avg_diversity = sum(m.chunk_diversity_score for m in metrics_list) / total_assemblies
        avg_overlap = sum(m.collection_overlap_score for m in metrics_list) / total_assemblies
        truncation_rate = sum(1 for m in metrics_list if m.context_truncated) / total_assemblies
        
        # Collection usage
        all_collections = set()
        for m in metrics_list:
            all_collections.update(m.collections_searched)
        
        return {
            "total_assemblies": total_assemblies,
            "avg_reranking_time_ms": avg_reranking_time,
            "avg_chunks_retrieved": avg_chunks_retrieved,
            "avg_chunks_used": avg_chunks_used,
            "avg_utilization_rate": avg_utilization,
            "avg_diversity_score": avg_diversity,
            "avg_overlap_score": avg_overlap,
            "truncation_rate": truncation_rate,
            "collections_used": sorted(all_collections),
        }
    
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
            logger.info(f"Cleared assembly metrics older than {older_than_hours} hours")
        else:
            self.metrics_history.clear()
            logger.info("Cleared all assembly metrics history")


# Global tracker instance
_tracker_instance: Optional[AssemblyMetricsTracker] = None


def get_assembly_metrics_tracker() -> AssemblyMetricsTracker:
    """Get singleton assembly metrics tracker instance."""
    global _tracker_instance
    if _tracker_instance is None:
        _tracker_instance = AssemblyMetricsTracker()
    return _tracker_instance