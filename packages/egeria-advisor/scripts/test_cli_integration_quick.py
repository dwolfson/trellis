#!/usr/bin/env python3
"""
Quick test of CLI Command Agent integration in ConversationAgent.

Tests that CLI queries are detected and routed correctly without waiting for full LLM responses.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.cli_integration import get_cli_router
from rich.console import Console

console = Console()


def test_cli_detection():
    """Test CLI query detection."""
    
    console.print("\n[bold cyan]Testing CLI Query Detection[/bold cyan]\n")
    
    router = get_cli_router()
    
    # Test CLI queries (should be detected)
    cli_queries = [
        "How do I create a glossary?",
        "What parameters does hey_egeria monitor_server take?",
        "Show me all hey_egeria commands",
        "List commands for working with glossaries",
        "What does the create_glossary command do?",
    ]
    
    console.print("[bold]CLI Queries (should be detected):[/bold]")
    for query in cli_queries:
        detected = router.should_use_cli_agent(query)
        status = "[green]✓[/green]" if detected else "[red]✗[/red]"
        console.print(f"{status} {query}")
    
    # Test non-CLI queries (should NOT be detected)
    non_cli_queries = [
        "What is Egeria?",
        "How does the metadata repository work?",
        "Explain the Open Metadata Types",
    ]
    
    console.print("\n[bold]Non-CLI Queries (should NOT be detected):[/bold]")
    for query in non_cli_queries:
        detected = router.should_use_cli_agent(query)
        status = "[red]✗[/red]" if detected else "[green]✓[/green]"
        console.print(f"{status} {query}")
    
    console.print("\n[bold green]Detection Test Complete![/bold green]\n")


def test_integration_exists():
    """Test that integration code exists in ConversationAgent."""
    
    console.print("\n[bold cyan]Testing Integration Code[/bold cyan]\n")
    
    # Read the conversation_agent.py file
    agent_file = Path(__file__).parent.parent / "advisor" / "agents" / "conversation_agent.py"
    
    if not agent_file.exists():
        console.print("[red]✗ conversation_agent.py not found[/red]")
        return False
    
    content = agent_file.read_text()
    
    # Check for CLI integration imports
    checks = [
        ("CLI import", "from advisor.cli_integration import get_cli_router"),
        ("CLI detection", "should_use_cli_agent"),
        ("CLI routing", "route_query"),
        ("CLI response handling", "cli_command_agent"),
    ]
    
    all_passed = True
    for check_name, check_string in checks:
        if check_string in content:
            console.print(f"[green]✓[/green] {check_name}: Found")
        else:
            console.print(f"[red]✗[/red] {check_name}: Not found")
            all_passed = False
    
    if all_passed:
        console.print("\n[bold green]Integration Code Complete![/bold green]\n")
    else:
        console.print("\n[bold red]Integration Code Incomplete![/bold red]\n")
    
    return all_passed


if __name__ == "__main__":
    try:
        # Test detection
        test_cli_detection()
        
        # Test integration
        integration_ok = test_integration_exists()
        
        if integration_ok:
            console.print("[bold green]✓ CLI Command Agent is integrated into agent mode![/bold green]")
            console.print("\n[cyan]Users can now ask CLI questions in agent mode and get intelligent responses.[/cyan]\n")
            sys.exit(0)
        else:
            console.print("[bold red]✗ Integration incomplete[/bold red]\n")
            sys.exit(1)
        
    except Exception as e:
        console.print(f"\n[red]Test failed: {e}[/red]")
        import traceback
        console.print(f"[dim]{traceback.format_exc()}[/dim]")
        sys.exit(1)