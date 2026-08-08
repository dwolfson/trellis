#!/usr/bin/env python3
"""
Diagnose RAG retrieval quality for code example queries.

This script tests what context is actually being retrieved for code queries
and helps identify why responses might be hallucinations.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.rag_retrieval import RAGRetriever
from advisor.collection_router import get_collection_router
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

console = Console()


def diagnose_query(query: str):
    """Diagnose what gets retrieved for a query."""
    console.print(f"\n[bold cyan]Diagnosing Query:[/bold cyan] {query}")
    console.print("=" * 80)
    
    # 1. Check routing
    console.print("\n[bold]Step 1: Collection Routing[/bold]")
    router = get_collection_router()
    collections = router.route_query(query, max_collections=3)
    console.print(f"Collections to search: {collections}")
    
    # 2. Check retrieval
    console.print("\n[bold]Step 2: RAG Retrieval (top_k=10)[/bold]")
    retriever = RAGRetriever(use_multi_collection=True, enable_cache=False)
    results = retriever.retrieve(query, top_k=10)
    
    console.print(f"Retrieved {len(results)} results\n")
    
    # 3. Analyze results
    if not results:
        console.print("[red]✗ NO RESULTS RETRIEVED![/red]")
        console.print("This explains the hallucination - no context provided to LLM")
        return
    
    # Show results table
    table = Table(title="Retrieved Context", show_header=True, header_style="bold cyan")
    table.add_column("#", style="cyan", width=3)
    table.add_column("Score", justify="right", width=6)
    table.add_column("Collection", width=15)
    table.add_column("File", width=40)
    table.add_column("Preview", width=60)
    
    for i, result in enumerate(results, 1):
        file_path = result.metadata.get('file_path', 'Unknown')
        collection = result.metadata.get('collection', 'Unknown')
        score = result.score
        preview = result.text[:100].replace('\n', ' ')
        
        table.add_row(
            str(i),
            f"{score:.3f}",
            collection,
            file_path,
            preview + "..."
        )
    
    console.print(table)
    
    # 4. Check for code examples
    console.print("\n[bold]Step 3: Code Example Analysis[/bold]")
    
    code_indicators = ['def ', 'class ', 'import ', 'from ', '"""', "'''"]
    code_results = []
    test_results = []
    
    for result in results:
        text = result.text
        file_path = result.metadata.get('file_path', '')
        
        # Check if it's actual code
        has_code = any(indicator in text for indicator in code_indicators)
        if has_code:
            code_results.append(result)
        
        # Check if it's from tests
        if '/tests/' in file_path or '/test_' in file_path:
            test_results.append(result)
    
    console.print(f"Results with code: {len(code_results)}/{len(results)}")
    console.print(f"Results from tests: {len(test_results)}/{len(results)}")
    
    if len(code_results) < 3:
        console.print("[yellow]⚠ Warning: Few code examples in results[/yellow]")
        console.print("This may lead to poor quality or hallucinated responses")
    
    if len(test_results) == 0:
        console.print("[yellow]⚠ Warning: No test examples retrieved[/yellow]")
        console.print("Tests directory has the best working examples")
    
    # 5. Show best result details
    if results:
        console.print("\n[bold]Step 4: Best Match Details[/bold]")
        best = results[0]
        console.print(Panel(
            f"[cyan]File:[/cyan] {best.metadata.get('file_path', 'Unknown')}\n"
            f"[cyan]Collection:[/cyan] {best.metadata.get('collection', 'Unknown')}\n"
            f"[cyan]Score:[/cyan] {best.score:.3f}\n\n"
            f"[cyan]Content:[/cyan]\n{best.text[:500]}...",
            title="Top Result",
            border_style="cyan"
        ))
    
    # 6. Recommendations
    console.print("\n[bold green]Recommendations:[/bold green]")
    if len(test_results) == 0:
        console.print("• [yellow]Add 'test' or 'example' to query to boost test file results[/yellow]")
    if len(code_results) < 5:
        console.print("• [yellow]Increase min_score threshold to filter out non-code results[/yellow]")
    if len(results) < 10:
        console.print("• [yellow]Increase top_k to get more context[/yellow]")


def main():
    """Run diagnostics on common queries."""
    console.print("[bold cyan]RAG Quality Diagnostic Tool[/bold cyan]")
    console.print("=" * 80)
    
    test_queries = [
        "give me a pyegeria example to create a digital product",
        "show me a test example for creating a glossary",
        "how do I create a term in pyegeria",
        "pyegeria code example for asset creation"
    ]
    
    for query in test_queries:
        try:
            diagnose_query(query)
            console.print("\n" + "=" * 80)
        except Exception as e:
            console.print(f"[red]Error diagnosing query:[/red] {e}")
            import traceback
            traceback.print_exc()
    
    console.print("\n[bold]Summary:[/bold]")
    console.print("If results show:")
    console.print("  • Low scores (<0.7): Context not relevant")
    console.print("  • No code examples: Wrong chunks retrieved")
    console.print("  • No test files: Missing best examples")
    console.print("\nThen the LLM will hallucinate because it has no good context to work with.")


if __name__ == "__main__":
    main()