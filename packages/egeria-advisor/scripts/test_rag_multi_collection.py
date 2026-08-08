#!/usr/bin/env python3
"""
End-to-end test for RAG system with multi-collection search.

Tests the complete flow from query to context building using
the integrated multi-collection search system.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.rag_retrieval import RAGRetriever


def test_basic_retrieval():
    """Test basic retrieval with multi-collection search."""
    print("\n" + "="*80)
    print("TEST 1: Basic Retrieval with Multi-Collection Search")
    print("="*80)
    
    # Create retriever with multi-collection enabled
    retriever = RAGRetriever(use_multi_collection=True)
    
    # Test query
    query = "How do I use pyegeria to connect to a server?"
    print(f"\nQuery: {query}")
    
    # Retrieve results
    results = retriever.retrieve(query, top_k=5)
    
    print(f"\nResults found: {len(results)}")
    
    if results:
        print("\nTop 3 results:")
        for i, result in enumerate(results[:3], 1):
            print(f"\n{i}. Score: {result.score:.4f}")
            print(f"   File: {result.metadata.get('file_path', 'unknown')}")
            print(f"   Collection: {result.metadata.get('_collection', 'unknown')}")
            print(f"   Text preview: {result.text[:100]}...")
    
    status = "✓ PASS" if len(results) > 0 else "✗ FAIL"
    print(f"\nStatus: {status}")
    
    return len(results) > 0


def test_context_building():
    """Test context building from multi-collection results."""
    print("\n" + "="*80)
    print("TEST 2: Context Building")
    print("="*80)
    
    retriever = RAGRetriever(use_multi_collection=True)
    
    query = "What CLI commands are available in pyegeria?"
    print(f"\nQuery: {query}")
    
    # Retrieve and build context
    context, sources = retriever.retrieve_and_build_context(
        query=query,
        top_k=3,
        format_style="detailed"
    )
    
    print(f"\nContext length: {len(context)} characters")
    print(f"Sources: {len(sources)}")
    
    if sources:
        print("\nSource collections:")
        collections = set(s.get('file_path', 'unknown').split('/')[0] for s in sources)
        for collection in collections:
            print(f"  - {collection}")
    
    print("\nContext preview (first 500 chars):")
    print(context[:500])
    print("...")
    
    status = "✓ PASS" if len(context) > 0 and len(sources) > 0 else "✗ FAIL"
    print(f"\nStatus: {status}")
    
    return len(context) > 0


def test_specific_collection_queries():
    """Test queries that should route to specific collections."""
    print("\n" + "="*80)
    print("TEST 3: Specific Collection Routing")
    print("="*80)
    
    retriever = RAGRetriever(use_multi_collection=True)
    
    test_cases = [
        ("pyegeria widget configuration", "pyegeria"),
        ("CLI command options", "pyegeria_cli"),
        ("data engine proxy setup", "pyegeria_drE"),
    ]
    
    passed = 0
    for query, expected_collection in test_cases:
        print(f"\nQuery: {query}")
        print(f"Expected collection: {expected_collection}")
        
        results = retriever.retrieve(query, top_k=3)
        
        if results:
            # Check if results are from expected collection
            collections = set(r.metadata.get('_collection', 'unknown') for r in results)
            print(f"Collections found: {collections}")
            
            if expected_collection in collections:
                print("✓ Routed correctly")
                passed += 1
            else:
                print("✗ Routing mismatch")
        else:
            print("✗ No results found")
    
    status = "✓ PASS" if passed == len(test_cases) else f"⚠ PARTIAL ({passed}/{len(test_cases)})"
    print(f"\nOverall status: {status}")
    
    return passed == len(test_cases)


def test_fallback_behavior():
    """Test fallback to multiple collections for generic queries."""
    print("\n" + "="*80)
    print("TEST 4: Fallback Behavior")
    print("="*80)
    
    retriever = RAGRetriever(use_multi_collection=True)
    
    # Generic query that should search multiple collections
    query = "How to configure settings?"
    print(f"\nQuery: {query}")
    
    results = retriever.retrieve(query, top_k=5)
    
    print(f"\nResults found: {len(results)}")
    
    if results:
        # Check how many collections were searched
        collections = set(r.metadata.get('_collection', 'unknown') for r in results)
        print(f"Collections searched: {collections}")
        print(f"Number of collections: {len(collections)}")
        
        # Fallback should search multiple collections
        status = "✓ PASS" if len(collections) > 1 else "⚠ SINGLE COLLECTION"
    else:
        status = "✗ FAIL - No results"
    
    print(f"\nStatus: {status}")
    
    return len(results) > 0


def test_single_vs_multi_collection():
    """Compare single-collection vs multi-collection mode."""
    print("\n" + "="*80)
    print("TEST 5: Single vs Multi-Collection Comparison")
    print("="*80)
    
    query = "pyegeria server connection"
    print(f"\nQuery: {query}")
    
    # Test with multi-collection
    print("\n--- Multi-Collection Mode ---")
    retriever_multi = RAGRetriever(use_multi_collection=True)
    results_multi = retriever_multi.retrieve(query, top_k=5)
    print(f"Results: {len(results_multi)}")
    if results_multi:
        collections_multi = set(r.metadata.get('_collection', 'unknown') for r in results_multi)
        print(f"Collections: {collections_multi}")
        avg_score_multi = sum(r.score for r in results_multi) / len(results_multi)
        print(f"Average score: {avg_score_multi:.4f}")
    
    # Test with single-collection (if code_elements collection exists)
    print("\n--- Single-Collection Mode ---")
    try:
        retriever_single = RAGRetriever(use_multi_collection=False)
        results_single = retriever_single.retrieve(query, top_k=5)
        print(f"Results: {len(results_single)}")
        if results_single:
            avg_score_single = sum(r.score for r in results_single) / len(results_single)
            print(f"Average score: {avg_score_single:.4f}")
    except Exception as e:
        print(f"Single-collection mode not available: {e}")
        results_single = []
    
    print("\n--- Comparison ---")
    print(f"Multi-collection results: {len(results_multi)}")
    print(f"Single-collection results: {len(results_single)}")
    
    status = "✓ PASS" if len(results_multi) > 0 else "✗ FAIL"
    print(f"\nStatus: {status}")
    
    return len(results_multi) > 0


def main():
    """Run all end-to-end tests."""
    logger.info("Starting RAG multi-collection end-to-end tests")
    
    try:
        results = []
        
        results.append(("Basic Retrieval", test_basic_retrieval()))
        results.append(("Context Building", test_context_building()))
        results.append(("Specific Routing", test_specific_collection_queries()))
        results.append(("Fallback Behavior", test_fallback_behavior()))
        results.append(("Single vs Multi", test_single_vs_multi_collection()))
        
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        
        passed = sum(1 for _, result in results if result)
        total = len(results)
        
        for test_name, result in results:
            status = "✓ PASS" if result else "✗ FAIL"
            print(f"{status} - {test_name}")
        
        print(f"\nTotal: {passed}/{total} tests passed ({passed/total*100:.0f}%)")
        
        if passed == total:
            print("\n🎉 ALL TESTS PASSED!")
            return 0
        else:
            print(f"\n⚠ {total - passed} test(s) failed")
            return 1
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())