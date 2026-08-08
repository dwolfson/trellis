"""
Unit tests for ONNX embedding generation.

Tests the ONNXEmbeddingGenerator class and backend selection.
"""

import pytest
import numpy as np
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import advisor.embeddings_onnx



@pytest.fixture(autouse=True)
def mock_onnx_internal_methods():
    """Mock internal ONNX methods to simplify test setups."""
    with patch('advisor.embeddings_onnx.ONNXEmbeddingGenerator._test_inference'), \
         patch('advisor.embeddings_onnx.ONNXEmbeddingGenerator._get_embedding_dim', return_value=384):
        yield


class TestONNXEmbeddingGenerator:
    """Test ONNX embedding generator."""
    
    @pytest.fixture
    def mock_onnx_model(self, tmp_path):
        """Create a mock ONNX model file."""
        model_path = tmp_path / "test_model.onnx"
        model_path.touch()
        return model_path
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock ONNX Runtime session."""
        session = Mock()
        # Mock output: (batch_size, seq_length, hidden_size)
        session.run.return_value = [np.random.randn(1, 3, 384)]
        return session
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_initialization(self, mock_tokenizer, mock_session_class, mock_onnx_model):
        """Test ONNX generator initialization."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        # Setup mocks
        mock_session_class.return_value = Mock()
        mock_session_class.return_value.run.return_value = [np.random.randn(1, 10, 384)]
        mock_tokenizer.from_pretrained.return_value = Mock()
        
        # Initialize generator
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=mock_onnx_model,
            tokenizer_name="test-model"
        )
        
        assert generator.onnx_model_path == mock_onnx_model
        assert generator.embedding_dim == 384
        assert generator.batch_size == 32
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_encode_single_text(self, mock_tokenizer, mock_session_class, mock_onnx_model):
        """Test encoding a single text."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        # Setup mocks
        mock_session = Mock()
        mock_session.run.return_value = [np.random.randn(1, 3, 384)]
        mock_session_class.return_value = mock_session
        
        mock_tok = Mock()
        mock_tok.return_value = {
            "input_ids": np.array([[1, 2, 3]]),
            "attention_mask": np.array([[1, 1, 1]])
        }
        mock_tokenizer.from_pretrained.return_value = mock_tok
        
        # Initialize and encode
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=mock_onnx_model,
            tokenizer_name="test-model"
        )
        
        embedding = generator.encode("test text")
        
        assert isinstance(embedding, np.ndarray)
        assert embedding.shape[0] == 1  # Single text
        assert embedding.shape[1] == 384  # Embedding dimension
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_encode_batch(self, mock_tokenizer, mock_session_class, mock_onnx_model):
        """Test encoding multiple texts."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        # Setup mocks
        mock_session = Mock()
        mock_session.run.return_value = [np.random.randn(3, 3, 384)]
        mock_session_class.return_value = mock_session
        
        mock_tok = Mock()
        mock_tok.return_value = {
            "input_ids": np.array([[1, 2, 3], [4, 5, 6], [7, 8, 9]]),
            "attention_mask": np.array([[1, 1, 1], [1, 1, 1], [1, 1, 1]])
        }
        mock_tokenizer.from_pretrained.return_value = mock_tok
        
        # Initialize and encode
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=mock_onnx_model,
            tokenizer_name="test-model"
        )
        
        texts = ["text1", "text2", "text3"]
        embeddings = generator.encode(texts)
        
        assert isinstance(embeddings, np.ndarray)
        assert embeddings.shape[0] == 3  # Three texts
        assert embeddings.shape[1] == 384  # Embedding dimension
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_normalization(self, mock_tokenizer, mock_session_class, mock_onnx_model):
        """Test that embeddings are normalized."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        # Setup mocks
        mock_session = Mock()
        mock_session.run.return_value = [np.random.randn(1, 3, 384)]
        mock_session_class.return_value = mock_session
        
        mock_tok = Mock()
        mock_tok.return_value = {
            "input_ids": np.array([[1, 2, 3]]),
            "attention_mask": np.array([[1, 1, 1]])
        }
        mock_tokenizer.from_pretrained.return_value = mock_tok
        
        # Initialize and encode
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=mock_onnx_model,
            tokenizer_name="test-model"
        )
        
        embedding = generator.encode("test text", normalize=True)
        
        # Check L2 norm is approximately 1
        norm = np.linalg.norm(embedding[0])
        assert np.isclose(norm, 1.0, atol=1e-6)
    
    @patch('advisor.embeddings_onnx.ort.get_available_providers')
    def test_provider_selection(self, mock_providers, mock_onnx_model):
        """Test execution provider selection."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        # Mock available providers
        mock_providers.return_value = [
            "CUDAExecutionProvider",
            "CPUExecutionProvider"
        ]
        
        with patch('advisor.embeddings_onnx.ort.InferenceSession'), \
             patch('advisor.embeddings_onnx.AutoTokenizer'):
            
            generator = ONNXEmbeddingGenerator(
                onnx_model_path=mock_onnx_model,
                tokenizer_name="test-model"
            )
            
            # Should select CUDA first
            assert "CUDAExecutionProvider" in generator.providers
    
    def test_mean_pooling(self, mock_onnx_model):
        """Test mean pooling implementation."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        with patch('advisor.embeddings_onnx.ort.InferenceSession'), \
             patch('advisor.embeddings_onnx.AutoTokenizer'):
            
            generator = ONNXEmbeddingGenerator(
                onnx_model_path=mock_onnx_model,
                tokenizer_name="test-model"
            )
            
            # Test data
            last_hidden_state = np.array([
                [[1.0, 2.0], [3.0, 4.0], [5.0, 6.0]]  # (1, 3, 2)
            ])
            attention_mask = np.array([[1, 1, 0]])  # Mask last token
            
            # Perform mean pooling
            result = generator._mean_pooling(last_hidden_state, attention_mask)
            
            # Expected: mean of first two tokens
            expected = np.array([[2.0, 3.0]])  # (1+3)/2, (2+4)/2
            
            assert result.shape == (1, 2)
            np.testing.assert_array_almost_equal(result, expected)


class TestBackendSelection:
    """Test backend selection in get_embedding_generator."""
    
    @patch('advisor.embeddings.get_full_config')
    def test_pytorch_backend_default(self, mock_config):
        """Test PyTorch backend is used by default."""
        from advisor.embeddings import get_embedding_generator, _embedding_generator
        
        # Reset global
        import advisor.embeddings
        advisor.embeddings._embedding_generator = None
        
        # Mock config
        emb_config = MagicMock()
        emb_config.backend = "pytorch"
        emb_config.model = "test-model"
        emb_config.device = "cpu"
        emb_config.batch_size = 32
        mock_config.return_value = {
            "embeddings": emb_config
        }
        
        with patch('advisor.embeddings.EmbeddingGenerator') as mock_gen:
            generator = get_embedding_generator()
            mock_gen.assert_called_once()
    
    @patch('advisor.embeddings.get_full_config')
    def test_onnx_backend_selection(self, mock_config):
        """Test ONNX backend is selected when configured."""
        from advisor.embeddings import get_embedding_generator
        
        # Reset global
        import advisor.embeddings
        advisor.embeddings._embedding_generator = None
        
        # Mock config
        emb_config = MagicMock()
        emb_config.backend = "onnx"
        emb_config.model = "test-model"
        emb_config.batch_size = 32
        emb_config.max_length = 512
        emb_config.onnx.model_path = "test.onnx"
        emb_config.onnx.providers = None
        mock_config.return_value = {
            "embeddings": emb_config
        }
        
        with patch('advisor.embeddings_onnx.ONNXEmbeddingGenerator') as mock_onnx:
            with patch('advisor.embeddings.logger'):
                generator = get_embedding_generator()
                mock_onnx.assert_called_once()
    
    @patch('advisor.embeddings.get_full_config')
    def test_onnx_fallback_to_pytorch(self, mock_config):
        """Test fallback to PyTorch if ONNX fails."""
        from advisor.embeddings import get_embedding_generator
        
        # Reset global
        import advisor.embeddings
        advisor.embeddings._embedding_generator = None
        
        # Mock config
        emb_config = MagicMock()
        emb_config.backend = "onnx"
        emb_config.model = "test-model"
        emb_config.batch_size = 32
        emb_config.onnx.model_path = "nonexistent.onnx"
        mock_config.return_value = {
            "embeddings": emb_config
        }
        
        with patch('advisor.embeddings_onnx.ONNXEmbeddingGenerator', side_effect=Exception("ONNX failed")):
            with patch('advisor.embeddings.EmbeddingGenerator') as mock_pytorch:
                with patch('advisor.embeddings.logger'):
                    generator = get_embedding_generator()
                    mock_pytorch.assert_called_once()


class TestEmbeddingQuality:
    """Test embedding quality and consistency."""
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_embedding_consistency(self, mock_tokenizer, mock_session_class, tmp_path):
        """Test that same text produces same embedding."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        model_path = tmp_path / "test.onnx"
        model_path.touch()
        
        # Setup mocks with deterministic output
        mock_session = Mock()
        output = np.ones((1, 3, 384))
        mock_session.run.return_value = [output]
        mock_session_class.return_value = mock_session
        
        mock_tok = Mock()
        mock_tok.return_value = {
            "input_ids": np.array([[1, 2, 3]]),
            "attention_mask": np.array([[1, 1, 1]])
        }
        mock_tokenizer.from_pretrained.return_value = mock_tok
        
        # Initialize generator
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=model_path,
            tokenizer_name="test-model"
        )
        
        # Encode same text twice
        emb1 = generator.encode("test text")
        emb2 = generator.encode("test text")
        
        # Should be identical
        np.testing.assert_array_equal(emb1, emb2)
    
    @patch('advisor.embeddings_onnx.ort.InferenceSession')
    @patch('advisor.embeddings_onnx.AutoTokenizer')
    def test_embedding_shape(self, mock_tokenizer, mock_session_class, tmp_path):
        """Test embedding output shape is correct."""
        from advisor.embeddings_onnx import ONNXEmbeddingGenerator
        
        model_path = tmp_path / "test.onnx"
        model_path.touch()
        
        # Setup mocks
        mock_session = Mock()
        mock_session.run.return_value = [np.random.randn(5, 10, 384)]
        mock_session_class.return_value = mock_session
        
        mock_tok = Mock()
        mock_tok.return_value = {
            "input_ids": np.array([[1]*10]*5),
            "attention_mask": np.array([[1]*10]*5)
        }
        mock_tokenizer.from_pretrained.return_value = mock_tok
        
        # Initialize generator
        generator = ONNXEmbeddingGenerator(
            onnx_model_path=model_path,
            tokenizer_name="test-model"
        )
        
        # Encode batch
        texts = [f"text{i}" for i in range(5)]
        embeddings = generator.encode(texts)
        
        # Check shape
        assert embeddings.shape == (5, 384)
        assert embeddings.dtype == np.float64 or embeddings.dtype == np.float32