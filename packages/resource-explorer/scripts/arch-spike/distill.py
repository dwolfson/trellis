#!/usr/bin/env python3
"""Distillation, the deterministic half — §5.2 steps 1 and the merge part of 2/3.

    python3 distill.py prometheus --root /path/to/checkout   # -> ir/prometheus-distilled.json

§5.2 divides the work: *"Heuristics own steps 1, 4, 5; the LLM owns 2 and 3 and
adjudicates ambiguous partitions."* Finding 76/77 measured the problem the
heuristic half has to solve — 3270 candidates for 6 declared components on
Kubernetes, which ranking narrows to hundreds rather than tens.

**This file exists to find out how far principled filtering gets before an LLM
is involved at all**, because every candidate it removes is one the adjudicator
never has to be shown, and because a deterministic rule can be regression-tested
against the pre-registered corpus where a prompt cannot.

Each filter is stated as a claim about what a component *is*, not as a tuning
knob, and each is measured separately so a filter that costs recall is visible
rather than buried in a blend.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

# Directory names that are never a component of the system in their own right.
# A component may CONTAIN tests or docs — Prometheus's `config/` owns
# `config/testdata/` and the ground truth says so — but a candidate whose files
# are *entirely* test or documentation material is describing the project's
# support material, not its architecture.
_SUPPORT_SEGMENTS = frozenset({
    "test", "tests", "testdata", "test_data", "fixtures", "e2e",
    "docs", "doc", "documentation", "examples", "example", "samples",
    "hack", "scripts", "tools", "vendor", "third_party", "mocks",
})


def _roots(comp: dict) -> list[str]:
    return [g.rstrip("/*").rstrip("/") for g in (comp.get("files") or []) if g]


def _is_support_only(comp: dict) -> bool:
    """Every declared root sits under a support directory."""
    roots = _roots(comp)
    if not roots:
        return False
    return all(any(seg in _SUPPORT_SEGMENTS for seg in r.split("/")) for r in roots)


def _claims_whole_repo(comp: dict) -> bool:
    """A candidate whose roots include the checkout root claims everything.

    The coupling proposer emits one of these on every target (`.`, globbing
    `cmd/**`, `staging/**`, ...). It is the same thing the npm detector calls a
    workspace root and `go_subsystems` calls a module root: **a container, not a
    component.** Removing it before anything else matters because a whole-repo
    claim makes every real component look like its refinement — measured on
    Kubernetes, where that alone collapsed 3303 candidates to 4 and took the
    entire ground truth with it.
    """
    return any(r == "" or r == "." for r in _roots(comp))


def _is_refinement(comp: dict, parent_roots: set[str]) -> bool:
    """Every root of this candidate lies strictly inside a CLASSIFIED parent.

    §2a says a refinement is legitimate, not wrong — and the union rule credits
    a set of children covering a parent. But when the parent is also present the
    children add nothing, and they are what turns 6 components into 3270.

    **`parent_roots` deliberately contains only candidates that carry a type.**
    An untyped blob is not a parent worth deferring to: `pkg` (proposed by
    coupling, type `?`) swallowed `pkg/scheduler`, which is half of Kubernetes'
    `kube-scheduler`. Deferring to a parent is a claim that the parent is the
    better answer, and that is only true when something actually classified it.
    """
    roots = _roots(comp)
    if not roots:
        return False
    for r in roots:
        parts = r.split("/")
        if not any("/".join(parts[:i]) in parent_roots for i in range(1, len(parts))):
            return False
    return True


FILTERS = {
    "support-only": _is_support_only,
    "refinement": None,      # needs the whole candidate set; handled in distill()
}


def distill(components: list[dict], drop_support: bool = True,
            drop_refinements: bool = True) -> tuple[list[dict], dict]:
    kept = list(components)
    stats = {"input": len(components)}

    if drop_support:
        before = len(kept)
        kept = [c for c in kept if not _is_support_only(c)]
        stats["dropped_support_only"] = before - len(kept)

    before = len(kept)
    kept = [c for c in kept if not _claims_whole_repo(c)]
    stats["dropped_whole_repo_claims"] = before - len(kept)

    if drop_refinements:
        parent_roots = {r for c in kept if c.get("type") for r in _roots(c)}
        before = len(kept)
        # MEASURED ALTERNATIVE, REJECTED: sparing refinements that carry a
        # type ("a classified child is a component in its own right") sounds
        # obviously right and is strictly worse on every axis — Kubernetes
        # 358 candidates at 6/6 became 762 at 5/6, Milvus 238 became 276 at the
        # same 3/5, and Prometheus did not recover the component it was meant
        # to save. Recorded rather than silently reverted: the intuition is
        # appealing enough that someone will try it again.
        kept = [c for c in kept if not _is_refinement(c, parent_roots)]
        stats["dropped_refinements"] = before - len(kept)

    stats["output"] = len(kept)
    return kept, stats


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("--keep-support", action="store_true")
    ap.add_argument("--keep-refinements", action="store_true")
    ap.add_argument("--out")
    args = ap.parse_args()

    path = os.path.join("ir", f"{args.target}.json")
    ir = json.load(open(path))
    kept, stats = distill(ir["components"],
                          drop_support=not args.keep_support,
                          drop_refinements=not args.keep_refinements)
    ir["components"] = kept
    ir["target"] = f"{args.target}-distilled"
    out = args.out or os.path.join("ir", f"{args.target}-distilled.json")
    json.dump(ir, open(out, "w"), indent=2)
    print(f"wrote {out}")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
