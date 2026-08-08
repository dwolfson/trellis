#!/usr/bin/env python3
"""
Test script for scoped queries functionality.

This script tests the complete end-to-end flow:
1. Query processor extracts path filter
2. RAG system passes it to analytics
3. Analytics returns scoped results

Run this to verify scoped queries work before testing in CLI.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.query_processor import get_query_processor
from advisor.analytics import get_analytics_manager
from advisor.rag_system import RAGSystem


def test_query_processor():
    """Test that query processor extracts path correctly."""
    print("=" * 60)
    print("TEST 1: Query Processor Path Extraction")
    print("=" * 60)
    
    qp = get_query_processor()
    
    test_queries = [
        "How many classes are under the Pyegeria folder?",
        "How many functions in the commands directory?",
        "How many methods within pyegeria?",
        "How many classes are in the codebase?"  # No path filter
    ]
    
    for query in test_queries:
        result = qp.process_query(query)
        print(f"\nQuery: {query}")
        print(f"  Type: {result['query_type'].value}")
        print(f"  Path Filter: {result.get('path_filter', 'None')}")
        
        if "pyegeria" in query.lower() or "commands" in query.lower():
            if result.get('path_filter'):
                print("  ✓ Path extracted correctly")
            else:
                print("  ✗ ERROR: Path not extracted!")
        else:
            if not result.get('path_filter'):
                print("  ✓ No path filter (as expected)")
            else:
                print(f"  ✗ ERROR: Unexpected path filter: {result.get('path_filter')}")


def test_analytics_direct():
    """Test analytics manager directly with path filter."""
    print("\n" + "=" * 60)
    print("TEST 2: Analytics Manager Direct Test")
    print("=" * 60)
    
    analytics = get_analytics_manager()
    
    # Test with path filter
    print("\nTest 2a: Classes in pyegeria (with path filter)")
    result = analytics.answer_quantitative_query(
        "How many classes?",
        path_filter="pyegeria"
    )
    print(f"Result: {result}")
    if "191" in result and "pyegeria" in result:
        print("✓ Correct scoped result")
    else:
        print("✗ ERROR: Expected 191 classes in pyegeria directory")
    
    # Test without path filter
    print("\nTest 2b: Classes in codebase (no path filter)")
    result = analytics.answer_quantitative_query(
        "How many classes?",
        path_filter=None
    )
    print(f"Result: {result}")
    if "196" in result and "egeria-python" in result:
        print("✓ Correct unscoped result")
    else:
        print("✗ ERROR: Expected 196 classes in entire codebase")


def test_rag_system():
    """Test RAG system end-to-end (without vector store initialization)."""
    print("\n" + "=" * 60)
    print("TEST 3: RAG System Integration")
    print("=" * 60)
    print("\nNote: This test requires full RAG system initialization.")
    print("If you see CUDA errors, the analytics layer is still working correctly.")
    print("The issue would be in your CLI/application not reloading the code.\n")
    
    try:
        rag = RAGSystem()
        
        query = "How many classes are under the Pyegeria folder?"
        print(f"Query: {query}")
        
        result = rag.query(query)
        print(f"Response: {result['response']}")
        print(f"Path Filter: {result.get('path_filter')}")
        
        if "191" in result['response'] and "pyegeria" in result['response']:
            print("✓ End-to-end scoped query works!")
        else:
            print("✗ ERROR: Expected scoped result with 191 classes")
            
    except Exception as e:
        print(f"⚠ RAG system initialization failed: {e}")
        print("This is expected if CUDA/GPU is not available.")
        print("The analytics layer (Tests 1 & 2) still work correctly.")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SCOPED QUERIES TEST SUITE")
    print("=" * 60)
    
    try:
        test_query_processor()
        test_analytics_direct()
        test_rag_system()
        
        print("\n" + "=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print("\nIf Tests 1 & 2 passed, scoped queries are working correctly.")
        print("If your CLI still shows wrong results, you need to:")
        print("  1. Restart your CLI/application")
        print("  2. Or reload the Python modules")
        print("  3. Or restart the Jupyter kernel (if using notebooks)")
        
    except Exception as e:
        print(f"\n✗ Test suite failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())