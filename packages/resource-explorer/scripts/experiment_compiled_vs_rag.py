"""Experiment: do compiled-evidence answers beat RAG-only answers?

context-compilation-design.md §9 asks it; docs/experiments/compiled-vs-rag.md
is the protocol. This script runs it.

Two conditions, one variable. Both use ConversationAgent with the same tools,
prompt shape, model and tier; the only difference is `compiled_evidence`:

    compiled   evidence packed from stored analysis results is in the prompt,
               gaps named (production behaviour)
    rag        the agent gets no compiled evidence and must search collections
               itself (the pre-2026-08-30 behaviour)

Every (repo, question, condition) produces one JSONL row with the answer, the
latency, the compile_id the agent used (compiled condition) and a REFERENCE
compile — the manifest a compile would produce for that question regardless of
condition — so the judge can check gap acknowledgement against ground truth
for both conditions. A judge model scores each row on a fixed rubric and the
script reports per-condition means, overall and by how the catalog says the
question is answerable (analysis / direct / human / mixed / gap ...).

Resumable: rows already in the output file are skipped, keyed on
(repo, question, condition). Run it with --limit first.

    uv run python scripts/experiment_compiled_vs_rag.py --repos egeria_python_git --limit 3
    uv run python scripts/experiment_compiled_vs_rag.py --repos egeria_python_git,kafka,docling
    uv run python scripts/experiment_compiled_vs_rag.py --summarise   # re-read results, print tables
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import statistics
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests

CONDITIONS = ("compiled", "rag")
#: Bump when JUDGE_PROMPT changes in a way that alters scores; every judged row
#: carries it, so runs judged under different rubrics are never averaged together.
RUBRIC_VERSION = "v2-2026-09-08"
DEFAULT_REPOS = "egeria_python_git,kafka,docling"
DEFAULT_OUT = Path("data/experiments/compiled_vs_rag")
JUDGE_MODEL = os.environ.get("EXPERIMENT_JUDGE_MODEL", "qwen2.5:32b")
OLLAMA = os.environ.get("LLM__OLLAMA__BASE_URL", os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434"))

JUDGE_PROMPT = """You are grading an assistant's answer about a software repository. Be strict and literal. Grade CONTENT, never fluency: two answers that say the same thing must get the same scores however they are phrased, and a hedged or specific correct statement is never worse than a confident general one.

QUESTION: {question}

WHAT THE SYSTEM ACTUALLY HAS STORED FOR THIS REPOSITORY (ground truth, from the analysis registry):
- Analyses with stored results that were available as evidence: {packed}
- Analyses with NO usable result for this repository (each one is a GAP): {gaps}
  (states: never_run = never executed; nothing_found = ran and found nothing; not_established = ran but cannot be credited; partial)

ASSISTANT'S ANSWER:
\"\"\"{answer}\"\"\"

