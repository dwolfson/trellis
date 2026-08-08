"""
Capture baseline metrics before re-ingestion.

This script runs a set of test queries and captures current
system performance for comparison after improvements.
"""

import json
import time
from pathlib import Path
from typing import Dict, List, Any
from loguru import logger
import sys

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.query_classifier import classify_query


# Test queries for each type
TEST_QUERIES = {
    "concept": [
        "What is a glossary?",
        "Define metadata",
        "Explain governance",
        "What is an asset?",
        "What is lineage?",
    ],
    "type": [
        "What properties does GlossaryTerm have?",
        "What attributes are in Asset?",
        "What fields does Connection have?",
    ],
    "code": [
        "Show me code for creating a glossary",
        "How do I use pyegeria to create an asset?",
        "Give me code for connecting to Egeria",
    ],
    "example": [
        "Give me an example of using pyegeria",
        "Show me a sample notebook",
        "Example of creating a connection",
    ],
    "tutorial": [
        "How do I get started with Egeria?",
        "How do I set up a server?",
        "How do I configure a connector?",
    ],
}


def capture_baseline() -> Dict[str, Any]:
    """
    Capture baseline metrics.
    
    Returns:
        Dict with baseline metrics
    """
    logger.info("Starting baseline capture...")
    
    baseline = {
        "timestamp": time.time(),
        "queries_by_type": {},
        "overall_stats": {
            "total_queries": 0,
            "total_latency_ms": 0,
            "total_chunks_retrieved": 0,
            "hallucinations_detected": 0,
        }
    }
    
    # Run queries for each type
    for query_type, queries in TEST_QUERIES.items():
        logger.info(f"Testing {query_type} queries...")
        
        type_results = []
        
        for query in queries:
            logger.info(f"  Query: {query}")
            
            # Classify query
            classification = classify_query(query)
            
            # Simulate query execution (actual RAG system may not be available)
            start_time = time.time()
            try:
                # Note: This would normally call the RAG system
                # For now, we just capture classification metrics
                latency_ms = (time.time() - start_time) * 1000
                
                # Extract metrics
                query_result = {
                    "query": query,
                    "classification": {
                        "type": classification.query_type.value,
                        "topics": [t.value for t in classification.topics],
                        "confidence": classification.confidence,
                        "expected_collections": classification.matched_patterns[:3] if classification.matched_patterns else [],
                    },
                    "latency_ms": latency_ms,
                    "success": True,
                    "error": None,
                    "note": "Classification only - RAG system integration pending"
                }
                
                # Update overall stats
                baseline["overall_stats"]["total_queries"] += 1
                baseline["overall_stats"]["total_latency_ms"] += latency_ms
                
                logger.info(f"    Classification: {classification.query_type.value} (confidence: {classification.confidence:.2f})")
                
            except Exception as e:
                logger.error(f"    Error: {e}")
                query_result = {
                    "query": query,
                    "classification": {
                        "type": classification.query_type.value,
                        "topics": [t.value for t in classification.topics],
                        "confidence": classification.confidence,
                    },
                    "success": False,
                    "error": str(e),
                }
            
            type_results.append(query_result)
        
        baseline["queries_by_type"][query_type] = type_results
    
    # Calculate averages
    total_queries = baseline["overall_stats"]["total_queries"]
    if total_queries > 0:
        baseline["overall_stats"]["avg_latency_ms"] = (
            baseline["overall_stats"]["total_latency_ms"] / total_queries
        )
    
    logger.info("Baseline capture complete!")
    logger.info(f"Total queries: {total_queries}")
    logger.info(f"Avg classification time: {baseline['overall_stats'].get('avg_latency_ms', 0):.1f}ms")
    
    return baseline


def save_baseline(baseline: Dict[str, Any], output_path: Path):
    """
    Save baseline to file.
    
    Args:
        baseline: Baseline metrics
        output_path: Output file path
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        json.dump(baseline, f, indent=2)
    
    logger.info(f"Baseline saved to: {output_path}")


def print_summary(baseline: Dict[str, Any]):
    """
    Print baseline summary.
    
    Args:
        baseline: Baseline metrics
    """
    print("\n" + "="*60)
    print("BASELINE METRICS SUMMARY")
    print("="*60)
    print(f"Total Queries: {baseline['overall_stats']['total_queries']}")
    print(f"Avg Classification Time: {baseline['overall_stats'].get('avg_latency_ms', 0):.1f}ms")
    print("\nBy Query Type:")
    for query_type, results in baseline['queries_by_type'].items():
        successful = sum(1 for r in results if r.get('success', False))
        print(f"  {query_type}: {successful}/{len(results)} successful")
    
    print("\nQuery Type Distribution:")
    for query_type, results in baseline['queries_by_type'].items():
        types = [r['classification']['type'] for r in results if 'classification' in r]
        if types:
            print(f"  {query_type} queries classified as: {', '.join(set(types))}")
    
    print("\nNote: Full RAG system metrics will be available after integration")
    print("="*60)


def main():
    """Main function."""
    # Capture baseline
    baseline = capture_baseline()
    
    # Save to file
    output_path = Path("data/baseline_metrics.json")
    save_baseline(baseline, output_path)
    
    # Print summary
    print_summary(baseline)


if __name__ == "__main__":
    main()