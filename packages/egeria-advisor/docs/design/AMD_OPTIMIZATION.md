# AMD AI Processor Optimization Guide

**Update (2026-07-11):** this was successfully applied on this machine (AMD Radeon 890M /
Strix Point iGPU). The `rocm5.7` wheel index below is stale — check
`rocm-smi --version` / `cat /opt/rocm/.info/version` for your actual installed ROCm runtime
version first, and match the PyTorch wheel index to it (this machine needed `rocm7.2`; PyTorch
publishes wheels at `https://download.pytorch.org/whl/rocm{X.Y}` for whatever versions are
current — check what's available with
`curl -s https://download.pytorch.org/whl/torch/ | grep -o 'rocm[0-9.]*' | sort -u`).
`torchaudio` was not installed on this machine and wasn't reinstalled — only
`torch`/`torchvision` were needed. No `.env`/`config/advisor.yaml` device override was
needed — `embeddings.device: auto` in `config/advisor.yaml` already picks up ROCm
automatically once the right wheel is installed, since ROCm-flavored PyTorch reports GPUs
through the same `torch.cuda.*` API as NVIDIA (verified: `torch.cuda.is_available()` returns
`True` and `torch.cuda.get_device_name(0)` correctly returns `"AMD Radeon 890M"`).

## Overview

Your AMD AI processor (likely Ryzen AI with NPU) can be optimized for better performance with machine learning workloads. Here's how to configure the Egeria Advisor to take advantage of it.

---

## AMD Hardware Detection

First, let's check what AMD hardware you have:

```bash
# Check CPU info
lscpu | grep -i amd

# Check for AMD GPU
lspci | grep -i amd

# Check for ROCm support (AMD's CUDA equivalent)
rocm-smi || echo "ROCm not installed"
```

---

## Optimization Options

### Option 1: ROCm for AMD GPU (Recommended if you have AMD GPU)

ROCm is AMD's open-source platform for GPU computing, equivalent to NVIDIA's CUDA.

#### Install ROCm

```bash
# For Ubuntu/Debian
wget https://repo.radeon.com/amdgpu-install/latest/ubuntu/jammy/amdgpu-install_5.7.50700-1_all.deb
sudo apt install ./amdgpu-install_5.7.50700-1_all.deb
sudo amdgpu-install --usecase=rocm

# Verify installation
rocm-smi
```

#### Install PyTorch with ROCm Support

**IMPORTANT**: PyTorch with ROCm requires Python 3.11 or 3.12 (not 3.13). Always work in a virtual environment.

```bash
# First, create virtual environment with Python 3.12
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
python3.12 -m venv .venv
source .venv/bin/activate

# Verify Python version (must be 3.11 or 3.12)
python --version  # Should show Python 3.12.x

# Uninstall CPU-only PyTorch if installed (only in venv)
pip uninstall torch torchvision torchaudio

# Install ROCm-enabled PyTorch in the virtual environment
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.7
```

**Troubleshooting**:
- **"Could not find a version that satisfies the requirement torch"**: You're using Python 3.13, which isn't supported yet. Recreate venv with Python 3.12: `python3.12 -m venv .venv`
- **"externally-managed-environment"**: You're trying to modify system Python. Always activate the virtual environment first: `source .venv/bin/activate`
- **No python3.12**: Install it: `sudo apt install python3.12 python3.12-venv`

#### Update Configuration

Edit `.env`:
```bash
# Change from CPU to ROCm
EMBEDDING_DEVICE=cuda  # PyTorch uses 'cuda' for both NVIDIA and AMD GPUs
```

Edit `config/advisor.yaml`:
```yaml
embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  device: cuda  # Will use AMD GPU via ROCm
  batch_size: 64  # Increase batch size for GPU
  normalize: true
  max_length: 512
```

---

### Option 2: OpenVINO for AMD CPU/NPU (Alternative)

OpenVINO supports AMD processors and can optimize inference.

#### Install OpenVINO

```bash
pip install openvino openvino-dev
```

#### Update Configuration

