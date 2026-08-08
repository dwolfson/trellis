#!/usr/bin/env python3
"""
Test script to verify feedback integration in the CLI.

This script tests that:
1. Feedback collector is properly initialized
2. /feedback and /stats commands are available
3. Feedback can be recorded and retrieved
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.feedback_collector import get_feedback_collector
from advisor.cli.interactive import InteractiveSession
from rich.console import Console


def test_feedback_collector():
    """Test that feedback collector works."""
    print("Testing feedback collector...")
    
    collector = get_feedback_collector()
    
    # Record test feedback
    success = collector.record_feedback(
        query="Test query",
        query_type="test",
        collections_searched=["test_collection"],
        response_length=100,
        rating="positive",
        user_comment="Test comment",
        session_id="test_session"
    )
    
    assert success, "Failed to record feedback"
    print("✓ Feedback recorded successfully")
    
    # Get stats
    stats = collector.get_feedback_stats()
    assert stats['total'] > 0, "No feedback found"
    print(f"✓ Feedback stats retrieved: {stats['total']} total entries")
    
    return True


def test_interactive_session_init():
    """Test that InteractiveSession initializes with feedback support."""
    print("\nTesting InteractiveSession initialization...")
    
    from advisor.rag_system import get_rag_system
    
    console = Console()
    rag = get_rag_system()
    
    options = {
        'verbose': False,
        'show_citations': True,
        'track_metrics': True,
        'enable_feedback': True,
    }
    
    session = InteractiveSession(rag, options, console)
    
    # Check that feedback collector is initialized
    assert session.feedback_collector is not None, "Feedback collector not initialized"
    print("✓ Feedback collector initialized in session")
    
    # Check that session_id is set
    assert session.session_id is not None, "Session ID not set"
    print(f"✓ Session ID set: {session.session_id}")
    
    # Check that commands include feedback commands
    assert '/feedback' in session.COMMANDS, "/feedback command not found"
    assert '/stats' in session.COMMANDS, "/stats command not found"
    print("✓ Feedback commands registered")
    
    # Check that methods exist
    assert hasattr(session, '_prompt_for_feedback'), "_prompt_for_feedback method missing"
    assert hasattr(session, '_handle_feedback_command'), "_handle_feedback_command method missing"
    assert hasattr(session, '_show_feedback_stats'), "_show_feedback_stats method missing"
    print("✓ All feedback methods present")
    
    return True


def test_feedback_disabled():
    """Test that feedback can be disabled."""
    print("\nTesting feedback disabled mode...")
    
    from advisor.rag_system import get_rag_system
    
    console = Console()
    rag = get_rag_system()
    
    options = {
        'verbose': False,
        'show_citations': True,
        'track_metrics': True,
        'enable_feedback': False,  # Disabled
    }
    
    session = InteractiveSession(rag, options, console)
    
    # Check that feedback collector is None when disabled
    assert session.feedback_collector is None, "Feedback collector should be None when disabled"
    print("✓ Feedback collector is None when disabled")
    
    return True


def main():
    """Run all tests."""
    print("=" * 70)
    print("Testing Feedback Integration in CLI")
    print("=" * 70)
    
    try:
        # Test 1: Feedback collector
        test_feedback_collector()
        
        # Test 2: Interactive session with feedback enabled
        test_interactive_session_init()
        
        # Test 3: Interactive session with feedback disabled
        test_feedback_disabled()
        
    except AssertionError as e:
        print(f"\n✗ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "=" * 70)
    print("✓ All tests passed!")
    print("=" * 70)
    
    print("\nTo test interactively, run:")
    print("  egeria-advisor --interactive")
    print("\nThen try:")
    print("  1. Ask a question")
    print("  2. Type /feedback to provide feedback")
    print("  3. Type /stats to see statistics")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())