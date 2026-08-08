#!/usr/bin/env python3
"""
Generate collection usage report from feedback and metrics data.

This script analyzes feedback and query metrics to show which collections
are being used, how often, and their performance characteristics.
"""

import sys
import json
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Dict, List, Any
from loguru import logger

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.feedback_collector import FeedbackCollector
from advisor.metrics_collector import MetricsCollector


def analyze_collection_usage(
    feedback_file: Path = None,
    metrics_db: Path = None,
    days: int = 7
) -> Dict[str, Any]:
    """
    Analyze collection usage from feedback and metrics.
    
    Args:
        feedback_file: Path to feedback JSONL file
        metrics_db: Path to metrics database
        days: Number of days to analyze
        
    Returns:
        Dictionary with collection usage statistics
    """
    if feedback_file is None:
        feedback_file = Path("data/feedback/user_feedback.jsonl")
    
    if metrics_db is None:
        metrics_db = Path("data/metrics.db")
    
    # Initialize collectors
    feedback_collector = FeedbackCollector(feedback_file)
    
    # Get feedback stats
    logger.info("Analyzing feedback data...")
    feedback_stats = feedback_collector.get_feedback_stats()
    
    # Analyze collection usage from feedback
    collection_usage = {}
    
    for collection, data in feedback_stats.get("by_collection", {}).items():
        total = data.get("total", 0)
        positive = data.get("positive", 0)
        negative = data.get("negative", 0)
        
        satisfaction = positive / total if total > 0 else 0
        
        collection_usage[collection] = {
            "total_queries": total,
            "positive_feedback": positive,
            "negative_feedback": negative,
            "neutral_feedback": data.get("neutral", 0),
            "satisfaction_rate": satisfaction,
            "satisfaction_percentage": f"{satisfaction * 100:.1f}%"
        }
    
    # Sort by usage
    sorted_collections = sorted(
        collection_usage.items(),
        key=lambda x: x[1]["total_queries"],
        reverse=True
    )
    
    # Calculate totals
    total_queries = sum(data["total_queries"] for data in collection_usage.values())
    
    # Add usage percentage
    for collection, data in collection_usage.items():
        data["usage_percentage"] = f"{(data['total_queries'] / total_queries * 100):.1f}%" if total_queries > 0 else "0%"
    
    return {
        "analysis_period_days": days,
        "total_queries": total_queries,
        "total_collections": len(collection_usage),
        "collections": dict(sorted_collections),
        "summary": {
            "most_used": sorted_collections[0][0] if sorted_collections else None,
            "least_used": sorted_collections[-1][0] if sorted_collections else None,
            "highest_satisfaction": max(
                collection_usage.items(),
                key=lambda x: x[1]["satisfaction_rate"]
            )[0] if collection_usage else None,
            "lowest_satisfaction": min(
                collection_usage.items(),
                key=lambda x: x[1]["satisfaction_rate"]
            )[0] if collection_usage else None,
        }
    }


def print_collection_report(report: Dict[str, Any]):
    """
    Print collection usage report in a readable format.
    
    Args:
        report: Report dictionary from analyze_collection_usage()
    """
    print("\n" + "=" * 80)
    print("COLLECTION USAGE REPORT")
    print("=" * 80)
    print(f"\nAnalysis Period: Last {report['analysis_period_days']} days")
    print(f"Total Queries: {report['total_queries']:,}")
    print(f"Collections Used: {report['total_collections']}")
    
    print("\n" + "-" * 80)
    print("COLLECTION STATISTICS")
    print("-" * 80)
    print(f"{'Collection':<25} {'Queries':<10} {'Usage %':<10} {'Satisfaction':<15} {'Rating'}")
    print("-" * 80)
    
    for collection, data in report["collections"].items():
        queries = data["total_queries"]
        usage_pct = data["usage_percentage"]
        satisfaction_pct = data["satisfaction_percentage"]
        
        # Create satisfaction bar
        satisfaction = data["satisfaction_rate"]
        bar_length = int(satisfaction * 20)
        bar = "█" * bar_length + "░" * (20 - bar_length)
        
        print(f"{collection:<25} {queries:<10} {usage_pct:<10} {satisfaction_pct:<15} {bar}")
    
    print("\n" + "-" * 80)
    print("SUMMARY")
    print("-" * 80)
    summary = report["summary"]
    print(f"Most Used Collection:        {summary['most_used']}")
    print(f"Least Used Collection:       {summary['least_used']}")
    print(f"Highest Satisfaction:        {summary['highest_satisfaction']}")
    print(f"Lowest Satisfaction:         {summary['lowest_satisfaction']}")
    
    print("\n" + "=" * 80)


def export_report_json(report: Dict[str, Any], output_file: Path):
    """
    Export report to JSON file.
    
    Args:
        report: Report dictionary
        output_file: Output file path
    """
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    logger.info(f"Report exported to {output_file}")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Generate collection usage report"
    )
    parser.add_argument(
        "--days",
        type=int,
        default=7,
        help="Number of days to analyze (default: 7)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON file path"
    )
    parser.add_argument(
        "--feedback-file",
        type=Path,
        help="Path to feedback JSONL file"
    )
    parser.add_argument(
        "--metrics-db",
        type=Path,
        help="Path to metrics database"
    )
    
    args = parser.parse_args()
    
    try:
        # Generate report
        logger.info("Generating collection usage report...")
        report = analyze_collection_usage(
            feedback_file=args.feedback_file,
            metrics_db=args.metrics_db,
            days=args.days
        )
        
        # Print report
        print_collection_report(report)
        
        # Export if requested
        if args.output:
            export_report_json(report, args.output)
        
        return 0
        
    except Exception as e:
        logger.error(f"Failed to generate report: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())