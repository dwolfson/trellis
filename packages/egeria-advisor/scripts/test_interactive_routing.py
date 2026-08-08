#!/usr/bin/env python3
"""
Test script for interactive routing with clarification and follow-ups.

This script demonstrates:
1. Confidence-based clarification
2. Follow-up question suggestions
3. Succinct answer formatting
4. Interactive conversation flow
"""

from advisor.query_classifier import classify_query, QueryType
from advisor.collection_router import get_collection_router
from advisor.interactive_response import (
    get_interactive_handler,
    create_interactive_response,
    ResponseMode
)


def test_high_confidence_query():
    """Test query with high confidence - should get succinct answer with options."""
    print("\n" + "="*60)
    print("TEST 1: High Confidence Query")
    print("="*60)
    
    query = "Show me the documentation for create_glossary"
    print(f"\nQuery: '{query}'")
    
    # Classify query
    classification = classify_query(query)
    print(f"Classification: {classification.query_type.value}")
    print(f"Confidence: {classification.confidence:.2f}")
    
    # Route query
    router = get_collection_router()
    collections = router.route_query(query)
    print(f"Routed to: {collections}")
    
    # Create interactive response
    handler = get_interactive_handler()
    
    # Simulate answer
    answer = "The create_glossary command creates a new glossary in Egeria. It requires a name and optional description parameter."
    
    response = handler.create_interactive_response(
        answer=answer,
        classification=classification,
        confidence=classification.confidence,
        collections_searched=collections,
        topic="create_glossary"
    )
    
    print(f"\nResponse Mode: {response.response_mode.value}")
    print(f"Clarification Needed: {response.clarification_needed}")
    print(f"\nFollow-up Options:")
    for i, option in enumerate(response.follow_up_options, 1):
        print(f"  {i}. {option}")
    
    print(f"\n{'-'*60}")
    print("Formatted Response:")
    print(f"{'-'*60}")
    print(response.answer)


def test_low_confidence_query():
    """Test query with low confidence - should request clarification."""
    print("\n" + "="*60)
    print("TEST 2: Low Confidence Query (Ambiguous)")
    print("="*60)
    
    query = "Tell me about glossary"
    print(f"\nQuery: '{query}'")
    
    # Classify query
    classification = classify_query(query)
    print(f"Classification: {classification.query_type.value}")
    print(f"Confidence: {classification.confidence:.2f}")
    
    # Route query
    router = get_collection_router()
    collections = router.route_query(query)
    print(f"Routed to: {collections}")
    
    # Create interactive response with low confidence
    handler = get_interactive_handler()
    
    # Simulate that we're uncertain
    low_confidence = 0.35
    
    response = handler.create_interactive_response(
        answer="",  # No answer yet, need clarification
        classification=classification,
        confidence=low_confidence,
        collections_searched=collections,
        topic="glossary"
    )
    
    print(f"\nResponse Mode: {response.response_mode.value}")
    print(f"Clarification Needed: {response.clarification_needed}")
    
    print(f"\n{'-'*60}")
    print("Clarification Request:")
    print(f"{'-'*60}")
    print(response.answer)


def test_multiple_routes_query():
    """Test query that matches multiple collections - should offer clarification."""
    print("\n" + "="*60)
    print("TEST 3: Multiple Routes Query")
    print("="*60)
    
    query = "How do I use OMAS?"
    print(f"\nQuery: '{query}'")
    
    # Classify query
    classification = classify_query(query)
    print(f"Classification: {classification.query_type.value}")
    print(f"Confidence: {classification.confidence:.2f}")
    
    # Route query - OMAS appears in multiple collections
    router = get_collection_router()
    collections = router.route_query(query, max_collections=3)
    print(f"Routed to: {collections}")
    
    # Create interactive response
    handler = get_interactive_handler()
    
    # Medium confidence but multiple routes
    response = handler.create_interactive_response(
        answer="",
        classification=classification,
        confidence=0.55,
        collections_searched=collections,
        topic="OMAS"
    )
    
    print(f"\nResponse Mode: {response.response_mode.value}")
    print(f"Clarification Needed: {response.clarification_needed}")
    
    print(f"\n{'-'*60}")
    print("Response:")
    print(f"{'-'*60}")
    print(response.answer)


def test_follow_up_options():
    """Test different query types get appropriate follow-up options."""
    print("\n" + "="*60)
    print("TEST 4: Follow-up Options by Query Type")
    print("="*60)
    
    handler = get_interactive_handler()
    
    test_cases = [
        (QueryType.CONCEPT, "concept query"),
        (QueryType.CODE, "code query"),
        (QueryType.EXAMPLE, "example query"),
        (QueryType.TUTORIAL, "tutorial query"),
    ]
    
    for query_type, description in test_cases:
        options = handler.get_follow_up_options(query_type)
        print(f"\n{description.upper()} ({query_type.value}):")
        for i, option in enumerate(options, 1):
            print(f"  {i}. {option}")


def test_trigger_word_hints():
    """Test trigger word hints for better query phrasing."""
    print("\n" + "="*60)
    print("TEST 5: Trigger Word Hints")
    print("="*60)
    
    handler = get_interactive_handler()
    
    intents = ["documentation", "code", "cli", "examples"]
    
    for intent in intents:
        hint = handler.get_trigger_word_hints(intent)
        if hint:
            print(f"\n{intent.upper()}:")
            print(hint)


def test_succinct_format():
    """Test succinct answer formatting."""
    print("\n" + "="*60)
    print("TEST 6: Succinct Answer Format")
    print("="*60)
    
    handler = get_interactive_handler()
    
    answer = "The create_glossary command creates a new glossary in Egeria. It requires a name parameter and accepts an optional description."
    
    follow_ups = [
        "Would you like to see a code example?",
        "Do you want to see related commands?",
        "Should I show you the command options?",
        "Would you like to see common use cases?"
    ]
    
    formatted = handler.format_succinct_response(answer, follow_ups)
    
    print(f"\n{'-'*60}")
    print("Formatted Response:")
    print(f"{'-'*60}")
    print(formatted)


def test_confidence_thresholds():
    """Test confidence threshold logic."""
    print("\n" + "="*60)
    print("TEST 7: Confidence Threshold Logic")
    print("="*60)
    
    handler = get_interactive_handler()
    
    test_cases = [
        (0.85, 1, "High confidence, single route"),
        (0.60, 1, "Medium confidence, single route"),
        (0.40, 1, "Low confidence, single route"),
        (0.60, 3, "Medium confidence, multiple routes"),
        (0.25, 1, "Very low confidence"),
    ]
    
    for confidence, num_routes, description in test_cases:
        should_clarify = handler.should_clarify(confidence, num_routes)
        print(f"\n{description}:")
        print(f"  Confidence: {confidence:.2f}")
        print(f"  Routes: {num_routes}")
        print(f"  Should Clarify: {'YES' if should_clarify else 'NO'}")


def main():
    """Run all tests."""
    print("=" * 60)
    print("Testing Interactive Routing System")
    print("=" * 60)
    
    try:
        test_high_confidence_query()
        test_low_confidence_query()
        test_multiple_routes_query()
        test_follow_up_options()
        test_trigger_word_hints()
        test_succinct_format()
        test_confidence_thresholds()
        
        print("\n" + "=" * 60)
        print("✓ All tests completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\n✗ Test failed with error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())