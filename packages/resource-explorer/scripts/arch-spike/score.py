#!/usr/bin/env python3
"""Compare detector output against pre-registered ground truth — plan §5, §5a.

    python3 score.py trellis
    python3 score.py egeria-workspaces --gt-name egeria-workspaces

Reads `ir/{target}.json` (detect.py's output) and
`../../tests/fixtures/architecture-ground-truth/{target}.md`, and reuses that
fixture's own `validate.parse()` / `tracked_files()` / `expand()` rather than
writing a second parser — a file that validates is a file this script can
read (README.md).

Two measures, never mixed (plan §5a):

  - **Component-set agreement** — precision/recall/F1 on component *names*.
    Applies to every ground-truth component, including ones with no
    first-party files (kafka, postgres, kroki are third-party images; T1 is
    25-of-27 fileless). This is the only measure available for the
    `deployment` perspective.
  - **File-partition agreement** — Adjusted Rand Index + NMI over
    file→component assignment. Only for components that own file globs.
    Scored only over files BOTH sides assign (plan §5); coverage of each
    side is reported separately because a detector that confidently
    partitions 20% of the repo is a different failure from one that
    partitions all of it badly.

**Perspective is load-bearing (plan §5a).** The detectors in this slice read
manifests and deployment artifacts only — physical + deployment. A
ground-truth file declaring `Perspective: deployment` (egeria-workspaces) is
a genuine comparison. One declaring `Perspective: logical` (trellis) is not:
no detector targets the logical perspective yet (that is distillation, a
later phase), so that comparison is reported as a labelled DIAGNOSTIC and
never rolled into a pass/fail verdict — the exit criteria in plan §6 say so
explicitly.

**Provenance-split reporting.** Every ground-truth component carries a
`Provenance:` line. Scores are reported twice — `maintainer` tier (provenance
starts with "maintainer", however much an assistant filled in around it) and
`all` tier (every component, including assistant-authored ones) — so
assistant contamination is measured rather than denied (README.md).

Never edits a ground-truth file to improve a score. If a score looks wrong,
that is a finding for the Phase 0 write-up, not something this script fixes.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
GT_DIR = os.path.normpath(os.path.join(SPIKE_DIR, "..", "..", "tests",
                                        "fixtures", "architecture-ground-truth"))
sys.path.insert(0, GT_DIR)
import validate  # noqa: E402  (parse, tracked_files, expand, unquote, PLACEHOLDER)

try:
    from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score
except ImportError:  # pragma: no cover — sklearn is a resource-explorer dep already
    adjusted_rand_score = normalized_mutual_info_score = None


# ── loading ──────────────────────────────────────────────────────────────

def load_ir(target: str) -> dict:
    path = os.path.join(SPIKE_DIR, "ir", f"{target}.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_gt(gt_name: str) -> dict:
    path = os.path.join(GT_DIR, f"{gt_name}.md")
    return validate.parse(path)


def real_components(doc: dict) -> dict[str, dict]:
    return {n: c for n, c in doc["components"].items()
            if not validate.PLACEHOLDER.search(n)}


def provenance_tier(comp: dict) -> str:
    p = comp.get("provenance", "").strip().lower()
    return "maintainer" if p.startswith("maintainer") else "assistant"


# ── component-set agreement ─────────────────────────────────────────────

def component_set_score(gt_names: set[str], det_names: set[str]) -> dict:
    hit = gt_names & det_names
    missed = gt_names - det_names           # false negatives — GT said it exists, detector didn't find it
    spurious = det_names - gt_names         # false positives — detector invented/found something ungrounded
    precision = len(hit) / len(det_names) if det_names else 0.0
    recall = len(hit) / len(gt_names) if gt_names else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "gt_count": len(gt_names), "detected_count": len(det_names),
        "matched": len(hit), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
        "missed": sorted(missed), "spurious": sorted(spurious),
    }


# ── file-partition agreement ────────────────────────────────────────────

def file_assignment(components: dict[str, list[str]], root: str,
                     tracked: set[str] | None) -> dict[str, str]:
    """file -> owning component name, for the first component whose glob
    matches it (later components do not override — matches validate.py's
    own "claimed by both" warning semantics, first writer wins here)."""
    out: dict[str, str] = {}
    for name, globs in components.items():
        for g in globs:
            for hit in validate.expand(g, root, tracked):
                out.setdefault(hit, name)
    return out


def file_partition_score(gt_files: dict[str, str], det_files: dict[str, str]) -> dict:
    common = sorted(set(gt_files) & set(det_files))
    result = {
        "gt_assigned": len(gt_files), "detector_assigned": len(det_files),
        "common": len(common),
    }
    if not common or adjusted_rand_score is None:
        result["ari"] = result["nmi"] = None
        return result
    labels_gt = [gt_files[f] for f in common]
    labels_det = [det_files[f] for f in common]
    result["ari"] = round(adjusted_rand_score(labels_gt, labels_det), 4)
    result["nmi"] = round(normalized_mutual_info_score(labels_gt, labels_det), 4)
    return result


# ── driving one target ──────────────────────────────────────────────────

def score(target: str, gt_name: str, root_override: str | None) -> dict:
    ir = load_ir(target)
    doc = load_gt(gt_name)
    real = real_components(doc)

    perspective = doc["meta"].get("perspective", "logical").strip().lower()
    files_required = perspective in validate.FILES_REQUIRED
    diagnostic_only = perspective == "logical"
    # The detector slice reads manifests + deployment artifacts only (plan
    # §5a preface) — never the logical perspective. Any `logical`-perspective
    # ground truth is therefore a cross-perspective diagnostic, not a score.

    root = root_override or validate.unquote(doc["meta"].get("checkout", "")) or ir["checkout"]
    tracked = validate.tracked_files(root) if os.path.isdir(root) else None
    scope = doc["meta"].get("scope", "")
    if tracked is not None and scope:
        prefixes = ([validate.unquote(x).rstrip("/") for x in validate.CODE_SPAN.findall(scope)]
                    or [x.strip().rstrip("/") for x in scope.split(",") if x.strip()])
        if prefixes:
            tracked = {f for f in tracked
                       if any(f == p or f.startswith(p + "/") for p in prefixes)}

    # Scope narrowing (plan §5, GT README "Provenance"/"Scope") applies to the
    # detector side too. A component the detector found entirely outside the
    # ground-truth's declared Scope (e.g. `packages/egeria-advisor` for
    # trellis.md) is out of the experiment, not a miss or a false positive —
    # scoring it either way would be comparing against a denominator the GT
    # never claimed to cover.
    def in_scope(comp: dict) -> bool:
        if tracked is None or not comp["files"]:
            return True   # fileless (deployment perspective) or no scope info — always in scope
        return bool(file_assignment({comp["name"]: comp["files"]}, root, tracked))

    scoped_components = [c for c in ir["components"] if in_scope(c)] if root else ir["components"]
    det_names_all = {c["name"] for c in scoped_components}
    det_files_by_name = {c["name"]: c["files"] for c in scoped_components if c["files"]}
    det_file_map = file_assignment(det_files_by_name, root, tracked) if root and tracked is not None else {}

    out: dict = {
        "target": target, "gt_file": f"{gt_name}.md", "perspective": perspective,
        "diagnostic_only": diagnostic_only, "root": root,
        "in_scope_tracked": len(tracked) if tracked is not None else None,
        "tiers": {},
    }

    for tier in ("maintainer", "all"):
        tier_comps = {n: c for n, c in real.items()
                      if tier == "all" or provenance_tier(c) == "maintainer"}
        gt_names = set(tier_comps)
        cset = component_set_score(gt_names, det_names_all)

        fpart = None
        if files_required and root and tracked is not None:
            gt_files_by_name = {n: [f for f in c["files"] if not validate.PLACEHOLDER.search(f)]
                                 for n, c in tier_comps.items()}
            gt_files_by_name = {n: g for n, g in gt_files_by_name.items() if g}
            gt_file_map = file_assignment(gt_files_by_name, root, tracked)
            fpart = file_partition_score(gt_file_map, det_file_map)

        out["tiers"][tier] = {"component_set": cset, "file_partition": fpart}

    return out


def render(result: dict) -> str:
    lines = []
    tag = " [DIAGNOSTIC ONLY — logical GT vs physical/deployment detectors, not a pass/fail score]" \
        if result["diagnostic_only"] else ""
    lines.append(f"=== {result['target']} vs {result['gt_file']} "
                 f"(perspective={result['perspective']}){tag}")
    for tier_name, tier in result["tiers"].items():
        cs = tier["component_set"]
        lines.append(f"  [{tier_name}] component-set: "
                     f"{cs['matched']}/{cs['gt_count']} matched, "
                     f"precision={cs['precision']:.2f} recall={cs['recall']:.2f} "
                     f"f1={cs['f1']:.2f} ({cs['detected_count']} detected total)")
        if cs["missed"]:
            lines.append(f"    missed ({len(cs['missed'])}): {', '.join(cs['missed'][:12])}"
                         + (" ..." if len(cs["missed"]) > 12 else ""))
        if cs["spurious"]:
            lines.append(f"    spurious ({len(cs['spurious'])}): {', '.join(cs['spurious'][:12])}"
                         + (" ..." if len(cs["spurious"]) > 12 else ""))
        fp = tier["file_partition"]
        if fp is None:
            lines.append(f"    file-partition: N/A for perspective={result['perspective']} "
                         f"(plan §5a — component-set is the only applicable measure)")
        else:
            lines.append(f"    file-partition: ARI={fp['ari']} NMI={fp['nmi']} "
                         f"over {fp['common']} files both sides assign "
                         f"(gt={fp['gt_assigned']}, detector={fp['detector_assigned']})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", help="IR filename stem, e.g. trellis, egeria-workspaces")
    ap.add_argument("--gt-name", help="ground-truth filename stem, defaults to target")
    ap.add_argument("--root", help="override checkout root")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = score(args.target, args.gt_name or args.target, args.root)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
