#!/usr/bin/env python3
"""
Test enhanced relationship queries.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.enhanced_relationships import get_enhanced_relationship_handler
from loguru import logger


def main():
    """Test enhanced relationship queries."""
    logger.info("=" * 60)
    logger.info("Testing Enhanced Relationship Queries")
    logger.info("=" * 60)
    
    handler = get_enhanced_relationship_handler()
    
    # Test queries
    test_queries = [
        "How many modules are there?",
        "How many classes are there?",
        "How many functions are there?",
        "What does pyegeria import?",
        "What are the most dependent modules?",
        "Are there any circular imports?",
        "What classes inherit from EgeriaClient?",
        "What does GlossaryManager call?",
        "What calls get_glossary?",
    ]
    
    for query in test_queries:
        logger.info(f"\n{'='*60}")
        logger.info(f"Query: {query}")
        logger.info(f"{'='*60}")
        
        response = handler.answer_query(query)
        print(response)
        print()


if __name__ == "__main__":
    main()