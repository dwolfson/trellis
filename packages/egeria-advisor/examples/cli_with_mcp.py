#!/usr/bin/env python3
"""
Interactive CLI with MCP Tool Support

Example usage:
    python examples/cli_with_mcp.py
    python examples/cli_with_mcp.py --no-tools
    python examples/cli_with_mcp.py --config config/mcp_servers.json
"""

import asyncio
import argparse
import sys
import json
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.mcp_agent import initialize_mcp_agent, shutdown_mcp_agent, MCPError


def pretty_print_result(result):
    """
    Pretty print tool result - handles MCP content format, JSON, and Markdown.
    
    MCP returns content as a list of content items:
    [{"type": "text", "text": "..."}, ...]
    
    Args:
        result: Tool execution result (MCP content array or other format)
    """
    # Handle MCP content array format
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                content_type = item.get("type", "")
                
                if content_type == "text":
                    # Text content - could be JSON, Markdown, or plain text
                    text = item.get("text", "")
                    try:
                        # Try to parse as JSON
                        parsed = json.loads(text)
                        print(json.dumps(parsed, indent=2))
                    except (json.JSONDecodeError, TypeError):
                        # It's markdown or plain text
                        print(text)
                
                elif content_type == "image":
                    # Image content
                    print(f"[Image: {item.get('mimeType', 'unknown')}]")
                    if "data" in item:
                        print(f"  Data length: {len(item['data'])} bytes")
                
                elif content_type == "resource":
                    # Resource reference
                    print(f"[Resource: {item.get('uri', 'unknown')}]")
                    if "text" in item:
                        print(item["text"])
                
                else:
                    # Unknown content type, print as JSON
                    print(json.dumps(item, indent=2))
            else:
                # List item is not a dict
                print(item)
    
    # Handle direct string
    elif isinstance(result, str):
        try:
            parsed = json.loads(result)
            print(json.dumps(parsed, indent=2))
        except (json.JSONDecodeError, TypeError):
            print(result)
    
    # Handle dict or other objects
    elif isinstance(result, dict):
        print(json.dumps(result, indent=2))
    
    else:
        # Other types
        print(result)


def normalize_command(cmd: str) -> str:
    """
    Normalize command to full form, supporting abbreviations.
    
    Args:
        cmd: Command string (may be abbreviated)
        
    Returns:
        Normalized command string
    """
    cmd_lower = cmd.lower()
    
    # Command abbreviations
    abbreviations = {
        'e': 'execute',
        'exec': 'execute',
        't': 'tools',
        'm': 'metrics',
        'c': 'clear-cache',
        'cc': 'clear-cache',
        'h': 'help',
        'q': 'quit',
        'x': 'exit'
    }
    
    return abbreviations.get(cmd_lower, cmd_lower)


