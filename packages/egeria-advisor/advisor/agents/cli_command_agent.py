"""
CLI Command Agent for answering questions about hey_egeria and dr_egeria commands.

This agent specializes in:
- Finding commands by purpose or category
- Explaining command usage and parameters
- Generating usage examples
- Providing command documentation

Enhanced with metadata filtering for precise command searches.
"""

import json
from typing import Dict, List, Any, Optional
from loguru import logger

from advisor.agents.base import BaseAgent
from advisor.data_prep.cli_indexer import CLICommandIndexer
from advisor.llm_client import OllamaClient
from advisor.vector_store import SearchResult
from advisor.metadata_filters import (
    extract_cli_filters,
    build_combined_filter_expr
)


class CLICommandAgent(BaseAgent):
    """Specialized agent for CLI command queries."""
    
    def __init__(
        self,
        llm_client: Optional[OllamaClient] = None,
        indexer: Optional[CLICommandIndexer] = None
    ):
        """
        Initialize CLI command agent.
        
        Args:
            llm_client: LLM client for generating responses
            indexer: CLI command indexer for searching commands
        """
        super().__init__(name="cli_command")
        
        self.llm_client = llm_client or OllamaClient()
        self.indexer = indexer or CLICommandIndexer()
        
        logger.info("Initialized CLI Command Agent")
    
    def can_handle(self, query: str) -> bool:
        """
        Determine if this agent can handle the query.
        
        Args:
            query: User query
            
        Returns:
            True if query is about CLI commands
        """
        # Keywords that indicate CLI command queries
        cli_keywords = [
            'command', 'hey_egeria', 'dr_egeria', 'cli',
            'how do i', 'how to', 'run', 'execute',
            'create glossary', 'list', 'monitor', 'delete',
            'parameter', 'option', 'flag', 'usage'
        ]
        
        query_lower = query.lower()
        return any(keyword in query_lower for keyword in cli_keywords)
    
    def process(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Process a user query (required by BaseAgent).
        
        Args:
            query: User query string
            context: Optional context dictionary
            
        Returns:
            Dictionary with response and metadata
        """
        response_text = self.query(query, context)
        
        return self._format_response(
            response=response_text,
            sources=[],
            confidence=0.9
        )
    
    def query(self, user_query: str, context: Optional[Dict[str, Any]] = None) -> str:
        """
        Process a CLI command query.
        
        Args:
            user_query: User's question
            context: Optional context information
            
        Returns:
            Formatted response with command information
        """
        logger.info(f"CLI Command Agent processing query: {user_query}")
        
        # Classify query type
        query_type = self._classify_query(user_query)
        logger.debug(f"Query type: {query_type}")
        
        # Search for relevant commands
        search_results = self._search_commands(user_query, query_type)
        
        if not search_results:
            return self._generate_no_results_response(user_query)
        
        # Generate response based on query type
        if query_type == "list_commands":
            response = self._generate_list_response(search_results, user_query)
        elif query_type == "command_usage":
            response = self._generate_usage_response(search_results, user_query)
        elif query_type == "parameter_info":
            response = self._generate_parameter_response(search_results, user_query)
        else:  # general
            response = self._generate_general_response(search_results, user_query)

        return response

    def handle(self, query: str, perspective: Optional[str] = None) -> Dict[str, Any]:
        """
        Web-facing entry point, matching the handle(query, perspective=None) -> dict
        convention used by every other agent dispatched from advisor/rag_system.py
        (ExamplesAgent, DocAgent, etc.). perspective is currently unused here — CLI
        command answers don't vary by role — accepted for interface consistency.
        """
        from advisor.agents.examples_agent import _make_result
        response_text = self.query(query)
        return _make_result(query, response_text, "cli_command")

    def _classify_query(self, query: str) -> str:
        """
        Classify the type of CLI query.
        
        Args:
            query: User query
            
        Returns:
            Query type: list_commands, command_usage, parameter_info, or general
        """
        query_lower = query.lower()
        
        # List commands
        if any(phrase in query_lower for phrase in [
            'what commands', 'list commands', 'show commands',
            'available commands', 'all commands'
        ]):
            return "list_commands"
        
        # Command usage
        if any(phrase in query_lower for phrase in [
            'how do i', 'how to', 'how can i',
            'usage', 'example', 'run'
        ]):
            return "command_usage"
        
        # Parameter information
        if any(phrase in query_lower for phrase in [
            'parameter', 'option', 'flag', 'argument',
            'what does', 'required'
        ]):
            return "parameter_info"
        
        return "general"
    
    def _search_commands(
        self,
        query: str,
        query_type: str,
        top_k: int = 5,
        use_metadata_filters: bool = False  # Disabled until collection has scalar fields
    ) -> List[SearchResult]:
        """
        Search for relevant commands with optional metadata filtering.
        
        Args:
            query: Search query
            query_type: Type of query
            top_k: Number of results to return
            use_metadata_filters: Whether to extract and apply metadata filters
            
        Returns:
            List of search results
        """
        try:
            # Adjust top_k based on query type
            if query_type == "list_commands":
                top_k = 10  # Show more commands for list queries
            
            # Extract metadata filters from query if enabled
            filter_expr = None
            if use_metadata_filters:
                filters = extract_cli_filters(query)
                if filters:
                    filter_expr = build_combined_filter_expr(filters)
                    logger.info(f"Applying CLI metadata filters: {filter_expr}")
            
            results = self.indexer.search_commands(
                query=query,
                top_k=top_k,
                filter_expr=filter_expr
            )
            
            logger.debug(f"Found {len(results)} matching commands")
            if filter_expr:
                logger.debug(f"  (filtered by: {filter_expr})")
            return results
            
        except Exception as e:
            logger.error(f"Error searching commands: {e}")
            return []
    
    def _generate_list_response(
        self,
        results: List[SearchResult],
        query: str
    ) -> str:
        """Generate response for list commands queries."""
        response_parts = ["# Available Commands\n"]
        
        # Group by category
        by_category: Dict[str, List[SearchResult]] = {}
        for result in results:
            category = result.metadata.get('category', 'other')
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(result)
        
        # Format by category
        for category, cmds in sorted(by_category.items()):
            response_parts.append(f"\n## {category.upper()} Commands")
            for cmd in cmds:
                cmd_name = cmd.metadata.get('command_name', 'unknown')
                description = cmd.metadata.get('description', 'No description')
                response_parts.append(f"- **{cmd_name}**: {description}")
        
        return "\n".join(response_parts)
    
    def _generate_usage_response(
        self,
        results: List[SearchResult],
        query: str
    ) -> str:
        """Generate response for command usage queries."""
        if not results:
            return "No matching commands found."
        
        # Use the top result
        top_result = results[0]
        cmd_data = self._extract_command_data(top_result)
        
        if not cmd_data:
            return "Command information not available."
        
        response_parts = [
            f"# {cmd_data['command_name']}\n",
            f"**Type:** {cmd_data.get('type', 'unknown')}",
            f"**Category:** {cmd_data.get('category', 'unknown')}\n"
        ]
        
        # Add description
        description = cmd_data.get('description', '')
        if description:
            response_parts.append(f"## Description\n{description}\n")
        
        # Add note about multiple invocation methods
        response_parts.append("## CLI Command Format")
        response_parts.append("*This shows the CLI/hey_egeria command format. This operation may also be available via:*")
        response_parts.append("- Java Client API")
        response_parts.append("- REST API (HTTP)")
        response_parts.append("- PyEgeria Python API")
        response_parts.append("- Dr. Egeria Markdown\n")
        response_parts.append("*Ask specifically about these formats if needed (e.g., 'How do I create a glossary using PyEgeria?')*\n")
        
        # Add usage example
        response_parts.append("## Usage")
        usage_example = self._generate_usage_example(cmd_data)
        response_parts.append(f"```bash\n{usage_example}\n```\n")
        
        # Add parameters
        parameters = cmd_data.get('parameters', [])
        if parameters:
            response_parts.append("## Parameters")
            
            # Required parameters
            required = [p for p in parameters if p.get('required')]
            if required:
                response_parts.append("\n### Required:")
                for param in required:
                    param_line = f"- **{param['name']}** ({param.get('type', 'str')})"
                    if param.get('help'):
                        param_line += f": {param['help']}"
                    response_parts.append(param_line)
            
            # Optional parameters
            optional = [p for p in parameters if not p.get('required')]
            if optional:
                response_parts.append("\n### Optional:")
                for param in optional[:5]:  # Show first 5 optional
                    param_line = f"- **{param['name']}** ({param.get('type', 'str')})"
                    if param.get('default') is not None:
                        param_line += f" [default: {param['default']}]"
                    if param.get('help'):
                        param_line += f": {param['help']}"
                    response_parts.append(param_line)
                
                if len(optional) > 5:
                    response_parts.append(f"\n*...and {len(optional) - 5} more optional parameters*")
        
        # Add related commands (filter out duplicates and the main command)
        if len(results) > 1:
            response_parts.append("\n## Related Commands")
            seen_commands = {cmd_data['command_name']}
            related_count = 0
            
            for result in results[1:]:  # Skip first (main command)
                cmd_name = result.metadata.get('command_name', 'unknown')
                
                # Skip if we've already seen this command
                if cmd_name in seen_commands:
                    continue
                
                seen_commands.add(cmd_name)
                description = result.metadata.get('description', '')
                response_parts.append(f"- **{cmd_name}**: {description}")
                
                related_count += 1
                if related_count >= 3:  # Show max 3 related
                    break
        
        return "\n".join(response_parts)
    
    def _generate_parameter_response(
        self,
        results: List[SearchResult],
        query: str
    ) -> str:
        """Generate response for parameter information queries."""
        if not results:
            return "No matching commands found."
        
        top_result = results[0]
        cmd_data = self._extract_command_data(top_result)
        
        if not cmd_data:
            return "Command information not available."
        
        response_parts = [
            f"# Parameters for {cmd_data['command_name']}\n"
        ]
        
        parameters = cmd_data.get('parameters', [])
        if not parameters:
            return f"No parameters found for {cmd_data['command_name']}"
        
        # Group parameters
        required = [p for p in parameters if p.get('required')]
        optional = [p for p in parameters if not p.get('required')]
        
        if required:
            response_parts.append("## Required Parameters\n")
            for param in required:
                response_parts.append(self._format_parameter(param))
        
        if optional:
            response_parts.append("\n## Optional Parameters\n")
            for param in optional:
                response_parts.append(self._format_parameter(param))
        
        return "\n".join(response_parts)
    
    def _generate_general_response(
        self,
        results: List[SearchResult],
        query: str
    ) -> str:
        """Generate general response using LLM."""
        if not results:
            return "No matching commands found."
        
        # Prepare context from search results
        context_parts = []
        for i, result in enumerate(results[:3], 1):
            cmd_data = self._extract_command_data(result)
            if cmd_data:
                context_parts.append(f"Command {i}: {cmd_data['command_name']}")
                context_parts.append(f"Description: {cmd_data.get('description', 'N/A')}")
                context_parts.append(f"Type: {cmd_data.get('type', 'N/A')}")
                context_parts.append(f"Category: {cmd_data.get('category', 'N/A')}")

                # Include the actual flag names/required-status, not just a count —
                # without this the LLM has no real syntax to draw from and guesses
                # (confirmed live: produced a fabricated positional arg when only a
                # parameter count was given).
                params = cmd_data.get('parameters', [])
                if params:
                    param_lines = []
                    for p in params:
                        name = p.get('name', '')
                        req = 'required' if p.get('required') else 'optional'
                        default = p.get('default')
                        default_part = f", default={default!r}" if default is not None else ""
                        param_lines.append(f"  {name} ({req}{default_part}): {p.get('help', '')}")
                    context_parts.append(f"Parameters ({len(params)}):")
                    context_parts.extend(param_lines)
                context_parts.append("")

        context = "\n".join(context_parts)

        # Generate response using LLM
        prompt = f"""You are a helpful assistant for Egeria CLI commands.

STRICT: Use ONLY the command name and parameter names/flags listed in "Available Commands"
below — do not invent flags, positional arguments, or syntax that doesn't appear there. If
the context doesn't include enough detail to show a full invocation, say so rather than
guessing.

User Question: {query}

Available Commands:
{context}

Provide a clear, concise answer to the user's question. Include:
1. Which command(s) to use
2. Brief explanation of what they do
3. Basic usage example if relevant

Keep the response focused and practical."""
        
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                max_tokens=500,
                temperature=0.3
            )
            return response
        except Exception as e:
            logger.error(f"LLM generation failed: {e}")
            # Fallback to usage response
            return self._generate_usage_response(results, query)
    
    def _generate_no_results_response(self, query: str) -> str:
        """Generate response when no commands are found."""
        return f"""# No Matching Commands Found

I couldn't find any commands matching your query: "{query}"

**Suggestions:**
- Try using different keywords
- Check the command name spelling
- Use `list commands` to see all available commands
- Try searching by category (cat, ops, tech, my)

**Example queries:**
- "How do I create a glossary?"
- "What monitoring commands are available?"
- "Show me all catalog commands"
"""
    
    def _extract_command_data(self, result: SearchResult) -> Optional[Dict[str, Any]]:
        """Extract command data from search result metadata."""
        try:
            command_data_json = result.metadata.get('command_data')
            if command_data_json:
                return json.loads(command_data_json)
            return None
        except Exception as e:
            logger.error(f"Error extracting command data: {e}")
            return None
    
    def _generate_usage_example(self, cmd_data: Dict[str, Any]) -> str:
        """Generate a usage example for a command."""
        cmd_name = cmd_data['command_name']
        cmd_type = cmd_data.get('type', 'unknown')
        category = cmd_data.get('category', '')
        
        if cmd_type == 'dr_egeria':
            # dr_egeria markdown format
            usage = cmd_data.get('usage', f'# {cmd_name}\n...\n---')
            return f"# In markdown file:\n{usage}\n\n# Process with:\ndr_egeria_md --input-file my_doc.md"
        
        # hey_egeria command format - show both invocation methods
        parts = [cmd_name]
        
        # Add required parameters
        parameters = cmd_data.get('parameters', [])
        required = [p for p in parameters if p.get('required')]
        
        for param in required:
            param_name = param['name']
            param_type = param.get('type', 'str')
            
            if param_type == 'bool':
                parts.append(param_name)
            else:
                example_value = self._get_example_value(param)
                parts.append(f'{param_name} "{example_value}"')
        
        # Add common optional parameters
        common_opts = ['--server', '--url', '--userid']
        optional = [p for p in parameters if not p.get('required')]
        for param in optional:
            if param['name'] in common_opts:
                parts.append(f"{param['name']} <value>")
        
        # Generate both invocation methods
        direct_usage = " ".join(parts)
        
        # Add hey_egeria prefix if category exists
        if category:
            hey_egeria_usage = f"hey_egeria {category} {direct_usage}"
            return f"# Direct invocation:\n{direct_usage}\n\n# Or via hey_egeria:\n{hey_egeria_usage}"
        
        return direct_usage
    
    def _get_example_value(self, param: Dict[str, Any]) -> str:
        """Get an example value for a parameter."""
        param_name = param['name'].lower()
        
        # Common examples
        if 'name' in param_name:
            return "MyName"
        elif 'description' in param_name:
            return "A description"
        elif 'url' in param_name:
            return "https://localhost:9443"
        elif 'server' in param_name:
            return "view-server"
        elif 'user' in param_name:
            return "erinoverview"
        
        return "value"
    
    def _format_parameter(self, param: Dict[str, Any]) -> str:
        """Format a parameter for display."""
        parts = [f"**{param['name']}**"]
        
        # Type
        param_type = param.get('type', 'str')
        parts.append(f"({param_type})")
        
        # Default
        if param.get('default') is not None:
            parts.append(f"[default: {param['default']}]")
        
        # Required
        if param.get('required'):
            parts.append("[REQUIRED]")
        
        # Help text
        if param.get('help'):
            parts.append(f"\n  {param['help']}")

        return " ".join(parts) + "\n"


_cli_command_agent: Optional["CLICommandAgent"] = None


def get_cli_command_agent() -> "CLICommandAgent":
    global _cli_command_agent
    if _cli_command_agent is None:
        _cli_command_agent = CLICommandAgent()
    return _cli_command_agent