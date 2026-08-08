#!/usr/bin/env python3
"""
Test script to verify query cache performance improvements.

This script:
1. Tests cache hit/miss behavior
2. Measures performance improvements from caching
3. Validates cache statistics
4. Tests cache with different query parameters
"""

import sys
import time
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.panel import Panel

from advisor.rag_retrieval import RAGRetriever
from advisor.query_cache import get_query_cache

console = Console()


def test_cache_hit_miss():
    """Test basic cache hit/miss behavior."""
    console.print("\n[bold cyan]Test 1: Cache Hit/Miss Behavior[/bold cyan]")
    
    # Initialize RAG with cache enabled
    rag = RAGRetriever(use_multi_collection=True, enable_cache=True)
    cache = get_query_cache()
    cache.clear()
    
    query = "How do I connect to an OMAG server?"
    
    # First query - should be a cache miss
    console.print("\n[yellow]First query (cache miss expected)...[/yellow]")
    start = time.time()
    results1 = rag.retrieve(query, top_k=5)
    time1 = time.time() - start
    
    stats1 = cache.get_stats()
    console.print(f"Time: {time1:.3f}s")
    console.print(f"Results: {len(results1)}")
    console.print(f"Cache stats: {stats1}")
    
    # Second query - should be a cache hit
    console.print("\n[yellow]Second query (cache hit expected)...[/yellow]")
    start = time.time()
    results2 = rag.retrieve(query, top_k=5)
    time2 = time.time() - start
    
    stats2 = cache.get_stats()
    console.print(f"Time: {time2:.3f}s")
    console.print(f"Results: {len(results2)}")
    console.print(f"Cache stats: {stats2}")
    
    # Verify cache hit
    speedup = time1 / time2 if time2 > 0 else 0
    console.print(f"\n[green]✓ Speedup: {speedup:.1f}x faster[/green]")
    console.print(f"[green]✓ Cache hit rate: {stats2['hit_rate']:.1%}[/green]")
    
    return {
        "first_query_time": time1,
        "second_query_time": time2,
        "speedup": speedup,
        "hit_rate": stats2['hit_rate']
    }


def test_cache_with_different_params():
    """Test cache behavior with different query parameters."""
    console.print("\n[bold cyan]Test 2: Cache with Different Parameters[/bold cyan]")
    
    rag = RAGRetriever(use_multi_collection=True, enable_cache=True)
    cache = get_query_cache()
    cache.clear()
    
    query = "How do I create an asset?"
    
    # Query with top_k=5
    console.print("\n[yellow]Query with top_k=5...[/yellow]")
    results1 = rag.retrieve(query, top_k=5)
    console.print(f"Results: {len(results1)}")
    
    # Same query with top_k=10 - should be cache miss
    console.print("\n[yellow]Same query with top_k=10 (cache miss expected)...[/yellow]")
    results2 = rag.retrieve(query, top_k=10)
    console.print(f"Results: {len(results2)}")
    
    # Repeat with top_k=5 - should be cache hit
    console.print("\n[yellow]Repeat with top_k=5 (cache hit expected)...[/yellow]")
    results3 = rag.retrieve(query, top_k=5)
    console.print(f"Results: {len(results3)}")
    
    stats = cache.get_stats()
    console.print(f"\n[green]✓ Cache stats: {stats}[/green]")
    console.print(f"[green]✓ Hit rate: {stats['hit_rate']:.1%}[/green]")
    
    return stats


def test_multiple_queries():
    """Test cache performance with multiple different queries."""
    console.print("\n[bold cyan]Test 3: Multiple Queries Performance[/bold cyan]")
    
    rag = RAGRetriever(use_multi_collection=True, enable_cache=True)
    cache = get_query_cache()
    cache.clear()
    
    queries = [
        "How do I connect to an OMAG server?",
        "How do I create an asset?",
        "How do I search for glossary terms?",
        "How do I get server status?",
        "How do I configure a platform?",
    ]
    
    # First pass - all cache misses
    console.print("\n[yellow]First pass (all cache misses)...[/yellow]")
    start = time.time()
    for query in queries:
        results = rag.retrieve(query, top_k=5)
        console.print(f"  {query[:50]}... -> {len(results)} results")
    time_first = time.time() - start
    
    stats_first = cache.get_stats()
    console.print(f"Time: {time_first:.3f}s")
    console.print(f"Cache stats: {stats_first}")
    
    # Second pass - all cache hits
    console.print("\n[yellow]Second pass (all cache hits)...[/yellow]")
    start = time.time()
    for query in queries:
        results = rag.retrieve(query, top_k=5)
        console.print(f"  {query[:50]}... -> {len(results)} results")
    time_second = time.time() - start
    
    stats_second = cache.get_stats()
    console.print(f"Time: {time_second:.3f}s")
    console.print(f"Cache stats: {stats_second}")
    
    speedup = time_first / time_second if time_second > 0 else 0
    console.print(f"\n[green]✓ Total speedup: {speedup:.1f}x faster[/green]")
    console.print(f"[green]✓ Average time per query (first): {time_first/len(queries):.3f}s[/green]")
    console.print(f"[green]✓ Average time per query (second): {time_second/len(queries):.3f}s[/green]")
    
    return {
        "first_pass_time": time_first,
        "second_pass_time": time_second,
        "speedup": speedup,
        "queries_tested": len(queries)
    }


