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

**Scope was Python only through finding 36/37; now Python + Java.** The
Python-only scope was measured, not lazy: trellis is 472 first-party `.py`
files against 7 `.js`; egeria-workspaces-fs is 167 `.py` against 6 `.js` + 1
`.ts`. Real import syntax in JS/TS (`require`, dynamic `import()`, bundler
aliases) is a different extraction problem for a signal that would touch
under 2% of either target's first-party files — still not built, still a
finding rather than a silent scope-down.

Java is different: it is the *only* language the obvious adversarial target
(`odpi/egeria`, 231 Gradle modules) has. Zero tracked `.py` files there meant
coupling could not run on it at all, and "does this generalise beyond a
well-factored Python monorepo?" was unanswerable. So Java gets first-class
extraction and resolution, not a bolt-on: per-language extractor (ast-grep
rule) and resolver (below), sharing one graph assembly in `build_graph` —
the graph and everything downstream (dispersion, coupling shapes, scoring)
is language-agnostic, only extraction/resolution differ per plan and design
§5.5's own framing.

**Extraction is ast-grep** (plan §0(a): do not join `project_code_relationships`
× `project_code_symbols` — that recovers `inherits_from` pairs, not imports;
do not adopt grimp — it imports the code to resolve it, needing the dependency
environment installed). `rules-imports/import-python.yml` matches the three
Python import node kinds; `rules-imports/import-java.yml` matches Java's
single `import_declaration` node kind (plain/static/wildcard alike — verified
live, finding-19 discipline, before being trusted). Both rules live in their
own directory, not `rules/`, so `code_markers.py`'s scan of `rules/*.yml`
never sees them and never logs a spurious "no MARKER_ROLES entry" note.

**Resolution is ast-grep's *finding* + a language-specific re-parse of the
matched text** — Python's own `ast` module for Python (re-deriving
module/name/level from a hand-rolled regex over Python import syntax would
silently break on a form nobody tested, the finding-19 lesson); a small
regex for Java, because unlike Python's grammar Java import statements have
exactly one shape (`import [static] a.b.C[.*];`) with no multi-import,
aliasing, or continuation forms to get wrong. Either way ast-grep still does
the *extraction* (which lines are import statements); the re-parse only
structures what was already found.

Resolution itself is a best-effort static approximation per language, stated
so the numbers are read correctly:

**Python:**

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

**Java:** Java's import maps a fully-qualified name (`a.b.C`) straight onto a
*package* (from the imported file's own `package a.b;` declaration, not a
directory-name convention — Gradle/Maven layouts vary, and `roots_for_file`'s
directory-prefix trick does not apply because a package has no required
relationship to a source-root directory beyond "some directory holds
`src/main/java` or similar" which isn't guaranteed at all). So resolution is
a global index — **every first-party `.java` file's `package` declaration +
its own filename** (Java requires a public top-level type's name to match its
file — the same convention `javac` itself enforces) — is `fqcn -> file`, and
imports resolve by dotted-name lookup, trying progressively shorter prefixes
so a nested-class import (`a.b.Outer.Inner`) or a static-member import
(`import static a.b.C.method;`, where `method` is not a class) still lands on
`a.b.C`. A class-wildcard import (`import a.b.*;`) cannot name one target at
all — every first-party top-level type directly in package `a.b` is a
plausible edge, so it fans out to all of them, tagged `kind: wildcard` so
that fan-out reads as what it is rather than being conflated with a real
single-symbol import.

Gradle's 231-module layout raises the same duplicate-name risk finding 37
found and fixed for Python's two `PyegeriaWebHandler` copies: two modules
declaring the same class name under the same package (test fixtures are the
likely case) would collide in a flat `fqcn -> file` map. Mirroring
`roots_for_file`'s fix, a Java import resolves within the importing file's
own **Gradle/Maven module** first (nearest enclosing `build.gradle`,
`build.gradle.kts`, or `pom.xml`) before falling back to any first-party
match — same principle (an import resolves within its own copy first),
applied to the boundary Java actually has (the module, not a directory
tree).

**Both languages:** Anything that does not resolve to a first-party file
(stdlib, third-party, or a resolution miss) is recorded as **external**, not
silently dropped — plan Task 1 asks for this explicitly: "an external-heavy
subtree is a different kind of component."

No network, no import execution, no dependency environment, no `javac`/
classpath resolution.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from collections import Counter, defaultdict

from . import exclusion
from .code_markers import _binary  # reuse — do NOT reimplement the venv-vs-PATH lookup

RULES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "rules-imports")

