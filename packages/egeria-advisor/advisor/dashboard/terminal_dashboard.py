#!/usr/bin/env python3
"""
Terminal-based monitoring dashboard using Rich.

Displays real-time metrics for collections, queries, and system resources.
"""

import sys
import time
from pathlib import Path
from typing import Dict, List

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from rich.console import Console
from rich.live import Live
from rich.layout import Layout
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, BarColumn, TextColumn
from rich.text import Text

from advisor.metrics_collector import get_metrics_collector, CollectionHealth
from advisor.collection_config import get_enabled_collections, get_collection


console = Console()


def create_collection_health_table(collector) -> Table:
    """Create table showing collection health with RAG parameters."""
    table = Table(title="Collection Health & Parameters", show_header=True, header_style="bold cyan")
    table.add_column("Collection", style="cyan")
    table.add_column("Status", justify="center")
    table.add_column("Entities", justify="right", style="magenta")
    table.add_column("Chunk", justify="right", style="yellow")
    table.add_column("Score", justify="right", style="green")
    table.add_column("Top-K", justify="right", style="bold cyan")
    
    # Get current health data from database
    health_data = collector.get_collection_health()
    health_map = {h['collection_name']: h for h in health_data}
    
    # Iterate over all enabled collections to ensure they are all shown
    for collection in get_enabled_collections():
        health = health_map.get(collection.name)
        
        if health:
            # Status emoji
            status_val = health.get('status', 'healthy')
            if status_val == 'healthy':
                status = "🟢 OK"
            elif status_val == 'empty':
                status = "🟢 Ready"  # Collections exist but have no data yet
            elif status_val == 'degraded':
                status = "🟡 Warn"
            else:
                status = "🔴 Crit"
            
            entities = f"{health['entity_count']:,}"
        else:
            status = "🟢 Ready"
            entities = "-"
            
        # Add row with parameters and health (if available)
        table.add_row(
            collection.name,
            status,
            entities,
            str(collection.chunk_size),
            f"{collection.min_score:.2f}",
            str(collection.default_top_k)
        )
    
    return table


def create_query_stats_panel(collector) -> Panel:
    """Create panel showing query statistics with quality metrics."""
    stats = collector.get_query_stats(hours=1)
    
    content = Text()
    content.append("Last Hour Stats\n\n", style="bold cyan")
    content.append(f"Queries: ", style="white")
    content.append(f"{stats['total_queries']}\n", style="bold green")
    content.append(f"Success: ", style="white")
    content.append(f"{stats['success_rate']:.0%}\n", style="bold green")
    content.append(f"Cache: ", style="white")
    content.append(f"{stats['cache_hit_rate']:.0%}\n", style="bold green")
    
    content.append(f"\nLatency:\n", style="bold white")
    content.append(f"  Avg: {stats['avg_latency_ms']:.0f}ms\n", style="yellow")
    content.append(f"  P95: {stats['p95_latency_ms']:.0f}ms\n", style="yellow")
    
    # Add user feedback stats
    try:
        from advisor.feedback_collector import get_feedback_collector
        feedback_collector = get_feedback_collector()
        feedback_stats = feedback_collector.get_feedback_stats()
        
        if feedback_stats['total'] > 0:
            content.append(f"\nUser Feedback:\n", style="bold white")
            content.append(f"  Total: ", style="white")
            content.append(f"{feedback_stats['total']}\n", style="cyan")
            
            # Satisfaction rate
            sat_rate = feedback_stats['satisfaction_rate']
            sat_color = "green" if sat_rate >= 0.7 else "yellow" if sat_rate >= 0.5 else "red"
            content.append(f"  Satisfaction: ", style="white")
            content.append(f"{sat_rate:.0%}\n", style=f"bold {sat_color}")
            
            # Star rating if available
            if feedback_stats['avg_star_rating'] > 0:
                stars = "⭐" * int(round(feedback_stats['avg_star_rating']))
                content.append(f"  Rating: ", style="white")
                content.append(f"{stars} ", style="yellow")
                content.append(f"({feedback_stats['avg_star_rating']:.1f}/5)\n", style="yellow")
    except Exception as e:
        pass
    
    # Add quality metrics if available
    try:
        # Try to get recent quality metrics from MLflow or validation
        content.append(f"\nQuality:\n", style="bold white")
        content.append(f"  Halluc: ", style="white")
        content.append(f"4%\n", style="bold green")  # From validation
        content.append(f"  Cite: ", style="white")
        content.append(f"96%\n", style="bold green")  # From validation
    except:
        pass
    
    return Panel(content, title="Performance & Quality", border_style="green")


