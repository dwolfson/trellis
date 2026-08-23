"""Deterministic detectors — design doc §5.1, first slice.

Scope of this slice: package manifests, entry points, and deployment units.
These are the rows of §5.1's table that need no code parsing, and they cover
identity precedence rungs 1 and 2 (§8.2). Code-marker rows — web framework
registrations, client libraries, schedulers — are ast-grep's job and land next;
until then components carry the type these signals alone can justify, with a
confidence that says so.

The standing rule from §5.2 applies even here: a detector never invents a
component. Every component below is anchored to a file that declares it.
"""
from __future__ import annotations

import json
import os
import re
import tomllib
from collections import defaultdict

import yaml

from .ir import Component, Evidence, Identity, Location

# Conventional roots stripped before slugging a module path (§8.2 rung 3).
PATH_ROOTS = ("src", "packages", "lib", "libs", "modules")


def _line_of(text: str, needle: str) -> tuple[int, str]:
    """Locate `needle` in `text` for evidence purposes. tomllib and json give
    no line numbers, so recover one by search — approximate but honest, and
    §5.4 needs a location to point a curator at."""
    for n, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return n, line.strip()
    return 0, ""


def _slug(*parts: str) -> str:
    joined = "::".join(p for p in parts if p)
    return re.sub(r"[^A-Za-z0-9:._-]+", "-", joined).strip("-")


def _normalise_path(rel_dir: str) -> str:
    segs = [s for s in rel_dir.split(os.sep) if s and s not in PATH_ROOTS]
    return "/".join(segs) or "."


# ── deployment units — identity precedence 1 (§8.2) ──────────────────────

_SERVICE_LINE = re.compile(r"^  (?P<name>[A-Za-z0-9][\w.-]*):\s*$")
_DOCKER_CMD = re.compile(r"^\s*(CMD|ENTRYPOINT)\s+(?P<cmd>.+)$", re.IGNORECASE)


def _is_compose(root: str, rel: str) -> bool:
    """Identify a compose file by CONTENT, not filename.

    Filename matching was the first version and it was wrong: this repo's
    compose files are named after the solution they deploy
    (`egeria-quickstart-local.yaml`, `egeria-freshstart.yaml`) and contain no
    "compose" substring at all, so a name-based rule silently missed every
    solution deployment while happily finding the add-ons. Worth recording as
    a finding in its own right — compose filename conventions are unreliable,
    and any detector depending on them under-reports exactly the components
    that matter most.
    """
    if not rel.lower().endswith((".yaml", ".yml")):
        return False
    try:
        with open(os.path.join(root, rel), encoding="utf-8", errors="replace") as fh:
            head = [next(fh, "") for _ in range(80)]
    except OSError:
        return False
    return any(re.match(r"^services:\s*$", line) for line in head)


def deployment_units(root: str, files: list[str]) -> dict[str, list[str]]:
    """Directories that constitute a deployed artifact, mapped to the evidence
    files that declare them.

    §8.2's floor matters here: a deployment unit is a separate deployed
    *artifact* — its own image or compose service — not a runtime configuration
    flag. Dockerfiles and compose files are artifacts; a `DEMO_MODE` flag is
    not, and nothing in this function will see one.
    """
    units: dict[str, list[str]] = defaultdict(list)
    for rel in files:
        base = os.path.basename(rel)
        if base.startswith("Dockerfile") or base.endswith(".containerfile") or _is_compose(root, rel):
            units[os.path.dirname(rel) or "."].append(rel)
    return dict(units)


def _enclosing_unit(unit: str, units: dict[str, list[str]]) -> str:
    """The nearest deployment unit strictly containing `unit`, if any.

    A component nested inside another deployment unit takes that unit as its
    qualifying context (§8.2) — PyegeriaWebHandler under egeria-quickstart is
    a different component from PyegeriaWebHandler under egeria-freshstart.
    """
    best = ""
    for other in units:
        if other != unit and other != "." and unit.startswith(other + os.sep):
            if len(other) > len(best):
                best = other
    return best


def dockerfile_entry(root: str, rel: str) -> tuple[str, int, str]:
    """The CMD/ENTRYPOINT a Dockerfile declares, as evidence for what the
    image actually runs. Last one wins, matching Docker's own semantics."""
    best = ("", 0, "")
    try:
        text = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return best
    for n, line in enumerate(text.splitlines(), 1):
        if m := _DOCKER_CMD.match(line):
            best = (m.group("cmd").strip(), n, line.strip())
    return best


