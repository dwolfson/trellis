"""
Agent Interactive Session for Egeria Advisor

This module provides an interactive session using the ConversationAgent.
"""

import sys
import json
import asyncio
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.completion import WordCompleter
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.markdown import Markdown
from rich.table import Table
from rich.prompt import Prompt, Confirm

from advisor.agents.conversation_agent import create_agent
from advisor.mcp_agent import initialize_mcp_agent, shutdown_mcp_agent, get_mcp_agent
from advisor.mcp_client import MCPTool
from advisor.feedback_collector import get_feedback_collector


class AgentInteractiveSession:
    """Interactive REPL session using ConversationAgent."""
    
    # Special commands
    COMMANDS = {
        '/help': 'Show help message',
        '/clear': 'Clear conversation history',
        '/clear-query-cache': 'Clear query response cache',
        '/cqc': 'Clear query response cache (alias)',
        '/history': 'Show conversation history',
        '/stats': 'Show agent statistics',
        '/feedback': 'Provide feedback on last response',
        '/fstats': 'Show feedback statistics',
        '/exit': 'Exit interactive mode',
        '/quit': 'Exit interactive mode',
        '/verbose': 'Toggle verbose mode',
        '/citations': 'Toggle citation display',
        '/tools': 'List available MCP tools',
        '/execute': 'Execute an MCP tool',
        '/exec': 'Execute an MCP tool (alias)',
        '/e': 'Execute an MCP tool (short alias)',
        '/metrics': 'Show MCP tool metrics',
        '/clear-cache': 'Clear MCP tool cache',
        '/cc': 'Clear MCP tool cache (alias)',
    }
    
    def __init__(self, options: Dict[str, Any], console: Console):
        """
        Initialize agent interactive session.
        
        Parameters
        ----------
        options : dict
            CLI options
        console : Console
            Rich console for output
        """
        self.options = options
        self.console = console
        
        # Session state
        self.running = True
        self.last_query: Optional[str] = None
        self.last_response: Optional[Dict[str, Any]] = None
        self.last_agent_type: Optional[str] = None  # Track which agent handled the last query
        
        # Options
        self.verbose = options.get('verbose', False)
        self.show_citations = options.get('show_citations', True)
        self.mcp_enabled = options.get('enable_mcp', True)
        self.enable_feedback = options.get('enable_feedback', True)
        
        # Feedback system
        self.feedback_collector = get_feedback_collector() if self.enable_feedback else None
        self.session_id = str(uuid.uuid4())[:8]
        
        # Initialize agents
        self.agent = None
        self.mcp_agent = None
        
        # Set up prompt session
        history_file = Path.home() / '.egeria_advisor_agent_history'
        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)),
            auto_suggest=AutoSuggestFromHistory(),
            completer=self._create_completer(),
        )
    
    def _create_completer(self) -> WordCompleter:
        """Create command completer."""
        words = list(self.COMMANDS.keys()) + [
            'glossary', 'collection', 'asset', 'term', 'category',
            'create', 'find', 'update', 'delete', 'search',
            'how', 'what', 'why', 'when', 'where', 'show', 'example'
        ]
        return WordCompleter(words, ignore_case=True)
    
    def run(self):
        """Run the interactive REPL loop."""
        # Initialize conversation agent
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
                transient=True
            ) as progress:
                progress.add_task("Initializing agent...", total=None)
                # MLflow tracking now works with LRU cache (fixed in conversation_agent.py)
                # Increased rag_top_k from 5 to 10 for better code example retrieval
                # See docs/design/PERFORMANCE_AND_QUALITY_ANALYSIS.md for details
                enable_mlflow = self.options.get('track', True)  # Respect CLI --track flag
                self.agent = create_agent(max_history=10, cache_size=100, rag_top_k=10, enable_mlflow=enable_mlflow)
        except Exception as e:
            self.console.print(f"[red]✗ Failed to initialize agent:[/red] {e}")
            if self.verbose:
                self.console.print_exception()
            sys.exit(1)
        
        self.console.print("[green]✓[/green] Agent ready")
        
        # Initialize MCP agent (optional)
        if self.mcp_enabled:
            try:
                with Progress(
                    SpinnerColumn(),
                    TextColumn("[progress.description]{task.description}"),
                    console=self.console,
                    transient=True
                ) as progress:
                    progress.add_task("Initializing MCP tools...", total=None)
                    # Run async initialization in sync context
                    asyncio.run(self._init_mcp_agent())
                
                if self.mcp_agent:
                    tool_count = len(self.mcp_agent.get_available_tools())
                    self.console.print(f"[green]✓[/green] MCP tools ready ({tool_count} tools)")
            except Exception as e:
                self.console.print(f"[yellow]⚠ MCP tools unavailable:[/yellow] {e}")
                if self.verbose:
                    self.console.print_exception()
                self.mcp_agent = None
        
        self.console.print()  # Add spacing
        
        try:
            while self.running:
                try:
                    # Get user input
                    user_input = self.prompt_session.prompt('agent> ')
                    
                    # Skip empty input
                    if not user_input.strip():
                        continue
                    
                    # Handle commands
                    if user_input.startswith('/'):
                        self._handle_command(user_input.strip())
                    else:
                        # Handle query
                        self._handle_query(user_input.strip())
                    
                    self.console.print()  # Add spacing
                
                except KeyboardInterrupt:
                    self.console.print("\n[dim]Use /exit or Ctrl+D to quit[/dim]")
                    continue
                except EOFError:
                    # Ctrl+D pressed
                    self.console.print("\n[cyan]Goodbye![/cyan]")
                    break
        
        finally:
            self._cleanup()
    
    def _handle_command(self, command: str):
        """
        Handle special commands.
        
        Parameters
        ----------
        command : str
            Command string starting with /
        """
        cmd = command.lower().split()[0]
        
        if cmd in ['/exit', '/quit']:
            self.console.print("[cyan]Goodbye![/cyan]")
            self.running = False
        
        elif cmd == '/help':
            self._show_help()
        
        elif cmd == '/clear':
            self.agent.clear_history()
            self.console.print("[green]✓[/green] Conversation history cleared")
        
        elif cmd in ['/clear-query-cache', '/cqc']:
            # Clear the LRU cache on the agent's run method
            if hasattr(self.agent, '_cached_run'):
                self.agent._cached_run.cache_clear()
                self.console.print("[green]✓[/green] Query response cache cleared")
            else:
                self.console.print("[yellow]⚠[/yellow] No query cache to clear")
        
        elif cmd == '/history':
            self._show_history()
        
        elif cmd == '/stats':
            self._show_stats()
        
        elif cmd == '/verbose':
            self.verbose = not self.verbose
            status = "enabled" if self.verbose else "disabled"
            self.console.print(f"[green]✓[/green] Verbose mode {status}")
        
        elif cmd == '/citations':
            self.show_citations = not self.show_citations
            status = "enabled" if self.show_citations else "disabled"
            self.console.print(f"[green]✓[/green] Citations {status}")
        
        # Feedback commands
        elif cmd == '/feedback':
            self._handle_feedback_command()
        
        elif cmd == '/fstats':
            self._show_feedback_stats()
        
        # MCP tool commands
        elif cmd == '/tools':
            self._show_tools()
        
        elif cmd in ['/execute', '/exec', '/e']:
            # Run async command in sync context
            asyncio.run(self._execute_tool(command))
        
        elif cmd == '/metrics':
            self._show_mcp_metrics()
        
        elif cmd in ['/clear-cache', '/cc']:
            if self.mcp_agent:
                self.mcp_agent.clear_cache()
                self.console.print("[green]✓[/green] MCP tool cache cleared")
            else:
                self.console.print("[yellow]MCP tools not available[/yellow]")
        
        else:
            self.console.print(f"[yellow]Unknown command:[/yellow] {cmd}")
            self.console.print("[dim]Type /help for available commands[/dim]")
    
    def _handle_query(self, query: str):
        """
        Handle user query.
        
        Parameters
        ----------
        query : str
            User's query
        """
        # Check if this is a follow-up selection (e.g., "1", "2", etc.)
        is_follow_up = False
        follow_up_query = self._check_follow_up_selection(query)
        if follow_up_query:
            query = follow_up_query
            is_follow_up = True
            self.console.print(f"[dim]→ Interpreting as: {query}[/dim]\n")
        
        # For follow-up queries from PyEgeria, add PyEgeria context to maintain routing
        if is_follow_up and self.last_agent_type == "pyegeria":
            # Extract the topic from the original query
            topic = self._extract_topic_from_query(self.last_query) if self.last_query else ""
            if topic:
                # Add PyEgeria-specific context to ensure it routes back to PyEgeria agent
                query = f"{query} for PyEgeria {topic}"
                self.console.print(f"[dim]→ Maintaining PyEgeria context: {query}[/dim]\n")
        
        # Show processing indicator
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=self.console,
            transient=True
        ) as progress:
            progress.add_task("Processing...", total=None)
            
            try:
                # Execute query with agent
                result = self.agent.run(query, use_rag=True)
                
                # Track which agent type handled this query
                self.last_agent_type = result.get("agent_type", "unknown")
                
                # Store for feedback
                self.last_query = query
                self.last_response = result
                
                # Display response
                self.console.print(Panel(
                    Markdown(result["content"]),
                    title="[bold cyan]Agent Response[/bold cyan]",
                    border_style="cyan"
                ))
                
                # Show sources if enabled
                if self.show_citations and result.get("sources"):
                    self.console.print("\n[bold]Sources:[/bold]")
                    for i, source in enumerate(result["sources"][:5], 1):
                        # Handle both string sources (from PyEgeria agent) and dict sources (from RAG)
                        if isinstance(source, str):
                            self.console.print(f"  [cyan]{i}.[/cyan] {source}")
                        elif isinstance(source, dict):
                            file_path = source.get("file_path", "Unknown")
                            collection = source.get("collection", "Unknown")
                            score = source.get("score", 0.0)
                            self.console.print(
                                f"  [cyan]{i}.[/cyan] {file_path} "
                                f"[dim]({collection}, score: {score:.3f})[/dim]"
                            )
                        else:
                            self.console.print(f"  [cyan]{i}.[/cyan] {source}")
                
                # Show follow-up options if available
                follow_up_options = result.get("follow_up_options", [])
                if follow_up_options:
                    self.console.print("\n[bold cyan]What would you like to know more about?[/bold cyan]")
                    for i, option in enumerate(follow_up_options, 1):
                        self.console.print(f"  [cyan]{i}.[/cyan] {option}")
                    self.console.print("\n[dim]Type the number or describe what you'd like![/dim]")
                
                # Show metadata if verbose
                if self.verbose:
                    self.console.print(f"\n[dim]RAG used: {result.get('rag_used', False)}, "
                                     f"Cache hit: {result.get('cache_hit', False)}[/dim]")
            
            except Exception as e:
                self.console.print(f"[red]✗ Error:[/red] {e}")
                if self.verbose:
                    self.console.print_exception()
    
    def _check_follow_up_selection(self, query: str) -> Optional[str]:
        """
        Check if query is a follow-up selection (e.g., "1", "2") and convert to full query.
        
        Parameters
        ----------
        query : str
            User's input
            
        Returns
        -------
        Optional[str]
            Converted query if it's a follow-up selection, None otherwise
        """
        # Check if last response had follow-up options
        if not self.last_response or not self.last_response.get("follow_up_options"):
            return None
        
        query_stripped = query.strip()
        
        # Check if it's a number selection
        if query_stripped.isdigit():
            selection = int(query_stripped)
            follow_up_options = self.last_response.get("follow_up_options", [])
            
            if 1 <= selection <= len(follow_up_options):
                selected_option = follow_up_options[selection - 1]
                
                # Convert option to query based on last query context
                if self.last_query:
                    # Extract the topic from last query
                    topic = self._extract_topic_from_query(self.last_query)
                    
                    # Map option to query
                    return self._convert_option_to_query(selected_option, topic)
        
        return None
    
    def _extract_topic_from_query(self, query: str) -> str:
        """Extract the main topic from a query."""
        # Simple extraction - look for class names, method names, etc.
        words = query.split()
        # Common patterns: "What does X do?", "Tell me about X", "Show me X"
        for i, word in enumerate(words):
            if word.lower() in ['does', 'is', 'about', 'me'] and i + 1 < len(words):
                return words[i + 1].strip('?.,')
        
        # Fallback: return last significant word
        significant_words = [w for w in words if len(w) > 3 and w[0].isupper()]
        return significant_words[-1] if significant_words else words[-1].strip('?.,')
    
    def _convert_option_to_query(self, option: str, topic: str) -> str:
        """
        Convert a follow-up option to a full query.
        
        Parameters
        ----------
        option : str
            The follow-up option text
        topic : str
            The topic from the original query
            
        Returns
        -------
        str
            Full query string
        """
        option_lower = option.lower()
        
        # Map common option patterns to queries
        if "code example" in option_lower or "example" in option_lower:
            return f"Show me a code example for {topic}"
        elif "documentation" in option_lower or "docs" in option_lower:
            return f"Show me the documentation for {topic}"
        elif "related" in option_lower:
            return f"What are related classes to {topic}?"
        elif "parameters" in option_lower or "options" in option_lower:
            return f"What are the parameters for {topic}?"
        elif "commands" in option_lower:
            return f"Show me related commands for {topic}"
        elif "implementation" in option_lower or "how" in option_lower:
            return f"How is {topic} implemented?"
        elif "async" in option_lower or "sync" in option_lower:
            return f"Explain async vs sync usage for {topic}"
        else:
            # Generic fallback
            return f"{option} for {topic}"
    
    def _show_help(self):
        """Show help message."""
        help_text = "[bold cyan]Available Commands:[/bold cyan]\n\n"
        
        help_text += "[bold]Conversation:[/bold]\n"
        help_text += "  [cyan]/help[/cyan]        - Show this help\n"
        help_text += "  [cyan]/clear[/cyan]       - Clear conversation history\n"
        help_text += "  [cyan]/history[/cyan]     - Show conversation history\n"
        help_text += "  [cyan]/stats[/cyan]       - Show agent statistics\n"
        help_text += "  [cyan]/verbose[/cyan]     - Toggle verbose mode\n"
        help_text += "  [cyan]/citations[/cyan]   - Toggle citation display\n"
        
        if self.feedback_collector:
            help_text += "\n[bold]Feedback:[/bold]\n"
            help_text += "  [cyan]/feedback[/cyan]    - Provide feedback on last response\n"
            help_text += "  [cyan]/fstats[/cyan]      - Show feedback statistics\n"
        
        # Always show MCP commands with availability indicator
        help_text += "\n[bold]MCP Tools:"
        if self.mcp_agent:
            tool_count = len(self.mcp_agent.get_available_tools())
            help_text += f" [green]({tool_count} tools available)[/green][/bold]\n"
        else:
            help_text += " [yellow](unavailable)[/yellow][/bold]\n"
        
        help_text += "  [cyan]/tools[/cyan]       - List available MCP tools\n"
        help_text += "  [cyan]/execute[/cyan]     - Execute a tool (aliases: /exec, /e)\n"
        help_text += "  [cyan]/metrics[/cyan]     - Show tool execution metrics\n"
        help_text += "  [cyan]/clear-cache[/cyan] - Clear tool result cache (alias: /cc)\n"
        
        help_text += "\n[bold]System:[/bold]\n"
        help_text += "  [cyan]/exit[/cyan]        - Exit (or Ctrl+D)\n"
        
        help_text += "\n[bold cyan]Agent Features:[/bold cyan]\n"
        help_text += "  • Conversational AI with memory\n"
        help_text += "  • RAG-enhanced responses with source citation\n"
        help_text += "  • Response caching for repeated queries\n"
        help_text += "  • Conversation history tracking\n"
        
        if self.mcp_agent:
            help_text += "  • MCP tool execution for reports and commands\n"
        
        help_text += "\n[bold cyan]Usage Examples:[/bold cyan]\n"
        help_text += "  • Ask questions: [dim]'How do I create a glossary?'[/dim]\n"
        help_text += "  • Request code: [dim]'Show me an example of creating a term'[/dim]\n"
        
        if self.mcp_agent:
            help_text += "  • List tools: [dim]/tools[/dim]\n"
            help_text += "  • Execute tool: [dim]/execute list_reports[/dim] or [dim]/e list_reports[/dim]\n"
            help_text += "  • View metrics: [dim]/metrics[/dim]\n"
        else:
            help_text += "  • [dim]MCP tools require config/mcp_servers.json configuration[/dim]\n"
        
        help_text += "\n[dim]Use arrow keys to navigate command history[/dim]\n"
        
        self.console.print(Panel(help_text, border_style="cyan", padding=(1, 2)))
    
    def _show_history(self):
        """Show conversation history."""
        history = self.agent.get_history()
        
        if not history:
            self.console.print("[dim]No conversation history[/dim]")
            return
        
        self.console.print("[bold cyan]Conversation History:[/bold cyan]\n")
        
        for i, entry in enumerate(history, 1):
            query = entry['query']
            num_sources = entry.get('sources', 0)
            
            self.console.print(f"  [cyan]{i}.[/cyan] {query}")
            if self.verbose:
                response_preview = entry['response'][:100] + "..." if len(entry['response']) > 100 else entry['response']
                self.console.print(f"     [dim]{response_preview}[/dim]")
                self.console.print(f"     [dim]({num_sources} sources)[/dim]")
    
    def _show_stats(self):
        """Show agent statistics."""
        stats = self.agent.get_stats()
        
        table = Table(title="Agent Statistics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        
        table.add_row("Conversation Turns", str(stats['conversation_turns']))
        table.add_row("Cache Hits", str(stats['cache_hits']))
        table.add_row("Cache Misses", str(stats['cache_misses']))
        table.add_row("Cache Size", f"{stats['cache_size']}/{stats['cache_max_size']}")
        table.add_row("Cache Hit Rate", f"{stats['cache_hit_rate']:.1%}")
        
        self.console.print(table)
    def _show_tools(self):
        """Show available MCP tools."""
        if not self.mcp_agent:
            self.console.print("[yellow]MCP tools not available[/yellow]")
            return
        
        tools = self.mcp_agent.get_available_tools()
        
        if not tools:
            self.console.print("[dim]No MCP tools available[/dim]")
            return
        
        table = Table(title="Available MCP Tools", show_header=True, header_style="bold cyan")
        table.add_column("Tool", style="cyan")
        table.add_column("Description")
        table.add_column("Server", style="dim")
        
        for tool in tools:
            table.add_row(
                tool.name,
                tool.description or "No description",
                tool.server  # Fixed: use 'server' not 'server_name'
            )
        
        self.console.print(table)
    
    async def _execute_tool(self, command: str):
        """Execute an MCP tool."""
        if not self.mcp_agent:
            self.console.print("[yellow]MCP tools not available[/yellow]")
            return
        
        # Parse command: /execute tool_name [args] or /e tool_name [args]
        parts = command.split(maxsplit=2)
        if len(parts) < 2:
            self.console.print("[yellow]Usage: /execute <tool_name> [report_spec][/yellow]")
            self.console.print("[dim]Use /tools to see available tools[/dim]")
            return
        
        tool_name = parts[1].strip()
        quick_args = parts[2].strip() if len(parts) > 2 else None
        
        # Get tool info
        tool = self.mcp_agent.get_tool(tool_name)
        if not tool:
            self.console.print(f"[red]Tool not found:[/red] {tool_name}")
            self.console.print("[dim]Use /tools to see available tools[/dim]")
            return
        
        # Get parameters - use quick args if provided, otherwise interactive
        try:
            if quick_args:
                # Quick execution with provided argument
                # Assume first parameter is the one being provided
                schema = tool.input_schema
                if schema and 'properties' in schema:
                    first_param = list(schema['properties'].keys())[0]
                    arguments = {first_param: quick_args}
                    self.console.print(f"[dim]Using {first_param}={quick_args}[/dim]")
                else:
                    arguments = {}
            else:
                # Interactive parameter collection
                arguments = self._get_tool_arguments(tool)
        except KeyboardInterrupt:
            self.console.print("\n[yellow]Tool execution cancelled[/yellow]")
            return
        
        # Execute tool
        try:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=self.console,
                transient=True
            ) as progress:
                progress.add_task(f"Executing {tool_name}...", total=None)
                result = await self.mcp_agent.execute_tool(tool_name, arguments)
            
            # Display result
            self._display_tool_result(result)
        
        except Exception as e:
            self.console.print(f"[red]✗ Tool execution failed:[/red] {e}")
            if self.verbose:
                self.console.print_exception()
    
    def _get_tool_arguments(self, tool: MCPTool) -> dict:
        """Get tool arguments from user input."""
        arguments = {}
        schema = tool.input_schema
        
        if not schema or 'properties' not in schema:
            return arguments
        
        properties = schema['properties']
        required = schema.get('required', [])
        
        self.console.print(f"\n[bold]Parameters for {tool.name}:[/bold]")
        
        for param_name, param_info in properties.items():
            param_type = param_info.get('type', 'string')
            description = param_info.get('description', '')
            default = param_info.get('default')
            enum_values = param_info.get('enum')
            
            # Show parameter info
            required_marker = "[red]*[/red]" if param_name in required else ""
            self.console.print(f"\n{required_marker} [cyan]{param_name}[/cyan] ({param_type})")
            
            if description:
                self.console.print(f"  [dim]{description}[/dim]")
            
            if enum_values:
                self.console.print(f"  [dim]Valid values: {', '.join(map(str, enum_values))}[/dim]")
            
            if default is not None:
                self.console.print(f"  [dim]Default: {default}[/dim]")
            
            # Get input
            prompt = f"  Value: "
            value = input(prompt).strip()
            
            # Use default if empty and not required
            if not value:
                if param_name in required:
                    self.console.print(f"[red]Error: {param_name} is required[/red]")
                    return self._get_tool_arguments(tool)  # Retry
                elif default is not None:
                    value = default
                else:
                    continue
            
            # Type conversion
            try:
                if param_type == 'integer':
                    value = int(value)
                elif param_type == 'number':
                    value = float(value)
                elif param_type == 'boolean':
                    value = value.lower() in ('true', 'yes', '1', 'y')
            except ValueError:
                self.console.print(f"[red]Invalid {param_type} value[/red]")
                return self._get_tool_arguments(tool)  # Retry
            
            arguments[param_name] = value
        
        return arguments
    
    def _display_tool_result(self, result):
        """Display tool execution result with pretty printing."""
        self.console.print("\n[bold green]✓ Tool Result:[/bold green]\n")
        
        # Handle MCP content format
        if isinstance(result, list):
            for item in result:
                if isinstance(item, dict):
                    content_type = item.get('type', 'text')
                    
                    if content_type == 'text':
                        text = item.get('text', '')
                        # Try to parse as JSON for pretty printing
                        try:
                            parsed = json.loads(text)
                            self.console.print(json.dumps(parsed, indent=2))
                        except:
                            # Display as-is (could be markdown)
                            self.console.print(text)
                    
                    elif content_type == 'image':
                        self.console.print(f"[dim]Image: {item.get('data', 'N/A')}[/dim]")
                    
                    elif content_type == 'resource':
                        self.console.print(f"[dim]Resource: {item.get('uri', 'N/A')}[/dim]")
        else:
            # Fallback for non-MCP format
            self.console.print(str(result))
    
    def _show_mcp_metrics(self):
        """Show MCP tool metrics."""
        if not self.mcp_agent:
            self.console.print("[yellow]MCP tools not available[/yellow]")
            return
        
        metrics = self.mcp_agent.get_metrics()
        
        table = Table(title="MCP Tool Metrics", show_header=True, header_style="bold cyan")
        table.add_column("Metric", style="cyan")
        table.add_column("Value", justify="right")
        
        table.add_row("Total Calls", str(metrics.get('total_calls', 0)))
        table.add_row("Successful Calls", str(metrics.get('successful_calls', 0)))
        table.add_row("Failed Calls", str(metrics.get('failed_calls', 0)))
        table.add_row("Success Rate", f"{metrics.get('success_rate', 0):.1%}")
        table.add_row("Cache Hits", str(metrics.get('cache_hits', 0)))
        table.add_row("Cache Misses", str(metrics.get('cache_misses', 0)))
        
        avg_time = metrics.get('avg_execution_time', 0)
        if avg_time > 0:
            table.add_row("Avg Execution Time", f"{avg_time:.2f}s")
        
        self.console.print(table)
    
    def _handle_feedback_command(self):
        """Handle /feedback command to provide feedback on last response."""
        if not self.feedback_collector:
            self.console.print("[yellow]Feedback collection is disabled[/yellow]")
            return
        
        if not self.last_response or not self.last_query:
            self.console.print("[yellow]No previous response to provide feedback on[/yellow]")
            return
        
        # Show last query and response summary
        self.console.print("\n[bold cyan]Last Query:[/bold cyan]")
        self.console.print(f"  {self.last_query}")
        self.console.print(f"\n[bold cyan]Response:[/bold cyan]")
        response_preview = self.last_response.get('content', '')[:200]
        self.console.print(f"  {response_preview}...")
        self.console.print()
        
        # Ask for 5-star rating
        self.console.print("[cyan]How would you rate this answer?[/cyan]")
        self.console.print("  ⭐⭐⭐⭐⭐ [green]5[/green] - Excellent")
        self.console.print("  ⭐⭐⭐⭐   [green]4[/green] - Good")
        self.console.print("  ⭐⭐⭐     [yellow]3[/yellow] - Okay")
        self.console.print("  ⭐⭐       [yellow]2[/yellow] - Poor")
        self.console.print("  ⭐         [red]1[/red] - Very Poor")
        
        star_rating = int(Prompt.ask("Your rating", choices=["1", "2", "3", "4", "5"], default="4"))
        
        # Map to rating category
        if star_rating >= 4:
            rating = "positive"
        elif star_rating == 3:
            rating = "neutral"
        else:
            rating = "negative"
        
        # Ask for feedback category
        self.console.print("\n[cyan]What aspect would you like to rate?[/cyan]")
        self.console.print("  [cyan]1[/cyan] - Accuracy (was the information correct?)")
        self.console.print("  [cyan]2[/cyan] - Completeness (was the answer complete?)")
        self.console.print("  [cyan]3[/cyan] - Clarity (was it easy to understand?)")
        self.console.print("  [cyan]4[/cyan] - Relevance (did it answer your question?)")
        self.console.print("  [cyan]5[/cyan] - Overall")
        
        category_choice = Prompt.ask("Choose", choices=["1", "2", "3", "4", "5"], default="5")
        category_map = {
            "1": "accuracy",
            "2": "completeness",
            "3": "clarity",
            "4": "relevance",
            "5": "overall"
        }
        category = category_map[category_choice]
        
        # Collect additional feedback for low ratings
        feedback_text = None
        user_comment = None
        
        if star_rating <= 3:
            self.console.print("\n[yellow]What could be improved?[/yellow]")
            self.console.print("  [cyan]1[/cyan] - Wrong or inaccurate information")
            self.console.print("  [cyan]2[/cyan] - Incomplete or missing information")
            self.console.print("  [cyan]3[/cyan] - Unclear or confusing explanation")
            self.console.print("  [cyan]4[/cyan] - Not relevant to my question")
            self.console.print("  [cyan]5[/cyan] - Other")
            
            problem_choice = Prompt.ask("Choose", choices=["1", "2", "3", "4", "5"], default="5")
            
            problem_map = {
                "1": "Inaccurate information",
                "2": "Incomplete answer",
                "3": "Unclear explanation",
                "4": "Not relevant",
                "5": "Other issue"
            }
            feedback_text = problem_map[problem_choice]
        
        # Ask for optional comment
        if star_rating <= 4:
            self.console.print("\n[cyan]Any additional comments?[/cyan] [dim](optional, helps us improve)[/dim]")
            comment = Prompt.ask("Comment", default="")
            if comment:
                user_comment = comment
        
        # Record feedback
        try:
            # Extract collections from sources
            collections_searched = []
            if self.last_response.get("sources"):
                collections_searched = list(set(
                    source.get("collection", "unknown") 
                    for source in self.last_response["sources"]
                ))
            
            self.feedback_collector.record_feedback(
                query=self.last_query,
                query_type="agent",
                collections_searched=collections_searched,
                response_length=len(self.last_response.get('content', '')),
                rating=rating,
                feedback_text=feedback_text,
                user_comment=user_comment,
                session_id=self.session_id,
                star_rating=star_rating,
                category=category
            )
            self.console.print(f"[green]✓[/green] Thank you for your {star_rating}-star feedback!")
            if star_rating >= 4:
                self.console.print("[dim]Your positive feedback helps us improve! 🎉[/dim]")
            elif star_rating <= 2:
                self.console.print("[dim]We're sorry the response wasn't helpful. We'll work to improve.[/dim]")
        except Exception as e:
            self.console.print(f"[red]✗[/red] Failed to record feedback: {e}")
    
    def _show_feedback_stats(self):
        """Show feedback statistics."""
        if not self.feedback_collector:
            self.console.print("[yellow]Feedback collection is disabled[/yellow]")
            return
        
        try:
            stats = self.feedback_collector.get_feedback_stats()
            
            if stats['total'] == 0:
                self.console.print("[dim]No feedback recorded yet[/dim]")
                return
            
            # Create statistics table
            table = Table(title="Feedback Statistics", show_header=True, header_style="bold cyan")
            table.add_column("Metric", style="cyan")
            table.add_column("Value", justify="right")
            
            table.add_row("Total Feedback", str(stats['total']))
            table.add_row("Positive", f"[green]{stats['positive']}[/green]")
            table.add_row("Negative", f"[red]{stats['negative']}[/red]")
            table.add_row("Neutral", f"[yellow]{stats.get('neutral', 0)}[/yellow]")
            table.add_row("Satisfaction Rate", f"{stats['satisfaction_rate']:.1%}")
            
            self.console.print()
            self.console.print(table)
            
            # Show by query type if available
            if stats.get('by_query_type'):
                self.console.print("\n[bold cyan]By Query Type:[/bold cyan]")
                for qtype, data in stats['by_query_type'].items():
                    satisfaction = data.get('positive', 0) / data['total'] if data['total'] > 0 else 0
                    self.console.print(f"  {qtype:20} - {data['total']:3} queries ({satisfaction:.1%} positive)")
        
        except Exception as e:
            self.console.print(f"[red]✗[/red] Failed to get feedback stats: {e}")
    
    
    async def _init_mcp_agent(self):
        """Initialize MCP agent asynchronously."""
        try:
            self.mcp_agent = await initialize_mcp_agent()
        except Exception as e:
            if self.verbose:
                self.console.print(f"[dim]MCP initialization error: {e}[/dim]")
            self.mcp_agent = None
    
    def _cleanup(self):
        """Clean up session resources."""
        # Shutdown MCP agent if initialized
        if self.mcp_agent:
            try:
                asyncio.run(shutdown_mcp_agent())
            except Exception as e:
                if self.verbose:
                    self.console.print(f"[yellow]Warning: MCP shutdown error:[/yellow] {e}")