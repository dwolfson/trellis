"""
Interactive response handler for query clarification and follow-up suggestions.

This module provides:
- Confidence-based clarification prompts
- Follow-up question suggestions
- Succinct answer formatting with options
- Interactive conversation flow
"""

from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
import yaml
from loguru import logger

from advisor.query_classifier import QueryClassification, QueryType


class ResponseMode(Enum):
    """Response formatting modes."""
    SUCCINCT_WITH_OPTIONS = "succinct_with_options"
    CLARIFICATION_REQUEST = "clarification_request"
    NO_CLEAR_MATCH = "no_clear_match"
    STANDARD = "standard"


@dataclass
class InteractiveResponse:
    """Structure for interactive response with follow-ups."""
    answer: str
    confidence: float
    response_mode: ResponseMode
    follow_up_options: List[str]
    clarification_needed: bool
    route_options: Optional[List[Dict[str, Any]]] = None


class InteractiveResponseHandler:
    """Handles interactive responses with clarification and follow-ups."""
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize interactive response handler.
        
        Args:
            config_path: Path to routing.yaml config file
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config" / "routing.yaml"
        
        self.config = self._load_config(config_path)
        self.confidence_thresholds = self.config.get('confidence_thresholds', {})
        self.clarification_settings = self.config.get('clarification', {})
        self.followup_templates = self.config.get('followup_templates', {})
        self.response_formats = self.config.get('response_formats', {})
        self.trigger_words = self.config.get('trigger_words', {})
        
        logger.info("Initialized InteractiveResponseHandler")
    
    def _load_config(self, config_path: Path) -> Dict[str, Any]:
        """Load configuration from YAML file."""
        if not config_path.exists():
            logger.warning(f"Config not found at {config_path}, using defaults")
            return self._get_default_config()
        
        try:
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
                return config or {}
        except Exception as e:
            logger.error(f"Error loading config: {e}, using defaults")
            return self._get_default_config()
    
    def _get_default_config(self) -> Dict[str, Any]:
        """Get default configuration."""
        return {
            'confidence_thresholds': {
                'high_confidence': 0.75,
                'medium_confidence': 0.50,
                'low_confidence': 0.30,
            },
            'clarification': {
                'enabled': True,
                'ask_when_confidence_below': 0.50,
                'ask_when_multiple_routes': True,
            },
            'followup_templates': {
                'general': [
                    "Would you like to see an example?",
                    "Do you want more details?",
                    "Should I show you related topics?",
                ]
            },
            'response_formats': {},
            'trigger_words': {}
        }
    
    def should_clarify(
        self,
        confidence: float,
        num_routes: int = 1
    ) -> bool:
        """
        Determine if clarification is needed.
        
        Args:
            confidence: Routing confidence score
            num_routes: Number of equally-matched routes
            
        Returns:
            True if clarification should be requested
        """
        if not self.clarification_settings.get('enabled', True):
            return False
        
        # Check confidence threshold
        threshold = self.clarification_settings.get('ask_when_confidence_below', 0.50)
        if confidence < threshold:
            return True
        
        # Check multiple routes
        if num_routes > 1 and self.clarification_settings.get('ask_when_multiple_routes', True):
            return True
        
        return False
    
    def get_follow_up_options(
        self,
        query_type: QueryType,
        topic: Optional[str] = None
    ) -> List[str]:
        """
        Get follow-up question options for a query type.
        
        Args:
            query_type: Type of query
            topic: Optional topic for context
            
        Returns:
            List of follow-up question options
        """
        # Map QueryType to template key
        type_key = query_type.value if hasattr(query_type, 'value') else str(query_type)
        
        # Get templates for this query type
        templates = self.followup_templates.get(type_key, self.followup_templates.get('general', []))
        
        return templates[:4]  # Return up to 4 options
    
    def format_succinct_response(
        self,
        answer: str,
        follow_up_options: List[str]
    ) -> str:
        """
        Format response in succinct style with follow-up options.
        
        Args:
            answer: Brief answer to the question
            follow_up_options: List of follow-up options
            
        Returns:
            Formatted response string
        """
        # Get template
        template = self.response_formats.get('succinct_with_options', {}).get('structure', '')
        
        if not template:
            # Fallback format
            formatted = f"## Quick Answer\n\n{answer}\n\n"
            formatted += "## What would you like to know more about?\n\n"
            for i, option in enumerate(follow_up_options, 1):
                formatted += f"{i}. {option}\n"
            formatted += "\nJust let me know the number or describe what you'd like!"
            return formatted
        
        # Build options list
        options_text = ""
        for i, option in enumerate(follow_up_options, 1):
            options_text += f"{i}. {option}\n"
        
        # Simple template replacement
        formatted = template.replace("[Brief, direct answer to the question - 2-3 sentences max]", answer)
        formatted = formatted.replace("[Option 1 - e.g., \"See a code example\"]", follow_up_options[0] if len(follow_up_options) > 0 else "See more details")
        formatted = formatted.replace("[Option 2 - e.g., \"View related commands\"]", follow_up_options[1] if len(follow_up_options) > 1 else "View examples")
        formatted = formatted.replace("[Option 3 - e.g., \"Read the full documentation\"]", follow_up_options[2] if len(follow_up_options) > 2 else "Read documentation")
        formatted = formatted.replace("[Option 4 - e.g., \"Understand the parameters\"]", follow_up_options[3] if len(follow_up_options) > 3 else "Learn more")
        
        return formatted
    
    def format_clarification_request(
        self,
        topic: str,
        route_options: List[Dict[str, str]]
    ) -> str:
        """
        Format clarification request when routing is ambiguous.
        
        Args:
            topic: Topic being asked about
            route_options: List of possible routing options
            
        Returns:
            Formatted clarification request
        """
        template = self.response_formats.get('clarification_request', {}).get('structure', '')
        
        if not template:
            # Fallback format
            formatted = f"I found information about '{topic}' in multiple areas. "
            formatted += "To give you the best answer, could you clarify what you're looking for?\n\n"
            for i, option in enumerate(route_options, 1):
                formatted += f"{i}. **{option['name']}** - {option['description']}\n"
            formatted += "\nWhich would be most helpful? (Choose a number or describe your need)"
            return formatted
        
        # Use template
        formatted = template.replace("{topic}", topic)
        return formatted
    
    def format_no_clear_match(self) -> str:
        """
        Format response when no clear routing match found.
        
        Returns:
            Formatted prompt for user clarification
        """
        template = self.response_formats.get('no_clear_match', {}).get('structure', '')
        
        if not template:
            # Fallback format
            return """I'm not quite sure what you're looking for. Could you help me understand by choosing one:

1. **Explain the concept** - What is it and how does it work?
2. **Show me code** - Give me implementation examples
3. **Guide me through it** - Step-by-step tutorial
4. **Troubleshoot** - Help me fix a problem

Or feel free to rephrase your question with more details!"""
        
        return template
    
    def get_trigger_word_hints(self, intent: str) -> Optional[str]:
        """
        Get trigger word hints for better query phrasing.
        
        Args:
            intent: Intent type (documentation, code, cli, examples)
            
        Returns:
            Hint string or None
        """
        if intent not in self.trigger_words:
            return None
        
        trigger_info = self.trigger_words[intent]
        keywords = trigger_info.get('keywords', [])
        example = trigger_info.get('example', '')
        
        hint = f"**Tip:** For {intent}, try using words like: {', '.join(keywords[:3])}\n"
        if example:
            hint += f"{example}"
        
        return hint
    
    def create_interactive_response(
        self,
        answer: str,
        classification: QueryClassification,
        confidence: float,
        collections_searched: List[str],
        topic: Optional[str] = None
    ) -> InteractiveResponse:
        """
        Create an interactive response with appropriate formatting.
        
        Args:
            answer: The answer text
            classification: Query classification result
            confidence: Routing confidence
            collections_searched: Collections that were searched
            topic: Optional topic extracted from query
            
        Returns:
            InteractiveResponse with formatted answer and options
        """
        # Determine if clarification is needed
        clarification_needed = self.should_clarify(confidence, len(collections_searched))
        
        # Get follow-up options
        follow_up_options = self.get_follow_up_options(classification.query_type, topic)
        
        # Determine response mode
        if clarification_needed and confidence < 0.30:
            response_mode = ResponseMode.NO_CLEAR_MATCH
            formatted_answer = self.format_no_clear_match()
        elif clarification_needed and len(collections_searched) > 1:
            response_mode = ResponseMode.CLARIFICATION_REQUEST
            route_options = [
                {"name": "Documentation", "description": "Conceptual explanation and architecture"},
                {"name": "Code Examples", "description": "Working Python/Java code"},
                {"name": "CLI Commands", "description": "Command-line usage"},
            ]
            formatted_answer = self.format_clarification_request(topic or "this topic", route_options)
        elif confidence >= 0.50:
            response_mode = ResponseMode.SUCCINCT_WITH_OPTIONS
            formatted_answer = self.format_succinct_response(answer, follow_up_options)
        else:
            response_mode = ResponseMode.STANDARD
            formatted_answer = answer
        
        return InteractiveResponse(
            answer=formatted_answer,
            confidence=confidence,
            response_mode=response_mode,
            follow_up_options=follow_up_options,
            clarification_needed=clarification_needed,
            route_options=None
        )


# Singleton instance
_handler_instance: Optional[InteractiveResponseHandler] = None


def get_interactive_handler() -> InteractiveResponseHandler:
    """Get singleton interactive response handler."""
    global _handler_instance
    if _handler_instance is None:
        _handler_instance = InteractiveResponseHandler()
    return _handler_instance


def create_interactive_response(
    answer: str,
    classification: QueryClassification,
    confidence: float,
    collections_searched: List[str],
    topic: Optional[str] = None
) -> InteractiveResponse:
    """
    Convenience function to create interactive response.
    
    Args:
        answer: The answer text
        classification: Query classification result
        confidence: Routing confidence
        collections_searched: Collections that were searched
        topic: Optional topic extracted from query
        
    Returns:
        InteractiveResponse with formatted answer and options
    """
    handler = get_interactive_handler()
    return handler.create_interactive_response(
        answer, classification, confidence, collections_searched, topic
    )