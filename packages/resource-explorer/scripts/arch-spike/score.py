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



def load_revision(gt_name: str) -> dict | None:
    """`{target}-revised.md`, if one exists — the sanctioned way to correct a
    pre-registered fixture without editing it (fixtures README rule 3).

    This existed as prose that **nothing read** for two days: the maintainer's
    decisions about residue ownership, misplaced code and component hierarchy
    were recorded and then ignored by every consumer. That is the same defect as
    a guard writing a field no reader consumes — a decision filed is not a
    decision used.
    """
    path = os.path.join(GT_DIR, f"{gt_name}-revised.md")
    return validate.parse(path) if os.path.exists(path) else None


def apply_revision(doc: dict, revision: dict | None) -> tuple[dict, list[str]]:
    """Merge a revision delta onto the base fixture. Returns (doc, notes).

    Three kinds of entry, all additive — a revision never removes:

      * `Additional files:`  extra globs for a component the base already has
      * `New component: yes` a component the base lacks entirely (e.g. a parent
                             the flat fixture had no way to express)
      * `Sub-components:`    parent/child links, by component name or by path

    The base file is never mutated on disk; this is a read-time merge.
    """
    if not revision:
        return doc, []
    merged = {k: (dict(v) if isinstance(v, dict) else v) for k, v in doc.items()}
    merged["components"] = {n: dict(c) for n, c in doc["components"].items()}
    notes: list[str] = []

    for name, rev in revision.get("components", {}).items():
        if validate.PLACEHOLDER.search(name):
            continue
        extra = rev.get("additional files")
        subs = rev.get("sub-components")
        base = merged["components"].get(name)

        if base is None:
            merged["components"][name] = {
                "type": rev.get("type"), "files": [], "identity": "",
                "notes": rev.get("notes", ""),
            }
            base = merged["components"][name]
            notes.append(f"revision adds component {name!r}")

        if extra:
            for g in (extra if isinstance(extra, list) else [extra]):
                if g and g not in base["files"]:
                    base["files"].append(g)
            notes.append(f"revision extends {name!r} by "
                         f"{len(extra) if isinstance(extra, list) else 1} glob(s)")

        if subs:
            kids = subs if isinstance(subs, list) else [subs]
            base["sub_components"] = [validate.unquote(k) for k in kids]
            notes.append(f"revision gives {name!r} {len(kids)} sub-component(s)")

    return merged, notes


# ── component-set agreement ─────────────────────────────────────────────

def _normalise_name(name: str, project_prefix: str = "") -> tuple[str, str]:
    """`(normalised, prefix_stripped)` for identity-aware matching.

    Finding 90. The detector found all four of immich's declared components and
    scored 0/4, because matching was exact string and the differences were a
    hyphen against an underscore (`immich-server` vs `immich_server`) and a
    `container_name` prefix (`postgres` vs `immich_postgres`). Both are Compose
    conventions, not disagreements about what exists.

    Two normalisations, both cosmetic, neither able to merge distinct things:

    * **separators** — `-` and `_` are interchangeable in Compose naming and
      carry no meaning;
    * **the project prefix** — Compose derives `container_name` as
      `<project>_<service>`, and the project defaults to the directory name, so
      the prefix is the target's own name and stripping it recovers the service.

    The prefix is taken from the TARGET rather than inferred from the data, so
    it cannot be tuned. That matters for the case this must not break:
    `immich-e2e-postgres` normalises to `immich_e2e_postgres` and strips to
    `e2e_postgres`, which is correctly NOT `postgres` — a different container
    that a looser substring rule would have matched.
    """
    n = name.strip().lower().replace("-", "_")
    stripped = n
    if project_prefix:
        pfx = project_prefix.strip().lower().replace("-", "_") + "_"
        if n.startswith(pfx):
            stripped = n[len(pfx):]
    return n, stripped


def component_set_score(gt_names: set[str], det_names: set[str],
                        project_prefix: str = "") -> dict:
    # Index the detector's names by both normalised forms, so a ground-truth
    # name matches whichever the detector happened to use.
    det_index: dict[str, str] = {}
    for d in det_names:
        n, stripped = _normalise_name(d, project_prefix)
        det_index.setdefault(n, d)
        det_index.setdefault(stripped, d)

    hit: set[str] = set()
    matched_det: set[str] = set()
    for g in gt_names:
        n, stripped = _normalise_name(g, project_prefix)
        for key in (g, n, stripped):
            if key in det_index:
                hit.add(g)
                matched_det.add(det_index[key])
                break

    missed = gt_names - hit                 # false negatives — GT said it exists, detector didn't find it
    spurious = det_names - matched_det      # false positives — detector invented/found something ungrounded
    precision = len(hit) / len(det_names) if det_names else 0.0
    recall = len(hit) / len(gt_names) if gt_names else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
    return {
        "gt_count": len(gt_names), "detected_count": len(det_names),
        "matched": len(hit), "precision": round(precision, 4),
        "recall": round(recall, 4), "f1": round(f1, 4),
        "missed": sorted(missed), "spurious": sorted(spurious),
    }