async def interactive_mode(enable_tools: bool = True, config_path: str = None):
    """
    Interactive CLI with MCP tool support.
    
    Args:
        enable_tools: Whether to enable MCP tools
        config_path: Path to MCP configuration file
    """
    print("=" * 70)
    print("Egeria Advisor - Interactive Mode with MCP Tools")
    print("=" * 70)
    
    mcp_agent = None
    
    if enable_tools:
        try:
            print("\nInitializing MCP agent...")
            mcp_agent = await initialize_mcp_agent(config_path=config_path)
            
            tools = mcp_agent.get_available_tools()
            if tools:
                print(f"\n✓ MCP agent initialized with {len(tools)} tools:")
                for tool in tools:
                    print(f"  • {tool.name} ({tool.server}): {tool.description}")
            else:
                print("\n⚠ No MCP tools available")
                enable_tools = False
                
        except Exception as e:
            print(f"\n⚠ Failed to initialize MCP agent: {e}")
            print("Continuing without MCP tools...")
            enable_tools = False
    else:
        print("\nMCP tools disabled")
    
    print("\nCommands (abbreviations in parentheses):")
    print("  query <text>     - Ask a question")
    print("  tools (t)        - List available tools")
    print("  execute <tool> (e, exec) - Execute a tool directly")
    print("  metrics (m)      - Show MCP metrics")
    print("  clear-cache (c, cc) - Clear tool result cache")
    print("  help (h)         - Show this help")
    print("  exit/quit (x, q) - Exit the program")
    print()
    
    try:
        while True:
            try:
                user_input = input(">>> ").strip()
                
                if not user_input:
                    continue
                
                # Parse command and arguments
                parts = user_input.split(maxsplit=1)
                command = normalize_command(parts[0]) if parts else ""
                args = parts[1] if len(parts) > 1 else ""
                
                # Handle exit commands
                if command in ["exit", "quit"]:
                    break
                
                # Handle help command
                if command == "help":
                    print("\nCommands (abbreviations in parentheses):")
                    print("  query <text>     - Ask a question")
                    print("  tools (t)        - List available tools")
                    print("  execute <tool> (e, exec) - Execute a tool directly")
                    print("  metrics (m)      - Show MCP metrics")
                    print("  clear-cache (c, cc) - Clear tool result cache")
                    print("  help (h)         - Show this help")
                    print("  exit/quit (x, q) - Exit the program")
                    continue
                
                # Handle tools command
                if command == "tools":
                    if mcp_agent:
                        tools = mcp_agent.get_available_tools()
                        if tools:
                            print(f"\nAvailable tools ({len(tools)}):")
                            for tool in tools:
                                print(f"\n  {tool.name} ({tool.server})")
                                print(f"    {tool.description}")
                                print(f"    Parameters: {tool.input_schema.get('properties', {}).keys()}")
                        else:
                            print("\nNo tools available")
                    else:
                        print("\nMCP tools not enabled")
                    continue
                
                # Handle metrics command
                if command == "metrics":
                    if mcp_agent:
                        metrics = mcp_agent.get_metrics()
                        print("\nMCP Metrics:")
                        print(f"  Tool invocations: {metrics['tool_invocations']}")
                        print(f"  Successes: {metrics['tool_successes']}")
                        print(f"  Failures: {metrics['tool_failures']}")
                        print(f"  Success rate: {metrics['success_rate']:.1%}")
                        print(f"  Avg execution time: {metrics['average_execution_time']:.2f}s")
                        print(f"  Cache hits: {metrics['cache_hits']}")
                        print(f"  Cache misses: {metrics['cache_misses']}")
                    else:
                        print("\nMCP tools not enabled")
                    continue
                
                # Handle clear-cache command
                if command == "clear-cache":
                    if mcp_agent:
                        mcp_agent.clear_cache()
                        print("\n✓ Tool cache cleared")
                    else:
                        print("\nMCP tools not enabled")
                    continue
                
                # Handle execute command
                if command == "execute":
                    if not mcp_agent:
                        print("\nMCP tools not enabled")
                        continue
                    
                    tool_name = args.strip()
                    tool = mcp_agent.get_tool(tool_name)
                    
                    if not tool:
                        print(f"\n✗ Tool not found: {tool_name}")
                        print("\nAvailable tools:")
                        for t in mcp_agent.get_available_tools():
                            print(f"  • {t.name}")
                        continue
                    
                    print(f"\nTool: {tool.name}")
                    print(f"Description: {tool.description}")
                    print(f"Parameters: {tool.input_schema.get('properties', {})}")
                    
                    # Get arguments from user
                    arguments = {}
                    properties = tool.input_schema.get('properties', {})
                    required = tool.input_schema.get('required', [])
                    
                    for param_name, param_info in properties.items():
                        is_required = param_name in required
                        param_type = param_info.get('type', 'string')
                        
                        # Build prompt with helpful information
                        prompt = f"  {param_name}"
                        if is_required:
                            prompt += " (required)"
                        
                        # Show enum values if available
                        if 'enum' in param_info:
                            enum_values = param_info['enum']
                            prompt += f" [{', '.join(map(str, enum_values))}]"
                        else:
                            prompt += f" [{param_type}]"
                        
                        # Show description if available
                        if 'description' in param_info:
                            print(f"    {param_info['description']}")
                        
                        prompt += ": "
                        value = input(prompt).strip()
                        
                        if value:
                            # Simple type conversion
                            param_type = param_info.get('type', 'string')
                            if param_type == 'integer':
                                value = int(value)
                            elif param_type == 'number':
                                value = float(value)
                            elif param_type == 'boolean':
                                value = value.lower() in ['true', 'yes', '1']
                            
                            arguments[param_name] = value
                        elif is_required:
                            print(f"✗ Required parameter missing: {param_name}")
                            break
                    else:
                        # All required parameters provided
                        try:
                            print(f"\nExecuting {tool_name}...")
                            result = await mcp_agent.execute_tool(tool_name, arguments)
                            print(f"\n✓ Result:")
                            pretty_print_result(result)
                        except MCPError as e:
                            print(f"\n✗ Tool execution failed: {e}")
                    
                    continue
                
                # Handle query command
                if command == "query":
                    query = args.strip()
                    
                    if not query:
                        print("\n✗ Please provide a query")
                        continue
                    
                    print(f"\nQuery: {query}")
                    
                    # For now, just show that we would process the query
                    # In a full implementation, this would integrate with the RAG system
                    print("\n[Note: Full RAG integration with MCP tools coming in Phase 10.2]")
                    print("This would:")
                    print("1. Analyze query to determine if tools are needed")
                    print("2. Perform RAG search for context")
                    print("3. Generate response with tool descriptions")
                    print("4. If LLM requests tool use, invoke tool")
                    print("5. Add tool results to context")
                    print("6. Generate final response")
                    
                    if mcp_agent:
                        print(f"\nAvailable tools: {len(mcp_agent.get_available_tools())}")
                    
                    continue
                
                # Default: treat as query
                query = user_input
                print(f"\nQuery: {query}")
                print("\n[Note: Full RAG integration with MCP tools coming in Phase 10.2]")
                
            except KeyboardInterrupt:
                print("\n\nUse 'exit' or 'quit' to exit")
                continue
            except Exception as e:
                print(f"\n✗ Error: {e}")
                continue
    
    finally:
        if mcp_agent:
            print("\nShutting down MCP agent...")
            await shutdown_mcp_agent()
            print("✓ MCP agent shut down")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Interactive CLI with MCP tool support"
    )
    parser.add_argument(
        "--no-tools",
        action="store_true",
        help="Disable MCP tools"
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to MCP configuration file"
    )
    
    args = parser.parse_args()
    
    try:
        asyncio.run(interactive_mode(
            enable_tools=not args.no_tools,
            config_path=args.config
        ))
    except KeyboardInterrupt:
        print("\n\nExiting...")
    except Exception as e:
        print(f"\n✗ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()