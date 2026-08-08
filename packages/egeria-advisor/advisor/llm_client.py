"""
LLM client wrapper for Ollama integration.

This module provides a simple interface to interact with Ollama models
for text generation with the Egeria Advisor.
"""

import requests
import threading
from typing import Optional, Dict, Any, List, Iterator, Callable
from loguru import logger
import json
import time
import asyncio
import aiohttp

# Thread-local streaming hook.  When query_stream() runs _process_query in a
# worker thread it sets _stream_local.on_token to a callable(str).  Any
# OllamaClient.generate() call on that thread will then stream tokens via
# stream_generate() and forward each token to the callback, returning the
# assembled full text so callers stay unchanged.
_stream_local: threading.local = threading.local()

from advisor.config import settings, get_full_config
from advisor.mlflow_tracking import get_mlflow_tracker
from advisor.metrics_collector import get_metrics_collector, QueryMetric


class OllamaClient:
    """Client for interacting with Ollama LLM API."""
    
    def __init__(
        self,
        base_url: Optional[str] = None,
        model: Optional[str] = None,
        timeout: int = 180
    ):
        """
        Initialize Ollama client.
        
        Args:
            base_url: Ollama API base URL
            model: Default model to use
            timeout: Request timeout in seconds (default 180 for slow CPU inference)
        """
        config = get_full_config()
        llm_config = config.get("llm")
        
        self.base_url = base_url or llm_config.base_url
        self.default_model = model or llm_config.models.query
        self.timeout = timeout or llm_config.parameters.timeout
        
        # Get default parameters
        self.default_params = {
            "temperature": llm_config.parameters.temperature,
            "top_p": llm_config.parameters.top_p,
            "top_k": llm_config.parameters.top_k,
            "repeat_penalty": llm_config.parameters.repeat_penalty
        }
        
        # Initialize monitoring
        # Note: MLflow tracking disabled in LLM client due to context manager conflicts
        # Tracking should be done at agent/CLI layer instead
        self.mlflow_tracker = None  # Disabled - causes "generator didn't stop after throw()"
        self.metrics_collector = get_metrics_collector()
        
        logger.info(f"Initialized Ollama client: {self.base_url}")
        logger.info(f"Default model: {self.default_model}")
    
    def is_available(self) -> bool:
        """Check if Ollama service is available."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"Ollama not available: {e}")
            return False
    
    def list_models(self) -> List[str]:
        """List available models."""
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=5)
            response.raise_for_status()
            data = response.json()
            models = [model["name"] for model in data.get("models", [])]
            logger.info(f"Available models: {models}")
            return models
        except Exception as e:
            logger.error(f"Failed to list models: {e}")
            return []
    
    def generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> str:
        """
        Generate text completion.
        
        Args:
            prompt: Input prompt
            model: Model to use (defaults to configured model)
            system: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            **kwargs: Additional parameters
            
        Returns:
            Generated text
        """
        model = model or self.default_model
        start_time = time.time()
        success = True
        error_message = None
        generated_text = ""
        
        # Build request payload
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": stream,
            "options": {
                "temperature": temperature or self.default_params["temperature"],
                "top_p": self.default_params["top_p"],
                "top_k": self.default_params["top_k"],
                "repeat_penalty": self.default_params["repeat_penalty"]
            }
        }
        
        if system:
            payload["system"] = system
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        # Add any additional options
        payload["options"].update(kwargs)
        
        logger.debug(f"Generating with model: {model}")
        logger.debug(f"Prompt length: {len(prompt)} chars")
        
        try:
            # If a thread-local streaming callback is installed (set by
            # RAGSystem.query_stream), stream tokens to it and return the
            # assembled text so all callers remain unchanged.
            _on_token: Optional[Callable[[str], None]] = getattr(_stream_local, "on_token", None)
            if _on_token is not None:
                full_response = ""
                for token in self.stream_generate(
                    prompt,
                    model=model,
                    system=system,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    **kwargs,
                ):
                    _on_token(token)
                    full_response += token
                generated_text = full_response
                generation_time_ms = (time.time() - start_time) * 1000
                logger.debug(f"Streamed {len(generated_text)} chars in {generation_time_ms:.0f}ms")
                return generated_text

            # MLflow tracking removed - causes context manager conflicts
            # Tracking should be done at agent/CLI layer
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()

            if stream:
                # Handle streaming response
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        if "response" in data:
                            full_response += data["response"]
                generated_text = full_response
            else:
                # Handle non-streaming response
                data = response.json()
                generated_text = data.get("response", "")
            
            # Log timing info
            generation_time_ms = (time.time() - start_time) * 1000
            logger.debug(f"Generated {len(generated_text)} chars in {generation_time_ms:.0f}ms")
            return generated_text
                
        except requests.exceptions.Timeout:
            success = False
            error_message = f"Request timed out after {self.timeout}s"
            logger.error(error_message)
            raise
        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(f"Generation failed: {e}")
            raise
            # MLflow tracking and metrics_collector removed - causes redundancy and conflicts
            # Tracking should be done at RAGSystem layer
    def stream_generate(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield response tokens one at a time from Ollama's streaming API."""
        model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": {
                "temperature": temperature or self.default_params["temperature"],
                "top_p": self.default_params["top_p"],
                "top_k": self.default_params["top_k"],
                "repeat_penalty": self.default_params["repeat_penalty"],
            },
        }
        if system:
            payload["system"] = system
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        payload["options"].update(kwargs)

        response = requests.post(
            f"{self.base_url}/api/generate",
            json=payload,
            stream=True,
            timeout=self.timeout,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                token = data.get("response", "")
                if token:
                    yield token
                if data.get("done"):
                    break

    def stream_chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs,
    ) -> Iterator[str]:
        """Yield chat response tokens one at a time from Ollama's streaming API."""
        model = model or self.default_model
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {
                "temperature": temperature or self.default_params["temperature"],
                "top_p": self.default_params["top_p"],
                "top_k": self.default_params["top_k"],
                "repeat_penalty": self.default_params["repeat_penalty"],
            },
        }
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        payload["options"].update(kwargs)

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            stream=True,
            timeout=self.timeout,
        )
        response.raise_for_status()
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                token = (data.get("message") or {}).get("content", "")
                if token:
                    yield token
                if data.get("done"):
                    break

    async def generate_async(
        self,
        prompt: str,
        model: Optional[str] = None,
        system: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """
        Generate text completion asynchronously.
        
        Args:
            prompt: Input prompt
            model: Model to use (defaults to configured model)
            system: System prompt
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            **kwargs: Additional parameters
            
        Returns:
            Generated text
        """
        model = model or self.default_model
        start_time = time.time()
        
        # Build request payload
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,  # Non-streaming for simplicity
            "options": {
                "temperature": temperature or self.default_params["temperature"],
                "top_p": self.default_params["top_p"],
                "top_k": self.default_params["top_k"],
                "repeat_penalty": self.default_params["repeat_penalty"]
            }
        }
        
        if system:
            payload["system"] = system
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        # Add any additional options
        payload["options"].update(kwargs)
        
        logger.debug(f"Generating async with model: {model}")
        logger.debug(f"Prompt length: {len(prompt)} chars")
        
        try:
            # Use aiohttp for async HTTP requests
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=payload
                ) as response:
                    response.raise_for_status()
                    data = await response.json()
                    generated_text = data.get("response", "")
            
            # Log timing info
            generation_time_ms = (time.time() - start_time) * 1000
            logger.debug(f"Generated {len(generated_text)} chars in {generation_time_ms:.0f}ms (async)")
            return generated_text
                
        except asyncio.TimeoutError:
            error_message = f"Request timed out after {self.timeout}s"
            logger.error(error_message)
            raise
        except Exception as e:
            logger.error(f"Async generation failed: {e}")
            raise
    
            pass
    
    def chat(
        self,
        messages: List[Dict[str, str]],
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        stream: bool = False,
        **kwargs
    ) -> str:
        """
        Chat completion with message history.
        
        Args:
            messages: List of message dicts with 'role' and 'content'
            model: Model to use
            temperature: Sampling temperature
            max_tokens: Maximum tokens to generate
            stream: Whether to stream the response
            **kwargs: Additional parameters
            
        Returns:
            Generated response
        """
        model = model or self.default_model
        start_time = time.time()
        success = True
        error_message = None
        response_text = ""
        
        payload = {
            "model": model,
            "messages": messages,
            "stream": stream,
            "options": {
                "temperature": temperature or self.default_params["temperature"],
                "top_p": self.default_params["top_p"],
                "top_k": self.default_params["top_k"],
                "repeat_penalty": self.default_params["repeat_penalty"]
            }
        }
        
        if max_tokens:
            payload["options"]["num_predict"] = max_tokens
        
        payload["options"].update(kwargs)
        
        # Calculate total message length
        total_message_length = sum(len(msg.get("content", "")) for msg in messages)
        
        logger.debug(f"Chat with {len(messages)} messages")
        
        try:
            # MLflow tracking removed - causes context manager conflicts
            # Tracking should be done at agent/CLI layer
            response = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=self.timeout
            )
            response.raise_for_status()
            
            if stream:
                full_response = ""
                for line in response.iter_lines():
                    if line:
                        data = json.loads(line)
                        if "message" in data and "content" in data["message"]:
                            full_response += data["message"]["content"]
                response_text = full_response
            else:
                data = response.json()
                message = data.get("message", {})
                response_text = message.get("content", "")
            
            # Log timing info
            generation_time_ms = (time.time() - start_time) * 1000
            logger.debug(f"Generated {len(response_text)} chars in {generation_time_ms:.0f}ms")
            return response_text
                
        except Exception as e:
            success = False
            error_message = str(e)
            logger.error(f"Chat failed: {e}")
            raise
        finally:
            # Metrics recording removed - done at RAGSystem layer
            pass


