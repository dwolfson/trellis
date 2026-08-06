# Ollama Setup Guide

Egeria Advisor uses [Ollama](https://ollama.com/) for all local LLM inference. No cloud
API keys are required.

## Install

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Or run it in Docker:

```bash
docker run -d \
  --name ollama \
  -p 11434:11434 \
  -v ollama:/root/.ollama \
  --restart unless-stopped \
  ollama/ollama
```

## Required models

Egeria Advisor routes different tasks to different models (see `config/advisor.yaml` →
`llm.models`):

| Model | Used for |
|---|---|
| `llama3.1:8b` | RAG Q&A, routing, conversation — the high-volume path, tuned for speed |
| `qwen2.5-coder:32b` | LGCI planning — narrative generation, refinement, complex extraction |
| `codellama:13b` | Code generation and maintenance tasks |

Pull all three before starting the web UI:

```bash
ollama pull llama3.1:8b
ollama pull qwen2.5-coder:32b
ollama pull codellama:13b
```

`qwen2.5-coder:32b` is a large model (~20GB). If disk space or hardware is tight, the system
still runs with just `llama3.1:8b` pulled — planning quality (narrative text, multi-step
extraction) degrades, but RAG Q&A, code examples, and reports work normally.

## Verify

```bash
curl http://localhost:11434/api/tags
```

Should list all pulled models. If the web UI's MCP status dot or query responses report
connection errors, confirm Ollama is running and reachable at the `base_url` configured in
`config/advisor.yaml` (`llm.base_url`, default `http://localhost:11434`).

## GPU acceleration

Ollama automatically uses GPU acceleration (CUDA, ROCm, or Apple Metal) when available. See
`docs/design/AMD_OPTIMIZATION.md` for AMD-specific tuning notes. No configuration is needed
for NVIDIA/CUDA setups beyond having the drivers installed — Ollama detects and uses the GPU
automatically.

## Changing models

To use a different model for a given role, edit `config/advisor.yaml`:

```yaml
llm:
  models:
    query: llama3.1:8b
    code: codellama:13b
    conversation: llama3.1:8b
    maintenance: codellama:13b
    planning: qwen2.5-coder:32b
```

Pull the new model with `ollama pull <name>` first, then restart the web UI — models are
resolved once at process startup.