# ── strict containment (finding 61) ─────────────────────────────────────
#
# ARI/NMI compare two FLAT partitions and have no notion of one refining the
# other — finding 61: applying a maintainer-endorsed correction that made the
# detector's answer objectively righter (assigning `configdata`/`github` to
# `Core`, `dashboard` to `Web backend` — exactly the components the detector
# already proposes as nodes in their own right) made ARI worse, because a
# component nested one level inside a matched ground-truth component reads to
# ARI as disagreement. Per §2a that is precisely not an error (a refinement),
# so ARI is not the right headline once ground truth carries a hierarchy.
#
# Strict containment asks a narrower, matcher-free question instead: for each
# ground-truth component, does SOME proposed node's file set equal it
# EXACTLY? No partial credit, no clustering metric — exact glob-expanded
# equality, scored over the same `tracked` file set the rest of this script
# uses. This is the manual measure finding 61 used to get "10/13" on the base
# fixture; it is implemented here so it stops being manual.
#
# finding 62: a parent defined only by its children (`Web application`) has
# no files of its own — `apply_revision`'s "New component: yes" path leaves
# it with `files: []`. Scored literally, an empty set trivially fails
# equality against everything, so a genuinely real component becomes
# invisible rather than wrong. The fix mirrors finding 62's own suggestion:
# a ground-truth component with no files of its own is scored against the
# UNION of its declared `sub_components`' owned file sets (looked up by
# name in the same tier), not against its own (empty) globs. A component
# that already has explicit files (`Surveyors`, whose `sub_components` only
# annotate internal structure — its glob already covers all of them) is
# scored on those files exactly as before; the union rule only fires when
# there is nothing else to score against.

def _component_owned_files(name: str, comp: dict, root: str,
                           tracked: set[str] | None, tier_comps: dict[str, dict],
                           _seen: frozenset[str] = frozenset()) -> frozenset[str]:
    own_globs = [f for f in comp.get("files", []) if not validate.PLACEHOLDER.search(f)]
    if own_globs:
        hits: set[str] = set()
        for g in own_globs:
            hits.update(validate.expand(g, root, tracked))
        return frozenset(hits)
    subs = comp.get("sub_components") or []
    if not subs or name in _seen:
        return frozenset()
    union: set[str] = set()
    for sub_name in subs:
        sub_comp = tier_comps.get(sub_name)
        if sub_comp is None:
            continue   # a sub-component name the current tier doesn't carry
        union |= _component_owned_files(sub_name, sub_comp, root, tracked,
                                        tier_comps, _seen | {name})
    return frozenset(union)


