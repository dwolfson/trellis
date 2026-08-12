"""Tests for CiWorkflowParser — Assessment expansion plan B4's heuristic
keyword scan of .github/workflows/*.yml content."""
from __future__ import annotations

from resource_explorer.ingestion.ci_workflow_parser import CiWorkflowParser


def _write_workflow(root, name, content):
    wf_dir = root / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    (wf_dir / name).write_text(content)


class TestCiWorkflowParser:
    def test_no_workflows_dir_yields_no_findings(self, tmp_path):
        assert CiWorkflowParser().parse(tmp_path) == []

    def test_empty_workflows_dir_yields_no_findings(self, tmp_path):
        (tmp_path / ".github" / "workflows").mkdir(parents=True)
        assert CiWorkflowParser().parse(tmp_path) == []

    def test_full_ci_detects_all_three_checks(self, tmp_path):
        _write_workflow(tmp_path, "ci.yml", """
name: CI
jobs:
  build:
    steps:
      - run: pip install -e .
      - run: pytest tests/
      - run: ruff check .
      - run: docker build -t myimage .
""")
        findings = CiWorkflowParser().parse(tmp_path)
        by_check = {f["check_name"]: f for f in findings}
        assert set(by_check) == {"ci_runs_tests", "ci_runs_lint", "ci_runs_build"}
        assert by_check["ci_runs_tests"]["label"] == "pass"
        assert by_check["ci_runs_lint"]["label"] == "pass"
        assert by_check["ci_runs_build"]["label"] == "pass"
        assert "pytest" in by_check["ci_runs_tests"]["detail"]["matched_keywords"]

    def test_ci_with_no_meaningful_steps_is_all_gaps(self, tmp_path):
        _write_workflow(tmp_path, "ci.yml", """
name: CI
jobs:
  noop:
    steps:
      - run: echo "hello"
""")
        findings = CiWorkflowParser().parse(tmp_path)
        by_check = {f["check_name"]: f for f in findings}
        assert all(f["label"] == "gap" for f in by_check.values())

    def test_matches_across_multiple_workflow_files(self, tmp_path):
        _write_workflow(tmp_path, "test.yml", "jobs:\n  t:\n    steps:\n      - run: npm test\n")
        _write_workflow(tmp_path, "lint.yml", "jobs:\n  l:\n    steps:\n      - run: eslint .\n")
        findings = CiWorkflowParser().parse(tmp_path)
        by_check = {f["check_name"]: f for f in findings}
        assert by_check["ci_runs_tests"]["label"] == "pass"
        assert by_check["ci_runs_lint"]["label"] == "pass"
        assert by_check["ci_runs_build"]["label"] == "gap"

    def test_matches_both_yml_and_yaml_extensions(self, tmp_path):
        _write_workflow(tmp_path, "ci.yaml", "jobs:\n  t:\n    steps:\n      - run: go test ./...\n")
        findings = CiWorkflowParser().parse(tmp_path)
        by_check = {f["check_name"]: f for f in findings}
        assert by_check["ci_runs_tests"]["label"] == "pass"

    def test_case_insensitive_matching(self, tmp_path):
        _write_workflow(tmp_path, "ci.yml", "jobs:\n  t:\n    steps:\n      - run: PYTEST tests/\n")
        findings = CiWorkflowParser().parse(tmp_path)
        by_check = {f["check_name"]: f for f in findings}
        assert by_check["ci_runs_tests"]["label"] == "pass"
