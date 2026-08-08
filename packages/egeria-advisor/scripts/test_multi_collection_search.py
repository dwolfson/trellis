#!/usr/bin/env python3
"""
Test multi-collection search functionality.

Tests the complete multi-collection search pipeline including:
- Query routing
- Collection searching
- Result merging and re-ranking
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from advisor.multi_collection_store import MultiCollectionStore, get_multi_collection_store
from advisor.collection_config import get_enabled_collections


def test_query_routing():
    """Test that queries are routed to appropriate collections."""
    print("\n" + "="*80)
    print("TEST 1: Query Routing")
    print("="*80)
    
    store = get_multi_collection_store()
    
    test_queries = [
        ("How do I use pyegeria widgets?", ["pyegeria"]),
        ("What CLI commands are available?", ["pyegeria_cli"]),
        ("How to use the data engine proxy?", ["pyegeria_drE"]),
        ("Tell me about pyegeria", ["pyegeria", "pyegeria_cli", "pyegeria_drE"]),
    ]
    
    for query, expected_collections in test_queries:
        print(f"\nQuery: {query}")
        result = store.search_with_routing(query, top_k=3)
        print(f"  Collections searched: {result.collections_searched}")
        print(f"  Expected: {expected_collections}")
        print(f"  Routing strategy: {result.routing_strategy}")
        print(f"  Results found: {len(result.results)}")
        
        # Check if at least one expected collection was searched
        found = any(col in result.collections_searched for col in expected_collections)
        status = "✓ PASS" if found else "✗ FAIL"
        print(f"  Status: {status}")


def test_result_merging():
    """Test that results from multiple collections are properly merged."""
    print("\n" + "="*80)
    print("TEST 2: Result Merging and Re-ranking")
    print("="*80)
    
    store = get_multi_collection_store()
    
    # Query that should match multiple collections
    query = "pyegeria configuration"
    print(f"\nQuery: {query}")
    
    result = store.search_with_routing(query, top_k=5, max_collections=3)
    
    print(f"\nCollections searched: {result.collections_searched}")
    print(f"Total results: {len(result.results)}")
    print(f"Routing strategy: {result.routing_strategy}")
    
    if result.results:
        print("\nTop 3 results:")
        for i, res in enumerate(result.results[:3], 1):
            print(f"\n{i}. Score: {res.score:.4f}")
            print(f"   Collection: {res.metadata.get('collection_name', 'unknown')}")
            print(f"   File: {res.metadata.get('file_path', 'unknown')}")
            print(f"   Text preview: {res.text[:100]}...")
    
    print(f"\nCollection scores:")
    for collection, score in result.collection_scores.items():
        print(f"  {collection}: {score:.4f}")


def test_fallback_strategy():
    """Test fallback to broader search when specific routing fails."""
    print("\n" + "="*80)
    print("TEST 3: Fallback Strategy")
    print("="*80)
    
    store = get_multi_collection_store()
    
    # Generic query that might not match specific domain terms
    query = "how to connect to server"
    print(f"\nQuery: {query}")
    
    result = store.search_with_fallback(query, top_k=5, min_results=3, max_collections=5)
    
    print(f"\nCollections searched: {result.collections_searched}")
    print(f"Routing strategy: {result.routing_strategy}")
    print(f"Results found: {len(result.results)}")
    
    if result.results:
        print("\nTop result:")
        res = result.results[0]
        print(f"  Score: {res.score:.4f}")
        print(f"  Collection: {res.metadata.get('collection_name', 'unknown')}")
        print(f"  File: {res.metadata.get('file_path', 'unknown')}")


def test_collection_quality_weighting():
    """Test that collection quality affects result ranking."""
    print("\n" + "="*80)
    print("TEST 4: Collection Quality Weighting")
    print("="*80)
    
    store = get_multi_collection_store()
    
    query = "pyegeria API"
    print(f"\nQuery: {query}")
    
    result = store.search_with_routing(query, top_k=10, max_collections=3)
    
    print(f"\nCollections searched: {result.collections_searched}")
    print(f"Total results: {len(result.results)}")
    
    # Group results by collection
    by_collection = {}
    for res in result.results:
        col = res.metadata.get('collection_name', 'unknown')
        if col not in by_collection:
            by_collection[col] = []
        by_collection[col].append(res)
    
    print("\nResults by collection:")
    for collection, results in by_collection.items():
        avg_score = sum(r.score for r in results) / len(results)
        print(f"  {collection}: {len(results)} results, avg score: {avg_score:.4f}")


def test_enabled_collections():
    """Test that only enabled collections are searched."""
    print("\n" + "="*80)
    print("TEST 5: Enabled Collections Only")
    print("="*80)
    
    enabled = get_enabled_collections()
    print(f"\nEnabled collections: {[c.name for c in enabled]}")
    
    store = get_multi_collection_store()
    
    # Try a query that might match disabled collections
    query = "Java code examples"
    print(f"\nQuery: {query}")
    
    result = store.search_with_routing(query, top_k=5)
    
    print(f"\nCollections searched: {result.collections_searched}")
    
    # Verify only enabled collections were searched
    all_enabled = all(col in [c.name for c in enabled] for col in result.collections_searched)
    status = "✓ PASS" if all_enabled else "✗ FAIL"
    print(f"Status: {status} - Only enabled collections searched")


def main():
    """Run all tests."""
    logger.info("Starting multi-collection search tests")
    
    try:
        test_query_routing()
        test_result_merging()
        test_fallback_strategy()
        test_collection_quality_weighting()
        test_enabled_collections()
        
        print("\n" + "="*80)
        print("ALL TESTS COMPLETED")
        print("="*80)
        
    except Exception as e:
        logger.error(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()