# The only languages this module can actually extract an import graph from.
# This is the single source of truth for "extractable" — read by
# arch_recovery_coupling.py (and arch_recovery_detect.py) to decide whether a
# zero-component run means "genuinely nothing" or "this step cannot read this
# language yet" (README findings 57/58). When a new language extractor is
# added below (a new rules-imports/*.yml + resolver + a fp_<lang> line in
# build_graph), add its extension here too — that is what makes the
# no_supported_source check start passing on its own instead of silently
# staying stale the way the bug it fixes did.
SUPPORTED_EXTENSIONS: dict[str, str] = {".py": "python", ".java": "java"}

# A much broader, best-effort extension -> language map, used only to name
# what *is* present in a repo imports.py cannot read — e.g. surfacing
# "rust" in an unverified outcome's detail instead of a bare boolean. Not
# used for any extraction decision, so it can be as loose as it likes;
# SUPPORTED_EXTENSIONS above is the only list that gates behaviour.
_KNOWN_LANGUAGES_BY_EXTENSION: dict[str, str] = {
    ".py": "python", ".java": "java", ".rs": "rust", ".go": "go", ".cs": "csharp",
    ".rb": "ruby", ".kt": "kotlin", ".kts": "kotlin", ".js": "javascript",
    ".jsx": "javascript", ".ts": "typescript", ".tsx": "typescript", ".c": "c",
    ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp", ".swift": "swift",
    ".scala": "scala", ".php": "php", ".m": "objective-c", ".mm": "objective-c",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang", ".clj": "clojure",
    ".hs": "haskell", ".lua": "lua", ".dart": "dart", ".sh": "shell",
}


def extractable_first_party(first_party: list[str]) -> list[str]:
    """The subset of `first_party` this module can extract imports from —
    i.e. what `build_graph` will actually scan. Empty means an import graph
    from this repo is guaranteed empty regardless of what ast-grep finds,
    which is the condition callers use to decide `unverified` vs a trusted
    zero."""
    return [f for f in first_party if os.path.splitext(f)[1] in SUPPORTED_EXTENSIONS]


def languages_present(first_party: list[str]) -> dict[str, int]:
    """Best-effort census of what languages `first_party` actually contains,
    by extension — for outcome detail only (e.g. `{"rust": 214}`), so an
    `unverified` result says what could not be read rather than just that
    something could not be read."""
    counts: dict[str, int] = {}
    for f in first_party:
        lang = _KNOWN_LANGUAGES_BY_EXTENSION.get(os.path.splitext(f)[1])
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    return counts


# ── ast-grep extraction ─────────────────────────────────────────────────

def _scan_statements(root: str, first_party: set[str], rule_filename: str) -> list[dict]:
    """Every import-statement match for one language's rule, restricted to
    first-party files. Mirrors code_markers.scan()'s shape but against its
    own rules dir. Shared by Python and Java — only the rule file differs."""
    import subprocess
    binary = _binary()
    if binary is None:
        return []
    rule_path = os.path.join(RULES_DIR, rule_filename)
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
        if rel not in first_party:
            continue
        m["_rel"] = rel
        out.append(m)
    return out


def _scan_import_statements(root: str, first_party_py: set[str]) -> list[dict]:
    """Python import-statement matches. Thin wrapper kept for callers written
    before Java was added."""
    return _scan_statements(root, first_party_py, "import-python.yml")


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


def roots_for_file(importing_file: str, source_roots: list[str],
                   fp_set_hint: frozenset[str] | set[str] = frozenset()) -> list[str]:
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

    # A SCRIPT directory is its own resolution root; a PACKAGE directory is not.
    #
    # Python puts a script's own directory on sys.path[0], so `import sibling`
    # works between loose scripts. Inside a package it does not — py3 removed
    # implicit relative imports, so a bare name there resolves from sys.path,
    # not from the neighbouring file. The presence of __init__.py is exactly
    # that distinction, so it is what this tests.
    #
    # Without this, a flat script directory that is neither a manifest dir nor
    # a deployment unit is no root at all and NONE of its sibling imports
    # resolve. Measured on `scripts/arch-spike`: 0 intra-directory edges for
    # files that plainly import each other. Downstream that reads as "no import
    # signal", which is indistinguishable from a genuine cross-language seam —
    # and co-change's seam rescue duly fired on it, breaking a ground-truth
    # match that had nothing to do with language.
    #
    # Related to but distinct from the wrong-copy bug: there, two directories
    # were both roots and the wrong one won; here there is no root at all.
    own_dir = importing_file.rsplit("/", 1)[0] if "/" in importing_file else ""
    if own_dir and own_dir not in own and f"{own_dir}/__init__.py" not in fp_set_hint:
        own.append(own_dir)

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


