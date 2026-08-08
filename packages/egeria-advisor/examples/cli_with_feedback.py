#!/usr/bin/env python3
"""
Example CLI integration with user feedback collection.

This demonstrates how to integrate the feedback system into a CLI application.
"""

import sys
from pathlib import Path
from typing import Dict, Any

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_system import get_rag_system
from advisor.feedback_collector import get_feedback_collector
from loguru import logger
import uuid


def prompt_for_feedback(query: str, response: Dict[str, Any], session_id: str) -> None:
    """
    Prompt user for feedback after showing response.
    
    Args:
        query: Original user query
        response: Response dictionary from RAG system
        session_id: Current session ID
    """
    print("\n" + "─" * 70)
    print("Was this answer helpful?")
    print("  [y] Yes, this was helpful 👍")
    print("  [n] No, this wasn't helpful 👎")
    print("  [s] Skip feedback")
    print("─" * 70)
    
    feedback_choice = input("Your choice (y/n/s): ").strip().lower()
    
    if feedback_choice == 's':
        print("Feedback skipped.")
        return
    
    collector = get_feedback_collector()
    
    if feedback_choice == 'y':
        # Positive feedback
        print("\nGreat! Would you like to add a comment? (optional)")
        comment = input("Comment (or press Enter to skip): ").strip()
        
        collector.record_feedback(
            query=query,
            query_type=response.get('query_type', 'unknown'),
            collections_searched=response.get('collections_searched', []),
            response_length=len(response.get('response', '')),
            rating="positive",
            user_comment=comment if comment else None,
            session_id=session_id
        )
        print("✅ Thank you for your positive feedback!")
        
    elif feedback_choice == 'n':
        # Negative feedback with details
        print("\nSorry the answer wasn't helpful. Can you help us improve?")
        
        # Ask for reason
        print("\nWhat was the problem?")
        print("  [1] Wrong information")
        print("  [2] Incomplete answer")
        print("  [3] Wrong collection searched")
        print("  [4] Poor code example")
        print("  [5] Other")
        
        reason_choice = input("Choose (1-5): ").strip()
        
        reason_map = {
            '1': "Wrong information provided",
            '2': "Answer was incomplete",
            '3': "Searched wrong collection",
            '4': "Code example was poor quality",
            '5': "Other issue"
        }
        feedback_text = reason_map.get(reason_choice, "Unspecified issue")
        
        # Ask for suggested collection if routing issue
        suggested_collection = None
        if reason_choice == '3':
            print("\nWhich collection should have been searched?")
            print("  Available: pyegeria, pyegeria_cli, pyegeria_drE,")
            print("             egeria_java, egeria_docs, egeria_workspaces")
            suggested = input("Suggested collection: ").strip()
            if suggested:
                suggested_collection = suggested
        
        # Ask for additional comment
        print("\nAny additional comments? (optional)")
        comment = input("Comment: ").strip()
        
        collector.record_feedback(
            query=query,
            query_type=response.get('query_type', 'unknown'),
            collections_searched=response.get('collections_searched', []),
            response_length=len(response.get('response', '')),
            rating="negative",
            feedback_text=feedback_text,
            suggested_collection=suggested_collection,
            user_comment=comment if comment else None,
            session_id=session_id
        )
        print("✅ Thank you for your feedback! This helps us improve.")
    
    else:
        print("Invalid choice. Feedback skipped.")


def interactive_session():
    """Run an interactive query session with feedback collection."""
    print("=" * 70)
    print("Egeria Advisor - Interactive Session with Feedback")
    print("=" * 70)
    print("\nType 'quit' or 'exit' to end the session")
    print("Type 'stats' to see feedback statistics")
    print()
    
    # Initialize RAG system
    rag = get_rag_system()
    collector = get_feedback_collector()
    
    # Generate session ID
    session_id = str(uuid.uuid4())[:8]
    logger.info(f"Started session: {session_id}")
    
    query_count = 0
    
    while True:
        # Get user query
        query = input("\n🔍 Your question: ").strip()
        
        if not query:
            continue
        
        if query.lower() in ['quit', 'exit']:
            print("\nThank you for using Egeria Advisor!")
            
            # Show session statistics
            stats = collector.get_feedback_stats()
            if stats['total'] > 0:
                print(f"\nSession feedback: {stats['positive']} positive, {stats['negative']} negative")
                print(f"Overall satisfaction: {stats['satisfaction_rate']:.1%}")
            
            break
        
        if query.lower() == 'stats':
            # Show feedback statistics
            stats = collector.get_feedback_stats()
            print("\n📊 Feedback Statistics")
            print("─" * 70)
            print(f"Total feedback: {stats['total']}")
            print(f"Positive: {stats['positive']} ({stats['positive']/stats['total']*100:.1f}%)" if stats['total'] > 0 else "No feedback yet")
            print(f"Negative: {stats['negative']} ({stats['negative']/stats['total']*100:.1f}%)" if stats['total'] > 0 else "")
            print(f"Satisfaction rate: {stats['satisfaction_rate']:.1%}" if stats['total'] > 0 else "")
            continue
        
        query_count += 1
        
        try:
            # Process query
            print("\n⏳ Processing...")
            result = rag.query(query, track_metrics=False)
            
            # Display response
            print("\n" + "=" * 70)
            print("📝 Response:")
            print("=" * 70)
            print(result['response'])
            print("\n" + "─" * 70)
            print(f"Query type: {result['query_type']}")
            print(f"Sources: {result['num_sources']}")
            if 'collections_searched' in result:
                print(f"Collections: {', '.join(result.get('collections_searched', []))}")
            print("─" * 70)
            
            # Prompt for feedback
            prompt_for_feedback(query, result, session_id)
            
        except Exception as e:
            logger.error(f"Error processing query: {e}")
            print(f"\n❌ Error: {e}")
            print("Please try rephrasing your question.")


def main():
    """Main entry point."""
    try:
        interactive_session()
    except KeyboardInterrupt:
        print("\n\nSession interrupted. Goodbye!")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        print(f"\n❌ Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()