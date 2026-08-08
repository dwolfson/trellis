"""Terminal status dashboard — shows environment health and project collection counts."""
from __future__ import annotations

from rich.console import Console
from rich.table import Table


def print_status(console: Console) -> None:
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.vector_store_pg import MultiCollectionStore

    console.print("\n[bold]Resource Explorer — Environment Status[/bold]\n")

    _check_services(console)

    projects = ProjectRegistry().list_all()
    store = MultiCollectionStore()

    table = Table(title="Projects & Collections")
    table.add_column("Project", style="cyan")
    table.add_column("Status")
    table.add_column("Collection")
    table.add_column("Vectors", justify="right")

    for project in projects:
        for i, collection in enumerate(project.collections):
            count = store.count(collection)
            table.add_row(
                project.display_name if i == 0 else "",
                project.status.value if i == 0 else "",
                collection,
                str(count),
            )
        if not project.collections:
            table.add_row(project.display_name, project.status.value, "(none)", "0")

    console.print(table)


def _check_services(console: Console) -> None:
    import httpx
    services = {
        "Ollama": "http://localhost:11434",
        "Phoenix": "http://localhost:6006",
        "MLflow": "http://localhost:5025",
    }
    for name, url in services.items():
        try:
            r = httpx.get(url, timeout=2)
            status = "[green]up[/green]" if r.status_code < 500 else "[red]error[/red]"
        except Exception:
            status = "[dim]down[/dim]"
        console.print(f"  {name:12} {status}")
    console.print(f"  {'pgvector':12} {_check_pgvector()}")
    console.print()


def _check_pgvector() -> str:
    """Real Postgres connectivity probe, replacing the old Milvus :9091/healthz
    check (no pgvector equivalent — this connects directly instead)."""
    try:
        from resource_explorer.vector_store_pg import _get_shared_store
        store = _get_shared_store()
        store.connect()
        return "[green]up[/green]"
    except Exception:
        return "[dim]down[/dim]"