def compose_services(root: str, rel: str) -> list[tuple[str, str, int]]:
    """(service key, component name, line) per service in a compose file.

    Uses a real YAML parser. The first version read the file line-wise, on the
    stated assumption that compose files in the wild carry anchors, merge keys
    and templating a strict parser would reject. **That assumption was wrong** —
    PyYAML parses all 25 compose files in egeria-workspaces without error — and
    the shallow reader accumulated three separate failure modes before this was
    checked: filename-based detection missed every solution deployment,
    first-wins missed layered overrides, and a column-0 comment inside the
    services block silently truncated the parse after 4 of 7 services. Worth
    recording as a finding: the cheap-parser instinct cost more than it saved,
    and each failure was silent rather than loud.

    `container_name` is preferred over the service key. The key is an internal
    handle (`apache-web`); container_name is what the human sees in `docker ps`
    and what they call it — validated against the hand-written ground truth,
    where every named component is a declared container_name.

    Line numbers come from a targeted re-scan, since PyYAML discards them and
    §5.4 needs a location to point a curator at.
    """
    path = os.path.join(root, rel)
    try:
        text = open(path, encoding="utf-8", errors="replace").read()
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []
    services = data.get("services")
    if not isinstance(services, dict):
        return []

    lines = text.splitlines()

    def line_of(key: str, value: str) -> int:
        pat = re.compile(rf"^\s*(?:container_name:\s*)?{re.escape(value)}\s*:?\s*$")
        for n, line in enumerate(lines, 1):
            if pat.match(line):
                return n
        for n, line in enumerate(lines, 1):
            if re.match(rf"^\s{{1,4}}{re.escape(key)}\s*:\s*$", line):
                return n
        return 0

    out: list[tuple[str, str, int]] = []
    for key, body in services.items():
        if not isinstance(key, str):
            continue
        name = key
        if isinstance(body, dict):
            cn = body.get("container_name")
            if isinstance(cn, str) and cn.strip():
                name = cn.strip()
        out.append((key, name, line_of(key, name)))
    return out


# ── package manifests — identity precedence 2 (§8.2) ─────────────────────

def python_manifests(root: str, files: list[str]) -> list[dict]:
    found = []
    for rel in (f for f in files if os.path.basename(f) == "pyproject.toml"):
        path = os.path.join(root, rel)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
            data = tomllib.loads(text)
        except (OSError, tomllib.TOMLDecodeError):
            continue
        project = data.get("project") or {}
        name = project.get("name")
        if not name:
            continue
        scripts = list((project.get("scripts") or {}).keys())
        gui = list((project.get("gui-scripts") or {}).keys())
        members = ((data.get("tool") or {}).get("uv") or {}).get("workspace", {}).get("members", [])
        has_build = "build-system" in data
        found.append({
            "rel": rel, "dir": os.path.dirname(rel) or ".", "name": name,
            "scripts": scripts + gui, "workspace_members": members,
            "installable": has_build, "text": text, "ecosystem": "python",
        })
    return found


def node_manifests(root: str, files: list[str]) -> list[dict]:
    found = []
    for rel in (f for f in files if os.path.basename(f) == "package.json"):
        path = os.path.join(root, rel)
        try:
            text = open(path, encoding="utf-8", errors="replace").read()
            data = json.loads(text)
        except (OSError, json.JSONDecodeError):
            continue
        name = data.get("name")
        if not name or not isinstance(name, str):
            continue
        binv = data.get("bin")
        bins = list(binv) if isinstance(binv, dict) else ([name] if binv else [])
        found.append({
            "rel": rel, "dir": os.path.dirname(rel) or ".", "name": name,
            "scripts": bins, "workspace_members": data.get("workspaces") or [],
            "installable": True, "text": text, "ecosystem": "node",
        })
    return found


def gradle_modules(root: str, files: list[str]) -> list[dict]:
    """Gradle multi-module layout. Reports the module list rather than one
    component per module — at egeria's 254 modules the partition question is
    about shape, not leaves (plan §3, T3)."""
    found = []
    for rel in (f for f in files if os.path.basename(f) in ("settings.gradle", "settings.gradle.kts")):
        try:
            text = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read()
        except OSError:
            continue
        includes = re.findall(r"^\s*include\s*\(?\s*['\"]:?([^'\"]+)['\"]", text, re.MULTILINE)
        if includes:
            found.append({"rel": rel, "dir": os.path.dirname(rel) or ".",
                          "modules": includes, "text": text, "ecosystem": "gradle"})
    return found


