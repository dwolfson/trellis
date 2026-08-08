#!/usr/bin/env python3
"""
Test script for ConversationAgent.

Tests the simple agent using existing LLMClient and RAG retrieval.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from advisor.agents.conversation_agent import create_agent


console = Console()


def test_basic_query():
    """Test basic query with RAG."""
    console.print("\n[bold cyan]Test 1: Basic Query with RAG[/bold cyan]")
    
    agent = create_agent()
    
    query = "How do I create a connection in Egeria?"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    response = agent.run(query)
    
    console.print(Panel(
        Markdown(response["content"]),
        title="Agent Response",
        border_style="green"
    ))
    
    # Show sources
    if response["sources"]:
        console.print(f"\n[dim]Sources ({len(response['sources'])}):[/dim]")
        for source in response["sources"][:3]:
            console.print(f"  • [{source['collection']}] {source['file_path']} (score: {source['score']})")
    
    console.print(f"\n[dim]RAG used: {response['rag_used']}, Cache hit: {response['cache_hit']}[/dim]")


def test_cache():
    """Test caching."""
    console.print("\n[bold cyan]Test 2: Cache Performance[/bold cyan]")
    
    agent = create_agent()
    
    query = "What is an asset in Egeria?"
    
    # First query
    console.print(f"\n[yellow]First Query:[/yellow] {query}")
    import time
    start = time.time()
    response1 = agent.run(query)
    time1 = time.time() - start
    console.print(f"[dim]Time: {time1:.3f}s, Cache hit: {response1['cache_hit']}[/dim]")
    
    # Second query (should be cached)
    console.print(f"\n[yellow]Second Query (cached):[/yellow] {query}")
    start = time.time()
    response2 = agent.run(query)
    time2 = time.time() - start
    console.print(f"[dim]Time: {time2:.3f}s, Cache hit: {response2['cache_hit']}[/dim]")
    
    if time2 > 0:
        speedup = time1 / time2
        console.print(f"\n[green]✓ Cache speedup: {speedup:.1f}x[/green]")


def test_conversation():
    """Test conversation history."""
    console.print("\n[bold cyan]Test 3: Conversation History[/bold cyan]")
    
    agent = create_agent(max_history=5)
    
    queries = [
        "What is a connection in Egeria?",
        "How do I create one?",
        "Can you show me an example?"
    ]
    
    for i, query in enumerate(queries, 1):
        console.print(f"\n[yellow]Query {i}:[/yellow] {query}")
        response = agent.run(query)
        console.print(f"[green]Response:[/green] {response['content'][:200]}...")
    
    # Show history
    history = agent.get_history()
    console.print(f"\n[dim]Conversation history: {len(history)} turns[/dim]")


def test_stats():
    """Test statistics."""
    console.print("\n[bold cyan]Test 4: Agent Statistics[/bold cyan]")
    
    agent = create_agent()
    
    # Run some queries
    queries = [
        "What is Egeria?",
        "How do I use pyegeria?",
        "What is Egeria?",  # Repeat for cache hit
    ]
    
    for query in queries:
        agent.run(query)
    
    # Get stats
    stats = agent.get_stats()
    
    table = Table(title="Agent Statistics")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    
    table.add_row("Conversation Turns", str(stats["conversation_turns"]))
    table.add_row("Cache Hits", str(stats["cache_hits"]))
    table.add_row("Cache Misses", str(stats["cache_misses"]))
    table.add_row("Cache Hit Rate", f"{stats['cache_hit_rate']:.1%}")
    table.add_row("Cache Size", f"{stats['cache_size']}/{stats['cache_max_size']}")
    
    console.print(table)


def interactive_mode():
    """Interactive chat mode."""
    console.print(Panel(
        "[bold]Interactive Agent Mode[/bold]\n"
        "Chat with the Egeria agent. Type 'quit' to exit, 'stats' for statistics.",
        border_style="blue"
    ))
    
    agent = create_agent()
    
    while True:
        try:
            query = console.input("\n[bold cyan]You:[/bold cyan] ")
            
            if query.lower() in ['quit', 'exit', 'q']:
                break
            
            if query.lower() == 'stats':
                stats = agent.get_stats()
                console.print(f"\n[dim]{stats}[/dim]")
                continue
            
            if not query.strip():
                continue
            
            response = agent.run(query)
            
            console.print("\n[bold green]Agent:[/bold green]")
            console.print(Panel(
                Markdown(response["content"]),
                border_style="green"
            ))
            
            if response["sources"]:
                console.print(f"[dim]Sources: {len(response['sources'])}[/dim]")
            if response["cache_hit"]:
                console.print("[dim]⚡ Cache hit[/dim]")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            import traceback
            console.print(traceback.format_exc())
    
    stats = agent.get_stats()
    console.print(f"\n[dim]Session stats: {stats}[/dim]")
    console.print("\n[yellow]Goodbye![/yellow]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Conversation Agent")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--test", "-t",
        type=str,
        choices=["basic", "cache", "conversation", "stats"],
        help="Run specific test"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        interactive_mode()
    elif args.test == "basic":
        test_basic_query()
    elif args.test == "cache":
        test_cache()
    elif args.test == "conversation":
        test_conversation()
    elif args.test == "stats":
        test_stats()
    else:
        # Run all tests
        console.print(Panel(
            "[bold]Conversation Agent Test Suite[/bold]\n"
            "Testing simple agent with existing LLMClient and RAG",
            border_style="blue"
        ))
        
        try:
            test_basic_query()
            test_cache()
            test_conversation()
            test_stats()
            console.print("\n[bold green]✓ All tests completed![/bold green]")
        except Exception as e:
            console.print(f"\n[bold red]✗ Test failed: {e}[/bold red]")
            import traceback
            console.print(traceback.format_exc())


if __name__ == "__main__":
    main()