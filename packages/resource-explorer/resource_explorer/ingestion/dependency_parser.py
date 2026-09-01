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
      Java    — pom.xml, build.gradle, build.gradle.kts
    """

    def parse(self, local_root: Path, resource_slug: str) -> list[dict]:
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

        for pattern in ("build.gradle", "build.gradle.kts"):
            for manifest in root.rglob(pattern):
                if "vendor" not in str(manifest):
                    deps.extend(self._parse_gradle(manifest))

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

    #: Gradle configurations, mapped to this module's dep_type vocabulary.
    #: `compileOnly` is dev rather than runtime deliberately: it is on the compile
    #: classpath and absent at runtime, so treating it as a runtime dependency
    #: would overstate what actually ships.
    _GRADLE_CONFIGS = {
        "implementation": "runtime", "api": "runtime", "runtimeOnly": "runtime",
        "compile": "runtime", "runtime": "runtime",
        "compileOnly": "dev", "annotationProcessor": "dev", "developmentOnly": "dev",
        "testImplementation": "test", "testCompileOnly": "test",
        "testRuntimeOnly": "test", "testCompile": "test",
    }

    #: `implementation 'g:a:v'` / `implementation("g:a")` — Groovy and Kotlin DSL.
    _GRADLE_STRING_RE = re.compile(
        r"^\s*(?P<config>[A-Za-z]+)\s*\(?\s*['\"](?P<coord>[^'\"]+)['\"]\s*\)?\s*$"
    )
    #: `implementation group: 'g', name: 'a', version: 'v'` — the map form.
    _GRADLE_MAP_RE = re.compile(
        r"^\s*(?P<config>[A-Za-z]+)\s+group\s*:\s*['\"](?P<group>[^'\"]+)['\"]"
        r"\s*,\s*name\s*:\s*['\"](?P<name>[^'\"]+)['\"]"
        r"(?:\s*,\s*version\s*:\s*['\"](?P<version>[^'\"]+)['\"])?"
    )
    #: `implementation project(':x')` — an internal module, NOT an external package.
    _GRADLE_PROJECT_RE = re.compile(r"^\s*[A-Za-z]+\s*\(?\s*project\s*\(")

    def _parse_gradle(self, path: Path) -> list[dict]:
        """Coordinates declared literally in a Gradle build file.

        **Deliberately partial, and it says what it skipped.** `build.gradle` is
        Groovy (or Kotlin) *code*, not a data format: a coordinate can come from a
        version catalog (`libs.spring.core`), an `ext` property, a variable, or a
        plugin, and resolving those means running Gradle. This reads the literal
        forms only.

        Two exclusions matter more than the parsing:

        * `project(':some:module')` is an internal module, not a package. Recording
          those would invent dependencies that exist in no registry, and every one
          would come back unmatched from a CVE lookup — noise indistinguishable
          from a clean result.
        * A coordinate with no version is recorded **with an empty version**, not
          dropped. Egeria is the worked example: all 714 of its literal coordinates
          are `group:artifact`, because versions come from a BOM. `cve_scan`
          already classifies those as unqueryable with "no pinned version to
          query" rather than as clean, so recording them turns "we never looked"
          into "we looked and cannot answer without the BOM" — a different and
          more useful state.

        What could not be resolved is logged per file rather than silently
        dropped, because a dependency list quietly missing its version-catalog
        entries looks complete and is worse than none.
        """
        deps: list[dict] = []
        unresolved = internal = 0
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception as exc:
            logger.debug("gradle read error at %s: %s", path, exc)
            return deps

        source = path.name
        for raw in text.splitlines():
            line = raw.split("//", 1)[0].rstrip()
            if not line.strip():
                continue
            head = line.strip().split(None, 1)[0].split("(", 1)[0]
            if head not in self._GRADLE_CONFIGS:
                continue
            dep_type = self._GRADLE_CONFIGS[head]

            if self._GRADLE_PROJECT_RE.match(line):
                internal += 1
                continue

            m = self._GRADLE_MAP_RE.match(line)
            if m:
                deps.append(self._dep(
                    "java", f"{m.group('group')}:{m.group('name')}",
                    m.group("version") or "", dep_type, source))
                continue

            m = self._GRADLE_STRING_RE.match(line)
            if m:
                coord = m.group("coord")
                parts = coord.split(":")
                if len(parts) == 3:
                    # `${jacksonVersion}` is an unresolved Groovy variable, not a
                    # version. Recording it as one would put a string no registry
                    # can match into dep_version; cve_scan would then reject it as
                    # "a range or unparseable", which is a true statement about the
                    # wrong thing. Empty means "declared here, resolved elsewhere",
                    # which is what actually happened.
                    ver = parts[2]
                    if "$" in ver:
                        ver = ""
                        unresolved += 1
                    deps.append(self._dep("java", f"{parts[0]}:{parts[1]}", ver, dep_type, source))
                elif len(parts) == 2:
                    # No version: resolved by a BOM or platform, not absent.
                    deps.append(self._dep("java", coord, "", dep_type, source))
                else:
                    unresolved += 1
                continue

            # A configuration line naming something this cannot read — a version
            # catalog accessor, a variable, a function call.
            unresolved += 1

        if unresolved or internal:
            logger.info(
                "gradle %s: %d dependency(ies) recorded, %d unresolved "
                "(version catalog/variable/plugin), %d internal project() refs skipped",
                path, len(deps), unresolved, internal,
            )
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
