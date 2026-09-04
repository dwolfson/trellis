#!/usr/bin/env python3
"""
CPU-only LLM throughput probe against a local Ollama server.

Forces num_gpu=0 so the model runs on CPU regardless of what accelerators
the host has, then reports prefill/generation throughput and time-to-first-
token for a ~5.3k-token prompt against llama3.1:8b.

Usage
-----
    python3 probe_llm_cpu.py

Run it TWICE and record the second run's numbers — the first run pays for
model load into RAM. Requires an Ollama server reachable at
http://localhost:11434 with `llama3.1:8b` pulled (`ollama pull llama3.1:8b`).

Intended targets: the CPU-only Linux demo boxes named in
docs/runtime-architecture-plan.md ("Target environments" section) —
Framework 13 (host alias "framework") and Demo 2 (Intel box) — reached over
SSH per ~/.ssh/config. Do NOT run this against a host named "cray"; that is
a live demo machine. Before running remotely, confirm the host is reachable
and has ollama installed:

    ssh -o BatchMode=yes -o ConnectTimeout=5 <host> uname -a
    ssh <host> which ollama

Then either run this script over SSH (`ssh <host> python3 - < probe_llm_cpu.py`)
or copy it over and run it locally on the box. Also record on that host:
    nproc
    grep 'model name' /proc/cpuinfo | head -1
    free -g
"""
import json
import time
import urllib.request

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"


def build_prompt() -> str:
    text = ("Egeria is an open metadata and governance platform. " * 60 + "\n") * 8
    return text + "\nSummarize the above in one sentence."


def run_once():
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": build_prompt(),
            "stream": False,
            "options": {"num_predict": 60, "num_ctx": 8192, "num_gpu": 0},
        }
    ).encode()
    req = urllib.request.Request(
        OLLAMA_URL, body, {"Content-Type": "application/json"}
    )
    t0 = time.time()
    d = json.load(urllib.request.urlopen(req, timeout=1800))
    wall = time.time() - t0

    prompt_tok = d["prompt_eval_count"]
    prefill_tok_s = prompt_tok / (d["prompt_eval_duration"] / 1e9)
    gen_tok_s = d["eval_count"] / (d["eval_duration"] / 1e9)
    total_s = d["total_duration"] / 1e9
    ttft_s = (d["load_duration"] + d["prompt_eval_duration"]) / 1e9

    print(
        "prompt_tok=%d prefill_tok/s=%.0f gen_tok/s=%.1f total=%.1fs ttft=%.1fs wall=%.1fs"
        % (prompt_tok, prefill_tok_s, gen_tok_s, total_s, ttft_s, wall)
    )


if __name__ == "__main__":
    print("Run 1 (includes model load):")
    run_once()
    print("Run 2 (warm):")
    run_once()
