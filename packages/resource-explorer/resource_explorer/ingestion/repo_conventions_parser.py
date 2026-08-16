"""Heuristic scan of repo file structure (and a couple of small text files)
for a handful of real-world "how well set up is this repo" conventions —
Discovery-tier signals from data already collected at ingestion/profile
time, not a new fetch category. Assessment expansion Part 2
(docs/discovery-automate-project-context-plan.md).

Grounded explicitly in prior art rather than invented from nothing (see the
plan doc's "Standards & prior art" section):
  - security_policy_content, automated_build, deployment_docker mirror
    checks OpenSSF Scorecard already runs (Security-Policy, CI-Tests/
    Maintained-adjacent, and general packaging/build signals).
  - catalog_info mirrors Backstage's (CNCF) `catalog-info.yaml` convention
    for a repo self-describing its place in an enterprise catalog.

Same "cheap structural/keyword signal, not full understanding" pattern as
CiWorkflowParser (B4) and DocumentationSurveyor's presence checks — a
heuristic keyword/filename match, not semantic parsing. A repo doing the
right thing in an unrecognized way will read as a false gap; accepted
tradeoff, same class as any keyword-based classifier in this codebase.
"""
from __future__ import annotations

import re
from pathlib import Path

# ── security_policy_content ─────────────────────────────────────────────
# Checked in priority order — first file found wins (matches
# DocumentationSurveyor's/B3's "first candidate present" convention).
_SECURITY_POLICY_CANDIDATES = (
    "SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md", "SECURITY.rst",
)
_SECURITY_POLICY_KEYWORDS = (
    "responsible disclosure", "report a vulnerability", "reporting a vulnerability",
    "security policy", "report security", "pgp key", "security@",
)

# ── automated_build ──────────────────────────────────────────────────────
_BUILD_TOOL_FILES = (
    "Makefile", "makefile", "GNUmakefile", "build.gradle", "build.gradle.kts", "webpack.config.js", "webpack.config.ts",
)

