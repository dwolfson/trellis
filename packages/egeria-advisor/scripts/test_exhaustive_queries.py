#!/usr/bin/env python3
"""
Test exhaustive query detection and complete method listing.

This script tests that queries like "how many methods" return ALL methods,
not just semantically relevant ones.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.pyegeria_agent import PyEgeriaAgent
from loguru import logger


def test_exhaustive_queries():
    """Test that exhaustive queries return complete lists."""
    
    logger.info("=" * 80)
    logger.info("TESTING EXHAUSTIVE QUERY DETECTION")
    logger.info("=" * 80)
    
    agent = PyEgeriaAgent()
    
    # Test queries that should return ALL methods
    test_cases = [
        {
            'query': 'how many methods does CollectionManager have?',
            'expected_count': 83,
            'description': 'Count query'
        },
        {
            'query': 'what methods are in CollectionManager?',
            'expected_count': 83,
            'description': 'List query'
        },
        {
            'query': 'list all methods in CollectionManager',
            'expected_count': 83,
            'description': 'Explicit "list all"'
        },
        {
            'query': 'show me all the methods in GlossaryManager',
            'expected_count': None,  # Don't know exact count, just verify > 10
            'description': 'Different class'
        }
    ]
    
    results = []
    
    for test in test_cases:
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Test: {test['description']}")
        logger.info(f"Query: {test['query']}")
        logger.info(f"{'=' * 60}")
        
        # Check if query is detected as exhaustive
        is_exhaustive = agent.is_exhaustive_query(test['query'])
        logger.info(f"Detected as exhaustive: {is_exhaustive}")
        
        # Get answer
        response = agent.answer(test['query'])
        
        # Count methods in response
        answer = response.get('answer', '')
        sources = response.get('sources', [])
        
        # Try to extract method count from answer
        import re
        count_match = re.search(r'(\d+)\s+methods?', answer.lower())
        reported_count = int(count_match.group(1)) if count_match else None
        
        logger.info(f"\nResponse preview: {answer[:200]}...")
        logger.info(f"Reported method count: {reported_count}")
        logger.info(f"Number of sources: {len(sources)}")
        
        # Verify
        if test['expected_count']:
            if reported_count == test['expected_count']:
                logger.info(f"✓ PASS: Correctly reported {reported_count} methods")
                results.append(('PASS', test['description']))
            else:
                logger.error(f"✗ FAIL: Expected {test['expected_count']}, got {reported_count}")
                results.append(('FAIL', test['description']))
        else:
            if reported_count and reported_count > 10:
                logger.info(f"✓ PASS: Reported {reported_count} methods (> 10)")
                results.append(('PASS', test['description']))
            else:
                logger.warning(f"⚠ UNCERTAIN: Reported {reported_count} methods")
                results.append(('UNCERTAIN', test['description']))
    
    # Summary
    logger.info(f"\n{'=' * 80}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'=' * 80}")
    
    for status, description in results:
        symbol = '✓' if status == 'PASS' else ('✗' if status == 'FAIL' else '⚠')
        logger.info(f"{symbol} {status}: {description}")
    
    passed = sum(1 for s, _ in results if s == 'PASS')
    total = len(results)
    logger.info(f"\nPassed: {passed}/{total}")
    
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(test_exhaustive_queries())