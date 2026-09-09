#!/usr/bin/env python3
"""Measurement spike for `docs/curation-lenses-design.md` §8.

Read-only over the registry. No Egeria, no LLM, no writes anywhere except the
JSON dump under `--out`.

    .venv/bin/python3 scripts/curation_lenses_spike.py \
        --repos kafka,egeria_python_git,docling --out /tmp/lenses_spike

What it does, following §8's Method:

1. Loads the stored cluster hierarchy (`kind="architecture_blueprints"`,
   `check_name="candidate_blueprint"` — written by `arch_recovery/persist.py`)
   and the stored component hierarchy (`kind="architecture_recovery"`,
   `check_name="component"`, whose `parent_slug`/`depth` carry the deep tree).
   Nothing is recomputed: `clustering.propose()` is not re-run.
2. Computes per node: size, depth, import cohesion, change-coupling cohesion,
   semantic cohesion, boundary fan-in/fan-out, oversized, signal, carrier.
3. Applies the three lenses' cut rules (§5 + §4.2).
4. Family agreement matrix per lens bar.
5. Agreement with `architecture_component_verdicts` (MoJo / MoJoFM).
6. Wall clock per repo for 1-4.

WHERE THE DESIGN IS SILENT, THE CHOICE IS A PARAMETER BELOW AND IS NAMED IN THE
REPORT. None of them is tuned against an outcome; each is a first, stated guess.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

# ── PARAMETERS — every choice §8 left open ──────────────────────────────────

#: Cut depth per lens, as a depth in the combined rollup->cluster->component
#: tree (root nodes are depth 0). §5 names C4 levels, not numbers; these are
#: the numeric reading of "coarse / medium / fine".
CUT_DEPTH = {"deploy": 1, "learn": 2, "maintain": 4}

#: Which architecture perspectives (§4.1) each lens reads. A perspective with
#: no stored clusters for a repo is reported unavailable, never substituted.
LENS_PERSPECTIVES = {
    "deploy": ["deployment", "physical"],
    "learn": ["logical"],
    "maintain": ["logical", "physical"],
}

#: Which cohesion families decide "cohesive" for §4.2's two adjustments.
LENS_DECIDERS = {
    "deploy": ("import",),
    "learn": ("semantic",),
    "maintain": ("import", "cochange"),
}

#: Import-cohesion bar — REUSED from coupling.COHESIVE_BAR, never redefined
#: here (coupling.py carries an explicit rule against re-tuning it).
IMPORT_BAR = 0.35

#: Change-coupling bar. CHOSEN, not measured: co-change cohesion has never had
#: a bar in this codebase (coupling.py's COCHANGE_SEAM_MIN_WEIGHT is a weight
#: floor, not a cohesion bar). Set equal to IMPORT_BAR so the two families are
#: compared on the same number rather than on two arbitrary ones.
COCHANGE_BAR = 0.35

#: Semantic-cohesion bar. CHOSEN. Mean pairwise TF-IDF cosine over member
#: identifiers+docstrings runs much lower than a ratio-of-edges metric, so the
#: same 0.35 would classify almost everything "not cohesive"; 0.30 is a first
#: guess and the report states the distribution so it can be re-set.
SEMANTIC_BAR = 0.30

#: A family only has an opinion about a node when it has values for at least
#: this fraction of the node's component leaves. Below it the family abstains,
#: which is different from disagreeing (find-absence-as-answer).
MIN_COVERAGE = 0.5

#: Deploy's stop rule: "do not open a runnable unit unless it has more than one
#: external touchpoint". Touchpoints = declared ports + wire endpoints
#: (`kind="architecture_interfaces"`).
DEPLOY_MIN_TOUCHPOINTS = 2

#: Semantic cohesion is mean pairwise cosine; capped so a 600-member node does
#: not cost 180k cosines. Members are sampled deterministically (sorted, evenly
#: spaced) and the node records how many were used.
SEMANTIC_MAX_MEMBERS = 24

#: The two registry kinds this reads.
KIND_RECOVERY = "architecture_recovery"
KIND_BLUEPRINTS = "architecture_blueprints"
KIND_INTERFACES = "architecture_interfaces"


# ── loading ────────────────────────────────────────────────────────────────

def _json(value):
    if isinstance(value, dict):
        return value
    try:
        return json.loads(value or "{}")
    except Exception:
        return {}


def load_clusters(conn, slug: str) -> dict[str, list[dict]]:
    """{perspective: [cluster detail, ...]} for the LATEST run that produced
    rows for that perspective.

    Per perspective, not per repo: `repo_arch_detect` (physical/deployment)
    and `repo_arch_coupling` (logical) are independent steps with their own
    `surveyed_at`, so "the latest run" is only meaningful within a perspective.
    """
    rows = conn.execute(
        "SELECT surveyed_at, detail_json FROM project_analysis_findings "
        "WHERE project_slug=%s AND kind=%s AND check_name='candidate_blueprint'",
        (slug, KIND_BLUEPRINTS),
    ).fetchall()
    by_persp: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for row in rows:
        detail = _json(row["detail_json"])
        by_persp[detail.get("perspective", "")][str(row["surveyed_at"])].append(detail)
    out = {}
    for persp, runs in by_persp.items():
        latest = max(runs)
        # A cluster name can repeat inside one run only if the tree does; keep
        # the first and record nothing silently.
        seen, kept = set(), []
        for detail in runs[latest]:
            if detail["name"] in seen:
                continue
            seen.add(detail["name"])
            kept.append(detail)
        out[persp] = kept
    return out


def load_components(conn, slug: str) -> dict[str, dict]:
    """{scope_locator: component detail} — latest row per scope, the same rule
    `_architecture_recovery_results` uses."""
    rows = conn.execute(
        "SELECT scope_locator, surveyed_at, detail_json FROM project_analysis_findings "
        "WHERE project_slug=%s AND kind=%s AND check_name='component'",
        (slug, KIND_RECOVERY),
    ).fetchall()
    latest: dict[str, tuple[str, dict]] = {}
    for row in rows:
        scope = row["scope_locator"]
        stamp = str(row["surveyed_at"])
        if scope not in latest or stamp > latest[scope][0]:
            latest[scope] = (stamp, _json(row["detail_json"]))
    out = {}
    for scope, (_stamp, detail) in latest.items():
        detail = dict(detail)
        detail["path"] = scope
        out[scope] = detail
    return out


def load_metrics(conn, slug: str) -> dict[str, dict[str, float]]:
    """{scope_locator: {metric_name: latest value}} for the cohesion families."""
    rows = conn.execute(
        "SELECT scope_locator, metric_name, metric_value, surveyed_at "
        "FROM project_analysis_metrics WHERE project_slug=%s AND kind=%s "
        "AND metric_name IN ('import_cohesion','cochange_cohesion') "
        "ORDER BY surveyed_at ASC",
        (slug, KIND_RECOVERY),
    ).fetchall()
    out: dict[str, dict[str, float]] = defaultdict(dict)
    for row in rows:
        out[row["scope_locator"]][row["metric_name"]] = float(row["metric_value"] or 0.0)
    return out


def load_shapes(conn, slug: str) -> dict[str, dict]:
    """{scope: {"shape": ..., "neighbors": n, "entropy": e}} parsed from the
    coupling-shape evidence rows.

    The import GRAPH itself is not persisted — only this prose excerpt records
    anything about the boundary. `classify_subtree` writes the neighbour count
    and the dispersion entropy into it for connective shapes; a `cohesive` or
    `merge-candidate` row carries neither, so those come back with None.
    """
    rows = conn.execute(
        "SELECT scope_locator, check_name, detail_json FROM project_analysis_findings "
        "WHERE project_slug=%s AND kind=%s AND check_name LIKE 'coupling shape%%'",
        (slug, KIND_RECOVERY),
    ).fetchall()
    out: dict[str, dict] = {}
    for row in rows:
        shape = row["check_name"].split("=", 1)[-1].strip()
        detail = _json(row["detail_json"])
        excerpt = ""
        for loc in detail.get("locations") or []:
            excerpt = loc.get("excerpt", "") or excerpt
        neighbors = re.search(r"dispersed across (\d+) components", excerpt)
        entropy = re.search(r"entropy ([0-9.]+)", excerpt)
        out[row["scope_locator"]] = {
            "shape": shape,
            "neighbors": int(neighbors.group(1)) if neighbors else None,
            "entropy": float(entropy.group(1)) if entropy else None,
        }
    return out


def load_touchpoints(conn, slug: str) -> Counter:
    """{component name: declared ports + wire endpoints}. Ports and wires
    attribute by component NAME, not slug (clustering.py `_name_of`)."""
    rows = conn.execute(
        "SELECT detail_json FROM project_analysis_findings "
        "WHERE project_slug=%s AND kind=%s",
        (slug, KIND_INTERFACES),
    ).fetchall()
    counts: Counter = Counter()
    seen = set()
    for row in rows:
        detail = _json(row["detail_json"])
        key = json.dumps(detail, sort_keys=True)
        if key in seen:      # the same run's rows repeat across re-surveys
            continue
        seen.add(key)
        if detail.get("kind") == "port" and detail.get("component"):
            counts[detail["component"]] += 1
        elif detail.get("kind") == "wire":
            for end in ("source", "target"):
                if detail.get(end):
                    counts[detail[end]] += 1
    return counts


def load_symbols(conn, slug: str) -> tuple[dict[str, list[str]], dict[str, str], list[tuple[str, str]]]:
    """(file -> tokens, class name -> file, inheritance edges).

    Identifiers and docstrings come from `project_code_symbols`; the only
    relationship type stored is `inherits_from`, so that is the ONLY structural
    edge set available for boundary fan-in/fan-out (see the report).
    """
    rows = conn.execute(
        "SELECT file_path, name, kind, docstring, is_private FROM project_code_symbols "
        "WHERE project_slug=%s",
        (slug,),
    ).fetchall()
    tokens: dict[str, list[str]] = defaultdict(list)
    name_files: dict[str, set[str]] = defaultdict(set)
    public: dict[str, int] = Counter()
    for row in rows:
        path = row["file_path"]
        tokens[path].extend(_tokenise(row["name"] or ""))
        tokens[path].extend(_tokenise(row["docstring"] or "")[:40])
        if row["kind"] in ("class", "interface"):
            name_files[row["name"]].add(path)
        if not row["is_private"]:
            public[path] += 1
    # A class name defined in two files cannot be resolved to one boundary;
    # dropped rather than guessed.
    name_file = {n: next(iter(f)) for n, f in name_files.items() if len(f) == 1}
    rel = conn.execute(
        "SELECT source_name, target_name FROM project_code_relationships "
        "WHERE project_slug=%s AND relationship_type='inherits_from'",
        (slug,),
    ).fetchall()
    edges = []
    for row in rel:
        src, tgt = name_file.get(row["source_name"]), name_file.get(row["target_name"])
        if src and tgt and src != tgt:
            edges.append((src, tgt))
    return dict(tokens), dict(public), edges


_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]+")
_STOP = {"self", "the", "and", "for", "with", "this", "that", "from", "return",
         "returns", "param", "params", "args", "none", "true", "false", "type",
         "str", "int", "list", "dict", "bool", "get", "set", "value", "name"}


def _tokenise(text: str) -> list[str]:
    out = []
    for word in _TOKEN.findall(text):
        # split camelCase / PascalCase
        for part in re.findall(r"[A-Z]+(?![a-z])|[A-Z][a-z]+|[a-z]+|\d+", word):
            part = part.lower()
            if len(part) > 2 and part not in _STOP:
                out.append(part)
    return out


# ── tree ───────────────────────────────────────────────────────────────────

class Node:
    __slots__ = ("key", "name", "kind", "perspective", "children", "depth",
                 "scope", "signal", "carrier", "oversized", "leaves", "metrics")

    def __init__(self, key, name, kind, perspective, scope="", signal="",
                 carrier="", oversized=False):
        self.key, self.name, self.kind = key, name, kind
        self.perspective, self.scope = perspective, scope
        self.signal, self.carrier, self.oversized = signal, carrier, oversized
        self.children: list[Node] = []
        self.depth = 0
        self.leaves: list[str] = []       # component scope locators beneath
        self.metrics: dict = {}


def build_tree(clusters: list[dict], components: dict[str, dict], perspective: str) -> tuple[list[Node], list[str]]:
    """Combined forest: rollup cluster -> leaf cluster -> component subtree.

    The stored cluster tree is at most two levels (`clustering.rollup` nests one
    level over a flat list of leaf clusters; `_build` flattens its own
    recursion). The DEEP hierarchy lives on the components themselves, in
    `parent_slug`/`depth`. §4.2's cut is over "candidate components and nested
    clusters", so both are stitched into one tree here.

    Returns (roots, stragglers) where stragglers are perspective components no
    cluster covers — clustering.py's "no signal, no cluster" residue.
    """
    comps = {s: c for s, c in components.items()
             if c.get("perspective") == perspective and not c.get("structural")}
    by_slug = {c.get("slug"): s for s, c in comps.items() if c.get("slug")}

    # component forest
    kids: dict[str, list[str]] = defaultdict(list)
    roots_c: list[str] = []
    for scope, comp in comps.items():
        parent = by_slug.get(comp.get("parent_slug") or "")
        if parent and parent != scope:
            kids[parent].append(scope)
        else:
            roots_c.append(scope)

    def comp_node(scope: str, seen: frozenset) -> Node:
        """A FRESH node per occurrence. The stored leaf clusters overlap (e.g.
        docling has both `.agents/skills` and `.agents/skills/dignified-python`
        as leaf clusters), so one component subtree is reachable by more than
        one path and cannot carry a single depth. Occurrences are deduplicated
        at the cut, not here."""
        comp = comps[scope]
        node = Node(f"c:{scope}", scope, "component", perspective, scope=scope,
                    signal=",".join(comp.get("proposed_by") or []) or "component",
                    carrier="component")
        for child in sorted(kids.get(scope, [])):
            if child in seen:
                continue
            node.children.append(comp_node(child, seen | {child}))
        return node

    cluster_by_name = {c["name"]: c for c in clusters}

    def cluster_node(detail: dict, seen: frozenset) -> Node:
        node = Node(f"b:{detail['name']}", detail["name"], "cluster", perspective,
                    signal=detail.get("signal", ""), carrier=detail.get("carrier", ""),
                    oversized=bool(detail.get("oversized")))
        for child_name in detail.get("children") or []:
            child = cluster_by_name.get(child_name)
            if child and child_name not in seen:
                node.children.append(cluster_node(child, seen | {child_name}))
        if not detail.get("children"):
            # members are component slugs; keep only the topmost of any chain
            member_scopes = {by_slug[s] for s in detail.get("members") or [] if s in by_slug}
            tops = []
            for scope in sorted(member_scopes):
                anc, parent = scope, comps[scope].get("parent_slug")
                covered = False
                while parent and by_slug.get(parent):
                    anc = by_slug[parent]
                    if anc in member_scopes:
                        covered = True
                        break
                    parent = comps[anc].get("parent_slug")
                if not covered:
                    tops.append(scope)
            for scope in tops:
                node.children.append(comp_node(scope, frozenset({scope})))
        return node

    roots = [cluster_node(d, frozenset({d["name"]}))
             for d in sorted(clusters, key=lambda d: d["name"]) if not d.get("parent")]
    # A cluster node whose members resolve to no component of this perspective
    # contributes nothing and is not a decision. Counted, not silently dropped.
    empty = [r.name for r in roots if not _has_component(r)]
    roots = [r for r in roots if _has_component(r)]

    def depth_and_leaves(node: Node, depth: int) -> list[str]:
        node.depth = depth
        acc: list[str] = [node.scope] if node.kind == "component" else []
        for child in node.children:
            acc.extend(depth_and_leaves(child, depth + 1))
        node.leaves = sorted(set(acc))
        return node.leaves

    for root in roots:
        depth_and_leaves(root, 0)

    covered = Counter(s for r in roots for s in r.leaves)
    stragglers = sorted(set(comps) - set(covered))
    return roots, stragglers, {"empty_clusters": empty,
                               "components_in_perspective": len(comps),
                               "components_covered": len(covered)}


def _has_component(node: Node) -> bool:
    return node.kind == "component" or any(_has_component(c) for c in node.children)


# ── per-node metrics ───────────────────────────────────────────────────────

def scope_for_file(path: str, scopes: list[str]) -> str | None:
    """Deepest component scope that is a path prefix of `path`."""
    best = None
    for scope in scopes:
        if scope and (path == scope or path.startswith(scope + "/")):
            if best is None or len(scope) > len(best):
                best = scope
    return best


class Measurer:
    def __init__(self, metrics, shapes, touchpoints, tokens, public, edges,
                 components):
        self.metrics, self.shapes, self.touchpoints = metrics, shapes, touchpoints
        self.components = components
        scopes = sorted(components)
        self.file_scope = {p: scope_for_file(p, scopes) for p in tokens}
        self.public = public
        # per-component document, TF over its files
        docs: dict[str, Counter] = defaultdict(Counter)
        for path, toks in tokens.items():
            scope = self.file_scope.get(path)
            if scope:
                docs[scope].update(toks)
        self.docs = docs
        n = max(1, len(docs))
        df = Counter()
        for counter in docs.values():
            df.update(counter.keys())
        self.idf = {t: math.log(n / (1 + c)) + 1.0 for t, c in df.items()}
        self.vectors: dict[str, dict[str, float]] = {}
        for scope, counter in docs.items():
            vec = {t: (1 + math.log(c)) * self.idf.get(t, 1.0) for t, c in counter.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            self.vectors[scope] = {t: v / norm for t, v in vec.items()}
        # public symbols per component scope
        self.public_by_scope = Counter()
        for path, count in public.items():
            scope = self.file_scope.get(path)
            if scope:
                self.public_by_scope[scope] += count
        # inheritance edges resolved to component scopes
        self.edges = [(self.file_scope.get(a), self.file_scope.get(b)) for a, b in edges]
        self.edges = [(a, b) for a, b in self.edges if a and b and a != b]

    def _family(self, leaves: list[str], metric: str) -> tuple[float | None, float]:
        values = [self.metrics[s][metric] for s in leaves
                  if s in self.metrics and metric in self.metrics[s]]
        coverage = len(values) / len(leaves) if leaves else 0.0
        if not values or coverage < MIN_COVERAGE:
            return None, coverage
        return sum(values) / len(values), coverage

    def semantic(self, leaves: list[str]) -> tuple[float | None, float]:
        present = [s for s in leaves if s in self.vectors]
        coverage = len(present) / len(leaves) if leaves else 0.0
        if len(present) < 2 or coverage < MIN_COVERAGE:
            return None, coverage
        if len(present) > SEMANTIC_MAX_MEMBERS:
            step = len(present) / SEMANTIC_MAX_MEMBERS
            present = [present[int(i * step)] for i in range(SEMANTIC_MAX_MEMBERS)]
        total, pairs = 0.0, 0
        for i, a in enumerate(present):
            va = self.vectors[a]
            for b in present[i + 1:]:
                vb = self.vectors[b]
                small, large = (va, vb) if len(va) < len(vb) else (vb, va)
                total += sum(v * large.get(t, 0.0) for t, v in small.items())
                pairs += 1
        return (total / pairs if pairs else None), coverage

    def boundary(self, leaves: list[str]) -> tuple[int, int]:
        inside = set(leaves)
        fan_out = sum(1 for a, b in self.edges if a in inside and b not in inside)
        fan_in = sum(1 for a, b in self.edges if b in inside and a not in inside)
        return fan_in, fan_out

    def touch(self, leaves: list[str]) -> int:
        total = 0
        for scope in leaves:
            comp = self.components.get(scope) or {}
            for key in (comp.get("name"), scope, scope.split("/")[-1]):
                if key and key in self.touchpoints:
                    total += self.touchpoints[key]
                    break
        return total

    def measure(self, node: Node) -> dict:
        leaves = node.leaves or ([node.scope] if node.scope else [])
        imp, imp_cov = self._family(leaves, "import_cohesion")
        coc, coc_cov = self._family(leaves, "cochange_cohesion")
        sem, sem_cov = self.semantic(leaves)
        fan_in, fan_out = self.boundary(leaves)
        shape = (self.shapes.get(node.scope) or {}) if node.scope else {}
        node.metrics = {
            "size": len(leaves), "depth": node.depth, "kind": node.kind,
            "import_cohesion": imp, "import_coverage": round(imp_cov, 3),
            "cochange_cohesion": coc, "cochange_coverage": round(coc_cov, 3),
            "semantic_cohesion": sem, "semantic_coverage": round(sem_cov, 3),
            "fan_in": fan_in, "fan_out": fan_out,
            "oversized": node.oversized, "signal": node.signal, "carrier": node.carrier,
            "shape": shape.get("shape"), "shape_neighbors": shape.get("neighbors"),
            "touchpoints": self.touch(leaves),
            "public_symbols": sum(self.public_by_scope.get(s, 0) for s in leaves),
        }
        return node.metrics


# ── lenses ─────────────────────────────────────────────────────────────────

FAMILY_KEY = {"import": ("import_cohesion", IMPORT_BAR),
              "cochange": ("cochange_cohesion", COCHANGE_BAR),
              "semantic": ("semantic_cohesion", SEMANTIC_BAR)}


def verdict_of(metrics: dict, family: str) -> bool | None:
    key, bar = FAMILY_KEY[family]
    value = metrics.get(key)
    return None if value is None else value >= bar


def cohesive_under(lens: str, metrics: dict) -> bool | None:
    """True/False/None (no family had an opinion) under the lens's deciders."""
    opinions = [verdict_of(metrics, f) for f in LENS_DECIDERS[lens]]
    opinions = [o for o in opinions if o is not None]
    if not opinions:
        return None
    return all(opinions)


