#!/usr/bin/env python3
"""
Test script for Phase 1 Feedback System with sentiment analysis.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.feedback_collector import get_feedback_collector
from advisor.sentiment_analysis import get_sentiment_analyzer


def test_sentiment_analysis():
    """Test sentiment analysis on various feedback comments."""
    print("\n=== Testing Sentiment Analysis ===\n")
    
    analyzer = get_sentiment_analyzer()
    
    test_comments = [
        "This is amazing! The answer was exactly what I needed.",
        "Terrible response. Completely wrong information.",
        "I'm confused by this answer. It doesn't make sense.",
        "Pretty good, but could be more detailed.",
        "This is frustrating. I've asked this three times now.",
        "Excellent work! Very helpful and clear.",
        "",  # Empty comment
    ]
    
    for comment in test_comments:
        if comment:
            result = analyzer.analyze(comment)
            print(f"Comment: '{comment[:50]}...'")
            print(f"  Sentiment: {result.sentiment} (confidence: {result.confidence:.2f})")
            print(f"  Emotions: {', '.join(result.emotions) if result.emotions else 'None'}")
            print(f"  Keywords: {', '.join(result.keywords_found) if result.keywords_found else 'None'}")
            print()


def test_feedback_collection_with_sentiment():
    """Test feedback collection with sentiment analysis."""
    print("\n=== Testing Feedback Collection with Sentiment ===\n")
    
    collector = get_feedback_collector()
    
    # Simulate feedback with different sentiments
    test_cases = [
        {
            "query": "How do I create a server in Egeria?",
            "response": "To create a server, use the ServerConfig class...",
            "rating": "positive",
            "star_rating": 5,
            "category_ratings": {
                "accuracy": 5,
                "completeness": 4,
                "clarity": 5,
                "relevance": 5
            },
            "comment": "Perfect answer! Very clear and helpful.",
            "query_type": "how_to",
            "collections_searched": ["egeria_docs"]
        },
        {
            "query": "What is a metadata repository?",
            "response": "A metadata repository stores metadata...",
            "rating": "negative",
            "star_rating": 2,
            "category_ratings": {
                "accuracy": 3,
                "completeness": 2,
                "clarity": 2,
                "relevance": 3
            },
            "comment": "This is confusing and doesn't answer my question.",
            "query_type": "concept",
            "collections_searched": ["egeria_docs"]
        },
        {
            "query": "How to configure OMAG server?",
            "response": "Configure OMAG server using...",
            "rating": "neutral",
            "star_rating": 3,
            "category_ratings": {
                "accuracy": 3,
                "completeness": 3,
                "clarity": 3,
                "relevance": 3
            },
            "comment": "Okay, but could use more examples.",
            "query_type": "how_to",
            "collections_searched": ["egeria_docs"]
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"Test Case {i}: {test_case['rating'].upper()} feedback")
        print(f"  Query: {test_case['query']}")
        print(f"  Star Rating: {'⭐' * test_case['star_rating']}")
        print(f"  Comment: {test_case['comment']}")
        
        # Record feedback (this will trigger sentiment analysis)
        collector.record_feedback(**test_case)
        
        print(f"  ✓ Feedback recorded with sentiment analysis")
        print()
    
    # Get statistics
    stats = collector.get_statistics()
    print("\n=== Feedback Statistics ===")
    print(f"Total feedback: {stats['total_feedback']}")
    print(f"Average rating: {stats['average_rating']:.2f}")
    print(f"Rating distribution:")
    for rating, count in stats['rating_distribution'].items():
        print(f"  {rating}: {count}")
    
    if stats.get('average_star_rating'):
        print(f"\nAverage star rating: {stats['average_star_rating']:.2f} ⭐")
    
    if stats.get('category_averages'):
        print("\nCategory averages:")
        for category, avg in stats['category_averages'].items():
            print(f"  {category}: {avg:.2f} ⭐")


def test_batch_sentiment_analysis():
    """Test batch sentiment analysis."""
    print("\n=== Testing Batch Sentiment Analysis ===\n")
    
    analyzer = get_sentiment_analyzer()
    
    feedback_entries = [
        {
            "comment": "Excellent response! Very helpful.",
            "rating": "positive"
        },
        {
            "comment": "This doesn't help at all.",
            "rating": "negative"
        },
        {
            "comment": "I'm not sure I understand this.",
            "rating": "neutral"
        },
        {
            "comment": "Amazing! Exactly what I needed!",
            "rating": "positive"
        },
        {
            "comment": "Frustrating. Still confused.",
            "rating": "negative"
        }
    ]
    
    results = analyzer.analyze_feedback_batch(feedback_entries)
    
    print(f"Analyzed {results['total_analyzed']} feedback entries")
    print(f"\nSentiment distribution:")
    for sentiment, count in results['sentiment_distribution'].items():
        print(f"  {sentiment}: {count}")
    
    print(f"\nEmotion distribution:")
    for emotion, count in results['emotion_distribution'].items():
        print(f"  {emotion}: {count}")
    
    print(f"\nAverage confidence: {results['average_confidence']:.2f}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Phase 1 Feedback System with Sentiment Analysis - Test Suite")
    print("=" * 60)
    
    try:
        test_sentiment_analysis()
        test_feedback_collection_with_sentiment()
        test_batch_sentiment_analysis()
        
        print("\n" + "=" * 60)
        print("✓ All tests completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()