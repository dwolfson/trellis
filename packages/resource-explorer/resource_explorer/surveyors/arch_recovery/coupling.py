"""Coupling as PROPOSER — Phase 1 §4.1, ported from scripts/arch-spike/coupling.py.

Trimmed relative to the spike original: this keeps only the proposer half
(`propose()` and everything it depends on). The spike also carried a
diagnostic/scoring half (`boundary_stats_*`, `candidate_boundaries`,
`which_gt_component`, `which_detector_component`, `run()`, `render()`,
`main()`) that reads the pre-registered ground-truth fixtures via
`validate.py` — that is score.py's job now (README "Status": kept as a
test/eval harness, not a runtime step), and this module must not import
`tests/fixtures/architecture-ground-truth/validate.py` from package code.

Everything below is otherwise a straight port — see the arch-spike README
(findings 33/34/35/39/41/43/44) for how this shape was arrived at, and do
not re-tune `COHESIVE_BAR`/`DISPERSION_BAR` to move a score (task rule).

Only import edges feed `propose()` — they are directional (source ->
target), which fan_in/fan_out requires. Co-change pairs are undirected and
are NOT fed into the shape classification, matching the spike exactly.
`cohesion_table()` is kept and exposed anyway so a caller (the
repo_arch_coupling surveyor) can attach co-change cohesion as *supporting*
evidence alongside a proposal without it influencing the proposal itself.
"""
from __future__ import annotations

import math
import os

from .code_markers import file_subtree_map

# ── Task 3.2's building blocks, kept because propose() and the surveyor
# both need them (candidate subtree assignment + cohesion measurement) ──

def candidate_subtrees(files: list[str], package_roots: list[str]) -> dict[str, str]:
    """file -> subtree — every directory holding >=2 first-party files, at
    every depth, is a candidate (code_markers.build_hierarchy); a file maps
    to the deepest one that contains it. Files with no enclosing package
    root, or no qualifying ancestor, are excluded (absent from the dict)."""
    file_subtree, _hierarchy = file_subtree_map(files, package_roots)
    return file_subtree


def cohesion_table(file_subtree: dict[str, str], edges: list[dict],
                   src_key: str, tgt_key: str, weight_key: str) -> dict[str, dict]:
    """subtree -> {"internal", "boundary", "cohesion", "total_weight"} —
    used for the diagnostic/supporting cohesion numbers (e.g. attaching
    co-change cohesion as evidence), not for the shape classification
    below, which uses `_neighbor_breakdown` instead so it can tell fan-in
    from fan-out."""
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


# ── wiring classify_subtree into actual Component proposals ──────────────
#
# Only import edges feed this — they are directional (source -> target),
# which `fan_in`/`fan_out` requires. Co-change pairs are undirected and are
# deliberately not fed through here.

def _neighbor_breakdown(file_subtree: dict[str, str], edges: list[dict],
                        src_key: str, tgt_key: str, weight_key: str) -> dict[str, dict]:
    """subtree -> {"internal": w, "fan_in": {other_subtree: w}, "fan_out": {other_subtree: w}}.

    fan_in/fan_out are keyed by NEIGHBOURING CANDIDATE SUBTREES, not files —
    that is what makes dispersion meaningful ("spread across 14 others",
    README finding 34). An edge whose far end has no candidate subtree (a
    loose top-level file, an excluded path) contributes to neither dict: it
    is real external traffic but has no neighbour identity to disperse
    across, so counting it would understate cohesion without informing
    dispersion.
    """
    table: dict[str, dict] = {}

    def row(sub: str) -> dict:
        return table.setdefault(sub, {"internal": 0, "fan_in": {}, "fan_out": {}})

    for e in edges:
        sa, sb = file_subtree.get(e[src_key]), file_subtree.get(e[tgt_key])
        if sa is None and sb is None:
            continue
        w = e.get(weight_key, 1)
        if sa is not None and sa == sb:
            row(sa)["internal"] += w
        elif sa is not None and sb is not None:
            row(sa)["fan_out"][sb] = row(sa)["fan_out"].get(sb, 0) + w
            row(sb)["fan_in"][sa] = row(sb)["fan_in"].get(sa, 0) + w
        # else: one side has no candidate subtree — external traffic with no
        # neighbour identity, deliberately not counted (see docstring).
    return table