Return ONLY a JSON object with these keys:
- "declines": true/false — does the answer decline to answer, saying the evidence or stored analyses do not cover the question (in any wording)?
- "answers_question": 0, 1 or 2. If it does NOT decline: 2 = directly and usefully answers what was asked; 1 = partially; 0 = does not address it. If it DOES decline: 2 = declines AND names which analysis would answer it and/or what would have to run; 1 = declines and grounds the refusal in what is or is not stored; 0 = a bare refusal with no grounding. Never score a refusal higher for sounding thorough, and never score a guess higher for sounding confident.
- "cites_evidence": true/false — the answer names a specific analysis, finding, file, metric or source FOR A CLAIM IT MAKES. Naming analyses only to say they were not used does not count.
- "missing_result_claims": list of gap analysis ids (from the GAP list above, exact ids) for which the answer states a concrete result AS IF MEASURED. This INCLUDES asserting absence or a zero — e.g. "there is no telemetry", "no CVEs were found", "provenance is handled via CLA" — for a gap whose state is never_run or not_established. Check every gap in the list individually. Empty list if none.
- "claims_missing_result": true if missing_result_claims is non-empty, else false.
- "acknowledges_limits": true/false — the answer says what it could not determine, what has not been checked, what is unknown or not available, or that the evidence does not cover the question. Any such hedge-shaped statement counts, including "no information available" and "not available in the provided data".
- "unsupported_claims": integer — count of specific factual claims (numbers, names, findings, described features, asserted absences) not attributable to the stored evidence listed above or to general knowledge clearly labelled as such. A statement that evidence is missing or does not cover the question is NOT a claim (count 0 for it). Every entry in missing_result_claims is also an unsupported claim; keep the two consistent.
- "rationale": one sentence.
"""


def _sha(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()[:12]


def load_questions(limit: int | None, seed: int) -> list[dict]:
    from resource_explorer.surveyors.question_catalog_reader import get_questions
    entries = get_questions("repo", perspectives=None, purposes=None)
    rows = []
    for e in entries:
        answering = e.get("answering") or {}
        rows.append({
            "question": e["question"],
            "stage": e.get("stage", ""),
            "answering_kind": answering.get("kind", "") if isinstance(answering, dict) else str(answering),
        })
    rng = random.Random(seed)
    rng.shuffle(rows)  # order must not correlate with catalog position
    return rows[:limit] if limit else rows


def reference_compile(registry, slug: str, question: str) -> dict:
    """The manifest a compile produces for this question — ground truth for
    the judge in BOTH conditions. Persisted like any compile (same id as the
    agent's own compile in the compiled condition, so `hits` goes up)."""
    from resource_explorer.context_compile import compile_context
    c = compile_context(registry, slug, question, perspectives=[], budget=6000,
                        session_id="experiment:compiled_vs_rag")
    packed = [p["key"] for p in c.manifest.get("packed", []) if p.get("role") == "evidence"]
    # The rung each section was packed at. Without it, "the rung was too
    # coarse to answer" cannot be told apart from "the model ignored it"
    # (audit of run full-20260908, cause C unfalsifiable).
    rungs = {p["key"]: str(p.get("rung")) for p in c.manifest.get("packed", []) if p.get("role") == "evidence"}
    gaps = [{"key": g["key"], "state": g.get("state"), "reason": g.get("reason")} for g in c.manifest.get("gaps", [])]
    return {"compile_id": c.compile_id, "packed": packed, "rungs": rungs, "gaps": gaps,
            "used": c.manifest.get("used"), "budget": c.manifest.get("budget")}


def answer(slug: str, question: str, condition: str) -> tuple[str, float, str | None]:
    from resource_explorer.agents.conversation_agent import ConversationAgent
    agent = ConversationAgent(resource_slug=slug, compiled_evidence=(condition == "compiled"))
    agent.session_id = f"experiment:compiled_vs_rag:{condition}"
    t0 = time.perf_counter()
    text = agent.handle(question, resource_slug=slug, perspectives=[])
    latency = time.perf_counter() - t0
    compiled = getattr(agent, "_last_compiled", None)
    return text, latency, getattr(compiled, "compile_id", None)


def judge(question: str, answer_text: str, ref: dict) -> dict:
    prompt = JUDGE_PROMPT.format(
        question=question,
        packed=", ".join(ref["packed"]) or "(none)",
        gaps=", ".join(f'{g["key"]} ({g["state"]})' for g in ref["gaps"]) or "(none)",
        answer=answer_text[:6000],
    )
    r = requests.post(f"{OLLAMA}/api/generate", json={
        "model": JUDGE_MODEL, "prompt": prompt, "stream": False, "format": "json",
        "options": {"temperature": 0, "num_ctx": 8192},
    }, timeout=600)
    r.raise_for_status()
    raw = r.json().get("response", "{}")
    try:
        out = json.loads(raw)
    except json.JSONDecodeError:
        out = {"parse_error": raw[:300]}
    out["judge_model"] = JUDGE_MODEL
    out["rubric_version"] = RUBRIC_VERSION
    return out


def rejudge(args) -> None:
    """Re-score existing answers under the current rubric; nothing is re-answered.

    Reads <out>/results.jsonl, writes <out>/results.<RUBRIC_VERSION>.jsonl with
    the same rows and a fresh `judge`, keeping the previous verdict under
    `judge_previous` so rubric changes are auditable row by row. Resumable.
    """
    src = Path(args.out) / "results.jsonl"
    dst = Path(args.out) / f"results.{RUBRIC_VERSION}.jsonl"
    done = set()
    if dst.exists():
        for line in dst.read_text().splitlines():
            if line.strip():
                r = json.loads(line); done.add((r["repo"], r["question"], r["condition"]))
    rows = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]
    print(f"re-judging {len(rows)} rows under {RUBRIC_VERSION} with {JUDGE_MODEL}; {len(done)} already done", flush=True)
    for i, r in enumerate(rows, 1):
        key = (r["repo"], r["question"], r["condition"])
        if key in done:
            continue
        if r["answer"].startswith("[ERROR]"):
            verdict = {"skipped": "answer errored"}
        else:
            verdict = judge(r["question"], r["answer"], r["reference"])
        new = dict(r); new["judge_previous"] = r.get("judge"); new["judge"] = verdict
        with dst.open("a") as f:
            f.write(json.dumps(new, default=str) + "\n")
        v = verdict
        print(f"[{i}/{len(rows)}] {r['repo']} | {r['condition']:8s} | aq={v.get('answers_question')} "
              f"cites={v.get('cites_evidence')} missing={v.get('claims_missing_result')} "
              f"limits={v.get('acknowledges_limits')} | {r['question'][:60]}", flush=True)
    summarise(dst, args)


