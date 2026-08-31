"""CLI entry point — all resource-explorer commands."""
from __future__ import annotations

import os

# Suppress gRPC fork warnings, HuggingFace progress bars, and tokenizer parallelism
# noise that pollutes normal CLI output. Set DEBUG=1 to restore verbose logging.
if not os.environ.get("DEBUG"):
    os.environ.setdefault("GRPC_VERBOSITY", "NONE")
    os.environ.setdefault("GLOG_minloglevel", "3")
    os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("TQDM_DISABLE", "1")

from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(
    name="resource-explorer",
    help="Scout, survey, and catalog information resources using Egeria.",
    rich_markup_mode="rich",
)
console = Console()


@app.command()
def add(
    github_url: str = typer.Argument(help="GitHub repository URL to add"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Accept all proposed collections without prompting"),
    subpath: Optional[str] = typer.Option(None, "--subpath", help="Index only this subdirectory (for monorepos)"),
    name: Optional[str] = typer.Option(None, "--name", help="Project slug override (required when --subpath is used)"),
    extra_docs_path: list[str] = typer.Option(
        [], "--extra-docs-path",
        help="Repo-relative path (file or directory) outside --subpath to ingest as docs/examples. "
             "Repeat to add multiple paths, e.g. --extra-docs-path docs/guide.md --extra-docs-path examples/",
    ),
    from_local: Optional[str] = typer.Option(
        None, "--from-local",
        help="Path to a local clone of the repository. Skips the GitHub download — "
             "useful when registering multiple sub-projects from the same repo.",
    ),
    group: Optional[str] = typer.Option(None, "--group", help="Assign this repo to a project group"),
):
    """Add a GitHub project (runs onboarding wizard to detect content and plan ingestion)."""
    if subpath and not name:
        console.print("[red]--name is required when using --subpath[/red]")
        raise typer.Exit(1)
    if extra_docs_path and not subpath:
        console.print("[yellow]--extra-docs-path is only useful together with --subpath; ignoring.[/yellow]")
        extra_docs_path = []
    from resource_explorer.cli.wizard import OnboardingWizard
    wizard = OnboardingWizard()
    wizard.run(github_url, accept_all=yes, subproject_path=subpath, slug_override=name,
               extra_docs_paths=extra_docs_path or None, local_path=from_local,
               group_slug=group)


@app.command()
def remove(
    slug: str = typer.Argument(help="Project slug to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a project and drop all its pgvector collections."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        console.print(f"[red]Project '{slug}' not found.[/red]")
        raise typer.Exit(1)
    if not yes:
        typer.confirm(f"Remove '{project.display_name}' and all its collections?", abort=True)
    from resource_explorer.vector_store_pg import MultiCollectionStore
    store = MultiCollectionStore()
    for collection in project.collections:
        store.drop_collection(collection)
    registry.remove(slug)
    console.print(f"[green]Removed {project.display_name}.[/green]")


@app.command(name="list")
def list_projects(
    details: bool = typer.Option(False, "--details", "-d", help="Show collection names and vector counts"),
):
    """List all registered projects and their status."""
    from resource_explorer.cli.formatters import print_project_table
    from resource_explorer.registry import ProjectRegistry
    projects = ProjectRegistry().list_all()
    print_project_table(projects, console, details=details)


@app.command()
def ask(
    query: str = typer.Argument(help="Question to ask"),
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Scope to a specific project slug"),
    no_cache: bool = typer.Option(False, "--no-cache", help="Bypass query cache"),
):
    """Ask a one-shot question about a project (or all projects)."""
    import hashlib
    from resource_explorer.rag_system import RAGSystem
    from resource_explorer.observability.feedback_collector import FeedbackCollector

    # When no explicit project is given, check for a fuzzy alias match
    if not project:
        project = _maybe_resolve_alias(query)

    system = RAGSystem()
    response = system.query(query, resource_slug=project)
    console.print(response)
    query_hash = hashlib.sha256(query.encode()).hexdigest()[:16]
    FeedbackCollector().prompt_and_collect(query_hash)


@app.command()
def chat(
    project: Optional[str] = typer.Option(None, "--project", "-p", help="Scope to a specific project slug"),
    session_id: Optional[str] = typer.Option(None, "--session-id", "-s", help="Resume a previous session by ID"),
):
    """Start an interactive multi-turn chat session."""
    from resource_explorer.cli.interactive import InteractiveSession
    InteractiveSession(resource_slug=project, session_id=session_id).run()


@app.command(name="add-docs")
def add_docs(
    slug: str = typer.Argument(help="Project slug"),
    docs_url: Optional[str] = typer.Option(None, "--docs-url", help="Documentation site URL to ingest as web_docs"),
    homepage_url: Optional[str] = typer.Option(None, "--homepage", help="Homepage URL to store on the project"),
):
    """Attach a documentation site or homepage to an already-registered project."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.vector_store_pg import MultiCollectionStore

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        console.print(f"[red]Project '{slug}' not found.[/red]")
        raise typer.Exit(1)

    if homepage_url:
        # Just update the metadata field — no ingestion needed
        import sqlite3
        conn = sqlite3.connect(registry.db_path)
        conn.execute("UPDATE projects SET homepage_url = ? WHERE slug = ?", (homepage_url, project.slug))
        conn.commit()
        conn.close()
        console.print(f"[green]Homepage URL updated for '{slug}'.[/green]")

    if docs_url:
        # Update stored docs_url
        import sqlite3
        conn = sqlite3.connect(registry.db_path)
        conn.execute("UPDATE projects SET docs_url = ? WHERE slug = ?", (docs_url, project.slug))
        conn.commit()
        conn.close()
        console.print(f"[cyan]Ingesting docs from {docs_url}...[/cyan]")
        _ingest_web_docs(project, docs_url, registry)

    if not docs_url and not homepage_url:
        console.print("[yellow]Provide at least --docs-url or --homepage.[/yellow]")
        raise typer.Exit(1)


def _ingest_web_docs(project, docs_url: str, registry) -> None:
    """Fetch a docs site via Docling and insert into the project's web_docs collection."""
    from resource_explorer.ingestion.doc_parser import DocParser, DocChunk
    from resource_explorer.ingestion.data_prep import DataPrep
    from resource_explorer.vector_store_pg import MultiCollectionStore
    from resource_explorer.configdata.collection_config import COLLECTION_TYPES

    ctype = COLLECTION_TYPES.get("web_docs")
    if not ctype:
        console.print("[red]web_docs collection type not configured.[/red]")
        return

    collection_name = f"{project.slug}_web_docs"
    parser = DocParser(ctype.chunk_size, ctype.chunk_overlap)

    try:
        chunks = parser.parse_url(docs_url, project.slug)
    except Exception as exc:
        console.print(f"[red]Failed to fetch docs:[/red] {exc}")
        return

    chunks = DataPrep().filter(chunks)
    if not chunks:
        console.print("[yellow]No content extracted from docs URL.[/yellow]")
        return

    store = MultiCollectionStore()
    count = store.insert(collection_name, [c.text for c in chunks], [c.metadata for c in chunks])

    collections = list(project.collections)
    if collection_name not in collections:
        collections.append(collection_name)
    registry.update_indexed_at(project.slug, collections)
    console.print(f"[green]Inserted {count} chunks into {collection_name}.[/green]")


@app.command()
def refresh(
    slugs: Optional[list[str]] = typer.Argument(
        default=None,
        help="Project slug(s) to re-index. Omit when using --all.",
    ),
    all_projects: bool = typer.Option(False, "--all", help="Re-index every registered project"),
    top_level: bool = typer.Option(
        False, "--top-level",
        help="With --all: skip sub-projects (those with a parent_slug set)",
    ),
    no_stats: bool = typer.Option(False, "--no-stats", help="Skip GitHub statistics update"),
    history: int = typer.Option(
        90, "--history", "-H",
        help="Days of commit history to fetch (default: 90). Use 365 for a full year.",
    ),
    symbols: bool = typer.Option(
        False, "--symbols",
        help="Extract (or re-extract) code symbols from source files.",
    ),
):
    """Incrementally re-index one or more projects and refresh GitHub statistics.

    Examples:

      resource-explorer refresh myproject
      resource-explorer refresh proj1 proj2 proj3
      resource-explorer refresh --all
      resource-explorer refresh --all --top-level   # skip sub-projects
    """
    from resource_explorer.ingestion.incremental import IncrementalIndexer
    from resource_explorer.query_cache import QueryCache
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    targets = _resolve_slugs(registry, slugs, all_projects, top_level)
    if not targets:
        raise typer.Exit(1)

    failed: list[str] = []
    for project in targets:
        slug = project.slug
        label = f"[bold]{project.display_name}[/bold]" + (
            f" [dim]({slug})[/dim]" if project.display_name != slug else ""
        )
        if project.parent_slug:
            label += f" [dim]← sub-project of {project.parent_slug}[/dim]"
        console.print(f"\n[cyan]Refreshing {label} …[/cyan]")
        try:
            indexer = IncrementalIndexer()
            indexer.refresh(project)
            dropped = QueryCache().invalidate_project(slug)
            if dropped:
                console.print(f"  [dim]Cleared {dropped} cached query result(s).[/dim]")
            if symbols:
                try:
                    from resource_explorer.ingestion.pipeline import IngestionPipeline
                    count = IngestionPipeline().extract_symbols_only(
                        slug, project.github_url, project.collections or []
                    )
                    console.print(
                        f"  [dim]Symbols: {count} extracted.[/dim]" if count
                        else "  [yellow]No code collections — symbols skipped.[/yellow]"
                    )
                except Exception as exc:
                    console.print(f"  [yellow]Symbol extraction failed: {exc}[/yellow]")
            if not no_stats:
                try:
                    from resource_explorer.github.stats_fetcher import StatsFetcher
                    result = StatsFetcher().fetch(slug, lookback_days=history)
                    if "commits_fetch_error" in result:
                        console.print(
                            f"  [yellow]Commit history warning:[/yellow] {result['commits_fetch_error']}"
                        )
                    else:
                        n = result.get("commits_fetched", 0)
                        console.print(f"  [dim]Stats updated ({n} commits, {history}d lookback).[/dim]")
                except Exception as exc:
                    console.print(f"  [dim]Stats update skipped: {exc}[/dim]")
            # Collections were proposed once, at onboarding, from the repo as
            # it stood then. Nothing re-evaluates them, so a repo that gains
            # PDFs keeps ignoring them forever. This is a query over the file
            # inventory the refresh just updated -- no scan, no extra fetch.
            # It reports only: enabling a collection changes what gets embedded
            # and costs real ingestion time, so that stays a human decision.
            try:
                from resource_explorer.collection_drift import detect_drift
                for finding in detect_drift(registry, project.slug):
                    console.print(
                        f"  [yellow]Eligible but not enabled — {finding.summary}[/yellow]"
                    )
                    for path in finding.sample_paths:
                        console.print(f"      [dim]{path}[/dim]")
            except Exception as exc:
                console.print(f"  [dim]Collection drift check skipped: {exc}[/dim]")
            console.print(f"  [green]✓ Done[/green]")
        except Exception as exc:
            console.print(f"  [red]✗ Failed: {exc}[/red]")
            failed.append(slug)

    _print_batch_summary(targets, failed, "refreshed")


@app.command()
def status():
    """Show environment health: services, projects, collection counts."""
    from resource_explorer.dashboard.terminal_dashboard import print_status
    print_status(console)


@app.command()
def tui():
    """Launch the full-screen Textual TUI (project sidebar + chat + feedback)."""
    from resource_explorer.tui.app import run
    run()


@app.command()
def web(
    host: str = typer.Option("127.0.0.1", help="Bind host"),
    port: int = typer.Option(8810, help="Bind port"),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code changes (dev mode)"),
):
    """Start the web UI (FastAPI + HTML frontend with Plotly charts and markdown)."""
    import uvicorn
    console.print(f"[cyan]Starting web UI at http://{host}:{port}[/cyan]")
    # Configure before the server starts, and hand uvicorn a matching config so
    # server and application lines share one format and one destination. Without
    # log_config, uvicorn installs its own non-propagating handlers and its
    # output diverges from everything else's.
    from resource_explorer.observability.logging_setup import (
        configure_logging, uvicorn_log_config)
    configure_logging()
    uvicorn.run("resource_explorer.web.app:app", host=host, port=port, reload=reload,
                log_config=uvicorn_log_config())


@app.command()
def serve(
    host: str = typer.Option("0.0.0.0", help="Bind host"),
    port: int = typer.Option(8100, help="Base port"),
    all_agents: bool = typer.Option(False, "--all", help="Start all 6 specialist agents on consecutive ports"),
):
    """Start the AgentStack A2A server (exposes agents to beeai.dev platform).

    Without --all: orchestrator only on PORT (routes by intent, general RAG fallback).

    With --all: starts all 6 agents on consecutive ports:
      PORT+0  orchestrator
      PORT+1  statistics
      PORT+2  code search
      PORT+3  documentation
      PORT+4  health
      PORT+5  compare
    """
    from resource_explorer.agentstack_server import run as agentstack_run
    if all_agents:
        console.print(f"[cyan]Starting all Resource Explorer agents (base port {port})...[/cyan]")
    else:
        console.print(f"[cyan]Starting Resource Explorer orchestrator on {host}:{port}[/cyan]")
    agentstack_run(host=host, port=port, all_agents=all_agents)


def _resolve_slugs(registry, slugs, all_projects: bool, top_level: bool):
    """Return the list of Project objects to act on, validating inputs."""
    from resource_explorer.registry import ProjectRegistry  # already imported at call site, but safe
    if all_projects:
        projects = registry.list_all()
        if top_level:
            projects = [p for p in projects if not p.parent_slug]
        if not projects:
            console.print("[yellow]No projects registered.[/yellow]")
            return []
        return projects

    if not slugs:
        console.print("[red]Provide at least one slug or use --all.[/red]")
        return []

    result = []
    for slug in slugs:
        p = registry.get(slug)
        if p is None:
            console.print(f"[red]Project '{slug}' not found — skipping.[/red]")
        else:
            result.append(p)
    if not result:
        console.print("[red]No valid projects found.[/red]")
    return result


def _print_batch_summary(targets, failed: list[str], verb: str) -> None:
    """Print a one-liner batch completion summary only when >1 project was processed."""
    if len(targets) <= 1:
        return
    ok = len(targets) - len(failed)
    color = "green" if not failed else ("yellow" if ok else "red")
    console.print(
        f"\n[{color}]{verb.title()}: {ok}/{len(targets)} succeeded"
        + (f" — failed: {', '.join(failed)}" if failed else "")
        + f"[/{color}]"
    )


def _print_survey_report(result) -> None:
    """Print a full single-project survey report to the console."""
    from resource_explorer.surveyors.survey_report import AnnotationType
    console.print(f"\n[bold]Survey Report: {result.project_display_name}[/bold]")
    console.print(f"GitHub: {result.github_url}")
    if result.resource_slug != result.project_display_name:
        console.print(f"Slug:   {result.resource_slug}")
    console.print(f"Surveyed at: {result.surveyed_at.isoformat()}")
    console.print(f"Annotations: {len(result.annotations)}  |  Errors: {len(result.errors)}\n")

    for ann_type in AnnotationType:
        group = result.by_type(ann_type)
        if not group:
            continue
        console.print(f"[bold yellow]{ann_type.value}[/bold yellow] ({len(group)})")
        for ann in group:
            console.print(f"  • {ann.summary}")
            if ann.explanation:
                console.print(f"    [dim]{ann.explanation}[/dim]")
            # Show column-level schema for data file profiles
            if (
                ann_type == AnnotationType.SCHEMA_ANALYSIS
                and getattr(ann, "analysis_step", "") == "DataProfiling"
                and ann.json_properties.get("columns")
            ):
                cols = ann.json_properties["columns"]
                shown = cols[:8]
                parts = [f"{c['name']} ({c['dtype']})" for c in shown]
                if len(cols) > 8:
                    parts.append(f"+{len(cols) - 8} more")
                console.print(f"    [dim]Columns: {', '.join(parts)}[/dim]")
        console.print()

    if result.errors:
        console.print("[bold red]Survey errors:[/bold red]")
        for err in result.errors:
            console.print(f"  [red]• {err}[/red]")
        console.print()


def _print_survey_batch_summary(rows: list[dict], published: bool) -> None:
    """Print a Rich table summarising all projects surveyed in batch mode."""
    from rich.table import Table
    tbl = Table(
        "Project", "Annotations", "Errors",
        *( ["Report GUID"] if published else [] ),
        "Status",
        title="Survey Batch Summary",
        title_style="bold",
    )
    for r in rows:
        guid_short = (r["report_guid"] or "")[:12] + "…" if r["report_guid"] else "—"
        status = "[green]✓[/green]" if r["ok"] else "[red]✗[/red]"
        err_str = str(r["errors"]) if r["errors"] else "[dim]0[/dim]"
        row = [r["slug"], str(r["annotations"]), err_str]
        if published:
            row.append(guid_short)
        row.append(status)
        tbl.add_row(*row)
    console.print(tbl)


def _maybe_resolve_alias(query: str) -> Optional[str]:
    """
    Check for a fuzzy alias candidate before running a query.
    If found, prompt the user to confirm. If confirmed, saves the alias and returns the slug.
    """
    try:
        from resource_explorer.registry import ProjectRegistry
        registry = ProjectRegistry()
        result = registry.fuzzy_candidate(query)
        if not result:
            return None
        term, slug = result
        project = registry.get(slug)
        display = project.display_name if project else slug
        confirmed = typer.confirm(
            f'Did you mean "{display}"? Remember "{term}" as an alias for {slug}?',
            default=False,
        )
        if confirmed:
            registry.add_alias(term, slug)
            return slug
    except Exception:
        pass
    return None


# ── aliases sub-group ─────────────────────────────────────────────────────────


groups_app = typer.Typer(name="group", help="Group related resources under an umbrella project (e.g. 'egeria' containing egeria-python, egeria-advisor, and related DBs).")
app.add_typer(groups_app)


@groups_app.command(name="create")
def group_create(
    slug: str = typer.Argument(help="Group slug, e.g. 'egeria'"),
    display_name: str = typer.Option(..., "--name", help="Human-readable group name, e.g. 'Egeria'"),
    description: str = typer.Option("", "--desc", help="Optional description"),
):
    """Create (or rename) an umbrella project group."""
    from resource_explorer.registry import ProjectRegistry
    ProjectRegistry().create_group(slug, display_name, description)
    console.print(f"[green]Group '{slug}' created.[/green]")


@groups_app.command(name="list")
def group_list():
    """List all project groups with their member resources and aggregate stats."""
    from resource_explorer.registry import ProjectRegistry
    from rich.table import Table
    registry = ProjectRegistry()
    groups = registry.list_groups()
    if not groups:
        console.print("[dim]No groups defined yet. Create one with 'resource-explorer group create'.[/dim]")
        return

    table = Table(title="Project Groups", box=None, show_header=True, header_style="bold cyan")
    table.add_column("Group")
    table.add_column("Slug")
    table.add_column("Members", justify="right")
    table.add_column("Stars", justify="right")
    table.add_column("Commits (30d)", justify="right")
    table.add_column("Languages")

    for g in groups:
        stats = registry.get_group_aggregate_stats(g.slug)
        member_count = stats["project_count"] + stats["database_count"] + stats["filesystem_count"]
        
        langs = ", ".join(f"{l}({c})" for l, c in sorted(stats["languages"].items(), key=lambda x: x[1], reverse=True)[:3])
        
        table.add_row(
            g.display_name,
            g.slug,
            str(member_count),
            str(stats["stars"]),
            str(stats["commits_30d"]),
            langs or "[dim]none[/dim]"
        )
    console.print(table)


@groups_app.command(name="show")
def group_show(slug: str = typer.Argument(help="Group slug")):
    """Show member resources and aggregate stats for a single group."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    group = registry.get_group(slug)
    if not group:
        console.print(f"[red]Group '{slug}' not found.[/red]")
        raise typer.Exit(1)

    repos = registry.list_projects_in_group(slug)
    dbs = registry.list_databases_in_group(slug)
    fss = registry.list_filesystems_in_group(slug)
    stats = registry.get_group_aggregate_stats(slug)

    console.print(f"[bold]{group.display_name}[/bold] ({group.slug})")
    if group.description:
        console.print(f"[dim]{group.description}[/dim]")
    console.print()
    
    if repos:
        console.print(f"[bold cyan]Repositories ({len(repos)}):[/bold cyan]")
        for r in repos:
            console.print(f"  - {r.display_name} ({r.slug})")
    
    if dbs:
        console.print(f"[bold cyan]Databases ({len(dbs)}):[/bold cyan]")
        for db in dbs:
            console.print(f"  - {db.display_name} ({db.slug})")
            
    if fss:
        console.print(f"[bold cyan]Filesystems ({len(fss)}):[/bold cyan]")
        for fs in fss:
            console.print(f"  - {fs.display_name} ({fs.slug})")

    console.print(f"\n[bold cyan]Aggregate Stats:[/bold cyan]")
    console.print(f"  Stars: {stats['stars']} | Forks: {stats['forks']}")
    console.print(f"  Commits (30d/90d): {stats['commits_30d']} / {stats['commits_90d']}")
    console.print(f"  Contributors (max): {stats['contributors_count']}")
    console.print(f"  DB Assets: {stats['db_schema_count']} schemas, {stats['db_table_count']} tables")
    console.print(f"  FS Assets: {stats['fs_file_count']} files")


@groups_app.command(name="assign")
def group_assign(
    resource_type: str = typer.Argument(..., help="Type of resource: repo, database, or filesystem"),
    resource_slug: str = typer.Argument(..., help="Slug of the resource to assign"),
    group_slug: str = typer.Argument(..., help="Group slug to assign it to"),
):
    """Assign a registered resource to a group."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    
    if not registry.get_group(group_slug):
        console.print(f"[red]Group '{group_slug}' not found. Create it first with 'group create'.[/red]")
        raise typer.Exit(1)

    if resource_type == "repo":
        if not registry.get(resource_slug):
            console.print(f"[red]Repository '{resource_slug}' not found.[/red]")
            raise typer.Exit(1)
        registry.set_project_group(resource_slug, group_slug)
    elif resource_type == "database":
        if not registry.get_database(resource_slug):
            console.print(f"[red]Database '{resource_slug}' not found.[/red]")
            raise typer.Exit(1)
        registry.set_database_group(resource_slug, group_slug)
    elif resource_type == "filesystem":
        if not registry.get_filesystem(resource_slug):
            console.print(f"[red]Filesystem '{resource_slug}' not found.[/red]")
            raise typer.Exit(1)
        registry.set_filesystem_group(resource_slug, group_slug)
    else:
        console.print(f"[red]Invalid resource type '{resource_type}'. Use 'repo', 'database', or 'filesystem'.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{resource_type} '{resource_slug}' → group '{group_slug}'.[/green]")


@groups_app.command(name="unassign")
def group_unassign(
    resource_type: str = typer.Argument(..., help="Type of resource: repo, database, or filesystem"),
    resource_slug: str = typer.Argument(..., help="Slug of the resource to unassign"),
):
    """Remove a resource from whatever group it belongs to."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    
    if resource_type == "repo":
        registry.set_project_group(resource_slug, "")
    elif resource_type == "database":
        registry.set_database_group(resource_slug, "")
    elif resource_type == "filesystem":
        registry.set_filesystem_group(resource_slug, "")
    else:
        console.print(f"[red]Invalid resource type '{resource_type}'. Use 'repo', 'database', or 'filesystem'.[/red]")
        raise typer.Exit(1)

    console.print(f"[green]{resource_type} '{resource_slug}' ungrouped.[/green]")


@groups_app.command(name="remove")
def group_remove(
    slug: str = typer.Argument(help="Group slug to delete"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Delete a group. Member resources are ungrouped, not removed."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.get_group(slug):
        console.print(f"[red]Group '{slug}' not found.[/red]")
        raise typer.Exit(1)
    if not yes:
        typer.confirm(f"Delete group '{slug}'? Member resources will be ungrouped.", abort=True)
    unassigned = registry.delete_group(slug)
    console.print(f"[green]Group '{slug}' removed ({unassigned} resource(s) ungrouped).[/green]")


aliases_app = typer.Typer(name="aliases", help="Manage project name aliases.")
app.add_typer(aliases_app)


@aliases_app.command(name="list")
def aliases_list(
    slug: Optional[str] = typer.Argument(None, help="Project slug (omit to list all)"),
):
    """List stored aliases, optionally filtered to one project."""
    from resource_explorer.registry import ProjectRegistry
    rows = ProjectRegistry().list_aliases(slug)
    if not rows:
        console.print("[dim]No aliases found.[/dim]")
        return
    from rich.table import Table
    tbl = Table("Alias", "Project", "Source", "Created")
    for r in rows:
        tbl.add_row(r["alias"], r["project_slug"], r["confirmed_by"], r["created_at"][:10])
    console.print(tbl)


@aliases_app.command(name="add")
def aliases_add(
    alias: str = typer.Argument(help='Alias phrase, e.g. "Egeria Platform"'),
    slug: str = typer.Argument(help="Project slug to map to"),
):
    """Add a name alias for a project."""
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    if not registry.exists(slug):
        console.print(f"[red]Project '{slug}' not found.[/red]")
        raise typer.Exit(1)
    registry.add_alias(alias, slug)
    console.print(f'[green]Alias "{alias}" → {slug} saved.[/green]')


@aliases_app.command(name="remove")
def aliases_remove(
    alias: str = typer.Argument(help="Alias to remove"),
):
    """Remove a stored alias."""
    from resource_explorer.registry import ProjectRegistry
    removed = ProjectRegistry().remove_alias(alias)
    if removed:
        console.print(f'[green]Alias "{alias}" removed.[/green]')
    else:
        console.print(f'[yellow]Alias "{alias}" not found.[/yellow]')


repair_app = typer.Typer(
    name="repair",
    help="Repair a repo's registration: rename it, fix its github_url, enable a "
         "drift-flagged collection, or fix an investigation membership.",
)
app.add_typer(repair_app)


@repair_app.command(name="rename")
def repair_rename(
    slug: str = typer.Argument(help="Current repo slug"),
    new_slug: str = typer.Argument(help="New slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Rename a repo's slug — across the registry AND its pgvector collections.

    See docs/repair-operations-design.md for exactly what this moves and
    what it refuses. Shared collections another repo also lists are left
    untouched; only this repo's own collections are renamed.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.repair import RepairError, rename_repo
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        console.print(f"[red]Repo '{slug}' not found.[/red]")
        raise typer.Exit(1)
    if not yes:
        typer.confirm(
            f"Rename '{slug}' to '{new_slug}'? This moves {len(project.collections)} "
            f"pgvector collection(s) and every registry row that references it.",
            abort=True,
        )
    try:
        result = rename_repo(slug, new_slug, registry=registry)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Renamed '{result.old_slug}' -> '{result.new_slug}'.[/green]")
    for line in result.renamed_collections:
        console.print(f"  [dim]collection: {line}[/dim]")
    if result.unchanged_shared_collections:
        console.print(f"  [dim]shared collections left unchanged: {result.unchanged_shared_collections}[/dim]")


@repair_app.command(name="set-github-url")
def repair_set_github_url(
    slug: str = typer.Argument(help="Repo slug"),
    new_url: str = typer.Argument(help="Correct github_url"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Confirm dropping existing collections"),
):
    """Correct a repo's github_url. Drops its existing collections (they were
    embedded from the wrong repo) and leaves it needing a re-index — run
    `resource-explorer refresh <slug>` afterward."""
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.repair import RepairError, change_github_url
    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        console.print(f"[red]Repo '{slug}' not found.[/red]")
        raise typer.Exit(1)
    if not yes:
        typer.confirm(
            f"Change github_url for '{slug}' from {project.github_url!r} to {new_url!r}? "
            f"This drops all {len(project.collections)} existing collection(s); "
            f"you'll need to re-index afterward.",
            abort=True,
        )
    try:
        result = change_github_url(slug, new_url, confirm=True, registry=registry)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]'{slug}' now points at {result['new_url']}.[/green]")
    console.print(f"  [yellow]Dropped {len(result['dropped_collections'])} collection(s) — run "
                  f"'resource-explorer refresh {slug}' to re-index.[/yellow]")


@repair_app.command(name="enable-collection")
def repair_enable_collection(
    slug: str = typer.Argument(help="Repo slug"),
    collection_type: str = typer.Argument(help="Collection type name, e.g. 'pdfs' (see collection_drift output)"),
):
    """Turn on a collection type collection_drift flagged as eligible but not enabled."""
    from resource_explorer.repair import RepairError, enable_collection
    try:
        result = enable_collection(slug, collection_type)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]Enabled '{result['collection']}' — {result['chunks_inserted']} chunk(s) inserted.[/green]")


@repair_app.command(name="list-memberships")
def repair_list_memberships(slug: str = typer.Argument(help="Repo slug")):
    """Which investigations this repo is a Folio member of."""
    from resource_explorer.repair import RepairError, list_repo_investigation_memberships
    try:
        rows = list_repo_investigation_memberships(slug)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not rows:
        console.print(f"[dim]'{slug}' is not a member of any investigation.[/dim]")
        return
    from rich.table import Table
    tbl = Table("Investigation", "Status", "State", "Rationale")
    for r in rows:
        tbl.add_row(r["investigation_slug"], r["status"], r["state"], r["membership_rationale"])
    console.print(tbl)


@repair_app.command(name="repoint-membership")
def repair_repoint_membership(
    slug: str = typer.Argument(help="Repo slug"),
    from_investigation: str = typer.Argument(help="Investigation slug to remove membership from"),
    to_investigation: str = typer.Argument(help="Investigation slug to add membership to"),
):
    """Move a repo's investigation membership from one investigation to another."""
    from resource_explorer.repair import RepairError, repoint_investigation_member
    try:
        result = repoint_investigation_member(slug, from_investigation, to_investigation)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]'{slug}' moved from '{from_investigation}' to '{to_investigation}'.[/green]")


@repair_app.command(name="drop-membership")
def repair_drop_membership(
    slug: str = typer.Argument(help="Repo slug"),
    investigation_slug: str = typer.Argument(help="Investigation slug to drop membership from"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Drop a repo from one investigation's Folio."""
    from resource_explorer.repair import RepairError, drop_investigation_member
    if not yes:
        typer.confirm(f"Drop '{slug}' from investigation '{investigation_slug}'?", abort=True)
    try:
        drop_investigation_member(slug, investigation_slug)
    except RepairError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]'{slug}' dropped from '{investigation_slug}'.[/green]")


@app.command()
def survey(
    slugs: Optional[list[str]] = typer.Argument(
        default=None,
        help="Project slug(s) to survey. Omit when using --all.",
    ),
    all_projects: bool = typer.Option(False, "--all", help="Survey every registered project"),
    top_level: bool = typer.Option(
        False, "--top-level",
        help="With --all: skip sub-projects (those with a parent_slug set)",
    ),
    publish: bool = typer.Option(False, "--publish", help="Push the survey report to Egeria"),
    refresh_cache: bool = typer.Option(False, "--refresh", help="Force-refresh the file type cache from Egeria before surveying"),
    platform_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL (overrides EGERIA_PLATFORM_URL env var)"),
    view_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name (overrides EGERIA_VIEW_SERVER)"),
    data_path: Optional[str] = typer.Option(None, "--data-path", help="Path to a local clone for CSV/Parquet column-level profiling"),
):
    """Survey one or more projects and produce Egeria-aligned annotation reports.

    Without --publish: prints the survey as a markdown report (no Egeria required).
    With --publish: also pushes to Egeria.  Sub-projects that share a GitHub URL
    with their parent will share the same SourceControlLibrary asset in Egeria.

    Examples:

      resource-explorer survey myproject
      resource-explorer survey proj1 proj2 proj3
      resource-explorer survey --all
      resource-explorer survey --all --top-level     # skip sub-projects
      resource-explorer survey --all --publish       # survey + publish all
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_orchestrator import SurveyOrchestrator
    from resource_explorer.surveyors.survey_report import AnnotationType

    registry = ProjectRegistry()
    targets = _resolve_slugs(registry, slugs, all_projects, top_level)
    if not targets:
        raise typer.Exit(1)

    batch = len(targets) > 1

    # Build Egeria client once (if needed) and reuse across projects
    pyegeria_client = None
    if refresh_cache or publish:
        pyegeria_client = _try_build_egeria_client(platform_url, view_server)

    publisher = None
    if publish:
        from resource_explorer.surveyors.egeria_publisher import EgeriaConnectionError, EgeriaPublisher
        try:
            publisher = EgeriaPublisher(
                platform_url=platform_url,
                view_server=view_server,
                registry=registry,
            )
        except EgeriaConnectionError as exc:
            console.print(f"[red]Egeria connection failed: {exc}[/red]")
            raise typer.Exit(1)

    orchestrator = SurveyOrchestrator(
        registry=registry,
        pyegeria_client=pyegeria_client,
        force_refresh=refresh_cache,
        data_path=data_path,
    )

    failed: list[str] = []
    survey_rows: list[dict] = []   # for batch summary table

    for project in targets:
        slug = project.slug
        label = f"[bold]{project.display_name}[/bold]"
        if project.parent_slug:
            label += f" [dim](sub-project of {project.parent_slug}, path: {project.subproject_path or '/'})[/dim]"
        console.print(f"\n[cyan]Surveying {label} …[/cyan]")

        try:
            result = orchestrator.run(slug)
        except Exception as exc:
            console.print(f"  [red]✗ Survey failed: {exc}[/red]")
            failed.append(slug)
            survey_rows.append({"slug": slug, "annotations": 0, "errors": 1, "report_guid": None, "ok": False})
            try:
                from resource_explorer.activity_logger import log_survey
                log_survey(
                    registry,
                    entity_type="repo",
                    entity_slug=project.slug,
                    entity_name=project.display_name,
                    entity_location=project.github_url,
                    intent="assessment",
                    status="error",
                    summary="Survey failed",
                    detail=str(exc),
                )
            except Exception:
                pass
            continue

        # ── Per-project report (condensed in batch mode) ──────────────────
        if not batch:
            _print_survey_report(result)
        else:
            ann_counts = {t.value: len(result.by_type(t)) for t in AnnotationType if result.by_type(t)}
            summary = ", ".join(f"{v} {k}" for k, v in ann_counts.items())
            status_str = f"[green]✓[/green]" if not result.errors else f"[yellow]⚠ {len(result.errors)} error(s)[/yellow]"
            console.print(f"  {status_str} {len(result.annotations)} annotations — {summary}")
            if result.errors:
                for err in result.errors[:3]:
                    console.print(f"    [dim red]{err}[/dim red]")

        # ── Egeria publish ────────────────────────────────────────────────
        report_guid = None
        if publisher:
            try:
                console.print(f"  [dim]Publishing to Egeria…[/dim]")
                report_guid = publisher.publish(result)
                console.print(f"  [green]SurveyReport GUID: {report_guid}[/green]")
            except Exception as exc:
                console.print(f"  [red]Egeria publish failed: {exc}[/red]")
                try:
                    from resource_explorer.activity_logger import log_catalog
                    log_catalog(
                        registry,
                        entity_type="repo",
                        entity_slug=project.slug,
                        entity_name=project.display_name,
                        entity_location=project.github_url,
                        status="error",
                        summary="Egeria publish failed",
                        detail=str(exc),
                    )
                except Exception:
                    pass
                if not batch:
                    raise typer.Exit(1)
                failed.append(f"{slug}(publish)")

        survey_rows.append({
            "slug": slug,
            "annotations": len(result.annotations),
            "errors": len(result.errors),
            "report_guid": report_guid,
            "ok": slug not in failed,
        })

    if batch:
        _print_survey_batch_summary(survey_rows, publish)
    elif not failed and publish and not batch:
        # Single-project governance action prompt (batch skips this)
        catalog = typer.confirm(
            "\nTrigger governance action process to catalog this asset in Egeria?",
            default=False,
        )
        if catalog:
            console.print(
                "[yellow]Governance action integration is not yet implemented — "
                "watch for this in a future release.[/yellow]"
            )

    _print_batch_summary(targets, failed, "surveyed")


@app.command(name="survey-definition")
def survey_definition(
    slug: str = typer.Argument(help="Project slug to survey"),
    survey_def: Optional[str] = typer.Option(
        None, "--survey-definition", "-s",
        help="Name/qualifiedName of the Survey Definition (GovernanceActionProcess) in Egeria. "
             "If omitted, RE looks up candidates by Technology Type.",
    ),
    refresh_definition: bool = typer.Option(
        False, "--refresh-definition", help="Ignore any cached Survey Definition GUID and re-resolve"
    ),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL override"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name override"),
):
    """Execute a Survey Definition authored in Egeria against a registered project.

    Fetches the Survey Definition from Egeria, runs each step tagged
    executes_at=resource-explorer using the matching existing sub-surveyor
    (repo_health, repo_security, etc.), and publishes results back to Egeria via
    the existing, already-narrow EgeriaPublisher.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinitionReaderError,
        UnsupportedSurveyDefinitionError,
    )

    registry = ProjectRegistry()
    project = registry.get(slug)
    if not project:
        console.print(f"[red]Project '{slug}' not found.[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Running Survey Definition for '{slug}'...[/cyan]")
    try:
        results = run_survey_definition(
            entity_type="repo",
            slug=slug,
            registry=registry,
            survey_definition_ref=survey_def,
            refresh_definition=refresh_definition,
        )
    except UnsupportedSurveyDefinitionError as exc:
        console.print(f"[red]✗ Unsupported Survey Definition: {exc}[/red]")
        raise typer.Exit(1)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗ Survey Definition run failed: {exc}[/red]")
        raise typer.Exit(1)

    if results.get("errors"):
        console.print("[red]✗ Completed with errors:[/red]")
        for err in results["errors"]:
            console.print(f"  {err}")
        for step in results.get("steps", []):
            console.print(f"  [dim]{step['step']}: {step['status']}[/dim]")
        raise typer.Exit(1)

    console.print(f"[green]✓ Survey Definition completed: {results.get('process_qualified_name', '')}[/green]")
    for step in results.get("steps", []):
        console.print(f"  {step['step']}: {step['status']}")
    if results.get("egeria_report_guid"):
        console.print(f"  Report GUID: {results['egeria_report_guid']}")


@app.command(name="egeria-reset")
def egeria_reset(
    slugs: Optional[list[str]] = typer.Argument(default=None, help="Project slug(s) to reset"),
    all_projects: bool = typer.Option(False, "--all", help="Reset all registered projects"),
):
    """Clear cached Egeria GUIDs and survey history for one or more projects.

    Use this after resetting the Egeria database so that the next
    'survey --publish' re-registers each project from scratch.

    Examples:
      resource-explorer egeria-reset egeria
      resource-explorer egeria-reset egeria beeai_framework
      resource-explorer egeria-reset --all
    """
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()

    if all_projects:
        targets = [p.slug for p in registry.list()]
    elif slugs:
        targets = list(slugs)
    else:
        console.print("[red]Provide one or more project slugs, or use --all.[/red]")
        raise typer.Exit(1)

    if not targets:
        console.print("[yellow]No registered projects found.[/yellow]")
        raise typer.Exit(0)

    from rich.table import Table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("Project", min_width=20)
    table.add_column("GUID cleared", justify="center", min_width=13)
    table.add_column("Survey records deleted", justify="right", min_width=22)

    for slug in targets:
        if not registry.exists(slug):
            console.print(f"[yellow]Project '{slug}' not found — skipping.[/yellow]")
            continue
        result = registry.clear_egeria_registration(slug)
        guid_str = "[green]yes[/green]" if result["asset_guid_cleared"] else "[dim]none[/dim]"
        table.add_row(slug, guid_str, str(result["surveys_deleted"]))

    console.print(table)
    console.print(
        "\n[dim]Run [bold]resource-explorer survey <slug> --publish[/bold] "
        "to re-register and publish a fresh survey.[/dim]"
    )


@app.command(name="egeria-reports")
def egeria_reports(
    slug: str = typer.Argument(help="Project slug"),
    full: bool = typer.Option(False, "--full", help="Show all annotations for the latest survey"),
    platform_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL (overrides EGERIA_PLATFORM_URL env var)"),
    view_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name (overrides EGERIA_VIEW_SERVER)"),
):
    """Show Egeria survey reports published for a project.

    Reads from the local registry by default (no Egeria connection needed).
    Use --full to fetch and display all annotations from Egeria for the latest survey.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.egeria_reader import EgeriaReader, EgeriaReaderError

    registry = ProjectRegistry()
    project = registry.get(slug)
    if project is None:
        console.print(f"[red]Project '{slug}' not found.[/red]")
        raise typer.Exit(1)

    reader = EgeriaReader(
        platform_url=platform_url,
        view_server=view_server,
        registry=registry,
    )

    # ── Asset registration status ─────────────────────────────────────────────
    asset_guid = registry.get_egeria_asset_guid(slug)
    console.print(f"\n[bold]Egeria surveys for {project.display_name}[/bold]")
    if asset_guid:
        console.print(f"Asset GUID : [cyan]{asset_guid}[/cyan]  (SourceControlLibrary)")
    else:
        console.print("Asset GUID : [dim]not registered[/dim]")
    console.print(f"Platform   : {reader.platform_url}\n")

    # ── Survey history (from local registry) ──────────────────────────────────
    surveys = reader.get_survey_reports_from_registry(slug)

    if not surveys:
        console.print("[yellow]No surveys published to Egeria yet for this project.[/yellow]")
        console.print("Run [bold]resource-explorer survey " + slug + " --publish[/bold] to publish one.")
        raise typer.Exit(0)

    # Build table
    from rich.table import Table
    table = Table(show_header=True, header_style="bold", box=None, padding=(0, 2))
    table.add_column("#", style="dim", width=3)
    table.add_column("Surveyed at", min_width=22)
    table.add_column("Annotations", justify="right", min_width=11)
    table.add_column("Egeria Report GUID")

    for i, row in enumerate(surveys, start=1):
        suffix = "  ← latest" if i == 1 else ""
        count = str(row.get("annotation_count") or "—")
        table.add_row(
            str(i),
            row.get("surveyed_at", "—"),
            count,
            f"[cyan]{row.get('egeria_report_guid', '—')}[/cyan]{suffix}",
        )

    console.print(table)

    if not full:
        console.print("\nRun with [bold]--full[/bold] to display all annotations for the latest survey.")
        raise typer.Exit(0)

    # ── Full annotation display for the latest survey ─────────────────────────
    latest = surveys[0]
    report_guid = latest.get("egeria_report_guid", "")
    surveyed_at = latest.get("surveyed_at", "")

    console.print(f"\n[bold]Annotations for survey: {surveyed_at}[/bold]")
    console.print(f"Report GUID: [cyan]{report_guid}[/cyan]\n")

    try:
        annotations = reader.get_annotations(slug, surveyed_at)
    except EgeriaReaderError as exc:
        console.print(f"[red]Could not connect to Egeria: {exc}[/red]")
        console.print("[dim]Hint: set EGERIA_PLATFORM_URL in .env to enable full annotation display.[/dim]")
        raise typer.Exit(1)

    if not annotations:
        console.print("[yellow]No annotations found in Egeria for this survey.[/yellow]")
        raise typer.Exit(0)

    # Group by annotation_type
    from collections import defaultdict
    groups: dict[str, list] = defaultdict(list)
    for ann in annotations:
        groups[ann.get("annotation_type", "Unknown")].append(ann)

    for ann_type, group in sorted(groups.items()):
        console.print(f"[bold yellow]{ann_type}[/bold yellow] ({len(group)})")
        for ann in group:
            summary = ann.get("summary", "")
            confidence = ann.get("confidence")
            line = f"  • {summary}"
            if confidence is not None:
                line += f"  [dim][confidence: {confidence}][/dim]"
            console.print(line)
            explanation = ann.get("explanation", "")
            if explanation:
                console.print(f"    [dim]{explanation}[/dim]")
            # Show key subtype fields inline
            sub = ann.get("subtype_data", {})
            if sub.get("actionRequested"):
                console.print(f"    [yellow]Action: {sub['actionRequested']}[/yellow]")
            if sub.get("qualityScores"):
                scores = "  ".join(f"{k}={v}" for k, v in sub["qualityScores"].items())
                console.print(f"    [dim]Scores: {scores}[/dim]")
        console.print()


# ── database sub-group ────────────────────────────────────────────────────────

database_app = typer.Typer(name="database", help="Manage database entities and surveys.")
app.add_typer(database_app)


@database_app.command(name="register")
def database_register(
    slug: str = typer.Argument(help="Unique identifier for this database"),
    db_type: str = typer.Option(..., "--type", help="Database type (postgresql, mysql, etc.)"),
    host: str = typer.Option(..., "--host", help="Database host"),
    port: int = typer.Option(..., "--port", help="Database port"),
    database: str = typer.Option(..., "--database", help="Database name"),
    display_name: Optional[str] = typer.Option(None, "--name", help="Display name (defaults to slug)"),
    description: str = typer.Option("", "--description", help="Database description"),
    group: Optional[str] = typer.Option(None, "--group", help="Assign this database to a project group"),
):
    """Register a database in the registry.
    
    Example:
        resource-explorer database register my-postgres \\
            --type postgresql \\
            --host localhost \\
            --port 5432 \\
            --database mydb \\
            --name "My PostgreSQL Database" \\
            --group egeria
    """
    from resource_explorer.registry import DatabaseEntity, ProjectRegistry
    
    registry = ProjectRegistry()
    
    # Check if already exists
    if registry.database_exists(slug):
        console.print(f"[red]Database '{slug}' already registered.[/red]")
        raise typer.Exit(1)
    
    # Create database entity
    db_entity = DatabaseEntity(
        slug=slug,
        display_name=display_name or slug,
        db_type=db_type,
        host=host,
        port=port,
        database_name=database,
        description=description,
        group_slug=group or "",
    )
    
    # Register
    registry.register_database(db_entity)
    console.print(f"[green]✓ Database '{slug}' registered successfully.[/green]")
    console.print(f"  Type: {db_type}")
    console.print(f"  Host: {host}:{port}")
    console.print(f"  Database: {database}")


@database_app.command(name="list")
def database_list(
    db_type: Optional[str] = typer.Option(None, "--type", help="Filter by database type"),
):
    """List all registered databases."""
    from resource_explorer.registry import ProjectRegistry
    from rich.table import Table
    
    registry = ProjectRegistry()
    databases = registry.list_databases(db_type)
    
    if not databases:
        console.print("[dim]No databases registered.[/dim]")
        return
    
    table = Table("Slug", "Display Name", "Type", "Host", "Database", "Last Surveyed")
    for db in databases:
        last_surveyed = db.last_surveyed_at[:10] if db.last_surveyed_at else "Never"
        table.add_row(
            db.slug,
            db.display_name,
            db.db_type,
            f"{db.host}:{db.port}",
            db.database_name,
            last_surveyed,
        )
    
    console.print(table)


@database_app.command(name="survey")
def database_survey(
    slug: str = typer.Argument(help="Database slug to survey"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Database username (required for custom survey)"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Database password (required for custom survey)", hide_input=True),
    use_egeria: bool = typer.Option(False, "--egeria", help="Try Egeria survey first (hybrid approach)"),
    force_custom: bool = typer.Option(False, "--force-custom", help="Skip Egeria and use custom surveyor"),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL (overrides EGERIA_PLATFORM_URL)"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name (overrides EGERIA_VIEW_SERVER)"),
    secrets_path: Optional[str] = typer.Option(None, "--secrets-path", help="Path to Egeria secrets file"),
):
    """Run a survey on a registered database using hybrid approach.
    
    By default, uses custom surveyor (requires --user and --password).
    With --egeria, tries Egeria first and falls back to custom if needed.
    
    Examples:
        # Custom survey (direct connection)
        resource-explorer database survey my-postgres --user admin --password secret
        
        # Hybrid approach (try Egeria first, fall back to custom)
        resource-explorer database survey my-postgres --egeria --user admin --password secret
        
        # Force custom survey (skip Egeria)
        resource-explorer database survey my-postgres --force-custom --user admin --password secret
        
        # Egeria-only survey (with secrets file)
        resource-explorer database survey my-postgres --egeria --secrets-path /path/to/secrets.omsecrets
    """
    from resource_explorer.registry import ProjectRegistry
    
    registry = ProjectRegistry()
    
    # Check if database exists
    if not registry.database_exists(slug):
        console.print(f"[red]Database '{slug}' not found. Register it first with 'database register'.[/red]")
        raise typer.Exit(1)
    
    # Determine survey mode
    if use_egeria or (not force_custom and not user):
        # Use hybrid approach
        from resource_explorer.surveyors.database.hybrid_database_surveyor import run_hybrid_survey
        
        console.print(f"[cyan]Surveying database '{slug}' (hybrid mode)...[/cyan]")
        
        # Prepare credentials if provided
        credentials = None
        if user and password:
            credentials = {"user": user, "password": password}
        
        try:
            results = run_hybrid_survey(
                slug,
                credentials=credentials,
                registry=registry,
                force_custom=force_custom,
                platform_url=egeria_url,
                view_server=egeria_server,
                secrets_path=secrets_path,
            )
        except Exception as e:
            console.print(f"[red]✗ Survey failed: {e}[/red]")
            raise typer.Exit(1)
    else:
        # Use custom surveyor directly
        from resource_explorer.surveyors.database.database_surveyor import run_database_survey
        
        if not user or not password:
            console.print("[red]Custom survey requires --user and --password options.[/red]")
            raise typer.Exit(1)
        
        console.print(f"[cyan]Surveying database '{slug}' (custom mode)...[/cyan]")
        
        try:
            results = run_database_survey(
                slug,
                {"user": user, "password": password},
                registry,
            )
        except Exception as e:
            console.print(f"[red]✗ Survey failed: {e}[/red]")
            raise typer.Exit(1)
    
    # Display results
    if results.get("errors"):
        console.print(f"[red]✗ Survey failed:[/red]")
        for error in results["errors"]:
            console.print(f"  {error}")
        try:
            from resource_explorer.activity_logger import log_survey
            db_entity = registry.get_database(slug)
            log_survey(
                registry,
                entity_type="database",
                entity_slug=slug,
                entity_name=db_entity.display_name if db_entity else slug,
                entity_location=(
                    f"{db_entity.host}:{db_entity.port}/{db_entity.database_name}"
                    if db_entity else ""
                ),
                intent="assessment",
                status="error",
                summary="Database survey failed",
                detail="; ".join(str(e) for e in results["errors"]),
            )
        except Exception:
            pass
        raise typer.Exit(1)

    # Log successful database survey
    try:
        from resource_explorer.activity_logger import log_survey
        db_entity = registry.get_database(slug)
        source_label = results.get("source", "unknown")
        schema_info = results.get("schema_info", {})
        log_survey(
            registry,
            entity_type="database",
            entity_slug=slug,
            entity_name=db_entity.display_name if db_entity else slug,
            entity_location=(
                f"{db_entity.host}:{db_entity.port}/{db_entity.database_name}"
                if db_entity else ""
            ),
            intent="assessment",
            status="pending" if results.get("status") == "pending" else "ok",
            summary=(
                f"Database survey ({source_label}): "
                f"{schema_info.get('total_tables', results.get('annotation_count', 0))} tables"
            ),
            detail=results.get("message", ""),
        )
    except Exception:
        pass

    # Show survey source
    source = results.get("source", "unknown")
    if source == "egeria":
        console.print(f"[green]✓ Survey completed (source: Egeria)[/green]")
        
        # Check if pending
        if results.get("status") == "pending":
            console.print(f"\n[yellow]{results.get('message', 'Survey pending')}[/yellow]")
            if results.get("engine_action_guid"):
                console.print(f"[dim]Engine Action GUID: {results['engine_action_guid']}[/dim]")
            return
        
        # Show Egeria results
        console.print(f"\n[bold]Survey Report:[/bold]")
        console.print(f"  Report GUID: {results.get('egeria_report_guid', 'N/A')}")
        console.print(f"  Annotations: {results.get('annotation_count', 0)}")
        if results.get("description"):
            console.print(f"  Description: {results['description']}")
        
    elif source == "custom":
        console.print(f"[green]✓ Survey completed (source: Custom)[/green]")
        
        schema_info = results.get("schema_info", {})
        stats = results.get("statistics", {})
        
        console.print(f"\n[bold]Schema Summary:[/bold]")
        console.print(f"  Schemas: {len(schema_info.get('schemas', []))}")
        console.print(f"  Tables: {schema_info.get('total_tables', 0)}")
        console.print(f"  Columns: {schema_info.get('total_columns', 0)}")
        
        db_size = stats.get("database_size", {})
        if db_size:
            console.print(f"\n[bold]Database Size:[/bold]")
            console.print(f"  {db_size.get('size_pretty', 'unknown')}")
        
        console.print(f"\n[bold]Annotations:[/bold] {len(results.get('annotations', []))} created")
        console.print(f"[dim]Results stored in registry.[/dim]")
    else:
        console.print(f"[yellow]Unknown survey source: {source}[/yellow]")


@database_app.command(name="survey-definition")
def database_survey_definition(
    slug: str = typer.Argument(help="Database slug to survey"),
    user: Optional[str] = typer.Option(None, "--user", "-u", help="Database username"),
    password: Optional[str] = typer.Option(None, "--password", "-p", help="Database password", hide_input=True),
    survey_definition: Optional[str] = typer.Option(
        None, "--survey-definition", "-s",
        help="Name/qualifiedName of the Survey Definition (GovernanceActionProcess) in Egeria. "
             "If omitted, RE looks up candidates by Technology Type.",
    ),
    refresh_definition: bool = typer.Option(
        False, "--refresh-definition", help="Ignore any cached Survey Definition GUID and re-resolve"
    ),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL override"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name override"),
):
    """Execute a Survey Definition authored in Egeria against a registered database.

    Fetches the Survey Definition (a GovernanceActionProcess + chained steps) from
    Egeria, runs each step tagged executes_at=resource-explorer locally, and
    publishes results back to Egeria — without cataloging the database or
    triggering Egeria's own native survey as a side effect.

    Examples:
        resource-explorer database survey-definition my-postgres --user admin --password secret
        resource-explorer database survey-definition my-postgres -s PostgreSQLStandardSurvey --user admin --password secret
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinitionReaderError,
        UnsupportedSurveyDefinitionError,
    )

    registry = ProjectRegistry()
    if not registry.database_exists(slug):
        console.print(f"[red]Database '{slug}' not found. Register it first with 'database register'.[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Running Survey Definition for database '{slug}'...[/cyan]")
    try:
        results = run_survey_definition(
            entity_type="database",
            slug=slug,
            registry=registry,
            survey_definition_ref=survey_definition,
            refresh_definition=refresh_definition,
            db_user=user or "",
            db_pwd=password or "",
        )
    except UnsupportedSurveyDefinitionError as exc:
        console.print(f"[red]✗ Unsupported Survey Definition: {exc}[/red]")
        raise typer.Exit(1)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗ Survey Definition run failed: {exc}[/red]")
        raise typer.Exit(1)

    from resource_explorer.activity_logger import log_survey
    db_entity = registry.get_database(slug)
    status = "error" if results.get("errors") else "ok"
    try:
        log_survey(
            registry,
            entity_type="database",
            entity_slug=slug,
            entity_name=db_entity.display_name if db_entity else slug,
            entity_location=(
                f"{db_entity.host}:{db_entity.port}/{db_entity.database_name}" if db_entity else ""
            ),
            intent="assessment",
            status=status,
            summary=f"Survey Definition run ({results.get('process_qualified_name', '')})",
            detail="; ".join(results.get("errors", [])),
        )
    except Exception:
        pass

    if results.get("errors"):
        console.print("[red]✗ Completed with errors:[/red]")
        for err in results["errors"]:
            console.print(f"  {err}")
        for step in results.get("steps", []):
            console.print(f"  [dim]{step['step']}: {step['status']}[/dim]")
        raise typer.Exit(1)

    console.print(f"[green]✓ Survey Definition completed: {results.get('process_qualified_name', '')}[/green]")
    for step in results.get("steps", []):
        console.print(f"  {step['step']}: {step['status']}")
    if results.get("egeria_report_guid"):
        console.print(f"  Report GUID: {results['egeria_report_guid']}")