def _component_globs(sub: str, files: set[str]) -> list[str]:
    """The precise glob set for exactly the files `sub` owns after rehoming
    (below) — not an approximation, and not the old fixed-depth choice
    between `X/*` and `X/**` (that choice assumed depth topped out at two
    segments, which an unbounded hierarchy does not). A file directly in
    `sub` is covered by `sub/*`; a file under some non-candidate (or
    dropped) descendant is residue and is covered by one `sub/<branch>/**`
    per distinct immediate branch — never a single `sub/**`, which would
    also swallow a sibling candidate nested under `sub` and reintroduce the
    majority-vote bug (README finding 35/36's caveat).

    `sub == "."` (the flat-repo case, §2a/finding 55 — the package root
    itself is now an eligible candidate) uses bare `*`/`<branch>/**`, no
    `./` prefix, matching detectors.py's own root-glob convention.
    """
    at_root = sub == "."
    prefix = "" if at_root else sub.rstrip("/") + "/"
    direct = False
    branches: set[str] = set()
    for f in files:
        rest = f[len(prefix):] if (at_root or f.startswith(prefix)) else f
        parts = rest.split("/")
        if len(parts) > 1:
            branches.add(parts[0])
        else:
            direct = True
    star = "*" if at_root else f"{sub}/*"
    globs = [star] if direct else []
    globs.extend((f"{b}/**" if at_root else f"{sub}/{b}/**") for b in sorted(branches))
    return globs or [star]


def _rehome_dropped(subtree_files: dict[str, set[str]], hierarchy: dict[str, dict],
                    emitted: set[str]) -> tuple[dict[str, set[str]], list[str]]:
    """Every candidate is emitted UNLESS `classify_subtree` calls it
    `merge-candidate` (§2a — depth is never pruned away by the generator
    itself; only the classifier's own "not a component" verdict drops one).
    A dropped candidate's files still need an owner — the residue rule
    stated properly (README finding 44): a component owns everything
    beneath it that nothing else claims. Generalises the old one-level
    orphan-adoption pass to the unbounded hierarchy by walking each dropped
    candidate's `parent` chain to the nearest ancestor that WAS emitted.

    Returns `(owned, notes)` — `owned` maps each emitted subtree to the
    full set of files it ends up covering (its own plus any rehomed
    residue); a dropped candidate with no emitted ancestor at all (rare —
    every candidate on its branch was a merge-candidate) contributes no
    files anywhere, same as the old orphan pass leaving a truly unclaimed
    bucket unclaimed.
    """
    owned: dict[str, set[str]] = {sub: set(files) for sub, files in subtree_files.items()
                                  if sub in emitted}
    notes: list[str] = []
    for sub, files in sorted(subtree_files.items()):
        if sub in emitted:
            continue
        anc = hierarchy.get(sub, {}).get("parent")
        while anc is not None and anc not in emitted:
            anc = hierarchy.get(anc, {}).get("parent")
        if anc is not None:
            owned.setdefault(anc, set()).update(files)
            notes.append(f"{anc}: adopted unproposed subtree {sub} (nothing else claims it)")
    return owned, notes


