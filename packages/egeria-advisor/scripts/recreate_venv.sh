#!/bin/bash
# Script to recreate virtual environment with Python 3.12

set -e  # Exit on error

PROJECT_DIR="/home/dwolfson/localGit/egeria-v6/egeria-advisor"
VENV_DIR="$PROJECT_DIR/.venv"

echo "=========================================="
echo "Recreating Virtual Environment"
echo "=========================================="

# Check if Python 3.12 is installed
if ! command -v python3.12 &> /dev/null; then
    echo "❌ Python 3.12 not found!"
    echo ""
    echo "Install it with:"
    echo "  sudo apt update"
    echo "  sudo apt install python3.12 python3.12-venv python3.12-dev"
    exit 1
fi

echo "✓ Python 3.12 found: $(python3.12 --version)"

# Navigate to project directory
cd "$PROJECT_DIR"

# Remove old virtual environment if it exists
if [ -d "$VENV_DIR" ]; then
    echo ""
    echo "Removing old virtual environment..."
    rm -rf "$VENV_DIR"
    echo "✓ Old .venv removed"
fi

# Create new virtual environment with Python 3.12
echo ""
echo "Creating new virtual environment with Python 3.12..."
python3.12 -m venv .venv
echo "✓ Virtual environment created"

# Activate virtual environment
echo ""
echo "Activating virtual environment..."
source .venv/bin/activate

# Verify Python version
PYTHON_VERSION=$(python --version)
echo "✓ Active Python: $PYTHON_VERSION"

if [[ ! "$PYTHON_VERSION" =~ "Python 3.12" ]]; then
    echo "❌ ERROR: Virtual environment is not using Python 3.12!"
    exit 1
fi

# Upgrade pip
echo ""
echo "Upgrading pip..."
pip install --upgrade pip
echo "✓ pip upgraded"

# Install project dependencies
echo ""
echo "Installing project dependencies..."
pip install -e ".[dev]"
echo "✓ Dependencies installed"

# Show installed packages
echo ""
echo "=========================================="
echo "Installation Summary"
echo "=========================================="
python --version
pip --version
echo ""
echo "Key packages installed:"
pip list | grep -E "(torch|sentence-transformers|pydantic|loguru|pytest)" || echo "  (checking...)"

echo ""
echo "=========================================="
echo "✓ Virtual Environment Ready!"
echo "=========================================="
echo ""
echo "To activate the virtual environment:"
echo "  cd $PROJECT_DIR"
echo "  source .venv/bin/activate"
echo ""
echo "To install PyTorch with ROCm (for AMD GPU):"
echo "  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/rocm5.7"
echo ""
echo "To test the setup:"
echo "  python scripts/test_setup.py"
echo ""