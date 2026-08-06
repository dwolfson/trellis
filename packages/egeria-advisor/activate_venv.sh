#!/bin/bash
# Quick activation script for the virtual environment
# Usage: source activate_venv.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PATH="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV_PATH" ]; then
    echo "❌ Virtual environment not found at $VENV_PATH"
    echo "Run: bash scripts/recreate_venv.sh"
    return 1
fi

source "$VENV_PATH/bin/activate"

echo "✓ Virtual environment activated"
echo "Python: $(python --version)"
echo "Location: $VIRTUAL_ENV"