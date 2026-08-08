"""
Test vector search functionality in pgvector.

This script tests that we can successfully search for similar code elements
using semantic similarity.
"""

from advisor.vector_store import get_vector_store
from loguru import logger
import sys


def test_search(query: str, collection: str = "code_elements", top_k: int = 5):
    """Test vector search with a query."""
    logger.info(f"Testing search in '{collection}' collection")
    logger.info(f"Query: {query}")
    logger.info("=" * 80)
    
    vector_store = get_vector_store()
    
    try:
        # Perform search
        results = vector_store.search(
            collection_name=collection,
            query_text=query,
            top_k=top_k
        )
        
        logger.info(f"Found {len(results)} results:\n")
        
        for i, result in enumerate(results, 1):
            print(f"\n{i}. Score: {result.score:.4f}")
            print(f"   ID: {result.id}")
            print(f"   Name: {result.metadata.get('name', 'N/A')}")
            print(f"   Type: {result.metadata.get('type', 'N/A')}")
            print(f"   File: {result.metadata.get('file', 'N/A')}")
            print(f"   Text preview: {result.text[:200]}...")
        
        return True
        
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return False
    finally:
        vector_store.disconnect()


def main():
    """Run test searches."""
    test_queries = [
        "create a glossary term",
        "connect to Egeria server",
        "get asset information",
        "search for metadata",
        "configure OMAG server"
    ]
    
    logger.info("=" * 80)
    logger.info("Vector Search Test")
    logger.info("=" * 80)
    
    success_count = 0
    
    for query in test_queries:
        print("\n" + "=" * 80)
        if test_search(query):
            success_count += 1
        print("=" * 80)
    
    print(f"\n\n{'=' * 80}")
    print(f"Test Summary: {success_count}/{len(test_queries)} queries successful")
    print("=" * 80)
    
    return 0 if success_count == len(test_queries) else 1


if __name__ == "__main__":
    sys.exit(main())