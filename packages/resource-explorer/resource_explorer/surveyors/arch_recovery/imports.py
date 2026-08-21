#!/usr/bin/env python3
"""Module import graph — design §5.5 signal 1, plan §0(a).

    python3 imports.py /path/to/checkout --target trellis   # -> signals/trellis-imports.json

**Why this exists at all (README finding 20).** Code markers only recover a
boundary where a *framework* is used. On trellis that is 4 of 11 ground-truth
components; the other 7 (`Agents`, `Core`, `RAG ingestion`, `Observability`,
`Surveyors`, `Utility scripts`) are conventional, not declared, and no marker
rule could ever see them. Import coupling is one of the two detector-side
signals (co-change is the other, `cochange.py`) that could propose such a
boundary instead of just validating one someone else proposed.

**Scope: Python only, and that is not laziness — it is measured.** Both
targets are checked with `exclusion.py`'s own first-party census before
committing to this: trellis is 472 first-party `.py` files against 7 `.js`;
egeria-workspaces-fs is 167 `.py` against 6 `.js` + 1 `.ts`. Real import
syntax in JS/TS (`require`, dynamic `import()`, bundler aliases) is a
different extraction problem for a signal that would touch under 2% of
either target's first-party files. Not built; noted as a finding rather than
silently scoped down.

**Extraction is ast-grep** (plan §0(a): do not join `project_code_relationships`
× `project_code_symbols` — that recovers `inherits_from` pairs, not imports;
do not adopt grimp — it imports the code to resolve it, needing the dependency
environment installed). `rules-imports/import-python.yml` matches the three
Python import node kinds. That rule lives in its own directory, not
`rules/`, so `code_markers.py`'s scan of `rules/*.yml` never sees it and
never logs a spurious "no MARKER_ROLES entry" note for it.

**Resolution is ast-grep's *finding* + Python's own `ast` module for
*parsing* the text ast-grep found** — re-deriving module/name/level from a
hand-rolled regex over Python import syntax (relative dots, parenthesised
multi-imports, `as` aliases, `from __future__ import ...`) would silently
break on a form nobody tested, exactly the finding-19 lesson from the
code-marker rules. `ast.parse` on the *matched snippet* is not "using ast
instead of ast-grep" — ast-grep still does the extraction (which lines are
import statements); ast only structures what was already found.

Resolution itself is a best-effort static approximation, stated so the
numbers are read correctly:

- **Absolute imports** (`import a.b.c`, `from a.b import c`) are resolved
  against a set of *source roots*: every directory holding a `pyproject.toml`
  (§8.2 rung 2) plus every deployment-unit directory (§8.2 rung 1 — this is
  what lets `PyegeriaWebHandler`, which ships no manifest at all per
  README finding 4, resolve its own internal imports) plus the checkout root
  itself as a last resort.
- **Relative imports** (`from . import x`, `from ..pkg import y`) resolve
  directly from the importing file's own directory using the dot-count
  (`level`), which needs no source root at all.
- `from a.b import c` cannot distinguish "c is a submodule of a.b" from "c is
  a symbol defined in a.b" without executing the code. Submodule is tried
  first (`a/b/c.py`); if that does not exist as a first-party file, the edge
  targets the *package* (`a/b/__init__.py` or `a/b.py`) instead of guessing
  which symbol. Either way the edge lands on the right file; only in the
  disjunction case could it land on `a/b/__init__.py` when the true source of
  `c` is a sibling re-exported through it.
- Anything that does not resolve to a first-party file (stdlib, third-party,
  or a resolution miss) is recorded as **external**, not silently dropped —
  plan Task 1 asks for this explicitly: "an external-heavy subtree is a
  different kind of component."

No network, no import execution, no dependency environment.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import textwrap
from collections import Counter

from . import exclusion
from .code_markers import _binary  # reuse — do NOT reimplement the venv-vs-PATH lookup

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules-imports")


# ── ast-grep extraction ─────────────────────────────────────────────────

def _scan_import_statements(root: str, first_party_py: set[str]) -> list[dict]:
    """Every Python import-statement match, restricted to first-party files.
    Mirrors code_markers.scan()'s shape but against its own rules dir."""
    import subprocess
    binary = _binary()
    if binary is None:
        return []
    rule_path = os.path.join(RULES_DIR, "import-python.yml")
    try:
        proc = subprocess.run([binary, "scan", "-r", rule_path, root, "--json=compact"],
                              capture_output=True, timeout=300)
    except (OSError, subprocess.SubprocessError):
        return []
    raw = proc.stdout.decode("utf-8", "replace").strip()
    if not raw:
        return []
    try:
        matches = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out = []
    for m in matches:
        rel = os.path.relpath(m.get("file", ""), root).replace(os.sep, "/")
        if rel not in first_party_py:
            continue
        m["_rel"] = rel
        out.append(m)
    return out


