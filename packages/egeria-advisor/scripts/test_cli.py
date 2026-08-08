#!/usr/bin/env python3
"""
Test script for Egeria Advisor CLI

This script tests the CLI components without requiring full installation.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from rich.console import Console

console = Console()


def test_imports():
    """Test that all CLI modules can be imported."""
    console.print("[bold cyan]Testing CLI Imports...[/bold cyan]\n")
    
    tests = [
        ("advisor.cli.main", "Main CLI module"),
        ("advisor.cli.formatters", "Formatters module"),
        ("advisor.cli.interactive", "Interactive module"),
    ]
    
    passed = 0
    failed = 0
    
    for module_name, description in tests:
        try:
            __import__(module_name)
            console.print(f"  [green]✓[/green] {description}")
            passed += 1
        except ImportError as e:
            console.print(f"  [red]✗[/red] {description}: {e}")
            failed += 1
    
    console.print()
    return passed, failed


def test_formatter():
    """Test the response formatter."""
    console.print("[bold cyan]Testing Response Formatter...[/bold cyan]\n")
    
    try:
        from advisor.cli.formatters import ResponseFormatter
        
        # Create sample result
        sample_result = {
            'query': 'What is a glossary?',
            'response': 'A glossary is a collection of terms and their definitions.',
            'sources': [
                {
                    'file_path': 'pyegeria/glossary_manager.py',
                    'name': 'GlossaryManager',
                    'score': 0.95
                }
            ],
            'response_time': 1.23,
            'confidence': 0.92
        }
        
        # Test text formatter
        formatter = ResponseFormatter(format_type='text', show_citations=True, verbose=True)
        console.print("  [green]✓[/green] Text formatter created")
        
        # Test JSON formatter
        formatter_json = ResponseFormatter(format_type='json')
        console.print("  [green]✓[/green] JSON formatter created")
        
        # Test markdown formatter
        formatter_md = ResponseFormatter(format_type='markdown')
        console.print("  [green]✓[/green] Markdown formatter created")
        
        console.print()
        console.print("[bold]Sample Output (Text Format):[/bold]")
        console.print("─" * 60)
        formatter.display(sample_result, console)
        
        return True
    
    except Exception as e:
        console.print(f"  [red]✗[/red] Formatter test failed: {e}")
        console.print_exception()
        return False


def test_cli_help():
    """Test CLI help command."""
    console.print("\n[bold cyan]Testing CLI Help...[/bold cyan]\n")
    
    try:
        from advisor.cli.main import cli
        from click.testing import CliRunner
        
        runner = CliRunner()
        result = runner.invoke(cli, ['--help'])
        
        if result.exit_code == 0:
            console.print("  [green]✓[/green] CLI help command works")
            console.print("\n[bold]CLI Help Output:[/bold]")
            console.print("─" * 60)
            console.print(result.output)
            return True
        else:
            console.print(f"  [red]✗[/red] CLI help failed with exit code {result.exit_code}")
            return False
    
    except Exception as e:
        console.print(f"  [red]✗[/red] CLI help test failed: {e}")
        console.print_exception()
        return False


def main():
    """Run all tests."""
    console.print("\n" + "=" * 60)
    console.print("[bold cyan]Egeria Advisor CLI Test Suite[/bold cyan]")
    console.print("=" * 60 + "\n")
    
    # Test imports
    passed, failed = test_imports()
    
    # Test formatter if imports passed
    if failed == 0:
        formatter_ok = test_formatter()
        cli_ok = test_cli_help()
    else:
        console.print("[yellow]⚠[/yellow] Skipping other tests due to import failures")
        console.print("[dim]Install dependencies: pip install -e \".[dev]\"[/dim]\n")
        return 1
    
    # Summary
    console.print("\n" + "=" * 60)
    console.print("[bold cyan]Test Summary[/bold cyan]")
    console.print("=" * 60)
    console.print(f"  Imports: [green]{passed} passed[/green], [red]{failed} failed[/red]")
    
    if failed == 0:
        console.print("  [green]✓[/green] All tests passed!")
        console.print("\n[bold]Next Steps:[/bold]")
        console.print("  1. Install dependencies: [cyan]pip install -e \".[dev]\"[/cyan]")
        console.print("  2. Try the CLI: [cyan]egeria-advisor --help[/cyan]")
        console.print("  3. Ask a question: [cyan]egeria-advisor \"What is a glossary?\"[/cyan]")
        console.print("  4. Interactive mode: [cyan]egeria-advisor --interactive[/cyan]")
        return 0
    else:
        console.print("  [red]✗[/red] Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())