# ── Java: parsing the matched snippet ───────────────────────────────────

# Java import syntax has exactly one shape — `import [static] a.b.C[.*];` —
# unlike Python's, so a small regex is not the finding-19 risk a hand-rolled
# Python-import regex would be (no multi-import, no aliasing, no
# continuation forms to silently mishandle). ast-grep still does the
# extraction; this only structures the one statement form it found.
_JAVA_IMPORT_RE = re.compile(
    r"^import\s+(?P<static>static\s+)?(?P<path>[\w.]+?)(?P<wildcard>\.\*)?\s*;\s*$"
)


def _parse_java_snippet(text: str) -> tuple[str, bool, bool] | None:
    """One matched `import_declaration`'s text -> (dotted_path, is_static,
    is_wildcard), or None if the text doesn't match the one Java import
    shape (defensive — ast-grep's own rule only matches import_declaration,
    so this should never actually miss)."""
    m = _JAVA_IMPORT_RE.match(text.strip())
    if not m:
        return None
    return m.group("path"), bool(m.group("static")), bool(m.group("wildcard"))


# ── Java: resolution ─────────────────────────────────────────────────────

_JAVA_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.M)


def _java_package(root: str, rel: str) -> str:
    """`package a.b;` from a first-party .java file — always near the top,
    so only the first 4KB need reading."""
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            head = fh.read(4096)
    except OSError:
        return ""
    m = _JAVA_PACKAGE_RE.search(head)
    return m.group(1) if m else ""


def java_fqcn_index(root: str, fp_java: list[str]) -> dict[str, list[str]]:
    """fully-qualified-class-name -> [files]. Built from each file's own
    `package` declaration plus its filename (Java requires a public
    top-level type's name to match its file, the same rule `javac` itself
    enforces) — no source-root/classpath modelling needed, unlike Python
    where module path and file path are the same thing only by directory
    convention. A list, not one file, because Gradle's 231-module layout can
    genuinely declare the same fqcn twice (finding-37 risk, mirrored here —
    see roots_for_file's docstring for the Python precedent)."""
    idx: dict[str, list[str]] = defaultdict(list)
    for rel in fp_java:
        pkg = _java_package(root, rel)
        type_name = os.path.splitext(os.path.basename(rel))[0]
        fqcn = f"{pkg}.{type_name}" if pkg else type_name
        idx[fqcn].append(rel)
    return idx


def java_module_roots(first_party: list[str]) -> set[str]:
    """Nearest-enclosing-module boundary for Java, the equivalent of
    Python's `source_roots()` — every directory holding a `build.gradle`,
    `build.gradle.kts`, or `pom.xml`, plus the checkout root as a
    last-resort bucket."""
    roots = {"."}
    for rel in first_party:
        if os.path.basename(rel) in ("build.gradle", "build.gradle.kts", "pom.xml"):
            roots.add(os.path.dirname(rel) or ".")
    return roots


def module_root_for_file(rel: str, module_roots: set[str]) -> str:
    """Longest (most specific) module root enclosing `rel` — the Java
    analogue of `roots_for_file`'s "own enclosing root first" ordering."""
    candidates = [r for r in module_roots
                  if r == "." or rel == r or rel.startswith(r + "/")]
    return max(candidates, key=len) if candidates else "."


def _pick_java_hit(hits: list[str], importing_file: str, module_roots: set[str]) -> str:
    """When an fqcn resolves to more than one first-party file (the
    finding-37 risk), prefer a file in the importing file's own module
    before falling back to any match — deterministic either way."""
    if len(hits) == 1:
        return hits[0]
    own_root = module_root_for_file(importing_file, module_roots)
    same_module = [h for h in hits if module_root_for_file(h, module_roots) == own_root]
    return sorted(same_module)[0] if same_module else sorted(hits)[0]


