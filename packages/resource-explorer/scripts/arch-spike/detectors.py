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

from ir import Component, Evidence, Identity, Location

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
_DOCKER_CMD = re.compile(r"^\s*(CMD|ENTRYPOINT)\s+(?P<cmd>.+)$", re.I)


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
        if base.startswith("Dockerfile") or base.endswith(".containerfile"):
            units[os.path.dirname(rel) or "."].append(rel)
        elif _is_compose(root, rel):
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


def compose_services(root: str, rel: str) -> list[tuple[str, int]]:
    """Service names from a compose file, with line numbers.

    A deliberately shallow line-based read rather than a YAML parse: compose
    files in the wild carry anchors, merge keys and templating that a strict
    parser rejects, and this slice only needs the service names. A real parser
    is Phase 1's problem, and the shallowness is recorded as an IR note.
    """
    out: list[tuple[str, int]] = []
    in_services = False
    try:
        text = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return out
    for n, line in enumerate(text.splitlines(), 1):
        if re.match(r"^services:\s*$", line):
            in_services = True
            continue
        if in_services:
            if line and not line[0].isspace():
                in_services = False
                continue
            if m := _SERVICE_LINE.match(line):
                out.append((m.group("name"), n))
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
        includes = re.findall(r"^\s*include\s*\(?\s*['\"]:?([^'\"]+)['\"]", text, re.M)
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

    # Compose services are third-party components with no first-party code
    # (§8.2b's add-on tier) — real components, but not ones a manifest declares.
    for unit, decls in units.items():
        for decl in decls:
            if os.path.basename(decl).startswith("Dockerfile"):
                continue
            for svc, line in compose_services(root, decl):
                slug = _slug(os.path.basename(unit), svc)
                if any(c.slug == slug for c in components):
                    continue
                components.append(Component(
                    slug=slug, name=svc, type="Third Party Process",
                    identity=Identity("deployment-unit", svc, unit),
                    files=[], confidence=65, confidence_level="Derived",
                ))
                evidence.append(Evidence(
                    subject_kind="component", subject_slug=slug,
                    assertion="declared as a compose service",
                    detector="compose:services",
                    locations=[Location(decl, line, f"{svc}:")],
                    confidence=65, confidence_level="Derived",
                ))

    if gradle := gradle_modules(root, files):
        for g in gradle:
            notes.append(f"{g['rel']}: {len(g['modules'])} Gradle modules — "
                         f"not expanded into components in this slice")

    notes.append("compose parsed line-wise, not with a YAML parser — service names only")
    notes.append("no code-marker detectors yet: every Software Service in this target "
                 "is currently reported as Console Command or Software Library")
    return components, evidence, notes