def run(args) -> None:
    from resource_explorer.registry import ProjectRegistry
    registry = ProjectRegistry()
    out_dir = Path(args.out); out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "results.jsonl"
    done = set()
    if out.exists():
        for line in out.read_text().splitlines():
            if line.strip():
                r = json.loads(line); done.add((r["repo"], r["question"], r["condition"]))
    repos = [s.strip() for s in args.repos.split(",") if s.strip()]
    for slug in repos:
        if registry.get(slug) is None:
            sys.exit(f"unknown resource slug: {slug}")
    questions = load_questions(args.limit, args.seed)
    total = len(repos) * len(questions) * len(CONDITIONS)
    print(f"{len(repos)} repos x {len(questions)} questions x {len(CONDITIONS)} conditions = {total} rows; "
          f"{len(done)} already done; judge={JUDGE_MODEL}", flush=True)
    if args.dry_run:
        return
    i = 0
    for slug in repos:
        for q in questions:
            ref = None
            for condition in CONDITIONS:
                i += 1
                key = (slug, q["question"], condition)
                if key in done:
                    continue
                if ref is None:
                    ref = reference_compile(registry, slug, q["question"])
                try:
                    text, latency, cid = answer(slug, q["question"], condition)
                except Exception as exc:  # record the failure as a row; do not stop the run
                    text, latency, cid = f"[ERROR] {type(exc).__name__}: {exc}", 0.0, None
                verdict = judge(q["question"], text, ref) if not text.startswith("[ERROR]") else {"skipped": "answer errored"}
                row = {
                    "run_id": args.run_id, "ts": datetime.now(timezone.utc).isoformat(),
                    "repo": slug, "question": q["question"], "stage": q["stage"],
                    "answering_kind": q["answering_kind"], "condition": condition,
                    "answer": text, "latency_s": round(latency, 2),
                    "agent_compile_id": cid, "reference": ref,
                    "compile_id_matches_reference": (cid == ref["compile_id"]) if cid else None,
                    "judge": verdict,
                }
                with out.open("a") as f:
                    f.write(json.dumps(row, default=str) + "\n")
                done.add(key)
                v = verdict if isinstance(verdict, dict) else {}
                print(f"[{i}/{total}] {slug} | {condition:8s} | {latency:5.1f}s | aq={v.get('answers_question')} "
                      f"cites={v.get('cites_evidence')} missing={v.get('claims_missing_result')} "
                      f"unsupported={v.get('unsupported_claims')} | {q['question'][:60]}", flush=True)
    summarise(out, args)