# ── deployment_docker ────────────────────────────────────────────────────
_DOCKER_FILES = ("Dockerfile", "dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
_HELM_CHART_FILE = "Chart.yaml"

# ── catalog_info (Backstage convention) ─────────────────────────────────
_CATALOG_INFO_CANDIDATES = ("catalog-info.yaml", "catalog-info.yml", ".backstage/catalog-info.yaml")

# ── doc_breadth ───────────────────────────────────────────────────────────
_README_RE = re.compile(r"^readme(\.md|\.rst|\.txt)?$", re.IGNORECASE)
_DOCS_DIR_RE = re.compile(r"(^|/)(docs|documentation|doc)/", re.IGNORECASE)
_MD_TXT_RE = re.compile(r"\.(md|txt)$", re.IGNORECASE)


def _basename(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _first_existing(local_root: Path, candidates: tuple[str, ...]) -> Path | None:
    for rel in candidates:
        p = local_root / rel
        if p.is_file():
            return p
    return None


def _any_file_present(local_root: Path, filenames: tuple[str, ...]) -> list[str]:
    """Search the whole tree (not just root) for any of these basenames —
    matches how build/deploy tooling commonly lives in a subdirectory
    (monorepos, a `docker/` folder, etc.), not always at repo root."""
    found = []
    for p in local_root.rglob("*"):
        if p.is_file() and p.name in filenames:
            found.append(str(p.relative_to(local_root)))
    return found


class RepoConventionsParser:
    """Scans a downloaded repo tree for the Part 2 Discovery-tier convention
    signals. Returns a list of finding dicts (upsert_finding-shaped) — may
    be empty only if the repo somehow has zero files (never in practice)."""

    def parse(self, local_root: Path) -> list[dict]:
        local_root = Path(local_root)
        findings: list[dict] = []
        findings.append(self._security_policy_content(local_root))
        findings.append(self._automated_build(local_root))
        findings.append(self._deployment_docker(local_root))
        findings.append(self._catalog_info(local_root))
        findings.append(self._doc_breadth(local_root))
        return findings

    def _security_policy_content(self, local_root: Path) -> dict:
        path = _first_existing(local_root, _SECURITY_POLICY_CANDIDATES)
        if path is None:
            return {
                "check_name": "security_policy_content", "label": "not_found",
                "summary": "No SECURITY.md-style file found.",
                "confidence": 90, "detail": {},
            }
        try:
            text = path.read_text(encoding="utf-8", errors="ignore").lower()
        except Exception:
            text = ""
        matched = [kw for kw in _SECURITY_POLICY_KEYWORDS if kw in text]
        label = "pass" if matched else "gap"
        summary = (
            f"{path.name} found, contains recognizable policy language (matched: {', '.join(matched[:2])})"
            if matched else f"{path.name} found, but no recognizable policy language detected"
        )
        return {
            "check_name": "security_policy_content", "label": label, "summary": summary,
            "confidence": 80, "detail": {"path": str(path.relative_to(local_root)), "matched_keywords": matched},
        }

    def _automated_build(self, local_root: Path) -> dict:
        found = _any_file_present(local_root, _BUILD_TOOL_FILES)
        pyproject = local_root / "pyproject.toml"
        if pyproject.is_file():
            try:
                if "[build-system]" in pyproject.read_text(encoding="utf-8", errors="ignore"):
                    found.append("pyproject.toml ([build-system])")
            except Exception:
                pass
        label = "pass" if found else "gap"
        summary = f"Build tooling found: {', '.join(found[:3])}" if found else "No build-tooling files found"
        return {
            "check_name": "automated_build", "label": label, "summary": summary,
            "confidence": 75, "detail": {"files": found},
        }

    def _deployment_docker(self, local_root: Path) -> dict:
        found = _any_file_present(local_root, _DOCKER_FILES)
        helm = _any_file_present(local_root, (_HELM_CHART_FILE,))
        found.extend(f"{p} (Helm)" for p in helm)
        label = "pass" if found else "gap"
        summary = f"Deployment/container evidence found: {', '.join(found[:3])}" if found else "No Dockerfile/compose/Helm chart found"
        return {
            "check_name": "deployment_docker", "label": label, "summary": summary,
            "confidence": 75, "detail": {"files": found},
        }

    def _catalog_info(self, local_root: Path) -> dict:
        path = _first_existing(local_root, _CATALOG_INFO_CANDIDATES)
        label = "present" if path else "absent"
        summary = (
            f"Self-describing catalog metadata found ({path.relative_to(local_root)}) — "
            "already integrated into some enterprise inventory."
            if path else "No catalog-info.yaml (Backstage convention) or similar found."
        )
        return {
            "check_name": "catalog_info", "label": label, "summary": summary,
            "confidence": 90, "detail": {"path": str(path.relative_to(local_root)) if path else ""},
        }

    def _doc_breadth(self, local_root: Path) -> dict:
        readme_count = 0
        md_txt_count = 0
        docs_dir_present = False
        for p in local_root.rglob("*"):
            if not p.is_file():
                continue
            rel = str(p.relative_to(local_root)).replace("\\", "/")
            name = _basename(rel)
            if _README_RE.match(name):
                readme_count += 1
            if _MD_TXT_RE.search(name):
                md_txt_count += 1
            if not docs_dir_present and _DOCS_DIR_RE.search(rel + "/"):
                docs_dir_present = True

        signal_count = (1 if readme_count >= 1 else 0) + (1 if docs_dir_present else 0) + (1 if md_txt_count >= 3 else 0)
        label = "pass" if signal_count >= 2 else "gap"
        summary = (
            f"{readme_count} README(s), {'a' if docs_dir_present else 'no'} docs folder, "
            f"{md_txt_count} .md/.txt file(s) total"
        )
        return {
            "check_name": "doc_breadth", "label": label, "summary": summary,
            "confidence": 85,
            "detail": {"readme_count": readme_count, "docs_dir_present": docs_dir_present, "md_txt_count": md_txt_count},
        }
