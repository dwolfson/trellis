#!/usr/bin/env python3
"""
Test enhanced analytics queries.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.enhanced_analytics import get_enhanced_analytics_manager
from loguru import logger


def main():
    """Test enhanced analytics queries."""
    logger.info("=" * 60)
    logger.info("Testing Enhanced Analytics Queries")
    logger.info("=" * 60)
    
    manager = get_enhanced_analytics_manager()
    
    # Test queries
    test_queries = [
        "How many files are there?",
        "How many lines of code?",
        "What is the average complexity?",
        "What is the maintainability?",
        "What are the estimated bugs?",
        "What are the largest folders?",
        "What are the most complex folders?",
        "What folders need attention?",
        "What are the metrics for pyegeria?",
        "What are the metrics for tests?",
    ]
    
    for query in test_queries:
        logger.info(f"\n{'='*60}")
        logger.info(f"Query: {query}")
        logger.info(f"{'='*60}")
        
        response = manager.answer_query(query)
        print(response)
        print()


if __name__ == "__main__":
    main()