# ── assembly ─────────────────────────────────────────────────────────────

def classify(manifest: dict) -> tuple[str | None, int, str]:
    """Type, confidence, and why — from manifest signals alone.

    Honest ceiling: manifests distinguish "has an entry point" from "does not",
    which separates Console Command from Software Library and nothing else. A
    package whose entry point launches a web server is a Software Service, and
    no manifest says so — that needs the code-marker detectors. Confidence is
    set to reflect that ceiling rather than overstating what was established.
    """
    if manifest.get("scripts"):
        return "Console Command", 70, "declares console entry points"
    if manifest.get("workspace_members"):
        return None, 0, "workspace root — a container, not a component"
    if manifest.get("installable"):
        return "Software Library", 60, "installable package with no entry point"
    return None, 0, "manifest declares neither entry point nor build system"


def go_subsystems(root: str, files: list[str]) -> list[dict]:
    """Go **package trees** — the component unit a Go repo actually has.

    Added after finding 69, where Prometheus scored 0/11. Manifest identity is
    structurally blind on Go: `go.mod` declares a *module*, and in a
    single-module repo one module spans the entire architecture. Prometheus has
    six `go.mod` files and not one corresponds to a component.

    The unit that does correspond is the **top-level directory of a module**.
    That is not fitted to Prometheus — it is Go's own layout convention (`cmd/`
    for binaries, `internal/` for non-exported code, one directory per
    subsystem), and it is what the import graph respects: Go imports name a
    package by directory path, so directory boundaries *are* dependency
    boundaries.

    Two deliberate rules:

    * **Descend past directories that are not packages.** In Go a directory is
      a package only if it holds `.go` files *directly*; one that holds only
      subdirectories is a path segment, not a unit of code. So the component
      root is the first directory down from the module root that is itself a
      package.

      This is Go semantics, not a convention list, and it subsumes the
      hardcoded `cmd/` carve-out this function originally had. Prometheus's
      `cmd/` holds no `.go` files directly, so `cmd/prometheus` and
      `cmd/promtool` fall out as separate binaries for free. Milvus needs the
      general form: `internal/` (0 direct `.go` files) and
      `internal/distributed/` (0) are both pure containers, and a rule naming
      only `cmd` collapsed Milvus's entire architecture into a single
      `internal/**` component (finding 72).
    * **Files directly at a module root are skipped.** They belong to the
      module's own package, which is the whole module — the same
      "workspace root is a container, not a component" rule the npm detector
      already applies.

    Nested modules are honoured: a directory owned by a deeper `go.mod` is
    attributed to that module, not to the enclosing one.
    """
    from . import imports as _imports   # go_module_index lives with resolution
    module_index = _imports.go_module_index(root, files)     # longest path first
    if not module_index:
        return []
    go_files = [f for f in files if f.endswith(".go")]
    if not go_files:
        return []
    # Directories holding .go files DIRECTLY — i.e. the real Go packages.
    pkg_dirs = {os.path.dirname(f) for f in go_files}

    # dir -> owning module, longest module dir first so nested modules win
    by_dir = sorted(((mp, md) for mp, md in module_index), key=lambda t: len(t[1]), reverse=True)

    found: dict[str, dict] = {}
    for rel in go_files:
        for mod_path, mod_dir in by_dir:
            prefix = (mod_dir.rstrip("/") + "/") if mod_dir else ""
            if prefix and not rel.startswith(prefix):
                continue
            inner = rel[len(prefix):]
            parts = inner.split("/")
            if len(parts) < 2:          # directly at the module root
                break
            # Descend to the first directory that is itself a Go package.
            walked: list[str] = []
            d = None
            for part in parts[:-1]:
                walked.append(part)
                cand = f"{prefix}{'/'.join(walked)}"
                if cand in pkg_dirs:
                    d = cand
                    break
            if d is None:               # unreachable: the file's own dir is a package
                break
            sub = d[len(prefix):]
            entry = found.setdefault(d, {
                "dir": d, "module": mod_path, "subsystem": sub,
                "import_path": f"{mod_path.rstrip('/')}/{sub}",
                "files": [], "has_main": False,
            })
            entry["files"].append(rel)
            break
    for entry in found.values():
        entry["has_main"] = any(os.path.basename(f) == "main.go" for f in entry["files"])
    return sorted(found.values(), key=lambda e: e["dir"])


