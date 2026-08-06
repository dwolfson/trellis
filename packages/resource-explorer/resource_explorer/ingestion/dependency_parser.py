"""Parse dependency manifest files to build a project dependency graph."""
from __future__ import annotations

import json
import logging
import re
import xml.etree.ElementTree as ET
from pathlib import Path

logger = logging.getLogger(__name__)


class DependencyParser:
    """
    Parses manifest files for multiple ecosystems and returns a list of dependency dicts.

    Supported:
      Python  — pyproject.toml, requirements.txt, setup.py
      Node.js — package.json
      Go      — go.mod
      Java    — pom.xml
    """

    def parse(self, local_root: Path, project_slug: str) -> list[dict]:
        deps: list[dict] = []
        root = Path(local_root)

        for manifest in root.rglob("pyproject.toml"):
            if "_test" not in str(manifest) and "vendor" not in str(manifest):
                deps.extend(self._parse_pyproject(manifest))

        for manifest in root.rglob("requirements*.txt"):
            if "vendor" not in str(manifest):
                deps.extend(self._parse_requirements(manifest))

        for manifest in root.rglob("setup.py"):
            if "vendor" not in str(manifest):
                deps.extend(self._parse_setup_py(manifest))

        for manifest in root.rglob("package.json"):
            parts = manifest.relative_to(root).parts
            if "node_modules" not in parts and "vendor" not in parts:
                deps.extend(self._parse_package_json(manifest))

        for manifest in root.rglob("go.mod"):
            if "vendor" not in str(manifest):
                deps.extend(self._parse_go_mod(manifest))

        for manifest in root.rglob("pom.xml"):
            if "vendor" not in str(manifest):
                deps.extend(self._parse_pom_xml(manifest))

        # Deduplicate by (dep_name, ecosystem, source_file)
        seen: set[tuple] = set()
        unique: list[dict] = []
        for d in deps:
            key = (d["dep_name"].lower(), d["ecosystem"], d["source_file"])
            if key not in seen:
                seen.add(key)
                unique.append(d)

        return unique

    # ── parsers ───────────────────────────────────────────────────────────────

    def _parse_pyproject(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        try:
            try:
                import tomllib
            except ImportError:
                try:
                    import tomli as tomllib  # type: ignore[no-redef]
                except ImportError:
                    return []

            with open(path, "rb") as f:
                data = tomllib.load(f)

            src = str(path.name)

            # PEP 517/518 [project.dependencies]
            for dep_str in data.get("project", {}).get("dependencies", []):
                name, ver = self._split_pep508(dep_str)
                deps.append(self._dep("python", name, ver, "runtime", src))

            # [project.optional-dependencies]
            for group, dep_list in data.get("project", {}).get("optional-dependencies", {}).items():
                for dep_str in dep_list:
                    name, ver = self._split_pep508(dep_str)
                    deps.append(self._dep("python", name, ver, "optional", src))

            # Poetry [tool.poetry.dependencies]
            for name, spec in data.get("tool", {}).get("poetry", {}).get("dependencies", {}).items():
                if name.lower() == "python":
                    continue
                ver = spec if isinstance(spec, str) else (spec.get("version", "") if isinstance(spec, dict) else "")
                deps.append(self._dep("python", name, ver, "runtime", src))

            for name, spec in data.get("tool", {}).get("poetry", {}).get("dev-dependencies", {}).items():
                ver = spec if isinstance(spec, str) else ""
                deps.append(self._dep("python", name, ver, "dev", src))

        except Exception as exc:
            logger.debug("pyproject.toml parse error at %s: %s", path, exc)
        return deps

    def _parse_requirements(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        dep_type = "dev" if "dev" in path.name or "test" in path.name else "runtime"
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if not line or line.startswith(("#", "-r", "-c", "--")):
                    continue
                name, ver = self._split_pep508(line)
                if name:
                    deps.append(self._dep("python", name, ver, dep_type, path.name))
        except Exception as exc:
            logger.debug("requirements parse error at %s: %s", path, exc)
        return deps

    def _parse_setup_py(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Regex for install_requires=[...] — handles multi-line with quotes
            m = re.search(r'install_requires\s*=\s*\[(.*?)\]', text, re.DOTALL)
            if m:
                for item in re.findall(r'["\']([^"\']+)["\']', m.group(1)):
                    name, ver = self._split_pep508(item)
                    if name:
                        deps.append(self._dep("python", name, ver, "runtime", "setup.py"))
        except Exception as exc:
            logger.debug("setup.py parse error at %s: %s", path, exc)
        return deps

    def _parse_package_json(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="ignore"))
            src = str(path.relative_to(path.parent.parent) if path.parent.parent.exists() else path.name)
            for name, ver in data.get("dependencies", {}).items():
                deps.append(self._dep("javascript", name, str(ver), "runtime", src))
            for name, ver in data.get("devDependencies", {}).items():
                deps.append(self._dep("javascript", name, str(ver), "dev", src))
            for name, ver in data.get("peerDependencies", {}).items():
                deps.append(self._dep("javascript", name, str(ver), "optional", src))
        except Exception as exc:
            logger.debug("package.json parse error at %s: %s", path, exc)
        return deps

    def _parse_go_mod(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        try:
            in_require = False
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                line = line.strip()
                if line.startswith("require ("):
                    in_require = True
                    continue
                if in_require and line == ")":
                    in_require = False
                    continue
                if in_require or line.startswith("require "):
                    dep_line = line.removeprefix("require ").strip()
                    # Strip inline comments
                    dep_line = dep_line.split("//")[0].strip()
                    if not dep_line:
                        continue
                    parts = dep_line.split()
                    if len(parts) >= 1:
                        name = parts[0]
                        ver = parts[1] if len(parts) >= 2 else ""
                        dep_type = "indirect" if "// indirect" in line else "runtime"
                        deps.append(self._dep("go", name, ver, dep_type, "go.mod"))
        except Exception as exc:
            logger.debug("go.mod parse error at %s: %s", path, exc)
        return deps

    def _parse_pom_xml(self, path: Path) -> list[dict]:
        deps: list[dict] = []
        try:
            tree = ET.parse(path)
            root = tree.getroot()
            ns = ""
            if root.tag.startswith("{"):
                ns = root.tag.split("}")[0] + "}"

            for dep in root.iter(f"{ns}dependency"):
                group = (dep.findtext(f"{ns}groupId") or "").strip()
                artifact = (dep.findtext(f"{ns}artifactId") or "").strip()
                ver = (dep.findtext(f"{ns}version") or "").strip()
                scope = (dep.findtext(f"{ns}scope") or "runtime").strip()
                name = f"{group}:{artifact}" if group else artifact
                if name:
                    dep_type = "test" if scope == "test" else ("dev" if scope in ("provided", "optional") else "runtime")
                    deps.append(self._dep("java", name, ver, dep_type, "pom.xml"))
        except Exception as exc:
            logger.debug("pom.xml parse error at %s: %s", path, exc)
        return deps

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _dep(ecosystem: str, name: str, version: str, dep_type: str, source_file: str) -> dict:
        return {
            "dep_name": name.strip(),
            "dep_version": version.strip(),
            "dep_type": dep_type,
            "ecosystem": ecosystem,
            "source_file": source_file,
        }

    @staticmethod
    def _split_pep508(spec: str) -> tuple[str, str]:
        """Split a PEP 508 dependency string into (name, version_specifier)."""
        spec = spec.strip().split(";")[0].strip()  # strip environment markers
        m = re.match(r'^([A-Za-z0-9_.\-\[\]]+)\s*([>=<!~^,\s].*)?$', spec)
        if m:
            return m.group(1).split("[")[0], (m.group(2) or "").strip()
        return spec, ""
