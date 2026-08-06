"""
RAG Tool for BeeAI Agents.

This module wraps the Egeria RAG System as a Tool that can be used by
BeeAI agents to retrieve information.
"""

from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from beeai_framework.tools.tool import Tool
from beeai_framework.emitter import Emitter
from advisor.rag_system import get_rag_system

class RAGToolInput(BaseModel):
    """Input schema for RAG Tool."""
    query: str = Field(..., description="The query to search for in the knowledge base.")

class RAGTool(Tool):
    """
    Tool for retrieving information from the Egeria knowledge base using RAG.
    """
    name = "SearchKnowledgeBase"
    description = (
        "Search the Egeria knowledge base for documentation, code examples, "
        "and explanations. Use this tool to answer questions about Egeria concepts, "
        "usage, and codebase details."
    )
    input_schema = RAGToolInput

    def __init__(self):
        """Initialize the tool."""
        super().__init__()
        self.rag_system = get_rag_system()
        self._emitter = Emitter.root().child(
            namespace=["tool", "rag", "SearchKnowledgeBase"]
        )

    def _create_emitter(self) -> Emitter:
        """Create the emitter for the tool."""
        return self._emitter

    def _run(self, input: RAGToolInput, options: Optional[Dict[str, Any]] = None) -> str:
        """
        Execute the tool.

        Args:
            input: Tool input parameters
            options: Execution options

        Returns:
            String response from the RAG system
        """
        try:
            result = self.rag_system.query(
                user_query=input.query,
                include_context=True
            )
            return result.get("response", "No relevant information found.")
        except Exception as e:
            return f"Error retrieving information: {str(e)}"