@database_app.command(name="remove")
def database_remove(
    slug: str = typer.Argument(help="Database slug to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a database from the registry."""
    from resource_explorer.registry import ProjectRegistry
    
    registry = ProjectRegistry()
    db = registry.get_database(slug)
    
    if not db:
        console.print(f"[red]Database '{slug}' not found.[/red]")
        raise typer.Exit(1)
    
    if not yes:
        typer.confirm(f"Remove database '{db.display_name}' ({slug})?", abort=True)
    
    registry.remove_database(slug)
    console.print(f"[green]✓ Database '{slug}' removed.[/green]")


@database_app.command(name="info")
def database_info(
    slug: str = typer.Argument(help="Database slug"),
):
    """Show detailed information about a database."""
    from resource_explorer.registry import ProjectRegistry
    from rich.table import Table
    
    registry = ProjectRegistry()
    db = registry.get_database(slug)
    
    if not db:
        console.print(f"[red]Database '{slug}' not found.[/red]")
        raise typer.Exit(1)
    
    console.print(f"\n[bold]{db.display_name}[/bold] ({db.slug})")
    console.print(f"Type: {db.db_type}")
    console.print(f"Host: {db.host}:{db.port}")
    console.print(f"Database: {db.database_name}")
    console.print(f"Status: {db.status.value}")
    if db.description:
        console.print(f"Description: {db.description}")
    console.print(f"Registered: {db.registered_at[:10]}")
    if db.last_surveyed_at:
        console.print(f"Last Surveyed: {db.last_surveyed_at[:10]}")
    
    # Show survey history
    surveys = registry.get_database_surveys(slug)
    if surveys:
        console.print(f"\n[bold]Survey History:[/bold] ({len(surveys)} surveys)")
        table = Table("Date", "Schemas", "Tables", "Columns")
        for survey in surveys[:5]:  # Show last 5
            table.add_row(
                survey["surveyed_at"][:10],
                str(survey["schema_count"]),
                str(survey["table_count"]),
                str(survey["column_count"]),
            )
        console.print(table)
    else:
        console.print("\n[dim]No surveys yet.[/dim]")


# ── filesystem sub-group ──────────────────────────────────────────────────────

filesystem_app = typer.Typer(name="filesystem", help="Manage filesystem entities and surveys.")
app.add_typer(filesystem_app)


@filesystem_app.command(name="register")
def filesystem_register(
    slug: str = typer.Argument(help="Unique identifier for this filesystem"),
    local_path: str = typer.Option(..., "--local-path", "-l", help="Local directory path to walk/traverse"),
    canonical_path: str = typer.Option("", "--canonical-path", "-c", help="Canonical root path recorded in Egeria"),
    display_name: Optional[str] = typer.Option(None, "--name", help="Display name (defaults to slug)"),
    description: str = typer.Option("", "--description", help="Filesystem description"),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name"),
    egeria_user: Optional[str] = typer.Option(None, "--egeria-user", help="Egeria user id"),
    egeria_password: Optional[str] = typer.Option(None, "--egeria-password", help="Egeria user password", hide_input=True),
    group: Optional[str] = typer.Option(None, "--group", help="Assign this filesystem to a project group"),
):
    """Register a local filesystem directory in the registry.
    
    Example:
        resource-explorer filesystem register my-data \
            --local-path /Users/dwolfson/localGit/data \
            --canonical-path file://shared-nfs/data \
            --name "Shared Data Mount" \
            --group egeria
    """
    from resource_explorer.registry import FileSystemEntity, ProjectRegistry
    
    registry = ProjectRegistry()
    
    # Check if already exists
    if registry.filesystem_exists(slug):
        console.print(f"[red]FileSystem '{slug}' already registered.[/red]")
        raise typer.Exit(1)
        
    # Resolve absolute path for local_path
    abs_local_path = os.path.abspath(local_path)
    if not os.path.exists(abs_local_path):
        console.print(f"[yellow]Warning: Local path '{abs_local_path}' does not exist on disk currently.[/yellow]")
        
    fs_entity = FileSystemEntity(
        slug=slug,
        display_name=display_name or slug,
        local_mount_point=abs_local_path,
        canonical_mount_point=canonical_path or abs_local_path,
        description=description,
        egeria_url=egeria_url or "",
        egeria_server=egeria_server or "",
        egeria_user=egeria_user or "",
        egeria_password=egeria_password or "",
        group_slug=group or "",
    )
    
    registry.register_filesystem(fs_entity)
    console.print(f"[green]✓ FileSystem '{slug}' registered successfully.[/green]")
    console.print(f"  Local Mount: {abs_local_path}")
    console.print(f"  Canonical Mount: {canonical_path or abs_local_path}")


@filesystem_app.command(name="list")
def filesystem_list():
    """List all registered filesystems."""
    from resource_explorer.registry import ProjectRegistry
    from rich.table import Table
    
    registry = ProjectRegistry()
    filesystems = registry.list_filesystems()
    
    if not filesystems:
        console.print("[dim]No filesystems registered.[/dim]")
        return
        
    table = Table("Slug", "Display Name", "Local Mount Point", "Canonical Mount Point", "Files", "Data Files", "Last Surveyed")
    for fs in filesystems:
        last_surveyed = fs.last_surveyed_at[:10] if fs.last_surveyed_at else "Never"
        table.add_row(
            fs.slug,
            fs.display_name,
            fs.local_mount_point,
            fs.canonical_mount_point or fs.local_mount_point,
            str(fs.file_count),
            str(fs.data_file_count),
            last_surveyed,
        )
        
    console.print(table)


@filesystem_app.command(name="survey")
def filesystem_survey(
    slug: str = typer.Argument(help="Filesystem slug to survey"),
    use_egeria: bool = typer.Option(False, "--egeria", help="Publish survey results to Egeria (hybrid approach)"),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL override"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name override"),
    egeria_user: Optional[str] = typer.Option(None, "--egeria-user", help="Egeria user id override"),
    egeria_password: Optional[str] = typer.Option(None, "--egeria-password", help="Egeria user password override", hide_input=True),
):
    """Run a local survey on the filesystem, walking files and profiling schemas.
    
    With --egeria, it automatically publishes the cataloged directory structure,
    data files, and survey annotations directly into Egeria's metadata server.
    """
    from resource_explorer.registry import ProjectRegistry, ProjectStatus
    
    registry = ProjectRegistry()
    
    # Check if filesystem exists
    fs_entity = registry.get_filesystem(slug)
    if not fs_entity:
        console.print(f"[red]FileSystem '{slug}' not found. Register it first with 'filesystem register'.[/red]")
        raise typer.Exit(1)
        
    console.print(f"[cyan]Surveying filesystem '{slug}'...[/cyan]")
    registry.update_filesystem_status(slug, ProjectStatus.ACTIVE)
    
    try:
        if use_egeria:
            from resource_explorer.surveyors.filesystem.hybrid_filesystem_surveyor import run_hybrid_filesystem_survey
            results = run_hybrid_filesystem_survey(
                slug,
                registry=registry,
                egeria_url=egeria_url,
                egeria_server=egeria_server,
                egeria_user=egeria_user,
                egeria_password=egeria_password,
                force_egeria_publish=True,
            )
        else:
            from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import LocalFileSystemSurveyor
            local_surveyor = LocalFileSystemSurveyor(fs_entity, registry)
            results = local_surveyor.run()
            registry.add_filesystem_survey(
                fs_slug=slug,
                surveyed_at=results["surveyed_at"],
                survey_data=results,
                egeria_report_guid="local-only",
                source="local",
            )
    except Exception as e:
        console.print(f"[red]✗ Survey failed: {e}[/red]")
        registry.update_filesystem_status(slug, ProjectStatus.ERROR, str(e))
        raise typer.Exit(1)

    # Show results
    console.print(f"[green]✓ Survey completed successfully.[/green]")
    console.print(f"  Total Files: {results['total_files']}")
    console.print(f"  Data Files: {results['total_data_files']}")
    console.print(f"  Total Size: {results['total_size']}")
    
    # Log successful walk in activity log — annotations only present for
    # local-mode results (hybrid mode's annotations are built and published
    # separately inside run_hybrid_filesystem_survey).
    try:
        from resource_explorer.activity_logger import log_survey
        from resource_explorer.surveyors.filesystem.local_filesystem_surveyor import build_rfa_annotations
        annotations = build_rfa_annotations(results) if not use_egeria else []
        log_survey(
            registry,
            entity_type="filesystem",
            entity_slug=slug,
            entity_name=fs_entity.display_name,
            entity_location=fs_entity.local_mount_point,
            intent="assessment",
            status="error" if annotations else "ok",
            summary=f"FileSystem survey: {results['total_files']} files ({results['total_data_files']} data files)",
            detail=f"Walked {fs_entity.local_mount_point}. Total size {results['total_size']}.",
            annotations=annotations,
        )
    except Exception:
        pass


@filesystem_app.command(name="survey-definition")
def filesystem_survey_definition(
    slug: str = typer.Argument(help="Filesystem slug to survey"),
    survey_definition: Optional[str] = typer.Option(
        None, "--survey-definition", "-s",
        help="Name/qualifiedName of the Survey Definition (GovernanceActionProcess) in Egeria. "
             "If omitted, RE looks up candidates by Technology Type.",
    ),
    refresh_definition: bool = typer.Option(
        False, "--refresh-definition", help="Ignore any cached Survey Definition GUID and re-resolve"
    ),
    egeria_url: Optional[str] = typer.Option(None, "--egeria-url", help="Egeria platform URL override"),
    egeria_server: Optional[str] = typer.Option(None, "--egeria-server", help="Egeria view server name override"),
):
    """Execute a Survey Definition authored in Egeria against a registered filesystem.

    Fetches the Survey Definition from Egeria, runs each step tagged
    executes_at=resource-explorer locally, and publishes results back to Egeria
    — without auto-cataloging the filesystem root or its files as a side effect.
    """
    from resource_explorer.registry import ProjectRegistry
    from resource_explorer.surveyors.survey_definition_executor import (
        SurveyDefinitionExecutorError,
        run_survey_definition,
    )
    from resource_explorer.surveyors.survey_definition_reader import (
        SurveyDefinitionReaderError,
        UnsupportedSurveyDefinitionError,
    )

    registry = ProjectRegistry()
    if not registry.get_filesystem(slug):
        console.print(f"[red]FileSystem '{slug}' not found. Register it first with 'filesystem register'.[/red]")
        raise typer.Exit(1)

    console.print(f"[cyan]Running Survey Definition for filesystem '{slug}'...[/cyan]")
    try:
        results = run_survey_definition(
            entity_type="filesystem",
            slug=slug,
            registry=registry,
            survey_definition_ref=survey_definition,
            refresh_definition=refresh_definition,
        )
    except UnsupportedSurveyDefinitionError as exc:
        console.print(f"[red]✗ Unsupported Survey Definition: {exc}[/red]")
        raise typer.Exit(1)
    except (SurveyDefinitionExecutorError, SurveyDefinitionReaderError) as exc:
        console.print(f"[red]✗ {exc}[/red]")
        raise typer.Exit(1)
    except Exception as exc:
        console.print(f"[red]✗ Survey Definition run failed: {exc}[/red]")
        raise typer.Exit(1)

    from resource_explorer.activity_logger import log_survey
    fs_entity = registry.get_filesystem(slug)
    status = "error" if results.get("errors") else "ok"
    try:
        log_survey(
            registry,
            entity_type="filesystem",
            entity_slug=slug,
            entity_name=fs_entity.display_name if fs_entity else slug,
            entity_location=fs_entity.local_mount_point if fs_entity else "",
            intent="assessment",
            status=status,
            summary=f"Survey Definition run ({results.get('process_qualified_name', '')})",
            detail="; ".join(results.get("errors", [])),
        )
    except Exception:
        pass

    if results.get("errors"):
        console.print("[red]✗ Completed with errors:[/red]")
        for err in results["errors"]:
            console.print(f"  {err}")
        raise typer.Exit(1)

    console.print(f"[green]✓ Survey Definition completed: {results.get('process_qualified_name', '')}[/green]")
    for step in results.get("steps", []):
        console.print(f"  {step['step']}: {step['status']}")
    if results.get("egeria_report_guid"):
        console.print(f"  Report GUID: {results['egeria_report_guid']}")


@filesystem_app.command(name="remove")
def filesystem_remove(
    slug: str = typer.Argument(help="Filesystem slug to remove"),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation"),
):
    """Remove a filesystem from the registry."""
    from resource_explorer.registry import ProjectRegistry
    
    registry = ProjectRegistry()
    fs = registry.get_filesystem(slug)
    
    if not fs:
        console.print(f"[red]FileSystem '{slug}' not found.[/red]")
        raise typer.Exit(1)
        
    if not yes:
        typer.confirm(f"Remove FileSystem '{fs.display_name}' ({slug})?", abort=True)
        
    registry.remove_filesystem(slug)
    console.print(f"[green]✓ FileSystem '{slug}' removed.[/green]")



def _try_build_egeria_client(platform_url: Optional[str], view_server: Optional[str]):
    """Attempt to build a pyegeria client for optional cache refresh. Returns None on failure."""
    import os
    url = platform_url or os.getenv("EGERIA_PLATFORM_URL", "")
    server = view_server or os.getenv("EGERIA_VIEW_SERVER", "")
    user = os.getenv("EGERIA_USER", "")
    password = os.getenv("EGERIA_USER_PASSWORD", "")
    if not url:
        return None
    try:
        from pyegeria import ValidMetadataManager
        client = ValidMetadataManager(server, url, user, password)
        client.create_egeria_bearer_token(user, password)
        return client
    except Exception:
        return None


# ── prefect sub-group ─────────────────────────────────────────────────────────

prefect_app = typer.Typer(name="prefect", help="Manage Prefect flows, workers, and deployments.")
app.add_typer(prefect_app)


@prefect_app.command(name="deploy")
def prefect_deploy():
    """Deploy Resource Explorer flows to the Prefect server."""
    from pathlib import Path

    from resource_explorer.prefect.flows import re_survey_flow
    from resource_explorer.config import get_config

    config = get_config()
    console.print(f"[blue]Deploying flows to Prefect server at {config.prefect.api_url}...[/blue]")
    try:
        # .deploy() alone errors ("Either an image or remote storage location
        # must be provided") because a bare work_pool_name assumes the worker
        # fetches code from a remote source (git/Docker) — the right shape for
        # a `process`-type pool running on this same machine is `from_source`
        # pointing at this checkout, so the worker subprocess can just import
        # the flow module directly. Confirmed live against a local server
        # 2026-08-26 — this checkout's own root is the source, since the
        # worker process runs with the resource-explorer package importable.
        source_root = Path(__file__).resolve().parents[2]  # packages/resource-explorer/
        re_survey_flow.from_source(
            source=str(source_root),
            entrypoint="resource_explorer/prefect/flows.py:re_survey_flow",
        ).deploy(
            name="re-survey-step-deployment",
            work_pool_name=config.prefect.work_pool,
        )
        console.print(f"[green]✓ Flows successfully deployed to work pool '[bold]{config.prefect.work_pool}[/bold]'![/green]")
    except Exception as e:
        console.print(f"[red]Failed to deploy flows: {e}[/red]")
        raise typer.Exit(1)


@prefect_app.command(name="worker")
def prefect_worker(
    pool: Optional[str] = typer.Option(None, "--pool", "-p", help="Work pool name override"),
):
    """Start a local Prefect worker to run tasks from the work pool."""
    import subprocess
    from resource_explorer.config import get_config

    config = get_config()
    pool_name = pool or config.prefect.work_pool
    console.print(f"[blue]Starting Prefect worker for pool '[bold]{pool_name}[/bold]'...[/blue]")
    try:
        subprocess.run(["prefect", "worker", "start", "--pool", pool_name], check=True)
    except KeyboardInterrupt:
        console.print("[yellow]\nWorker stopped.[/yellow]")
    except Exception as e:
        console.print(f"[red]Failed to run worker: {e}[/red]")
        raise typer.Exit(1)


# ── batch CSV import/export (resource_explorer/batch_io.py) ─────────────────

@app.command(name="export-resources")
def export_resources(
    path: str = typer.Argument(help="CSV file to write"),
):
    """Export every registered resource as a CSV inventory + scorecard.

    Columns prefixed `status_` are observed state and are ignored if the file is
    imported again, so an export can be handed straight back to import-resources
    without editing. See resource_explorer/batch_io.py for why that line exists.
    """
    from resource_explorer.batch_io import export_rows, write_csv
    from resource_explorer.registry import ProjectRegistry

    rows = export_rows(ProjectRegistry())
    n = write_csv(rows, path)
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["resource_type"]] = by_type.get(r["resource_type"], 0) + 1
    console.print(f"[green]Wrote {n} resource(s) to {path}[/green]")
    for t, c in sorted(by_type.items()):
        console.print(f"  {t}: {c}")


