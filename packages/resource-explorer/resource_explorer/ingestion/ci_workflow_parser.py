"""Heuristic keyword scan of .github/workflows/*.yml content for signs of
real test/lint/build stages — not artifact *presence* (that's
SecurityHygieneSurveyor's "ci_config" check), but whether the CI config
actually *runs* anything meaningful.

Assessment expansion plan B4 (docs/assessment-expansion-plan.md). Deliberately
a substring/keyword match over raw YAML text, not full YAML semantic parsing
— matching this codebase's existing "cheap structural signal, not full
understanding" pattern (DocumentationSurveyor's own presence checks,
DependencyParser's regex-based manifest parsing). A workflow that legitimately
runs tests via an unusual invocation this list doesn't recognize will read as
a false gap — an accepted heuristic tradeoff, not a bug, same class as any
keyword-based classifier in this codebase.
"""
from __future__ import annotations

from pathlib import Path

# Substring keywords, lowercase-matched against each workflow file's raw
# text. Not exhaustive — covers the common ecosystems/tools this codebase
# already surveys elsewhere (dependency_parser.py's Python/Node/Go/Java
# coverage, plus common lint tools for each).
_TEST_KEYWORDS = (
    "pytest", "npm test", "npm run test", "yarn test", "go test",
    "unittest", "jest", "mocha", "cargo test", "mvn test", "gradle test",
    "rspec", "phpunit", "make test", "tox",
)
_LINT_KEYWORDS = (
    "ruff", "eslint", "flake8", "pylint", "black --check", "prettier --check",
    "golangci-lint", "rubocop", "shellcheck", "mypy", "cargo clippy",
    "checkstyle",
)
_BUILD_KEYWORDS = (
    "docker build", "docker buildx", "npm run build", "yarn build",
    "go build", "mvn package", "mvn install", "cargo build", "make build",
    "gradle build", "python -m build", "poetry build", "webpack",
)

_CHECKS = (
    ("ci_runs_tests", "runs tests", _TEST_KEYWORDS),
    ("ci_runs_lint", "runs lint/static-analysis", _LINT_KEYWORDS),
    ("ci_runs_build", "runs a build step", _BUILD_KEYWORDS),
)


class CiWorkflowParser:
    """Scans .github/workflows/*.y*ml under local_root for keyword evidence
    of test/lint/build stages. Returns a list of finding dicts (empty if no
    workflow files exist at all — mirrors DependencyParser's "no manifests,
    no findings" convention rather than reporting 3 gaps for a repo this
    surveyor never actually looked at)."""

    def parse(self, local_root: Path) -> list[dict]:
        workflows_dir = Path(local_root) / ".github" / "workflows"
        if not workflows_dir.is_dir():
            return []

        workflow_files = sorted(
            [*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")]
        )
        if not workflow_files:
            return []

        combined_text = ""
        file_names = []
        for wf in workflow_files:
            try:
                combined_text += "\n" + wf.read_text(encoding="utf-8", errors="ignore").lower()
                file_names.append(wf.name)
            except Exception:
                continue

        if not file_names:
            return []

        findings: list[dict] = []
        for check_name, description, keywords in _CHECKS:
            matched = [kw for kw in keywords if kw in combined_text]
            label = "pass" if matched else "gap"
            summary = (
                f"CI {description} (matched: {', '.join(matched[:3])})"
                if matched
                else f"CI does not appear to {description.replace('runs ', 'run ')}"
            )
            findings.append({
                "check_name": check_name, "label": label, "summary": summary,
                "confidence": 80,  # heuristic keyword match, not semantic parsing
                "detail": {"workflow_files": file_names, "matched_keywords": matched},
            })

        return findings
