#!/usr/bin/env python3
"""
Test script for enhanced MLflow tracking with resource and accuracy monitoring.

This script tests:
1. Resource monitoring (CPU, memory, GPU)
2. Accuracy tracking (feedback, relevance, confidence)
3. Integration with MLflow
"""

import sys
import time
import random
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.mlflow_tracking import (
    get_mlflow_tracker,
    ResourceMonitor,
    AccuracyTracker
)
from loguru import logger


def test_resource_monitor():
    """Test ResourceMonitor class."""
    logger.info("Testing ResourceMonitor...")
    
    monitor = ResourceMonitor()
    monitor.start()
    
    # Simulate some work
    data = []
    for i in range(100000):
        data.append(i * 2)
    
    time.sleep(0.5)
    
    metrics = monitor.get_metrics()
    
    logger.info(f"Resource metrics: {metrics}")
    
    # Validate metrics
    assert "resource_duration_seconds" in metrics
    assert "resource_cpu_percent" in metrics
    assert "resource_memory_mb" in metrics
    assert "resource_memory_delta_mb" in metrics
    
    assert metrics["resource_duration_seconds"] > 0
    assert metrics["resource_memory_mb"] > 0
    
    logger.success("✓ ResourceMonitor test passed")
    return metrics


def test_accuracy_tracker():
    """Test AccuracyTracker class."""
    logger.info("Testing AccuracyTracker...")
    
    tracker = AccuracyTracker()
    
    # Add various scores
    tracker.add_feedback(4.5)  # 1-5 scale
    tracker.add_feedback(5.0)
    tracker.add_feedback(3.5)
    
    tracker.add_relevance(0.85)
    tracker.add_relevance(0.92)
    tracker.add_relevance(0.78)
    
    tracker.add_confidence(0.88)
    tracker.add_confidence(0.95)
    
    metrics = tracker.get_metrics()
    
    logger.info(f"Accuracy metrics: {metrics}")
    
    # Validate metrics
    assert "accuracy_feedback_avg" in metrics
    assert "accuracy_feedback_count" in metrics
    assert "accuracy_relevance_avg" in metrics
    assert "accuracy_relevance_count" in metrics
    assert "accuracy_confidence_avg" in metrics
    assert "accuracy_confidence_count" in metrics
    
    # Check averages
    assert 0 <= metrics["accuracy_feedback_avg"] <= 1
    assert 0 <= metrics["accuracy_relevance_avg"] <= 1
    assert 0 <= metrics["accuracy_confidence_avg"] <= 1
    
    # Check counts
    assert metrics["accuracy_feedback_count"] == 3
    assert metrics["accuracy_relevance_count"] == 3
    assert metrics["accuracy_confidence_count"] == 2
    
    logger.success("✓ AccuracyTracker test passed")
    return metrics


def test_mlflow_tracker_basic():
    """Test basic MLflowTracker functionality."""
    logger.info("Testing MLflowTracker basic functionality...")
    
    tracker = get_mlflow_tracker()
    
    if not tracker.enabled:
        logger.warning("MLflow tracking is disabled, skipping test")
        return
    
    with tracker.track_operation(
        operation_name="test_basic_operation",
        params={"test_param": "value"},
        tags={"test": "basic"}
    ) as op:
        # Simulate work
        time.sleep(0.2)
        
        # Log some metrics
        op.log_metrics({"test_metric": 42.0})
    
    logger.success("✓ MLflowTracker basic test passed")


def test_mlflow_tracker_with_resources():
    """Test MLflowTracker with resource monitoring."""
    logger.info("Testing MLflowTracker with resource monitoring...")
    
    tracker = get_mlflow_tracker()
    
    if not tracker.enabled:
        logger.warning("MLflow tracking is disabled, skipping test")
        return
    
    with tracker.track_operation(
        operation_name="test_resource_monitoring",
        params={"operation": "resource_test"},
        tags={"test": "resources"},
        track_resources=True
    ) as op:
        # Simulate CPU and memory intensive work
        data = []
        for i in range(500000):
            data.append(i ** 2)
        
        time.sleep(0.3)
        
        # Log custom metrics
        op.log_metrics({"custom_metric": 123.45})
    
    logger.success("✓ MLflowTracker resource monitoring test passed")


