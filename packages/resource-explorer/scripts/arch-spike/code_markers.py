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
attribute the marker. The rule used here is **the top-level subpackage beneath
the owning manifest's package root** — the manifest already establishes the
package root (identity precedence rung 2, §8.2), and the conventional
subdivision of a package is its immediate subpackages.

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

from ir import Component, Evidence, Identity, Location

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
    # Go (finding 94 — the marker proposer was Python-only, so every non-Python
    # target had been running three proposers rather than four)
    "go-http-server":            ("Software Service",  85, True),
    "go-grpc-server":            ("Software Service",  85, True),
    "go-cli-construction":       ("Console Command",   80, True),
    # Java. `java-main-method` is the JVM analogue of finding 78's `package main`
    # entry-point detection: declared, not inferred from a filename.
    "java-spring-service":       ("Software Service",  85, True),
    "java-main-method":          ("Console Command",   75, True),
    "java-scheduled":            ("Automated Action",  75, True),
    # wire evidence only — see module docstring
    "go-client-sql":             ("",                  0,  False),
    "client-postgres":           ("",                  0,  False),
    "client-kafka":              ("",                  0,  False),
    "client-boto3":              ("",                  0,  False),
}


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


def _subtree_for(rel: str, package_roots: list[str]) -> str | None:
    """The top-level subpackage beneath the nearest enclosing package root."""
    best = max((p for p in package_roots
                if rel == p or rel.startswith(p.rstrip("/") + "/") or p == "."),
               key=len, default=None)
    if best is None:
        return None
    inner = rel[len(best):].lstrip("/") if best != "." else rel
    parts = [p for p in inner.split("/") if p]
    if len(parts) < 2:            # a file directly in the root is not a subtree
        return None
    prefix = best.rstrip("/") + "/" if best != "." else ""
    # skip the distribution directory itself (resource-explorer/resource_explorer/...)
    return f"{prefix}{parts[0]}/{parts[1]}" if len(parts) > 2 else f"{prefix}{parts[0]}"


def propose(root: str, first_party: list[str], package_roots: list[str],
            ) -> tuple[list[Component], list[Evidence], list[str]]:
    fp = set(first_party)
    hits = scan(root, fp)
    if not hits:
        return [], [], ["ast-grep unavailable or no rule matched — no code-marker components"]

    notes: list[str] = []
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
            sub = _subtree_for(m["_rel"], package_roots)
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
        components.append(Component(
            slug=slug, name=name, type=ctype,
            identity=Identity("module-path", sub),
            files=[f"{sub}/**"], confidence=conf, confidence_level="Derived",
            perspective="logical",
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
