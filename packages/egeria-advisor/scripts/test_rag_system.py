#!/usr/bin/env python3
"""
Test script for the RAG system.

This script tests the complete RAG pipeline including:
- Query processing
- Vector retrieval
- Context building
- LLM response generation
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import get_rag_system
from loguru import logger


def test_health_check():
    """Test system health."""
    logger.info("=" * 60)
    logger.info("Testing RAG System Health")
    logger.info("=" * 60)

    rag = get_rag_system()
    health = rag.health_check()

    logger.info(f"LLM Available: {health['llm_available']}")
    logger.info(f"Vector Store Connected: {health['vector_store_connected']}")
    logger.info(f"Embedding Model Loaded: {health['embedding_model_loaded']}")

    all_healthy = all(health.values())
    if all_healthy:
        logger.success("✓ All systems healthy!")
    else:
        logger.warning("⚠ Some systems not ready")

    return all_healthy


def test_simple_query():
    """Test a simple query."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Simple Query")
    logger.info("=" * 60)

    rag = get_rag_system()

    query = "What is the EgeriaClient class used for?"
    logger.info(f"Query: {query}")

    try:
        result = rag.query(query, track_metrics=True)

        logger.info(f"\nQuery Type: {result['query_type']}")
        logger.info(f"Number of Sources: {result['num_sources']}")
        logger.info(f"\nResponse:\n{result['response']}")

        if result['sources']:
            logger.info("\nTop Sources:")
            for i, source in enumerate(result['sources'][:3], 1):
                # Handle both dictionary and SearchResult object
                file_path = getattr(source, 'metadata', {}).get('file_path', 'unknown') if hasattr(source, 'metadata') else source.get('file_path', 'unknown')
                score = getattr(source, 'score', 0) if hasattr(source, 'score') else source.get('score', 0)

                logger.info(f"  {i}. {file_path} (score: {score:.3f})")

        logger.success("✓ Query completed successfully!")
        return True

    except Exception as e:
        logger.error(f"✗ Query failed: {e}")
        return False


def test_code_search():
    """Test code search functionality."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Code Search")
    logger.info("=" * 60)

    rag = get_rag_system()

    query = "Find functions that handle API connections"
    logger.info(f"Query: {query}")

    try:
        result = rag.query(query, track_metrics=False)

        logger.info(f"\nQuery Type: {result['query_type']}")
        logger.info(f"Number of Sources: {result['num_sources']}")
        logger.info(f"\nResponse (first 500 chars):\n{result['response'][:500]}...")

        logger.success("✓ Code search completed!")
        return True

    except Exception as e:
        logger.error(f"✗ Code search failed: {e}")
        return False


def test_explanation():
    """Test code explanation."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Code Explanation")
    logger.info("=" * 60)

    rag = get_rag_system()

    code = """
def connect_to_server(url, username, password):
    client = EgeriaClient(url)
    client.authenticate(username, password)
    return client
"""

    logger.info(f"Code to explain:\n{code}")

    try:
        explanation = rag.explain_code(code)
        logger.info(f"\nExplanation:\n{explanation}")

        logger.success("✓ Code explanation completed!")
        return True

    except Exception as e:
        logger.error(f"✗ Code explanation failed: {e}")
        return False


def test_similar_code():
    """Test finding similar code."""
    logger.info("\n" + "=" * 60)
    logger.info("Testing Similar Code Search")
    logger.info("=" * 60)

    rag = get_rag_system()

    code = "def get_asset_by_guid(guid):"
    logger.info(f"Finding code similar to: {code}")

    try:
        similar = rag.find_similar_code(code, top_k=3)

        logger.info(f"\nFound {len(similar)} similar code snippets:")
        for i, item in enumerate(similar, 1):
            # Handle both dictionary and SearchResult object
            if hasattr(item, 'metadata'):
                name = item.metadata.get('name', 'unnamed')
                file_path = item.metadata.get('file_path', 'unknown')
                score = item.score
                code_preview = item.text[:100]
            else:
                name = item.get('name', 'unnamed')
                file_path = item.get('file_path', 'unknown')
                score = item.get('score', 0)
                code_preview = item.get('code', '')[:100]

            logger.info(f"\n{i}. {name} ({file_path})")
            logger.info(f"   Score: {score:.3f}")
            logger.info(f"   Code preview: {code_preview}...")

        logger.success("✓ Similar code search completed!")
        return True

    except Exception as e:
        logger.error(f"✗ Similar code search failed: {e}")
        return False


def run_all_tests():
    """Run all tests."""
    logger.info("\n" + "=" * 80)
    logger.info("RAG SYSTEM TEST SUITE")
    logger.info("=" * 80)

    tests = [
        ("Health Check", test_health_check),
        ("Simple Query", test_simple_query),
        ("Code Search", test_code_search),
        ("Code Explanation", test_explanation),
        ("Similar Code Search", test_similar_code),
    ]

    results = {}
    for name, test_func in tests:
        try:
            results[name] = test_func()
        except Exception as e:
            logger.error(f"Test '{name}' crashed: {e}")
            results[name] = False

    # Summary
    logger.info("\n" + "=" * 80)
    logger.info("TEST SUMMARY")
    logger.info("=" * 80)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status}: {name}")

    logger.info(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        logger.success("\n🎉 All tests passed!")
        return 0
    else:
        logger.warning(f"\n⚠ {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    exit_code = run_all_tests()
    sys.exit(exit_code)
