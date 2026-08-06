"""
Tool-Augmented RAG System

Integrates MCP tools with the RAG system to enable tool invocation during query processing.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass

from advisor.mcp_agent import MCPAgent, get_mcp_agent, MCPError

logger = logging.getLogger(__name__)


@dataclass
class ToolCall:
    """Represents a tool call from the LLM."""
    
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolResult:
    """Represents the result of a tool execution."""
    
    tool_call_id: str
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None


def should_use_tools(query: str, query_type: str) -> bool:
    """
    Determine if query would benefit from tool use.
    
    Args:
        query: User query
        query_type: Type of query (from query_processor)
        
    Returns:
        True if tools should be enabled
    """
    tool_indicators = {
        "report": ["generate report", "create report", "show report", "report on"],
        "command": ["run command", "execute", "invoke", "run"],
        "data": ["get data", "fetch", "retrieve", "list", "show me"],
        "action": ["create", "update", "delete", "modify", "add", "remove"],
        "lineage": ["lineage", "trace", "track", "flow"],
        "governance": ["governance", "policy", "compliance", "audit"]
    }
    
    query_lower = query.lower()
    
    # Check for explicit tool indicators
    for category, indicators in tool_indicators.items():
        if any(indicator in query_lower for indicator in indicators):
            logger.info(f"Query matches tool category: {category}")
            return True
    
    # Check query type
    action_query_types = ["code_search", "example", "troubleshooting"]
    if query_type in action_query_types:
        logger.info(f"Query type suggests tool use: {query_type}")
        return True
    
    return False


def extract_tool_calls(llm_response: Dict[str, Any]) -> List[ToolCall]:
    """
    Extract tool calls from LLM response.
    
    Args:
        llm_response: Response from LLM
        
    Returns:
        List of tool calls
    """
    tool_calls = []
    
    # Check for OpenAI-style tool calls
    if "tool_calls" in llm_response:
        for tc in llm_response["tool_calls"]:
            try:
                tool_calls.append(ToolCall(
                    id=tc["id"],
                    name=tc["function"]["name"],
                    arguments=json.loads(tc["function"]["arguments"])
                ))
            except (KeyError, json.JSONDecodeError) as e:
                logger.error(f"Failed to parse tool call: {e}")
    
    # Check for function_call (older format)
    elif "function_call" in llm_response:
        try:
            fc = llm_response["function_call"]
            tool_calls.append(ToolCall(
                id="call_0",
                name=fc["name"],
                arguments=json.loads(fc["arguments"])
            ))
        except (KeyError, json.JSONDecodeError) as e:
            logger.error(f"Failed to parse function call: {e}")
    
    return tool_calls


class ToolAugmentedRAG:
    """RAG system with MCP tool invocation capabilities."""
    
    def __init__(
        self,
        rag_system: Any,  # RAGSystem instance
        mcp_agent: Optional[MCPAgent] = None,
        max_tool_iterations: int = 3
    ):
        """
        Initialize tool-augmented RAG.
        
        Args:
            rag_system: Existing RAG system instance
            mcp_agent: MCP agent (if None, will get singleton)
            max_tool_iterations: Maximum tool invocation iterations
        """
        self.rag_system = rag_system
        self.mcp_agent = mcp_agent or get_mcp_agent()
        self.max_tool_iterations = max_tool_iterations
    
    async def query_with_tools(
        self,
        query: str,
        enable_tools: bool = True,
        use_cache: bool = True,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Process query with optional tool invocation.
        
        Flow:
        1. Analyze query to determine if tools are needed
        2. Perform RAG search for context
        3. Generate response with tool descriptions
        4. If LLM requests tool use, invoke tool
        5. Add tool results to context
        6. Generate final response
        
        Args:
            query: User query
            enable_tools: Whether to enable tool invocation
            use_cache: Whether to use cached tool results
            **kwargs: Additional arguments for RAG system
            
        Returns:
            Dictionary with response and metadata
        """
        try:
            # Get query type from RAG system
            query_type = kwargs.get("query_type", "explanation")
            
            # Determine if tools should be used
            use_tools = enable_tools and should_use_tools(query, query_type)
            
            if not use_tools or not self.mcp_agent._initialized:
                # Fall back to regular RAG
                logger.info("Processing query without tools")
                return await self._query_without_tools(query, **kwargs)
            
            # Process with tools
            logger.info("Processing query with tools enabled")
            return await self._query_with_tools(query, use_cache, **kwargs)
            
        except Exception as e:
            logger.error(f"Error in tool-augmented query: {e}")
            # Fall back to regular RAG on error
            return await self._query_without_tools(query, **kwargs)
    
    async def _query_without_tools(
        self,
        query: str,
        **kwargs
    ) -> Dict[str, Any]:
        """Process query without tools (regular RAG)."""
        # Call existing RAG system
        result = await self.rag_system.query(query, **kwargs)
        
        return {
            "response": result.get("response", ""),
            "sources": result.get("sources", []),
            "collections_searched": result.get("collections_searched", []),
            "tools_used": [],
            "tool_results": [],
            "query_type": result.get("query_type", "explanation")
        }
    
    async def _query_with_tools(
        self,
        query: str,
        use_cache: bool,
        **kwargs
    ) -> Dict[str, Any]:
        """Process query with tool invocation."""
        tools_used = []
        tool_results = []
        
        # Step 1: Get RAG context
        logger.info("Step 1: Getting RAG context")
        rag_result = await self.rag_system.query(query, **kwargs)
        
        context = rag_result.get("context", "")
        sources = rag_result.get("sources", [])
        collections = rag_result.get("collections_searched", [])
        
        # Step 2: Get available tools
        available_tools = self.mcp_agent.get_tool_descriptions()
        
        if not available_tools:
            logger.warning("No tools available, falling back to regular RAG")
            return await self._query_without_tools(query, **kwargs)
        
        # Step 3: Build messages with tool descriptions
        messages = self._build_messages_with_tools(
            query, context, available_tools
        )
        
        # Step 4: Iterative tool invocation
        iteration = 0
        while iteration < self.max_tool_iterations:
            iteration += 1
            logger.info(f"Tool iteration {iteration}/{self.max_tool_iterations}")
            
            # Get LLM response
            llm_response = await self._get_llm_response(messages, available_tools)
            
            # Check for tool calls
            tool_calls = extract_tool_calls(llm_response)
            
            if not tool_calls:
                # No more tool calls, we have final response
                final_response = llm_response.get("content", "")
                break
            
            # Execute tool calls
            logger.info(f"Executing {len(tool_calls)} tool calls")
            results = await self._execute_tool_calls(tool_calls, use_cache)
            
            # Track tools used
            for tc, result in zip(tool_calls, results):
                tools_used.append(tc.name)
                tool_results.append(result)
            
            # Add tool results to messages
            messages.append({
                "role": "assistant",
                "content": llm_response.get("content"),
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments)
                        }
                    }
                    for tc in tool_calls
                ]
            })
            
            for result in results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": result.tool_call_id,
                    "name": result.tool_name,
                    "content": json.dumps({
                        "success": result.success,
                        "result": result.result,
                        "error": result.error
                    })
                })
        else:
            # Max iterations reached
            logger.warning(f"Max tool iterations ({self.max_tool_iterations}) reached")
            final_response = "I apologize, but I reached the maximum number of tool invocations. Please try rephrasing your question."
        
        return {
            "response": final_response,
            "sources": sources,
            "collections_searched": collections,
            "tools_used": list(set(tools_used)),  # Unique tools
            "tool_results": tool_results,
            "query_type": rag_result.get("query_type", "explanation"),
            "tool_iterations": iteration
        }
    
    def _build_messages_with_tools(
        self,
        query: str,
        context: str,
        tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Build messages array with system prompt and tools."""
        system_prompt = f"""You are an expert Egeria advisor with access to tools for generating reports and executing commands.

Context from documentation:
{context}

When answering questions:
1. Use the provided context when available
2. If you need to generate a report or execute a command, use the available tools
3. Explain what you're doing when using tools
4. Provide clear, actionable responses

Available tools: {', '.join(t['function']['name'] for t in tools)}
"""
        
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
    
    async def _get_llm_response(
        self,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Get response from LLM with tool descriptions."""
        # This would integrate with the actual LLM client
        # For now, return a mock response structure
        
        # In real implementation:
        # llm_client = self.rag_system.llm_client
        # response = await llm_client.chat_completion(
        #     messages=messages,
        #     tools=tools,
        #     tool_choice="auto"
        # )
        # return response["choices"][0]["message"]
        
        # Mock response for now
        return {
            "role": "assistant",
            "content": "Based on the context, here's the answer..."
        }
    
    async def _execute_tool_calls(
        self,
        tool_calls: List[ToolCall],
        use_cache: bool
    ) -> List[ToolResult]:
        """Execute multiple tool calls."""
        results = []
        
        for tc in tool_calls:
            try:
                logger.info(f"Executing tool: {tc.name}")
                result = await self.mcp_agent.execute_tool(
                    tc.name,
                    tc.arguments,
                    use_cache=use_cache
                )
                
                results.append(ToolResult(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    success=True,
                    result=result
                ))
                
            except MCPError as e:
                logger.error(f"Tool {tc.name} failed: {e}")
                results.append(ToolResult(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    success=False,
                    result=None,
                    error=str(e)
                ))
        
        return results


# Singleton instance
_tool_augmented_rag: Optional[ToolAugmentedRAG] = None


def get_tool_augmented_rag(
    rag_system: Any = None,
    mcp_agent: Optional[MCPAgent] = None
) -> ToolAugmentedRAG:
    """
    Get or create the tool-augmented RAG singleton.
    
    Args:
        rag_system: RAG system instance
        mcp_agent: MCP agent instance
        
    Returns:
        ToolAugmentedRAG instance
    """
    global _tool_augmented_rag
    
    if _tool_augmented_rag is None:
        if rag_system is None:
            # Import here to avoid circular dependency
            from advisor.rag_system import get_rag_system
            rag_system = get_rag_system()
        
        _tool_augmented_rag = ToolAugmentedRAG(
            rag_system=rag_system,
            mcp_agent=mcp_agent
        )
    
    return _tool_augmented_rag