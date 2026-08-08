#!/usr/bin/env python3
"""
Test the complete exhaustive query flow through ConversationAgent.
"""

import sys
sys.path.insert(0, '.')

from advisor.agents.conversation_agent import ConversationAgent
from loguru import logger

# Configure logger to show all messages
logger.remove()
logger.add(sys.stderr, level="DEBUG")

def test_exhaustive_query():
    """Test exhaustive query detection and routing."""
    
    print("=" * 80)
    print("TESTING EXHAUSTIVE QUERY FLOW")
    print("=" * 80)
    
    # Create agent
    agent = ConversationAgent(enable_mlflow=False, enable_mcp=False)
    
    # Test query
    query = "list all the methods in ProjectManager"
    print(f"\nQuery: {query}\n")
    
    # Run query
    response = agent.run(query, use_rag=True)
    
    print("\n" + "=" * 80)
    print("RESPONSE")
    print("=" * 80)
    print(f"Answer: {response.get('content', response.get('answer', ''))[:500]}...")
    print(f"\nSources: {len(response.get('sources', []))}")
    print(f"Routed to: {response.get('metadata', {}).get('routed_to', 'unknown')}")
    
    # Check if it worked
    if 'routed_to' in response.get('metadata', {}):
        routed_to = response['metadata']['routed_to']
        print(f"\n✓ Query was routed to: {routed_to}")
        
        if routed_to == 'pyegeria_agent':
            print("✓ Correctly routed to PyEgeria Agent")
        else:
            print(f"✗ Expected pyegeria_agent, got {routed_to}")
    
    # Check source count
    source_count = len(response.get('sources', []))
    print(f"\nSource count: {source_count}")
    
    if source_count > 10:
        print(f"✓ Got {source_count} sources (likely exhaustive query worked)")
    else:
        print(f"⚠ Only {source_count} sources (might still be semantic search)")

if __name__ == '__main__':
    test_exhaustive_query()