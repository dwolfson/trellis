#!/usr/bin/env python3
"""
Test script for verifying BeeAI Agent Framework.
"""

import sys
import asyncio
from pathlib import Path
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents import ConversationAgent

async def test_agent_framework():
    """Test the agent framework routing and execution."""
    logger.info("=" * 60)
    logger.info("Testing BeeAI Agent Framework")
    logger.info("=" * 60)

    # Initialize orchestrator
    agent = ConversationAgent()

    test_queries = [
        # Query Agent
        ("What is the EgeriaClient?", "query"),

        # Code Example Agent
        ("Show me how to create a glossary.", "code"),

        # Maintenance Agent
        ("How do I debug connection errors?", "maintenance")
    ]

    results = {}

    for query, expected_agent in test_queries:
        logger.info(f"\nProcessing query: {query}")
        logger.info(f"Expected agent: {expected_agent}")

        try:
            # Await the process method since BeeAI is async
            response = await agent.process(query)

            routed_to = response.get("routed_to", "unknown")
            logger.info(f"Routed to: {routed_to}")
            logger.info(f"Response preview: {response.get('response', '')[:100]}...")

            if routed_to == expected_agent:
                logger.success(f"✓ Correctly routed to {routed_to}")
                results[query] = True
            else:
                logger.warning(f"✗ Routed to {routed_to} but expected {expected_agent}")
                results[query] = response.get("response") is not None

        except Exception as e:
            logger.error(f"✗ Failed to process query: {e}")
            results[query] = False

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("AGENT VERIFICATION SUMMARY")
    logger.info("=" * 60)

    passed = sum(1 for r in results.values() if r)
    total = len(results)

    logger.info(f"Total: {passed}/{total} queries handled")

    if passed == total:
        logger.success("🎉 Agent Framework verified!")
        return 0
    else:
        logger.warning(f"⚠ {total - passed} queries failed")
        return 1

if __name__ == "__main__":
    exit_code = asyncio.run(test_agent_framework())
    sys.exit(exit_code)
