#!/usr/bin/env python3
"""
CPU-only LLM throughput probe against a local Ollama server.

Forces num_gpu=0 so the model runs on CPU regardless of what accelerators
the host has, then reports prefill/generation throughput and time-to-first-
token for a ~5.3k-token prompt against llama3.1:8b.

Usage
-----
    python3 probe_llm_cpu.py

Each run uses a fresh prompt (a nonce in the text), because Ollama caches the
prompt prefix and an identical second run reports tens of thousands of tokens
per second of "prefill" — a cache hit, not a measurement. Record the run's own
numbers; `load` is reported separately so a cold run is still usable.
`--mode gpu` skips the num_gpu=0 override and measures whatever accelerator
Ollama picked (check `ollama ps`). Requires an Ollama server reachable at
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
import sys
import time
import urllib.request
import uuid

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL = "llama3.1:8b"


def build_prompt() -> str:
    # The nonce defeats Ollama's prompt-prefix cache; without it a repeated run
    # reports a cache hit as prefill throughput.
    text = f"Run {uuid.uuid4()}.\n" + ("Egeria is an open metadata and governance platform. " * 60 + "\n") * 8
    return text + "\nSummarize the above in one sentence."


def run_once(mode: str = "cpu"):
    options = {"num_predict": 60, "num_ctx": 8192}
    if mode == "cpu":
        options["num_gpu"] = 0
    body = json.dumps(
        {
            "model": MODEL,
            "prompt": build_prompt(),
            "stream": False,
            "options": options,
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
        "%s: prompt_tok=%d prefill_tok/s=%.0f gen_tok/s=%.1f total=%.1fs ttft=%.1fs load=%.1fs wall=%.1fs"
        % (mode, prompt_tok, prefill_tok_s, gen_tok_s, total_s, ttft_s, d["load_duration"] / 1e9, wall)
    )


if __name__ == "__main__":
    mode = "cpu"
    if "--mode" in sys.argv:
        mode = sys.argv[sys.argv.index("--mode") + 1]
    if mode not in ("cpu", "gpu"):
        sys.exit("usage: probe_llm_cpu.py [--mode cpu|gpu]")
    print("Run 1 (includes model load):")
    run_once(mode)
    print("Run 2 (warm, fresh prompt):")
    run_once(mode)