def test_mlflow_tracker_with_accuracy():
    """Test MLflowTracker with accuracy tracking."""
    logger.info("Testing MLflowTracker with accuracy tracking...")
    
    tracker = get_mlflow_tracker()
    
    if not tracker.enabled:
        logger.warning("MLflow tracking is disabled, skipping test")
        return
    
    with tracker.track_operation(
        operation_name="test_accuracy_tracking",
        params={"query": "test query"},
        tags={"test": "accuracy"},
        track_accuracy=True
    ) as op:
        # Simulate query processing
        time.sleep(0.1)
        
        # Add accuracy metrics
        op.add_relevance(0.87)
        op.add_confidence(0.93)
        op.add_feedback(4.2)
        
        # Add more scores
        op.add_relevance(0.91)
        op.add_confidence(0.88)
    
    logger.success("✓ MLflowTracker accuracy tracking test passed")


def test_mlflow_tracker_complete():
    """Test MLflowTracker with both resource and accuracy tracking."""
    logger.info("Testing MLflowTracker with complete monitoring...")
    
    tracker = get_mlflow_tracker()
    
    if not tracker.enabled:
        logger.warning("MLflow tracking is disabled, skipping test")
        return
    
    with tracker.track_operation(
        operation_name="test_complete_monitoring",
        params={
            "query": "How do I create a glossary?",
            "query_type": "code_search",
            "top_k": 10
        },
        tags={
            "test": "complete",
            "environment": "test"
        },
        track_resources=True,
        track_accuracy=True
    ) as op:
        # Simulate vector search
        time.sleep(0.1)
        search_relevance = random.uniform(0.7, 0.95)
        op.add_relevance(search_relevance)
        
        # Simulate LLM generation
        data = []
        for i in range(100000):
            data.append(i * 3)
        time.sleep(0.2)
        
        llm_confidence = random.uniform(0.8, 0.98)
        op.add_confidence(llm_confidence)
        
        # Simulate user feedback
        user_rating = random.uniform(3.5, 5.0)
        op.add_feedback(user_rating)
        
        # Log custom metrics
        op.log_metrics({
            "vector_search_time": 0.1,
            "llm_generation_time": 0.2,
            "total_results": 10
        })
    
    logger.success("✓ MLflowTracker complete monitoring test passed")


def test_mlflow_tracker_disabled_features():
    """Test MLflowTracker with disabled features."""
    logger.info("Testing MLflowTracker with disabled features...")
    
    tracker = get_mlflow_tracker()
    
    if not tracker.enabled:
        logger.warning("MLflow tracking is disabled, skipping test")
        return
    
    # Test with resources disabled
    with tracker.track_operation(
        operation_name="test_no_resources",
        track_resources=False,
        track_accuracy=True
    ) as op:
        time.sleep(0.1)
        op.add_relevance(0.85)
    
    # Test with accuracy disabled
    with tracker.track_operation(
        operation_name="test_no_accuracy",
        track_resources=True,
        track_accuracy=False
    ) as op:
        time.sleep(0.1)
        op.log_metrics({"test": 1.0})
    
    # Test with both disabled
    with tracker.track_operation(
        operation_name="test_no_monitoring",
        track_resources=False,
        track_accuracy=False
    ) as op:
        time.sleep(0.1)
        op.log_metrics({"basic": 2.0})
    
    logger.success("✓ MLflowTracker disabled features test passed")


def main():
    """Run all tests."""
    logger.info("=" * 60)
    logger.info("Enhanced MLflow Tracking Test Suite")
    logger.info("=" * 60)
    
    try:
        # Test individual components
        logger.info("\n1. Testing Individual Components")
        logger.info("-" * 60)
        resource_metrics = test_resource_monitor()
        accuracy_metrics = test_accuracy_tracker()
        
        # Test MLflow integration
        logger.info("\n2. Testing MLflow Integration")
        logger.info("-" * 60)
        test_mlflow_tracker_basic()
        test_mlflow_tracker_with_resources()
        test_mlflow_tracker_with_accuracy()
        test_mlflow_tracker_complete()
        test_mlflow_tracker_disabled_features()
        
        # Summary
        logger.info("\n" + "=" * 60)
        logger.success("All tests passed! ✓")
        logger.info("=" * 60)
        
        logger.info("\nSummary:")
        logger.info(f"  Resource monitoring: {len(resource_metrics)} metrics tracked")
        logger.info(f"  Accuracy tracking: {len(accuracy_metrics)} metrics tracked")
        logger.info("\nView results in MLflow UI:")
        logger.info("  http://localhost:5025")
        logger.info("\nLook for runs with names starting with 'test_'")
        
        return 0
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())