Edit `config/advisor.yaml`:
```yaml
embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  device: cpu  # OpenVINO will optimize CPU execution
  backend: openvino  # Use OpenVINO backend
  batch_size: 32
  normalize: true
```

---

### Option 3: ONNX Runtime with DirectML (Windows) or ROCm (Linux)

ONNX Runtime can use AMD hardware acceleration.

#### Install ONNX Runtime

```bash
# For Linux with ROCm
pip install onnxruntime-rocm

# For Windows with DirectML
pip install onnxruntime-directml
```

---

## Ollama Optimization for AMD

Ollama can use AMD GPUs via ROCm:

### Docker with ROCm Support

```bash
# Stop existing Ollama container
docker stop ollama

# Run with ROCm support
docker run -d \
  --device=/dev/kfd \
  --device=/dev/dri \
  --group-add video \
  --name ollama \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  --restart unless-stopped \
  ollama/ollama:rocm

# Verify GPU is detected
docker exec ollama ollama run llama3.1:8b "test"
```

### Native Ollama with ROCm

```bash
# Install Ollama with ROCm support
curl -fsSL https://ollama.com/install.sh | sh

# Set environment variable for ROCm
export OLLAMA_GPU_DRIVER=rocm

# Start Ollama
ollama serve &

# Pull models
ollama pull llama3.1:8b
ollama pull codellama:13b
```

---

## Sentence Transformers Optimization

For embedding generation, optimize sentence-transformers:

### Create Optimized Embedding Module

Create `advisor/embeddings/amd_embeddings.py`:

```python
"""AMD-optimized embedding generation."""
from sentence_transformers import SentenceTransformer
import torch

class AMDEmbeddings:
    def __init__(self, model_name: str, device: str = "cuda"):
        """
        Initialize AMD-optimized embeddings.
        
        Parameters
        ----------
        model_name : str
            Name of the sentence-transformers model
        device : str
            Device to use ('cuda' for AMD GPU, 'cpu' for CPU)
        """
        self.device = device
        
        # Check if ROCm/CUDA is available
        if device == "cuda" and not torch.cuda.is_available():
            print("⚠️  CUDA/ROCm not available, falling back to CPU")
            self.device = "cpu"
        
        # Load model
        self.model = SentenceTransformer(model_name, device=self.device)
        
        # Enable AMD-specific optimizations
        if self.device == "cuda":
            # Use mixed precision for faster inference
            self.model.half()  # FP16 precision
            print(f"✓ Loaded {model_name} on AMD GPU with FP16")
        else:
            print(f"✓ Loaded {model_name} on CPU")
    
    def encode(self, texts: list[str], batch_size: int = 32) -> list:
        """
        Generate embeddings for texts.
        
        Parameters
        ----------
        texts : list[str]
            Texts to embed
        batch_size : int
            Batch size for processing
        
        Returns
        -------
        list
            List of embeddings
        """
        return self.model.encode(
            texts,
            batch_size=batch_size,
            show_progress_bar=True,
            convert_to_numpy=True,
            normalize_embeddings=True
        )
```

---

## Performance Tuning

### Batch Size Optimization

AMD GPUs benefit from larger batch sizes:

```yaml
# config/advisor.yaml
embeddings:
  batch_size: 64  # Increase for GPU (was 32 for CPU)
```

### Thread Optimization

For CPU workloads, optimize thread count:

```bash
# Add to .env
OMP_NUM_THREADS=8  # Set to number of physical cores
MKL_NUM_THREADS=8
```

### Memory Optimization

```yaml
# config/advisor.yaml
rag:
  chunk_size: 512
  chunk_overlap: 50
  max_context_length: 4000  # Adjust based on available memory
```

---

## Verification

### Check GPU Usage

```bash
# Monitor AMD GPU
watch -n 1 rocm-smi

# Or
watch -n 1 radeontop
```

### Benchmark Performance

Create `scripts/benchmark_amd.py`:

