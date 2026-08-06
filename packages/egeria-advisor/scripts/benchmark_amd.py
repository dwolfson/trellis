#!/usr/bin/env python3
"""
Benchmark AMD hardware performance for embeddings and LLM inference.

This script helps you verify that AMD GPU acceleration is working correctly.
"""
import sys
import time
from pathlib import Path

def benchmark_embeddings():
    """Benchmark embedding generation on CPU and GPU."""
    print("=" * 80)
    print("Embedding Generation Benchmark")
    print("=" * 80)
    
    try:
        import torch
        from sentence_transformers import SentenceTransformer
    except ImportError as e:
        print(f"❌ Missing dependencies: {e}")
        print("Install with: pip install torch sentence-transformers")
        return
    
    # Test data
    texts = [
        "This is a test sentence for embedding generation.",
        "Egeria is an open metadata and governance platform.",
        "PyEgeria provides Python bindings for Egeria.",
    ] * 100  # 300 texts total
    
    print(f"\nTest data: {len(texts)} texts")
    print(f"PyTorch version: {torch.__version__}")
    print(f"CUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"CUDA device: {torch.cuda.get_device_name(0)}")
        print(f"CUDA version: {torch.version.cuda}")
    
    results = {}
    
    # Benchmark CPU
    print("\n" + "-" * 80)
    print("Testing CPU...")
    print("-" * 80)
    
    try:
        model_cpu = SentenceTransformer(
            'sentence-transformers/all-MiniLM-L6-v2',
            device='cpu'
        )
        
        # Warmup
        _ = model_cpu.encode(texts[:10], batch_size=10, show_progress_bar=False)
        
        # Benchmark
        start = time.time()
        embeddings_cpu = model_cpu.encode(
            texts,
            batch_size=32,
            show_progress_bar=True,
            convert_to_numpy=True
        )
        cpu_time = time.time() - start
        
        results['cpu'] = {
            'time': cpu_time,
            'throughput': len(texts) / cpu_time,
            'shape': embeddings_cpu.shape
        }
        
        print(f"\n✓ CPU Results:")
        print(f"  Time: {cpu_time:.2f}s")
        print(f"  Throughput: {results['cpu']['throughput']:.2f} texts/sec")
        print(f"  Embedding shape: {results['cpu']['shape']}")
        
    except Exception as e:
        print(f"❌ CPU benchmark failed: {e}")
        results['cpu'] = None
    
    # Benchmark GPU if available
    if torch.cuda.is_available():
        print("\n" + "-" * 80)
        print("Testing GPU (AMD via ROCm)...")
        print("-" * 80)
        
        try:
            model_gpu = SentenceTransformer(
                'sentence-transformers/all-MiniLM-L6-v2',
                device='cuda'
            )
            
            # Use FP16 for faster inference on AMD
            model_gpu.half()
            
            # Warmup
            _ = model_gpu.encode(texts[:10], batch_size=10, show_progress_bar=False)
            
            # Benchmark
            start = time.time()
            embeddings_gpu = model_gpu.encode(
                texts,
                batch_size=64,  # Larger batch for GPU
                show_progress_bar=True,
                convert_to_numpy=True
            )
            gpu_time = time.time() - start
            
            results['gpu'] = {
                'time': gpu_time,
                'throughput': len(texts) / gpu_time,
                'shape': embeddings_gpu.shape
            }
            
            print(f"\n✓ GPU Results:")
            print(f"  Time: {gpu_time:.2f}s")
            print(f"  Throughput: {results['gpu']['throughput']:.2f} texts/sec")
            print(f"  Embedding shape: {results['gpu']['shape']}")
            
            if results['cpu']:
                speedup = cpu_time / gpu_time
                print(f"\n🚀 GPU Speedup: {speedup:.2f}x faster than CPU")
            
        except Exception as e:
            print(f"❌ GPU benchmark failed: {e}")
            print("   Make sure ROCm is installed and configured correctly")
            results['gpu'] = None
    else:
        print("\n⚠️  GPU not available")
        print("   To enable AMD GPU:")
        print("   1. Install ROCm: sudo amdgpu-install --usecase=rocm")
        print("   2. Install PyTorch with ROCm: pip install torch --index-url https://download.pytorch.org/whl/rocm5.7")
        results['gpu'] = None
    
    return results

def benchmark_ollama():
    """Benchmark Ollama LLM inference."""
    print("\n" + "=" * 80)
    print("Ollama LLM Inference Benchmark")
    print("=" * 80)
    
    try:
        import ollama
    except ImportError:
        print("❌ Ollama package not installed")
        print("Install with: pip install ollama")
        return None
    
    try:
        # Test prompt
        prompt = "What is metadata management? Answer in one sentence."
        
        print(f"\nTest prompt: {prompt}")
        print("Model: llama3.1:8b")
        
        # Benchmark
        start = time.time()
        response = ollama.generate(
            model='llama3.1:8b',
            prompt=prompt
        )
        elapsed = time.time() - start
        
        response_text = response['response']
        tokens = len(response_text.split())  # Rough token count
        
        print(f"\n✓ Ollama Results:")
        print(f"  Time: {elapsed:.2f}s")
        print(f"  Tokens: ~{tokens}")
        print(f"  Throughput: ~{tokens/elapsed:.2f} tokens/sec")
        print(f"  Response: {response_text[:100]}...")
        
        # Check if GPU was used
        if 'eval_duration' in response:
            eval_time = response['eval_duration'] / 1e9  # Convert to seconds
            print(f"  Eval time: {eval_time:.2f}s")
        
        return {
            'time': elapsed,
            'tokens': tokens,
            'throughput': tokens / elapsed
        }
        
    except Exception as e:
        print(f"❌ Ollama benchmark failed: {e}")
        print("   Make sure Ollama is running: docker ps | grep ollama")
        print("   Or start it: docker start ollama")
        return None

def check_system_info():
    """Display system information."""
    print("=" * 80)
    print("System Information")
    print("=" * 80)
    
    import platform
    print(f"\nPython: {platform.python_version()}")
    print(f"Platform: {platform.platform()}")
    print(f"Processor: {platform.processor()}")
    
    try:
        import torch
        print(f"\nPyTorch: {torch.__version__}")
        print(f"CUDA available: {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"CUDA version: {torch.version.cuda}")
            print(f"GPU: {torch.cuda.get_device_name(0)}")
            print(f"GPU memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.2f} GB")
    except ImportError:
        print("\nPyTorch: Not installed")
    
    try:
        import ollama
        print(f"\nOllama: Installed")
        # Try to get version
        try:
            models = ollama.list()
            print(f"Available models: {len(models.get('models', []))}")
        except:
            print("Ollama: Not running")
    except ImportError:
        print("\nOllama: Not installed")

def main():
    """Run all benchmarks."""
    check_system_info()
    
    # Benchmark embeddings
    embedding_results = benchmark_embeddings()
    
    # Benchmark Ollama
    ollama_results = benchmark_ollama()
    
    # Summary
    print("\n" + "=" * 80)
    print("Benchmark Summary")
    print("=" * 80)
    
    if embedding_results and embedding_results.get('cpu'):
        print(f"\n📊 Embeddings (CPU): {embedding_results['cpu']['throughput']:.2f} texts/sec")
    
    if embedding_results and embedding_results.get('gpu'):
        print(f"📊 Embeddings (GPU): {embedding_results['gpu']['throughput']:.2f} texts/sec")
        if embedding_results.get('cpu'):
            speedup = embedding_results['cpu']['time'] / embedding_results['gpu']['time']
            print(f"   🚀 Speedup: {speedup:.2f}x")
    
    if ollama_results:
        print(f"\n📊 Ollama LLM: ~{ollama_results['throughput']:.2f} tokens/sec")
    
    print("\n" + "=" * 80)
    
    # Recommendations
    print("\nRecommendations:")
    
    if not embedding_results or not embedding_results.get('gpu'):
        print("  ⚠️  AMD GPU not detected or not configured")
        print("     See AMD_OPTIMIZATION.md for setup instructions")
    else:
        print("  ✅ AMD GPU is working correctly!")
    
    if not ollama_results:
        print("  ⚠️  Ollama not available")
        print("     Start with: docker start ollama")
    else:
        print("  ✅ Ollama is working correctly!")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())