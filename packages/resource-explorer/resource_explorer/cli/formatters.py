"""Rich output helpers for the CLI."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table

from resource_explorer.registry import Project


def print_project_table(projects: list[Project], console: Console, details: bool = False) -> None:
    if not projects:
        console.print("[yellow]No projects registered. Run: project-explorer add <github-url>[/yellow]")
        return

    if details:
        _print_project_details(projects, console)
    else:
        _print_project_summary(projects, console)


def _print_project_summary(projects: list[Project], console: Console) -> None:
    from resource_explorer.vector_store_pg import MultiCollectionStore
    store = MultiCollectionStore()

    table = Table(title="Registered Projects")
    table.add_column("Slug", style="cyan")
    table.add_column("Name")
    table.add_column("Group", style="magenta")
    table.add_column("Status")
    table.add_column("Collections")
    table.add_column("Vectors", justify="right")
    table.add_column("Last Indexed")
    for p in projects:
        status_color = {"active": "green", "indexing": "yellow", "paused": "dim", "error": "red"}.get(
            p.status.value, "white"
        )
        col_types = [c.removeprefix(f"{p.slug}_") for c in sorted(p.collections)]
        total_vecs = sum(store.count(c) for c in p.collections)
        table.add_row(
            p.slug,
            p.display_name,
            p.group_slug or "[dim]-[ /dim]",
            f"[{status_color}]{p.status.value}[/{status_color}]",
            ", ".join(col_types) if col_types else "[dim]none[/dim]",
            f"{total_vecs:,}" if total_vecs else "[dim]0[/dim]",
            p.last_indexed_at[:10] if p.last_indexed_at else "never",
        )
    console.print(table)


def _print_project_details(projects: list[Project], console: Console) -> None:
    from resource_explorer.vector_store_pg import MultiCollectionStore
    store = MultiCollectionStore()

    for p in projects:
        status_color = {"active": "green", "indexing": "yellow", "paused": "dim", "error": "red"}.get(
            p.status.value, "white"
        )
        console.print(
            f"\n[bold cyan]{p.slug}[/bold cyan]  [dim]({p.display_name})[/dim]  "
            f"[{status_color}]{p.status.value}[/{status_color}]"
        )
        if p.description:
            console.print(f"  [dim]{p.description}[/dim]")
        if p.group_slug:
            console.print(f"  Group:         [magenta]{p.group_slug}[/magenta]")
        console.print(f"  GitHub:       {p.github_url}")
        if p.homepage_url:
            console.print(f"  Homepage:     {p.homepage_url}")
        if p.docs_url:
            console.print(f"  Docs:         {p.docs_url}")
        console.print(f"  Last indexed: {p.last_indexed_at[:10] if p.last_indexed_at else 'never'}")

        if p.collections:
            table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
            table.add_column("Collection", style="cyan")
            table.add_column("Vectors", justify="right")
            table.add_column("Type")
            total = 0
            for col in sorted(p.collections):
                count = store.count(col)
                total += count
                ctype = col.removeprefix(f"{p.slug}_")
                table.add_row(col, f"{count:,}", ctype)
            table.add_row("[dim]TOTAL[/dim]", f"[bold]{total:,}[/bold]", "")
            console.print(table)
        else:
            console.print("  [dim]No collections indexed yet.[/dim]")