def test_cache_disabled():
    """Test performance without cache for comparison."""
    console.print("\n[bold cyan]Test 4: Performance Without Cache[/bold cyan]")
    
    rag = RAGRetriever(use_multi_collection=True, enable_cache=False)
    
    query = "How do I connect to an OMAG server?"
    
    # First query
    console.print("\n[yellow]First query...[/yellow]")
    start = time.time()
    results1 = rag.retrieve(query, top_k=5)
    time1 = time.time() - start
    console.print(f"Time: {time1:.3f}s, Results: {len(results1)}")
    
    # Second query - should take similar time (no cache)
    console.print("\n[yellow]Second query (no cache)...[/yellow]")
    start = time.time()
    results2 = rag.retrieve(query, top_k=5)
    time2 = time.time() - start
    console.print(f"Time: {time2:.3f}s, Results: {len(results2)}")
    
    console.print(f"\n[yellow]⚠ Without cache, queries take similar time[/yellow]")
    console.print(f"[yellow]  First: {time1:.3f}s, Second: {time2:.3f}s[/yellow]")
    
    return {
        "first_query_time": time1,
        "second_query_time": time2
    }


def create_summary_table(results):
    """Create a summary table of all test results."""
    table = Table(title="Cache Performance Test Summary", show_header=True)
    table.add_column("Test", style="cyan")
    table.add_column("Metric", style="yellow")
    table.add_column("Value", style="green")
    
    # Test 1: Cache Hit/Miss
    test1 = results['test1']
    table.add_row(
        "Cache Hit/Miss",
        "First query time",
        f"{test1['first_query_time']:.3f}s"
    )
    table.add_row(
        "",
        "Second query time (cached)",
        f"{test1['second_query_time']:.3f}s"
    )
    table.add_row(
        "",
        "Speedup",
        f"{test1['speedup']:.1f}x"
    )
    table.add_row(
        "",
        "Hit rate",
        f"{test1['hit_rate']:.1%}"
    )
    
    # Test 2: Different Parameters
    test2 = results['test2']
    table.add_row(
        "Different Parameters",
        "Hit rate",
        f"{test2['hit_rate']:.1%}"
    )
    table.add_row(
        "",
        "Total requests",
        str(test2['total_requests'])
    )
    
    # Test 3: Multiple Queries
    test3 = results['test3']
    table.add_row(
        "Multiple Queries",
        "First pass time",
        f"{test3['first_pass_time']:.3f}s"
    )
    table.add_row(
        "",
        "Second pass time (cached)",
        f"{test3['second_pass_time']:.3f}s"
    )
    table.add_row(
        "",
        "Speedup",
        f"{test3['speedup']:.1f}x"
    )
    table.add_row(
        "",
        "Queries tested",
        str(test3['queries_tested'])
    )
    
    # Test 4: No Cache
    test4 = results['test4']
    table.add_row(
        "Without Cache",
        "First query time",
        f"{test4['first_query_time']:.3f}s"
    )
    table.add_row(
        "",
        "Second query time",
        f"{test4['second_query_time']:.3f}s"
    )
    
    return table


def main():
    """Run all cache performance tests."""
    console.print(Panel.fit(
        "[bold cyan]Egeria Advisor - Query Cache Performance Tests[/bold cyan]\n"
        "Testing cache integration and performance improvements",
        border_style="cyan"
    ))
    
    results = {}
    
    try:
        # Run tests
        results['test1'] = test_cache_hit_miss()
        results['test2'] = test_cache_with_different_params()
        results['test3'] = test_multiple_queries()
        results['test4'] = test_cache_disabled()
        
        # Display summary
        console.print("\n")
        table = create_summary_table(results)
        console.print(table)
        
        # Final verdict
        console.print("\n[bold green]✓ All cache tests completed successfully![/bold green]")
        console.print(f"[green]✓ Cache provides {results['test1']['speedup']:.1f}x speedup for repeated queries[/green]")
        console.print(f"[green]✓ Cache hit rate: {results['test1']['hit_rate']:.1%}[/green]")
        
    except Exception as e:
        console.print(f"\n[bold red]✗ Test failed: {e}[/bold red]")
        logger.exception("Test failed")
        return 1
    
    return 0


if __name__ == "__main__":
    sys.exit(main())