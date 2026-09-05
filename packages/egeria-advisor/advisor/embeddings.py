"""
Embedding generation for Egeria Advisor.

This module provides GPU-accelerated embedding generation using sentence-transformers.
Supports batch processing and caching for efficient vector generation.
"""

from dotenv import load_dotenv

# Must run before `sentence_transformers` (and the `huggingface_hub` it pulls in)
# is imported below — huggingface_hub reads HF_HUB_OFFLINE/TRANSFORMERS_OFFLINE/
# HF_HUB_DOWNLOAD_TIMEOUT from os.environ once, at import time, so .env values
# have to already be real process env vars by then.
load_dotenv()

import torch
from sentence_transformers import SentenceTransformer
from typing import List, Union, Optional
from loguru import logger
import numpy as np
from pathlib import Path
import json

from advisor.config import settings, get_full_config, ensure_writable_dir


class EmbeddingGenerator:
    """Generate embeddings using sentence-transformers with GPU acceleration."""

    def __init__(
        self,
        model_name: Optional[str] = None,
        device: Optional[str] = None,
        batch_size: Optional[int] = None,
        cache_dir: Optional[Path] = None
    ):
        """
        Initialize the embedding generator.

        Args:
            model_name: Name of the sentence-transformers model
            device: Device to use ('cuda', 'cpu', or 'auto')
            batch_size: Batch size for encoding
            cache_dir: Directory for caching embeddings
        """
        # Get embedding config
        full_config = get_full_config()
        embedding_config = full_config.get("embeddings")

        self.model_name = model_name or embedding_config.model
        self.batch_size = batch_size or embedding_config.batch_size
        self.cache_dir = cache_dir or Path(settings.advisor_cache_dir) / "embeddings"
        ensure_writable_dir(self.cache_dir, "ADVISOR_CACHE_DIR")

        # Determine device with universal GPU detection
        if device is None:
            device = embedding_config.device

        if device == "auto":
            self.device = self._detect_best_device()
        else:
            self.device = device

        logger.info(f"Initializing embedding model: {self.model_name}")
        logger.info(f"Using device: {self.device}")

        # Load model
        try:
            # Force CPU mode if specified to avoid GPU initialization issues
            if self.device == "cpu":
                import os
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
            
            self.model = SentenceTransformer(self.model_name, device=self.device)
            self.embedding_dim = self.model.get_sentence_embedding_dimension()
            logger.info(f"Model loaded successfully. Embedding dimension: {self.embedding_dim}")

            # Test GPU if using any GPU device
            if self.device in ["cuda", "mps"] or "hip" in self.device:
                self._test_gpu()

        except Exception as e:
            logger.error(f"Failed to load embedding model: {e}")
            # If GPU fails, try falling back to CPU
            if self.device != "cpu":
                logger.warning(f"{self.device.upper()} initialization failed, falling back to CPU")
                self.device = "cpu"
                import os
                os.environ["CUDA_VISIBLE_DEVICES"] = ""
                try:
                    self.model = SentenceTransformer(self.model_name, device="cpu")
                    self.embedding_dim = self.model.get_sentence_embedding_dimension()
                    logger.info(f"Model loaded successfully on CPU. Embedding dimension: {self.embedding_dim}")
                except Exception as cpu_error:
                    logger.error(f"Failed to load embedding model on CPU: {cpu_error}")
                    raise
            else:
                raise

    def _detect_best_device(self) -> str:
        """
        Detect the best available device for acceleration.
        
        Checks in priority order:
        1. NVIDIA CUDA
        2. AMD ROCm
        3. Apple Metal (MPS)
        4. CPU (fallback)
        
        Returns:
            Device string: "cuda", "mps", "cpu", or ROCm device
        """
        # Check for NVIDIA CUDA or AMD ROCm — PyTorch's ROCm builds report AMD GPUs
        # through the same torch.cuda.* API (there is no separate torch.hip namespace
        # to check in current PyTorch), so both vendors are detected here;
        # torch.version.hip is only set on ROCm builds and distinguishes which one it
        # actually is, for logging purposes only.
        if torch.cuda.is_available():
            device_name = torch.cuda.get_device_name(0)
            if getattr(torch.version, "hip", None):
                logger.info(f"✓ AMD ROCm available: {device_name} (ROCm {torch.version.hip})")
            else:
                logger.info(f"✓ NVIDIA CUDA available: {device_name}")
            return "cuda"
        
        # Check for Apple Metal (MPS)
        try:
            if hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
                logger.info("✓ Apple Metal (MPS) available")
                return "mps"
        except Exception as e:
            logger.debug(f"MPS check failed: {e}")
        
        # Fallback to CPU
        logger.info("No GPU acceleration available, using CPU")
        return "cpu"

    def _test_gpu(self):
        """Test GPU functionality with a sample encoding."""
        device_type = "GPU" if self.device in ["cuda", "mps"] or "hip" in self.device else self.device.upper()
        if self.device in ["cuda", "mps"] or "hip" in self.device:
            try:
                # Test encoding with the actual device being used
                self.model.encode("test", device=self.device)
                logger.info(f"✓ {device_type} encoding verified successfully")
            except Exception as e:
                logger.warning(f"{device_type} test failed ({e}), falling back to CPU")
                self.device = "cpu"
                self.model = SentenceTransformer(self.model_name, device="cpu")

    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text.

        Args:
            text: Text to encode

        Returns:
            Embedding as numpy array
        """
        return self.encode(text, convert_to_numpy=True)[0]

    def encode(
        self,
        texts: Union[str, List[str]],
        normalize: bool = True,
        show_progress: bool = False,
        convert_to_numpy: bool = True
    ) -> Union[np.ndarray, torch.Tensor]:
        """
        Encode text(s) into embeddings.

        Args:
            texts: Single text or list of texts to encode
            normalize: Whether to normalize embeddings to unit length
            show_progress: Show progress bar for batch encoding
            convert_to_numpy: Convert output to numpy array

        Returns:
            Embeddings as numpy array or torch tensor
        """
        if isinstance(texts, str):
            texts = [texts]

        logger.debug(f"Encoding {len(texts)} texts")

        try:
            embeddings = self.model.encode(
                texts,
                batch_size=self.batch_size,
                show_progress_bar=show_progress,
                normalize_embeddings=normalize,
                convert_to_numpy=convert_to_numpy,
                device=self.device
            )

            logger.debug(f"Generated embeddings shape: {embeddings.shape}")
            return embeddings

        except Exception as e:
            if self.device == "cuda":
                logger.warning(f"Encoding failed on GPU ({e}), retrying on CPU...")
                # Switch to CPU for this and future calls
                self.device = "cpu"
                self.model.to("cpu")
                return self.model.encode(
                    texts,
                    batch_size=self.batch_size,
                    show_progress_bar=show_progress,
                    normalize_embeddings=normalize,
                    convert_to_numpy=convert_to_numpy,
                    device="cpu"
                )
            else:
                logger.error(f"Failed to encode texts: {e}")
                raise

    def encode_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress: bool = True
    ) -> np.ndarray:
        """
        Encode a large batch of texts efficiently.

        Args:
            texts: List of texts to encode
            batch_size: Override default batch size
            show_progress: Show progress bar

        Returns:
            Numpy array of embeddings
        """
        batch_size = batch_size or self.batch_size

        logger.info(f"Encoding {len(texts)} texts in batches of {batch_size}")

        return self.encode(
            texts,
            normalize=True,
            show_progress=show_progress,
            convert_to_numpy=True
        )

    def encode_with_cache(
        self,
        texts: List[str],
        cache_key: str,
        force_refresh: bool = False
    ) -> np.ndarray:
        """
        Encode texts with caching support.

        Args:
            texts: List of texts to encode
            cache_key: Unique key for caching
            force_refresh: Force re-encoding even if cached

        Returns:
            Numpy array of embeddings
        """
        cache_file = self.cache_dir / f"{cache_key}.npy"
        metadata_file = self.cache_dir / f"{cache_key}_meta.json"

        # Check cache
        if not force_refresh and cache_file.exists():
            logger.info(f"Loading embeddings from cache: {cache_key}")
            try:
                embeddings = np.load(cache_file)

                # Verify cache metadata
                if metadata_file.exists():
                    with open(metadata_file) as f:
                        meta = json.load(f)
                        if meta.get("count") == len(texts) and meta.get("model") == self.model_name:
                            logger.info(f"✓ Cache valid, loaded {len(embeddings)} embeddings")
                            return embeddings

                logger.warning("Cache metadata mismatch, re-encoding")
            except Exception as e:
                logger.warning(f"Failed to load cache: {e}")

        # Generate embeddings
        logger.info(f"Generating embeddings for cache key: {cache_key}")
        embeddings = self.encode_batch(texts, show_progress=True)

        # Save to cache
        try:
            np.save(cache_file, embeddings)

            metadata = {
                "count": len(texts),
                "model": self.model_name,
                "dimension": self.embedding_dim,
                "device": self.device
            }
            with open(metadata_file, "w") as f:
                json.dump(metadata, f, indent=2)

            logger.info(f"✓ Saved embeddings to cache: {cache_key}")
        except Exception as e:
            logger.warning(f"Failed to save cache: {e}")

        return embeddings

    def get_embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return self.embedding_dim

    def get_model_info(self) -> dict:
        """Get information about the loaded model."""
        return {
            "model_name": self.model_name,
            "embedding_dim": self.embedding_dim,
            "device": self.device,
            "batch_size": self.batch_size,
            "max_seq_length": self.model.max_seq_length
        }


# Global instance for reuse
_embedding_generator: Optional[Union[EmbeddingGenerator, 'ONNXEmbeddingGenerator']] = None


def get_embedding_generator() -> Union[EmbeddingGenerator, 'ONNXEmbeddingGenerator']:
    """
    Get or create the global embedding generator instance.
    
    Automatically selects backend based on configuration:
    - backend='pytorch': Use PyTorch sentence-transformers (default)
    - backend='onnx': Use ONNX Runtime for 2-3x speedup
    
    Returns
    -------
    EmbeddingGenerator or ONNXEmbeddingGenerator
        Embedding generator instance
    """
    global _embedding_generator

    if _embedding_generator is None:
        # Get configuration
        full_config = get_full_config()
        embedding_config = full_config.get("embeddings")
        backend = getattr(embedding_config, "backend", "pytorch")
        
        if backend == "onnx":
            # Use ONNX backend
            try:
                from advisor.embeddings_onnx import ONNXEmbeddingGenerator
                
                onnx_config = getattr(embedding_config, "onnx", {})
                if isinstance(onnx_config, dict):
                    onnx_model_path = onnx_config.get("model_path", "models/all-MiniLM-L6-v2.optimized.onnx")
                    providers = onnx_config.get("providers")
                else:
                    onnx_model_path = getattr(onnx_config, "model_path", "models/all-MiniLM-L6-v2.optimized.onnx")
                    providers = getattr(onnx_config, "providers", None)
                
                logger.info(f"Using ONNX backend: {onnx_model_path}")
                _embedding_generator = ONNXEmbeddingGenerator(
                    onnx_model_path=onnx_model_path,
                    tokenizer_name=embedding_config.model,
                    batch_size=embedding_config.batch_size,
                    max_length=getattr(embedding_config, "max_length", 512),
                    providers=providers
                )
            except Exception as e:
                logger.warning(f"Failed to load ONNX backend: {e}")
                logger.info("Falling back to PyTorch backend")
                _embedding_generator = EmbeddingGenerator()
        else:
            # Use PyTorch backend (default)
            logger.info("Using PyTorch backend")
            _embedding_generator = EmbeddingGenerator()

    return _embedding_generator


def encode_text(text: Union[str, List[str]], **kwargs) -> np.ndarray:
    """
    Convenience function to encode text using the global generator.

    Args:
        text: Text or list of texts to encode
        **kwargs: Additional arguments passed to encode()

    Returns:
        Numpy array of embeddings
    """
    generator = get_embedding_generator()
    return generator.encode(text, **kwargs)
