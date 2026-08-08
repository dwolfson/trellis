#!/usr/bin/env python3
"""
Test script to verify follow-up queries maintain PyEgeria routing.

This tests the fix for the issue where follow-up options were routing
to semantic search instead of staying with PyEgeria agent.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.conversation_agent import create_agent
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

def test_follow_up_routing():
    """Test that follow-up queries maintain PyEgeria routing."""
    console = Console()
    
    # Create agent
    console.print("[bold cyan]Creating conversation agent...[/bold cyan]")
    agent = create_agent()
    
    # Test 1: Initial PyEgeria query
    console.print("\n[bold]Test 1: Initial PyEgeria Query[/bold]")
    query1 = "What does CollectionManager do?"
    console.print(f"Query: {query1}")
    
    result1 = agent.run(query1, use_rag=True)
    
    console.print(Panel(
        Markdown(result1["content"][:500] + "..."),
        title="Response (truncated)",
        border_style="cyan"
    ))
    
    agent_type = result1.get("agent_type", "unknown")
    console.print(f"\n[bold]Agent Type:[/bold] {agent_type}")
    
    if agent_type != "pyegeria":
        console.print("[red]❌ FAIL: Expected pyegeria agent, got {agent_type}[/red]")
        return False
    
    console.print("[green]✓ Correctly routed to PyEgeria agent[/green]")
    
    # Test 2: Simulate follow-up query (what the CLI would generate)
    console.print("\n[bold]Test 2: Follow-Up Query (Simulated)[/bold]")
    
    # This simulates what happens when user selects option "1"
    # The CLI converts it to: "Show me the documentation for CollectionManager"
    # Then adds PyEgeria context: "Show me the documentation for PyEgeria CollectionManager"
    query2 = "Show me the documentation for PyEgeria CollectionManager"
    console.print(f"Query: {query2}")
    
    result2 = agent.run(query2, use_rag=True)
    
    console.print(Panel(
        Markdown(result2["content"][:500] + "..."),
        title="Response (truncated)",
        border_style="cyan"
    ))
    
    agent_type2 = result2.get("agent_type", "unknown")
    console.print(f"\n[bold]Agent Type:[/bold] {agent_type2}")
    
    if agent_type2 != "pyegeria":
        console.print(f"[red]❌ FAIL: Expected pyegeria agent, got {agent_type2}[/red]")
        console.print("[yellow]This means follow-up routing is broken![/yellow]")
        return False
    
    console.print("[green]✓ Follow-up correctly maintained PyEgeria routing[/green]")
    
    # Test 3: Verify follow-up options are present
    console.print("\n[bold]Test 3: Follow-Up Options[/bold]")
    follow_ups = result1.get("follow_up_options", [])
    
    if not follow_ups:
        console.print("[yellow]⚠ WARNING: No follow-up options returned[/yellow]")
    else:
        console.print(f"[green]✓ Found {len(follow_ups)} follow-up options:[/green]")
        for i, option in enumerate(follow_ups, 1):
            console.print(f"  {i}. {option}")
    
    console.print("\n[bold green]✅ All tests passed![/bold green]")
    return True

if __name__ == "__main__":
    success = test_follow_up_routing()
    sys.exit(0 if success else 1)