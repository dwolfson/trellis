#!/usr/bin/env python3
"""
Test script for collection routing logic.

Tests the intelligent query routing system without requiring
actual pgvector collections to be populated.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.collection_router import get_collection_router
from advisor.collection_config import get_collection_summary, get_enabled_collections
from loguru import logger


def test_routing():
    """Test collection routing with various queries."""
    
    logger.info("=" * 60)
    logger.info("Testing Collection Routing Logic")
    logger.info("=" * 60)
    
    # Get router
    router = get_collection_router()
    
    # Show collection summary
    summary = get_collection_summary()
    logger.info(f"\nCollection Summary:")
    logger.info(f"  Total collections: {summary['total']}")
    logger.info(f"  Enabled: {summary['enabled']}")
    logger.info(f"  Phase 1 (Python): {summary['phase1']}")
    logger.info(f"  Phase 2 (Java/Docs/Workspaces): {summary['phase2']}")
    
    logger.info(f"\nEnabled Collections:")
    for name, info in summary['collections'].items():
        if info['enabled']:
            logger.info(f"  - {name}: priority={info['priority']}, type={info['content_type']}, lang={info['language']}")
    
    # Test queries
    test_queries = [
        # Python-specific
        ("How do I use pyegeria widgets?", ["pyegeria"]),
        ("What pyegeria commands are available?", ["pyegeria"]),
        ("Show me pyegeria examples", ["pyegeria"]),
        
        # CLI-specific
        ("What hey_egeria commands exist?", ["pyegeria_cli"]),
        ("How do I use the CLI?", ["pyegeria_cli"]),
        
        # Dr. Egeria-specific
        ("How does Dr. Egeria work?", ["pyegeria_drE"]),
        ("Markdown translation with dr egeria", ["pyegeria_drE"]),
        
        # General (should default to Python collections)
        ("What is Egeria?", None),  # Will use defaults
        ("Tell me about metadata", None),
        
        # Cross-domain (when Phase 2 enabled)
        ("How do I connect Python to Java?", None),
        ("Show me OMAS examples", None),
    ]
    
    logger.info("\n" + "=" * 60)
    logger.info("Testing Query Routing")
    logger.info("=" * 60)
    
    for query, expected in test_queries:
        logger.info(f"\nQuery: '{query}'")
        
        # Route query
        collections = router.route_query(query, max_collections=3)
        logger.info(f"  Routed to: {collections}")
        
        if expected:
            if collections[0] in expected:
                logger.info(f"  ✓ Correct (expected {expected})")
            else:
                logger.warning(f"  ✗ Unexpected (expected {expected})")
        else:
            logger.info(f"  ℹ No specific expectation (using defaults)")
        
        # Get routing with fallback
        routing = router.route_with_fallback(query, max_collections=5)
        logger.info(f"  Strategy: {routing['strategy']}")
        logger.info(f"  Primary: {routing['primary']}")
        if routing['fallback']:
            logger.info(f"  Fallback: {routing['fallback']}")
    
    # Test collection info
    logger.info("\n" + "=" * 60)
    logger.info("Collection Information")
    logger.info("=" * 60)
    
    for collection in get_enabled_collections():
        info = router.get_collection_info(collection.name)
        if info:
            logger.info(f"\n{info['name']}:")
            logger.info(f"  Description: {info['description']}")
            logger.info(f"  Type: {info['content_type']}")
            logger.info(f"  Language: {info['language']}")
            logger.info(f"  Priority: {info['priority']}")
            logger.info(f"  Domain terms: {', '.join(info['domain_terms'][:5])}...")
            logger.info(f"  Related: {', '.join(info['related_collections'])}")
    
    # Test routing summary
    logger.info("\n" + "=" * 60)
    logger.info("Routing Summary")
    logger.info("=" * 60)
    
    routing_summary = router.get_routing_summary()
    logger.info(f"Total collections: {routing_summary['total_collections']}")
    logger.info(f"Enabled: {', '.join(routing_summary['enabled_collections'])}")
    logger.info(f"Priority order: {', '.join(routing_summary['collections_by_priority'])}")
    logger.info(f"Domain categories: {', '.join(routing_summary['domain_categories'])}")
    
    logger.info("\n" + "=" * 60)
    logger.info("✓ Collection Routing Tests Complete")
    logger.info("=" * 60)


if __name__ == "__main__":
    test_routing()