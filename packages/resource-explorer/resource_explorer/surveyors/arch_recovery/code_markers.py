"""Code-marker detection — design §5.1's code half, via ast-grep.

The manifest and deployment detectors in `detectors.py` find components that
something *declares*. This finds components that only the code shows: a web
service, a CLI, a TUI, a scheduler. It is the half that matters for repos with
no deployment artifacts at all, which is most of them (plan §3, T2).

**These are `logical`-perspective components.** A marker says "this subtree
serves HTTP" — a statement about design, not about a file on disk or a
container that would be started. It is therefore the first detector here that
emits anything comparable to a logical-perspective ground truth (§4.1).

Boundary rule, and the reasoning matters more than the rule: a marker marks a
*file*, and a component is a *subtree*, so something must decide how far up to
attribute the marker. **The generator does not choose a depth** (spike README
findings 55/56/59 — a single fixed depth fits no repo shape in general: it
yields nothing on a flat app, only `src/main`/`src/test` on Gradle, and only
the right answer on a Python monorepo because that is the layout it was tuned
to). Instead every directory holding >=2 first-party files, at every depth
beneath the owning package root, is a candidate subtree, linked to its nearest
candidate ancestor (`build_hierarchy` below) — depth is never discarded
(approach-portfolio-model.md §2a: "store the hierarchy; project a level"). A
marker is attributed to the deepest candidate that contains it.

That is a structural rule, chosen because it derives from the manifest
boundary already detected, NOT because it reproduces any particular ground
truth. The distinction is load-bearing: picking a depth because it matches the
expected answer would make the Phase 0 comparison circular, which is the whole
reason the ground truth was pre-registered (plan §4).

Client-library markers (`client-postgres`, `client-kafka`, `client-boto3`) are
deliberately NOT component proposals. An outbound call says a component talks
to something; it does not say a component exists there. They are wire/port
evidence, attached to a component detected some other way — §5.2's rule that a
detector never invents a component applies to detectors too, not just the LLM.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections import defaultdict

from .ir import Component, Evidence, Identity, Location

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules")

# rule id -> (SolutionComponentType, confidence, proposes a component?)
# Confidence reflects how strongly the marker implies the *whole subtree* is
# that kind of component, not how sure we are the pattern matched.
MARKER_ROLES: dict[str, tuple[str, int, bool]] = {
    "fastapi-app-construction":  ("Software Service",  85, True),
    "fastapi-route-registration": ("Software Service", 70, True),
    "typer-cli-construction":    ("Console Command",   80, True),
    "textual-app-subclass":      ("User Interface",    80, True),
    "scheduler-worker":          ("Automated Action",  75, True),
    # wire evidence only — see module docstring
    "client-postgres":           ("",                  0,  False),
    "client-kafka":              ("",                  0,  False),
    "client-boto3":              ("",                  0,  False),
}


def marker_languages() -> set[str]:
    """Which languages have at least one rule in RULES_DIR — read from each
    rule file's own `language:` field rather than hardcoded, so a new marker
    rule for another language (e.g. a Rust `axum`/`clap` construction rule)
    starts counting the moment its .yml lands, with nothing else to update.
    Lowercased so callers can compare against imports.languages_present()'s
    keys without a case-mapping table."""
    langs: set[str] = set()
    for fn in sorted(os.listdir(RULES_DIR)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        with open(os.path.join(RULES_DIR, fn), encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("language:"):
                    langs.add(line.split(":", 1)[1].strip().lower())
                    break
    return langs


def _binary() -> str | None:
    """Prefer the venv's ast-grep over a system one, so the spike works for
    anyone who ran `uv sync` (pyproject declares `ast-grep-cli`). Verified
    necessary: on this machine ast-grep resolves from .venv/bin and NOT from
    PATH despite a Homebrew install."""
    here = os.path.dirname(os.path.abspath(__file__))
    for up in range(2, 7):
        cand = os.path.join(here, *([".."] * up), ".venv", "bin", "ast-grep")
        cand = os.path.normpath(cand)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return shutil.which("ast-grep") or shutil.which("sg")


def scan(root: str, first_party: set[str] | None = None) -> dict[str, list[dict]]:
    """rule id -> matches. Matches outside `first_party` are dropped, so
    vendored code cannot propose components (plan §3a)."""
    binary = _binary()
    if binary is None:
        return {}
    out: dict[str, list[dict]] = {}
    for fn in sorted(os.listdir(RULES_DIR)):
        if not fn.endswith((".yml", ".yaml")):
            continue
        rule_path = os.path.join(RULES_DIR, fn)
        try:
            proc = subprocess.run([binary, "scan", "-r", rule_path, root, "--json=compact"],
                                  capture_output=True, timeout=300)
        except (OSError, subprocess.SubprocessError):
            continue
        raw = proc.stdout.decode("utf-8", "replace").strip()
        if not raw:
            continue
        try:
            matches = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for m in matches:
            rel = os.path.relpath(m.get("file", ""), root)
            if first_party is not None and rel not in first_party:
                continue
            m["_rel"] = rel
            out.setdefault(m.get("ruleId") or fn[:-4], []).append(m)
    return out


def _package_root_for(rel: str, package_roots: list[str]) -> str | None:
    """The nearest (longest-matching) package root enclosing `rel`."""
    return max((p for p in package_roots
                if rel == p or rel.startswith(p.rstrip("/") + "/") or p == "."),
               key=len, default=None)


def _ancestor_dirs(rel: str, root: str) -> list[str]:
    """`rel`'s own directory and every ancestor, deepest first, ENDING WITH
    `root` itself (depth 0). A file sitting directly in `root` — no
    subdirectory at all — yields `[root]`: the package root is itself
    eligible as a candidate (below), which is what fixes the flat-repo case
    (spike README findings 36/55) — a repo with no subdirectory structure
    still has exactly one thing that can become a candidate, the whole
    package, instead of structurally having nothing (the old fixed-depth
    rule's "a file directly in the root is not a subtree")."""
    prefix = root.rstrip("/") + "/" if root != "." else ""
    inner = rel[len(prefix):] if prefix else rel
    parts = [p for p in inner.split("/")[:-1] if p]
    return [prefix + "/".join(parts[:i]) for i in range(len(parts), 0, -1)] + [root]


def _ancestors_of_dir(d: str, root: str) -> list[str]:
    """Ancestors of directory `d` (excluding `d` itself), deepest first,
    ending with `root` itself (empty when `d` already IS `root`)."""
    if d == root:
        return []
    prefix = root.rstrip("/") + "/" if root != "." else ""
    inner = d[len(prefix):] if prefix else d
    parts = [p for p in inner.split("/") if p]
    return [prefix + "/".join(parts[:i]) for i in range(len(parts) - 1, 0, -1)] + [root]


def _dir_depth(d: str, root: str) -> int:
    """Path segments between `root` and `d` (0 when `d` IS `root`)."""
    if d == root:
        return 0
    prefix = root.rstrip("/") + "/" if root != "." else ""
    inner = d[len(prefix):] if prefix else d
    return len([p for p in inner.split("/") if p])


def build_hierarchy(files: list[str], package_roots: list[str]) -> dict[str, dict]:
    """Every directory under a package root holding >=2 first-party files
    DIRECTLY (not recursively) is a candidate subtree — approach-portfolio-
    model.md §2a: depth is never discarded, every candidate is retained and
    linked to its nearest candidate ancestor rather than one depth being
    chosen (spike README findings 55/56/59 — depth profiles measured across
    six repo shapes share no common pattern, so no fixed rule or shape-
    detection scheme can substitute for keeping all of them).

    Returns `{subtree_path: {"depth": int, "parent": str | None, "root": str,
    "files": set[str]}}`. `depth` counts path segments below the package
    root (0 = the package root itself, eligible exactly when >=2
    first-party files sit directly in it with no subdirectory — the flat-
    repo case). `parent` is the nearest ancestor directory that is ALSO a
    candidate, or `None` when no ancestor qualifies (this subtree is the
    coarsest available reading for its branch).
    """
    direct: dict[str, set[str]] = defaultdict(set)
    depth_of: dict[str, int] = {}
    root_of: dict[str, str] = {}

    for f in files:
        root = _package_root_for(f, package_roots)
        if root is None:
            continue
        chain = _ancestor_dirs(f, root)          # deepest first, ends with root itself
        direct[chain[0]].add(f)                  # chain[0] = f's own dir (or root, if flat)
        for d in chain:
            depth_of[d] = _dir_depth(d, root)
            root_of[d] = root

    candidates = {d for d, fs in direct.items() if len(fs) >= 2}
    hierarchy: dict[str, dict] = {}
    for d in candidates:
        root = root_of[d]
        parent = next((a for a in _ancestors_of_dir(d, root) if a in candidates), None)
        hierarchy[d] = {"depth": depth_of[d], "parent": parent, "root": root, "files": direct[d]}
    return hierarchy


def file_subtree_map(files: list[str],
                     package_roots: list[str]) -> tuple[dict[str, str], dict[str, dict]]:
    """file -> its deepest owning candidate subtree (its own directory if
    that qualifies, else the nearest candidate ancestor) — the residue
    attribution is inherent here: a file under a non-candidate descendant of
    a candidate directory is attributed straight to that candidate, with no
    separate adoption pass needed for it (unlike a candidate that was later
    dropped by classification — see coupling.py's `_rehome_dropped`).

    Returns `(file_subtree, hierarchy)`; `hierarchy` is `build_hierarchy`'s
    output, returned alongside so a caller does not recompute it.
    """
    hierarchy = build_hierarchy(files, package_roots)
    out: dict[str, str] = {}
    for f in files:
        root = _package_root_for(f, package_roots)
        if root is None:
            continue
        for d in _ancestor_dirs(f, root):
            if d in hierarchy:
                out[f] = d
                break
    return out, hierarchy


def propose(root: str, first_party: list[str], package_roots: list[str],
            ) -> tuple[list[Component], list[Evidence], list[str]]:
    fp = set(first_party)
    hits = scan(root, fp)
    if not hits:
        return [], [], ["ast-grep unavailable or no rule matched — no code-marker components"]

    notes: list[str] = []
    # Every candidate subtree at every depth (§2a) — a marker is attributed
    # to the deepest one that contains it, not to a fixed depth.
    file_subtree, hierarchy = file_subtree_map(sorted(fp), package_roots)
    # subtree -> role -> [matches]
    by_subtree: dict[str, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    wires: dict[str, list[dict]] = defaultdict(list)

    for rule_id, matches in hits.items():
        role = MARKER_ROLES.get(rule_id)
        if role is None:
            notes.append(f"rule {rule_id!r} has no MARKER_ROLES entry — ignored")
            continue
        ctype, conf, proposes = role
        for m in matches:
            sub = file_subtree.get(m["_rel"])
            if sub is None:
                continue
            (by_subtree[sub][rule_id] if proposes else wires[sub]).append(m)

    components: list[Component] = []
    evidence: list[Evidence] = []

    for sub, roles in sorted(by_subtree.items()):
        # Strongest marker wins the type; a subtree serving HTTP *and* exposing
        # a CLI is reported as the higher-confidence one, with the loser kept as
        # evidence rather than silently dropped.
        ranked = sorted(roles.items(),
                        key=lambda kv: (MARKER_ROLES[kv[0]][1], len(kv[1])), reverse=True)
        top_rule, top_matches = ranked[0]
        ctype, conf, _ = MARKER_ROLES[top_rule]
        name = os.path.basename(sub)
        slug = f"code::{sub.replace('/', '::')}"
        node = hierarchy.get(sub, {})
        parent_dir = node.get("parent")
        components.append(Component(
            slug=slug, name=name, type=ctype,
            identity=Identity("module-path", sub),
            files=["**" if sub == "." else f"{sub}/**"], confidence=conf, confidence_level="Derived",
            perspective="logical",
            parent_slug=f"code::{parent_dir.replace('/', '::')}" if parent_dir else "",
            depth=node.get("depth", 0),
        ))
        for rule_id, ms in ranked:
            rtype, rconf, _ = MARKER_ROLES[rule_id]
            evidence.append(Evidence(
                subject_kind="component", subject_slug=slug,
                assertion=(f"solutionComponentType = {rtype}" if rule_id == top_rule
                           else f"also matches {rule_id} ({rtype})"),
                detector=f"ast-grep:{rule_id}",
                locations=[Location(m["_rel"], m.get("range", {}).get("start", {}).get("line", 0) + 1,
                                    (m.get("text") or "")[:80]) for m in ms[:3]],
                confidence=rconf if rule_id == top_rule else max(30, rconf - 20),
                confidence_level="Derived",
            ))
        if len(ranked) > 1:
            notes.append(f"{sub}: {len(ranked)} marker roles "
                         f"({', '.join(r for r, _ in ranked)}) — typed as {ctype}")

    for sub, ms in sorted(wires.items()):
        slug = f"code::{sub.replace('/', '::')}"
        by_rule: dict[str, list[dict]] = defaultdict(list)
        for m in ms:
            by_rule[m.get("ruleId", "client")].append(m)
        for rule_id, rms in by_rule.items():
            evidence.append(Evidence(
                subject_kind="component", subject_slug=slug,
                assertion=f"outbound dependency ({rule_id}) — wire evidence, not a component",
                detector=f"ast-grep:{rule_id}",
                locations=[Location(m["_rel"], m.get("range", {}).get("start", {}).get("line", 0) + 1,
                                    (m.get("text") or "")[:80]) for m in rms[:3]],
                confidence=60, confidence_level="Derived",
            ))

    notes.append(f"code markers: {len(components)} logical components from "
                 f"{sum(len(v) for v in hits.values())} matches across {len(hits)} rules")
    return components, evidence, notes
