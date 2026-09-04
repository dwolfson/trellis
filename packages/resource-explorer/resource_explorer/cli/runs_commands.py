"""CLI parity for the workflows and the run queue — plan §3.

"The CLI has no `analysis` command at all" was the plan's own finding, and it
was true for discovery and curate materialization too. Not because the CLI was
weaker than the web tier but because that code lived inside route modules. With
`resource_explorer/workflows/` extracted, these commands are thin: each one
calls the same function the corresponding route calls.

**`--queue` is the interesting flag.** By default a command runs its workflow
inline, in this process, and prints the result — which is what an operator at a
terminal wants, and what makes the CLI usable with no worker running at all.
With `--queue` the command instead enqueues a row and prints its id, so the same
command can hand work to a running worker: useful for a long survey you do not
want tied to your SSH session, and the reason `runs enqueue` exists as well.

The two paths deliberately share the workflow function rather than the queue
handler sharing an approximation of it: "what an analysis run does" must not
depend on whether a person or a worker started it.
"""
from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.table import Table

console = Console()

analysis_app = typer.Typer(name="analysis", help="Run local analyses and stage batches.")
scout_app = typer.Typer(name="scout", help="Fast coarse scans (Scouting).")
discovery_app = typer.Typer(name="discovery", help="Find repos worth considering.")
curate_app = typer.Typer(name="curate", help="Act on curator verdicts.")
runs_app = typer.Typer(name="runs", help="Inspect and drive the Postgres run queue.")


def _registry():
    from resource_explorer.registry import ProjectRegistry

    return ProjectRegistry()


def _enqueue(kind: str, target: dict, *, activity_id: str = "") -> str:
    from resource_explorer.run_queue import requested_by

    run_id = _registry().enqueue_run(
        kind, target, result_ref=activity_id, requested_by=requested_by(),
    )
    console.print(f"[cyan]queued[/cyan] {kind} → run [bold]{run_id}[/bold]")
    console.print("[dim]A `resource-explorer worker` (or a `web --embed-worker`) "
                  "executes it. `runs show " + run_id + "` to follow it.[/dim]")
    return run_id


# ── analysis ─────────────────────────────────────────────────────────────────


@analysis_app.command("run")
def analysis_run(
    project: str = typer.Argument(help="Project slug"),
    analysis_id: str = typer.Argument(help="Analysis id, e.g. security_scan"),
    publish: bool = typer.Option(
        False, "--publish/--no-publish",
        help="Force the Egeria auto-publish attempt even when the resource has "
             "no assigned Egeria project. Off by default, matching the route: "
             "publish is gated on assignment, not on the caller asking."),
    queue: bool = typer.Option(False, "--queue", help="Enqueue instead of running inline"),
):
    """Run one analysis's mapped survey step(s) against a project."""
    if queue:
        _enqueue("analysis_run", {"slug": project, "analysis_id": analysis_id})
        return

    from resource_explorer.workflows.analysis import resolve_analysis_plan, run_analysis

    is_ingest, steps = resolve_analysis_plan(analysis_id)
    if not is_ingest and not steps:
        console.print(f"[red]Analysis '{analysis_id}' has no mapped survey step(s).[/red]")
        raise typer.Exit(code=1)

    result = run_analysis(project, analysis_id, is_ingest=is_ingest, steps=steps)
    if result.status == "error":
        console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]{result.summary}[/green]")
    # Three states, three sentences. "Not attempted" and "attempted and failed"
    # are different facts and the second one needs a retry.
    if result.published is True:
        console.print("[dim]Published to Egeria.[/dim]")
    elif result.published is False:
        console.print("[yellow]Auto-publish to Egeria failed — findings are stored; "
                      "publish again to retry.[/yellow]")
    elif publish:
        console.print("[yellow]--publish was given but nothing was published: the "
                      "resource has no assigned Egeria project, or the run produced "
                      "no annotations.[/yellow]")


@analysis_app.command("stage-batch")
def analysis_stage_batch(
    project: str = typer.Argument(help="Project slug"),
    stage: str = typer.Argument(help="Funnel stage / intent, e.g. scouting"),
    queue: bool = typer.Option(False, "--queue", help="Enqueue instead of running inline"),
):
    """Run every local analysis tagged with one stage, as a single survey call."""
    from resource_explorer.workflows.analysis import resolve_stage_step_keys, run_stage_batch

    step_keys, analysis_count = resolve_stage_step_keys(stage)
    if not step_keys:
        console.print(f"[red]Stage '{stage}' has no batch-runnable local analyses.[/red]")
        raise typer.Exit(code=1)
    if queue:
        _enqueue("stage_batch", {"slug": project, "stage": stage, "step_keys": step_keys})
        return

    console.print(f"[cyan]{len(step_keys)} step(s) from {analysis_count} analyses[/cyan]")
    result = run_stage_batch(project, stage, step_keys)
    console.print(f"[green]{result.summary}[/green]" if result.status == "ok"
                  else f"[red]{result.summary}[/red]")
    for err in result.errors:
        console.print(f"  [yellow]{err}[/yellow]")
    if result.status == "error":
        raise typer.Exit(code=1)