def propose(tracked: set[str], package_roots: list[str],
           import_edges: list[dict]) -> tuple[list, list, list]:
    """Coupling as PROPOSER (plan §4.1) — subtrees classified `cohesive`,
    `connective-library` or `connective-orchestrator` become `Component`
    entries with `perspective="logical"`, the same perspective
    `code_markers.propose` uses. `merge-candidate` subtrees are
    deliberately never emitted — they are the one shape `classify_subtree`
    says is NOT a component (finding 34).

    Every OTHER candidate subtree — every directory holding >=2 first-party
    files, at every depth — is emitted (approach-portfolio-model.md §2a):
    the generator does not choose a level, it emits the whole hierarchy
    (`parent_slug`/`depth`, linked to the nearest candidate ancestor) and
    lets a consumer project (`projection.py`). The ~3,000-candidate count
    that killed the earlier "generate all depths, then prune parent-vs-
    children" experiment (README finding 56) stops being a problem once
    depth is stored rather than chosen — nothing here is pruned by level,
    only by the classifier's own verdict.

    Thresholds (`COHESIVE_BAR`, `DISPERSION_BAR`) are read as-is, never
    adjusted here — task rule: never tune a threshold to move a score.
    """
    from .ir import Component, Evidence, Identity, Location

    all_files = sorted(tracked)
    file_subtree, hierarchy = file_subtree_map(all_files, package_roots)
    subtree_files: dict[str, set[str]] = {}
    for f, s in file_subtree.items():
        subtree_files.setdefault(s, set()).add(f)

    breakdown = _neighbor_breakdown(file_subtree, import_edges, "source", "target", "weight")

    classified: dict[str, tuple[str, float, str]] = {}
    shape_counts: dict[str, int] = {}
    emitted: set[str] = set()
    for sub, files in sorted(subtree_files.items()):
        if len(files) < 2:
            continue
        row = breakdown.get(sub, {"internal": 0, "fan_in": {}, "fan_out": {}})
        shape, confidence, why = classify_subtree(row["internal"], row["fan_in"], row["fan_out"])
        classified[sub] = (shape, confidence, why)
        shape_counts[shape] = shape_counts.get(shape, 0) + 1
        if shape != "merge-candidate":
            emitted.add(sub)

    owned, notes = _rehome_dropped(subtree_files, hierarchy, emitted)

    def _nearest_emitted_ancestor(sub: str) -> str | None:
        # `hierarchy`'s own `parent` is the nearest CANDIDATE ancestor,
        # which may itself have been dropped as a merge-candidate and so
        # never became a Component (same walk `_rehome_dropped` does for
        # files). `parent_slug` must skip past those so a consumer can
        # walk purely emitted components end-to-end when projecting
        # (projection.py) — a link to a slug that was never emitted is a
        # dead end, not a coarser reading.
        anc = hierarchy.get(sub, {}).get("parent")
        while anc is not None and anc not in emitted:
            anc = hierarchy.get(anc, {}).get("parent")
        return anc

    components: list = []
    evidence: list = []
    for sub in sorted(emitted):
        shape, confidence, why = classified[sub]
        name = os.path.basename(sub.rstrip("/")) or sub
        slug = "coupling::" + sub.replace("/", "::")
        node = hierarchy.get(sub, {})
        parent_dir = _nearest_emitted_ancestor(sub)
        # type left None: coupling establishes a BOUNDARY, not a
        # SolutionComponentType — that needs a code marker or a human, and
        # asserting one here would overstate what this signal knows.
        components.append(Component(
            slug=slug, name=name, type=None,
            identity=Identity("module-path", sub),
            files=_component_globs(sub, owned.get(sub, set())), confidence=int(confidence),
            confidence_level="Derived", perspective="logical",
            parent_slug=f"coupling::{parent_dir.replace('/', '::')}" if parent_dir else "",
            depth=node.get("depth", 0),
        ))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=slug,
            assertion=f"coupling shape = {shape}",
            detector=f"coupling:{shape}",
            locations=[Location(sub, 0, why)],
            confidence=int(confidence), confidence_level="Derived",
        ))

    notes.append(
        f"coupling: {len(components)} logical components proposed from "
        f"{len(subtree_files)} candidate subtrees "
        f"(shapes: {', '.join(f'{k}={v}' for k, v in sorted(shape_counts.items()))}; "
        f"COHESIVE_BAR={COHESIVE_BAR}, DISPERSION_BAR={DISPERSION_BAR})"
    )
    return components, evidence, notes
