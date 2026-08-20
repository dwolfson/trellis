#!/usr/bin/env python3
"""Run the detector pass over a target and emit the Architecture IR.

    python3 detect.py /path/to/checkout --target trellis --out ir/

Phase 0 plan §2: standalone and throwaway. No RE integration, no registry
writes, no Egeria, no Prefect, no network. Reads a local checkout, writes JSON.
"""
from __future__ import annotations

import argparse
import os
import sys

import exclusion
from detectors import build_components
from ir import IR


def run(root: str, target: str, extra_excludes: tuple[str, ...] = ()) -> IR:
    census = exclusion.scan(root, extra_excludes)
    components, evidence, notes = build_components(root, census.first_party)
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