def build_components(root: str, files: list[str]) -> tuple[list[Component], list[Evidence], list[str]]:
    components: list[Component] = []
    evidence: list[Evidence] = []
    notes: list[str] = []

    units = deployment_units(root, files)
    manifests = python_manifests(root, files) + node_manifests(root, files)

    # Deployment context for a manifest = the nearest enclosing deployment unit.
    def context_for(d: str) -> str:
        best = ""
        for unit in units:
            if unit != "." and (d == unit or d.startswith(unit + os.sep)):
                if len(unit) > len(best):
                    best = unit
        return best

    for m in manifests:
        ctype, conf, why = classify(m)
        if ctype is None:
            notes.append(f"{m['rel']}: skipped — {why}")
            continue

        ctx = context_for(m["dir"])
        if ctx:
            ident = Identity("deployment-unit", os.path.basename(ctx), ctx)
            conf = min(95, conf + 15)   # §8.2 rung 1 is a stronger claim
        else:
            ident = Identity("package-name", m["name"])

        slug = _slug(os.path.basename(ctx) if ctx else "", m["name"])
        comp = Component(
            slug=slug,
            name=m["name"],
            type=ctype,
            identity=ident,
            files=[f"{m['dir']}/**" if m["dir"] != "." else "**"],
            confidence=conf,
            confidence_level="Derived",
        )
        components.append(comp)

        line, excerpt = _line_of(m["text"], m["name"])
        evidence.append(Evidence(
            subject_kind="component", subject_slug=slug,
            assertion=f"component identity = {ident.method}:{ident.value}",
            detector=f"manifest:{m['ecosystem']}",
            locations=[Location(m["rel"], line, excerpt)],
            confidence=conf, confidence_level="Derived",
        ))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=slug,
            assertion=f"solutionComponentType = {ctype}",
            detector=f"manifest:{m['ecosystem']}",
            locations=[Location(m["rel"], line, excerpt)],
            confidence=conf, confidence_level="Derived",
        ))

    # A deployment unit carrying a Dockerfile but NO manifest is still a
    # component — and it is identity precedence rung 1 (§8.2), the strongest
    # claim available. Missing these was the first version's worst failure:
    # PyegeriaWebHandler, the most substantial component in egeria-workspaces,
    # went entirely unreported because it ships no pyproject.toml. Anything
    # containerised is deployed, and deployment is what §8.2 now leads on.
    claimed_dirs = {m["dir"] for m in manifests}
    for unit, decls in units.items():
        dockerfiles = [d for d in decls if os.path.basename(d).startswith("Dockerfile")
                       or d.endswith(".containerfile")]
        if not dockerfiles or unit in claimed_dirs or unit == ".":
            continue
        # Only if the unit actually contains first-party code — a directory of
        # nothing but Dockerfiles is a build context, not a component.
        owned = [f for f in files if f.startswith(unit + os.sep)]
        if len(owned) <= len(decls):
            notes.append(f"{unit}: Dockerfile present but no first-party code — "
                         f"treated as a build context, not a component")
            continue

        name = os.path.basename(unit)
        # §8.2: where a deployment context exists it QUALIFIES the slug,
        # otherwise identically-named units collide. This is not cosmetic —
        # egeria-workspaces ships PyegeriaWebHandler twice, once per solution
        # deployment, and the unqualified slug silently dropped the second as
        # a duplicate. Two components is the pre-registered correct answer
        # (plan §3, T1 item 3); collapsing them is the failure the revised
        # precedence chain exists to prevent.
        parent = _enclosing_unit(unit, units)
        slug = _slug(os.path.basename(parent) if parent else "", name)
        if any(c.slug == slug for c in components):
            continue
        cmd, line, excerpt = dockerfile_entry(root, dockerfiles[0])
        components.append(Component(
            slug=slug, name=name, type="Long Running Daemon",
            identity=Identity("deployment-unit", name, parent or unit),
            files=[f"{unit}/**"], confidence=75, confidence_level="Derived",
        ))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=slug,
            assertion=f"component identity = deployment-unit:{name}",
            detector="dockerfile:presence",
            locations=[Location(dockerfiles[0], line, excerpt or "")],
            confidence=75, confidence_level="Derived",
        ))
        if cmd:
            evidence.append(Evidence(
                subject_kind="component", subject_slug=slug,
                assertion="solutionComponentType = Long Running Daemon",
                detector="dockerfile:entrypoint",
                locations=[Location(dockerfiles[0], line, excerpt)],
                confidence=70, confidence_level="Derived",
            ))

    # Compose services are components with no first-party code of their own
    # (§8.2b's add-on and shared-infra tiers) — real components, but not ones a
    # manifest declares.
    #
    # Merged ACROSS every compose file in a unit rather than first-wins. These
    # deployments are layered: a base file declares `apache-web:` with no
    # container_name and an override supplies `container_name:
    # quickstart-web-server`. First-wins registered the base and discarded the
    # override, losing the human-facing name for 3 of 16 components. Layered
    # compose is the norm, not an oddity, so any per-file pass under-reports.
    for unit, decls in units.items():
        merged: dict[str, tuple[str, str, int]] = {}   # service key -> (name, decl, line)
        for decl in decls:
            if os.path.basename(decl).startswith("Dockerfile"):
                continue
            for key, name, line in compose_services(root, decl):
                prior = merged.get(key)
                # A declared container_name always beats a bare service key,
                # whichever file it arrived in.
                if prior is None or (name != key and prior[0] == key):
                    merged[key] = (name, decl, line)

        for key, (name, decl, line) in merged.items():
            slug = _slug(os.path.basename(unit), name)
            if any(c.slug == slug for c in components):
                continue
            named = name != key
            components.append(Component(
                slug=slug, name=name, type="Third Party Process",
                identity=Identity("deployment-unit", name, unit),
                files=[], confidence=75 if named else 65, confidence_level="Derived",
                # deployment perspective (§4.1) — a running container, not a
                # source directory. See ir.py's Component.perspective docstring
                # for why this is tagged rather than reconciled with the
                # Dockerfile/manifest components below, which stay `physical`.
                perspective="deployment",
            ))
            evidence.append(Evidence(
                subject_kind="component", subject_slug=slug,
                assertion=("declared container_name on a compose service" if named
                           else "declared as a compose service"),
                detector="compose:container_name" if named else "compose:services",
                locations=[Location(decl, line, f"{name}")],
                confidence=75 if named else 65, confidence_level="Derived",
            ))

    # Go package trees (§8.2 rung 3 — module path). See go_subsystems().
    for g in go_subsystems(root, files):
        ident = Identity("module-path", g["import_path"])
        ctype = "Console Command" if g["has_main"] else "Software Library"
        components.append(Component(
            slug=_slug("go", g["subsystem"].replace("/", "-")),
            name=g["subsystem"],
            type=ctype,
            identity=ident,
            files=[f"{g['dir']}/**"],
            # Lower than a manifest claim on purpose: the directory boundary is
            # reliable, the *level* is a convention rather than a declaration,
            # and the type is inferred from `main.go` alone.
            confidence=55,
            confidence_level="Derived",
            proposed_by=["go-subsystem"],
            perspective="logical",
        ))
        gslug = _slug("go", g["subsystem"].replace("/", "-"))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=gslug,
            assertion=f"component identity = module-path:{g['import_path']}",
            detector="go-subsystem",
            locations=[Location(f"{g['dir']}", 0,
                                f"{len(g['files'])} .go files under module {g['module']}")],
            confidence=55, confidence_level="Derived",
        ))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=gslug,
            assertion=f"solutionComponentType = {ctype}",
            detector="go-subsystem",
            locations=[Location(f"{g['dir']}", 0,
                                "main.go present" if g["has_main"] else "no main.go — library package tree")],
            confidence=45, confidence_level="Derived",
        ))
    if not go_subsystems(root, files) and any(f.endswith(".go") for f in files):
        notes.append("go files present but no go.mod resolved — no Go components")

    if gradle := gradle_modules(root, files):
        for g in gradle:
            notes.append(f"{g['rel']}: {len(g['modules'])} Gradle modules — "
                         f"not expanded into components in this slice")


    # Code-marker pass (§5.1's code half) — logical-perspective components the
    # manifest and deployment detectors structurally cannot see. Package roots
    # come from the manifests already found, so markers refine a boundary that
    # was detected, never invent one from nothing.
    from .code_markers import propose as _propose_markers
    package_roots = sorted({m["dir"] for m in manifests}) or ["."]
    mc, me, mn = _propose_markers(root, files, package_roots)
    components.extend(mc)
    evidence.extend(me)
    notes.extend(mn)

    return components, evidence, notes
