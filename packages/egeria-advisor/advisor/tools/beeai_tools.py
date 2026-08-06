"""
BeeAI tools wrapping our optimized RAG retrieval.

These tools integrate our custom multi-collection search with BeeAI agents,
preserving all optimizations (caching, routing, parallel search).
"""

from typing import Optional, List, Dict, Any
from beeai_framework.tools import Tool, JSONToolOutput, StringToolOutput

from advisor.rag_retrieval import RAGRetriever


class MultiCollectionSearchTool(Tool):
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
    
    def __init__(self):
        """Initialize the search tool with RAG retriever."""
        super().__init__(options={
            "name": "search_egeria_code",
            "description": """Search for relevant Egeria code, documentation, and examples.
Use this tool when you need to find:
- How to use specific Egeria functions or classes
- Code examples for Egeria operations
- API documentation
- Implementation details

The tool automatically routes queries to the most relevant collections
and returns ranked results with source information.

Parameters:
- query (str): The search query to find relevant Egeria code and documentation
- top_k (int, optional): Number of results to return (default: 5)""",
        })
        self.retriever = RAGRetriever(
            use_multi_collection=True,
            enable_cache=True
        )
    
    def run(self, query: str, top_k: int = 5) -> JSONToolOutput:
        """
        Execute the search and return structured results.
        
        Parameters
        ----------
        query : str
            The search query
        top_k : int, optional
            Number of results to return (default: 5)
            
        Returns
        -------
        JSONToolOutput
            Structured search results with metadata
        """
        results = self.retriever.retrieve(
            query=query,
            top_k=top_k
        )
        
        if not results:
            return JSONToolOutput(data={
                "status": "no_results",
                "message": "No relevant results found.",
                "results": []
            })
        
        # Format results as structured data
        formatted_results = []
        for i, result in enumerate(results, 1):
            formatted_results.append({
                "rank": i,
                "file_path": result.metadata.get('file_path', 'Unknown'),
                "collection": result.metadata.get('collection', 'Unknown'),
                "element_name": result.metadata.get('name', ''),
                "element_type": result.metadata.get('type', result.metadata.get('element_type', '')),
                "relevance_score": round(result.score, 3),
                "content": result.content[:500] + ("..." if len(result.content) > 500 else ""),
                "full_content_length": len(result.content)
            })
        
        return JSONToolOutput(data={
            "status": "success",
            "query": query,
            "total_results": len(results),
            "results": formatted_results
        })


class CodeAnalysisTool(Tool):
    """
    Analyze specific code elements from Egeria codebase.
    
    This tool filters results by element type (class, function, method, etc.)
    and provides detailed code context.
    """
    
    def __init__(self):
        """Initialize the code analysis tool."""
        super().__init__(options={
            "name": "analyze_egeria_code",
            "description": """Analyze specific code elements (classes, functions, methods) from Egeria.
Use this when you need to:
- Find all classes related to a topic
- Locate specific functions or methods
- Understand code structure and relationships

You can filter by element types: class, function, method, variable, etc.

Parameters:
- query (str): What code elements to analyze
- element_types (list[str], optional): Filter by element types""",
        })
        self.retriever = RAGRetriever(use_multi_collection=True, enable_cache=True)
    
    def run(self, query: str, element_types: Optional[List[str]] = None) -> JSONToolOutput:
        """
        Execute code analysis and return structured results.
        
        Parameters
        ----------
        query : str
            What code elements to analyze
        element_types : list[str], optional
            Filter by element types (class, function, method, etc.)
            
        Returns
        -------
        JSONToolOutput
            Structured code analysis results grouped by type
        """
        results = self.retriever.retrieve(
            query=query,
            top_k=10,
            element_types=element_types if element_types else None
        )
        
        if not results:
            return JSONToolOutput(data={
                "status": "no_results",
                "message": "No code elements found matching the criteria.",
                "results_by_type": {}
            })
        
        # Group by element type
        by_type: Dict[str, List[Dict[str, Any]]] = {}
        for result in results:
            elem_type = result.metadata.get('type', result.metadata.get('element_type', 'unknown'))
            if elem_type not in by_type:
                by_type[elem_type] = []
            
            by_type[elem_type].append({
                "name": result.metadata.get('name', 'unnamed'),
                "file_path": result.metadata.get('file_path', 'unknown'),
                "collection": result.metadata.get('collection', 'unknown'),
                "relevance_score": round(result.score, 3),
                "code_snippet": result.content[:300] + ("..." if len(result.content) > 300 else ""),
                "full_content_length": len(result.content)
            })
        
        # Limit to top 5 per type
        for elem_type in by_type:
            by_type[elem_type] = by_type[elem_type][:5]
        
        return JSONToolOutput(data={
            "status": "success",
            "query": query,
            "element_types_filter": element_types,
            "total_results": len(results),
            "results_by_type": by_type,
            "type_counts": {k: len(v) for k, v in by_type.items()}
        })


class DocumentationLookupTool(Tool):
    """
    Look up Egeria documentation and guides.
    
    Specialized tool for finding documentation, tutorials, and guides
    from the egeria_docs collection.
    """
    
    def __init__(self):
        """Initialize the documentation lookup tool."""
        super().__init__(options={
            "name": "lookup_egeria_docs",
            "description": """Look up Egeria documentation, tutorials, and guides.
Use this when you need:
- Official documentation
- Getting started guides
- Conceptual explanations
- Architecture documentation
- Best practices

This tool focuses on the egeria_docs collection for authoritative information.

Parameters:
- query (str): What documentation to look up
- top_k (int, optional): Number of results (default: 3)""",
        })
        self.retriever = RAGRetriever(use_multi_collection=True, enable_cache=True)
    
    def run(self, query: str, top_k: int = 3) -> JSONToolOutput:
        """
        Look up documentation and return structured results.
        
        Parameters
        ----------
        query : str
            What documentation to look up
        top_k : int, optional
            Number of results (default: 3)
            
        Returns
        -------
        JSONToolOutput
            Structured documentation results
        """
        # Force routing to docs collection by adding "documentation" to query
        enhanced_query = f"documentation {query}"
        
        results = self.retriever.retrieve(
            query=enhanced_query,
            top_k=top_k * 2  # Get more results to filter
        )
        
        # Filter for docs collection
        doc_results = [r for r in results if r.metadata.get('collection') == 'egeria_docs'][:top_k]
        
        if not doc_results:
            return JSONToolOutput(data={
                "status": "no_results",
                "message": "No documentation found. Try a different query.",
                "results": []
            })
        
        formatted_results = []
        for i, result in enumerate(doc_results, 1):
            formatted_results.append({
                "rank": i,
                "file_path": result.metadata.get('file_path', 'Unknown'),
                "section": result.metadata.get('name', 'General'),
                "relevance_score": round(result.score, 3),
                "content": result.content[:800] + ("..." if len(result.content) > 800 else ""),
                "full_content_length": len(result.content)
            })
        
        return JSONToolOutput(data={
            "status": "success",
            "query": query,
            "total_results": len(formatted_results),
            "results": formatted_results
        })


def get_egeria_tools() -> List[Tool]:
    """
    Get all Egeria tools for BeeAI agents.
    
    Returns
    -------
    list[Tool]
        List of BeeAI tools for Egeria advisor
    """
    return [
        MultiCollectionSearchTool(),
        CodeAnalysisTool(),
        DocumentationLookupTool()
    ]