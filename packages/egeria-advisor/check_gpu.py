#!/usr/bin/env python3
"""Check if PyTorch can detect GPU"""

import sys

try:
    import torch
    
    print("=" * 60)
    print("PyTorch GPU Detection Test")
    print("=" * 60)
    
    # Check PyTorch version
    print(f"\nPyTorch version: {torch.__version__}")
    
    # Check CUDA availability
    print(f"\nCUDA available: {torch.cuda.is_available()}")
    
    if torch.cuda.is_available():
        print(f"CUDA version: {torch.version.cuda}")
        print(f"Number of GPUs: {torch.cuda.device_count()}")
        
        for i in range(torch.cuda.device_count()):
            print(f"\nGPU {i}:")
            print(f"  Name: {torch.cuda.get_device_name(i)}")
            print(f"  Compute Capability: {torch.cuda.get_device_capability(i)}")
            
            # Get memory info
            props = torch.cuda.get_device_properties(i)
            print(f"  Total Memory: {props.total_memory / 1024**3:.2f} GB")
            print(f"  Multi-Processor Count: {props.multi_processor_count}")
        
        # Test tensor creation on GPU
        print("\nTesting tensor creation on GPU...")
        try:
            x = torch.randn(3, 3).cuda()
            print(f"✓ Successfully created tensor on GPU")
            print(f"  Tensor device: {x.device}")
        except Exception as e:
            print(f"✗ Failed to create tensor on GPU: {e}")
    else:
        print("\n⚠ No CUDA-capable GPU detected")
        print("\nChecking for ROCm (AMD GPU) support...")
        
        # Check for ROCm
        if hasattr(torch.version, 'hip') and torch.version.hip is not None:
            print(f"ROCm/HIP version: {torch.version.hip}")
            print("AMD GPU support is available")
        else:
            print("No ROCm/HIP support detected")
    
    # Check available backends
    print("\n" + "=" * 60)
    print("Available backends:")
    print(f"  CPU: Always available")
    print(f"  CUDA: {torch.cuda.is_available()}")
    if hasattr(torch.backends, 'mps'):
        print(f"  MPS (Apple Silicon): {torch.backends.mps.is_available()}")
    
    print("=" * 60)
    
except ImportError:
    print("ERROR: PyTorch is not installed")
    print("Install it with: pip install torch")
    sys.exit(1)
except Exception as e:
    print(f"ERROR: {e}")
    sys.exit(1)