@app.command(name="import-resources")
def import_resources(
    path: str = typer.Argument(help="CSV file to read (see export-resources for the shape)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would happen, write nothing"),
    group: Optional[str] = typer.Option(None, "--group", help="Group for rows that name none"),
):
    """Register resources listed in a CSV, skipping any already present.

    Registers only — no RAG ingestion, matching the org-import path, so a large
    batch is cheap. Surveying afterwards is the expensive half.
    """
    from resource_explorer.batch_io import describe_skipped, parse_csv, plan_import
    from resource_explorer.github.org_importer import OrgImporter
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    try:
        rows = parse_csv(path)
    except (OSError, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1)
    if not rows:
        console.print("[yellow]No rows found.[/yellow]")
        raise typer.Exit(0)

    plan = plan_import(registry, rows)
    console.print(f"[bold]{plan.total} row(s) in {path}[/bold]")
    console.print(f"  [green]{len(plan.to_register)}[/green] to register")
    console.print(f"  [dim]{len(plan.already_registered)} already registered[/dim]")
    for label, bucket in (("invalid", plan.invalid),
                          ("duplicate in file", plan.duplicate_in_file),
                          ("unsupported type", plan.unsupported_type)):
        if bucket:
            console.print(f"  [yellow]{len(bucket)} {label}[/yellow]")
            for r in bucket[:10]:
                console.print(f"     {describe_skipped(r)}")
            if len(bucket) > 10:
                console.print(f"     … and {len(bucket) - 10} more")

    if dry_run:
        console.print("[dim]--dry-run: nothing written.[/dim]")
        raise typer.Exit(0)
    if not plan.to_register:
        raise typer.Exit(0)

    importer = OrgImporter(registry=registry)
    registered = failed = 0
    for row in plan.to_register:
        try:
            importer.import_repo(
                row.address,
                row.display_name or row.address.rstrip("/").rsplit("/", 1)[-1],
                row.notes,
                row.group or group or "",
            )
            registered += 1
        except Exception as exc:
            # Per-row isolation, like _run_import_batch: one bad repo in a batch
            # of hundreds must not end the run.
            failed += 1
            console.print(f"  [red]line {row.line}: {row.address} — {exc}[/red]")

        # Disposition is intent, so it is applied whether or not registration
        # succeeded — a candidate can carry one before it is ever registered.
        if row.disposition:
            try:
                registry.set_disposition(row.address, row.disposition,
                                         reason=row.disposition_reason)
            except Exception as exc:
                console.print(f"  [yellow]line {row.line}: disposition not set — {exc}[/yellow]")

    console.print(f"[green]Registered {registered}[/green]"
                  + (f", [red]{failed} failed[/red]" if failed else ""))