# ── scouting ─────────────────────────────────────────────────────────────────


@scout_app.command("run")
def scout_run(
    project: str = typer.Argument(help="Project slug"),
    queue: bool = typer.Option(False, "--queue", help="Enqueue instead of running inline"),
):
    """Coarse scan — repo stats plus language classification."""
    if queue:
        _enqueue("scouting_scan", {"slug": project})
        return

    from resource_explorer.workflows.scouting import run_scouting_scan

    result = run_scouting_scan(project)
    if result.status == "error":
        console.print(f"[red]{result.error}[/red]")
        raise typer.Exit(code=1)
    console.print(f"[green]{result.message}[/green]")


# ── discovery ────────────────────────────────────────────────────────────────


@discovery_app.command("search")
def discovery_search(
    query: str = typer.Argument("", help="Free-text keyword"),
    org: str = typer.Option("", "--org", help="Restrict to one GitHub account"),
    language: str = typer.Option("", "--language"),
    topic: str = typer.Option("", "--topic"),
    min_stars: int = typer.Option(0, "--min-stars"),
    limit: int = typer.Option(30, "--limit"),
):
    """Search GitHub for candidate repos, with local triage context attached."""
    from resource_explorer.workflows.discovery import (
        DiscoveryError,
        RepoSearchCriteria,
        enrich_repos,
        run_search_query,
    )

    registry = _registry()
    criteria = RepoSearchCriteria(
        keyword=query, org=org, language=language, topic=topic,
        min_stars=min_stars, limit=limit,
    )
    try:
        repos = run_search_query(criteria, registry)
    except DiscoveryError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1)

    table = Table(title=f"{len(repos)} result(s)")
    for col in ("repo", "★", "language", "registered", "disposition"):
        table.add_column(col)
    for r in enrich_repos(repos, registry):
        table.add_row(r.full_name, str(r.stars), r.language,
                      "yes" if r.already_registered else "", r.disposition)
    console.print(table)


@discovery_app.command("expand-org")
def discovery_expand_org(
    org: str = typer.Argument(help="GitHub account name"),
    queue: bool = typer.Option(False, "--queue", help="Enqueue instead of running inline"),
):
    """List a GitHub account's repo URLs, newest-activity first."""
    if queue:
        _enqueue("discovery_expand", {"org": org})
        return

    from resource_explorer.workflows.discovery import expand_org

    expansion = expand_org(org)
    if expansion.error:
        console.print(f"[red]{expansion.error}[/red]")
        raise typer.Exit(code=1)
    for url in expansion.urls:
        console.print(url, highlight=False)
    # Said out loud, not inferred from the count: a capped expansion that reads
    # as the whole account is the failure this flag exists to prevent.
    if expansion.truncated:
        console.print(f"[yellow]Truncated at {len(expansion.urls)} — this account "
                      "has more repos than were listed.[/yellow]")


# ── curate ───────────────────────────────────────────────────────────────────


@curate_app.command("materialize")
def curate_materialize(
    project: str = typer.Argument(help="Project slug"),
    target: str = typer.Argument(
        help="A component's scope_locator, or a blueprint's 'perspective::cluster_name'"),
    entity_type: str = typer.Option("repo", "--entity-type"),
):
    """Materialize an accepted component or blueprint verdict into Egeria.

    Which one is decided by the id's shape — `perspective::cluster_name` is a
    blueprint, anything else is a component's scope_locator. That is the same
    key `add_blueprint_verdict` builds, not a new convention.
    """
    from resource_explorer.workflows.curate import (
        materialize_blueprint_if_accepted,
        materialize_component_if_accepted,
    )

    registry = _registry()
    if "::" in target:
        perspective, cluster_name = target.split("::", 1)
        result = materialize_blueprint_if_accepted(
            registry, entity_type, project, perspective, cluster_name, "accepted",
        )
    else:
        result = materialize_component_if_accepted(
            registry, entity_type, project, target, "accepted",
        )

    if result is None:
        console.print("[yellow]Nothing attempted — materialization is only wired "
                      "for entity_type='repo'.[/yellow]")
        raise typer.Exit(code=1)
    console.print(json.dumps(result, indent=2, default=str))
    if result.get("status") == "error":
        raise typer.Exit(code=1)


