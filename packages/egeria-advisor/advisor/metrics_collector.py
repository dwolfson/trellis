"""
Metrics collection framework for monitoring system performance.

Collects and stores metrics about queries, collections, and system resources.
"""

import time
import psutil
import json
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from contextlib import contextmanager
from loguru import logger

from advisor.config import get_full_config
from advisor.db_consolidated import get_db_manager


@dataclass
class QueryMetric:
    """Metrics for a single query."""
    timestamp: float
    query_text: str
    collection_name: Optional[str]
    latency_ms: float
    cache_hit: bool
    success: bool
    query_type: Optional[str] = None
    error_message: Optional[str] = None
    result_count: Optional[int] = None
    embedding_time_ms: Optional[float] = None
    search_time_ms: Optional[float] = None
    llm_time_ms: Optional[float] = None
    avg_relevance_score: Optional[float] = None
    sources_json: Optional[str] = None  # JSON string of source metadata
    
    # Audit / Context columns
    active_perspective: Optional[str] = None
    resolved_intent: Optional[str] = None
    routing_agent: Optional[str] = None
    applied_policy_rule: Optional[Dict[str, Any]] = None  # Saved as JSONB
    perspective_history: Optional[List[str]] = None  # Saved as JSONB
    session_id: Optional[str] = None
    user_id: Optional[str] = None
    rating: Optional[str] = None
    star_rating: Optional[int] = None
    suggested_collection: Optional[str] = None
    feedback_text: Optional[str] = None


@dataclass
class CollectionHealth:
    """Health metrics for a collection."""
    collection_name: str
    last_check: float
    entity_count: int
    health_score: float
    storage_size_mb: float
    last_update: float
    status: str  # 'healthy', 'degraded', 'critical'


@dataclass
class SystemMetric:
    """System resource metrics."""
    timestamp: float
    cpu_percent: float
    memory_percent: float
    gpu_percent: Optional[float]
    disk_io_read_mb: float
    disk_io_write_mb: float
    network_sent_mb: float
    network_recv_mb: float