def forced(lens: str, metrics: dict) -> str | None:
    """The lens's own stop rules (§5), which override §4.2's depth logic."""
    if lens == "deploy":
        # "do not open a runnable unit unless it has more than one external
        # touchpoint"
        if metrics["touchpoints"] < DEPLOY_MIN_TOUCHPOINTS:
            return "closed"
    elif lens == "learn":
        # "open a node only if it exposes an interface". Declared ports barely
        # exist for logical components, so the proxy is: any public symbol.
        if metrics["touchpoints"] == 0 and metrics["public_symbols"] == 0:
            return "closed"
    elif lens == "maintain":
        # "open every node whose change coupling crosses its boundary"
        if verdict_of(metrics, "cochange") is False:
            return "open"
        # "never close a hotspot": churn-per-file is NOT stored
        # (project_commits has no per-file change data), so this half of the
        # rule is not implemented. Reported, not approximated.
    return None


def cut(roots: list[Node], lens: str, measurer: Measurer) -> list[Node]:
    depth_bar = CUT_DEPTH[lens]
    out: list[Node] = []

    def walk(node: Node):
        m = node.metrics or measurer.measure(node)
        rule = forced(lens, m)
        if not node.children:
            out.append(node)
            return
        if node.oversized:                       # §4.2: always shown open
            for child in node.children:
                walk(child)
            return
        if rule == "closed":
            out.append(node)
            return
        coh = cohesive_under(lens, m)
        if node.depth < depth_bar:
            if coh is True and rule != "open":    # §4.2 stop early on cohesive
                out.append(node)
                return
            for child in node.children:
                walk(child)
            return
        if node.depth == depth_bar:
            if coh is False or rule == "open":     # §4.2 open a non-cohesive node
                for child in node.children:
                    child.metrics or measurer.measure(child)
                    out.append(child)
                return
            out.append(node)
            return
        out.append(node)

    for root in roots:
        measurer.measure(root)
        walk(root)
    # One decision per distinct node, however many overlapping cluster paths
    # reach it. The overlap itself is reported separately (§4.4's object).
    seen: dict[tuple[str, str], Node] = {}
    for node in out:
        if not node.metrics:
            measurer.measure(node)
        seen.setdefault((node.kind, node.name), node)
    return list(seen.values())


