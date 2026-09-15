"""What this repository DECLARES itself to be, read from its manifests.

Curate's first claim -- "Software Library · pyegeria, on PyPI" -- was
inference until now: interface_surface infers a CLI from a dependency on
click, and the repo name stands in for the distribution name. The
manifests declare both. `[project.name]` is the distribution name (often
not the repo name), `[project.scripts]` is the CLI entry point as a fact,
`packages` gives component boundaries, and a publish workflow establishes
that the library is really distributed and under which name (Repo
Handoff, checks 2 and 3 -- folded into the step that already parses the
file, as the handoff said to).

One finding per declared distribution, kind="distribution":
  check_name  "python:pyegeria" / "javascript:@odpi/egeria-ui"
  label       "published" when a publish workflow names the ecosystem,
              else "declared"
  detail      {name, ecosystem, manifest, scripts, packages, publish_workflow}
Nothing is inferred: a repo with no [project] table declares nothing, and
that is the finding's absence, not a guess.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from resource_explorer.ingestion.vendored import is_vendored_abs

_PUBLISH_MARKERS = {
    "python": ("pypa/gh-action-pypi-publish", "twine upload", "poetry publish", "uv publish", "hatch publish"),
    "javascript": ("npm publish", "yarn publish", "pnpm publish"),
    "java": ("publishToMavenCentral", "publishToSonatype", "gradle publish", "mvn deploy", "maven-deploy"),
}


def _publish_workflows(root: Path) -> dict[str, str]:
    """ecosystem -> workflow file that publishes it, from .github/workflows."""
    out: dict[str, str] = {}
    wf = root / ".github" / "workflows"
    if not wf.is_dir():
        return out
    for f in sorted(wf.glob("*.y*ml")):
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for eco, markers in _PUBLISH_MARKERS.items():
            if eco not in out and any(m in text for m in markers):
                out[eco] = f.name
    return out


def _pyproject(path: Path) -> dict | None:
    try:
        import tomllib
        data = tomllib.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    project = data.get("project") or {}
    name = project.get("name") or (data.get("tool", {}).get("poetry", {}) or {}).get("name")
    if not name:
        return None
    # `scripts` stays a bare list of names — every existing reader (deployment_
    # evidence.py, curate.py, tests) treats it that way. `script_targets` is
    # new: the name -> "module:function" mapping the manifest actually
    # declares, needed by interface_surface's `declared` rung to say what the
    # entry point IS ("pyegeria.cli:main"), not just that one exists.
    project_scripts = project.get("scripts") or {}
    script_table = "[project.scripts]"
    if not project_scripts:
        project_scripts = (data.get("tool", {}).get("poetry", {}) or {}).get("scripts") or {}
        script_table = "[tool.poetry.scripts]"
    scripts = sorted(project_scripts.keys())
    script_targets = {k: str(v) for k, v in project_scripts.items()}
    packages: list[str] = []
    tool = data.get("tool", {}) or {}
    st = tool.get("setuptools", {}) or {}
    if isinstance(st.get("packages"), list):
        packages = [p for p in st["packages"] if isinstance(p, str)]
    elif isinstance((tool.get("hatch", {}).get("build", {}).get("targets", {}).get("wheel", {}) or {}).get("packages"), list):
        packages = list(tool["hatch"]["build"]["targets"]["wheel"]["packages"])
    return {"name": str(name), "ecosystem": "python", "scripts": scripts, "packages": packages,
            "version": str(project.get("version") or ""),
            "script_targets": script_targets,
            "script_table": script_table if scripts else ""}


def _package_json(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
    except Exception:
        return None
    if not isinstance(data, dict) or not data.get("name") or data.get("private") is True:
        return None
    bin_ = data.get("bin")
    if isinstance(bin_, dict):
        scripts = sorted(bin_.keys())
        script_targets = {k: str(v) for k, v in bin_.items()}
    elif isinstance(bin_, str):
        scripts = [data["name"]]
        script_targets = {data["name"]: bin_}
    else:
        scripts, script_targets = [], {}
    return {"name": str(data["name"]), "ecosystem": "javascript", "scripts": scripts, "packages": [],
            "version": str(data.get("version") or ""),
            "script_targets": script_targets,
            "script_table": "package.json bin" if scripts else ""}


_GRADLE_GROUP = re.compile(r"^\s*group\s*=?\s*['\"]([^'\"]+)['\"]", re.M)
_GRADLE_ARCHIVES = re.compile(r"archivesBaseName\s*=?\s*['\"]([^'\"]+)['\"]")


def _gradle(path: Path) -> dict | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    group = _GRADLE_GROUP.search(text)
    if not group:
        return None
    base = _GRADLE_ARCHIVES.search(text)
    name = f"{group.group(1)}:{base.group(1) if base else path.parent.name}"
    return {"name": name, "ecosystem": "java", "scripts": [], "packages": [], "version": ""}


_READERS = {"pyproject.toml": _pyproject, "package.json": _package_json,
            "build.gradle": _gradle, "build.gradle.kts": _gradle}


class DistributionParser:
    def parse(self, root: Path) -> list[dict]:
        publish = _publish_workflows(root)
        findings: list[dict] = []
        seen: set[str] = set()
        # Shallowest first, so the root manifest wins the dedupe over a
        # nested copy of the same distribution.
        for p in sorted(root.rglob("*"), key=lambda q: (len(q.parts), str(q))):
            if not p.is_file() or p.name not in _READERS or is_vendored_abs(p, root):
                continue
            d = _READERS[p.name](p)
            if not d:
                continue
            key = f"{d['ecosystem']}:{d['name']}"
            if key in seen:
                continue
            seen.add(key)
            rel = str(p.relative_to(root))
            wf = publish.get(d["ecosystem"], "")
            bits = [f"{d['name']} — {d['ecosystem']} distribution declared in {rel}"]
            if d["scripts"]:
                bits.append(f"{len(d['scripts'])} command-line entry point(s): {', '.join(d['scripts'][:6])}")
            if d["packages"]:
                bits.append(f"{len(d['packages'])} package(s)")
            bits.append(f"publish workflow: {wf}" if wf else "no publish workflow found")
            findings.append({
                "check_name": key,
                "label": "published" if wf else "declared",
                "summary": "; ".join(bits) + ".",
                "confidence": 100,
                "detail": {**d, "manifest": rel, "publish_workflow": wf},
            })
        return findings
