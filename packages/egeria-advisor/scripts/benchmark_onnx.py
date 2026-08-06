#!/usr/bin/env python3
"""
Benchmark ONNX vs PyTorch embeddings for performance comparison.

Measures:
- Inference speed (tokens/sec)
- Memory usage
- Embedding quality (cosine similarity)
"""

import argparse
import time
from pathlib import Path
from typing import List, Dict, Any
import numpy as np
from loguru import logger
import psutil
import sys


def benchmark_pytorch(
    model_name: str,
    test_texts: List[str],
    batch_size: int = 32
) -> Dict[str, Any]:
    """Benchmark PyTorch sentence-transformers."""
    from sentence_transformers import SentenceTransformer
    import torch
    
    logger.info("Benchmarking PyTorch...")
    
    # Load model
    model = SentenceTransformer(model_name, device="cpu")
    
    # Warm-up
    _ = model.encode(test_texts[:5])
    
    # Measure memory before
    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    
    # Benchmark encoding
    start_time = time.time()
    embeddings = model.encode(
        test_texts,
        batch_size=batch_size,
        show_progress_bar=False,
        convert_to_numpy=True
    )
    end_time = time.time()
    
    # Measure memory after
    mem_after = process.memory_info().rss / 1024 / 1024  # MB
    
    elapsed = end_time - start_time
    tokens_per_sec = len(test_texts) / elapsed
    
    return {
        "backend": "pytorch",
        "elapsed_time": elapsed,
        "tokens_per_sec": tokens_per_sec,
        "memory_mb": mem_after - mem_before,
        "embeddings": embeddings
    }


def benchmark_onnx(
    onnx_model_path: Path,
    test_texts: List[str],
    batch_size: int = 32
) -> Dict[str, Any]:
    """Benchmark ONNX Runtime."""
    import onnxruntime as ort
    from transformers import AutoTokenizer
    
    logger.info("Benchmarking ONNX...")
    
    # Load tokenizer (same as original model)
    tokenizer = AutoTokenizer.from_pretrained("sentence-transformers/all-MiniLM-L6-v2")
    
    # Create ONNX session with optimizations
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    
    # Auto-detect best execution provider
    providers = ort.get_available_providers()
    logger.info(f"Available providers: {providers}")
    
    session = ort.InferenceSession(
        str(onnx_model_path),
        sess_options,
        providers=providers
    )
    
    # Warm-up
    for text in test_texts[:5]:
        inputs = tokenizer(text, return_tensors="np", padding=True, truncation=True)
        _ = session.run(None, {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"]
        })
    
    # Measure memory before
    process = psutil.Process()
    mem_before = process.memory_info().rss / 1024 / 1024  # MB
    
    # Benchmark encoding
    start_time = time.time()
    embeddings_list = []
    
    for i in range(0, len(test_texts), batch_size):
        batch = test_texts[i:i + batch_size]
        inputs = tokenizer(
            batch,
            return_tensors="np",
            padding=True,
            truncation=True,
            max_length=512
        )
        
        outputs = session.run(None, {
            "input_ids": inputs["input_ids"],
            "attention_mask": inputs["attention_mask"]
        })
        
        # Mean pooling
        last_hidden_state = outputs[0]
        attention_mask = inputs["attention_mask"]
        
        # Expand attention mask for broadcasting
        attention_mask_expanded = np.expand_dims(attention_mask, -1)
        
        # Sum embeddings
        sum_embeddings = np.sum(last_hidden_state * attention_mask_expanded, axis=1)
        sum_mask = np.sum(attention_mask_expanded, axis=1)
        sum_mask = np.clip(sum_mask, a_min=1e-9, a_max=None)
        
        # Mean pooling
        mean_embeddings = sum_embeddings / sum_mask
        
        # Normalize
        norms = np.linalg.norm(mean_embeddings, axis=1, keepdims=True)
        normalized = mean_embeddings / norms
        
        embeddings_list.append(normalized)
    
    embeddings = np.vstack(embeddings_list)
    end_time = time.time()
    
    # Measure memory after
    mem_after = process.memory_info().rss / 1024 / 1024  # MB
    
    elapsed = end_time - start_time
    tokens_per_sec = len(test_texts) / elapsed
    
    return {
        "backend": "onnx",
        "elapsed_time": elapsed,
        "tokens_per_sec": tokens_per_sec,
        "memory_mb": mem_after - mem_before,
        "embeddings": embeddings
    }