def classify(lens: str, node: Node) -> str:
    m = node.metrics
    opinions = [verdict_of(m, f) for f in ("import", "cochange", "semantic")]
    held = [o for o in opinions if o is not None]
    if node.oversized:
        return "contested"
    if not held:
        return "no-signal"
    if len(set(held)) > 1:
        return "contested"
    decider = cohesive_under(lens, m)
    if decider is True and all(held):
        return "accept-as-unit"
    if decider is None:
        return "no-signal"
    return "contested" if not all(held) and any(held) else (
        "accept-as-unit" if decider else "needs-review")


# ── MoJo (Tzerpos & Holt 1999; MoJoFM: Wen & Tzerpos 2004) ─────────────────

def mno(a: list[set[str]], b: list[set[str]]) -> int:
    """One-way Move-Join number from partition A to partition B, greedy.

    Tag each A-cluster with the B-group it overlaps most; Moves = objects not
    in their cluster's tag group; Joins = clusters minus distinct tags. This is
    Tzerpos & Holt's own heuristic, not an exact optimum.
    """
    total = sum(len(c) for c in a)
    tags, moves = [], 0
    for cluster in a:
        best, best_n = None, -1
        for i, group in enumerate(b):
            overlap = len(cluster & group)
            if overlap > best_n:
                best, best_n = i, overlap
        tags.append(best)
        moves += len(cluster) - max(best_n, 0)
    joins = len(a) - len(set(tags))
    return moves + joins


