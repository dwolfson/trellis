#!/usr/bin/env python3
"""
Test script for Simple Egeria Agent.

This script tests the simplified agent that uses BeeAI components
without inheriting from base classes.
"""

import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

from advisor.agents.simple_agent import create_simple_agent


console = Console()


async def test_basic_query():
    """Test basic query."""
    console.print("\n[bold cyan]Test: Basic Query[/bold cyan]")
    
    agent = create_simple_agent()
    
    query = "How do I create a connection in Egeria?"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    with console.status("[bold green]Agent thinking...", spinner="dots"):
        response = await agent.run(query)
    
    console.print(Panel(
        Markdown(response["content"]),
        title="Agent Response",
        border_style="green"
    ))
    
    console.print(f"\n[dim]Metadata: {response['metadata']}[/dim]")
    console.print(f"[dim]Stats: {agent.get_stats()}[/dim]")


async def test_cache():
    """Test caching."""
    console.print("\n[bold cyan]Test: Cache Performance[/bold cyan]")
    
    agent = create_simple_agent()
    
    query = "What is an asset in Egeria?"
    
    # First query
    console.print(f"\n[yellow]First Query:[/yellow] {query}")
    import time
    start = time.time()
    response1 = await agent.run(query)
    time1 = time.time() - start
    console.print(f"[dim]Time: {time1:.3f}s, Cache hit: {response1['metadata']['cache_hit']}[/dim]")
    
    # Second query (should be cached)
    console.print(f"\n[yellow]Second Query (cached):[/yellow] {query}")
    start = time.time()
    response2 = await agent.run(query)
    time2 = time.time() - start
    console.print(f"[dim]Time: {time2:.3f}s, Cache hit: {response2['metadata']['cache_hit']}[/dim]")
    
    if time2 > 0:
        speedup = time1 / time2
        console.print(f"\n[green]✓ Cache speedup: {speedup:.1f}x[/green]")


async def interactive_mode():
    """Interactive chat mode."""
    console.print(Panel(
        "[bold]Interactive Agent Mode[/bold]\n"
        "Chat with the Egeria agent. Type 'quit' to exit.",
        border_style="blue"
    ))
    
    agent = create_simple_agent()
    
    while True:
        try:
            query = console.input("\n[bold cyan]You:[/bold cyan] ")
            
            if query.lower() in ['quit', 'exit', 'q']:
                break
            
            if not query.strip():
                continue
            
            with console.status("[bold green]Agent thinking...", spinner="dots"):
                response = await agent.run(query)
            
            console.print("\n[bold green]Agent:[/bold green]")
            console.print(Panel(
                Markdown(response["content"]),
                border_style="green"
            ))
            
            if response["metadata"].get("cache_hit"):
                console.print("[dim]⚡ Cache hit[/dim]")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    
    stats = agent.get_stats()
    console.print(f"\n[dim]Session stats: {stats}[/dim]")
    console.print("\n[yellow]Goodbye![/yellow]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test Simple Egeria Agent")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--test", "-t",
        type=str,
        choices=["basic", "cache"],
        help="Run specific test"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        asyncio.run(interactive_mode())
    elif args.test == "basic":
        asyncio.run(test_basic_query())
    elif args.test == "cache":
        asyncio.run(test_cache())
    else:
        # Run both tests
        console.print(Panel(
            "[bold]Simple Egeria Agent Test Suite[/bold]\n"
            "Testing simplified agent with BeeAI components",
            border_style="blue"
        ))
        asyncio.run(test_basic_query())
        asyncio.run(test_cache())
        console.print("\n[bold green]✓ All tests completed![/bold green]")


if __name__ == "__main__":
    main()