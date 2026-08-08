#!/usr/bin/env python3
"""
Interactive CLI with Tool-Augmented RAG

Combines RAG search with MCP tool invocation for enhanced query processing.

Example usage:
    python examples/cli_with_tools_and_rag.py
    python examples/cli_with_tools_and_rag.py --no-tools
    python examples/cli_with_tools_and_rag.py --config config/mcp_servers.json
"""

import asyncio
import argparse
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from advisor.mcp_agent import initialize_mcp_agent, shutdown_mcp_agent
from advisor.tool_augmented_rag import get_tool_augmented_rag


async def interactive_mode(
    enable_tools: bool = True,
    config_path: Optional[str] = None
):
    """
    Interactive CLI with tool-augmented RAG.
    
    Args:
        enable_tools: Whether to enable MCP tools
        config_path: Path to MCP configuration file
    """
    print("=" * 70)
    print("Egeria Advisor - Tool-Augmented RAG Mode")
    print("=" * 70)
    
    mcp_agent = None
    tool_rag = None
    
    if enable_tools:
        try:
            print("\nInitializing MCP agent...")
            mcp_agent = await initialize_mcp_agent(config_path=config_path)
            
            tools = mcp_agent.get_available_tools()
            if tools:
                print(f"\n✓ MCP agent initialized with {len(tools)} tools:")
                for tool in tools:
                    print(f"  • {tool.name}: {tool.description}")
                
                # Initialize tool-augmented RAG
                tool_rag = get_tool_augmented_rag(mcp_agent=mcp_agent)
                print("\n✓ Tool-augmented RAG initialized")
            else:
                print("\n⚠ No MCP tools available")
                enable_tools = False
                
        except Exception as e:
            print(f"\n⚠ Failed to initialize MCP: {e}")
            print("Continuing without MCP tools...")
            enable_tools = False
    else:
        print("\nMCP tools disabled")
    
    if not enable_tools:
        # Fall back to regular RAG
        tool_rag = get_tool_augmented_rag()
        print("✓ Regular RAG initialized")
    
    print("\nCommands:")
    print("  <query>          - Ask a question (with or without tools)")
    print("  tools            - List available tools")
    print("  metrics          - Show MCP metrics")
    print("  clear-cache      - Clear tool result cache")
    print("  help             - Show this help")
    print("  exit/quit        - Exit the program")
    print()
    
    try:
        while True:
            try:
                user_input = input(">>> ").strip()
                
                if not user_input:
                    continue
                
                if user_input.lower() in ["exit", "quit"]:
                    break
                
                if user_input.lower() == "help":
                    print("\nCommands:")
                    print("  <query>          - Ask a question")
                    print("  tools            - List available tools")
                    print("  metrics          - Show MCP metrics")
                    print("  clear-cache      - Clear tool result cache")
                    print("  help             - Show this help")
                    print("  exit/quit        - Exit the program")
                    continue
                
                if user_input.lower() == "tools":
                    if mcp_agent:
                        tools = mcp_agent.get_available_tools()
                        if tools:
                            print(f"\nAvailable tools ({len(tools)}):")
                            for tool in tools:
                                print(f"\n  {tool.name} ({tool.server})")
                                print(f"    {tool.description}")
                                params = tool.input_schema.get('properties', {})
                                if params:
                                    print(f"    Parameters: {', '.join(params.keys())}")
                        else:
                            print("\nNo tools available")
                    else:
                        print("\nMCP tools not enabled")
                    continue
                
                if user_input.lower() == "metrics":
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
                
                if user_input.lower() == "clear-cache":
                    if mcp_agent:
                        mcp_agent.clear_cache()
                        print("\n✓ Tool cache cleared")
                    else:
                        print("\nMCP tools not enabled")
                    continue
                
                # Process query with tool-augmented RAG
                query = user_input
                print(f"\nProcessing: {query}")
                print("─" * 70)
                
                try:
                    result = await tool_rag.query_with_tools(
                        query,
                        enable_tools=enable_tools
                    )
                    
                    # Display response
                    print(f"\n{result['response']}\n")
                    
                    # Display metadata
                    if result.get('tools_used'):
                        print(f"🔧 Tools used: {', '.join(result['tools_used'])}")
                        if result.get('tool_iterations'):
                            print(f"   Iterations: {result['tool_iterations']}")
                    
                    if result.get('collections_searched'):
                        print(f"📚 Collections: {', '.join(result['collections_searched'])}")
                    
                    if result.get('sources'):
                        print(f"📄 Sources: {len(result['sources'])} documents")
                    
                    print()
                    
                except Exception as e:
                    print(f"\n✗ Error processing query: {e}\n")
                
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
        description="Interactive CLI with tool-augmented RAG"
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
    from typing import Optional
    main()