def mojo(a: list[set[str]], b: list[set[str]]) -> dict:
    ab, ba = mno(a, b), mno(b, a)
    n = sum(len(c) for c in b)
    # MoJoFM's denominator is max(mno(A,B)) over all A; the all-singletons A
    # gives n - |B| (no moves, n-|B| joins). At the sample sizes this spike
    # actually has, that denominator is a handful and the percentage is noise —
    # it is clamped to [0,100] and reported with n so it can be discounted.
    max_mno = max(1, n - len(b))
    return {"mno_cut_to_human": ab, "mno_human_to_cut": ba,
            "mojo": min(ab, ba), "n_objects": n, "max_mno": max_mno,
            "mojofm_pct": round(max(0.0, min(100.0, 100.0 * (1 - ab / max_mno))), 1)}


# ── reporting ──────────────────────────────────────────────────────────────

def dist(values: list[int]) -> dict:
    if not values:
        return {"min": None, "median": None, "max": None}
    s = sorted(values)
    return {"min": s[0], "median": s[len(s) // 2], "max": s[-1]}


def run_repo(conn, slug: str) -> dict:
    started = time.time()
    clusters = load_clusters(conn, slug)
    components = load_components(conn, slug)
    metrics = load_metrics(conn, slug)
    shapes = load_shapes(conn, slug)
    touchpoints = load_touchpoints(conn, slug)
    tokens, public, edges = load_symbols(conn, slug)
    load_secs = time.time() - started

    result = {"repo": slug, "perspectives_present": sorted(clusters),
              "load_seconds": round(load_secs, 2), "lenses": {},
              "cluster_nodes": {p: len(c) for p, c in clusters.items()},
              "inheritance_edges": len(edges)}

    trees: dict[str, tuple[list[Node], list[str], Measurer]] = {}
    result["tree_notes"] = {}
    for persp, details in clusters.items():
        roots, stragglers, notes = build_tree(details, components, persp)
        comps_p = {s: c for s, c in components.items() if c.get("perspective") == persp}
        counts: Counter = Counter()

        def _count(n: Node):
            if n.kind == "component":
                counts[n.scope] += 1
            for ch in n.children:
                _count(ch)
        for root in roots:
            _count(root)
        notes["components_reachable_by_more_than_one_cluster"] = sum(
            1 for v in counts.values() if v > 1)
        result["tree_notes"][persp] = notes
        trees[persp] = (roots, stragglers,
                        Measurer(metrics, shapes, touchpoints, tokens, public, edges, comps_p))

    for lens in ("deploy", "learn", "maintain"):
        lens_out = {"perspectives": {}, "unavailable": []}
        for persp in LENS_PERSPECTIVES[lens]:
            if persp not in trees:
                lens_out["unavailable"].append(persp)
                continue
            roots, stragglers, measurer = trees[persp]
            nodes = cut(roots, lens, measurer)
            sizes = [n.metrics["size"] for n in nodes]
            buckets = Counter(classify(lens, n) for n in nodes)
            # family agreement over the nodes at this cut
            agree, disagree, abstain = 0, [], 0
            matrix = Counter()
            for node in nodes:
                op = {f: verdict_of(node.metrics, f) for f in ("import", "cochange", "semantic")}
                held = [v for v in op.values() if v is not None]
                if len(held) < 2:
                    abstain += 1
                    continue
                matrix[tuple(sorted((f, v) for f, v in op.items() if v is not None))] += 1
                if len(set(held)) == 1:
                    agree += 1
                else:
                    disagree.append({"node": node.name, "kind": node.kind,
                                     "size": node.metrics["size"],
                                     "import": node.metrics["import_cohesion"],
                                     "cochange": node.metrics["cochange_cohesion"],
                                     "semantic": (round(node.metrics["semantic_cohesion"], 3)
                                                  if node.metrics["semantic_cohesion"] is not None else None),
                                     "oversized": node.oversized, "signal": node.signal})
            lens_out["perspectives"][persp] = {
                "decision_count": len(nodes),
                "size_distribution": dist(sizes),
                "accept_as_unit": buckets["accept-as-unit"],
                "contested": buckets["contested"],
                "needs_review": buckets["needs-review"],
                "no_signal": buckets["no-signal"],
                "stragglers": len(stragglers),
                "straggler_examples": stragglers[:10],
                "families_agree": agree,
                "families_disagree": len(disagree),
                "families_abstain": abstain,
                "agreement_matrix": {json.dumps(k): v for k, v in matrix.items()},
                "disagreeing_nodes": sorted(disagree, key=lambda d: -d["size"])[:15],
                "nodes": [{"name": n.name, "kind": n.kind, **{
                    k: (round(v, 3) if isinstance(v, float) else v)
                    for k, v in n.metrics.items()}} for n in nodes],
            }
        result["lenses"][lens] = lens_out

    result["measure_seconds"] = round(time.time() - started, 2)

    # ── step 5: human verdicts
    rows = conn.execute(
        "SELECT scope_locator, verdict, verdict_target, created_at, note "
        "FROM architecture_component_verdicts WHERE entity_type='repo' AND entity_slug=%s "
        "ORDER BY created_at ASC", (slug,)).fetchall()
    latest_v: dict[str, dict] = {}
    for row in rows:
        latest_v[(row["verdict_target"], row["scope_locator"])] = dict(row)
    comp_verdicts = {k[1]: v for k, v in latest_v.items() if k[0] == "component"}
    result["verdicts"] = {
        "rows_total": len(rows),
        "distinct_component_scopes": len(comp_verdicts),
        "distinct_blueprint_scopes": sum(1 for k in latest_v if k[0] == "blueprint"),
        "anecdotal": len(comp_verdicts) < 20,
        "accepted": sorted(s for s, v in comp_verdicts.items() if v["verdict"] == "accepted"),
        "rejected": sorted(s for s, v in comp_verdicts.items() if v["verdict"] == "rejected"),
    }
    if comp_verdicts:
        result["verdict_comparison"] = compare_verdicts(comp_verdicts, trees, components, result)
    return result


def compare_verdicts(comp_verdicts, trees, components, result) -> dict:
    """MoJo between each lens cut and the partition the human verdicts imply.

    The human partition: every ACCEPTED scope becomes one group holding the
    component leaves beneath it; rejected scopes contribute nothing. Objects are
    restricted to leaves the human actually ruled on, since MoJo is undefined
    over objects one partition never saw.
    """
    out = {}
    accepted = [s for s, v in comp_verdicts.items() if v["verdict"] == "accepted"]
    for lens, lens_out in result["lenses"].items():
        for persp, block in lens_out["perspectives"].items():
            if persp not in trees:
                continue
            roots, _strag, _m = trees[persp]
            index: dict[str, Node] = {}

            def walk(n: Node):
                index[n.name] = n
                for c in n.children:
                    walk(c)
            for r in roots:
                walk(r)
            human = []
            for scope in accepted:
                node = index.get(scope)
                leaves = set(node.leaves) if node else ({scope} if scope in components else set())
                if leaves:
                    human.append(leaves)
            universe = set().union(*human) if human else set()
            if not universe:
                out[f"{lens}/{persp}"] = {"applicable": False,
                                          "why": "no accepted scope resolves to a node in this perspective's tree"}
                continue
            cut_groups = []
            for entry in block["nodes"]:
                node = index.get(entry["name"])
                leaves = set(node.leaves) & universe if node else set()
                if leaves:
                    cut_groups.append(leaves)
            if not cut_groups:
                out[f"{lens}/{persp}"] = {"applicable": False,
                                          "why": "the cut covers none of the verdicted objects"}
                continue
            stats = mojo(cut_groups, human)
            stats["applicable"] = True
            stats["human_groups"] = len(human)
            stats["cut_groups"] = len(cut_groups)
            # do the families agree on the accepted nodes?
            agree_on_accepted = []
            for scope in accepted:
                node = index.get(scope)
                if not node or not node.metrics:
                    continue
                op = [verdict_of(node.metrics, f) for f in ("import", "cochange", "semantic")]
                held = [v for v in op if v is not None]
                agree_on_accepted.append({
                    "scope": scope, "families_held": len(held),
                    "agree": (len(set(held)) == 1) if len(held) >= 2 else None,
                    "cohesive": (all(held) if held else None), "size": node.metrics["size"]})
            stats["accepted_node_agreement"] = agree_on_accepted
            out[f"{lens}/{persp}"] = stats
    return out


def print_report(results: list[dict]) -> None:
    for res in results:
        print(f"\n{'=' * 78}\n{res['repo']}  —  perspectives stored: "
              f"{', '.join(res['perspectives_present']) or 'NONE'}   "
              f"(load {res['load_seconds']}s, steps 1-4 {res['measure_seconds']}s)")
        print(f"  cluster nodes per perspective: {res['cluster_nodes']}   "
              f"inheritance edges resolved: {res['inheritance_edges']}")
        for lens, block in res["lenses"].items():
            if block["unavailable"]:
                print(f"  [{lens}] perspectives UNAVAILABLE (no stored clusters): "
                      f"{', '.join(block['unavailable'])}")
            for persp, stats in block["perspectives"].items():
                d = stats["size_distribution"]
                print(f"  [{lens}/{persp}] decisions={stats['decision_count']:>4} "
                      f"size min/med/max={d['min']}/{d['median']}/{d['max']}  "
                      f"accept={stats['accept_as_unit']} contested={stats['contested']} "
                      f"review={stats['needs_review']} no-signal={stats['no_signal']} "
                      f"stragglers={stats['stragglers']}")
                print(f"      families: agree={stats['families_agree']} "
                      f"disagree={stats['families_disagree']} "
                      f"abstain(<2 opinions)={stats['families_abstain']}")
                for node in stats["disagreeing_nodes"][:5]:
                    print(f"        ! {node['node']} (size {node['size']}) "
                          f"imp={node['import']} coc={node['cochange']} sem={node['semantic']}")
        v = res.get("verdicts", {})
        print(f"  verdicts: {v.get('rows_total', 0)} rows, "
              f"{v.get('distinct_component_scopes', 0)} distinct component scopes"
              + ("  [ANECDOTAL: <20]" if v.get("anecdotal") else ""))
        for key, stats in (res.get("verdict_comparison") or {}).items():
            if not stats.get("applicable"):
                print(f"      {key}: not applicable — {stats['why']}")
            else:
                print(f"      {key}: MoJo={stats['mojo']} "
                      f"(cut->human {stats['mno_cut_to_human']}, human->cut {stats['mno_human_to_cut']}) "
                      f"MoJoFM={stats['mojofm_pct']}% over n={stats['n_objects']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repos", default="kafka,egeria_python_git,docling")
    ap.add_argument("--out", default=os.environ.get("LENSES_SPIKE_OUT", "."))
    args = ap.parse_args()

    here = Path(__file__).resolve().parents[1]
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    from resource_explorer.registry import ProjectRegistry

    registry = ProjectRegistry()
    results = []
    with registry._conn() as conn:
        for slug in [s.strip() for s in args.repos.split(",") if s.strip()]:
            results.append(run_repo(conn, slug))

    print_report(results)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / "curation_lenses_spike.json"
    path.write_text(json.dumps(
        {"parameters": {"CUT_DEPTH": CUT_DEPTH, "LENS_PERSPECTIVES": LENS_PERSPECTIVES,
                        "LENS_DECIDERS": {k: list(v) for k, v in LENS_DECIDERS.items()},
                        "IMPORT_BAR": IMPORT_BAR, "COCHANGE_BAR": COCHANGE_BAR,
                        "SEMANTIC_BAR": SEMANTIC_BAR, "MIN_COVERAGE": MIN_COVERAGE,
                        "DEPLOY_MIN_TOUCHPOINTS": DEPLOY_MIN_TOUCHPOINTS,
                        "SEMANTIC_MAX_MEMBERS": SEMANTIC_MAX_MEMBERS},
         "results": results}, indent=1, default=str))
    print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
