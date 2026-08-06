# ONNX Migration Guide

**Version**: 1.0  
**Date**: 2026-03-03  
**Status: not adopted.** `config/advisor.yaml` → `embeddings.backend` is `pytorch` as of
2026-07-11; this migration was proposed and prototyped but PyTorch remains the active
embedding backend. Kept for reference if ONNX migration is revisited.

## Overview

This guide explains how to migrate from PyTorch to ONNX Runtime for embedding generation, achieving **2-3x speedup** and **50% memory reduction** while maintaining quality.

## Benefits of ONNX

### Performance Improvements
- **2-3x faster inference** compared to PyTorch
- **50% lower memory usage** (~200MB vs ~2GB)
- **Better GPU utilization** across platforms
- **Optimized CPU inference** when GPU unavailable

### Cross-Platform Support
- **NVIDIA**: TensorRT and CUDA execution providers
- **AMD**: MIGraphX execution provider (better than PyTorch ROCm)
- **Apple Silicon**: CoreML execution provider (better than MPS)
- **CPU**: Highly optimized CPU kernels

### Deployment Benefits
- Smaller package size
- Consistent behavior across platforms
- Production-ready inference engine
- No training overhead

## Prerequisites

### System Requirements
- Python 3.12+
- One of:
  - NVIDIA GPU with CUDA 11.8+ (for GPU acceleration)
  - AMD GPU with ROCm 5.0+ (for GPU acceleration)
  - Apple Silicon M1/M2/M3 (for GPU acceleration)
  - Modern CPU (fallback)

### Software Requirements
```bash
# Install ONNX dependencies
pip install -e .  # CPU version

# OR for GPU support (NVIDIA)
pip install -e ".[gpu]"

# OR with optimization tools
pip install -e ".[gpu,onnx-tools]"
```

## Migration Steps

### Step 1: Install Dependencies

#### Option A: CPU Only (Fastest to set up)
```bash
# Navigate to project directory
cd /path/to/egeria-advisor

# Install ONNX dependencies (CPU version)
pip install -e .

# Install conversion tools (required for model conversion)
pip install onnxscript

# Verify installation
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Should show: ['AzureExecutionProvider', 'CPUExecutionProvider']
```

**Note**: CPU-only installation still provides benefits:
- Optimized CPU inference (faster than PyTorch CPU)
- Smaller memory footprint
- Good for development/testing

#### Option B: GPU Support (NVIDIA)
```bash
# Uninstall CPU version first
pip uninstall onnxruntime

# Install GPU version
pip install onnxruntime-gpu

# Install other dependencies
pip install -e ".[onnx-tools]"

# Verify GPU support
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Should show: ['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']
```

**Requirements**:
- NVIDIA GPU with CUDA 11.8+
- CUDA Toolkit installed
- cuDNN installed

#### Option C: GPU Support (AMD ROCm)

**Step 1: Find your GPU's GFX version**
```bash
# Method 1: Using rocminfo
rocminfo | grep "gfx"

# Method 2: Using lspci and looking up your GPU
lspci | grep -i vga
# Then look up your GPU model in the table below
```

**Common AMD GPU GFX Versions**:
| GPU Series | GFX Version | HSA_OVERRIDE_GFX_VERSION |
|------------|-------------|--------------------------|
| RX 7900 XTX/XT | gfx1100 | 11.0.0 |
| RX 7800 XT | gfx1101 | 11.0.1 |
| RX 7700 XT | gfx1101 | 11.0.1 |
| RX 7600 | gfx1102 | 11.0.2 |
| RX 7500 XT | gfx1150 | 11.5.0 |
| RX 6950 XT | gfx1030 | 10.3.0 |
| RX 6900 XT | gfx1030 | 10.3.0 |
| RX 6800 XT/6800 | gfx1030 | 10.3.0 |
| RX 6750 XT | gfx1031 | 10.3.1 |
| RX 6700 XT | gfx1031 | 10.3.1 |
| RX 6650 XT | gfx1032 | 10.3.2 |
| RX 6600 XT/6600 | gfx1032 | 10.3.2 |
| RX 5700 XT/5700 | gfx1010 | 10.1.0 |
| RX 5600 XT/5500 XT | gfx1012 | 10.1.2 |
| Vega 64/56 | gfx900 | 9.0.0 |
| Radeon VII | gfx906 | 9.0.6 |

**Step 2: Install and configure**
```bash
# Install ROCm version
pip install onnxruntime-rocm

# Install other dependencies
pip install -e ".[onnx-tools]"

# Set environment for your GPU (example for RX 6900 XT)
export HSA_OVERRIDE_GFX_VERSION=10.3.0

# Add to your shell profile for persistence
echo 'export HSA_OVERRIDE_GFX_VERSION=10.3.0' >> ~/.bashrc
source ~/.bashrc

# Verify
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Should show: ['MIGraphXExecutionProvider', 'CPUExecutionProvider']
```