def strict_containment_score(tier_comps: dict[str, dict], det_files_by_name: dict[str, list[str]],
                             root: str, tracked: set[str] | None) -> dict:
    """(matched, total, matched_names, unmatched_names) — finding 61's
    headline measure. `det_files_by_name` is scoped/perspective-filtered the
    same way `det_names_all` is elsewhere in `score()`."""
    det_owned: dict[str, frozenset[str]] = {}
    for name, globs in det_files_by_name.items():
        hits: set[str] = set()
        for g in globs:
            hits.update(validate.expand(g, root, tracked))
        det_owned[name] = frozenset(hits)
    det_by_fileset: dict[frozenset[str], list[str]] = {}
    for name, files in det_owned.items():
        if files:
            det_by_fileset.setdefault(files, []).append(name)

    matched: list[str] = []
    unmatched: list[str] = []
    partial: list[dict] = []
    for name, comp in sorted(tier_comps.items()):
        gt_files = _component_owned_files(name, comp, root, tracked, tier_comps)
        if not gt_files:
            unmatched.append(name)
            continue
        if gt_files in det_by_fileset:
            matched.append(name)                      # exact node
            continue
        # §2a's other half: "an exact node, OR a set of children whose union
        # equals it". Without this the measure credits only exact matches and
        # reads every REFINEMENT as a miss — the precise failure §2a exists to
        # prevent, and the same shape as ARI's (finding 61): a measure that
        # silently contradicts a design decision it predates.
        #
        # Union over detector nodes wholly INSIDE the component, so a node that
        # spills outside cannot help cover it. Exhaustive cover only: partial
        # cover is not a match.
        inside = [f for f in det_owned.values() if f and f <= gt_files]
        covered = frozenset().union(*inside) if inside else frozenset()
        if covered == gt_files:
            matched.append(name)                      # covered by refinements
            continue

        unmatched.append(name)

        # ── partial cover (finding 72) ──────────────────────────────────
        #
        # A near-miss is NOT a match and is deliberately excluded from the
        # headline above: 575 != 576, and a measure that rounds is worse than
        # one that is strict. But the scorer previously had no way to SAY
        # "575 of 576", so a component recovered to 99.8% reported the same 0
        # as one recovered not at all — and three such near-misses across two
        # independent repos (Prometheus `Web UI and API` 325/380, Milvus
        # `Coordinator` 575/576 and `Streaming Node` 259/260, from two
        # unrelated causes) went invisible.
        #
        # No threshold is introduced. "Partial" is simply 0 < coverage < 1 —
        # the same discipline that kept Newman modularity out (§5.5): a
        # reported fraction beats an invented cut-off.
        missing = gt_files - covered
        # Components that touch this one but spill outside it cannot help
        # cover it. Reporting them separates the two failure modes: "we found
        # less than the component" from "we found a blob that merged it with
        # something else".
        overclaim = sorted(n for n, f in det_owned.items()
                           if f and not f <= gt_files and f & gt_files)
        partial.append({
            "name": name,
            "covered": len(covered), "total": len(gt_files),
            "coverage": round(len(covered) / len(gt_files), 4),
            "missing": len(missing),
            "missing_sample": sorted(missing)[:5],
            "contributors": len(inside),
            "overclaimed_by": overclaim[:5],
            "overclaim_count": len(overclaim),
        })

    partial.sort(key=lambda p: -p["coverage"])
    return {
        "matched": len(matched), "total": len(matched) + len(unmatched),
        "matched_names": sorted(matched), "unmatched_names": sorted(unmatched),
        # Reported alongside the headline, never folded into it.
        "partial": partial,
        "partial_count": sum(1 for p in partial if p["coverage"] > 0),
        "no_coverage_names": sorted(p["name"] for p in partial if p["coverage"] == 0),
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
    doc, revision_notes = apply_revision(doc, load_revision(gt_name))
    real = real_components(doc)

    perspective = doc["meta"].get("perspective", "logical").strip().lower()
    files_required = perspective in validate.FILES_REQUIRED
    # Derived, not hardcoded to `== "logical"`. A comparison is a diagnostic
    # only when NO detected component carries the ground truth's perspective —
    # i.e. nothing in this IR is even the right kind of claim. Once the
    # code-marker pass began emitting logical-perspective components this
    # became a real comparison for trellis, and the hardcode would have gone on
    # labelling it DIAGNOSTIC ONLY forever.
    det_perspectives = {c.get("perspective", "physical") for c in ir["components"]}
    diagnostic_only = perspective not in det_perspectives
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

    # The fixture's own `Excluded — not first-party` section is a SCOPE
    # declaration and is applied here, to `tracked`, so it narrows BOTH sides
    # exactly as `Scope:` above does.
    #
    # Finding 74. `validate.py` has always parsed this section; `score.py`
    # never read it. The consequence was that a ground-truth component whose
    # glob spans an excluded subdirectory could never be matched by anything:
    # the GT side expanded over all tracked files including the excluded ones,
    # while the detector side can only ever claim FIRST-PARTY files, because
    # `exclusion.py` removes vendored trees before detection begins. On
    # `trellis.md` that made `Web front-end` unmatchable — its glob is
    # `web/static/**`, and the fixture separately (and correctly) excludes
    # `web/static/vendor/**`, which holds three `.min.js` files no detector
    # will ever see.
    #
    # Finding 73 diagnosed that as a contradiction inside the fixture. It was
    # not: the fixture was right and said so in its own Excluded section. The
    # asymmetry was the scorer expanding the two sides against different file
    # universes — the same family as findings 12/24/51, and the third time in
    # this project that a "detector failure" turned out to live in the
    # measuring instrument.
    if tracked is not None and doc.get("excluded"):
        drop: set[str] = set()
        for g in doc["excluded"]:
            if validate.PLACEHOLDER.search(g):
                continue
            drop |= set(validate.expand(g, root, tracked))
        if drop:
            tracked = tracked - drop

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

    # Perspective filtering — plan §5a, and the correction behind findings 15/16:
    # a Dockerfile-directory component (physical — an implementation artifact)
    # and the compose-service component it builds (deployment — a running
    # container) are NOT the same thing counted twice; they are two
    # perspectives on one system, related one-to-many by ImplementedBy (design
    # §3.6, §4.2 "map, never merge"). Comparing a `deployment` ground truth
    # against `physical` detector output was scoring the wrong axis, which is
    # what made PyegeriaWebHandler read as spurious. For a genuinely scoreable
    # perspective (deployment/physical/dev), only same-perspective components
    # are eligible. For a `logical` ground truth (diagnostic_only) NO detector
    # in this slice targets that perspective at all, so filtering strictly
    # would make the comparison vacuous — plan §5a wants it computed anyway,
    # cross-perspective, purely as a distillation-baseline diagnostic. Hence
    # the filter applies only outside the diagnostic case.
    if not diagnostic_only:
        scoped_components = [c for c in scoped_components if c.get("perspective") == perspective]

    det_names_all = {c["name"] for c in scoped_components}
    # Keyed by SLUG, not name. Names are not unique — two proposers can name a
    # component after the same directory (`config` from the Go subsystem
    # proposer and `config` from the coupling subtree proposer), and a dict
    # comprehension over names silently keeps only the last. On Prometheus that
    # discarded 30 of 173 components, including every Go component whose glob
    # was the *correct* one, and the loss presented as three ground-truth
    # components the detector had in fact recovered exactly.
    #
    # Same family as findings 12/24/51: one identifier serving two purposes,
    # failing silently as missing data rather than as an error. Slugs are
    # unique by construction; the human name is only needed for display, and
    # the matched/unmatched lists are reported with ground-truth names anyway.
    det_files_by_name = {c["slug"]: c["files"] for c in scoped_components if c["files"]}
    det_file_map = file_assignment(det_files_by_name, root, tracked) if root and tracked is not None else {}

    out: dict = {
        "revision_applied": revision_notes,
        "target": target, "gt_file": f"{gt_name}.md", "perspective": perspective,
        "diagnostic_only": diagnostic_only, "root": root,
        "in_scope_tracked": len(tracked) if tracked is not None else None,
        "tiers": {},
    }

    for tier in ("maintainer", "all"):
        tier_comps = {n: c for n, c in real.items()
                      if tier == "all" or provenance_tier(c) == "maintainer"}
        gt_names = set(tier_comps)
        # The project prefix comes from the TARGET's own name — Compose derives
        # `container_name` as `<project>_<service>` and the project defaults to
        # the directory name — so it is a fact about the repo, not a knob.
        # `gt_name`, not `target`: the target carries run suffixes
        # (`immich-adjudicated`), while the fixture name is the repository name,
        # which is what Compose uses as the default project.
        cset = component_set_score(gt_names, det_names_all, project_prefix=gt_name)

        fpart = None
        containment = None
        if files_required and root and tracked is not None:
            gt_files_by_name = {n: [f for f in c["files"] if not validate.PLACEHOLDER.search(f)]
                                 for n, c in tier_comps.items()}
            gt_files_by_name = {n: g for n, g in gt_files_by_name.items() if g}
            gt_file_map = file_assignment(gt_files_by_name, root, tracked)
            fpart = file_partition_score(gt_file_map, det_file_map)
            containment = strict_containment_score(tier_comps, det_files_by_name, root, tracked)

        out["tiers"][tier] = {"component_set": cset, "file_partition": fpart,
                              "strict_containment": containment}

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
                         f"(gt={fp['gt_assigned']}, detector={fp['detector_assigned']}) "
                         f"— projected-level diagnostic only, see finding 61")
        sc = tier.get("strict_containment")
        if sc is not None:
            lines.append(f"    strict containment (finding 61 — headline): "
                         f"{sc['matched']}/{sc['total']} exact file-set matches")
            near = [p for p in sc.get("partial", []) if p["coverage"] > 0]
            if near:
                cov = sum(p["covered"] for p in near)
                tot = sum(p["total"] for p in near)
                lines.append(f"      partial (finding 72 — REPORTED, not counted above): "
                             f"{len(near)} component(s) covered {cov}/{tot} files "
                             f"({100 * cov / tot:.1f}%)")
                for p in near:
                    detail = (f"missing {p['missing']}: "
                              f"{', '.join(p['missing_sample'])}"
                              + (" ..." if p["missing"] > len(p["missing_sample"]) else ""))
                    over = (f"; {p['overclaim_count']} overclaiming node(s): "
                            f"{', '.join(p['overclaimed_by'])}" if p["overclaim_count"] else "")
                    lines.append(f"        {p['name']}: {p['covered']}/{p['total']} "
                                 f"({100 * p['coverage']:.1f}%) from {p['contributors']} node(s) "
                                 f"— {detail}{over}")
            if sc.get("no_coverage_names"):
                lines.append(f"      no coverage at all: "
                             f"{', '.join(sc['no_coverage_names'][:12])}"
                             + (" ..." if len(sc["no_coverage_names"]) > 12 else ""))
            elif sc["unmatched_names"] and not near:
                lines.append(f"      unmatched: {', '.join(sc['unmatched_names'][:12])}"
                             + (" ..." if len(sc["unmatched_names"]) > 12 else ""))
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
