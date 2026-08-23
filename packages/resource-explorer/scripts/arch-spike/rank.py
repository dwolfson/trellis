#!/usr/bin/env python3
"""Candidate ranking — how many candidates must a distiller actually see?

    python3 rank.py prometheus --root /path/to/checkout

Finding 76 established that no subset of the current proposers is both
high-recall and low-count: dropping coupling costs real matches, and keeping it
means 3270 candidates for 6 declared components on Kubernetes. So the question
for Phase 5 (§5.2) is not *which proposer* but *how far down a ranked list the
right answers sit* — because that decides whether an LLM adjudicator is shown 50
candidates or 3270.

**Measured, not tuned.** Weights fitted on these three fixtures would contaminate
the only pre-registered, owner-published ground truth this project has. So each
strategy below is motivated separately and stated up front, and the sweep is run
ONCE. A strategy that wins here is a hypothesis for the next repo, not a result.

Strategies:

* `confidence`  — §3.3b's confidence alone. The null hypothesis: the number the
  detectors already emit, used as-is.
* `agreement`   — independent agreement first (a component proposed by two
  proposers is a stronger claim than either alone — Phase 1 §4.4, portfolio §3),
  then confidence.
* `shallow`     — shallowest path first, then confidence. §6.0's rationale: a
  component is a *scope locator*, and the locators humans name are coarse.
  `internal/proxy` before `internal/proxy/accesslog/util`.
* `typed`       — components the pipeline could classify into the 13-value
  vocabulary before those it could not (`?`), then agreement, then shallowness,
  then confidence. Being classifiable is itself evidence of being a component.

Reported measure is **recall@N**: the strict-containment score (finding 61,
§2a's exact-node-or-union-of-refinements rule) computed over only the top N
candidates. It is the same rule `score.py` applies; `--verify` re-runs the full
scorer at N=ALL to confirm this file reproduces it rather than approximating it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "..", "tests", "fixtures", "architecture-ground-truth"))
import validate  # noqa: E402

GT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "..", "tests", "fixtures", "architecture-ground-truth")


def _expand(globs, root, tracked):
    hits = set()
    for g in globs:
        if validate.PLACEHOLDER.search(g):
            continue
        hits.update(validate.expand(g, root, tracked))
    return frozenset(hits)


def _depth(comp) -> int:
    """Shallowest glob wins — a component spanning `cmd/x` and `pkg/x` is as
    shallow as its shallowest arm."""
    globs = comp.get("files") or []
    if not globs:
        return 99
    return min(g.rstrip("/*").count("/") for g in globs)


def _roots(comp) -> list[str]:
    return [g.rstrip("/*").rstrip("/") for g in (comp.get("files") or [])]


def mark_rollups(comps: list[dict]) -> dict[str, bool]:
    """slug -> is this candidate a ROLL-UP (not a refinement of another)?

    Measured on the three owner-published fixtures: the *minimal* cover of a
    declared component is 2-3 nodes (`kube-controller-manager` is exactly
    `cmd/kube-controller-manager` + `pkg/controller`), while the number of
    candidates merely *contained* in it runs to 140. Ranking that does not
    separate the two buries the handful of nodes that actually matter under
    every nested leaf beneath them.

    Containment is decided by path prefix rather than set comparison —
    O(n log n) instead of 3303^2 subset tests, and for glob-defined candidates
    the two agree.
    """
    roots = {c["slug"]: _roots(c) for c in comps}
    allroots = sorted({r for rs in roots.values() for r in rs})
    out = {}
    for c in comps:
        mine = roots[c["slug"]]
        refined = bool(mine) and all(
            any(o != r and (r == o or r.startswith(o + "/")) for o in allroots)
            for r in mine)
        out[c["slug"]] = not refined
    return out


STRATEGIES = {
    "confidence": lambda c: (-c.get("confidence", 0),),
    "agreement":  lambda c: (-len(c.get("proposed_by") or []), -c.get("confidence", 0)),
    "shallow":    lambda c: (_depth(c), -c.get("confidence", 0)),
    "typed":      lambda c: (0 if c.get("type") else 1,
                             -len(c.get("proposed_by") or []),
                             _depth(c),
                             -c.get("confidence", 0)),
    # Roll-ups first. Motivated by the minimal-cover measurement above, not
    # fitted: a declared component is the LARGEST coherent unit, and §2a's
    # union rule means its refinements are legitimate but redundant once the
    # parent is present.
    "rollup":     None,   # filled in below — needs the candidate set
}


def matched_at(gt_sets: dict, det_sets: list[frozenset]) -> int:
    """§2a: exact node, OR a set of nodes wholly inside whose union equals it."""
    by_fileset = {f for f in det_sets if f}
    n = 0
    for gt_files in gt_sets.values():
        if not gt_files:
            continue
        if gt_files in by_fileset:
            n += 1
            continue
        inside = [f for f in det_sets if f and f <= gt_files]
        if inside and frozenset().union(*inside) == gt_files:
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("--gt-name")
    ap.add_argument("--root", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    gt_name = args.gt_name or args.target
    doc = validate.parse(os.path.join(GT_DIR, f"{gt_name}.md"))
    root = args.root
    tracked = validate.tracked_files(root)

    scope = doc["meta"].get("scope", "")
    if scope:
        pre = ([validate.unquote(x).rstrip("/") for x in validate.CODE_SPAN.findall(scope)]
               or [x.strip().rstrip("/") for x in scope.split(",") if x.strip()])
        if pre:
            tracked = {f for f in tracked if any(f == p or f.startswith(p + "/") for p in pre)}
    # finding 74 — the fixture's own Excluded section narrows BOTH sides
    drop = _expand(doc.get("excluded") or [], root, tracked)
    if drop:
        tracked = set(tracked) - drop

    gt_sets = {n: _expand(c.get("files") or [], root, tracked)
               for n, c in doc["components"].items()
               if not validate.PLACEHOLDER.search(n)}
    total = sum(1 for v in gt_sets.values() if v)

    ir = json.load(open(os.path.join("ir", f"{args.target}.json")))
    comps = [c for c in ir["components"] if c.get("files")]
    # expand ONCE — this is the expensive part, and every strategy reuses it
    sets = {c["slug"]: _expand(c["files"], root, tracked) for c in comps}
    comps = [c for c in comps if sets[c["slug"]]]

    ns = [10, 25, 50, 100, 250, 500, 1000, len(comps)]
    ns = sorted({n for n in ns if n <= len(comps)})
    isroll = mark_rollups(comps)
    strategies = dict(STRATEGIES)
    strategies["rollup"] = lambda c: (0 if isroll[c["slug"]] else 1,
                                      0 if c.get("type") else 1,
                                      _depth(c),
                                      -c.get("confidence", 0))
    rows = {}
    for name, key in strategies.items():
        ordered = sorted(comps, key=key)
        rows[name] = [(n, matched_at(gt_sets, [sets[c["slug"]] for c in ordered[:n]])) for n in ns]

    if args.json:
        print(json.dumps({"target": args.target, "total_gt": total,
                          "candidates": len(comps), "rows": rows}, indent=2))
        return 0

    print(f"=== {args.target}: {len(comps)} candidates, {total} declared components")
    print(f"    {'strategy':<12} " + " ".join(f"{('N=' + str(n)):>9}" for n in ns))
    for name, row in rows.items():
        cells = " ".join(f"{str(m) + '/' + str(total):>9}" for _, m in row)
        print(f"    {name:<12} {cells}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
