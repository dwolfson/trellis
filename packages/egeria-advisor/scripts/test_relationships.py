#!/usr/bin/env python3
"""
Test script for relationship queries.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.relationships import get_relationship_query_handler
from loguru import logger


def test_relationship_handler():
    """Test relationship query handler."""
    logger.info("=" * 60)
    logger.info("Testing Relationship Query Handler")
    logger.info("=" * 60)
    
    handler = get_relationship_query_handler()
    
    # Test queries
    test_queries = [
        "What does GlossaryManager call?",
        "What calls create_glossary?",
        "What does AssetCatalog import?",
        "What methods belong to GlossaryManager?",
    ]
    
    for query in test_queries:
        logger.info(f"\nQuery: {query}")
        response = handler.answer_relationship_query(query)
        logger.info(f"Answer:\n{response}\n")
    
    logger.success("\n✓ All relationship query tests completed!")


if __name__ == "__main__":
    test_relationship_handler()