# Global client instances
_ollama_client: Optional[OllamaClient] = None
_planning_llm_model: Optional[str] = None


def get_ollama_client() -> OllamaClient:
    """Get or create the global Ollama client instance (query model)."""
    global _ollama_client
    if _ollama_client is None:
        _ollama_client = OllamaClient()
    return _ollama_client


def get_planning_llm() -> OllamaClient:
    """
    Return an OllamaClient pre-configured with the planning model.

    The planning model (config: llm.models.planning) is used for narrative
    generation, refinement, and change application in GovernancePlanAgent and
    PlanElicitor.  Falls back to the default query model if not configured.
    """
    from advisor.config import get_full_config
    cfg = get_full_config()
    model = getattr(cfg.get("llm").models, "planning", None) or cfg.get("llm").models.query

    client = get_ollama_client()
    # Return a lightweight wrapper that overrides the default model
    return _ModelOverrideClient(client, model)


class _ModelOverrideClient:
    """Thin wrapper that injects a specific model into every generate() call."""

    def __init__(self, base: OllamaClient, model: str) -> None:
        self._base  = base
        self._model = model

    def generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> str:
        return self._base.generate(prompt, model=model or self._model, **kwargs)

    def stream_generate(self, prompt: str, model: Optional[str] = None, **kwargs) -> Iterator[str]:
        return self._base.stream_generate(prompt, model=model or self._model, **kwargs)

    def stream_chat(self, messages: List[Dict[str, str]], model: Optional[str] = None, **kwargs) -> Iterator[str]:
        return self._base.stream_chat(messages, model=model or self._model, **kwargs)

    def __getattr__(self, name: str):
        return getattr(self._base, name)