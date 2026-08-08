"""
MCP Client for Egeria Advisor

Implements Model Context Protocol (MCP) client for communicating with MCP servers
like the pyegeria MCP server for reports and Dr. Egeria commands.
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timedelta
import subprocess

logger = logging.getLogger(__name__)


@dataclass
class MCPTool:
    """Represents an MCP tool."""
    
    name: str
    description: str
    server: str
    input_schema: Dict[str, Any]
    output_schema: Optional[Dict[str, Any]] = None
    
    def to_function_definition(self) -> Dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema
            }
        }


@dataclass
class MCPResource:
    """Represents an MCP resource."""
    
    uri: str
    name: str
    description: str
    mime_type: Optional[str] = None


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    # For local servers (stdio transport)
    command: Optional[str] = None
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)

    # For remote servers (SSE/HTTP transport)
    url: Optional[str] = None
    transport: str = "stdio"  # "stdio" or "sse"
    headers: Dict[str, str] = field(default_factory=dict)  # e.g. Authorization

    # Common settings
    enabled: bool = True
    description: str = ""

    def get_env_with_defaults(self) -> Dict[str, str]:
        """Get environment variables with system env as fallback."""
        env = os.environ.copy()
        env.update(self.env)
        return env

    def is_local(self) -> bool:
        """Check if this is a local server."""
        return self.transport == "stdio" and self.command is not None

    def is_remote(self) -> bool:
        """Check if this is a remote server."""
        return self.transport == "sse" and self.url is not None


class MCPError(Exception):
    """Base exception for MCP errors."""
    pass


class MCPConnectionError(MCPError):
    """Failed to connect to MCP server."""
    pass


class MCPToolNotFoundError(MCPError):
    """Requested tool not found."""
    pass


class MCPToolExecutionError(MCPError):
    """Tool execution failed."""
    pass


class MCPTimeoutError(MCPError):
    """Tool execution timed out."""
    pass


class MCPClient:
    """Client for communicating with MCP servers."""
    
    def __init__(self, server_name: str, server_config: MCPServerConfig):
        """
        Initialize MCP client.
        
        Args:
            server_name: Name of the MCP server
            server_config: Configuration for the server
        """
        self.server_name = server_name
        self.server_config = server_config
        self.process: Optional[subprocess.Popen] = None
        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}
        self.connected = False
        self._request_id = 0
        
    async def connect(self) -> bool:
        """
        Start MCP server process and establish connection.
        
        Returns:
            True if connection successful
            
        Raises:
            MCPConnectionError: If connection fails
        """
        try:
            logger.info(f"Connecting to MCP server: {self.server_name}")
            
            # Start the MCP server process
            self.process = subprocess.Popen(
                [self.server_config.command] + self.server_config.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self.server_config.get_env_with_defaults(),
                text=True,
                bufsize=1
            )
            
            # Wait a bit for process to start
            await asyncio.sleep(0.5)
            
            # Check if process is still running
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise MCPConnectionError(
                    f"MCP server {self.server_name} failed to start: {stderr}"
                )
            
            # Send initialize request
            init_response = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {},
                    "resources": {}
                },
                "clientInfo": {
                    "name": "egeria-advisor",
                    "version": "1.0.0"
                }
            })
            
            if "error" in init_response:
                raise MCPConnectionError(
                    f"Failed to initialize: {init_response['error']}"
                )
            
            self.connected = True
            logger.info(f"Connected to MCP server: {self.server_name}")
            
            # Discover tools and resources
            await self.discover_tools()
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to MCP server {self.server_name}: {e}")
            if self.process:
                self.process.terminate()
                self.process = None
            raise MCPConnectionError(f"Connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Stop MCP server process."""
        if self.process:
            logger.info(f"Disconnecting from MCP server: {self.server_name}")
            try:
                self.process.terminate()
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
            finally:
                self.process = None
                self.connected = False
                logger.info(f"Disconnected from MCP server: {self.server_name}")
    
    async def discover_tools(self) -> List[MCPTool]:
        """
        Discover available tools from the MCP server.
        
        Returns:
            List of discovered tools
        """
        try:
            response = await self._send_request("tools/list", {})
            
            if "error" in response:
                logger.error(f"Failed to discover tools: {response['error']}")
                return []
            
            tools = []
            for tool_data in response.get("tools", []):
                tool = MCPTool(
                    name=tool_data["name"],
                    description=tool_data.get("description", ""),
                    server=self.server_name,
                    input_schema=tool_data.get("inputSchema", {}),
                    output_schema=tool_data.get("outputSchema")
                )
                self.tools[tool.name] = tool
                tools.append(tool)
            
            logger.info(f"Discovered {len(tools)} tools from {self.server_name}")
            return tools
            
        except Exception as e:
            logger.error(f"Failed to discover tools: {e}")
            return []
    
    async def invoke_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int = 30
    ) -> Any:
        """
        Invoke a tool with given arguments.
        
        Args:
            tool_name: Name of the tool to invoke
            arguments: Tool arguments
            timeout: Timeout in seconds
            
        Returns:
            Tool execution result
            
        Raises:
            MCPToolNotFoundError: If tool not found
            MCPToolExecutionError: If execution fails
            MCPTimeoutError: If execution times out
        """
        if tool_name not in self.tools:
            raise MCPToolNotFoundError(f"Tool not found: {tool_name}")
        
        try:
            logger.info(f"Invoking tool: {tool_name} with args: {arguments}")
            
            response = await asyncio.wait_for(
                self._send_request("tools/call", {
                    "name": tool_name,
                    "arguments": arguments
                }),
                timeout=timeout
            )
            
            if "error" in response:
                raise MCPToolExecutionError(
                    f"Tool execution failed: {response['error']}"
                )
            
            result = response.get("content", [])
            logger.info(f"Tool {tool_name} completed successfully")
            return result
            
        except asyncio.TimeoutError:
            raise MCPTimeoutError(
                f"Tool {tool_name} execution timed out after {timeout}s"
            )
        except Exception as e:
            logger.error(f"Tool {tool_name} execution failed: {e}")
            raise MCPToolExecutionError(f"Execution failed: {e}")
    
    async def list_resources(self) -> List[MCPResource]:
        """
        List available resources from the MCP server.
        
        Returns:
            List of available resources
        """
        try:
            response = await self._send_request("resources/list", {})
            
            if "error" in response:
                logger.error(f"Failed to list resources: {response['error']}")
                return []
            
            resources = []
            for resource_data in response.get("resources", []):
                resource = MCPResource(
                    uri=resource_data["uri"],
                    name=resource_data["name"],
                    description=resource_data.get("description", ""),
                    mime_type=resource_data.get("mimeType")
                )
                self.resources[resource.uri] = resource
                resources.append(resource)
            
            logger.info(f"Found {len(resources)} resources from {self.server_name}")
            return resources
            
        except Exception as e:
            logger.error(f"Failed to list resources: {e}")
            return []
    
    async def _send_request(
        self,
        method: str,
        params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Send a JSON-RPC request to the MCP server.
        
        Args:
            method: RPC method name
            params: Method parameters
            
        Returns:
            Response from server
        """
        if not self.process or not self.process.stdin or not self.process.stdout:
            raise MCPConnectionError("Not connected to MCP server")
        
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params
        }

        # subprocess.Popen's stdin/stdout are plain blocking streams — run the
        # write and each readline() in a thread executor rather than calling
        # them directly here. Calling blocking I/O straight from an async def
        # freezes the event loop thread itself, which silently defeats
        # invoke_tool()'s asyncio.wait_for() timeout: wait_for can only act at
        # an actual await/cancellation point, and there isn't one while the
        # thread is stuck inside readline(). Without this, an MCP server that
        # never writes a response hangs this call forever regardless of the
        # configured timeout.
        loop = asyncio.get_event_loop()

        # Send request
        request_json = json.dumps(request) + "\n"

        def _write() -> None:
            self.process.stdin.write(request_json)
            self.process.stdin.flush()

        await loop.run_in_executor(None, _write)

        # Read response — the MCP server may emit non-JSON lines to stdout
        # (startup messages, warnings, debug output) before the JSON-RPC response.
        # Accumulate lines until we have parseable JSON, skipping non-JSON preamble.
        accumulated = ""
        max_bytes = 4 * 1024 * 1024  # 4 MB safety cap
        while True:
            line = await loop.run_in_executor(None, self.process.stdout.readline)
            if not line:
                raise MCPConnectionError("No response from MCP server")
            accumulated += line
            if len(accumulated) > max_bytes:
                raise MCPConnectionError("MCP server response exceeded size limit")
            try:
                response = json.loads(accumulated)
                break
            except json.JSONDecodeError:
                # If the accumulated text doesn't start with '{' it's a preamble
                # line — discard and start fresh with the next line.
                if not accumulated.lstrip().startswith("{"):
                    logger.debug(
                        f"Skipping non-JSON stdout from MCP server: {accumulated[:120]!r}"
                    )
                    accumulated = ""
                # Otherwise keep accumulating (multi-line JSON response).

        if "error" in response:
            return response

        return response.get("result", {})


@dataclass
class MCPMetrics:
    """Metrics for MCP operations."""
    
    tool_invocations: int = 0
    tool_successes: int = 0
    tool_failures: int = 0
    total_execution_time: float = 0.0
    cache_hits: int = 0
    cache_misses: int = 0
    
    def success_rate(self) -> float:
        """Calculate tool success rate."""
        if self.tool_invocations == 0:
            return 0.0
        return self.tool_successes / self.tool_invocations
    
    def average_execution_time(self) -> float:
        """Calculate average tool execution time."""
        if self.tool_invocations == 0:
            return 0.0
        return self.total_execution_time / self.tool_invocations
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "tool_invocations": self.tool_invocations,
            "tool_successes": self.tool_successes,
            "tool_failures": self.tool_failures,
            "success_rate": self.success_rate(),
            "average_execution_time": self.average_execution_time(),
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses
        }


class ToolCache:
    """Cache for tool results."""
    
    def __init__(self, ttl: int = 300):
        """
        Initialize tool cache.
        
        Args:
            ttl: Time to live in seconds (default: 5 minutes)
        """
        self.cache: Dict[str, Tuple[Any, datetime]] = {}
        self.ttl = ttl
    
    def get(self, tool_name: str, arguments: Dict[str, Any]) -> Optional[Any]:
        """
        Get cached result if not expired.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Cached result or None if not found/expired
        """
        key = self._make_key(tool_name, arguments)
        
        if key in self.cache:
            result, timestamp = self.cache[key]
            if datetime.now() - timestamp < timedelta(seconds=self.ttl):
                return result
            else:
                # Expired, remove from cache
                del self.cache[key]
        
        return None
    
    def set(self, tool_name: str, arguments: Dict[str, Any], value: Any) -> None:
        """
        Cache a result.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            value: Result to cache
        """
        key = self._make_key(tool_name, arguments)
        self.cache[key] = (value, datetime.now())
    
    def clear(self) -> None:
        """Clear all cached results."""
        self.cache.clear()
    
    def _make_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """
        Create cache key from tool name and arguments.
        
        Args:
            tool_name: Name of the tool
            arguments: Tool arguments
            
        Returns:
            Cache key string
        """
        return f"{tool_name}:{json.dumps(arguments, sort_keys=True)}"


class MCPSSEClient:
    """
    MCP client for SSE (remote HTTP) transport.

    Maintains a persistent background event loop so the SSE connection and
    ClientSession stay alive between tool calls.  The calling code uses the
    same async interface as MCPClient (connect / disconnect / invoke_tool).
    """

    def __init__(self, server_name: str, server_config: MCPServerConfig):
        import threading
        self.server_name = server_name
        self.server_config = server_config
        self.tools: Dict[str, MCPTool] = {}
        self.resources: Dict[str, MCPResource] = {}
        self.connected = False

        # Background loop keeps SSE connection + ClientSession alive between calls
        self._loop = asyncio.new_event_loop()
        self._bg_thread = threading.Thread(
            target=self._loop.run_forever, daemon=True, name=f"mcp-sse-{server_name}"
        )
        self._bg_thread.start()
        self._session = None
        self._exit_stack = None

    # ------------------------------------------------------------------
    # Internal async helpers – run on self._loop via _submit()
    # ------------------------------------------------------------------

    def _submit(self, coro, timeout: int = 30):
        """Run coro on the background loop and block until done."""
        import concurrent.futures
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=timeout)

    async def _do_connect(self) -> None:
        try:
            from mcp.client.sse import sse_client
            from mcp import ClientSession
        except ImportError as exc:
            raise MCPConnectionError(
                "mcp package not installed — run 'uv add mcp' to enable SSE transport"
            ) from exc

        from contextlib import AsyncExitStack

        self._exit_stack = AsyncExitStack()
        headers = self.server_config.headers or {}

        read, write = await self._exit_stack.enter_async_context(
            sse_client(self.server_config.url, headers=headers)
        )
        self._session = await self._exit_stack.enter_async_context(
            ClientSession(read, write)
        )
        await self._session.initialize()

        tools_result = await self._session.list_tools()
        for tool_data in tools_result.tools:
            self.tools[tool_data.name] = MCPTool(
                name=tool_data.name,
                description=tool_data.description or "",
                server=self.server_name,
                input_schema=tool_data.inputSchema or {},
            )
        self.connected = True
        logger.info(
            f"SSE connected to {self.server_name} at {self.server_config.url}: "
            f"{len(self.tools)} tools"
        )

    async def _do_disconnect(self) -> None:
        if self._exit_stack:
            await self._exit_stack.aclose()
        self._exit_stack = None
        self._session = None
        self.connected = False

    async def _do_invoke(self, tool_name: str, arguments: Dict[str, Any]) -> Any:
        if not self._session:
            raise MCPConnectionError("SSE client not connected")
        result = await self._session.call_tool(tool_name, arguments)
        return result.content

    # ------------------------------------------------------------------
    # Public interface — mirrors MCPClient async API
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._submit(self._do_connect(), timeout=15))
        return True

    async def disconnect(self) -> None:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, lambda: self._submit(self._do_disconnect(), timeout=10))
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._bg_thread.join(timeout=5)

    async def invoke_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: int = 30,
    ) -> Any:
        if tool_name not in self.tools:
            raise MCPToolNotFoundError(f"Tool not found: {tool_name}")
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._submit(self._do_invoke(tool_name, arguments), timeout=timeout),
        )