**Troubleshooting AMD GPU**:
```bash
# If MIGraphXExecutionProvider doesn't appear:

# 1. Check ROCm installation
rocm-smi

# 2. Check if GPU is detected
rocminfo | grep "Name:"

# 3. Try without HSA_OVERRIDE_GFX_VERSION first
unset HSA_OVERRIDE_GFX_VERSION
python -c "import onnxruntime as ort; print(ort.get_available_providers())"

# 4. If still not working, check ROCm version compatibility
# ONNX Runtime ROCm requires ROCm 5.0+
```

#### Option D: Apple Silicon (M1/M2/M3)
```bash
# Install standard version (includes CoreML)
pip install -e ".[onnx-tools]"

# Verify
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
# Should show: ['CoreMLExecutionProvider', 'CPUExecutionProvider']
```

Expected output (varies by system):
```
# With GPU support (NVIDIA):
['TensorrtExecutionProvider', 'CUDAExecutionProvider', 'CPUExecutionProvider']

# With GPU support (AMD):
['MIGraphXExecutionProvider', 'CPUExecutionProvider']

# With GPU support (Apple Silicon):
['CoreMLExecutionProvider', 'CPUExecutionProvider']

# CPU only:
['AzureExecutionProvider', 'CPUExecutionProvider']
```

**Note**: If you only see `CPUExecutionProvider` or `AzureExecutionProvider`, you have the CPU version installed. For GPU acceleration, see the GPU setup section below.

### Step 2: Convert Model to ONNX

```bash
# Convert the embedding model
python scripts/convert_to_onnx.py \
  --model sentence-transformers/all-MiniLM-L6-v2 \
  --output models/all-MiniLM-L6-v2.onnx

# This will:
# 1. Load the PyTorch model
# 2. Export to ONNX format
# 3. Optimize the model
# 4. Validate correctness
```

Expected output:
```
✓ Model exported to: models/all-MiniLM-L6-v2.onnx
✓ Optimized model saved to: models/all-MiniLM-L6-v2.optimized.onnx
✓ ONNX model is valid
```

### Step 3: Benchmark Performance

```bash
# Compare PyTorch vs ONNX performance
python scripts/benchmark_onnx.py --num-texts 100

# This will measure:
# - Inference speed (texts/sec)
# - Memory usage (MB)
# - Embedding quality (cosine similarity)
```

Expected results:
```
BENCHMARK RESULTS
=================
Performance:
  PyTorch:
    Time: 2.450s
    Speed: 40.8 texts/sec
    Memory: 1024.5 MB

  ONNX:
    Time: 0.980s
    Speed: 102.0 texts/sec
    Memory: 512.3 MB

  Improvement:
    Speedup: 2.50x
    Memory reduction: 50.0%

Embedding Quality:
  Mean cosine similarity: 0.999876
  Min similarity: 0.999654
  Max similarity: 0.999987

SUCCESS CRITERIA
================
✓ Speedup: 2.50x >= 2.0x
✓ Memory reduction: 50.0% >= 30%
✓ Embedding quality: 0.999876 >= 0.999
```

### Step 4: Update Configuration

Edit `config/advisor.yaml`:

```yaml
embeddings:
  backend: onnx  # Change from 'pytorch' to 'onnx'
  model: sentence-transformers/all-MiniLM-L6-v2
  device: auto  # Still used for PyTorch fallback
  batch_size: 64
  normalize: true
  max_length: 512
  
  # ONNX-specific settings
  onnx:
    model_path: models/all-MiniLM-L6-v2.onnx
    providers: null  # null = auto-detect best provider
```

### Step 5: Test the System

```bash
# Test with a simple query
python -m advisor.cli.main "What is an asset?"

# Check logs for ONNX usage
# Should see: "Using ONNX backend: models/all-MiniLM-L6-v2.onnx"
# Should see: "Using execution providers: ['CUDAExecutionProvider', 'CPUExecutionProvider']"
```

### Step 6: Validate Quality

```bash
# Run quality validation
python scripts/test_rag_quality_improvements.py

# Verify hallucination rate is still ≤4%
# Check that search results are still relevant
```

## Configuration Options

### Backend Selection

```yaml
embeddings:
  backend: pytorch  # or 'onnx'
```

- `pytorch`: Use PyTorch sentence-transformers (default, safe)
- `onnx`: Use ONNX Runtime (faster, recommended)

### Execution Providers

```yaml
embeddings:
  onnx:
    providers: null  # Auto-detect (recommended)
```

Or specify manually:
```yaml
embeddings:
  onnx:
    providers:
      - TensorrtExecutionProvider  # NVIDIA TensorRT (fastest)
      - CUDAExecutionProvider      # NVIDIA CUDA
      - CPUExecutionProvider       # CPU fallback
```

