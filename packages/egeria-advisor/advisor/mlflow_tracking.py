"""
MLflow tracking integration for Egeria Advisor.

This module provides utilities for tracking experiments, metrics, and artifacts
using MLflow for observability and performance monitoring.
"""

import mlflow
from mlflow.tracking import MlflowClient
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from loguru import logger
from contextlib import contextmanager
import time
import psutil
import os
import json
import uuid

from advisor.config import settings

if TYPE_CHECKING:
    from advisor.query_classifier import QueryClassification
    from advisor.collection_metrics import CollectionRetrievalMetrics
    from advisor.assembly_metrics import DocumentAssemblyMetrics


class ResourceMonitor:
    """Monitor system resource consumption."""
    
    def __init__(self):
        """Initialize resource monitor."""
        self.process = psutil.Process(os.getpid())
        self.start_cpu_percent = None
        self.start_memory_mb = None
        self.start_time = None
        
    def start(self):
        """Start monitoring resources."""
        self.start_time = time.time()
        self.start_cpu_percent = self.process.cpu_percent()
        self.start_memory_mb = self.process.memory_info().rss / 1024 / 1024
        
    def get_metrics(self) -> Dict[str, float]:
        """
        Get resource consumption metrics.
        
        Returns:
            Dictionary with resource metrics
        """
        if self.start_time is None:
            return {}
        
        duration = time.time() - self.start_time
        current_cpu = self.process.cpu_percent()
        current_memory_mb = self.process.memory_info().rss / 1024 / 1024
        
        metrics = {
            "resource_duration_seconds": duration,
            "resource_cpu_percent": current_cpu,
            "resource_memory_mb": current_memory_mb,
            "resource_memory_delta_mb": current_memory_mb - self.start_memory_mb,
        }
        
        # Try to get GPU metrics if available
        try:
            import torch
            if torch.cuda.is_available():
                metrics["resource_gpu_memory_allocated_mb"] = torch.cuda.memory_allocated() / 1024 / 1024
                metrics["resource_gpu_memory_reserved_mb"] = torch.cuda.memory_reserved() / 1024 / 1024
                metrics["resource_gpu_utilization_percent"] = torch.cuda.utilization()
        except (ImportError, Exception):
            pass
        
        return metrics


class AccuracyTracker:
    """Track query accuracy metrics."""
    
    def __init__(self):
        """Initialize accuracy tracker."""
        self.feedback_scores: List[float] = []
        self.relevance_scores: List[float] = []
        self.confidence_scores: List[float] = []
        
    def add_feedback(self, score: float):
        """
        Add user feedback score.
        
        Args:
            score: Feedback score (0-1 or 1-5 scale)
        """
        # Normalize to 0-1 scale
        normalized = score / 5.0 if score > 1.0 else score
        self.feedback_scores.append(normalized)
        
    def add_relevance(self, score: float):
        """
        Add relevance score.
        
        Args:
            score: Relevance score (0-1)
        """
        self.relevance_scores.append(score)
        
    def add_confidence(self, score: float):
        """
        Add confidence score.
        
        Args:
            score: Confidence score (0-1)
        """
        self.confidence_scores.append(score)
        
    def get_metrics(self) -> Dict[str, float]:
        """
        Get accuracy metrics.
        
        Returns:
            Dictionary with accuracy metrics
        """
        metrics = {}
        
        if self.feedback_scores:
            metrics["accuracy_feedback_avg"] = sum(self.feedback_scores) / len(self.feedback_scores)
            metrics["accuracy_feedback_count"] = float(len(self.feedback_scores))
            
        if self.relevance_scores:
            metrics["accuracy_relevance_avg"] = sum(self.relevance_scores) / len(self.relevance_scores)
            metrics["accuracy_relevance_count"] = float(len(self.relevance_scores))
            
        if self.confidence_scores:
            metrics["accuracy_confidence_avg"] = sum(self.confidence_scores) / len(self.confidence_scores)
            metrics["accuracy_confidence_count"] = float(len(self.confidence_scores))
            
        return metrics


