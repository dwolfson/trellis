#!/usr/bin/env python3
"""
Test script to verify monitoring integration in RAG system components.

This script tests that monitoring code has been properly injected into:
- Query Agent
- LLM Client
- Query Processor
"""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.query_processor import get_query_processor
from advisor.llm_client import get_ollama_client
from advisor.agents.query_agent import QueryAgent
from advisor.metrics_collector import get_metrics_collector
from advisor.mlflow_tracking import get_mlflow_tracker


def test_query_processor_monitoring():
    """Test that query processor has monitoring."""
    logger.info("=" * 60)
    logger.info("Testing Query Processor Monitoring")
    logger.info("=" * 60)
    
    processor = get_query_processor()
    
    # Check that monitoring components are initialized
    assert hasattr(processor, 'mlflow_tracker'), "Query processor missing mlflow_tracker"
    assert hasattr(processor, 'metrics_collector'), "Query processor missing metrics_collector"
    logger.success("✓ Query processor has monitoring components")
    
    # Test processing a query
    test_query = "How do I create a glossary in Egeria?"
    result = processor.process(test_query)
    
    assert 'query_type' in result, "Query processing result missing query_type"
    assert 'keywords' in result, "Query processing result missing keywords"
    logger.success(f"✓ Query processed successfully: type={result['query_type']}")
    
    # Test with confidence
    query_type, confidence = processor.detect_query_type_with_confidence(test_query)
    logger.success(f"✓ Query type detection with confidence: {query_type.value} ({confidence:.2f})")
    
    return True


def test_llm_client_monitoring():
    """Test that LLM client has monitoring."""
    logger.info("=" * 60)
    logger.info("Testing LLM Client Monitoring")
    logger.info("=" * 60)
    
    client = get_ollama_client()
    
    # Check that monitoring components are initialized
    assert hasattr(client, 'mlflow_tracker'), "LLM client missing mlflow_tracker"
    assert hasattr(client, 'metrics_collector'), "LLM client missing metrics_collector"
    logger.success("✓ LLM client has monitoring components")
    
    # Check if Ollama is available
    if not client.is_available():
        logger.warning("⚠ Ollama service not available - skipping generation test")
        return True
    
    # Test generation (with a very short prompt to be quick)
    try:
        response = client.generate(
            prompt="Say 'test' in one word",
            max_tokens=10,
            temperature=0.1
        )
        logger.success(f"✓ LLM generation successful: {len(response)} chars")
    except Exception as e:
        logger.warning(f"⚠ LLM generation failed (expected if Ollama not running): {e}")
    
    return True


async def test_query_agent_monitoring():
    """Test that query agent has monitoring."""
    logger.info("=" * 60)
    logger.info("Testing Query Agent Monitoring")
    logger.info("=" * 60)
    
    try:
        agent = QueryAgent()
        
        # Check that monitoring components are initialized
        assert hasattr(agent, 'mlflow_tracker'), "Query agent missing mlflow_tracker"
        assert hasattr(agent, 'metrics_collector'), "Query agent missing metrics_collector"
        logger.success("✓ Query agent has monitoring components")
        
        # Test processing (will likely fail without proper setup, but we're testing monitoring)
        try:
            result = await agent.process("What is Egeria?")
            logger.success(f"✓ Query agent processing completed: {result.get('agent')}")
        except Exception as e:
            logger.warning(f"⚠ Query agent processing failed (expected without full setup): {e}")
        
        return True
    except Exception as e:
        logger.error(f"✗ Query agent initialization failed: {e}")
        return False


def test_metrics_collection():
    """Test that metrics are being collected."""
    logger.info("=" * 60)
    logger.info("Testing Metrics Collection")
    logger.info("=" * 60)
    
    collector = get_metrics_collector()
    
    # Get recent queries
    recent_queries = collector.get_recent_queries(limit=10)
    logger.info(f"Found {len(recent_queries)} recent queries in metrics database")
    
    if recent_queries:
        latest = recent_queries[0]
        logger.info(f"Latest query: {latest['query_text'][:50]}...")
        logger.info(f"  - Latency: {latest['latency_ms']:.1f}ms")
        logger.info(f"  - Success: {latest['success']}")
        logger.success("✓ Metrics are being collected")
    else:
        logger.info("No queries in metrics database yet (expected for fresh install)")
    
    # Get query stats
    stats = collector.get_query_stats(hours=24)
    logger.info(f"Query stats (last 24h):")
    logger.info(f"  - Total queries: {stats['total_queries']}")
    logger.info(f"  - Success rate: {stats['success_rate']:.1%}")
    logger.info(f"  - Cache hit rate: {stats['cache_hit_rate']:.1%}")
    logger.info(f"  - Avg latency: {stats['avg_latency_ms']:.1f}ms")
    
    return True


def test_mlflow_tracking():
    """Test that MLflow tracking is configured."""
    logger.info("=" * 60)
    logger.info("Testing MLflow Tracking")
    logger.info("=" * 60)
    
    tracker = get_mlflow_tracker()
    
    logger.info(f"MLflow enabled: {tracker.enabled}")
    logger.info(f"Tracking URI: {tracker.tracking_uri}")
    logger.info(f"Experiment: {tracker.experiment_name}")
    logger.info(f"Resource monitoring: {tracker.enable_resource_monitoring}")
    logger.info(f"Accuracy tracking: {tracker.enable_accuracy_tracking}")
    
    if tracker.enabled:
        logger.success("✓ MLflow tracking is enabled and configured")
    else:
        logger.warning("⚠ MLflow tracking is disabled (check .env configuration)")
    
    return True


async def main():
    """Run all monitoring tests."""
    logger.info("Starting Monitoring Integration Tests")
    logger.info("=" * 60)
    
    results = []
    
    # Test each component
    try:
        results.append(("Query Processor", test_query_processor_monitoring()))
    except Exception as e:
        logger.error(f"Query Processor test failed: {e}")
        results.append(("Query Processor", False))
    
    try:
        results.append(("LLM Client", test_llm_client_monitoring()))
    except Exception as e:
        logger.error(f"LLM Client test failed: {e}")
        results.append(("LLM Client", False))
    
    try:
        results.append(("Query Agent", await test_query_agent_monitoring()))
    except Exception as e:
        logger.error(f"Query Agent test failed: {e}")
        results.append(("Query Agent", False))
    
    try:
        results.append(("Metrics Collection", test_metrics_collection()))
    except Exception as e:
        logger.error(f"Metrics Collection test failed: {e}")
        results.append(("Metrics Collection", False))
    
    try:
        results.append(("MLflow Tracking", test_mlflow_tracking()))
    except Exception as e:
        logger.error(f"MLflow Tracking test failed: {e}")
        results.append(("MLflow Tracking", False))
    
    # Summary
    logger.info("=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)
    
    for component, passed in results:
        status = "✓ PASS" if passed else "✗ FAIL"
        logger.info(f"{status}: {component}")
    
    total_tests = len(results)
    passed_tests = sum(1 for _, passed in results if passed)
    
    logger.info("=" * 60)
    logger.info(f"Results: {passed_tests}/{total_tests} tests passed")
    
    if passed_tests == total_tests:
        logger.success("All monitoring integration tests passed!")
        return 0
    else:
        logger.warning(f"{total_tests - passed_tests} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)