class MetricsCollector:
    """
    Collect and store system metrics.
    
    Provides methods to record query metrics, collection health,
    and system resource usage in consolidated PostgreSQL.
    """
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize metrics collector.
        
        Args:
            db_path: Ignored, retained for signature compatibility.
        """
        self.db_manager = get_db_manager()
        self.db_manager.connect()
        
        # Track disk I/O baseline
        self._disk_io_baseline = psutil.disk_io_counters()
        self._network_baseline = psutil.net_io_counters()
        
        logger.info("Initialized MetricsCollector using consolidated PostgreSQL database")
    
    def record_query(self, metric: QueryMetric):
        """
        Record a query metric.
        
        Args:
            metric: QueryMetric instance
        """
        sql = """
            INSERT INTO query_metrics
            (timestamp, query_text, collection_name, latency_ms, query_type,
             cache_hit, success, error_message, result_count, embedding_time_ms,
             search_time_ms, llm_time_ms, avg_relevance_score, sources_json,
             active_perspective, resolved_intent, routing_agent,
             applied_policy_rule, perspective_history, session_id, user_id,
             rating, star_rating, suggested_collection, feedback_text)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        
        applied_policy_rule_json = json.dumps(metric.applied_policy_rule) if metric.applied_policy_rule is not None else None
        perspective_history_json = json.dumps(metric.perspective_history) if metric.perspective_history is not None else None
        
        self.db_manager.execute_update(sql, (
            metric.timestamp,
            metric.query_text,
            metric.collection_name,
            metric.latency_ms,
            metric.query_type,
            bool(metric.cache_hit),
            bool(metric.success),
            metric.error_message,
            metric.result_count,
            metric.embedding_time_ms,
            metric.search_time_ms,
            metric.llm_time_ms,
            metric.avg_relevance_score,
            metric.sources_json,
            metric.active_perspective,
            metric.resolved_intent,
            metric.routing_agent,
            applied_policy_rule_json,
            perspective_history_json,
            metric.session_id,
            metric.user_id,
            metric.rating,
            metric.star_rating,
            metric.suggested_collection,
            metric.feedback_text
        ))
    
    def record_plan_event(
        self,
        doc_id: str,
        event_type: str,
        title: Optional[str] = None,
        command_families: Optional[str] = None,
        outcome_status: Optional[str] = None,
        perspective: Optional[str] = None,
    ) -> None:
        """Record a plan lifecycle event (created / executed / archived)."""
        try:
            sql = """
                INSERT INTO plan_events
                (timestamp, doc_id, event_type, title, command_families, outcome_status, perspective)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            self.db_manager.execute_update(sql, (time.time(), doc_id, event_type, title, command_families, outcome_status, perspective))
        except Exception as exc:
            logger.warning(f"MetricsCollector.record_plan_event failed: {exc}")

    def record_collection_health(self, health: CollectionHealth):
        """
        Record collection health metrics.
        
        Args:
            health: CollectionHealth instance
        """
        sql = """
            INSERT INTO collection_health
            (collection_name, last_check, entity_count, health_score,
             storage_size_mb, last_update, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (collection_name) DO UPDATE SET
                last_check = EXCLUDED.last_check,
                entity_count = EXCLUDED.entity_count,
                health_score = EXCLUDED.health_score,
                storage_size_mb = EXCLUDED.storage_size_mb,
                last_update = EXCLUDED.last_update,
                status = EXCLUDED.status
        """
        self.db_manager.execute_update(sql, (
            health.collection_name,
            health.last_check,
            health.entity_count,
            health.health_score,
            health.storage_size_mb,
            health.last_update,
            health.status
        ))
    
    def record_system_metrics(self):
        """Record current system resource metrics."""
        metric = self.collect_system_metrics()
        
        sql = """
            INSERT INTO system_metrics
            (timestamp, cpu_percent, memory_percent, gpu_percent,
             disk_io_read_mb, disk_io_write_mb, network_sent_mb, network_recv_mb)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """
        self.db_manager.execute_update(sql, (
            metric.timestamp,
            metric.cpu_percent,
            metric.memory_percent,
            metric.gpu_percent,
            metric.disk_io_read_mb,
            metric.disk_io_write_mb,
            metric.network_sent_mb,
            metric.network_recv_mb
        ))
    
    def collect_system_metrics(self) -> SystemMetric:
        """
        Collect current system resource metrics.
        
        Returns:
            SystemMetric instance
        """
        # CPU and memory
        cpu_percent = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        
        # GPU (if available)
        gpu_percent = None
        try:
            import torch
            if torch.cuda.is_available():
                gpu_percent = torch.cuda.utilization()
            elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                gpu_percent = 0.0
        except:
            pass
        
        # Disk I/O
        disk_io = psutil.disk_io_counters()
        disk_read_mb = (disk_io.read_bytes - self._disk_io_baseline.read_bytes) / (1024 * 1024)
        disk_write_mb = (disk_io.write_bytes - self._disk_io_baseline.write_bytes) / (1024 * 1024)
        
        # Network I/O
        net_io = psutil.net_io_counters()
        net_sent_mb = (net_io.bytes_sent - self._network_baseline.bytes_sent) / (1024 * 1024)
        net_recv_mb = (net_io.bytes_recv - self._network_baseline.bytes_recv) / (1024 * 1024)
        
        return SystemMetric(
            timestamp=time.time(),
            cpu_percent=cpu_percent,
            memory_percent=memory.percent,
            gpu_percent=gpu_percent,
            disk_io_read_mb=disk_read_mb,
            disk_io_write_mb=disk_write_mb,
            network_sent_mb=net_sent_mb,
            network_recv_mb=net_recv_mb
        )
    
    def record_error(self, error_type: str, error_message: str, 
                    stack_trace: Optional[str] = None, context: Optional[str] = None):
        """
        Record an error.
        
        Args:
            error_type: Type of error
            error_message: Error message
            stack_trace: Optional stack trace
            context: Optional context information
        """
        sql = """
            INSERT INTO error_log
            (timestamp, error_type, error_message, stack_trace, context)
            VALUES (%s, %s, %s, %s, %s)
        """
        self.db_manager.execute_update(sql, (time.time(), error_type, error_message, stack_trace, context))
    
    def get_recent_queries(self, limit: int = 100) -> List[Dict]:
        """
        Get recent query metrics.
        
        Args:
            limit: Maximum number of queries to return
            
        Returns:
            List of query metric dicts
        """
        sql = """
            SELECT * FROM query_metrics
            ORDER BY timestamp DESC
            LIMIT %s
        """
        return self.db_manager.execute_query(sql, (limit,))
    
    def get_collection_health(self, collection_name: Optional[str] = None) -> List[Dict]:
        """
        Get collection health metrics.
        
        Args:
            collection_name: Optional collection name filter
            
        Returns:
            List of collection health dicts
        """
        if collection_name:
            sql = "SELECT * FROM collection_health WHERE collection_name = %s"
            return self.db_manager.execute_query(sql, (collection_name,))
        else:
            sql = "SELECT * FROM collection_health"
            return self.db_manager.execute_query(sql)
    
    def get_query_stats(self, hours: int = 24) -> Dict[str, Any]:
        """
        Get aggregated query statistics.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            Dict with statistics
        """
        cutoff = time.time() - (hours * 3600)
        
        # Total queries
        total_sql = "SELECT COUNT(*) AS count FROM query_metrics WHERE timestamp > %s"
        total_res = self.db_manager.execute_query(total_sql, (cutoff,))
        total_queries = total_res[0]['count'] if total_res else 0
        
        # Success rate
        success_sql = "SELECT COUNT(*) AS count FROM query_metrics WHERE timestamp > %s AND success = TRUE"
        success_res = self.db_manager.execute_query(success_sql, (cutoff,))
        successful_queries = success_res[0]['count'] if success_res else 0
        success_rate = successful_queries / total_queries if total_queries > 0 else 0
        
        # Cache hit rate
        cache_sql = "SELECT COUNT(*) AS count FROM query_metrics WHERE timestamp > %s AND cache_hit = TRUE"
        cache_res = self.db_manager.execute_query(cache_sql, (cutoff,))
        cache_hits = cache_res[0]['count'] if cache_res else 0
        cache_hit_rate = cache_hits / total_queries if total_queries > 0 else 0
        
        # Average latency
        avg_latency_sql = "SELECT AVG(latency_ms) AS avg FROM query_metrics WHERE timestamp > %s AND success = TRUE"
        avg_latency_res = self.db_manager.execute_query(avg_latency_sql, (cutoff,))
        avg_val = avg_latency_res[0]['avg'] if avg_latency_res else None
        avg_latency = float(avg_val) if avg_val is not None else 0.0
        
        # Percentiles
        percentile_sql = """
            SELECT latency_ms FROM query_metrics 
            WHERE timestamp > %s AND success = TRUE
            ORDER BY latency_ms
        """
        latencies = [float(row['latency_ms']) for row in self.db_manager.execute_query(percentile_sql, (cutoff,))]
        
        p50 = latencies[len(latencies) // 2] if latencies else 0
        p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0
        p99 = latencies[int(len(latencies) * 0.99)] if latencies else 0
        
        return {
            "total_queries": total_queries,
            "successful_queries": successful_queries,
            "success_rate": success_rate,
            "cache_hits": cache_hits,
            "cache_hit_rate": cache_hit_rate,
            "avg_latency_ms": avg_latency,
            "p50_latency_ms": p50,
            "p95_latency_ms": p95,
            "p99_latency_ms": p99
        }
    
    def cleanup_old_metrics(self, days: int = 30):
        """
        Remove metrics older than specified days.
        
        Args:
            days: Number of days to retain
        """
        cutoff = time.time() - (days * 86400)
        
        self.db_manager.execute_update("DELETE FROM query_metrics WHERE timestamp < %s", (cutoff,))
        self.db_manager.execute_update("DELETE FROM system_metrics WHERE timestamp < %s", (cutoff,))
        self.db_manager.execute_update("DELETE FROM error_log WHERE timestamp < %s", (cutoff,))
        
        logger.info(f"Cleaned up metrics older than {days} days")


@contextmanager
def track_query(collector: MetricsCollector, query_text: str, 
                collection_name: Optional[str] = None):
    """
    Context manager to track query metrics.
    
    Usage:
        with track_query(collector, "What is Egeria?") as tracker:
            result = perform_query()
            tracker.set_result(result)
    
    Args:
        collector: MetricsCollector instance
        query_text: Query text
        collection_name: Optional collection name
    """
    class QueryTracker:
        def __init__(self):
            self.start_time = time.time()
            self.cache_hit = False
            self.success = True
            self.error_message = None
            self.query_type = None
            self.result_count = None
            self.embedding_time_ms = None
            self.search_time_ms = None
            self.llm_time_ms = None
            self.avg_relevance_score = None
            self.sources_json = None
            
            # New audit columns
            self.active_perspective = None
            self.resolved_intent = None
            self.routing_agent = None
            self.applied_policy_rule = None
            self.perspective_history = None
        
        def set_cache_hit(self, hit: bool):
            self.cache_hit = hit
        
        def set_result(self, result):
            if hasattr(result, '__len__'):
                self.result_count = len(result)
        
        def set_error(self, error: Exception):
            self.success = False
            self.error_message = str(error)
        
        def set_timing(self, embedding_ms=None, search_ms=None, llm_ms=None):
            if embedding_ms is not None:
                self.embedding_time_ms = embedding_ms
            if search_ms is not None:
                self.search_time_ms = search_ms
            if llm_ms is not None:
                self.llm_time_ms = llm_ms
    
    tracker = QueryTracker()
    
    try:
        yield tracker
    except Exception as e:
        tracker.set_error(e)
        raise
    finally:
        latency_ms = (time.time() - tracker.start_time) * 1000
        
        metric = QueryMetric(
            timestamp=time.time(),
            query_text=query_text,
            collection_name=collection_name,
            latency_ms=latency_ms,
            query_type=tracker.query_type,
            cache_hit=tracker.cache_hit,
            success=tracker.success,
            error_message=tracker.error_message,
            result_count=tracker.result_count,
            embedding_time_ms=tracker.embedding_time_ms,
            search_time_ms=tracker.search_time_ms,
            llm_time_ms=tracker.llm_time_ms,
            avg_relevance_score=tracker.avg_relevance_score,
            sources_json=tracker.sources_json,
            active_perspective=tracker.active_perspective,
            resolved_intent=tracker.resolved_intent,
            routing_agent=tracker.routing_agent,
            applied_policy_rule=tracker.applied_policy_rule,
            perspective_history=tracker.perspective_history
        )
        
        collector.record_query(metric)


# Global metrics collector instance
_metrics_collector: Optional[MetricsCollector] = None


def get_metrics_collector() -> MetricsCollector:
    """Get or create global metrics collector instance."""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def sync_collection_health(retriever, collector):
    """
    Sync entity counts and health status for all enabled collections.
    
    Parameters
    ----------
    retriever : RAGRetriever or similar
        Object with access to vector_store
    collector : MetricsCollector
        Collector instance for recording health
    """
    try:
        from advisor.collection_config import get_enabled_collections
        from advisor.metrics_collector import CollectionHealth
        
        for collection in get_enabled_collections():
            try:
                # Use retriever's vector store to get actual count
                stats = retriever.vector_store.get_collection_stats(collection.name)
                count = stats.get("num_entities", 0)
                
                # Record health
                health = CollectionHealth(
                    collection_name=collection.name,
                    last_check=time.time(),
                    entity_count=count,
                    health_score=1.0 if count > 0 else 0.0,
                    storage_size_mb=0.0,  # Could be estimated if needed
                    last_update=time.time(),
                    status='healthy' if count > 0 else 'empty'
                )
                collector.record_collection_health(health)
            except Exception as e:
                # Only log as debug to avoid noise if the vector store isn't fully ready
                logger.debug(f"Could not get stats for collection {collection.name}: {e}")
                
        logger.debug("Successfully synced collection health metrics")
    except Exception as e:
        logger.warning(f"Failed to sync collection health: {e}")