# ── runs ─────────────────────────────────────────────────────────────────────


@runs_app.command("list")
def runs_list(
    state: str = typer.Option("", "--state", help="queued | claimed | running | succeeded | failed | cancelled"),
    kind: str = typer.Option("", "--kind"),
    limit: int = typer.Option(30, "--limit"),
):
    """What is in the queue, newest first."""
    from resource_explorer.registry import ProjectRegistry

    if state and state not in ProjectRegistry.RUN_STATES:
        console.print(f"[red]Unknown state '{state}' — expected one of "
                      f"{list(ProjectRegistry.RUN_STATES)}[/red]")
        raise typer.Exit(code=1)
    rows = _registry().list_runs(state=state or None, kind=kind or None, limit=limit)
    if not rows:
        # "No rows matched" and "the queue is empty" are different answers; say
        # which one this is.
        scope = f" in state '{state}'" if state else ""
        console.print(f"[dim]No runs{scope}.[/dim]")
        return
    table = Table()
    for col in ("id", "kind", "state", "claimed_by", "enqueued_at", "error"):
        table.add_column(col, overflow="fold")
    for r in rows:
        table.add_row(r["id"], r["kind"], r["state"], r["claimed_by"] or "—",
                      r["enqueued_at"], (r["error"] or "")[:80])
    console.print(table)


@runs_app.command("show")
def runs_show(run_id: str = typer.Argument(help="Run id")):
    """Everything recorded about one run."""
    row = _registry().get_run(run_id)
    if row is None:
        console.print(f"[red]Run '{run_id}' not found[/red]")
        raise typer.Exit(code=1)
    console.print(json.dumps(row, indent=2, default=str))


@runs_app.command("cancel")
def runs_cancel(run_id: str = typer.Argument(help="Run id")):
    """Cancel a run that has not been claimed yet."""
    registry = _registry()
    row = registry.get_run(run_id)
    if row is None:
        console.print(f"[red]Run '{run_id}' not found[/red]")
        raise typer.Exit(code=1)
    if registry.cancel_queued_run(run_id):
        console.print(f"[green]cancelled {run_id}[/green]")
        return
    console.print(
        f"[yellow]Run {run_id} is {row['state']}, not queued — nothing was "
        f"changed.[/yellow]\n[dim]A claimed run holds a real thread in "
        f"{row.get('claimed_by') or 'a worker'} and Python threads cannot be "
        "interrupted. Marking it cancelled would be a claim about work that is "
        "still running. If that worker dies, reconciliation resolves the row as "
        "failed.[/dim]"
    )
    raise typer.Exit(code=1)


@runs_app.command("enqueue")
def runs_enqueue(
    kind: str = typer.Argument(help="analysis_run | survey_definition_run | scouting_scan | stage_batch | discovery_expand"),
    target: str = typer.Argument("{}", help="Target as a JSON object, e.g. '{\"slug\": \"myrepo\"}'"),
    requested_by: str = typer.Option("", "--requested-by",
                                     help="Attribute the run to a user id (fairness applies)"),
):
    """Queue work for a worker straight from a shell.

    The escape hatch for anything the typed commands above do not cover, and the
    way to script the queue. `target` is passed to the kind's handler verbatim —
    see run_queue.py's HANDLERS for what each one reads.
    """
    from resource_explorer.registry import ProjectRegistry

    if kind not in ProjectRegistry.RUN_KINDS:
        console.print(f"[red]Unknown kind '{kind}' — expected one of "
                      f"{list(ProjectRegistry.RUN_KINDS)}[/red]")
        raise typer.Exit(code=1)
    try:
        parsed = json.loads(target)
    except ValueError as exc:
        console.print(f"[red]target is not valid JSON: {exc}[/red]")
        raise typer.Exit(code=1)
    if not isinstance(parsed, dict):
        console.print("[red]target must be a JSON object[/red]")
        raise typer.Exit(code=1)

    run_id = _registry().enqueue_run(kind, parsed, requested_by=requested_by)
    console.print(run_id, highlight=False)


def register(app: typer.Typer) -> None:
    """Attach every command group above to the root CLI app."""
    app.add_typer(analysis_app)
    app.add_typer(scout_app)
    app.add_typer(discovery_app)
    app.add_typer(curate_app)
    app.add_typer(runs_app)
