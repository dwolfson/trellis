"""
CLI Command Agent Integration Module.

This module integrates the CLI Command Agent into the main query routing system,
enabling automatic detection and routing of CLI command queries.
"""

from typing import Dict, Any, Optional
from loguru import logger

from advisor.agents.cli_command_agent import CLICommandAgent
from advisor.query_classifier import QueryClassifier, QueryTopic


class CLIQueryRouter:
    """Routes CLI-related queries to the CLI Command Agent."""
    
    def __init__(self):
        """Initialize CLI query router."""
        self.cli_agent = CLICommandAgent()
        self.classifier = QueryClassifier()
        logger.info("Initialized CLI Query Router")
    
    def should_use_cli_agent(self, query: str, classification: Optional[Any] = None) -> bool:
        """
        Determine if query should be routed to CLI Command Agent.
        
        Args:
            query: User query
            classification: Optional pre-computed classification
            
        Returns:
            True if query should use CLI agent
        """
        # First check if agent itself can handle it
        if self.cli_agent.can_handle(query):
            return True
        
        # Check classification if provided
        if classification:
            if QueryTopic.CLI in classification.topics:
                return True
        
        # Additional CLI-specific patterns
        cli_indicators = [
            'command', 'hey_egeria', 'hey-egeria', 'dr_egeria', 'dr-egeria',
            'cli', 'terminal', 'run', 'execute',
            'create_glossary', 'list_', 'monitor_', 'delete_',
            'parameter', 'option', 'flag', '--'
        ]
        
        query_lower = query.lower()
        return any(indicator in query_lower for indicator in cli_indicators)
    
    def route_query(self, query: str, context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Route query to CLI Command Agent.
        
        Args:
            query: User query
            context: Optional context
            
        Returns:
            Response dictionary from CLI agent
        """
        logger.info(f"Routing query to CLI Command Agent: {query}")
        
        try:
            # Use the agent's process method for standard response format
            response = self.cli_agent.process(query, context)
            
            # Add routing metadata
            response['routed_to'] = 'cli_command_agent'
            response['agent_type'] = 'specialized'
            
            return response
            
        except Exception as e:
            logger.error(f"Error routing to CLI agent: {e}")
            return {
                'agent': 'cli_command',
                'response': f"Error processing CLI command query: {e}",
                'sources': [],
                'confidence': 0.0,
                'error': str(e)
            }


def integrate_cli_agent_with_rag(rag_system):
    """
    Integrate CLI Command Agent with RAG system.
    
    This function adds CLI command detection to the RAG query processing pipeline.
    
    Args:
        rag_system: RAG system instance to integrate with
    """
    logger.info("Integrating CLI Command Agent with RAG system")
    
    # Store original query method
    original_query = rag_system.query
    cli_router = CLIQueryRouter()
    
    def enhanced_query(user_query: str, **kwargs):
        """Enhanced query method with CLI detection."""
        
        # Check if this is a CLI command query
        if cli_router.should_use_cli_agent(user_query):
            logger.info("Detected CLI command query, routing to CLI agent")
            
            # Get response from CLI agent
            cli_response = cli_router.route_query(user_query)
            
            # Convert to RAG system response format if needed
            if 'result' not in cli_response:
                cli_response['result'] = cli_response.get('response', '')
            
            return cli_response
        
        # Otherwise use normal RAG processing
        return original_query(user_query, **kwargs)
    
    # Replace query method
    rag_system.query = enhanced_query
    logger.info("CLI Command Agent integration complete")


# Singleton instance
_cli_router: Optional[CLIQueryRouter] = None


def get_cli_router() -> CLIQueryRouter:
    """Get or create CLI query router singleton."""
    global _cli_router
    if _cli_router is None:
        _cli_router = CLIQueryRouter()
    return _cli_router