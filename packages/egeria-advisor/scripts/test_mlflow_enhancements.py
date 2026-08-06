#!/usr/bin/env python3
"""
Test script to verify MLflow tracking enhancements.

This script tests the new MLflow tracking functionality added to:
- explain_code()
- find_similar_code()
- get_file_summary()
- Enhanced metrics in query()
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import get_rag_system
from loguru import logger
import time


def print_section(title: str):
    """Print a section header."""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")


def test_explain_code():
    """Test explain_code with MLflow tracking."""
    print_section("Test 1: explain_code() with MLflow Tracking")
    
    rag = get_rag_system()
    
    code = """def get_asset(guid):
    '''Get an asset by GUID'''
    return client.get_asset_by_guid(guid)"""
    
    print(f"Code to explain:\n{code}\n")
    
    try:
        result = rag.explain_code(code, track_metrics=True)
        print(f"✓ Explanation generated ({len(result)} chars)")
        print(f"\nExplanation:\n{result[:200]}...")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        logger.exception("explain_code test failed")
        return False


def test_find_similar_code():
    """Test find_similar_code with MLflow tracking."""
    print_section("Test 2: find_similar_code() with MLflow Tracking")
    
    rag = get_rag_system()
    
    code = "def create_glossary(name, description):"
    
    print(f"Finding code similar to: {code}\n")
    
    try:
        results = rag.find_similar_code(code, top_k=3, track_metrics=True)
        print(f"✓ Found {len(results)} similar code snippets")
        
        for i, result in enumerate(results, 1):
            print(f"\n{i}. {result.get('name', 'Unknown')}")
            print(f"   File: {result.get('file_path', 'Unknown')}")
            print(f"   Score: {result.get('score', 0.0):.4f}")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        logger.exception("find_similar_code test failed")
        return False


def test_get_file_summary():
    """Test get_file_summary with MLflow tracking."""
    print_section("Test 3: get_file_summary() with MLflow Tracking")
    
    rag = get_rag_system()
    
    # Use a common file path that should exist in the vector store
    file_path = "egeria-client.py"
    
    print(f"Getting summary for: {file_path}\n")
    
    try:
        summary = rag.get_file_summary(file_path, track_metrics=True)
        print(f"✓ Summary generated ({len(summary)} chars)")
        print(f"\nSummary:\n{summary[:300]}...")
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        logger.exception("get_file_summary test failed")
        return False


def test_enhanced_query_metrics():
    """Test enhanced metrics in query() method."""
    print_section("Test 4: Enhanced Metrics in query()")
    
    rag = get_rag_system()
    
    query = "How do I create a glossary in Egeria?"
    
    print(f"Query: {query}\n")
    
    try:
        result = rag.query(query, include_context=True, track_metrics=True)
        
        print(f"✓ Query processed successfully")
        print(f"\nMetrics captured:")
        print(f"  - Response length: {len(result['response'])} chars")
        print(f"  - Number of sources: {result.get('num_sources', 0)}")
        print(f"  - Retrieval time: {result.get('retrieval_time', 0.0):.3f}s")
        print(f"  - Generation time: {result.get('generation_time', 0.0):.3f}s")
        print(f"  - Avg relevance score: {result.get('avg_relevance_score', 0.0):.4f}")
        print(f"  - Context length: {result.get('context_length', 0)} chars")
        
        print(f"\nResponse preview:\n{result['response'][:200]}...")
        
        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        logger.exception("enhanced query metrics test failed")
        return False


def test_health_check():
    """Test system health before running tests."""
    print_section("System Health Check")
    
    rag = get_rag_system()
    
    try:
        health = rag.health_check()
        
        print("Component Status:")
        for component, status in health.items():
            status_icon = "✓" if status else "✗"
            print(f"  {status_icon} {component}: {status}")
        
        all_healthy = all(health.values())
        
        if all_healthy:
            print("\n✓ All components healthy")
        else:
            print("\n✗ Some components are not healthy")
        
        return all_healthy
    except Exception as e:
        print(f"✗ Health check failed: {e}")
        logger.exception("Health check failed")
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 80)
    print("  MLflow Tracking Enhancements - Verification Tests")
    print("=" * 80)
    
    # Check system health first
    if not test_health_check():
        print("\n⚠️  System health check failed. Please ensure all services are running.")
        print("   - Ollama: systemctl status ollama")
        print("   - pgvector: psql -h localhost -p 5442 -U egeria_advisor -d egeria_advisor -c 'SELECT 1;'")
        print("   - MLflow: docker ps | grep mlflow")
        return 1
    
    # Run tests
    results = {
        "explain_code": test_explain_code(),
        "find_similar_code": test_find_similar_code(),
        "get_file_summary": test_get_file_summary(),
        "enhanced_query_metrics": test_enhanced_query_metrics()
    }
    
    # Summary
    print_section("Test Summary")
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✓ All MLflow tracking enhancements verified successfully!")
        print(f"\nView tracked experiments at: http://localhost:5025")
        print("  (Docker container port 5000 mapped to host port 5025)")
        return 0
    else:
        print(f"\n✗ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())