def compare_embeddings(
    pytorch_embeddings: np.ndarray,
    onnx_embeddings: np.ndarray
) -> Dict[str, float]:
    """Compare embedding quality using cosine similarity."""
    from sklearn.metrics.pairwise import cosine_similarity
    
    # Compute pairwise cosine similarities
    similarities = []
    for i in range(len(pytorch_embeddings)):
        sim = cosine_similarity(
            pytorch_embeddings[i:i+1],
            onnx_embeddings[i:i+1]
        )[0][0]
        similarities.append(sim)
    
    return {
        "mean_similarity": np.mean(similarities),
        "min_similarity": np.min(similarities),
        "max_similarity": np.max(similarities),
        "std_similarity": np.std(similarities)
    }


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Benchmark ONNX vs PyTorch embeddings"
    )
    parser.add_argument(
        "--model",
        type=str,
        default="sentence-transformers/all-MiniLM-L6-v2",
        help="PyTorch model name"
    )
    parser.add_argument(
        "--onnx-model",
        type=Path,
        default=Path("models/all-MiniLM-L6-v2.onnx"),
        help="ONNX model path"
    )
    parser.add_argument(
        "--num-texts",
        type=int,
        default=100,
        help="Number of test texts"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        help="Batch size for encoding"
    )
    
    args = parser.parse_args()
    
    # Generate test texts
    test_texts = [
        f"This is test sentence number {i} for benchmarking embeddings."
        for i in range(args.num_texts)
    ]
    
    logger.info(f"Benchmarking with {len(test_texts)} texts...")
    
    # Benchmark PyTorch
    try:
        pytorch_results = benchmark_pytorch(
            args.model,
            test_texts,
            args.batch_size
        )
    except Exception as e:
        logger.error(f"PyTorch benchmark failed: {e}")
        sys.exit(1)
    
    # Benchmark ONNX
    if not args.onnx_model.exists():
        logger.error(f"ONNX model not found: {args.onnx_model}")
        logger.info("Run convert_to_onnx.py first")
        sys.exit(1)
    
    try:
        onnx_results = benchmark_onnx(
            args.onnx_model,
            test_texts,
            args.batch_size
        )
    except Exception as e:
        logger.error(f"ONNX benchmark failed: {e}")
        sys.exit(1)
    
    # Compare embeddings
    similarity_metrics = compare_embeddings(
        pytorch_results["embeddings"],
        onnx_results["embeddings"]
    )
    
    # Print results
    logger.info("\n" + "="*60)
    logger.info("BENCHMARK RESULTS")
    logger.info("="*60)
    
    logger.info("\nPerformance:")
    logger.info(f"  PyTorch:")
    logger.info(f"    Time: {pytorch_results['elapsed_time']:.3f}s")
    logger.info(f"    Speed: {pytorch_results['tokens_per_sec']:.1f} texts/sec")
    logger.info(f"    Memory: {pytorch_results['memory_mb']:.1f} MB")
    
    logger.info(f"\n  ONNX:")
    logger.info(f"    Time: {onnx_results['elapsed_time']:.3f}s")
    logger.info(f"    Speed: {onnx_results['tokens_per_sec']:.1f} texts/sec")
    logger.info(f"    Memory: {onnx_results['memory_mb']:.1f} MB")
    
    # Calculate speedup
    speedup = pytorch_results['elapsed_time'] / onnx_results['elapsed_time']
    memory_reduction = (1 - onnx_results['memory_mb'] / pytorch_results['memory_mb']) * 100
    
    logger.info(f"\n  Improvement:")
    logger.info(f"    Speedup: {speedup:.2f}x")
    logger.info(f"    Memory reduction: {memory_reduction:.1f}%")
    
    logger.info(f"\nEmbedding Quality:")
    logger.info(f"  Mean cosine similarity: {similarity_metrics['mean_similarity']:.6f}")
    logger.info(f"  Min similarity: {similarity_metrics['min_similarity']:.6f}")
    logger.info(f"  Max similarity: {similarity_metrics['max_similarity']:.6f}")
    logger.info(f"  Std deviation: {similarity_metrics['std_similarity']:.6f}")
    
    # Success criteria
    logger.info("\n" + "="*60)
    logger.info("SUCCESS CRITERIA")
    logger.info("="*60)
    
    success = True
    
    if speedup >= 2.0:
        logger.info(f"✓ Speedup: {speedup:.2f}x >= 2.0x")
    else:
        logger.warning(f"✗ Speedup: {speedup:.2f}x < 2.0x")
        success = False
    
    if memory_reduction >= 30:
        logger.info(f"✓ Memory reduction: {memory_reduction:.1f}% >= 30%")
    else:
        logger.warning(f"✗ Memory reduction: {memory_reduction:.1f}% < 30%")
        success = False
    
    if similarity_metrics['mean_similarity'] >= 0.999:
        logger.info(f"✓ Embedding quality: {similarity_metrics['mean_similarity']:.6f} >= 0.999")
    else:
        logger.warning(f"✗ Embedding quality: {similarity_metrics['mean_similarity']:.6f} < 0.999")
        success = False
    
    if success:
        logger.info("\n✓ All success criteria met!")
        sys.exit(0)
    else:
        logger.warning("\n✗ Some success criteria not met")
        sys.exit(1)


if __name__ == "__main__":
    main()