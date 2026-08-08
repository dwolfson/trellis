#!/usr/bin/env python3
"""
Test script for CLI Command Agent.

Tests the agent's ability to answer questions about CLI commands.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.cli_command_agent import CLICommandAgent
from loguru import logger

def main():
    """Test CLI Command Agent."""
    
    logger.info("="*60)
    logger.info("Testing CLI Command Agent")
    logger.info("="*60 + "\n")
    
    # Initialize agent
    try:
        agent = CLICommandAgent()
        logger.info("✓ Agent initialized successfully\n")
    except Exception as e:
        logger.error(f"Failed to initialize agent: {e}")
        return 1
    
    # Test queries
    test_queries = [
        "How do I create a glossary?",
        "What monitoring commands are available?",
        "Show me all catalog commands",
        "What parameters does list_assets take?",
        "How do I use dr_egeria?",
    ]
    
    for i, query in enumerate(test_queries, 1):
        logger.info(f"\n{'='*60}")
        logger.info(f"Test Query {i}: {query}")
        logger.info("="*60)
        
        try:
            # Check if agent can handle the query
            can_handle = agent.can_handle(query)
            logger.info(f"Can handle: {can_handle}")
            
            if can_handle:
                # Get response
                response = agent.query(query)
                logger.info(f"\nResponse:\n{response}\n")
            else:
                logger.warning("Agent cannot handle this query")
                
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            import traceback
            traceback.print_exc()
    
    logger.info("\n" + "="*60)
    logger.info("Testing complete!")
    logger.info("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())