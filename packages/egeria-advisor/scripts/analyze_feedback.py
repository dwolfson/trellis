#!/usr/bin/env python3
"""
Analyze user feedback and generate improvement recommendations.

Usage:
    python scripts/analyze_feedback.py
    python scripts/analyze_feedback.py --period week
    python scripts/analyze_feedback.py --export report.json
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.feedback_collector import get_feedback_collector
from loguru import logger


def analyze_feedback(period_days: int = 7):
    """
    Analyze feedback and generate report.
    
    Args:
        period_days: Number of days to analyze (default: 7)
    """
    collector = get_feedback_collector()
    
    print("=" * 70)
    print(f"Feedback Analysis Report")
    print(f"Period: Last {period_days} days")
    print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # Get overall statistics
    stats = collector.get_feedback_stats()
    
    if stats['total'] == 0:
        print("\n⚠️  No feedback data available yet.")
        print("\nTo start collecting feedback:")
        print("  1. Use the feedback_collector module in your code")
        print("  2. Enable feedback prompts in the CLI")
        print("  3. See USER_FEEDBACK_GUIDE.md for details")
        return
    
    # Overall statistics
    print(f"\n📊 Overall Statistics")
    print(f"{'─' * 70}")
    print(f"Total feedback entries: {stats['total']}")
    print(f"Positive: {stats['positive']} ({stats['positive']/stats['total']*100:.1f}%)")
    print(f"Negative: {stats['negative']} ({stats['negative']/stats['total']*100:.1f}%)")
    print(f"Neutral: {stats['neutral']} ({stats['neutral']/stats['total']*100:.1f}%)")
    print(f"Satisfaction rate: {stats['satisfaction_rate']*100:.1f}%")
    
    # Satisfaction by query type
    if stats['by_query_type']:
        print(f"\n📝 Satisfaction by Query Type")
        print(f"{'─' * 70}")
        for query_type, data in sorted(
            stats['by_query_type'].items(),
            key=lambda x: x[1]['total'],
            reverse=True
        ):
            total = data['total']
            positive = data.get('positive', 0)
            satisfaction = positive / total if total > 0 else 0
            
            # Status indicator
            if satisfaction >= 0.8:
                status = "✅"
            elif satisfaction >= 0.6:
                status = "⚠️ "
            else:
                status = "❌"
            
            print(f"{status} {query_type:20s}: {satisfaction*100:5.1f}% ({positive}/{total})")
    
    # Satisfaction by collection
    if stats['by_collection']:
        print(f"\n📚 Satisfaction by Collection")
        print(f"{'─' * 70}")
        for collection, data in sorted(
            stats['by_collection'].items(),
            key=lambda x: x[1]['total'],
            reverse=True
        ):
            total = data['total']
            positive = data.get('positive', 0)
            satisfaction = positive / total if total > 0 else 0
            
            # Status indicator
            if satisfaction >= 0.8:
                status = "✅"
            elif satisfaction >= 0.6:
                status = "⚠️ "
            else:
                status = "❌"
            
            print(f"{status} {collection:20s}: {satisfaction*100:5.1f}% ({positive}/{total})")
    
    # Routing corrections
    if stats['routing_corrections']:
        print(f"\n🔀 Routing Corrections Suggested")
        print(f"{'─' * 70}")
        print(f"Total corrections: {len(stats['routing_corrections'])}")
        print("\nTop corrections:")
        for i, correction in enumerate(stats['routing_corrections'][:5], 1):
            print(f"\n{i}. Query: \"{correction['query'][:60]}...\"")
            print(f"   Searched: {', '.join(correction['searched'])}")
            print(f"   Suggested: {correction['suggested']}")
    
    # Get improvement recommendations
    improvements = collector.get_routing_improvements()
    
    if improvements:
        print(f"\n💡 Recommended Actions")
        print(f"{'─' * 70}")
        
        # Group by type
        by_type = {}
        for imp in improvements:
            imp_type = imp['type']
            if imp_type not in by_type:
                by_type[imp_type] = []
            by_type[imp_type].append(imp)
        
        for imp_type, items in by_type.items():
            print(f"\n{imp_type.replace('_', ' ').title()} ({len(items)} items):")
            for item in items[:3]:  # Show top 3
                print(f"  • {item['action']}")
                if 'collection' in item:
                    print(f"    Collection: {item['collection']}")
                if 'query_type' in item:
                    print(f"    Query Type: {item['query_type']}")
                if 'satisfaction_rate' in item:
                    print(f"    Current satisfaction: {item['satisfaction_rate']*100:.1f}%")
    
    # Summary and next steps
    print(f"\n📋 Next Steps")
    print(f"{'─' * 70}")
    
    if stats['satisfaction_rate'] >= 0.8:
        print("✅ System is performing well!")
        print("   • Continue monitoring feedback")
        print("   • Consider minor optimizations")
    elif stats['satisfaction_rate'] >= 0.6:
        print("⚠️  System needs some improvements")
        print("   • Review low-satisfaction collections")
        print("   • Update prompt templates")
        print("   • Add missing domain terms")
    else:
        print("❌ System needs significant improvements")
        print("   • Urgent: Review routing logic")
        print("   • Urgent: Update prompt templates")
        print("   • Consider user interviews")
    
    print("\nFor detailed guidance, see:")
    print("  • USER_FEEDBACK_GUIDE.md")
    print("  • PHASE8_ROUTING_QUALITY_IMPROVEMENTS.md")
    print("=" * 70)


def export_report(output_file: Path):
    """Export feedback analysis to file."""
    collector = get_feedback_collector()
    stats = collector.get_feedback_stats()
    improvements = collector.get_routing_improvements()
    
    report = {
        "generated_at": datetime.now().isoformat(),
        "statistics": stats,
        "improvements": improvements
    }
    
    import json
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"✅ Report exported to {output_file}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Analyze user feedback and generate improvement recommendations"
    )
    parser.add_argument(
        '--period',
        choices=['day', 'week', 'month', 'all'],
        default='week',
        help='Time period to analyze (default: week)'
    )
    parser.add_argument(
        '--export',
        type=Path,
        help='Export report to JSON file'
    )
    
    args = parser.parse_args()
    
    # Map period to days
    period_map = {
        'day': 1,
        'week': 7,
        'month': 30,
        'all': 365 * 10  # Effectively all data
    }
    period_days = period_map[args.period]
    
    # Analyze feedback
    analyze_feedback(period_days)
    
    # Export if requested
    if args.export:
        export_report(args.export)


if __name__ == "__main__":
    main()