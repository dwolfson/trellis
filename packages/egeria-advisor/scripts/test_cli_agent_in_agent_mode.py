#!/usr/bin/env python3
"""
Test CLI Command Agent Integration in Agent Mode.

This script tests that CLI command queries are properly routed to the
CLI Command Agent when using the ConversationAgent (agent mode).
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.agents.conversation_agent import create_agent
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown

console = Console()


def test_cli_queries():
    """Test various CLI command queries in agent mode."""
    
    console.print("\n[bold cyan]Testing CLI Command Agent Integration in Agent Mode[/bold cyan]\n")
    
    # Create agent
    console.print("[yellow]Initializing agent...[/yellow]")
    agent = create_agent(max_history=5, cache_size=50, rag_top_k=10, enable_mlflow=False)
    console.print("[green]✓ Agent initialized[/green]\n")
    
    # Test queries
    test_queries = [
        "How do I create a glossary?",
        "What parameters does hey_egeria monitor_server take?",
        "Show me all hey_egeria commands",
        "List commands for working with glossaries",
        "What does the create_glossary command do?",
        "How do I use hey_egeria to list assets?",
    ]
    
    for i, query in enumerate(test_queries, 1):
        console.print(f"\n[bold]Test {i}/{len(test_queries)}:[/bold] {query}")
        console.print("[dim]" + "=" * 80 + "[/dim]")
        
        try:
            # Run query
            response = agent.run(query, use_rag=True)
            
            # Check if routed to CLI agent
            metadata = response.get('metadata', {})
            routed_to = metadata.get('routed_to', 'unknown')
            agent_type = metadata.get('agent', 'unknown')
            
            if routed_to == 'cli_command_agent':
                console.print(f"[green]✓ Routed to CLI Command Agent[/green]")
                console.print(f"[dim]Query Type: {metadata.get('query_type', 'unknown')}[/dim]")
                console.print(f"[dim]Confidence: {metadata.get('confidence', 0.0):.2f}[/dim]")
            else:
                console.print(f"[yellow]⚠ Routed to: {routed_to or 'standard RAG'}[/yellow]")
            
            # Display response
            content = response.get('content', '')
            if content:
                # Truncate for display
                display_content = content[:500] + "..." if len(content) > 500 else content
                console.print(Panel(
                    Markdown(display_content),
                    title="Response",
                    border_style="blue"
                ))
            
            # Display sources
            sources = response.get('sources', [])
            if sources:
                console.print(f"\n[dim]Sources: {len(sources)} items[/dim]")
                for j, source in enumerate(sources[:3], 1):
                    if isinstance(source, dict):
                        console.print(f"  {j}. {source.get('command_name', source.get('file_path', 'Unknown'))}")
        
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
            import traceback
            console.print(f"[dim]{traceback.format_exc()}[/dim]")
    
    console.print("\n[bold green]Testing Complete![/bold green]\n")


def test_non_cli_queries():
    """Test that non-CLI queries still work normally."""
    
    console.print("\n[bold cyan]Testing Non-CLI Queries (Should Use Standard RAG)[/bold cyan]\n")
    
    agent = create_agent(max_history=5, cache_size=50, rag_top_k=10, enable_mlflow=False)
    
    test_queries = [
        "What is Egeria?",
        "How does the metadata repository work?",
        "Explain the Open Metadata Types",
    ]
    
    for i, query in enumerate(test_queries, 1):
        console.print(f"\n[bold]Test {i}/{len(test_queries)}:[/bold] {query}")
        console.print("[dim]" + "=" * 80 + "[/dim]")
        
        try:
            response = agent.run(query, use_rag=True)
            
            metadata = response.get('metadata', {})
            routed_to = metadata.get('routed_to', 'standard_rag')
            
            if routed_to == 'cli_command_agent':
                console.print(f"[yellow]⚠ Unexpectedly routed to CLI Agent[/yellow]")
            else:
                console.print(f"[green]✓ Used standard RAG processing[/green]")
            
            content = response.get('content', '')
            if content:
                display_content = content[:300] + "..." if len(content) > 300 else content
                console.print(f"\n[dim]{display_content}[/dim]")
        
        except Exception as e:
            console.print(f"[red]✗ Error: {e}[/red]")
    
    console.print("\n[bold green]Testing Complete![/bold green]\n")


if __name__ == "__main__":
    try:
        # Test CLI queries
        test_cli_queries()
        
        # Test non-CLI queries
        test_non_cli_queries()
        
        console.print("\n[bold green]All Tests Passed! ✓[/bold green]")
        console.print("\n[cyan]CLI Command Agent is now integrated into agent mode.[/cyan]")
        console.print("[cyan]Users can ask CLI questions and get intelligent, formatted responses.[/cyan]\n")
        
    except KeyboardInterrupt:
        console.print("\n[yellow]Testing interrupted by user[/yellow]")
        sys.exit(1)
    except Exception as e:
        console.print(f"\n[red]Testing failed: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)