class MLflowTracker:
    """MLflow tracking wrapper for Egeria Advisor with resource and accuracy monitoring."""
    
    def __init__(
        self,
        tracking_uri: Optional[str] = None,
        experiment_name: Optional[str] = None,
        enable_resource_monitoring: bool = True,
        enable_accuracy_tracking: bool = True
    ):
        """
        Initialize MLflow tracker.
        
        Args:
            tracking_uri: MLflow tracking server URI
            experiment_name: Name of the experiment
            enable_resource_monitoring: Enable CPU/memory/GPU monitoring
            enable_accuracy_tracking: Enable accuracy metrics tracking
        """
        self.tracking_uri = tracking_uri or settings.mlflow_tracking_uri
        self.experiment_name = experiment_name or settings.mlflow_experiment_name
        self.enabled = settings.mlflow_enable_tracking
        self.enable_resource_monitoring = enable_resource_monitoring
        self.enable_accuracy_tracking = enable_accuracy_tracking
        
        # Initialize monitors
        self.resource_monitor = ResourceMonitor() if enable_resource_monitoring else None
        self.accuracy_tracker = AccuracyTracker() if enable_accuracy_tracking else None
        
        if not self.enabled:
            logger.info("MLflow tracking is disabled")
            return
        
        # Set tracking URI
        mlflow.set_tracking_uri(self.tracking_uri)
        logger.info(f"MLflow tracking URI: {self.tracking_uri}")
        
        # Set or create experiment
        try:
            experiment = mlflow.get_experiment_by_name(self.experiment_name)
            if experiment is None:
                experiment_id = mlflow.create_experiment(self.experiment_name)
                logger.info(f"Created MLflow experiment: {self.experiment_name} (ID: {experiment_id})")
            else:
                experiment_id = experiment.experiment_id
                logger.info(f"Using existing MLflow experiment: {self.experiment_name} (ID: {experiment_id})")
            
            mlflow.set_experiment(self.experiment_name)
            
        except Exception as e:
            logger.warning(f"Failed to set up MLflow experiment: {e}")
            self.enabled = False
    
    @contextmanager
    def start_run(self, run_name: Optional[str] = None, tags: Optional[Dict[str, str]] = None, nested: bool = True):
        """
        Context manager for MLflow runs.
        
        Args:
            run_name: Name for the run
            tags: Tags to add to the run
            nested: Whether to allow nested runs
            
        Yields:
            MLflow run object
        """
        if not self.enabled:
            yield None
            return
        
        try:
            with mlflow.start_run(run_name=run_name, tags=tags, nested=nested) as run:
                logger.debug(f"Started MLflow run: {run.info.run_id} (nested={nested})")
                yield run
        except Exception as e:
            logger.error(f"MLflow run failed: {e}")
            raise
    
    def log_params(self, params: Dict[str, Any]):
        """Log parameters to MLflow."""
        if not self.enabled:
            return
        
        try:
            mlflow.log_params(params)
            logger.debug(f"Logged {len(params)} parameters to MLflow")
        except Exception as e:
            logger.warning(f"Failed to log parameters: {e}")
    
    @contextmanager
    def track_operation(
        self,
        operation_name: str,
        params: Optional[Dict[str, Any]] = None,
        tags: Optional[Dict[str, str]] = None,
        track_resources: bool = True,
        track_accuracy: bool = True
    ):
        """
        Context manager for tracking an operation with MLflow including resource and accuracy monitoring.
        
        Args:
            operation_name: Name of the operation
            params: Parameters to log
            tags: Tags to add
            track_resources: Track resource consumption
            track_accuracy: Track accuracy metrics
            
        Yields:
            Tracker object with log_metrics, add_feedback, add_relevance, add_confidence methods
        """
        if not self.enabled:
            # Return a dummy tracker that does nothing
            class DummyTracker:
                def log_metrics(self, metrics: Dict[str, float]):
                    pass
                def add_feedback(self, score: float):
                    pass
                def add_relevance(self, score: float):
                    pass
                def add_confidence(self, score: float):
                    pass
            yield DummyTracker()
            return
        
        start_time = time.time()
        
        # Start resource monitoring
        if track_resources and self.resource_monitor:
            self.resource_monitor.start()
        
        # Create fresh accuracy tracker for this operation
        operation_accuracy = AccuracyTracker() if track_accuracy and self.enable_accuracy_tracking else None
        
        try:
            with self.start_run(run_name=operation_name, tags=tags) as run:
                if params:
                    self.log_params(params)
                
                # Create a tracker object that can log metrics and accuracy
                class OperationTracker:
                    def __init__(self, parent, accuracy_tracker):
                        self.parent = parent
                        self.accuracy_tracker = accuracy_tracker
                    
                    def log_metrics(self, metrics: Dict[str, float]):
                        self.parent.log_metrics(metrics)
                    
                    def add_feedback(self, score: float):
                        if self.accuracy_tracker:
                            self.accuracy_tracker.add_feedback(score)
                    
                    def add_relevance(self, score: float):
                        if self.accuracy_tracker:
                            self.accuracy_tracker.add_relevance(score)
                    
                    def add_confidence(self, score: float):
                        if self.accuracy_tracker:
                            self.accuracy_tracker.add_confidence(score)
                
                yield OperationTracker(self, operation_accuracy)
                
                # Log duration
                duration = time.time() - start_time
                metrics = {"operation_duration_seconds": duration}
                
                # Add resource metrics
                if track_resources and self.resource_monitor:
                    resource_metrics = self.resource_monitor.get_metrics()
                    metrics.update(resource_metrics)
                
                # Add accuracy metrics
                if operation_accuracy:
                    accuracy_metrics = operation_accuracy.get_metrics()
                    metrics.update(accuracy_metrics)
                
                self.log_metrics(metrics)
                
        except Exception as e:
            logger.error(f"Error tracking operation {operation_name}: {e}")
            raise
    
    def log_metrics(self, metrics: Dict[str, float], step: Optional[int] = None):
        """Log metrics to MLflow."""
        if not self.enabled:
            return
        
        try:
            mlflow.log_metrics(metrics, step=step)
            logger.debug(f"Logged {len(metrics)} metrics to MLflow")
        except Exception as e:
            logger.warning(f"Failed to log metrics: {e}")
    
    def log_metric(self, key: str, value: float, step: Optional[int] = None):
        """Log a single metric to MLflow."""
        if not self.enabled:
            return
        
        try:
            mlflow.log_metric(key, value, step=step)
        except Exception as e:
            logger.warning(f"Failed to log metric {key}: {e}")
    
    def log_artifact(self, local_path: str, artifact_path: Optional[str] = None):
        """Log an artifact to MLflow."""
        if not self.enabled:
            return
        
        try:
            mlflow.log_artifact(local_path, artifact_path)
            logger.debug(f"Logged artifact: {local_path}")
        except Exception as e:
            logger.warning(f"Failed to log artifact: {e}")
    
    def log_dict(self, dictionary: Dict[str, Any], artifact_file: str):
        """Log a dictionary as a JSON artifact."""
        if not self.enabled:
            return
        
        try:
            mlflow.log_dict(dictionary, artifact_file)
            logger.debug(f"Logged dictionary as {artifact_file}")
        except Exception as e:
            logger.warning(f"Failed to log dictionary: {e}")
    
    def set_tags(self, tags: Dict[str, str]):
        """Set tags for the current run."""
        if not self.enabled:
            return
        
        try:
            mlflow.set_tags(tags)
            logger.debug(f"Set {len(tags)} tags")
        except Exception as e:
            logger.warning(f"Failed to set tags: {e}")
    
    def track_query_lifecycle(
        self,
        query_id: str,
        query_text: str,
        classification: 'QueryClassification',
        collection_metrics: List['CollectionRetrievalMetrics'],
        assembly_metrics: 'DocumentAssemblyMetrics',
        llm_time_ms: float,
        llm_tokens_input: int,
        llm_tokens_output: int,
        total_latency_ms: float,
        cache_hit: bool = False,
        user_feedback_score: Optional[float] = None,
        hallucination_detected: bool = False
    ):
        """
        Track complete query lifecycle in MLflow.
        
        Args:
            query_id: Unique query identifier
            query_text: User query text
            classification: Query classification result
            collection_metrics: List of per-collection metrics
            assembly_metrics: Document assembly metrics
            llm_time_ms: LLM generation time
            llm_tokens_input: Input tokens to LLM
            llm_tokens_output: Output tokens from LLM
            total_latency_ms: Total end-to-end latency
            cache_hit: Whether result was from cache
            user_feedback_score: Optional user feedback (1-5)
            hallucination_detected: Whether hallucination was detected
        """
        if not self.enabled:
            return
        
        try:
            # Create run name
            run_name = f"query_{classification.query_type.value}_{query_id[:8]}"
            
            # Create tags
            tags = {
                "query_id": query_id,
                "query_type": classification.query_type.value,
                "query_topics": ",".join([t.value for t in classification.topics]),
                "routing_strategy": assembly_metrics.collections_searched[0] if assembly_metrics.collections_searched else "unknown",
                "collections_searched": ",".join(assembly_metrics.collections_searched),
                "primary_collection": assembly_metrics.get_primary_collection() or "unknown",
                "cache_hit": str(cache_hit),
                "hallucination_detected": str(hallucination_detected),
            }
            
            with self.start_run(run_name=run_name, tags=tags) as run:
                if not run:
                    return
                
                # Log parameters
                params = {
                    "query_type": classification.query_type.value,
                    "classification_confidence": classification.confidence,
                    "num_collections_searched": len(assembly_metrics.collections_searched),
                }
                self.log_params(params)
                
                # Log classification metrics
                metrics = {
                    "classification_confidence": classification.confidence,
                }
                
                # Log per-collection metrics
                for coll_metrics in collection_metrics:
                    prefix = f"collection_{coll_metrics.collection_name}_"
                    metrics.update({
                        f"{prefix}search_time_ms": coll_metrics.search_time_ms,
                        f"{prefix}chunks_retrieved": float(coll_metrics.chunks_retrieved),
                        f"{prefix}chunks_above_threshold": float(coll_metrics.chunks_above_threshold),
                        f"{prefix}chunks_in_final": float(coll_metrics.chunks_in_final_context),
                        f"{prefix}avg_score": coll_metrics.avg_score,
                        f"{prefix}max_score": coll_metrics.max_score,
                        f"{prefix}precision": coll_metrics.get_precision(),
                        f"{prefix}contribution_rate": coll_metrics.get_contribution_rate(),
                    })
                    
                    if coll_metrics.avg_rank_in_final > 0:
                        metrics[f"{prefix}avg_rank_in_final"] = coll_metrics.avg_rank_in_final
                
                # Log assembly metrics
                metrics.update({
                    "assembly_reranking_time_ms": assembly_metrics.reranking_time_ms,
                    "assembly_chunks_retrieved": float(assembly_metrics.total_chunks_retrieved),
                    "assembly_chunks_used": float(assembly_metrics.total_chunks_used),
                    "assembly_utilization_rate": assembly_metrics.get_utilization_rate(),
                    "assembly_context_length_chars": float(assembly_metrics.context_length_chars),
                    "assembly_context_truncated": float(assembly_metrics.context_truncated),
                    "assembly_diversity_score": assembly_metrics.chunk_diversity_score,
                    "assembly_overlap_score": assembly_metrics.collection_overlap_score,
                })
                
                # Log LLM metrics
                metrics.update({
                    "llm_time_ms": llm_time_ms,
                    "llm_tokens_input": float(llm_tokens_input),
                    "llm_tokens_output": float(llm_tokens_output),
                })
                
                # Log total metrics
                metrics.update({
                    "total_latency_ms": total_latency_ms,
                    "cache_hit": float(cache_hit),
                })
                
                # Log quality metrics if available
                if user_feedback_score is not None:
                    metrics["user_feedback_score"] = user_feedback_score
                
                metrics["hallucination_detected"] = float(hallucination_detected)
                
                self.log_metrics(metrics)
                
                # Log artifacts
                self._log_query_artifacts(
                    query_id,
                    query_text,
                    classification,
                    collection_metrics,
                    assembly_metrics
                )
                
                logger.info(f"Logged query lifecycle to MLflow: {query_id}")
                
        except Exception as e:
            logger.error(f"Failed to track query lifecycle: {e}")
    
    def log_query_sources(
        self,
        query_text: str,
        sources: List[Dict[str, Any]],
        avg_relevance_score: float,
        collection_name: Optional[str] = None
    ):
        """
        Log query source information and quality scores to MLflow.
        
        Args:
            query_text: User query text
            sources: List of source dictionaries with score, collection, file info
            avg_relevance_score: Average relevance score across sources
            collection_name: Primary collection name
        """
        if not self.enabled:
            return
        
        try:
            # Log as metrics
            metrics = {
                "num_sources": float(len(sources)),
                "avg_relevance_score": avg_relevance_score,
            }
            
            if sources:
                scores = [s.get("score", 0.0) for s in sources]
                metrics.update({
                    "min_source_score": min(scores),
                    "max_source_score": max(scores),
                    "median_source_score": sorted(scores)[len(scores)//2] if scores else 0.0,
                })
            
            self.log_metrics(metrics)
            
            # Log sources as artifact
            sources_artifact = {
                "query": query_text,
                "collection": collection_name or "unknown",
                "avg_score": avg_relevance_score,
                "sources": sources
            }
            self.log_dict(sources_artifact, "query_sources.json")
            
            logger.debug(f"Logged {len(sources)} sources to MLflow")
            
        except Exception as e:
            logger.warning(f"Failed to log query sources: {e}")
    
    def _log_query_artifacts(
        self,
        query_id: str,
        query_text: str,
        classification: 'QueryClassification',
        collection_metrics: List['CollectionRetrievalMetrics'],
        assembly_metrics: 'DocumentAssemblyMetrics'
    ):
        """
        Log query artifacts to MLflow.
        
        Args:
            query_id: Query identifier
            query_text: Query text
            classification: Classification result
            collection_metrics: Collection metrics
            assembly_metrics: Assembly metrics
        """
        try:
            # Query details
            query_details = {
                "query_id": query_id,
                "query_text": query_text,
                "query_type": classification.query_type.value,
                "query_topics": [t.value for t in classification.topics],
                "classification_confidence": classification.confidence,
                "matched_patterns": classification.matched_patterns,
                "matched_terms": {
                    topic.value: terms
                    for topic, terms in classification.matched_terms.items()
                },
            }
            self.log_dict(query_details, "query_details.json")
            
            # Routing decision
            routing_decision = {
                "collections_searched": assembly_metrics.collections_searched,
                "primary_collection": assembly_metrics.get_primary_collection(),
                "expected_collections": classification.matched_patterns,  # Placeholder
            }
            self.log_dict(routing_decision, "routing_decision.json")
            
            # Collection results
            collection_results = {}
            for coll_metrics in collection_metrics:
                collection_results[coll_metrics.collection_name] = {
                    "search_time_ms": coll_metrics.search_time_ms,
                    "chunks_retrieved": coll_metrics.chunks_retrieved,
                    "chunks_above_threshold": coll_metrics.chunks_above_threshold,
                    "chunks_in_final": coll_metrics.chunks_in_final_context,
                    "avg_score": coll_metrics.avg_score,
                    "max_score": coll_metrics.max_score,
                    "min_score": coll_metrics.min_score,
                    "score_distribution": coll_metrics.score_distribution,
                    "precision": coll_metrics.get_precision(),
                    "contribution_rate": coll_metrics.get_contribution_rate(),
                }
            self.log_dict(collection_results, "collection_results.json")
            
            # Assembly summary
            assembly_summary = {
                "collections_contributed": assembly_metrics.collections_contributed,
                "file_type_boosts": assembly_metrics.file_type_boosts_applied,
                "file_type_distribution": assembly_metrics.file_type_distribution,
                "total_chunks_retrieved": assembly_metrics.total_chunks_retrieved,
                "total_chunks_used": assembly_metrics.total_chunks_used,
                "utilization_rate": assembly_metrics.get_utilization_rate(),
                "diversity_score": assembly_metrics.chunk_diversity_score,
                "overlap_score": assembly_metrics.collection_overlap_score,
            }
            self.log_dict(assembly_summary, "assembly_summary.json")
            
        except Exception as e:
            logger.warning(f"Failed to log query artifacts: {e}")
    
    def track_collection_performance(
        self,
        collection_name: str,
        metrics_summary: Dict[str, Any]
    ):
        """
        Track per-collection performance summary.
        
        Args:
            collection_name: Name of the collection
            metrics_summary: Summary metrics dict
        """
        if not self.enabled:
            return
        
        try:
            run_name = f"collection_summary_{collection_name}"
            tags = {
                "collection_name": collection_name,
                "metric_type": "collection_summary",
            }
            
            with self.start_run(run_name=run_name, tags=tags) as run:
                if not run:
                    return
                
                # Convert all values to float for MLflow
                metrics = {}
                for key, value in metrics_summary.items():
                    if isinstance(value, (int, float)):
                        metrics[key] = float(value)
                
                self.log_metrics(metrics)
                self.log_dict(metrics_summary, f"{collection_name}_summary.json")
                
                logger.info(f"Logged collection performance for {collection_name}")
                
        except Exception as e:
            logger.error(f"Failed to track collection performance: {e}")


# Global tracker instance
_mlflow_tracker: Optional[MLflowTracker] = None


def get_mlflow_tracker(
    enable_resource_monitoring: bool = True,
    enable_accuracy_tracking: bool = True
) -> MLflowTracker:
    """
    Get or create the global MLflow tracker instance.
    
    Args:
        enable_resource_monitoring: Enable CPU/memory/GPU monitoring
        enable_accuracy_tracking: Enable accuracy metrics tracking
        
    Returns:
        MLflowTracker instance
    """
    global _mlflow_tracker
    
    if _mlflow_tracker is None:
        _mlflow_tracker = MLflowTracker(
            enable_resource_monitoring=enable_resource_monitoring,
            enable_accuracy_tracking=enable_accuracy_tracking
        )
    
    return _mlflow_tracker


@contextmanager
def track_operation(
    operation_name: str,
    params: Optional[Dict[str, Any]] = None,
    tags: Optional[Dict[str, str]] = None
):
    """
    Context manager to track an operation with MLflow.
    
    Args:
        operation_name: Name of the operation
        params: Parameters to log
        tags: Tags to add
        
    Yields:
        Tracker object with log_metric method
    """
    tracker = get_mlflow_tracker()
    
    start_time = time.time()
    
    with tracker.start_run(run_name=operation_name, tags=tags) as run:
        if run and params:
            tracker.log_params(params)
        
        # Create a simple object to hold metrics during the operation
        class MetricsLogger:
            def log_metric(self, key: str, value: float):
                tracker.log_metric(key, value)
            
            def log_metrics(self, metrics: Dict[str, float]):
                tracker.log_metrics(metrics)
        
        metrics_logger = MetricsLogger()
        
        try:
            yield metrics_logger
        finally:
            # Log duration
            duration = time.time() - start_time
            tracker.log_metric("duration_seconds", duration)
            logger.info(f"Operation '{operation_name}' completed in {duration:.2f}s")