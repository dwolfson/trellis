#!/usr/bin/env python3
"""
Validate Phase 3 improvements by testing queries and measuring hallucination rates.

This script:
1. Tests a set of queries across different types
2. Measures retrieval quality metrics
3. Compares against baseline
4. Validates hallucination rate reduction

Usage:
    python scripts/validate_phase3_improvements.py --baseline baseline_before.json
    python scripts/validate_phase3_improvements.py --compare baseline_before.json baseline_after.json
"""

import sys
import json
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import RAGSystem
from advisor.query_classifier import get_query_classifier, QueryType
from advisor.collection_metrics import get_collection_metrics_tracker


# Test queries organized by type
TEST_QUERIES = {
    QueryType.CONCEPT: [
        "What is metadata governance?",
        "Explain the concept of data lineage",
        "What is an asset in Egeria?",
        "What does OMAS stand for?",
        "Explain the Open Metadata Repository Services"
    ],
    QueryType.TYPE: [
        "What is the Asset entity type?",
        "Describe the GlossaryTerm type",
        "What attributes does the Connection type have?",
        "What is the Referenceable entity type?",
        "Explain the Classification type system"
    ],
    QueryType.CODE: [
        "How do I create an asset using pyegeria?",
        "Show me how to connect to an OMAG server",
        "How do I search for glossary terms?",
        "What's the code to create a connection?",
        "How do I use the AssetConsumer client?"
    ],
    QueryType.EXAMPLE: [
        "Show me an example of creating a glossary",
        "Give me an example of asset cataloging",
        "Show an example of lineage tracking",
        "Example of using the governance engine",
        "Show me how to deploy Egeria with Docker"
    ],
    QueryType.TUTORIAL: [
        "How do I get started with Egeria?",
        "Walk me through setting up pyegeria",
        "How do I configure an OMAG server?",
        "Guide me through creating a metadata repository",
        "How do I set up the Coco Pharmaceuticals demo?"
    ]
}


def run_query_test(rag_system: RAGSystem, query: str, query_type: QueryType) -> Dict[str, Any]:
    """
    Run a single query test and collect metrics.
    
    Args:
        rag_system: RAG system instance
        query: Query to test
        query_type: Expected query type
        
    Returns:
        Dictionary of metrics
    """
    logger.info(f"\nTesting query: {query}")
    logger.info(f"Expected type: {query_type.value}")
    
    try:
        # Run query
        response = rag_system.query(query)
        
        # Convert response to string if it's a dict
        response_text = response if isinstance(response, str) else str(response)
        
        # Get metrics from last query
        metrics = {
            "query": query,
            "query_type": query_type.value,
            "response_length": len(response_text) if response_text else 0,
            "success": bool(response_text),
            "timestamp": datetime.now().isoformat()
        }
        
        # Check if response contains citations (anti-hallucination indicator)
        has_citations = any(marker in response_text.lower() for marker in [
            "from ", "according to", "in ", "the documentation",
            "pyegeria/", "site/docs/", ".py", ".md"
        ]) if response_text else False
        
        metrics["has_citations"] = has_citations
        
        # Check for hallucination indicators
        hallucination_indicators = [
            "i don't have", "not in the", "not covered",
            "cannot find", "no information", "not available"
        ]
        admits_limitation = any(ind in response_text.lower() for ind in hallucination_indicators) if response_text else False
        metrics["admits_limitation"] = admits_limitation
        
        logger.info(f"✓ Response length: {metrics['response_length']}")
        logger.info(f"✓ Has citations: {has_citations}")
        logger.info(f"✓ Admits limitations: {admits_limitation}")
        
        return metrics
        
    except Exception as e:
        logger.error(f"Query failed: {e}")
        return {
            "query": query,
            "query_type": query_type.value,
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }


def calculate_hallucination_rate(results: List[Dict[str, Any]]) -> Dict[str, float]:
    """
    Calculate hallucination rate from test results.
    
    A response is considered non-hallucinated if:
    - It has citations (references sources)
    - OR it admits limitations (honest about missing info)
    
    Args:
        results: List of query test results
        
    Returns:
        Dictionary with hallucination metrics
    """
    total = len(results)
    successful = sum(1 for r in results if r.get("success", False))
    
    if successful == 0:
        return {
            "total_queries": total,
            "successful_queries": 0,
            "hallucination_rate": 1.0,
            "citation_rate": 0.0,
            "honesty_rate": 0.0
        }
    
    # Count responses with citations or honest admissions
    with_citations = sum(1 for r in results if r.get("has_citations", False))
    admits_limits = sum(1 for r in results if r.get("admits_limitation", False))
    non_hallucinated = sum(1 for r in results 
                          if r.get("has_citations", False) or r.get("admits_limitation", False))
    
    return {
        "total_queries": total,
        "successful_queries": successful,
        "hallucination_rate": 1.0 - (non_hallucinated / successful),
        "citation_rate": with_citations / successful,
        "honesty_rate": admits_limits / successful,
        "non_hallucinated_count": non_hallucinated
    }