def resolve_java_class(dotted: str, importing_file: str, fqcn_index: dict[str, list[str]],
                        module_roots: set[str]) -> str | None:
    """Resolve a dotted Java name to a first-party file, trying progressively
    shorter prefixes. This one loop handles three cases that all look the
    same syntactically:

    - a plain class import (`a.b.C` matches directly)
    - a nested/inner-class import (`a.b.Outer.Inner` — `Inner` isn't a
      top-level fqcn, so it drops to `a.b.Outer`)
    - a static-member import with the member name still attached
      (`a.b.C.method` — `method` isn't a class, drops to `a.b.C`)

    Best-effort, same spirit as Python's package/symbol disjunction: no
    classpath is resolved, so an inner class or a static member that
    genuinely collides with a same-named top-level class one segment up
    could in principle land on the wrong one. Not observed in practice."""
    parts = dotted.split(".")
    for n in range(len(parts), 0, -1):
        hits = fqcn_index.get(".".join(parts[:n]))
        if hits:
            return _pick_java_hit(hits, importing_file, module_roots)
    return None


def resolve_java_wildcard(package: str, fqcn_index: dict[str, list[str]]) -> list[str]:
    """`import a.b.*;` names no single symbol — every first-party top-level
    type directly in package `a.b` (not in a sub-package) is a plausible
    edge. Fans out deliberately; the caller tags these `kind: wildcard` so
    the fan-out is visible rather than conflated with a real one-symbol
    import."""
    prefix = f"{package}."
    out: list[str] = []
    for fqcn, files in fqcn_index.items():
        if fqcn.startswith(prefix) and "." not in fqcn[len(prefix):]:
            out.extend(files)
    return out


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


# ── Go ──────────────────────────────────────────────────────────────────
#
# Go resolution is the *simplest* of the three, and for a reason worth stating:
# an import path is absolute and module-qualified (`github.com/o/r/scrape`), so
# there is no per-file search path to walk (Python) and no global type index to
# build (Java). The `go.mod` module path plus the import string names the target
# directory outright.
#
# The one real difference is granularity: **Go imports a package (a directory),
# not a file.** So one import fans out to every `.go` file in that directory,
# exactly as a Java wildcard import does — `resolve_go_package` returns a list
# for the same reason `resolve_java_wildcard` does.

GO_MOD_MODULE = re.compile(r"^\s*module\s+(\S+)", re.M)


def _parse_go_snippet(text: str) -> tuple[str, str] | None:
    """`(import_path, kind)` from one `import_spec` node.

    Handles every spec form: plain (`"fmt"`), aliased (`stdlog "log"`), blank
    side-effect (`_ "net/http/pprof"`) and dot (`. "pkg"`). All four are real
    dependencies and all four are kept — a blank import is a side-effect
    dependency, which is architecturally *more* interesting than a plain one,
    not less.
    """
    m = re.search(r'"([^"]+)"', text)
    if not m:
        return None
    head = text[:m.start()].strip()
    kind = {"_": "blank", ".": "dot"}.get(head, "alias" if head else "plain")
    return m.group(1), kind


def go_module_index(root: str, first_party: list[str]) -> list[tuple[str, str]]:
    """`[(module_path, dir)]` from every first-party `go.mod`, longest module
    path first so a nested module wins over the repo-root one.

    A repo may declare several modules — Prometheus declares six — and only the
    root one usually spans the architecture (finding 69). Resolution needs them
    all, because an import into a nested module must land in that module's
    directory, not at the path the root module's prefix would imply.
    """
    out: list[tuple[str, str]] = []
    for rel in first_party:
        if os.path.basename(rel) != "go.mod":
            continue
        try:
            with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        m = GO_MOD_MODULE.search(text)
        if m:
            out.append((m.group(1).rstrip("/"), os.path.dirname(rel)))
    return sorted(out, key=lambda t: len(t[0]), reverse=True)


def go_files_by_dir(fp_go: list[str]) -> dict[str, list[str]]:
    """`dir -> [.go files directly in it]`. Non-recursive on purpose: a Go
    package is exactly one directory, and subdirectories are separate packages
    that must be imported by their own paths."""
    idx: dict[str, list[str]] = {}
    for rel in fp_go:
        idx.setdefault(os.path.dirname(rel), []).append(rel)
    return idx


