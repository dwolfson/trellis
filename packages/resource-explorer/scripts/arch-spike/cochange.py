#!/usr/bin/env python3
"""Co-change coupling from git history — design §5.5 signal 2, plan §0(b).

    python3 cochange.py /path/to/checkout --target trellis   # -> signals/trellis-cochange.json

**Source is `git log --name-only` over the local checkout** (plan §2 — Phase
0 reads local checkouts already on disk; the `git_clone_root` provider is a
Phase 0.5 prerequisite for anything beyond the spike, not a Phase 0 need).
Do **not** use `project_commits` — plan §0(b): its schema (`registry.py:548`)
is `sha`/`message`/author/`committed_at`, no per-file change data at all.

**Window and large-commit exclusion, both as flags with stated defaults.**

- `--months` (default **24**) — bus-factor and churn questions concern
  recent history; mining the full log buys little and costs more.
- `--max-files` (default **50**) — a bulk reformat or a vendored-dependency
  drop touches everything it reformats/adds, and every file pair in that
  commit becomes spuriously "coupled" with equal strength to a real
  three-file change that expresses actual design coupling. The threshold is
  applied to the commit's **raw** `--name-only` file count, before the
  first-party filter, on purpose: a 600-file vendor-drop commit that reduces
  to 4 first-party files after filtering is still evidence of nothing about
  those 4 files' coupling to each other, and filtering first would let it
  through. 50 is a stated, arbitrary-but-documented threshold, not tuned
  against either target's score — changing it is a `--max-files` flag, not a
  code edit.
- `--no-merges` (default **on**) — a merge commit's `--name-only` diff over
  the merge (as opposed to over each parent) is not a reliable file-change
  list for co-change purposes.

**Normalisation.** Raw co-change counts favour churn-heavy files — two files
that are each touched in half the commits in the repo will co-occur often by
chance alone, independent of any real coupling. Reported alongside the raw
count is a **cosine-style strength**: `count(a,b) / sqrt(count(a) * count(b))`,
where `count(x)` is the number of (capped, filtered) commits touching `x`.
This is the standard code-maat/`import-linter`-adjacent normalisation for
co-change (0 = never coupled beyond chance, 1 = always changed together and
never apart) and is symmetric, which a raw count is not informative about on
its own.

First-party filtering reuses `exclusion.py` exactly as `imports.py` does —
vendored files must never enter the graph (task instructions), and the
large-commit cap independently keeps a vendor-drop from ever contributing
pairs even before the filter runs.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
from collections import Counter
from itertools import combinations

import exclusion

MERGE_COMMIT_MARKER = "\x00MERGE\x00"


def _run_git_log(root: str, months: int, no_merges: bool) -> str:
    args = ["git", "-C", root, "log", f"--since={months} months ago",
            "--name-only", "--pretty=format:COMMIT\x1f%H"]
    if no_merges:
        args.append("--no-merges")
    proc = subprocess.run(args, capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace"))
    return proc.stdout.decode("utf-8", "replace")


def _parse_commits(log_text: str) -> list[tuple[str, list[str]]]:
    """[(sha, [files]), ...] in the order git emitted them."""
    commits: list[tuple[str, list[str]]] = []
    sha = None
    files: list[str] = []
    for line in log_text.splitlines():
        if line.startswith("COMMIT\x1f"):
            if sha is not None:
                commits.append((sha, files))
            sha = line.split("\x1f", 1)[1]
            files = []
        elif line.strip():
            files.append(line.strip())
    if sha is not None:
        commits.append((sha, files))
    return commits


def build_cochange(root: str, first_party: list[str], months: int,
                    max_files: int, no_merges: bool) -> dict:
    fp_set = set(first_party)
    log_text = _run_git_log(root, months, no_merges)
    commits = _parse_commits(log_text)

    considered = 0
    skipped_large = 0
    skipped_empty = 0
    pair_counts: Counter[tuple[str, str]] = Counter()
    file_commit_counts: Counter[str] = Counter()
    large_commit_examples: list[dict] = []

    for sha, raw_files in commits:
        if len(raw_files) > max_files:
            skipped_large += 1
            if len(large_commit_examples) < 10:
                large_commit_examples.append({"sha": sha, "raw_file_count": len(raw_files)})
            continue
        fp_files = sorted({f for f in raw_files if f in fp_set})
        if len(fp_files) < 2:
            skipped_empty += 1
            continue
        considered += 1
        for f in fp_files:
            file_commit_counts[f] += 1
        for a, b in combinations(fp_files, 2):
            pair_counts[(a, b) if a < b else (b, a)] += 1

    pairs = []
    for (a, b), n in pair_counts.items():
        ca, cb = file_commit_counts[a], file_commit_counts[b]
        strength = n / math.sqrt(ca * cb) if ca and cb else 0.0
        pairs.append({"a": a, "b": b, "cochange_count": n,
                      "commits_a": ca, "commits_b": cb,
                      "strength": round(strength, 4)})
    pairs.sort(key=lambda p: p["strength"], reverse=True)

    return {
        "root": root,
        "window_months": months,
        "max_files_per_commit": max_files,
        "no_merges": no_merges,
        "commits_total": len(commits),
        "commits_considered": considered,
        "commits_skipped_large": skipped_large,
        "commits_skipped_single_or_no_first_party_file": skipped_empty,
        "large_commit_examples": large_commit_examples,
        "first_party_files_with_history": len(file_commit_counts),
        "pair_count": len(pairs),
        "pairs": pairs,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("root")
    ap.add_argument("--target", help="output filename stem; defaults to directory name")
    ap.add_argument("--out", default="signals")
    ap.add_argument("--months", type=int, default=24)
    ap.add_argument("--max-files", type=int, default=50,
                    help="commits touching more raw files than this are excluded (bulk "
                         "reformat / vendor-drop guard)")
    ap.add_argument("--merges", action="store_true", help="include merge commits (default: excluded)")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"not a directory: {args.root}", file=sys.stderr)
        return 2

    target = args.target or os.path.basename(os.path.abspath(args.root))
    census = exclusion.scan(args.root, tuple(args.exclude))
    if not census.tracked_by_git:
        print(f"not a git checkout: {args.root} — co-change needs `git log`", file=sys.stderr)
        return 2

    result = build_cochange(census.root, census.first_party, args.months,
                            args.max_files, not args.merges)
    result["target"] = target
    result["census"] = census.as_dict()

    if result["commits_total"] == 0:
        print("WARNING: zero commits in window — check --months and that this is a "
              "real git checkout, not a shallow clone (README finding 19: a zero is a "
              "finding, not a pass)", file=sys.stderr)
    elif result["pair_count"] == 0:
        print("WARNING: commits exist but zero co-change pairs survived filtering — "
              "either every commit touches <2 first-party files or every commit "
              "exceeded --max-files; investigate before trusting this as a real zero",
              file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{target}-cochange.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2)

    print(f"wrote {path}")
    print(f"  {result['commits_total']} commits in window, {result['commits_considered']} "
          f"considered ({result['commits_skipped_large']} skipped as too large, "
          f"{result['commits_skipped_single_or_no_first_party_file']} skipped as <2 first-party files)")
    print(f"  {result['pair_count']} co-change pairs over "
          f"{result['first_party_files_with_history']} files")
    if result["pairs"]:
        top = result["pairs"][0]
        print(f"  strongest: {top['a']} <-> {top['b']} "
              f"(strength={top['strength']}, n={top['cochange_count']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
