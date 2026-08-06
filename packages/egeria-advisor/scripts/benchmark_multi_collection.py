#!/usr/bin/env python3
"""
Benchmark script for multi-collection search performance.

Tests search latency across different collections, query types,
and result sizes to identify optimization opportunities.
"""

import time
import statistics
from typing import List, Dict, Any, Tuple
from pathlib import Path
import json
from datetime import datetime

from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from advisor.multi_collection_store import get_multi_collection_store
from advisor.collection_router import get_collection_router
from advisor.embeddings import get_embedding_generator
from advisor.vector_store import get_vector_store


console = Console()


# Test queries organized by expected routing
TEST_QUERIES = {
    "pyegeria": [
        "How do I use the GlossaryManager?",
        "What is the EgeriaClient class?",
        "Show me pyegeria widget examples",
        "How to use the REST client?",
        "What are the async client methods?",
    ],
    "pyegeria_cli": [
        "What hey_egeria commands are available?",
        "How do I use the CLI?",
        "Show me command-line examples",
        "What CLI operations exist?",
        "How to run hey_egeria?",
    ],
    "pyegeria_drE": [
        "How does Dr. Egeria work?",
        "Markdown translation with dr egeria",
        "What is document automation?",
        "How to use markdown translator?",
        "Dr. Egeria processing examples",
    ],
    "egeria_java": [
        "What are OMAS services?",
        "How does OMAG work?",
        "Show me Java implementation",
        "What is OMRS?",
        "Explain OCF framework",
    ],
    "egeria_docs": [
        "What is Egeria?",
        "Explain metadata concepts",
        "What are governance zones?",
        "How does Egeria work?",
        "What is a glossary term?",
    ],
    "general": [
        "Tell me about metadata",
        "What can I do with Egeria?",
        "Show me examples",
        "How to get started?",
        "What features are available?",
    ],
}


def benchmark_embedding_generation(num_queries: int = 10) -> Dict[str, float]:
    """Benchmark embedding generation performance."""
    console.print("\n[bold cyan]Benchmarking Embedding Generation[/bold cyan]")
    
    embedding_gen = get_embedding_generator()
    queries = [q for queries in TEST_QUERIES.values() for q in queries][:num_queries]
    
    times = []
    for query in queries:
        start = time.time()
        embedding_gen.generate_embedding(query)
        elapsed = time.time() - start
        times.append(elapsed)
    
    return {
        "mean": statistics.mean(times),
        "median": statistics.median(times),
        "min": min(times),
        "max": max(times),
        "stdev": statistics.stdev(times) if len(times) > 1 else 0,
    }


def benchmark_single_collection_search(
    collection_name: str,
    queries: List[str],
    top_k: int = 10
) -> Dict[str, Any]:
    """Benchmark search performance for a single collection."""
    vector_store = get_vector_store()
    embedding_gen = get_embedding_generator()
    
    times = []
    result_counts = []
    
    for query in queries:
        # Generate embedding
        query_embedding = embedding_gen.generate_embedding(query)
        
        # Time the search
        start = time.time()
        results = vector_store.search(
            collection_name=collection_name,
            query_embedding=query_embedding,
            top_k=top_k
        )
        elapsed = time.time() - start
        
        times.append(elapsed)
        result_counts.append(len(results))
    
    return {
        "collection": collection_name,
        "num_queries": len(queries),
        "mean_time": statistics.mean(times),
        "median_time": statistics.median(times),
        "min_time": min(times),
        "max_time": max(times),
        "stdev_time": statistics.stdev(times) if len(times) > 1 else 0,
        "mean_results": statistics.mean(result_counts),
    }


