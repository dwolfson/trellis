"""
LangChain tools wrapping our optimized RAG retrieval.

These tools integrate our custom multi-collection search with LangChain agents,
preserving all optimizations (caching, routing, parallel search).
"""

from typing import Optional, List, Type
from pydantic import BaseModel, Field
from langchain.tools import BaseTool

from advisor.rag_retrieval import RAGRetriever


class MultiCollectionSearchInput(BaseModel):
    """Input schema for multi-collection search tool."""
    query: str = Field(description="The search query to find relevant Egeria code and documentation")
    top_k: int = Field(default=5, description="Number of results to return (default: 5)")


class MultiCollectionSearchTool(BaseTool):
    """
    Search across multiple Egeria code collections using semantic similarity.
    
    This tool uses our optimized RAG retrieval with:
    - Intelligent routing to relevant collections
    - Parallel search across collections
    - Query result caching (17,997x speedup for repeated queries)
    - Weighted result reranking
    
    Searches across: pyegeria, pyegeria_cli, pyegeria_drE, egeria_java, 
    egeria_docs, egeria_workspaces
    """
    
    name: str = "search_egeria_code"
    description: str = """
    Search for relevant Egeria code, documentation, and examples.
    Use this tool when you need to find:
    - How to use specific Egeria functions or classes
    - Code examples for Egeria operations
    - API documentation
    - Implementation details
    
    The tool automatically routes queries to the most relevant collections
    and returns ranked results with source information.
    """
    args_schema: Type[BaseModel] = MultiCollectionSearchInput
    
    def __init__(self):
        super().__init__()
        self.retriever = RAGRetriever(
            use_multi_collection=True,
            enable_cache=True
        )
    
    def _run(self, query: str, top_k: int = 5) -> str:
        """Execute the search synchronously."""
        results = self.retriever.retrieve(
            query=query,
            top_k=top_k
        )
        
        if not results:
            return "No relevant results found."
        
        # Format results for the agent
        output_lines = [f"Found {len(results)} relevant results:\n"]
        
        for i, result in enumerate(results, 1):
            file_path = result.metadata.get('file_path', 'Unknown')
            collection = result.metadata.get('collection', 'Unknown')
            name = result.metadata.get('name', '')
            score = result.score
            
            output_lines.append(f"\n{i}. [{collection}] {file_path}")
            if name:
                output_lines.append(f"   Element: {name}")
            output_lines.append(f"   Relevance: {score:.3f}")
            output_lines.append(f"   Content:\n{result.content[:500]}...")
            if len(result.content) > 500:
                output_lines.append("   [Content truncated]")
        
        return "\n".join(output_lines)
    
    async def _arun(self, query: str, top_k: int = 5) -> str:
        """Execute the search asynchronously."""
        # Use the async retrieval method
        results = await self.retriever.retrieve_async(
            query=query,
            top_k=top_k
        )
        
        if not results:
            return "No relevant results found."
        
        # Format results for the agent
        output_lines = [f"Found {len(results)} relevant results:\n"]
        
        for i, result in enumerate(results, 1):
            file_path = result.metadata.get('file_path', 'Unknown')
            collection = result.metadata.get('collection', 'Unknown')
            name = result.metadata.get('name', '')
            score = result.score
            
            output_lines.append(f"\n{i}. [{collection}] {file_path}")
            if name:
                output_lines.append(f"   Element: {name}")
            output_lines.append(f"   Relevance: {score:.3f}")
            output_lines.append(f"   Content:\n{result.content[:500]}...")
            if len(result.content) > 500:
                output_lines.append("   [Content truncated]")
        
        return "\n".join(output_lines)


class CodeAnalysisInput(BaseModel):
    """Input schema for code analysis tool."""
    query: str = Field(description="What code elements to analyze")
    element_types: Optional[List[str]] = Field(
        default=None,
        description="Filter by element types: class, function, method, etc."
    )


class CodeAnalysisTool(BaseTool):
    """
    Analyze specific code elements from Egeria codebase.
    
    This tool filters results by element type (class, function, method, etc.)
    and provides detailed code context.
    """
    
    name: str = "analyze_egeria_code"
    description: str = """
    Analyze specific code elements (classes, functions, methods) from Egeria.
    Use this when you need to:
    - Find all classes related to a topic
    - Locate specific functions or methods
    - Understand code structure and relationships
    
    You can filter by element types: class, function, method, variable, etc.
    """
    args_schema: Type[BaseModel] = CodeAnalysisInput
    
    def __init__(self):
        super().__init__()
        self.retriever = RAGRetriever(use_multi_collection=True, enable_cache=True)
    
    def _run(self, query: str, element_types: Optional[List[str]] = None) -> str:
        """Execute code analysis synchronously."""
        results = self.retriever.retrieve(
            query=query,
            top_k=10,
            element_types=element_types if element_types else None
        )
        
        if not results:
            return "No code elements found matching the criteria."
        
        # Group by element type
        by_type = {}
        for result in results:
            elem_type = result.metadata.get('type', result.metadata.get('element_type', 'unknown'))
            if elem_type not in by_type:
                by_type[elem_type] = []
            by_type[elem_type].append(result)
        
        # Format output
        output_lines = [f"Found {len(results)} code elements:\n"]
        
        for elem_type, elements in by_type.items():
            output_lines.append(f"\n{elem_type.upper()}:")
            for elem in elements[:5]:  # Limit to 5 per type
                name = elem.metadata.get('name', 'unnamed')
                file_path = elem.metadata.get('file_path', 'unknown')
                score = elem.score
                
                output_lines.append(f"  - {name}")
                output_lines.append(f"    File: {file_path}")
                output_lines.append(f"    Relevance: {score:.3f}")
                output_lines.append(f"    Code:\n{elem.content[:300]}...")
                output_lines.append("")
        
        return "\n".join(output_lines)
    
    async def _arun(self, query: str, element_types: Optional[List[str]] = None) -> str:
        """Execute code analysis asynchronously."""
        return self._run(query, element_types)


def get_egeria_tools() -> List[BaseTool]:
    """
    Get all Egeria tools for LangChain agents.
    
    Returns
    -------
    list
        List of LangChain tools
    """
    return [
        MultiCollectionSearchTool(),
        CodeAnalysisTool()
    ]