```python
"""Benchmark AMD performance."""
import time
import torch
from sentence_transformers import SentenceTransformer

def benchmark_device(device: str):
    """Benchmark embedding generation on device."""
    print(f"\nBenchmarking on {device}...")
    
    model = SentenceTransformer(
        'sentence-transformers/all-MiniLM-L6-v2',
        device=device
    )
    
    # Test data
    texts = ["This is a test sentence."] * 1000
    
    # Warmup
    _ = model.encode(texts[:10], batch_size=10)
    
    # Benchmark
    start = time.time()
    embeddings = model.encode(texts, batch_size=32)
    elapsed = time.time() - start
    
    print(f"  Time: {elapsed:.2f}s")
    print(f"  Throughput: {len(texts)/elapsed:.2f} texts/sec")
    print(f"  Embedding shape: {embeddings.shape}")

if __name__ == "__main__":
    # Test CPU
    benchmark_device("cpu")
    
    # Test GPU if available
    if torch.cuda.is_available():
        benchmark_device("cuda")
        print(f"\n✓ GPU speedup: {cpu_time/gpu_time:.2f}x")
    else:
        print("\n⚠️  GPU not available")
```

Run benchmark:
```bash
python scripts/benchmark_amd.py
```

---

## Expected Performance

### CPU (Ryzen AI)
- Embedding generation: ~50-100 texts/second
- LLM inference (Ollama): ~10-20 tokens/second

### GPU (AMD Radeon with ROCm)
- Embedding generation: ~500-1000 texts/second (10x faster)
- LLM inference (Ollama): ~50-100 tokens/second (5x faster)

---

## Troubleshooting

### ROCm Not Detecting GPU

```bash
# Check GPU is visible
ls /dev/kfd /dev/dri

# Check permissions
sudo usermod -a -G video $USER
sudo usermod -a -G render $USER
# Log out and back in
```

### PyTorch Not Using GPU

```python
# Test in Python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"CUDA device: {torch.cuda.get_device_name(0)}")
```

### Ollama Not Using GPU

```bash
# Check Ollama logs
docker logs ollama

# Should see: "GPU detected: AMD Radeon..."
```

---

## Recommended Configuration for AMD

### For AMD GPU (Radeon)

```yaml
# config/advisor.yaml
embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  device: cuda  # Uses ROCm
  batch_size: 64
  normalize: true

llm:
  provider: ollama
  base_url: http://localhost:11434
  # Ollama will auto-detect and use AMD GPU
```

```bash
# .env
EMBEDDING_DEVICE=cuda
OLLAMA_GPU_DRIVER=rocm
```

### For AMD CPU Only (No GPU)

```yaml
# config/advisor.yaml
embeddings:
  model: sentence-transformers/all-MiniLM-L6-v2
  device: cpu
  batch_size: 32  # Lower for CPU
  normalize: true

llm:
  provider: ollama
  base_url: http://localhost:11434
```

```bash
# .env
EMBEDDING_DEVICE=cpu
OMP_NUM_THREADS=8  # Set to your core count
```

---

## Summary

1. **Check your hardware**: `lscpu`, `lspci | grep -i amd`
2. **Install ROCm** if you have AMD GPU
3. **Update configuration** to use `cuda` device
4. **Restart Ollama** with ROCm support
5. **Run benchmark** to verify performance

The configuration is already set up to work with CPU by default, but you can get 5-10x speedup by enabling AMD GPU support!

---

## Quick Setup for AMD GPU

```bash
# 1. Install ROCm
sudo amdgpu-install --usecase=rocm

# 2. Install PyTorch with ROCm
pip install torch --index-url https://download.pytorch.org/whl/rocm5.7

# 3. Update .env
echo "EMBEDDING_DEVICE=cuda" >> .env

# 4. Restart Ollama with ROCm
docker stop ollama
docker run -d --device=/dev/kfd --device=/dev/dri --group-add video \
  --name ollama -p 11434:11434 -v ollama:/root/.ollama \
  ollama/ollama:rocm

# 5. Test
python scripts/benchmark_amd.py
```

That's it! Your AMD hardware will now be fully utilized.