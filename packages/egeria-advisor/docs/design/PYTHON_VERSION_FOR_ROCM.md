# Python Version Solution for AMD ROCm

**Status: possibly operative — verify before relying on it.** Moved out of `docs/history/` on 2026-09-03 because ROCm is still referenced by `advisor/embeddings_onnx.py`, `advisor/embeddings.py` and `advisor/configdata/advisor.yaml`. The Python versions it names may have moved on: `requires-python` is now `>=3.12`.

## Problem
- Your system only has Python 3.13 and 3.14 available
- PyTorch with ROCm currently only supports Python 3.8-3.12
- Python 3.12 is not in your distribution's repositories

## Solutions (Choose One)

### Option 1: Use CPU-Only PyTorch (Recommended for Now)

**Pros:**
- Works immediately with Python 3.13
- No additional setup required
- Still functional for development and testing
- Can switch to GPU later

**Steps:**
```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate

# Install CPU-only PyTorch (works with Python 3.13)
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Test the setup
python scripts/test_setup.py
python -m advisor.data_prep.pipeline
```

**Performance:**
- Embeddings: ~50-100 texts/sec on CPU
- Sufficient for development and moderate workloads
- Can upgrade to GPU later when PyTorch supports Python 3.13

---

### Option 2: Install Python 3.12 via pyenv

**Pros:**
- Get exact Python version needed
- Can have multiple Python versions
- Full AMD GPU support

**Cons:**
- Requires compilation (takes 10-15 minutes)
- Additional setup complexity

**Steps:**

1. **Install pyenv:**
```bash
# Install dependencies
sudo apt update
sudo apt install -y make build-essential libssl-dev zlib1g-dev \
  libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
  libncursesw5-dev xz-utils tk-dev libxml2-dev libxmlsec1-dev \
  libffi-dev liblzma-dev

# Install pyenv
curl https://pyenv.run | bash

# Add to ~/.bashrc
echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'command -v pyenv >/dev/null || export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc

# Reload shell
exec $SHELL
```

2. **Install Python 3.12:**
```bash
# Install Python 3.12.7 (latest 3.12)
pyenv install 3.12.7

# Set as local version for the project
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
pyenv local 3.12.7
```

3. **Recreate virtual environment:**
```bash
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
python --version  # Should show Python 3.12.7

# Install dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# Install PyTorch with ROCm
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.7
```

---

### Option 3: Use Deadsnakes PPA (Ubuntu/Debian)

**Pros:**
- Pre-built packages (fast installation)
- Easy to maintain

**Cons:**
- Only works on Ubuntu/Debian
- Requires adding external repository

**Steps:**
```bash
# Add deadsnakes PPA
sudo apt update
sudo apt install software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update

# Install Python 3.12
sudo apt install python3.12 python3.12-venv python3.12-dev

# Recreate virtual environment
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
rm -rf .venv
python3.12 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# Install PyTorch with ROCm
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.7
```

---

### Option 4: Wait for PyTorch ROCm Python 3.13 Support

**Timeline:**
- PyTorch typically adds new Python version support 2-4 months after release
- Python 3.13 was released October 2024
- ROCm support for Python 3.13 likely coming Q1-Q2 2025

**Current Status:**
- Use CPU-only PyTorch with Python 3.13 for now
- Monitor PyTorch releases: https://pytorch.org/get-started/locally/
- Upgrade when ROCm builds for Python 3.13 are available

---

## Recommendation

**For immediate development:** Use **Option 1** (CPU-only PyTorch)
- Works right now with your Python 3.13
- Sufficient for development and testing
- Easy to upgrade later

**For AMD GPU acceleration:** Use **Option 2** (pyenv) or **Option 3** (Deadsnakes PPA)
- Option 2 (pyenv) is more flexible and works on any Linux
- Option 3 (Deadsnakes) is faster if you're on Ubuntu/Debian

**For production:** Wait for **Option 4** (PyTorch Python 3.13 support)
- Most stable long-term solution
- No version management complexity

---

## Quick Start with CPU-Only (Recommended)

```bash
cd /home/dwolfson/localGit/egeria-v6/egeria-advisor
source .venv/bin/activate

# Install CPU-only PyTorch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Update config to use CPU
# Edit .env or config/advisor.yaml:
# EMBEDDING_DEVICE=cpu

# Test the setup
python scripts/test_setup.py
python -m advisor.data_prep.pipeline

# Run benchmark (will show CPU performance)
python scripts/benchmark_amd.py
```

This will get you up and running immediately, and you can add GPU support later when PyTorch supports Python 3.13 or after installing Python 3.12 via pyenv/deadsnakes.