def benchmark_multi_collection_search(
    queries_by_type: Dict[str, List[str]],
    top_k: int = 10
) -> List[Dict[str, Any]]:
    """Benchmark multi-collection search with routing."""
    multi_store = get_multi_collection_store()
    router = get_collection_router()
    
    results = []
    
    for query_type, queries in queries_by_type.items():
        times = []
        routing_times = []
        search_times = []
        result_counts = []
        collections_used = []
        
        for query in queries:
            # Time routing
            route_start = time.time()
            routed_collections = router.route_query(query)
            route_elapsed = time.time() - route_start
            routing_times.append(route_elapsed)
            
            # Time search
            search_start = time.time()
            search_result = multi_store.search_with_routing(
                query=query,
                top_k=top_k
            )
            search_elapsed = time.time() - search_start
            search_times.append(search_elapsed)
            
            total_elapsed = route_elapsed + search_elapsed
            times.append(total_elapsed)
            result_counts.append(len(search_result.results))
            collections_used.append(search_result.collections_searched)
        
        results.append({
            "query_type": query_type,
            "num_queries": len(queries),
            "mean_total_time": statistics.mean(times),
            "mean_routing_time": statistics.mean(routing_times),
            "mean_search_time": statistics.mean(search_times),
            "median_time": statistics.median(times),
            "min_time": min(times),
            "max_time": max(times),
            "stdev_time": statistics.stdev(times) if len(times) > 1 else 0,
            "mean_results": statistics.mean(result_counts),
            "collections_used": collections_used[0] if collections_used else [],
        })
    
    return results


def benchmark_top_k_scaling(
    query: str,
    top_k_values: List[int] = [5, 10, 20, 50, 100]
) -> List[Dict[str, Any]]:
    """Benchmark how search time scales with top_k."""
    multi_store = get_multi_collection_store()
    
    results = []
    for top_k in top_k_values:
        times = []
        for _ in range(3):  # Run 3 times for each top_k
            start = time.time()
            search_result = multi_store.search_with_routing(
                query=query,
                top_k=top_k
            )
            elapsed = time.time() - start
            times.append(elapsed)
        
        results.append({
            "top_k": top_k,
            "mean_time": statistics.mean(times),
            "min_time": min(times),
            "max_time": max(times),
        })
    
    return results


def print_embedding_results(results: Dict[str, float]):
    """Print embedding generation benchmark results."""
    table = Table(title="Embedding Generation Performance")
    table.add_column("Metric", style="cyan")
    table.add_column("Time (ms)", justify="right", style="green")
    
    table.add_row("Mean", f"{results['mean']*1000:.2f}")
    table.add_row("Median", f"{results['median']*1000:.2f}")
    table.add_row("Min", f"{results['min']*1000:.2f}")
    table.add_row("Max", f"{results['max']*1000:.2f}")
    table.add_row("Std Dev", f"{results['stdev']*1000:.2f}")
    
    console.print(table)


def print_single_collection_results(results: List[Dict[str, Any]]):
    """Print single collection benchmark results."""
    table = Table(title="Single Collection Search Performance")
    table.add_column("Collection", style="cyan")
    table.add_column("Queries", justify="right")
    table.add_column("Mean (ms)", justify="right", style="green")
    table.add_column("Median (ms)", justify="right")
    table.add_column("Min (ms)", justify="right")
    table.add_column("Max (ms)", justify="right")
    table.add_column("Avg Results", justify="right")
    
    for result in results:
        table.add_row(
            result["collection"],
            str(result["num_queries"]),
            f"{result['mean_time']*1000:.2f}",
            f"{result['median_time']*1000:.2f}",
            f"{result['min_time']*1000:.2f}",
            f"{result['max_time']*1000:.2f}",
            f"{result['mean_results']:.1f}",
        )
    
    console.print(table)


def print_multi_collection_results(results: List[Dict[str, Any]]):
    """Print multi-collection benchmark results."""
    table = Table(title="Multi-Collection Search Performance (with Routing)")
    table.add_column("Query Type", style="cyan")
    table.add_column("Total (ms)", justify="right", style="green")
    table.add_column("Routing (ms)", justify="right", style="yellow")
    table.add_column("Search (ms)", justify="right", style="blue")
    table.add_column("Collections", style="magenta")
    table.add_column("Avg Results", justify="right")
    
    for result in results:
        collections_str = ", ".join(result["collections_used"])
        table.add_row(
            result["query_type"],
            f"{result['mean_total_time']*1000:.2f}",
            f"{result['mean_routing_time']*1000:.2f}",
            f"{result['mean_search_time']*1000:.2f}",
            collections_str[:30] + "..." if len(collections_str) > 30 else collections_str,
            f"{result['mean_results']:.1f}",
        )
    
    console.print(table)


