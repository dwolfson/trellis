#!/usr/bin/env python3
"""Task 3 — score a partition against the two §5.5 signals, and ask the
question the plan calls the highest-value output: does either signal suggest
a boundary that neither the detectors nor the ground truth proposed?

    python3 coupling.py trellis
    python3 coupling.py egeria-workspaces --gt-name egeria-workspaces

Two things, both reading `signals/{target}-imports.json` and
`signals/{target}-cochange.json` (build them first with `imports.py` /
`cochange.py`):

1. **Cross-boundary edge ratio for a *given* partition** (`boundary_stats`) —
   fraction of import weight / co-change weight that crosses a component
   boundary, for the detector's partition and for the ground truth's, so the
   two are directly comparable. Low crossing = a partition the signals agree
   with; high crossing = a partition the signals contradict, regardless of
   what a manifest or a human said.

2. **Candidate boundaries neither side proposed** (`candidate_boundaries`) —
   the interesting one. Deliberately does NOT run general-purpose graph
   clustering (Louvain etc. — an extra dependency and a tuning surface this
   spike does not need). Instead it reuses the **exact same structural rule**
   `code_markers.py` already uses to decide how far up a marker attributes —
   top-level subpackage beneath the nearest manifest root, from
   `code_markers._subtree_for` — so a candidate subtree here is directly
   comparable to a code-marker component, not an apples-to-oranges cluster
   boundary. For each such subtree, compute import-cohesion and
   cochange-cohesion (internal weight / (internal + boundary weight)), then
   label it against both the detector IR and the ground truth:

   - **recovered** — high cohesion, IR proposed it too (agreement, not news)
   - **signal-only** — high cohesion, ground truth names it, detector did not
     (the qualified-pass gap from README finding 20 — exactly what plan Task
     3 asks to check for)
   - **novel** — high cohesion, NEITHER side names it (a boundary the repo's
     structure has that nobody — human or detector — wrote down)
   - low cohesion is reported too, unlabelled, so a silent filter never hides
     a negative result (README finding 19 — a zero is a finding).

Cohesion threshold is a flag (`--min-cohesion`, default 0.5) with a stated
default, not tuned to make either target's numbers look better (task rule:
never tune to improve a score) — 0.5 means "most of this subtree's traffic
with the rest of the repo, by weight, stays inside it," which is the plain
reading of "coupling proposes this as a component."
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
GT_DIR = os.path.normpath(os.path.join(SPIKE_DIR, "..", "..", "tests",
                                        "fixtures", "architecture-ground-truth"))
sys.path.insert(0, GT_DIR)
import validate  # noqa: E402

import detectors
from code_markers import _subtree_for


# ── loading ──────────────────────────────────────────────────────────────

def load_signal(target: str, kind: str) -> dict | None:
    path = os.path.join(SPIKE_DIR, "signals", f"{target}-{kind}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_ir(target: str) -> dict | None:
    path = os.path.join(SPIKE_DIR, "ir", f"{target}.json")
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


# ── Task 3.1 — cross-boundary ratio for a given partition ────────────────

def file_assignment_from_components(components: dict[str, list[str]], root: str,
                                    tracked: set[str] | None) -> dict[str, str]:
    out: dict[str, str] = {}
    for name, globs in components.items():
        for g in globs:
            for hit in validate.expand(g, root, tracked):
                out.setdefault(hit, name)
    return out


def boundary_stats_imports(file_component: dict[str, str], edges: list[dict]) -> dict:
    internal = boundary = 0
    internal_n = boundary_n = 0
    for e in edges:
        ca, cb = file_component.get(e["source"]), file_component.get(e["target"])
        if ca is None or cb is None:
            continue
        w = e.get("weight", 1)
        if ca == cb:
            internal += w
            internal_n += 1
        else:
            boundary += w
            boundary_n += 1
    total = internal + boundary
    return {
        "scored_edges": internal_n + boundary_n,
        "internal_weight": internal, "boundary_weight": boundary,
        "cross_boundary_ratio": round(boundary / total, 4) if total else None,
    }


def boundary_stats_cochange(file_component: dict[str, str], pairs: list[dict]) -> dict:
    internal = boundary = 0.0
    internal_n = boundary_n = 0
    for p in pairs:
        ca, cb = file_component.get(p["a"]), file_component.get(p["b"])
        if ca is None or cb is None:
            continue
        w = p.get("cochange_count", 1)
        if ca == cb:
            internal += w
            internal_n += 1
        else:
            boundary += w
            boundary_n += 1
    total = internal + boundary
    return {
        "scored_pairs": internal_n + boundary_n,
        "internal_weight": internal, "boundary_weight": boundary,
        "cross_boundary_ratio": round(boundary / total, 4) if total else None,
    }


# ── Task 3.2 — candidate boundaries neither side proposed ────────────────

def candidate_subtrees(files: list[str], package_roots: list[str]) -> dict[str, str]:
    """file -> subtree, same rule code_markers.py uses to attribute a marker
    (top-level subpackage beneath the nearest manifest root). Files with no
    enclosing package root are excluded (None)."""
    out = {}
    for f in files:
        sub = _subtree_for(f, package_roots)
        if sub is not None:
            out[f] = sub
    return out


def cohesion_table(file_subtree: dict[str, str], edges: list[dict],
                   src_key: str, tgt_key: str, weight_key: str) -> dict[str, dict]:
    table: dict[str, dict] = {}
    for e in edges:
        sa, sb = file_subtree.get(e[src_key]), file_subtree.get(e[tgt_key])
        if sa is None and sb is None:
            continue
        w = e.get(weight_key, 1)
        for sub in {s for s in (sa, sb) if s is not None}:
            row = table.setdefault(sub, {"internal": 0, "boundary": 0})
            if sa == sb:
                row["internal"] += w
            else:
                row["boundary"] += w
    for sub, row in table.items():
        total = row["internal"] + row["boundary"]
        row["cohesion"] = round(row["internal"] / total, 4) if total else 0.0
        row["total_weight"] = total
    return table


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def _containment(candidate: set[str], component: set[str]) -> float:
    """How much of `candidate` lies inside `component` — |A n B| / |A|.

    Directional on purpose (see MATCH_THRESHOLD). Answers "is this candidate
    part of that component?", which is the question being asked, rather than
    "are these two sets similar?", which is not.
    """
    return len(candidate & component) / len(candidate) if candidate else 0.0


# Jaccard, not directional overlap. Directional (intersection / len(subtree))
# was tried first and was wrong: a workspace-root manifest component like
# `resource-explorer` (`packages/resource-explorer/**`, IR shows this is a
# real emitted component) contains every subtree at overlap 1.0 by
# construction, which would label every candidate "recovered" by a container
# that says nothing about the specific boundary. Jaccard penalises exactly
# that — a component many times larger than the candidate subtree scores low
# even at 100% directional containment — so only a component that is
# *itself* roughly the size of the subtree counts as having proposed it.
# Containment, not Jaccard. A candidate subtree is typically a SUBSET of the
# ground-truth component that owns it — `packages/trellis-microflow/
# trellis_microflow` (2 files) sits inside GT's `packages/trellis-microflow/**`
# (5 files). Jaccard scores that 0.4 and, under a 0.5 bar, reported a correct
# partial match as a NOVEL boundary. Directional containment scores it 1.0.
#
# This is design §8.2a's rule — "measure containment, not similarity" — which
# was written for the PyegeriaWebHandler variant analysis and applies verbatim
# here. Symmetric measures penalise the subset relationship that is the normal
# shape of a candidate-vs-component comparison, and they do it silently, by
# inflating the novel count with things that are not novel.
MATCH_THRESHOLD = 0.5


def which_gt_component(subtree_files: set[str], gt_components: dict[str, list[str]],
                       root: str, tracked: set[str] | None) -> tuple[str | None, float]:
    best_name, best_score = None, 0.0
    for name, globs in gt_components.items():
        gt_files: set[str] = set()
        for g in globs:
            gt_files.update(validate.expand(g, root, tracked))
        if not gt_files:
            continue
        score = _containment(subtree_files, gt_files)
        if score > best_score:
            best_name, best_score = name, score
    return (best_name, round(best_score, 4)) if best_score >= MATCH_THRESHOLD else (None, round(best_score, 4))


def which_detector_component(subtree: str, subtree_files: set[str],
                             ir_components: list[dict], root: str,
                             tracked: set[str] | None) -> tuple[str | None, float]:
    best_name, best_score = None, 0.0
    for c in ir_components:
        if not c.get("files"):
            continue
        det_files: set[str] = set()
        for g in c["files"]:
            det_files.update(validate.expand(g, root, tracked))
        if not det_files:
            continue
        score = _jaccard(subtree_files, det_files)
        if score > best_score:
            best_name, best_score = c["name"], score
    return (best_name, round(best_score, 4)) if best_score >= MATCH_THRESHOLD else (None, round(best_score, 4))


def candidate_boundaries(root: str, tracked: set[str], package_roots: list[str],
                         import_edges: list[dict], cochange_pairs: list[dict],
                         ir_components: list[dict], gt_components: dict[str, list[str]],
                         min_cohesion: float) -> list[dict]:
    all_files = sorted(tracked)
    file_subtree = candidate_subtrees(all_files, package_roots)
    subtree_files: dict[str, set[str]] = {}
    for f, s in file_subtree.items():
        subtree_files.setdefault(s, set()).add(f)

    imp_table = cohesion_table(file_subtree, import_edges, "source", "target", "weight")
    coc_table = cohesion_table(file_subtree, cochange_pairs, "a", "b", "cochange_count")

    rows = []
    for sub, files in sorted(subtree_files.items()):
        if len(files) < 2:
            continue
        imp = imp_table.get(sub, {"cohesion": None, "total_weight": 0})
        coc = coc_table.get(sub, {"cohesion": None, "total_weight": 0})
        gt_name, gt_overlap = which_gt_component(files, gt_components, root, tracked)
        det_name, det_overlap = which_detector_component(sub, files, ir_components, root, tracked)

        high = ((imp["cohesion"] or 0) >= min_cohesion and imp["total_weight"] >= 3) or \
               ((coc["cohesion"] or 0) >= min_cohesion and coc["total_weight"] >= 3)
        if not high:
            label = None
        elif det_name:
            label = "recovered"
        elif gt_name:
            label = "signal-only"
        else:
            label = "novel"

        rows.append({
            "subtree": sub, "file_count": len(files),
            "import_cohesion": imp["cohesion"], "import_weight": imp["total_weight"],
            "cochange_cohesion": coc["cohesion"], "cochange_weight": coc["total_weight"],
            "ground_truth_component": gt_name, "ground_truth_overlap": gt_overlap,
            "detector_component": det_name, "detector_overlap": det_overlap,
            "label": label,
        })

    rows.sort(key=lambda r: ((r["import_cohesion"] or 0), (r["cochange_cohesion"] or 0)), reverse=True)
    return rows



# ── §4.1 — coupling as PROPOSER ──────────────────────────────────────────
#
# Phase 1 inverts coupling's role: it stops scoring a partition someone else
# proposed and starts contributing components to one. Two things Phase 0 did
# not build were needed, and the first turned out differently than the Phase 1
# plan predicted.
#
# **Newman modularity does not give a usable threshold, though the plan said it
# would.** Measured on trellis, the per-subtree modularity contribution
# Q_c = e_c/m - (deg_c/2m)^2 is POSITIVE for 15 of 16 candidates — in a sparse
# import graph almost any subtree beats chance, so `Q > 0` admits nearly
# everything. Q remains a good *ranking* (it puts surveyors, ingestion and
# agents at the top) but it is not a bar. Recorded as a plan-level miss: the
# fallback the plan named — relative ranking rather than an absolute threshold
# — is what the data actually supports.
#
# **What discriminates is directional dispersion.** A raw cohesion bar rejects
# any component that is structurally connective, which is why Core and
# Observability were missed in Phase 0: a shared library has almost no internal
# edges and enormous fan-in, so `internal/(internal+external)` is near zero for
# a component that plainly exists. But its fan-in is spread EVENLY across many
# others, and that is measurable. Three shapes, and the third is the only one
# that is genuinely not a component:
#
#   cohesive         — high internal ratio. The classic case.
#   connective       — low internal ratio, but external edges DISPERSED across
#                      many neighbours. A library (fan-in) or an orchestrator
#                      (fan-out). Real components; the Phase 0 rule threw them
#                      away.
#   merge-candidate  — low internal ratio AND external edges CONCENTRATED on
#                      one neighbour. Not a component: it belongs to that
#                      neighbour.
#
# Dispersion is normalised Shannon entropy over the external edge weights, so
# it is 1.0 when spread evenly across neighbours and 0.0 when they all point
# one way. Admitting on EITHER direction is deliberate — an earlier version
# required fan-in to exceed fan-out and misclassified `agents`, which is
# dispersed in both but slightly more outbound.

COHESIVE_BAR = 0.35
DISPERSION_BAR = 0.6


def _dispersion(counter: dict) -> float:
    """Normalised entropy of external edge weights across neighbours.

    1.0 = spread evenly across many; 0.0 = all pointing at one. A single
    neighbour is 0.0 by definition, which is the merge-candidate signal.
    """
    total = sum(counter.values())
    if total == 0 or len(counter) < 2:
        return 0.0
    ps = [v / total for v in counter.values()]
    return -sum(p * math.log(p) for p in ps) / math.log(len(counter))


def classify_subtree(internal: float, fan_in: dict, fan_out: dict) -> tuple[str, float, str]:
    """(shape, confidence, why) for one candidate subtree."""
    fi, fo = sum(fan_in.values()), sum(fan_out.values())
    total = internal + fi + fo
    cohesion = internal / total if total else 0.0
    d_in, d_out = _dispersion(fan_in), _dispersion(fan_out)

    if cohesion >= COHESIVE_BAR:
        return "cohesive", 75, f"internal edge ratio {cohesion:.2f}"
    if d_in >= DISPERSION_BAR and fi >= fo:
        return "connective-library", 60, (
            f"low cohesion ({cohesion:.2f}) but fan-in dispersed across "
            f"{len(fan_in)} components (entropy {d_in:.2f}) — shared-library shape")
    if d_out >= DISPERSION_BAR:
        return "connective-orchestrator", 60, (
            f"low cohesion ({cohesion:.2f}) but fan-out dispersed across "
            f"{len(fan_out)} components (entropy {d_out:.2f}) — orchestrator shape")
    if d_in >= DISPERSION_BAR:
        return "connective-library", 55, (
            f"low cohesion ({cohesion:.2f}), fan-in dispersed (entropy {d_in:.2f})")
    dominant = max(fan_out or fan_in or {"?": 0}, key=(fan_out or fan_in or {"?": 0}).get)
    return "merge-candidate", 0, (
        f"low cohesion ({cohesion:.2f}) and external edges concentrated on "
        f"{dominant} — belongs to it rather than standing alone")


def modularity_contribution(internal: float, degree: float, total_weight: float) -> float:
    """Newman Q_c. Kept for RANKING, explicitly not used as a threshold —
    see the module note above for why `Q > 0` admits nearly everything."""
    if total_weight <= 0:
        return 0.0
    return internal / total_weight - (degree / (2 * total_weight)) ** 2


# ── driving one target ──────────────────────────────────────────────────

def run(target: str, gt_name: str, root_override: str | None, min_cohesion: float) -> dict:
    imports_sig = load_signal(target, "imports")
    cochange_sig = load_signal(target, "cochange")
    ir = load_ir(target)
    if imports_sig is None and cochange_sig is None:
        return {"target": target, "error": "no signal files found — run imports.py / cochange.py first"}

    doc = validate.parse(os.path.join(GT_DIR, f"{gt_name}.md"))
    real = {n: c for n, c in doc["components"].items() if not validate.PLACEHOLDER.search(n)}
    gt_components = {n: c["files"] for n, c in real.items() if c["files"]}

    root = root_override or validate.unquote(doc["meta"].get("checkout", "")) \
        or (imports_sig or cochange_sig)["root"]
    tracked = validate.tracked_files(root)
    scope = doc["meta"].get("scope", "")
    if scope:
        prefixes = ([validate.unquote(x).rstrip("/") for x in validate.CODE_SPAN.findall(scope)]
                    or [x.strip().rstrip("/") for x in scope.split(",") if x.strip()])
        if prefixes:
            tracked = {f for f in tracked if any(f == p or f.startswith(p + "/") for p in prefixes)}

    import_edges = imports_sig["edges"] if imports_sig else []
    cochange_pairs = cochange_sig["pairs"] if cochange_sig else []
    ir_components = ir["components"] if ir else []

    # ── Task 3.1: cross-boundary ratio, detector partition vs ground truth
    # Keyed on `slug`, NOT `name` — IR `name` is not unique across deployment
    # contexts (finding 5: two components are both named "PyegeriaWebHandler",
    # disambiguated only by slug/deployment_context). A name-keyed dict
    # silently drops one of the two here, and the other's files then fall
    # through to whichever broader directory component claims them first —
    # found by comparing this function's det_map against ground truth's for
    # egeria-workspaces and seeing 137 quickstart-side files correctly land on
    # "PyegeriaWebHandler" while all 93 freshstart-side files landed on the
    # much coarser "egeria-freshstart" container instead of their own
    # "PyegeriaWebHandler" entry, which the name collision had overwritten.
    det_files_by_name = {c["slug"]: c["files"] for c in ir_components if c["files"]}
    det_map = file_assignment_from_components(det_files_by_name, root, tracked)
    gt_map = file_assignment_from_components(gt_components, root, tracked)

    boundary = {
        "detector_partition": {
            "files_assigned": len(det_map),
            "imports": boundary_stats_imports(det_map, import_edges) if import_edges else None,
            "cochange": boundary_stats_cochange(det_map, cochange_pairs) if cochange_pairs else None,
        },
        "ground_truth_partition": {
            "files_assigned": len(gt_map),
            "imports": boundary_stats_imports(gt_map, import_edges) if import_edges else None,
            "cochange": boundary_stats_cochange(gt_map, cochange_pairs) if cochange_pairs else None,
        },
    }

    # ── Task 3.2: candidate boundaries neither side proposed
    package_roots = sorted({m["dir"] for m in detectors.python_manifests(root, sorted(tracked))}) or ["."]
    candidates = candidate_boundaries(root, tracked, package_roots, import_edges, cochange_pairs,
                                      ir_components, gt_components, min_cohesion)

    return {
        "target": target, "gt_file": f"{gt_name}.md", "root": root,
        "min_cohesion": min_cohesion,
        "boundary_stats": boundary,
        "candidate_boundaries": candidates,
        "signal_only_count": sum(1 for r in candidates if r["label"] == "signal-only"),
        "novel_count": sum(1 for r in candidates if r["label"] == "novel"),
    }


def render(result: dict) -> str:
    if "error" in result:
        return f"=== {result['target']}: {result['error']}"
    lines = [f"=== {result['target']} vs {result['gt_file']} — coupling validation (min_cohesion={result['min_cohesion']})"]
    b = result["boundary_stats"]
    for label, key in (("detector", "detector_partition"), ("ground truth", "ground_truth_partition")):
        row = b[key]
        lines.append(f"  [{label} partition] {row['files_assigned']} files assigned")
        for sig in ("imports", "cochange"):
            s = row[sig]
            if s is None:
                lines.append(f"    {sig}: no signal file")
            elif s["cross_boundary_ratio"] is None:
                lines.append(f"    {sig}: 0 scoreable edges — cannot compute a ratio")
            else:
                lines.append(f"    {sig}: cross-boundary ratio = {s['cross_boundary_ratio']} "
                             f"({s['internal_weight']} internal / {s['boundary_weight']} crossing, "
                             f"weight-based)")
    lines.append(f"  candidate subtrees: {len(result['candidate_boundaries'])} evaluated, "
                f"{result['signal_only_count']} signal-only, {result['novel_count']} novel")
    for r in result["candidate_boundaries"]:
        if r["label"]:
            lines.append(f"    [{r['label']:>11}] {r['subtree']} "
                         f"(files={r['file_count']}, import_cohesion={r['import_cohesion']}, "
                         f"cochange_cohesion={r['cochange_cohesion']}, gt={r['ground_truth_component']}, "
                         f"detector={r['detector_component']})")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("target")
    ap.add_argument("--gt-name")
    ap.add_argument("--root")
    ap.add_argument("--min-cohesion", type=float, default=0.5)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    result = run(args.target, args.gt_name or args.target, args.root, args.min_cohesion)
    print(json.dumps(result, indent=2) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
