"""
Egeria Advisor CLI - Main Entry Point

This module provides the main command-line interface for the Egeria Advisor.
"""

import os
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from loguru import logger

from advisor.rag_system import get_rag_system
from advisor.cli.formatters import ResponseFormatter
from advisor.cli.interactive import InteractiveSession
from advisor.cli.agent_session import AgentInteractiveSession

console = Console()


@click.command()
@click.argument('query', required=False)
@click.option(
    '--interactive', '-i',
    is_flag=True,
    help='Start interactive mode'
)
@click.option(
    '--context', '-c',
    type=str,
    help='Provide context for the query (e.g., "glossary", "assets")'
)
@click.option(
    '--format', '-f',
    type=click.Choice(['text', 'json', 'markdown'], case_sensitive=False),
    default='text',
    help='Output format'
)
@click.option(
    '--no-citations',
    is_flag=True,
    help='Hide source citations'
)
@click.option(
    '--no-color',
    is_flag=True,
    help='Disable colored output'
)
@click.option(
    '--verbose', '-v',
    is_flag=True,
    help='Show detailed information'
)
@click.option(
    '--track/--no-track',
    default=True,
    help='Enable/disable MLflow tracking'
)
@click.option(
    '--feedback/--no-feedback',
    default=True,
    help='Enable/disable user feedback collection'
)
@click.option(
    '--debug', '-d',
    is_flag=True,
    help='Show debug/trace messages (loguru INFO level)'
)
@click.option(
    '--agent', '-a',
    is_flag=True,
    help='Use conversational agent mode (with conversation history)'
)
@click.version_option(version='0.1.0', prog_name='egeria-advisor')
def cli(
    query: Optional[str],
    interactive: bool,
    context: Optional[str],
    format: str,
    no_citations: bool,
    no_color: bool,
    verbose: bool,
    track: bool,
    feedback: bool,
    debug: bool,
    agent: bool
):
    """
    Egeria Advisor - AI-powered assistance for pyegeria
    
    Ask questions about Egeria concepts, get code examples, and receive
    guidance on using the pyegeria library.
    
    Examples:
    
        \b
        # Ask a direct question
        egeria-advisor "How do I create a glossary?"
        
        \b
        # Start interactive mode
        egeria-advisor --interactive
        
        \b
        # Get JSON output
        egeria-advisor "What is a collection?" --format=json
        
        \b
        # Provide context
        egeria-advisor "Show me examples" --context=glossary
    """
    # Configure logging level based on debug flag
    if not debug:
        # Disable all loguru logs when not in debug mode
        logger.remove()  # Remove all handlers
        # Redirect stderr to suppress library warnings (like amdgpu.ids)
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, 2)  # Redirect stderr (fd 2) to /dev/null
    
    # Disable colors if requested
    if no_color:
        console.no_color = True
    
    # Build options dict
    options = {
        'context': context,
        'format': format,
        'show_citations': not no_citations,
        'verbose': verbose,
        'track_metrics': track,
        'enable_feedback': feedback,
        'debug': debug,
        'agent_mode': agent,
    }
    
    try:
        # If agent mode is requested, automatically enable interactive
        if agent and not interactive and not query:
            interactive = True
        
        if interactive:
            # Start interactive mode
            start_interactive(options)
        elif query:
            # Handle direct query
            direct_query(query, options)
        else:
            # No query provided, show help
            ctx = click.get_current_context()
            click.echo(ctx.get_help())
            sys.exit(0)
    
    except KeyboardInterrupt:
        console.print("\n[yellow]Interrupted by user[/yellow]")
        sys.exit(0)
    except SystemExit:
        # Re-raise SystemExit to allow normal exit
        raise
    except Exception as e:
        if verbose:
            console.print_exception()
        else:
            console.print(f"[red]✗ Error:[/red] {e}")
            console.print("[dim]Use --verbose for more details[/dim]")
        sys.exit(1)


