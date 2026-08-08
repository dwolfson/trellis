#!/usr/bin/env python3
"""
Generate test metrics to populate the dashboard with proper collection tracking.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import RAGSystem
from loguru import logger

def main():
    """Generate test queries to populate metrics."""
    logger.info("Initializing RAG system...")
    rag = RAGSystem()
    
    # Test queries covering different collections and query types
    test_queries = [
        "What is an Asset in Egeria?",
        "How do I create a connection in Egeria?",
        "Show me an example of using the Asset Manager OMAS",
        "What types are available in the Open Metadata Types?",
        "How do I configure a metadata server?",
        "What is a governance action?",
        "Show me code for creating a glossary term",
        "What connectors are available in Egeria?",
    ]
    
    logger.info(f"Running {len(test_queries)} test queries...")
    
    for i, query in enumerate(test_queries, 1):
        logger.info(f"\n[{i}/{len(test_queries)}] Query: {query}")
        try:
            result = rag.query(query, track_metrics=True)
            logger.info(f"✓ Response: {len(result['response'])} chars from {result['num_sources']} sources")
            
            # Show which collections were used
            if result.get('sources'):
                collections = set()
                for source in result['sources']:
                    if hasattr(source, 'metadata'):
                        coll = source.metadata.get('_collection', 'unknown')
                    elif isinstance(source, dict):
                        coll = source.get('_collection', 'unknown')
                    else:
                        coll = 'unknown'
                    collections.add(coll)
                logger.info(f"  Collections used: {', '.join(collections)}")
        except Exception as e:
            logger.error(f"✗ Query failed: {e}")
    
    logger.info("\n✓ Test metrics generated successfully!")
    logger.info("Run the dashboard to see the results:")
    logger.info("  python -m advisor.dashboard.terminal_dashboard")
    logger.info("  or")
    logger.info("  streamlit run advisor/dashboard/streamlit_dashboard.py")

if __name__ == "__main__":
    main()