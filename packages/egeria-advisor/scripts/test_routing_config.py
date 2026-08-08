#!/usr/bin/env python3
"""
Test script for data-driven routing configuration.

This script tests:
1. Loading routing configuration from YAML
2. Query pattern matching
3. Collection domain term routing
4. Configuration reload functionality
"""

from advisor.query_patterns import (
    get_patterns_by_priority,
    get_domain_terms,
    get_collection_domain_terms,
    get_intent_keywords,
    reload_config,
    PatternPriority,
    QueryType
)
from advisor.collection_config import get_collection, get_enabled_collections
from advisor.collection_router import get_collection_router


def test_pattern_loading():
    """Test that query patterns are loaded from config."""
    print("\n=== Testing Query Pattern Loading ===")
    
    patterns = get_patterns_by_priority()
    
    print(f"✓ Loaded {len(patterns)} priority levels")
    
    for priority, types_dict in patterns.items():
        print(f"\n{priority.name} Priority:")
        for query_type, pattern_list in types_dict.items():
            print(f"  {query_type.name}: {len(pattern_list)} patterns")
            if pattern_list:
                print(f"    Example: '{pattern_list[0]}'")


def test_domain_terms():
    """Test that domain terms are loaded from config."""
    print("\n=== Testing Domain Terms Loading ===")
    
    # Test general domain terms
    all_terms = get_domain_terms()
    print(f"✓ Loaded {len(all_terms)} total domain terms")
    
    # Test category-specific terms
    categories = ["egeria_concepts", "pyegeria_code", "deployment"]
    for category in categories:
        terms = get_domain_terms(category)
        print(f"  {category}: {len(terms)} terms")
        if terms:
            print(f"    Examples: {', '.join(terms[:3])}")


def test_collection_domain_terms():
    """Test that collection-specific domain terms are loaded."""
    print("\n=== Testing Collection Domain Terms ===")
    
    collections = ["pyegeria", "pyegeria_cli", "egeria_java", "egeria_docs"]
    
    for coll_name in collections:
        terms = get_collection_domain_terms(coll_name)
        print(f"  {coll_name}: {len(terms)} terms")
        if terms:
            print(f"    Examples: {', '.join(terms[:3])}")


def test_intent_keywords():
    """Test that intent keywords are loaded."""
    print("\n=== Testing Intent Keywords ===")
    
    intents = get_intent_keywords()
    print(f"✓ Loaded {len(intents)} intent categories")
    
    for intent, keywords in intents.items():
        print(f"  {intent}: {keywords}")


def test_collection_routing():
    """Test actual query routing with loaded config."""
    print("\n=== Testing Query Routing ===")
    
    router = get_collection_router()
    
    test_queries = [
        "Show me the documentation for Asset Manager",
        "How to use pyegeria to create a glossary",
        "Java OMAS implementation",
        "hey-egeria commands for glossary management",
        "Jupyter notebook demo for lineage",
    ]
    
    for query in test_queries:
        collections = router.route_query(query, max_collections=3)
        print(f"\nQuery: '{query}'")
        print(f"  → Routes to: {collections}")


def test_config_reload():
    """Test configuration reload functionality."""
    print("\n=== Testing Configuration Reload ===")
    
    success = reload_config()
    if success:
        print("✓ Configuration reloaded successfully")
    else:
        print("✗ Configuration reload failed")


def test_collection_metadata():
    """Test that collections use config-loaded domain terms."""
    print("\n=== Testing Collection Metadata ===")
    
    collections = get_enabled_collections()
    print(f"✓ Found {len(collections)} enabled collections")
    
    for coll in collections[:3]:  # Show first 3
        print(f"\n{coll.name}:")
        print(f"  Priority: {coll.priority}")
        print(f"  Domain terms: {len(coll.domain_terms)}")
        print(f"  Examples: {', '.join(coll.domain_terms[:3])}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Data-Driven Routing Configuration")
    print("=" * 60)
    
    try:
        test_pattern_loading()
        test_domain_terms()
        test_collection_domain_terms()
        test_intent_keywords()
        test_collection_metadata()
        test_collection_routing()
        test_config_reload()
        
        print("\n" + "=" * 60)
        print("✓ All tests completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())