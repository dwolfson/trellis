# Virtual Environment Setup Guide

## Current Status
✅ Virtual environment created successfully at `.venv/`
✅ Python 3.12.12 installed
✅ All dependencies installed (egeria-advisor v0.1.0)
✅ VSCode configuration files created

## Quick Start

### Option 1: Use the activation script (Recommended)
```bash
source activate_venv.sh
```

### Option 2: Manual activation
```bash
source .venv/bin/activate
```

### Option 3: Direct Python execution (no activation needed)
```bash
.venv/bin/python your_script.py
```

## VSCode Integration

The following files have been created to help VSCode automatically detect and use the virtual environment:

1. **`.vscode/settings.json`** - Configures Python interpreter and terminal activation
2. **`.vscode/launch.json`** - Debug configurations for Python files and CLI
3. **`activate_venv.sh`** - Quick activation script

### To reload VSCode settings:
1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type "Reload Window" and select it
3. Or close and reopen VSCode

### To select the Python interpreter:
1. Press `Ctrl+Shift+P` (or `Cmd+Shift+P` on Mac)
2. Type "Python: Select Interpreter"
3. Choose `.venv/bin/python` (Python 3.12.12)

## Troubleshooting

### If terminal doesn't auto-activate:
1. Close all terminal windows in VSCode
2. Reload VSCode window (`Ctrl+Shift+P` → "Reload Window")
3. Open a new terminal (`Ctrl+` ` or Terminal → New Terminal)

### If "Refreshing virtual environments" hangs:
This is a VSCode Python extension issue. The virtual environment is actually ready!
- The venv exists at `.venv/`
- All packages are installed
- You can use it immediately with `source activate_venv.sh`

### Manual verification:
```bash
# Check Python version
.venv/bin/python --version

# Check installed packages
.venv/bin/pip list

# Check egeria-advisor installation
.venv/bin/pip show egeria-advisor

# Test the CLI
.venv/bin/egeria-advisor --help
```

## Next Steps

1. **Reload VSCode** to apply the new settings
2. **Open a new terminal** - it should auto-activate the venv
3. **Test the setup**:
   ```bash
   python scripts/test_setup.py
   ```

## Key Dependencies Installed

- pymilvus (vector database)
- docling (document processing)
- sentence-transformers (embeddings)
- langchain & langchain-community (LLM framework)
- ollama (local LLM client)
- mlflow (experiment tracking)
- click, rich, prompt-toolkit (CLI)
- pytest, black, ruff, mypy (dev tools)

## Environment Variables

Copy `.env.example` to `.env` and configure:
```bash
cp .env.example .env
# Edit .env with your settings
```

## Common Commands

```bash
# Activate venv
source activate_venv.sh

# Run tests
pytest

# Format code
black advisor/

# Lint code
ruff check advisor/

# Type check
mypy advisor/

# Run CLI
egeria-advisor --help