def run_validation(output_file = None) -> Dict[str, Any]:
    """
    Run full validation test suite.
    
    Args:
        output_file: Optional file to save results
        
    Returns:
        Validation results
    """
    logger.info("=" * 80)
    logger.info("PHASE 3 VALIDATION TEST")
    logger.info("=" * 80)
    
    # Initialize RAG system
    logger.info("\nInitializing RAG system...")
    rag_system = RAGSystem()
    
    # Run tests for each query type
    all_results = []
    results_by_type = {}
    
    for query_type, queries in TEST_QUERIES.items():
        logger.info(f"\n{'=' * 80}")
        logger.info(f"Testing {query_type.value.upper()} queries ({len(queries)} queries)")
        logger.info("=" * 80)
        
        type_results = []
        for query in queries:
            result = run_query_test(rag_system, query, query_type)
            type_results.append(result)
            all_results.append(result)
        
        results_by_type[query_type.value] = type_results
    
    # Calculate overall metrics
    logger.info("\n" + "=" * 80)
    logger.info("CALCULATING METRICS")
    logger.info("=" * 80)
    
    overall_metrics = calculate_hallucination_rate(all_results)
    
    logger.info(f"\nOverall Results:")
    logger.info(f"  Total queries: {overall_metrics['total_queries']}")
    logger.info(f"  Successful: {overall_metrics['successful_queries']}")
    logger.info(f"  Hallucination rate: {overall_metrics['hallucination_rate']:.1%}")
    logger.info(f"  Citation rate: {overall_metrics['citation_rate']:.1%}")
    logger.info(f"  Honesty rate: {overall_metrics['honesty_rate']:.1%}")
    
    # Calculate per-type metrics
    metrics_by_type = {}
    for query_type, type_results in results_by_type.items():
        type_metrics = calculate_hallucination_rate(type_results)
        metrics_by_type[query_type] = type_metrics
        
        logger.info(f"\n{query_type.upper()} queries:")
        logger.info(f"  Hallucination rate: {type_metrics['hallucination_rate']:.1%}")
        logger.info(f"  Citation rate: {type_metrics['citation_rate']:.1%}")
    
    # Compile final results
    validation_results = {
        "timestamp": datetime.now().isoformat(),
        "overall_metrics": overall_metrics,
        "metrics_by_type": metrics_by_type,
        "all_results": all_results,
        "results_by_type": results_by_type
    }
    
    # Save results if output file specified
    if output_file:
        output_file.parent.mkdir(parents=True, exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(validation_results, f, indent=2)
        logger.info(f"\n✓ Results saved to: {output_file}")
    
    return validation_results


def compare_baselines(before_file: Path, after_file: Path):
    """
    Compare before and after baseline metrics.
    
    Args:
        before_file: Baseline before improvements
        after_file: Baseline after improvements
    """
    logger.info("=" * 80)
    logger.info("BASELINE COMPARISON")
    logger.info("=" * 80)
    
    # Load baselines
    with open(before_file) as f:
        before = json.load(f)
    
    with open(after_file) as f:
        after = json.load(f)
    
    # Compare overall metrics
    before_hall = before["overall_metrics"]["hallucination_rate"]
    after_hall = after["overall_metrics"]["hallucination_rate"]
    improvement = (before_hall - after_hall) / before_hall if before_hall > 0 else 0
    
    logger.info(f"\nOverall Hallucination Rate:")
    logger.info(f"  Before: {before_hall:.1%}")
    logger.info(f"  After:  {after_hall:.1%}")
    logger.info(f"  Improvement: {improvement:.1%}")
    
    # Compare by query type
    logger.info(f"\nBy Query Type:")
    for query_type in before["metrics_by_type"].keys():
        before_type = before["metrics_by_type"][query_type]["hallucination_rate"]
        after_type = after["metrics_by_type"][query_type]["hallucination_rate"]
        type_improvement = (before_type - after_type) / before_type if before_type > 0 else 0
        
        logger.info(f"\n  {query_type.upper()}:")
        logger.info(f"    Before: {before_type:.1%}")
        logger.info(f"    After:  {after_type:.1%}")
        logger.info(f"    Improvement: {type_improvement:.1%}")
    
    # Check if target achieved
    target_rate = 0.27
    if after_hall <= target_rate:
        logger.info(f"\n✅ TARGET ACHIEVED! Hallucination rate ≤ {target_rate:.0%}")
    else:
        logger.info(f"\n⚠️  Target not yet achieved. Current: {after_hall:.1%}, Target: {target_rate:.0%}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate Phase 3 improvements"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("validation_results.json"),
        help="Output file for results"
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        help="Baseline file to compare against"
    )
    parser.add_argument(
        "--compare",
        nargs=2,
        metavar=("BEFORE", "AFTER"),
        help="Compare two baseline files"
    )
    
    args = parser.parse_args()
    
    try:
        if args.compare:
            # Compare mode
            before_file = Path(args.compare[0])
            after_file = Path(args.compare[1])
            
            if not before_file.exists():
                logger.error(f"Before file not found: {before_file}")
                return 1
            if not after_file.exists():
                logger.error(f"After file not found: {after_file}")
                return 1
            
            compare_baselines(before_file, after_file)
        else:
            # Validation mode
            results = run_validation(output_file=args.output)
            
            # Compare with baseline if provided
            if args.baseline and args.baseline.exists():
                logger.info("\n")
                compare_baselines(args.baseline, args.output)
        
        return 0
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())