@app.command(name="egeria-recheck")
def egeria_recheck(
    entity_type: Optional[list[str]] = typer.Option(
        None, "--entity-type", help="Restrict to repo/database/filesystem (repeatable; default: all)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Report what would be recorded, write nothing"),
):
    """Proactively re-check every cached Egeria GUID against the live server.

    Reactive divergence detection only marks a linkage stale the next time
    something actually uses the cached GUID — which can be a long time after
    Egeria's repository was reset. This asks Egeria about every cached GUID
    right now, so 'Admin > Egeria Links' reflects reality immediately rather
    than staying empty until each resource happens to be surveyed again.

    Examples:
      resource-explorer egeria-recheck
      resource-explorer egeria-recheck --dry-run
      resource-explorer egeria-recheck --entity-type repo --entity-type database
    """
    from resource_explorer.egeria_linkage import recheck_all_linkages
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    types = list(entity_type) if entity_type else None

    def _progress(checked, total, etype, slug):
        console.print(f"  [{checked}/{total}] {etype}/{slug}", end="\r")

    console.print("[bold]Rechecking cached Egeria GUIDs...[/bold]"
                  + (" [dim](dry run)[/dim]" if dry_run else ""))
    try:
        result = recheck_all_linkages(registry, entity_types=types, progress=_progress,
                                      dry_run=dry_run)
    except Exception as exc:
        console.print(f"\n[red]Could not connect to Egeria: {exc}[/red]")
        raise typer.Exit(1)

    console.print()  # clear the progress line
    console.print(f"  checked: {result['checked']}   "
                  f"[green]ok: {result['ok']}[/green]   "
                  f"[red]stale: {result['stale']}[/red]   "
                  f"[yellow]errors: {result['errors']}[/yellow]   "
                  f"[dim]skipped (no cached GUID): {result['skipped']}[/dim]")

    stale_rows = [d for d in result["details"] if d["result"] == "stale"]
    if stale_rows:
        # Printed as plain lines rather than a rich Table. Rich shrinks columns to
        # the console width — 80 when output is not a terminal — and *truncates*
        # rather than wrapping, which cut every GUID to 35 characters. A GUID
        # missing its last character still looks like a GUID, so a piped or saved
        # report carried identifiers that were quietly wrong, exactly when the
        # report is most likely to be kept and acted on later.
        console.print()
        console.print("[bold]Stale linkages"
                      + (" (not recorded — dry run)" if dry_run else " (recorded)")
                      + ":[/bold]")
        for row in stale_rows:
            console.print(f"  {row['entity_type']:<10}  {row['slug']:<28}  {row['guid']}",
                          highlight=False, soft_wrap=True)
        console.print(
            "\n[dim]Resolve from Admin > Egeria Links, or run "
            "[bold]resource-explorer egeria-reset <slug>[/bold] for repos.[/dim]"
        )

    error_rows = [d for d in result["details"] if d["result"] == "error"]
    if error_rows:
        console.print()
        console.print("[yellow]Could not verify (not marked stale):[/yellow]")
        for row in error_rows:
            console.print(f"  {row['entity_type']}/{row['slug']}: {row['detail'][:200]}")


if __name__ == "__main__":
    app()