def resolve_go_package(path: str, module_index: list[tuple[str, str]],
                       by_dir: dict[str, list[str]]) -> list[str]:
    """Every first-party `.go` file in the imported package, or `[]` for
    stdlib and third-party imports (which have no module prefix match and are
    counted as external, per the Python/Java convention)."""
    for mod_path, mod_dir in module_index:
        if path == mod_path:
            rest = ""
        elif path.startswith(mod_path + "/"):
            rest = path[len(mod_path) + 1:]
        else:
            continue
        d = os.path.normpath(os.path.join(mod_dir, rest)) if rest else mod_dir
        if d == ".":
            d = ""
        hits = by_dir.get(d)
        if hits:
            return hits
    return []


def _build_go_edges(root: str, fp_set: set[str], first_party: list[str]) -> tuple[
        list[dict], Counter, list[dict], int, int, int]:
    """Go counterpart to `_build_python_edges` / `_build_java_edges` — same
    return shape, so `build_graph` still needs no language branch.

    **Edge weighting.** Elsewhere weight means "how many symbols cross this
    edge" (three `from x import a/b/c` lines are one architectural edge of
    weight 3). A Go import names a whole package, so its faithful analogue is
    weight **1 per import statement, divided across the package's files** — each
    fanned-out edge carries `w = 1/len(targets)`. Without this, importing a
    40-file package would outweigh importing a 2-file package twentyfold purely
    because of file counts, and since *every* Go import is package-level the
    distortion would be universal rather than occasional, silently skewing every
    cohesion number computed downstream.

    Note `resolved_count` here counts **imports**, matching the
    `resolved_import_count` field name. `_build_java_edges` counts *edges* for
    the same field, so a Java wildcard over-counts; that is pre-existing and
    left alone rather than quietly changed under a Go commit.
    """
    matches = _scan_statements(root, fp_set, "import-go.yml")
    module_index = go_module_index(root, first_party)
    by_dir = go_files_by_dir(sorted(fp_set))

    edges: list[dict] = []
    external_by_file: Counter = Counter()
    parse_failures: list[dict] = []
    resolved_count = 0
    unresolved_count = 0

    for m in matches:
        src = m["_rel"]
        line = m.get("range", {}).get("start", {}).get("line", 0) + 1
        parsed = _parse_go_snippet(m.get("text") or "")
        if parsed is None:
            parse_failures.append({"file": src, "line": line, "text": (m.get("text") or "")[:120]})
            continue
        path, kind = parsed
        targets = [t for t in resolve_go_package(path, module_index, by_dir) if t != src]
        if not targets:
            external_by_file[src] += 1
            unresolved_count += 1
            continue
        resolved_count += 1
        share = 1.0 / len(targets)
        for target in targets:
            edges.append({"source": src, "target": target, "kind": kind,
                          "line": line, "raw": path, "language": "go", "w": share})

    return edges, external_by_file, parse_failures, resolved_count, unresolved_count, len(matches)


def _build_python_edges(root: str, fp_set: set[str], roots: list[str]) -> tuple[
        list[dict], Counter, list[dict], int, int, int]:
    """Returns (edges, external_by_file, parse_failures, resolved_count,
    unresolved_count, statements_matched)."""
    matches = _scan_statements(root, fp_set, "import-python.yml")

    edges: list[dict] = []
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
                    file_roots = roots_for_file(src, roots, fp_set)
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
                              "line": line, "raw": display, "language": "python"})
                resolved_count += 1
            elif target is None:
                external_by_file[src] += 1
                unresolved_count += 1

    return edges, external_by_file, parse_failures, resolved_count, unresolved_count, len(matches)


def _build_java_edges(root: str, fp_set: set[str], first_party: list[str]) -> tuple[
        list[dict], Counter, list[dict], int, int, int]:
    """Java counterpart to `_build_python_edges` — same return shape, so
    `build_graph` can merge both without a language-specific branch below
    this point (design §5.5: only extraction/resolution differ)."""
    matches = _scan_statements(root, fp_set, "import-java.yml")
    fqcn_index = java_fqcn_index(root, sorted(fp_set))
    module_roots = java_module_roots(first_party)

    edges: list[dict] = []
    external_by_file: Counter = Counter()
    parse_failures: list[dict] = []
    resolved_count = 0
    unresolved_count = 0

    for m in matches:
        src = m["_rel"]
        line = m.get("range", {}).get("start", {}).get("line", 0) + 1
        parsed = _parse_java_snippet(m.get("text") or "")
        if parsed is None:
            parse_failures.append({"file": src, "line": line, "text": (m.get("text") or "")[:120]})
            continue
        path, is_static, is_wildcard = parsed

        if is_static and is_wildcard:
            kind, targets = "static-wildcard", [resolve_java_class(path, src, fqcn_index, module_roots)]
        elif is_static:
            kind, targets = "static", [resolve_java_class(path, src, fqcn_index, module_roots)]
        elif is_wildcard:
            kind, targets = "wildcard", resolve_java_wildcard(path, fqcn_index)
        else:
            kind, targets = "class", [resolve_java_class(path, src, fqcn_index, module_roots)]

        targets = [t for t in targets if t]
        display = f"{'static ' if is_static else ''}{path}{'.*' if is_wildcard else ''}"

        if targets:
            for target in targets:
                if target != src:
                    edges.append({"source": src, "target": target, "kind": kind,
                                  "line": line, "raw": display, "language": "java"})
                    resolved_count += 1
        else:
            external_by_file[src] += 1
            unresolved_count += 1

    return edges, external_by_file, parse_failures, resolved_count, unresolved_count, len(matches)