Available providers:
- `TensorrtExecutionProvider` - NVIDIA TensorRT (fastest for NVIDIA)
- `CUDAExecutionProvider` - NVIDIA CUDA
- `MIGraphXExecutionProvider` - AMD ROCm
- `CoreMLExecutionProvider` - Apple Silicon
- `DirectMLExecutionProvider` - Windows GPU
- `CPUExecutionProvider` - CPU (always available)

### Model Path

```yaml
embeddings:
  onnx:
    model_path: models/all-MiniLM-L6-v2.onnx  # Relative to project root
```

## Troubleshooting

### Issue: ONNX model not found

**Error**: `FileNotFoundError: ONNX model not found: models/all-MiniLM-L6-v2.onnx`

**Solution**:
```bash
# Convert the model first
python scripts/convert_to_onnx.py
```

### Issue: No GPU acceleration

**Symptoms**: Using `CPUExecutionProvider` only

**Solutions**:

For NVIDIA:
```bash
# Install GPU version
pip install onnxruntime-gpu

# Verify CUDA
python -c "import onnxruntime as ort; print(ort.get_available_providers())"
```

For AMD:
```bash
# Install ROCm version
pip install onnxruntime-rocm

# Set environment
export HSA_OVERRIDE_GFX_VERSION=10.3.0  # Adjust for your GPU
```

For Apple Silicon:
```bash
# CoreML should be available by default
python -c "import onnxruntime as ort; print('CoreMLExecutionProvider' in ort.get_available_providers())"
```

### Issue: Lower quality results

**Symptoms**: Hallucination rate increased, relevance decreased

**Solution**:
```bash
# 1. Verify embedding similarity
python scripts/benchmark_onnx.py --num-texts 100

# Should show >0.999 similarity

# 2. If similarity is low, reconvert model
python scripts/convert_to_onnx.py --no-optimize

# 3. If still issues, fallback to PyTorch
# Edit config/advisor.yaml: backend: pytorch
```

### Issue: Slower than PyTorch

**Possible causes**:
1. Using CPU instead of GPU
2. Model not optimized
3. Batch size too small

**Solutions**:
```bash
# 1. Check execution provider
python -c "import onnxruntime as ort; print(ort.get_available_providers())"

# 2. Reconvert with optimization
python scripts/convert_to_onnx.py

# 3. Increase batch size in config
# Edit config/advisor.yaml: batch_size: 128
```

## Rollback to PyTorch

If you encounter issues, you can easily rollback:

```yaml
# config/advisor.yaml
embeddings:
  backend: pytorch  # Change back to pytorch
```

No other changes needed - the system will automatically use PyTorch.

## Performance Tuning

### Batch Size

Larger batch sizes improve throughput but use more memory:

```yaml
embeddings:
  batch_size: 32   # Default, balanced
  # batch_size: 64   # Higher throughput, more memory
  # batch_size: 128  # Maximum throughput, high memory
```

### Execution Provider Priority

For multi-GPU systems:

```yaml
embeddings:
  onnx:
    providers:
      - TensorrtExecutionProvider  # Try TensorRT first
      - CUDAExecutionProvider      # Fallback to CUDA
      - CPUExecutionProvider       # Final fallback
```

### Model Optimization

For maximum performance:

```bash
# Convert with optimization
python scripts/convert_to_onnx.py

# Use the optimized model
# config/advisor.yaml
embeddings:
  onnx:
    model_path: models/all-MiniLM-L6-v2.optimized.onnx
```

## Validation Checklist

Before deploying to production:

- [ ] ONNX model converted successfully
- [ ] Benchmark shows 2x+ speedup
- [ ] Embedding similarity >0.999
- [ ] Hallucination rate ≤4%
- [ ] Search results still relevant
- [ ] GPU acceleration working (if available)
- [ ] Memory usage acceptable
- [ ] No errors in logs

## FAQ

**Q: Will this break existing functionality?**  
A: No. The ONNX backend is a drop-in replacement with the same interface.

**Q: Can I switch back to PyTorch?**  
A: Yes, just change `backend: onnx` to `backend: pytorch` in config.

**Q: Do I need to re-ingest data?**  
A: No. Embeddings are compatible between backends (>0.999 similarity).

**Q: What if ONNX fails to load?**  
A: The system automatically falls back to PyTorch with a warning.

**Q: Is ONNX production-ready?**  
A: Yes. ONNX Runtime is used in production by Microsoft, Meta, and others.

**Q: Will quality degrade?**  
A: No. Embeddings are >99.9% similar, maintaining the 4% hallucination rate.

## Support

For issues or questions:
1. Check logs for error messages
2. Run benchmark to verify performance
3. Try PyTorch fallback if issues persist
4. Report issues with benchmark results

## Next Steps

After successful migration:
1. Monitor performance in production
2. Adjust batch size for your workload
3. Consider using optimized model for maximum speed
4. Share performance improvements with team

## References

- [ONNX Runtime Documentation](https://onnxruntime.ai/)
- [Execution Providers](https://onnxruntime.ai/docs/execution-providers/)
- [Performance Tuning](https://onnxruntime.ai/docs/performance/)