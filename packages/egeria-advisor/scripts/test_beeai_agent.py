#!/usr/bin/env python3
"""
Test script for BeeAI-based Egeria Agent.

This script tests the agent's ability to:
1. Answer questions using RAG tools
2. Manage conversation memory
3. Cache responses
4. Use multiple tools intelligently
"""

import sys
import asyncio
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.table import Table

from advisor.agents.beeai_agent import create_egeria_agent


console = Console()


async def test_basic_query():
    """Test basic query with tool usage."""
    console.print("\n[bold cyan]Test 1: Basic Query[/bold cyan]")
    
    agent = create_egeria_agent()
    
    query = "How do I create a connection in Egeria?"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    response = await agent.run(query)
    
    console.print(Panel(
        Markdown(response.content),
        title="Agent Response",
        border_style="green"
    ))
    
    console.print(f"\n[dim]Metadata: {response.metadata}[/dim]")
    
    return agent


async def test_code_analysis():
    """Test code analysis tool."""
    console.print("\n[bold cyan]Test 2: Code Analysis[/bold cyan]")
    
    agent = create_egeria_agent()
    
    query = "Find all classes related to asset management"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    response = await agent.run(query)
    
    console.print(Panel(
        Markdown(response.content),
        title="Agent Response",
        border_style="green"
    ))
    
    console.print(f"\n[dim]Metadata: {response.metadata}[/dim]")


async def test_documentation_lookup():
    """Test documentation lookup."""
    console.print("\n[bold cyan]Test 3: Documentation Lookup[/bold cyan]")
    
    agent = create_egeria_agent()
    
    query = "What is the Egeria architecture?"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    response = await agent.run(query)
    
    console.print(Panel(
        Markdown(response.content),
        title="Agent Response",
        border_style="green"
    ))
    
    console.print(f"\n[dim]Metadata: {response.metadata}[/dim]")


async def test_conversation_memory():
    """Test conversation memory across multiple queries."""
    console.print("\n[bold cyan]Test 4: Conversation Memory[/bold cyan]")
    
    agent = create_egeria_agent()
    
    queries = [
        "What is a connection in Egeria?",
        "How do I create one?",
        "Can you show me an example?"
    ]
    
    for i, query in enumerate(queries, 1):
        console.print(f"\n[yellow]Query {i}:[/yellow] {query}")
        
        response = await agent.run(query)
        
        console.print(Panel(
            Markdown(response.content[:500] + "..." if len(response.content) > 500 else response.content),
            title=f"Response {i}",
            border_style="green"
        ))
    
    # Show memory stats
    stats = agent.get_stats()
    console.print(f"\n[dim]Agent Stats: {stats}[/dim]")


async def test_cache_performance():
    """Test response caching."""
    console.print("\n[bold cyan]Test 5: Cache Performance[/bold cyan]")
    
    agent = create_egeria_agent()
    
    query = "How do I connect to an Egeria server?"
    
    # First query (cache miss)
    console.print(f"\n[yellow]First Query (cache miss):[/yellow] {query}")
    import time
    start = time.time()
    response1 = await agent.run(query)
    time1 = time.time() - start
    console.print(f"[dim]Time: {time1:.3f}s, Cache hit: {response1.metadata.get('cache_hit', False)}[/dim]")
    
    # Second query (cache hit)
    console.print(f"\n[yellow]Second Query (cache hit):[/yellow] {query}")
    start = time.time()
    response2 = await agent.run(query)
    time2 = time.time() - start
    console.print(f"[dim]Time: {time2:.3f}s, Cache hit: {response2.metadata.get('cache_hit', False)}[/dim]")
    
    # Show speedup
    if time2 > 0:
        speedup = time1 / time2
        console.print(f"\n[green]✓ Cache speedup: {speedup:.1f}x[/green]")


async def test_multi_tool_usage():
    """Test using multiple tools for a complex query."""
    console.print("\n[bold cyan]Test 6: Multi-Tool Usage[/bold cyan]")
    
    agent = create_egeria_agent()
    
    query = "Show me how to implement asset management, including relevant classes and documentation"
    console.print(f"\n[yellow]Query:[/yellow] {query}")
    
    response = await agent.run(query)
    
    console.print(Panel(
        Markdown(response.content),
        title="Agent Response",
        border_style="green"
    ))
    
    tools_used = response.metadata.get('tools_used', [])
    console.print(f"\n[dim]Tools used: {', '.join(tools_used) if tools_used else 'None'}[/dim]")


async def run_all_tests():
    """Run all tests."""
    console.print(Panel(
        "[bold]BeeAI Egeria Agent Test Suite[/bold]\n"
        "Testing agent capabilities with optimized RAG retrieval",
        border_style="blue"
    ))
    
    try:
        # Run tests
        await test_basic_query()
        await test_code_analysis()
        await test_documentation_lookup()
        await test_conversation_memory()
        await test_cache_performance()
        await test_multi_tool_usage()
        
        console.print("\n[bold green]✓ All tests completed![/bold green]")
        
    except Exception as e:
        console.print(f"\n[bold red]✗ Test failed: {e}[/bold red]")
        import traceback
        console.print(traceback.format_exc())


async def interactive_mode():
    """Interactive chat mode."""
    console.print(Panel(
        "[bold]Interactive Agent Mode[/bold]\n"
        "Chat with the Egeria agent. Type 'quit' to exit.",
        border_style="blue"
    ))
    
    agent = create_egeria_agent()
    
    while True:
        try:
            query = console.input("\n[bold cyan]You:[/bold cyan] ")
            
            if query.lower() in ['quit', 'exit', 'q']:
                break
            
            if not query.strip():
                continue
            
            # Show thinking indicator
            with console.status("[bold green]Agent thinking...", spinner="dots"):
                response = await agent.run(query)
            
            console.print("\n[bold green]Agent:[/bold green]")
            console.print(Panel(
                Markdown(response.content),
                border_style="green"
            ))
            
            # Show metadata
            if response.metadata.get('tools_used'):
                console.print(f"[dim]Tools: {', '.join(response.metadata['tools_used'])}[/dim]")
            if response.metadata.get('cache_hit'):
                console.print("[dim]⚡ Cache hit[/dim]")
        
        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
    
    # Show final stats
    stats = agent.get_stats()
    console.print(f"\n[dim]Session stats: {stats}[/dim]")
    console.print("\n[yellow]Goodbye![/yellow]")


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Test BeeAI Egeria Agent")
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Run in interactive mode"
    )
    parser.add_argument(
        "--test", "-t",
        type=str,
        help="Run specific test (basic, code, docs, memory, cache, multi)"
    )
    
    args = parser.parse_args()
    
    if args.interactive:
        asyncio.run(interactive_mode())
    elif args.test:
        test_map = {
            "basic": test_basic_query,
            "code": test_code_analysis,
            "docs": test_documentation_lookup,
            "memory": test_conversation_memory,
            "cache": test_cache_performance,
            "multi": test_multi_tool_usage
        }
        
        if args.test in test_map:
            asyncio.run(test_map[args.test]())
        else:
            console.print(f"[red]Unknown test: {args.test}[/red]")
            console.print(f"Available tests: {', '.join(test_map.keys())}")
    else:
        asyncio.run(run_all_tests())


if __name__ == "__main__":
    main()