def build_graph(root: str, first_party: list[str]) -> dict:
    fp_py = sorted(f for f in first_party if f.endswith(".py"))
    fp_java = sorted(f for f in first_party if f.endswith(".java"))
    fp_go = sorted(f for f in first_party if f.endswith(".go"))
    fp_py_set, fp_java_set = set(fp_py), set(fp_java)
    roots = source_roots(root, first_party)
    ast_available = _binary() is not None

    (py_edges, py_ext, py_fail,
     py_resolved, py_unresolved, py_matched) = _build_python_edges(root, fp_py_set, roots)
    (java_edges, java_ext, java_fail,
     java_resolved, java_unresolved, java_matched) = _build_java_edges(root, fp_java_set, first_party)

    (go_edges, go_ext, go_fail,
     go_resolved, go_unresolved, go_matched) = _build_go_edges(root, set(fp_go), first_party)

    edges = py_edges + java_edges + go_edges
    external_by_file: Counter = py_ext + java_ext + go_ext
    parse_failures = py_fail + java_fail + go_fail
    resolved_count = py_resolved + java_resolved + go_resolved
    unresolved_count = py_unresolved + java_unresolved + go_unresolved
    matched_count = py_matched + java_matched + go_matched

    # de-duplicate identical (source, target) pairs but keep a weight —
    # a file importing another via 3 separate `from x import a/b/c` lines
    # (or, for Java, 3 separate `import`/`import static` lines naming the
    # same class) is one architectural edge, weighted by how many symbols
    # cross it. `language` rides along on the first occurrence — a
    # (source, target) pair only ever comes from one language, since source
    # and target are always same-language files.
    weighted: dict[tuple[str, str], dict] = {}
    for e in edges:
        key = (e["source"], e["target"])
        w = weighted.setdefault(key, {"source": e["source"], "target": e["target"],
                                      "kind": e["kind"], "language": e["language"],
                                      "weight": 0, "lines": []})
        w["weight"] += e.get("w", 1)
        if len(w["lines"]) < 5:
            w["lines"].append(e["line"])

    return {
        "root": root,
        "python_files_scanned": len(fp_py),
        "java_files_scanned": len(fp_java),
        "go_files_scanned": len(fp_go),
        "source_roots": roots,
        "ast_grep_available": ast_available,
        "import_statements_matched": matched_count,
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

    scanned = graph["python_files_scanned"] + graph["java_files_scanned"]
    if not graph["ast_grep_available"]:
        print("WARNING: ast-grep binary not found — zero edges is a broken "
              "extraction, not a real zero (README finding 19)", file=sys.stderr)
    elif graph["edge_count"] == 0 and scanned > 0:
        print("WARNING: ast-grep ran and found source files but produced zero "
              "resolved edges — investigate before trusting this as a real "
              "zero (README finding 19)", file=sys.stderr)

    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, f"{target}-imports.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(graph, fh, indent=2)

    print(f"wrote {path}")
    print(f"  {graph['python_files_scanned']} python files, {graph['java_files_scanned']} java files, "
          f"{graph['import_statements_matched']} import statements matched")
    print(f"  {graph['edge_count']} distinct file->file edges "
          f"({graph['resolved_import_count']} resolved imports, "
          f"{graph['unresolved_import_count']} external/unresolved)")
    if graph["parse_failures"]:
        print(f"  {len(graph['parse_failures'])} snippets failed ast.parse — see parse_failures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