def print_scaling_results(results: List[Dict[str, Any]]):
    """Print top_k scaling benchmark results."""
    table = Table(title="Search Time Scaling with top_k")
    table.add_column("top_k", justify="right", style="cyan")
    table.add_column("Mean (ms)", justify="right", style="green")
    table.add_column("Min (ms)", justify="right")
    table.add_column("Max (ms)", justify="right")
    
    for result in results:
        table.add_row(
            str(result["top_k"]),
            f"{result['mean_time']*1000:.2f}",
            f"{result['min_time']*1000:.2f}",
            f"{result['max_time']*1000:.2f}",
        )
    
    console.print(table)


def save_results(results: Dict[str, Any], output_file: str = "benchmark_results.json"):
    """Save benchmark results to JSON file."""
    output_path = Path("data/cache") / output_file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    results["timestamp"] = datetime.now().isoformat()
    
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    
    console.print(f"\n[green]✓[/green] Results saved to {output_path}")


def main():
    """Run all benchmarks."""
    console.print("[bold cyan]Multi-Collection Search Benchmark[/bold cyan]")
    console.print("=" * 60)
    
    all_results = {}
    
    # 1. Benchmark embedding generation
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Benchmarking embedding generation...", total=None)
        embedding_results = benchmark_embedding_generation(num_queries=20)
        progress.update(task, completed=True)
    
    print_embedding_results(embedding_results)
    all_results["embedding_generation"] = embedding_results
    
    # 2. Benchmark single collection searches
    console.print("\n[bold cyan]Benchmarking Single Collection Searches[/bold cyan]")
    single_collection_results = []
    
    collections_to_test = ["pyegeria", "pyegeria_cli", "pyegeria_drE"]
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for collection in collections_to_test:
            task = progress.add_task(f"Testing {collection}...", total=None)
            queries = TEST_QUERIES.get(collection, TEST_QUERIES["general"])
            result = benchmark_single_collection_search(collection, queries)
            single_collection_results.append(result)
            progress.update(task, completed=True)
    
    print_single_collection_results(single_collection_results)
    all_results["single_collection"] = single_collection_results
    
    # 3. Benchmark multi-collection search with routing
    console.print("\n[bold cyan]Benchmarking Multi-Collection Search[/bold cyan]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Testing multi-collection routing...", total=None)
        multi_results = benchmark_multi_collection_search(TEST_QUERIES)
        progress.update(task, completed=True)
    
    print_multi_collection_results(multi_results)
    all_results["multi_collection"] = multi_results
    
    # 4. Benchmark top_k scaling
    console.print("\n[bold cyan]Benchmarking top_k Scaling[/bold cyan]")
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Testing top_k scaling...", total=None)
        scaling_results = benchmark_top_k_scaling(
            "How do I use the GlossaryManager?",
            top_k_values=[5, 10, 20, 50, 100]
        )
        progress.update(task, completed=True)
    
    print_scaling_results(scaling_results)
    all_results["top_k_scaling"] = scaling_results
    
    # Save all results
    save_results(all_results)
    
    # Print summary
    console.print("\n[bold green]Benchmark Complete![/bold green]")
    console.print("\n[bold]Key Findings:[/bold]")
    console.print(f"• Embedding generation: {embedding_results['mean']*1000:.2f}ms average")
    console.print(f"• Single collection search: {statistics.mean([r['mean_time'] for r in single_collection_results])*1000:.2f}ms average")
    console.print(f"• Multi-collection search: {statistics.mean([r['mean_total_time'] for r in multi_results])*1000:.2f}ms average")
    console.print(f"• Routing overhead: {statistics.mean([r['mean_routing_time'] for r in multi_results])*1000:.2f}ms average")


if __name__ == "__main__":
    main()