# ── parsing the matched snippet ─────────────────────────────────────────

def _parse_snippet(text: str) -> list[tuple[str | None, str | None, int]]:
    """One matched import statement's text -> list of (module, name, level).

    `module` is the dotted path (None for a bare `import x`'s own case is
    never hit — `import` always has a module). `name` is the imported symbol
    for `from` imports, or None for plain `import module` forms (those are
    resolved on `module` alone). `level` is the leading-dot count (0 for
    absolute). One statement can import several names (`from a import b, c`
    or `import a, b`), so this returns a list.
    """
    try:
        tree = ast.parse(textwrap.dedent(text))
    except SyntaxError:
        return []
    out: list[tuple[str | None, str | None, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                out.append((alias.name, None, 0))
        elif isinstance(node, ast.ImportFrom):
            module = node.module  # None for `from . import x`
            for alias in node.names:
                out.append((module, alias.name, node.level))
    return out


# ── resolution ───────────────────────────────────────────────────────────

def _try_module_file(dotted_parts: list[str], root_prefix: str, fp_set: set[str]) -> str | None:
    if not dotted_parts:
        cand = f"{root_prefix}/__init__.py".lstrip("/")
        return cand if cand in fp_set else None
    base = "/".join([root_prefix] + dotted_parts) if root_prefix else "/".join(dotted_parts)
    for cand in (f"{base}.py", f"{base}/__init__.py"):
        if cand in fp_set:
            return cand
    return None


def roots_for_file(importing_file: str, source_roots: list[str]) -> list[str]:
    """`source_roots` reordered so the importing file's OWN enclosing roots
    come first, nearest first.

    Resolving against one global, globally-ordered root list is wrong whenever
    a repo contains two copies of the same code, and egeria-workspaces does:
    `PyegeriaWebHandler` ships once under egeria-quickstart and once under
    egeria-freshstart, both of which are source roots, both containing a file
    called `common_serialize.py`. A flat sibling import (`from common_serialize
    import ...`) in a *quickstart* handler was resolving into the *freshstart*
    copy, because the global ordering put freshstart first for every file
    regardless of where the import lived.

    Measured before the fix: 156 of 170 quickstart-sourced edges pointed into
    freshstart, and only 14 stayed inside quickstart. An import resolves within
    its own copy first — that is what "sibling" means."""
    own = [r for r in source_roots
           if r != "." and (importing_file == r or importing_file.startswith(r + "/"))]
    own.sort(key=len, reverse=True)          # nearest enclosing root first
    return own + [r for r in source_roots if r not in own]


def resolve_absolute(module: str, source_roots: list[str], fp_set: set[str]) -> str | None:
    parts = module.split(".")
    for root in source_roots:
        prefix = "" if root == "." else root
        hit = _try_module_file(parts, prefix, fp_set)
        if hit:
            return hit
    return None


def resolve_relative(module: str | None, level: int, importing_file: str,
                      fp_set: set[str]) -> str | None:
    """`level` dots up from the importing file's own package."""
    own_dir_parts = os.path.dirname(importing_file).split("/") if "/" in importing_file \
        else ([os.path.dirname(importing_file)] if os.path.dirname(importing_file) else [])
    own_dir_parts = [p for p in own_dir_parts if p]
    # level=1 -> current package (own_dir_parts itself); each extra level
    # strips one more segment.
    up = level - 1
    target_dir_parts = own_dir_parts[: len(own_dir_parts) - up] if up else own_dir_parts
    if module:
        return _try_module_file(module.split("."), "/".join(target_dir_parts), fp_set)
    # bare `from . import x` / `from .. import x` — x is a submodule (or a
    # symbol re-exported by __init__.py; submodule is tried first).
    return None  # caller resolves per-name against target_dir_parts


def resolve_relative_name(name: str, level: int, importing_file: str, fp_set: set[str]) -> str | None:
    own_dir_parts = [p for p in os.path.dirname(importing_file).split("/") if p]
    up = level - 1
    target_dir_parts = own_dir_parts[: len(own_dir_parts) - up] if up else own_dir_parts
    return _try_module_file([name], "/".join(target_dir_parts), fp_set) or \
        _try_module_file([], "/".join(target_dir_parts + [name]), fp_set)


# ── driving one target ──────────────────────────────────────────────────

def source_roots(root: str, first_party: list[str]) -> list[str]:
    """Every plausible import-resolution root: manifest dirs (§8.2 rung 2),
    deployment-unit dirs (§8.2 rung 1 — covers manifest-less units like
    PyegeriaWebHandler, README finding 4), and the checkout root itself.
    Longest (most specific) first, so a nested manifest wins over the root."""
    from . import detectors
    roots: set[str] = {"."}
    for m in detectors.python_manifests(root, first_party):
        roots.add(m["dir"])
    try:
        for unit in detectors.deployment_units(root, first_party):
            roots.add(unit)
    except Exception:
        pass
    return sorted(roots, key=len, reverse=True)


def build_graph(root: str, first_party: list[str]) -> dict:
    fp_py = sorted(f for f in first_party if f.endswith(".py"))
    fp_set = set(fp_py)
    roots = source_roots(root, first_party)

    matches = _scan_import_statements(root, fp_set)
    ast_available = _binary() is not None

    edges: list[dict] = []
    external_hits: Counter = Counter()          # (source_file, external_module) -> not needed; aggregate
    external_by_file: Counter = Counter()
    parse_failures: list[dict] = []
    resolved_count = 0
    unresolved_count = 0

    for m in matches:
        src = m["_rel"]
        line = m.get("range", {}).get("start", {}).get("line", 0) + 1
        parsed = _parse_snippet(m.get("text") or "")
        if not parsed and (m.get("text") or "").strip():
            parse_failures.append({"file": src, "line": line, "text": (m.get("text") or "")[:120]})
            continue
        for module, name, level in parsed:
            target = None
            kind = "absolute" if level == 0 else "relative"
            if level == 0:
                if module:
                    file_roots = roots_for_file(src, roots)
                    target = resolve_absolute(module, file_roots, fp_set)
                    if target is None and name:
                        target = resolve_absolute(f"{module}.{name}", file_roots, fp_set)
                display = f"{module}.{name}" if (module and name) else (module or name or "?")
            else:
                if module:
                    target = resolve_relative(module, level, src, fp_set)
                    if target is None:
                        target = resolve_relative_name(name or "", level, src, fp_set) if name else None
                    display = f"{'.' * level}{module}.{name}" if name else f"{'.' * level}{module}"
                else:
                    target = resolve_relative_name(name or "", level, src, fp_set) if name else None
                    display = f"{'.' * level}{name or ''}"

            if target and target != src:
                edges.append({"source": src, "target": target, "kind": kind,
                              "line": line, "raw": display})
                resolved_count += 1
            elif target is None:
                external_by_file[src] += 1
                unresolved_count += 1

    # de-duplicate identical (source, target) pairs but keep a weight —
    # a file importing another via 3 separate `from x import a/b/c` lines
    # is one architectural edge, weighted by how many symbols cross it.
    weighted: dict[tuple[str, str], dict] = {}
    for e in edges:
        key = (e["source"], e["target"])
        w = weighted.setdefault(key, {"source": e["source"], "target": e["target"],
                                      "kind": e["kind"], "weight": 0, "lines": []})
        w["weight"] += 1
        if len(w["lines"]) < 5:
            w["lines"].append(e["line"])

    return {
        "root": root,
        "python_files_scanned": len(fp_py),
        "source_roots": roots,
        "ast_grep_available": ast_available,
        "import_statements_matched": len(matches),
        "edges": sorted(weighted.values(), key=lambda e: (e["source"], e["target"])),
        "edge_count": len(weighted),
        "resolved_import_count": resolved_count,
        "unresolved_import_count": unresolved_count,
        "external_by_file": dict(external_by_file.most_common()),
        "parse_failures": parse_failures,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[2])
    ap.add_argument("root")
    ap.add_argument("--target", help="output filename stem; defaults to directory name")
    ap.add_argument("--out", default="signals")
    ap.add_argument("--exclude", action="append", default=[])
    args = ap.parse_args()

    if not os.path.isdir(args.root):
        print(f"not a directory: {args.root}", file=sys.stderr)
        return 2

    target = args.target or os.path.basename(os.path.abspath(args.root))
    census = exclusion.scan(args.root, tuple(args.exclude))
    graph = build_graph(census.root, census.first_party)
    graph["target"] = target
    graph["census"] = census.as_dict()

    if not graph["ast_grep_available"]:
        print("WARNING: ast-grep binary not found — zero edges is a broken "
              "extraction, not a real zero (README finding 19)", file=sys.stderr)
    elif graph["edge_count"] == 0 and graph["python_files_scanned"] > 0:
        print("WARNING: ast-grep ran and found python files but produced zero "
              "resolved edges — investigate before trusting this as a real "
              "zero (README finding 19)", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{target}-imports.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2)

    print(f"wrote {path}")
    print(f"  {graph['python_files_scanned']} python files, "
          f"{graph['import_statements_matched']} import statements matched")
    print(f"  {graph['edge_count']} distinct file->file edges "
          f"({graph['resolved_import_count']} resolved imports, "
          f"{graph['unresolved_import_count']} external/unresolved)")
    if graph["parse_failures"]:
        print(f"  {len(graph['parse_failures'])} snippets failed ast.parse — see parse_failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
