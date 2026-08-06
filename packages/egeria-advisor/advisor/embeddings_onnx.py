"""
ONNX-based embedding generation for improved performance.

This module provides ONNX Runtime-based embedding generation with:
- 2-3x faster inference than PyTorch
- 50% lower memory footprint
- Cross-platform acceleration (NVIDIA, AMD, Apple Silicon)
- Automatic execution provider selection
"""

import numpy as np
from pathlib import Path
from typing import List, Union, Optional, Dict, Any
from loguru import logger
import onnxruntime as ort
from transformers import AutoTokenizer


class ONNXEmbeddingGenerator:
    """Generate embeddings using ONNX Runtime for optimized inference."""
    
    def __init__(
        self,
        onnx_model_path: Union[str, Path],
        tokenizer_name: str = "sentence-transformers/all-MiniLM-L6-v2",
        batch_size: int = 32,
        max_length: int = 512,
        providers: Optional[List[str]] = None
    ):
        """
        Initialize ONNX embedding generator.
        
        Parameters
        ----------
        onnx_model_path : str or Path
            Path to ONNX model file
        tokenizer_name : str
            HuggingFace tokenizer name
        batch_size : int
            Batch size for encoding
        max_length : int
            Maximum sequence length
        providers : list[str], optional
            ONNX execution providers (auto-detected if None)
        """
        self.onnx_model_path = Path(onnx_model_path)
        self.batch_size = batch_size
        self.max_length = max_length
        
        if not self.onnx_model_path.exists():
            raise FileNotFoundError(f"ONNX model not found: {self.onnx_model_path}")
        
        # Load tokenizer
        logger.info(f"Loading tokenizer: {tokenizer_name}")
        self.tokenizer = AutoTokenizer.from_pretrained(tokenizer_name)
        
        # Determine execution providers
        if providers is None:
            providers = self._get_best_providers()
        
        self.providers = providers
        logger.info(f"Using execution providers: {providers}")
        
        # Create ONNX session with optimizations
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        sess_options.intra_op_num_threads = 4
        sess_options.inter_op_num_threads = 4
        
        logger.info(f"Loading ONNX model: {self.onnx_model_path}")
        self.session = ort.InferenceSession(
            str(self.onnx_model_path),
            sess_options,
            providers=providers
        )
        
        # Get model info
        self.embedding_dim = self._get_embedding_dim()
        logger.info(f"Model loaded. Embedding dimension: {self.embedding_dim}")
        
        # Test inference
        self._test_inference()
    
    def _get_best_providers(self) -> List[str]:
        """
        Auto-detect best execution providers.
        
        Priority order:
        1. TensorRT (NVIDIA)
        2. CUDA (NVIDIA)
        3. MIGraphX (AMD)
        4. CoreML (Apple Silicon)
        5. DirectML (Windows GPU)
        6. CPU (fallback)
        
        Returns
        -------
        list[str]
            Ordered list of execution providers
        """
        available = ort.get_available_providers()
        logger.info(f"Available ONNX providers: {available}")
        
        # Priority order
        priority = [
            "TensorrtExecutionProvider",  # NVIDIA TensorRT
            "CUDAExecutionProvider",      # NVIDIA CUDA
            "MIGraphXExecutionProvider",  # AMD ROCm
            "CoreMLExecutionProvider",    # Apple Silicon
            "DirectMLExecutionProvider",  # Windows GPU
            "CPUExecutionProvider"        # CPU fallback
        ]
        
        # Select providers in priority order
        selected = []
        for provider in priority:
            if provider in available:
                selected.append(provider)
                if provider != "CPUExecutionProvider":
                    logger.info(f"✓ GPU acceleration available: {provider}")
                    break  # Use first GPU provider found
        
        # Always add CPU as fallback
        if "CPUExecutionProvider" not in selected:
            selected.append("CPUExecutionProvider")
        
        return selected
    
    def _get_embedding_dim(self) -> int:
        """Get embedding dimension from model output."""
        # Run dummy inference to get output shape
        dummy_input = self.tokenizer(
            "test",
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=self.max_length
        )
        
        outputs = self.session.run(None, {
            "input_ids": dummy_input["input_ids"],
            "attention_mask": dummy_input["attention_mask"]
        })
        
        # Output shape: (batch_size, seq_length, hidden_size)
        return outputs[0].shape[-1]
    
    def _test_inference(self):
        """Test inference to verify model works."""
        try:
            test_embedding = self.encode("test sentence")
            logger.info(f"✓ Inference test successful. Shape: {test_embedding.shape}")
        except Exception as e:
            logger.error(f"Inference test failed: {e}")
            raise
    
    def encode(
        self,
        texts: Union[str, List[str]],
        normalize: bool = True,
        show_progress: bool = False,
        convert_to_numpy: bool = True
    ) -> np.ndarray:
        """
        Encode text(s) into embeddings.
        
        Parameters
        ----------
        texts : str or list[str]
            Text or list of texts to encode
        normalize : bool
            Normalize embeddings to unit length
        show_progress : bool
            Show progress bar (not implemented for ONNX)
        convert_to_numpy : bool
            Always returns numpy array
            
        Returns
        -------
        np.ndarray
            Embeddings array of shape (n_texts, embedding_dim)
        """
        if isinstance(texts, str):
            texts = [texts]
        
        logger.debug(f"Encoding {len(texts)} texts with ONNX")
        
        # Process in batches
        all_embeddings = []
        
        for i in range(0, len(texts), self.batch_size):
            batch = texts[i:i + self.batch_size]
            batch_embeddings = self._encode_batch(batch, normalize)
            all_embeddings.append(batch_embeddings)
        
        # Concatenate all batches
        embeddings = np.vstack(all_embeddings)
        
        logger.debug(f"Generated embeddings shape: {embeddings.shape}")
        return embeddings
    
    def _encode_batch(self, texts: List[str], normalize: bool = True) -> np.ndarray:
        """
        Encode a single batch of texts.
        
        Parameters
        ----------
        texts : list[str]
            Batch of texts
        normalize : bool
            Normalize embeddings
            
        Returns
        -------
        np.ndarray
            Batch embeddings
        """
        # Tokenize
        inputs = self.tokenizer(
            texts,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=self.max_length
        )
        
        # Run inference
        outputs = self.session.run(None, {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"]
        })
        
        # Get last hidden state
        last_hidden_state = outputs[0]  # Shape: (batch_size, seq_length, hidden_size)
        attention_mask = inputs["attention_mask"]
        
        # Mean pooling
        embeddings = self._mean_pooling(last_hidden_state, attention_mask)
        
        # Normalize if requested
        if normalize:
            embeddings = self._normalize(embeddings)
        
        return embeddings
    
    def _mean_pooling(
        self,
        last_hidden_state: np.ndarray,
        attention_mask: np.ndarray
    ) -> np.ndarray:
        """
        Perform mean pooling on token embeddings.
        
        Parameters
        ----------
        last_hidden_state : np.ndarray
            Token embeddings (batch_size, seq_length, hidden_size)
        attention_mask : np.ndarray
            Attention mask (batch_size, seq_length)
            
        Returns
        -------
        np.ndarray
            Pooled embeddings (batch_size, hidden_size)
        """
        # Expand attention mask for broadcasting
        attention_mask_expanded = np.expand_dims(attention_mask, -1)
        
        # Sum embeddings (weighted by attention mask)
        sum_embeddings = np.sum(last_hidden_state * attention_mask_expanded, axis=1)
        
        # Sum attention mask
        sum_mask = np.sum(attention_mask_expanded, axis=1)
        sum_mask = np.clip(sum_mask, a_min=1e-9, a_max=None)  # Avoid division by zero
        
        # Mean pooling
        mean_embeddings = sum_embeddings / sum_mask
        
        return mean_embeddings
    
    def _normalize(self, embeddings: np.ndarray) -> np.ndarray:
        """
        Normalize embeddings to unit length.
        
        Parameters
        ----------
        embeddings : np.ndarray
            Embeddings to normalize
            
        Returns
        -------
        np.ndarray
            Normalized embeddings
        """
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms = np.clip(norms, a_min=1e-9, a_max=None)  # Avoid division by zero
        return embeddings / norms
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for a single text.
        
        Parameters
        ----------
        text : str
            Text to encode
            
        Returns
        -------
        np.ndarray
            Embedding vector
        """
        return self.encode(text)[0]
    
    def encode_batch(
        self,
        texts: List[str],
        batch_size: Optional[int] = None,
        show_progress: bool = True
    ) -> np.ndarray:
        """
        Encode a large batch of texts efficiently.
        
        Parameters
        ----------
        texts : list[str]
            List of texts to encode
        batch_size : int, optional
            Override default batch size
        show_progress : bool
            Show progress (not implemented)
            
        Returns
        -------
        np.ndarray
            Embeddings array
        """
        if batch_size is not None:
            old_batch_size = self.batch_size
            self.batch_size = batch_size
            embeddings = self.encode(texts, show_progress=show_progress)
            self.batch_size = old_batch_size
            return embeddings
        else:
            return self.encode(texts, show_progress=show_progress)
    
    def get_embedding_dim(self) -> int:
        """Get the embedding dimension."""
        return self.embedding_dim
    
    def get_model_info(self) -> Dict[str, Any]:
        """Get information about the loaded model."""
        return {
            "model_path": str(self.onnx_model_path),
            "embedding_dim": self.embedding_dim,
            "providers": self.providers,
            "batch_size": self.batch_size,
            "max_length": self.max_length,
            "backend": "onnx"
        }


# Global instance for reuse
_onnx_generator: Optional[ONNXEmbeddingGenerator] = None


def get_onnx_embedding_generator(
    onnx_model_path: Optional[Union[str, Path]] = None
) -> ONNXEmbeddingGenerator:
    """
    Get or create the global ONNX embedding generator instance.
    
    Parameters
    ----------
    onnx_model_path : str or Path, optional
        Path to ONNX model (default: models/all-MiniLM-L6-v2.onnx)
        
    Returns
    -------
    ONNXEmbeddingGenerator
        Global ONNX generator instance
    """
    global _onnx_generator
    
    if _onnx_generator is None:
        if onnx_model_path is None:
            onnx_model_path = Path("models/all-MiniLM-L6-v2.onnx")
        
        _onnx_generator = ONNXEmbeddingGenerator(onnx_model_path)
    
    return _onnx_generator