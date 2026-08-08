"""
BeeAI Framework Backend Configuration.

This module configures the LLM backend for BeeAI agents, specifically
integrating with Ollama using the framework's native model loading capabilities.
"""

from typing import Optional
from loguru import logger
from beeai_framework.backend.chat import ChatModel

class BeeAIBackend:
    """Backend factory for BeeAI."""

    @staticmethod
    def get_chat_model(model_name: str, temperature: float = 0.7) -> Optional[ChatModel]:
        """
        Get a configured ChatModel.

        Args:
            model_name: Name of the model (e.g., llama3.1:8b)
            temperature: Temperature setting

        Returns:
            ChatModel instance or None if loading fails
        """
        # BeeAI supports loading Ollama models via "ollama:model_name" format.
        # We ensure the model name is preserved (e.g., "llama3.1:8b")

        provider_model_id = f"ollama:{model_name}"

        try:
            model = ChatModel.from_name(provider_model_id)
            return model
        except Exception as e:
            logger.error(f"Failed to load model {provider_model_id}: {e}")
            return None