def summarise(out: Path, args=None) -> None:
    rows = [json.loads(l) for l in out.read_text().splitlines() if l.strip()]
    rows = [r for r in rows if isinstance(r.get("judge"), dict) and "answers_question" in r["judge"]]
    if not rows:
        print("no judged rows yet"); return

    def agg(sub):
        j = [r["judge"] for r in sub]
        n = len(j)
        return {
            "n": n,
            "answers_question(0-2)": round(statistics.mean(float(x.get("answers_question") or 0) for x in j), 2),
            "cites_evidence%": round(100 * sum(bool(x.get("cites_evidence")) for x in j) / n),
            "claims_missing_result%": round(100 * sum(bool(x.get("claims_missing_result")) for x in j) / n),
            "acknowledges_limits%": round(100 * sum(bool(x.get("acknowledges_limits")) for x in j) / n),
            "unsupported_claims(mean)": round(statistics.mean(float(x.get("unsupported_claims") or 0) for x in j), 2),
            "latency_s(median)": round(statistics.median(r["latency_s"] for r in sub), 1),
        }

    print("\n=== By condition ===")
    table = {c: agg([r for r in rows if r["condition"] == c]) for c in CONDITIONS if any(r["condition"] == c for r in rows)}
    keys = list(next(iter(table.values())).keys())
    print(f"{'metric':28s} " + " ".join(f"{c:>10s}" for c in table))
    for k in keys:
        print(f"{k:28s} " + " ".join(f"{str(table[c][k]):>10s}" for c in table))
    print("\n=== By answering kind (compiled vs rag) ===")
    kinds = sorted({r["answering_kind"] for r in rows})
    for kind in kinds:
        parts = []
        for c in CONDITIONS:
            sub = [r for r in rows if r["condition"] == c and r["answering_kind"] == kind]
            if sub:
                a = agg(sub)
                parts.append(f"{c}: n={a['n']} aq={a['answers_question(0-2)']} cites={a['cites_evidence%']}% missing={a['claims_missing_result%']}% unsup={a['unsupported_claims(mean)']}")
        print(f"{kind:10s} | " + " || ".join(parts))
    matches = [r for r in rows if r["condition"] == "compiled" and r.get("compile_id_matches_reference") is not None]
    if matches:
        ok = sum(1 for r in matches if r["compile_id_matches_reference"])
        print(f"\nreplayability: agent compile id == reference compile id in {ok}/{len(matches)} compiled rows")
    _mlflow(table, rows, args)


def _mlflow(table: dict, rows: list, args) -> None:
    try:
        from resource_explorer.config import get_config
        from resource_explorer.observability.reachability import endpoint_reachable
        cfg = get_config().observability.mlflow
        if not cfg.enabled or not endpoint_reachable(cfg.tracking_uri):
            print("(mlflow not reachable; skipped)"); return
        import mlflow
        mlflow.set_tracking_uri(cfg.tracking_uri)
        mlflow.set_experiment("compiled_vs_rag")
        for cond, m in table.items():
            with mlflow.start_run(run_name=f"{getattr(args, 'run_id', 'run')}-{cond}"):
                mlflow.log_params({"condition": cond, "judge_model": JUDGE_MODEL,
                                   "repos": getattr(args, "repos", ""), "n": m["n"]})
                mlflow.log_metrics({k.split("(")[0].replace("%", "_pct"): float(v) for k, v in m.items() if k != "n"})
        print(f"(mlflow: logged {len(table)} runs to experiment compiled_vs_rag)")
    except Exception as exc:
        print(f"(mlflow logging skipped: {exc})")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repos", default=DEFAULT_REPOS)
    ap.add_argument("--limit", type=int, default=None, help="first N questions (after a seeded shuffle)")
    ap.add_argument("--seed", type=int, default=20260908)
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--run-id", default=datetime.now().strftime("%Y%m%d-%H%M"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--summarise", action="store_true", help="only re-read results and print the tables")
    ap.add_argument("--summarise-file", default=None, help="results file to summarise (default results.jsonl)")
    ap.add_argument("--rejudge", action="store_true", help="re-score existing answers under the current rubric")
    args = ap.parse_args()
    if args.summarise:
        summarise(Path(args.summarise_file) if args.summarise_file else Path(args.out) / "results.jsonl", args); return
    if args.rejudge:
        rejudge(args); return
    run(args)


if __name__ == "__main__":
    main()