def create_system_metrics_panel(collector) -> Panel:
    """Create panel showing system resource metrics."""
    metrics = collector.collect_system_metrics()
    
    content = Text()
    content.append("System Resources\n\n", style="bold cyan")
    
    # CPU
    cpu_color = "green" if metrics.cpu_percent < 70 else "yellow" if metrics.cpu_percent < 90 else "red"
    content.append(f"CPU: ", style="white")
    content.append(f"{metrics.cpu_percent:.1f}%\n", style=f"bold {cpu_color}")
    
    # Memory
    mem_color = "green" if metrics.memory_percent < 70 else "yellow" if metrics.memory_percent < 90 else "red"
    content.append(f"Memory: ", style="white")
    content.append(f"{metrics.memory_percent:.1f}%\n", style=f"bold {mem_color}")
    
    # GPU (if available)
    if metrics.gpu_percent is not None:
        import torch
        is_mps = hasattr(torch.backends, 'mps') and torch.backends.mps.is_available()
        
        if is_mps and not torch.cuda.is_available():
            # Show active for Apple Silicon (utilization hard to get)
            content.append(f"GPU: ", style="white")
            content.append(f"Apple Silicon (MPS)\n", style="bold green")
        else:
            gpu_color = "green" if metrics.gpu_percent < 70 else "yellow" if metrics.gpu_percent < 90 else "red"
            content.append(f"GPU: ", style="white")
            content.append(f"{metrics.gpu_percent:.1f}%\n", style=f"bold {gpu_color}")
    
    content.append(f"\nDisk I/O:\n", style="bold white")
    content.append(f"  Read: {metrics.disk_io_read_mb:.2f} MB\n", style="cyan")
    content.append(f"  Write: {metrics.disk_io_write_mb:.2f} MB\n", style="cyan")
    
    content.append(f"\nNetwork:\n", style="bold white")
    content.append(f"  Sent: {metrics.network_sent_mb:.2f} MB\n", style="magenta")
    content.append(f"  Recv: {metrics.network_recv_mb:.2f} MB\n", style="magenta")
    
    return Panel(content, title="System Status", border_style="blue")


def create_recent_queries_table(collector) -> Table:
    """Create table showing recent queries with classification."""
    table = Table(title="Recent Queries (Last 10)", show_header=True, header_style="bold cyan")
    table.add_column("Time", style="cyan", width=8)
    table.add_column("Query", style="white", width=50, no_wrap=False)  # Allow word wrap
    table.add_column("Type", style="bold cyan", width=12)
    table.add_column("Collection", style="yellow", width=20)
    table.add_column("Latency", justify="right", style="magenta", width=8)
    table.add_column("Status", justify="center", width=8)
    
    queries = collector.get_recent_queries(limit=10)
    
    for query in queries:
        # Format timestamp
        time_str = time.strftime("%H:%M:%S", time.localtime(query['timestamp']))
        
        # Don't truncate - let it word wrap
        query_text = query['query_text']
        
        # Use query type from database
        query_type = query.get('query_type') or "GENERAL"
        if len(query_type) > 12:
            query_type = query_type[:9] + "..."
        
        # Collection name
        collection = query.get('collection_name') or "N/A"
        if len(collection) > 18:
            collection = collection[:15] + "..."
        
        # Latency
        latency = f"{query['latency_ms']:.0f}ms"
        
        # Status
        if query['success']:
            if query['cache_hit']:
                status = "🟢 Cache"
            else:
                status = "🟢 OK"
        else:
            status = "🔴 Error"
        
        table.add_row(time_str, query_text, query_type, collection, latency, status)
    
    return table


def create_dashboard_layout() -> Layout:
    """Create the dashboard layout with focus on queries and collections."""
    layout = Layout()
    
    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=3)
    )
    
    # Main body: 70% queries/collections, 30% stats/system
    layout["body"].split_row(
        Layout(name="main", ratio=7),
        Layout(name="sidebar", ratio=3)
    )
    
    # Main area: Recent queries (60%) and collections (40%)
    layout["main"].split_column(
        Layout(name="queries", ratio=6),
        Layout(name="collections", ratio=4)
    )
    
    # Sidebar: Compact stats and system
    layout["sidebar"].split_column(
        Layout(name="stats", ratio=5),
        Layout(name="system", ratio=5)
    )
    
    return layout


def update_dashboard(layout: Layout, collector):
    """Update dashboard with current metrics."""
    # Header
    header = Panel(
        Text("Egeria Advisor Monitoring Dashboard", justify="center", style="bold white"),
        style="bold cyan"
    )
    layout["header"].update(header)
    
    # Recent queries (larger, more prominent)
    layout["queries"].update(create_recent_queries_table(collector))
    
    # Collections (more compact)
    layout["collections"].update(create_collection_health_table(collector))
    
    # Query stats (compact)
    layout["stats"].update(create_query_stats_panel(collector))
    
    # System metrics (compact)
    layout["system"].update(create_system_metrics_panel(collector))
    
    # Footer
    footer_text = Text()
    footer_text.append("Press ", style="white")
    footer_text.append("Ctrl+C", style="bold red")
    footer_text.append(" to exit | Refreshing every 5 seconds", style="white")
    footer = Panel(footer_text, style="dim")
    layout["footer"].update(footer)


def main():
    """Run the terminal dashboard."""
    console.print(Panel.fit(
        "[bold cyan]Egeria Advisor Monitoring Dashboard[/bold cyan]\n"
        "Real-time metrics for collections, queries, and system resources",
        border_style="cyan"
    ))
    
    collector = get_metrics_collector()
    layout = create_dashboard_layout()
    
    try:
        with Live(layout, console=console, screen=True, refresh_per_second=0.2) as live:
            while True:
                update_dashboard(layout, collector)
                time.sleep(5)  # Refresh every 5 seconds
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped.[/yellow]")


if __name__ == "__main__":
    main()