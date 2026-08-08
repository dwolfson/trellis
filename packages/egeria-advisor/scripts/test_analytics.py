#!/usr/bin/env python3
"""
Test script for analytics functionality.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.analytics import get_analytics_manager
from loguru import logger


def test_analytics_manager():
    """Test the analytics manager."""
    logger.info("=" * 60)
    logger.info("Testing Analytics Manager")
    logger.info("=" * 60)
    
    analytics = get_analytics_manager()
    
    # Test individual queries
    logger.info(f"\nTotal classes: {analytics.get_total_classes()}")
    logger.info(f"Total functions: {analytics.get_total_functions()}")
    logger.info(f"Total methods: {analytics.get_total_methods()}")
    logger.info(f"Total files: {analytics.get_total_files()}")
    logger.info(f"Total lines of code: {analytics.get_total_lines_of_code():,}")
    
    # Test quantitative queries
    logger.info("\n" + "=" * 60)
    logger.info("Testing Quantitative Queries")
    logger.info("=" * 60)
    
    queries = [
        "How many classes are there?",
        "How many functions are in the codebase?",
        "What is the total lines of code?",
        "How many files are there?",
        "How many CLI commands are available?",
        "What CLI commands are there?",
        "How is the codebase structured and what are the relationships?",
        "How many modules and packages are in pyegeria?",
        "Show me a summary of the codebase",
    ]
    
    for query in queries:
        logger.info(f"\nQuery: {query}")
        answer = analytics.answer_quantitative_query(query)
        logger.info(f"Answer:\n{answer}")
    
    logger.success("\n✓ All analytics tests passed!")


if __name__ == "__main__":
    test_analytics_manager()