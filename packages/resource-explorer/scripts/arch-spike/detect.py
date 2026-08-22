#!/usr/bin/env python3
"""Run the detector pass over a target and emit the Architecture IR.

    python3 detect.py /path/to/checkout --target trellis --out ir/

Phase 0 plan §2: standalone and throwaway. No RE integration, no registry
writes, no Egeria, no Prefect, no network. Reads a local checkout, writes JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import exclusion
from detectors import build_components, python_manifests
from ir import IR

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
SIGNALS_DIR = os.path.join(SPIKE_DIR, "signals")


def _coupling_components(root: str, target: str, first_party: list[str]) -> tuple[list, list, list]:
    """§4.1 — coupling as proposer. Optional: only runs when `imports.py` has
    already been run for this target (`signals/{target}-imports.json`), same
    graceful-absence pattern `code_markers.scan` uses for a missing ast-grep
    binary — a missing precomputed signal is a note, not an error, so targets
    with no signal file (or no Python) still produce a valid IR.

    **Uses the package's `coupling.propose()`, not this directory's own
    (stale) `coupling.py`.** The two diverged: the local copy predates the
    hierarchy work (`parent_slug`/`depth`, `_component_globs`,
    `_rehome_dropped`) and the 2026-08-22 co-change rescue (design §4.1d,
    finding 63) — both live only in `resource_explorer/surveyors/
    arch_recovery/coupling.py` now. Scoring against the stale local version
    would silently measure last month's proposer, not the one the task
    (and the sub-surveyor that actually runs in RE) uses. The local
    `coupling.py` is untouched — it is still the Task 3 boundary-scoring
    harness (`python3 coupling.py trellis`), a separate diagnostic this
    function never used anyway.

    Co-change is loaded the same optional way as imports
    (`signals/{target}-cochange.json`) and passed through — absent, it is
    simply `[]` and `propose()` behaves exactly as it did import-only.
    """
    path = os.path.join(SIGNALS_DIR, f"{target}-imports.json")
    if not os.path.isfile(path):
        return [], [], [f"coupling: no signals/{target}-imports.json — run imports.py "
                        f"first; coupling proposer skipped"]
    with open(path, encoding="utf-8") as fh:
        sig = json.load(fh)
    cochange_path = os.path.join(SIGNALS_DIR, f"{target}-cochange.json")
    cochange_pairs: list = []
    if os.path.isfile(cochange_path):
        with open(cochange_path, encoding="utf-8") as fh:
            cochange_pairs = json.load(fh).get("pairs", [])
    from resource_explorer.surveyors.arch_recovery import coupling  # local import: same
    # graceful-absence style as the stale-copy note above explains
    package_roots = sorted({m["dir"] for m in python_manifests(root, first_party)}) or ["."]
    return coupling.propose(set(first_party), package_roots, sig.get("edges", []), cochange_pairs)


def _merge_agreeing(components: list) -> tuple[list, list]:
    """Collapse components that different approaches proposed for the SAME
    file set, and treat the agreement as evidence rather than as a duplicate.

    Independent approaches converging on one boundary is the strongest signal
    this design produces — it is what the portfolio model (see
    docs/approach-portfolio-model.md) exists to exploit — and before this it
    surfaced as two rows in the IR and a double-count in every score.

    Merge rules, in order of what each approach can honestly contribute:

    - **Type comes from whichever approach can supply one.** A code marker
      knows a subtree serves HTTP; coupling knows only *where* a boundary is,
      never what kind of thing sits inside it. So a marker-derived type wins
      over `None`, and coupling-only components keep `None` rather than being
      given a guessed type — classification is distillation's job (§5.2).
    - **Confidence rises with agreement**, capped at 95: two independent
      approaches agreeing is worth more than either alone, but never certainty.
    - **Every contributing slug is kept** in `proposed_by`, because Phase 1
      §4.4 wants the portfolio legible — which approach found what is a
      first-class question, not debug output.
    """
    by_files: dict[tuple, list] = {}
    for c in components:
        by_files.setdefault(tuple(sorted(c.files)), []).append(c)

    merged, notes = [], []
    for files, group in by_files.items():
        if len(group) == 1 or not files:
            merged.extend(group)
            continue
        typed = next((c for c in group if c.type is not None), None)
        winner = typed or group[0]
        winner.confidence = min(95, max(c.confidence for c in group) + 10 * (len(group) - 1))
        winner.proposed_by = sorted({c.slug.split("::")[0] for c in group})
        merged.append(winner)
        notes.append(f"{files[0]}: proposed independently by "
                     f"{', '.join(winner.proposed_by)} — merged, confidence raised to "
                     f"{winner.confidence}")
    return merged, notes


def run(root: str, target: str, extra_excludes: tuple[str, ...] = ()) -> IR:
    census = exclusion.scan(root, extra_excludes)
    components, evidence, notes = build_components(root, census.first_party)

    cc, ce, cn = _coupling_components(root, target, census.first_party)
    components.extend(cc)
    evidence.extend(ce)
    notes.extend(cn)

    components, merge_notes = _merge_agreeing(components)
    notes.extend(merge_notes)
    ir = IR(target=target, checkout=census.root, census=census.as_dict(),
            components=components, evidence=evidence, notes=notes)
    if census.first_party_ratio < 0.5:
        # plan §3a — make it loud rather than letting a shrunken corpus pass silently
        ir.notes.insert(0, f"WARNING: only {100*census.first_party_ratio:.1f}% of tracked "
                            f"files are first-party; check the exclusion rules")
    return ir


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("--target", help="name for the IR; defaults to the directory name")
    ap.add_argument("--out", default="ir", help="output directory (default: ir/)")
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--stdout", action="store_true", help="print IR instead of writing")
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"not a directory: {args.root}", file=sys.stderr)
        return 2

    target = args.target or os.path.basename(os.path.abspath(args.root))
    ir = run(args.root, target, tuple(args.exclude))

    if args.stdout:
        print(ir.to_json())
    else:
        os.makedirs(args.out, exist_ok=True)
        path = os.path.join(args.out, f"{target}.json")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(ir.to_json())
        print(f"wrote {path}")

    print(f"  {ir.census['first_party']}/{ir.census['total']} first-party files")
    print(f"  {len(ir.components)} components, {len(ir.evidence)} evidence records")
    by_type: dict[str, int] = {}
    for c in ir.components:
        by_type[c.type or "?"] = by_type.get(c.type or "?", 0) + 1
    for t, n in sorted(by_type.items(), key=lambda kv: -kv[1]):
        print(f"    {n:>3}  {t}")
    for n in ir.notes:
        print(f"  note: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
