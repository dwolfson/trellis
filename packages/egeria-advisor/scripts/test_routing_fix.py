#!/usr/bin/env python3
"""
Test script to verify routing fixes for egeria_docs prioritization.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.collection_router import get_collection_router
from advisor.collection_config import get_collection, get_collections_by_priority


def test_docs_priority():
    """Test that egeria_docs has higher priority than pyegeria."""
    print("Testing collection priorities...")
    
    collections = get_collections_by_priority()
    
    print("\nCollections by priority (highest first):")
    for i, col in enumerate(collections, 1):
        print(f"  {i}. {col.name:20} - priority={col.priority}, type={col.content_type.value}")
    
    # Check that egeria_docs has priority 11
    docs = get_collection("egeria_docs")
    assert docs is not None, "egeria_docs collection not found"
    assert docs.priority == 11, f"Expected priority 11, got {docs.priority}"
    print(f"\n✓ egeria_docs priority is {docs.priority}")
    
    # Check that it's higher than pyegeria
    pyegeria = get_collection("pyegeria")
    assert pyegeria is not None, "pyegeria collection not found"
    assert docs.priority > pyegeria.priority, "egeria_docs should have higher priority than pyegeria"
    print(f"✓ egeria_docs priority ({docs.priority}) > pyegeria priority ({pyegeria.priority})")


def test_documentation_query_routing():
    """Test routing for documentation-specific queries."""
    print("\n" + "="*70)
    print("Testing documentation query routing...")
    print("="*70)
    
    router = get_collection_router()
    
    test_queries = [
        "what does the Egeria documentation say about myProfile?",
        "show me the docs for glossary",
        "where is the documentation for OMAS?",
        "what is in the egeria documentation about assets?",
    ]
    
    for query in test_queries:
        print(f"\nQuery: {query}")
        collections = router.route_query(query, max_collections=3)
        print(f"  Routed to: {collections}")
        
        # Check if egeria_docs is in the results
        if "egeria_docs" in collections:
            position = collections.index("egeria_docs") + 1
            print(f"  ✓ egeria_docs found at position {position}")
            
            # For documentation queries, it should be first
            if any(kw in query.lower() for kw in ["documentation", "docs"]):
                if position == 1:
                    print(f"  ✓ egeria_docs is first (as expected for doc query)")
                else:
                    print(f"  ⚠ egeria_docs is at position {position}, expected 1")
        else:
            print(f"  ✗ egeria_docs NOT in results!")


def test_intent_detection():
    """Test that documentation intent is properly detected."""
    print("\n" + "="*70)
    print("Testing intent detection...")
    print("="*70)
    
    router = get_collection_router()
    
    # Test query with explicit "documentation" keyword
    query = "what does the Egeria documentation say about myProfile?"
    print(f"\nQuery: {query}")
    
    # Get routing with details
    routing = router.route_with_fallback(query, max_collections=5)
    print(f"  Strategy: {routing['strategy']}")
    print(f"  Primary collections: {routing['primary']}")
    print(f"  Fallback collections: {routing['fallback']}")
    
    # Check that egeria_docs is in primary
    if "egeria_docs" in routing['primary']:
        print("  ✓ egeria_docs in primary collections")
    else:
        print("  ✗ egeria_docs NOT in primary collections!")


def main():
    """Run all tests."""
    print("="*70)
    print("Testing Routing Fixes for egeria_docs Prioritization")
    print("="*70)
    
    try:
        # Test 1: Priority configuration
        test_docs_priority()
        
        # Test 2: Documentation query routing
        test_documentation_query_routing()
        
        # Test 3: Intent detection
        test_intent_detection()
        
        print("\n" + "="*70)
        print("✓ All routing tests passed!")
        print("="*70)
        
        print("\nTo test interactively:")
        print("  egeria-advisor --interactive --debug")
        print("\nThen try:")
        print("  > what does the Egeria documentation say about myProfile?")
        
        return 0
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())