def direct_query(query: str, options: dict):
    """
    Handle a single direct query and exit.
    
    Parameters
    ----------
    query : str
        The user's query
    options : dict
        CLI options
    """
    verbose = options.get('verbose', False)
    
    # Show welcome message
    if verbose:
        console.print(Panel(
            "[bold cyan]Egeria Advisor[/bold cyan]\n"
            "AI-powered assistance for pyegeria",
            border_style="cyan"
        ))
        console.print()
    
    # Initialize RAG system
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            progress.add_task("Initializing advisor...", total=None)
            rag = get_rag_system()
    except Exception as e:
        console.print(f"[red]✗ Failed to initialize advisor:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)
    
    # Check system health
    if verbose:
        health = rag.health_check()
        if not all(health.values()):
            console.print("[yellow]⚠ Warning: Some services are not healthy[/yellow]")
            for service, status in health.items():
                icon = "✓" if status else "✗"
                color = "green" if status else "red"
                console.print(f"  [{color}]{icon}[/{color}] {service}")
            console.print()
    
    # Execute query
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            progress.add_task("Processing query...", total=None)
            
            result = rag.query(
                user_query=query,
                include_context=True,
                track_metrics=options.get('track_metrics', True)
            )
    except Exception as e:
        console.print(f"[red]✗ Query failed:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)
    
    # Format and display response
    formatter = ResponseFormatter(
        format_type=options.get('format', 'text'),
        show_citations=options.get('show_citations', True),
        verbose=verbose
    )
    
    formatter.display(result, console)
    # MLflow >=2.10 spawns non-daemon worker threads that block Python shutdown.
    # All output is flushed by Rich; force-exit now so the shell prompt returns immediately.
    sys.stdout.flush()
    os._exit(0)


def start_interactive(options: dict):
    """
    Start interactive REPL mode.
    
    Parameters
    ----------
    options : dict
        CLI options
    """
    verbose = options.get('verbose', False)
    agent_mode = options.get('agent_mode', False)
    
    # Use agent mode if requested
    if agent_mode:
        # Show welcome banner for agent mode
        console.print(Panel(
            "[bold cyan]Egeria Advisor - Agent Mode[/bold cyan]\n\n"
            "Conversational AI assistant with memory and context awareness.\n\n"
            "[dim]Commands:[/dim]\n"
            "  [cyan]/help[/cyan]     - Show all commands\n"
            "  [cyan]/tools[/cyan]    - List MCP tools\n"
            "  [cyan]/execute[/cyan]  - Execute MCP tool (alias: /e)\n"
            "  [cyan]/clear[/cyan]    - Clear conversation history\n"
            "  [cyan]/history[/cyan]  - Show conversation history\n"
            "  [cyan]/stats[/cyan]    - Show agent statistics\n"
            "  [cyan]/exit[/cyan]     - Exit (or Ctrl+D)\n\n"
            "[dim]Type your question or /help for more info[/dim]",
            border_style="cyan"
        ))
        console.print()
        
        # Start agent session
        session = AgentInteractiveSession(options, console)
        session.run()
        return
    
    # Standard RAG mode
    # Show welcome banner
    feedback_status = "enabled" if options.get('enable_feedback', True) else "disabled"
    feedback_commands = ""
    if options.get('enable_feedback', True):
        feedback_commands = (
            "  [cyan]/feedback[/cyan] - Provide feedback on last response\n"
            "  [cyan]/stats[/cyan]    - Show feedback statistics\n"
        )
    
    console.print(Panel(
        "[bold cyan]Egeria Advisor - Interactive Mode[/bold cyan]\n\n"
        "Ask questions about Egeria concepts, get code examples, and receive guidance.\n\n"
        "[dim]Commands:[/dim]\n"
        "  [cyan]/help[/cyan]     - Show help\n"
        "  [cyan]/clear[/cyan]    - Clear conversation context\n"
        "  [cyan]/history[/cyan]  - Show query history\n"
        f"{feedback_commands}"
        "  [cyan]/exit[/cyan]     - Exit (or Ctrl+D)\n\n"
        f"[dim]Feedback collection: {feedback_status}[/dim]\n"
        "[dim]Type your question and press Enter[/dim]",
        border_style="cyan"
    ))
    console.print()
    
    # Initialize RAG system
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True
        ) as progress:
            progress.add_task("Initializing advisor...", total=None)
            rag = get_rag_system()
    except Exception as e:
        console.print(f"[red]✗ Failed to initialize advisor:[/red] {e}")
        if verbose:
            console.print_exception()
        sys.exit(1)
    
    # Check system health
    health = rag.health_check()
    if not all(health.values()):
        console.print("[yellow]⚠ Warning: Some services are not healthy[/yellow]")
        for service, status in health.items():
            icon = "✓" if status else "✗"
            color = "green" if status else "red"
            console.print(f"  [{color}]{icon}[/{color}] {service}")
        console.print()
    else:
        console.print("[green]✓[/green] All systems ready\n")
    
    # Start interactive session
    session = InteractiveSession(rag, options, console)
    session.run()


@click.command("web")
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind host")
@click.option("--port", default=8880, show_default=True, help="Bind port")
@click.option("--reload/--no-reload", default=True, show_default=True,
              help="Auto-reload the server on code changes (dev mode)")
def web_command(host: str, port: int, reload: bool):
    """Launch the browser-based web UI."""
    import uvicorn
    mode = "auto-reload on" if reload else "auto-reload off"
    console.print(f"[cyan]Starting Egeria Advisor web UI at http://{host}:{port} ({mode})[/cyan]")
    uvicorn.run(
        "advisor.web.app:app",
        host=host,
        port=port,
        reload=reload,
        # Watch the advisor package so edits to Python and static assets restart the server.
        reload_dirs=["advisor"] if reload else None,
        log_level="warning",
    )


if __name__ == '__main__':
    cli()