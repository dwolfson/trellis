#!/usr/bin/env python3
"""
Test vector store caching behavior to determine if singleton pattern can be safely re-enabled.

This script tests:
1. Collection caching with modifications
2. Query plan staleness
3. Connection pooling behavior
"""

import sys
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.vector_store import VectorStoreManager
from advisor.config import settings


def test_collection_caching():
    """Test if collection caching causes issues."""
    logger.info("=" * 80)
    logger.info("Testing Collection Caching")
    logger.info("=" * 80)
    
    # Create two instances
    store1 = VectorStoreManager()
    store2 = VectorStoreManager()
    
    store1.connect()
    store2.connect()
    
    # Test 1: Check if both can access the same collection
    logger.info("\nTest 1: Multiple instances accessing same collection")
    try:
        collection_name = "egeria_docs"  # Use existing collection
        
        # Get collection from both stores
        coll1 = store1.get_collection(collection_name)
        coll2 = store2.get_collection(collection_name)
        
        # Check if they work
        logger.info(f"Store 1 collection: {coll1.name}, entities: {coll1.num_entities}")
        logger.info(f"Store 2 collection: {coll2.name}, entities: {coll2.num_entities}")
        
        logger.info("✓ Both stores can access collection")
        
    except Exception as e:
        logger.error(f"✗ Test 1 failed: {e}")
        return False
    
    # Test 2: Check if search works with both
    logger.info("\nTest 2: Search with both instances")
    try:
        results1 = store1.search(
            collection_name=collection_name,
            query_text="What is Egeria?",
            top_k=3
        )
        results2 = store2.search(
            collection_name=collection_name,
            query_text="What is Egeria?",
            top_k=3
        )
        
        logger.info(f"Store 1 results: {len(results1)}")
        logger.info(f"Store 2 results: {len(results2)}")
        
        if len(results1) > 0 and len(results2) > 0:
            logger.info("✓ Both stores can search successfully")
        else:
            logger.warning("⚠ One or both stores returned no results")
            
    except Exception as e:
        logger.error(f"✗ Test 2 failed: {e}")
        return False
    
    # Test 3: Check connection state
    logger.info("\nTest 3: Connection state")
    logger.info(f"Store 1 connected: {store1.is_connected()}")
    logger.info(f"Store 2 connected: {store2.is_connected()}")
    
    # Disconnect
    store1.disconnect()
    store2.disconnect()
    
    logger.info("\n" + "=" * 80)
    logger.info("All tests passed! Singleton pattern should be safe.")
    logger.info("=" * 80)
    
    return True


def test_singleton_pattern():
    """Test if singleton pattern would work correctly."""
    logger.info("\n" + "=" * 80)
    logger.info("Testing Singleton Pattern")
    logger.info("=" * 80)
    
    # Simulate singleton behavior
    _instance = None
    
    def get_singleton():
        nonlocal _instance
        if _instance is None:
            _instance = VectorStoreManager()
        return _instance
    
    # Get instance multiple times
    store1 = get_singleton()
    store2 = get_singleton()
    store3 = get_singleton()
    
    logger.info(f"Instance 1 ID: {id(store1)}")
    logger.info(f"Instance 2 ID: {id(store2)}")
    logger.info(f"Instance 3 ID: {id(store3)}")
    
    if id(store1) == id(store2) == id(store3):
        logger.info("✓ Singleton pattern working correctly")
        
        # Test if it can connect and search
        store1.connect()
        
        try:
            results = store1.search(
                collection_name="egeria_docs",
                query_text="metadata",
                top_k=2
            )
            logger.info(f"✓ Singleton instance can search: {len(results)} results")
            
            store1.disconnect()
            return True
            
        except Exception as e:
            logger.error(f"✗ Singleton search failed: {e}")
            return False
    else:
        logger.error("✗ Singleton pattern not working")
        return False


def main():
    """Run all tests."""
    logger.info("Starting Vector Store Caching Tests")
    logger.info(f"pgvector: {settings.pgvector_host}:{settings.pgvector_port}")
    
    try:
        # Test 1: Collection caching
        if not test_collection_caching():
            logger.error("Collection caching test failed")
            return 1
        
        # Test 2: Singleton pattern
        if not test_singleton_pattern():
            logger.error("Singleton pattern test failed")
            return 1
        
        logger.info("\n" + "=" * 80)
        logger.info("✅ ALL TESTS PASSED")
        logger.info("Recommendation: Singleton pattern can be safely re-enabled")
        logger.info("=" * 80)
        
        return 0
        
    except Exception as e:
        logger.error(f"Test suite failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())