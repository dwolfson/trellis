#!/usr/bin/env python3
"""
Test script for CLI Command Agent integration.

Tests the integration of CLI Command Agent with the query routing system.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.cli_integration import CLIQueryRouter, get_cli_router
from loguru import logger

def main():
    """Test CLI integration."""
    
    logger.info("="*60)
    logger.info("Testing CLI Command Agent Integration")
    logger.info("="*60 + "\n")
    
    # Initialize router
    try:
        router = get_cli_router()
        logger.info("✓ CLI Query Router initialized\n")
    except Exception as e:
        logger.error(f"Failed to initialize router: {e}")
        return 1
    
    # Test queries
    test_cases = [
        # Should route to CLI agent
        ("How do I create a glossary?", True),
        ("What commands are available?", True),
        ("Show me monitoring commands", True),
        ("What parameters does list_assets take?", True),
        ("hey_egeria commands", True),
        ("dr_egeria usage", True),
        
        # Should NOT route to CLI agent
        ("What is an Asset in Egeria?", False),
        ("Explain metadata governance", False),
        ("Show me code examples", False),
    ]
    
    logger.info("Testing CLI Detection:")
    logger.info("="*60 + "\n")
    
    correct = 0
    total = len(test_cases)
    
    for query, should_route in test_cases:
        detected = router.should_use_cli_agent(query)
        status = "✓" if detected == should_route else "✗"
        result = "PASS" if detected == should_route else "FAIL"
        
        logger.info(f"{status} [{result}] Query: '{query}'")
        logger.info(f"   Expected: {should_route}, Got: {detected}\n")
        
        if detected == should_route:
            correct += 1
    
    # Summary
    logger.info("="*60)
    logger.info(f"Detection Accuracy: {correct}/{total} ({100*correct/total:.1f}%)")
    logger.info("="*60 + "\n")
    
    # Test actual routing
    logger.info("Testing Query Routing:")
    logger.info("="*60 + "\n")
    
    test_query = "How do I create a glossary?"
    logger.info(f"Query: {test_query}")
    
    try:
        response = router.route_query(test_query)
        logger.info(f"\n✓ Response received:")
        logger.info(f"  Agent: {response.get('agent', 'unknown')}")
        logger.info(f"  Confidence: {response.get('confidence', 0.0)}")
        logger.info(f"  Response length: {len(response.get('response', ''))}")
        logger.info(f"  Routed to: {response.get('routed_to', 'unknown')}")
        
        if response.get('response'):
            logger.info(f"\n  Response preview:")
            preview = response['response'][:200] + "..." if len(response['response']) > 200 else response['response']
            logger.info(f"  {preview}")
        
    except Exception as e:
        logger.error(f"✗ Routing failed: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    logger.info("\n" + "="*60)
    logger.info("Integration test complete!")
    logger.info("="*60)
    
    return 0 if correct == total else 1

if __name__ == "__main__":
    sys.exit(main())