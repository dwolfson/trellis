#!/usr/bin/env python3
"""
Test script to verify RAG quality improvements.

This script tests the same queries from the diagnostic to verify that:
1. min_score threshold filters out low-quality results
2. File type boosting prioritizes test files and code
3. Fewer markdown docs pollute code query results
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_retrieval import RAGRetriever
from advisor.config import get_full_config
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def analyze_results(results, query_desc):
    """Analyze and display result quality metrics."""
    
    if not results:
        console.print(f"[red]No results for: {query_desc}[/red]")
        return
    
    # Count file types
    code_count = 0
    test_count = 0
    markdown_count = 0
    
    for result in results:
        file_path = result.metadata.get("file_path", "")
        if "/test" in file_path.lower() or file_path.endswith("_test.py"):
            test_count += 1
            code_count += 1
        elif file_path.endswith(".py"):
            code_count += 1
        elif file_path.endswith(".md"):
            markdown_count += 1
    
    # Calculate metrics
    total = len(results)
    code_pct = (code_count / total * 100) if total > 0 else 0
    test_pct = (test_count / total * 100) if total > 0 else 0
    md_pct = (markdown_count / total * 100) if total > 0 else 0
    
    # Get score range
    scores = [r.score for r in results]
    min_score = min(scores) if scores else 0
    max_score = max(scores) if scores else 0
    avg_score = sum(scores) / len(scores) if scores else 0
    
    # Create metrics table
    table = Table(title=f"Results for: {query_desc}", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Target", style="yellow")
    table.add_column("Status", style="bold")
    
    # Total results
    table.add_row(
        "Total Results",
        str(total),
        "8-10",
        "✓" if 8 <= total <= 10 else "✗"
    )
    
    # Code examples
    status = "✓" if code_pct >= 70 else "✗"
    table.add_row(
        "Code Examples",
        f"{code_count}/{total} ({code_pct:.0f}%)",
        ">70%",
        status
    )
    
    # Test files
    status = "✓" if test_pct >= 30 else "✗"
    table.add_row(
        "Test Files",
        f"{test_count}/{total} ({test_pct:.0f}%)",
        ">30%",
        status
    )
    
    # Markdown docs
    status = "✓" if md_pct <= 30 else "✗"
    table.add_row(
        "Markdown Docs",
        f"{markdown_count}/{total} ({md_pct:.0f}%)",
        "<30%",
        status
    )
    
    # Average score
    status = "✓" if avg_score >= 0.40 else "✗"
    table.add_row(
        "Avg Score",
        f"{avg_score:.3f}",
        ">0.40",
        status
    )
    
    # Score range
    table.add_row(
        "Score Range",
        f"{min_score:.3f} - {max_score:.3f}",
        "0.35+",
        "✓" if min_score >= 0.35 else "✗"
    )
    
    console.print(table)
    console.print()
    
    # Show top 3 results
    console.print(Panel.fit(
        "[bold]Top 3 Results:[/bold]",
        border_style="blue"
    ))
    
    for i, result in enumerate(results[:3], 1):
        file_path = result.metadata.get("file_path", "unknown")
        file_name = Path(file_path).name
        score = result.score
        
        # Determine file type emoji
        if "/test" in file_path.lower():
            emoji = "🧪"
        elif file_path.endswith(".py"):
            emoji = "🐍"
        elif file_path.endswith(".md"):
            emoji = "📄"
        else:
            emoji = "📁"
        
        console.print(f"{i}. {emoji} {file_name} (score: {score:.3f})")
        console.print(f"   Path: {file_path}")
        console.print()


def main():
    """Run quality improvement tests."""
    
    console.print(Panel.fit(
        "[bold cyan]RAG Quality Improvement Verification[/bold cyan]\n"
        "Testing min_score threshold and file type boosting",
        border_style="cyan"
    ))
    console.print()
    
    # Initialize retriever
    console.print("[yellow]Initializing RAG retriever...[/yellow]")
    retriever = RAGRetriever(
        top_k=10,
        use_multi_collection=True,
        enable_cache=False  # Disable cache for testing
    )
    console.print("[green]✓ Retriever initialized[/green]")
    console.print()
    
    # Test queries (same as diagnostic)
    test_queries = [
        ("give me a pyegeria example to create a digital product", "Digital Product Example"),
        ("show me a test example for creating a glossary", "Glossary Test Example"),
        ("how do I create a term in pyegeria", "Create Term"),
        ("pyegeria code example for asset creation", "Asset Creation Example"),
    ]
    
    console.print("[bold]Running test queries...[/bold]")
    console.print("=" * 80)
    console.print()
    
    for query, desc in test_queries:
        console.print(f"[bold blue]Query:[/bold blue] {query}")
        console.print()
        
        # Retrieve results
        results = retriever.retrieve(query)
        
        # Analyze and display
        analyze_results(results, desc)
        
        console.print("=" * 80)
        console.print()
    
    # Summary
    console.print(Panel.fit(
        "[bold green]Verification Complete[/bold green]\n\n"
        "Expected improvements:\n"
        "• Query 2 should now have >70% code examples (was 0%)\n"
        "• Query 2 should have >30% test files (was 0%)\n"
        "• All queries should have <30% markdown docs\n"
        "• All queries should have avg score >0.40\n"
        "• Min scores should be >0.35 (threshold increased)",
        border_style="green"
    ))


if __name__ == "__main__":
    main()