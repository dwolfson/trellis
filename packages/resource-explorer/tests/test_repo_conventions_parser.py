"""Tests for RepoConventionsParser — Assessment expansion Part 2's
Discovery-tier convention signals
(docs/discovery-automate-project-context-plan.md Part 2)."""
from __future__ import annotations

from resource_explorer.ingestion.repo_conventions_parser import RepoConventionsParser


def _write(root, rel_path, content=""):
    p = root / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _findings_by_check(findings):
    return {f["check_name"]: f for f in findings}


class TestParse:
    def test_returns_all_five_checks_always(self, tmp_path):
        findings = RepoConventionsParser().parse(tmp_path)
        assert {f["check_name"] for f in findings} == {
            "security_policy_content", "automated_build", "deployment_docker",
            "catalog_info", "doc_breadth",
        }


class TestSecurityPolicyContent:
    def test_no_file_is_not_found(self, tmp_path):
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["security_policy_content"]["label"] == "not_found"

    def test_file_with_policy_language_passes(self, tmp_path):
        _write(tmp_path, "SECURITY.md", "# Security Policy\n\nTo report a vulnerability, email security@example.com")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["security_policy_content"]["label"] == "pass"

    def test_file_without_policy_language_is_gap(self, tmp_path):
        _write(tmp_path, "SECURITY.md", "# Security\n\nSee our other docs.")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["security_policy_content"]["label"] == "gap"

    def test_github_subdir_location_recognized(self, tmp_path):
        _write(tmp_path, ".github/SECURITY.md", "Please report a vulnerability via email.")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["security_policy_content"]["label"] == "pass"


class TestAutomatedBuild:
    def test_no_build_tooling_is_gap(self, tmp_path):
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["automated_build"]["label"] == "gap"

    def test_makefile_passes(self, tmp_path):
        _write(tmp_path, "Makefile", "build:\n\techo hi\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["automated_build"]["label"] == "pass"

    def test_pyproject_build_system_table_passes(self, tmp_path):
        _write(tmp_path, "pyproject.toml", "[build-system]\nrequires = ['setuptools']\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["automated_build"]["label"] == "pass"

    def test_pyproject_without_build_system_table_does_not_pass_alone(self, tmp_path):
        _write(tmp_path, "pyproject.toml", "[tool.black]\nline-length = 100\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["automated_build"]["label"] == "gap"

    def test_build_tooling_found_in_subdirectory(self, tmp_path):
        _write(tmp_path, "backend/build.gradle", "")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["automated_build"]["label"] == "pass"


class TestDeploymentDocker:
    def test_no_evidence_is_gap(self, tmp_path):
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["deployment_docker"]["label"] == "gap"

    def test_dockerfile_passes(self, tmp_path):
        _write(tmp_path, "Dockerfile", "FROM python:3.13\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["deployment_docker"]["label"] == "pass"

    def test_compose_yaml_passes(self, tmp_path):
        _write(tmp_path, "compose.yaml", "services: {}\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["deployment_docker"]["label"] == "pass"

    def test_helm_chart_passes(self, tmp_path):
        _write(tmp_path, "chart/Chart.yaml", "apiVersion: v2\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["deployment_docker"]["label"] == "pass"


class TestCatalogInfo:
    def test_absent_by_default(self, tmp_path):
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["catalog_info"]["label"] == "absent"

    def test_present_at_root(self, tmp_path):
        _write(tmp_path, "catalog-info.yaml", "apiVersion: backstage.io/v1alpha1\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["catalog_info"]["label"] == "present"


class TestDocBreadth:
    def test_no_docs_is_gap(self, tmp_path):
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["doc_breadth"]["label"] == "gap"
        assert by_check["doc_breadth"]["detail"]["readme_count"] == 0

    def test_readme_plus_docs_folder_passes(self, tmp_path):
        _write(tmp_path, "README.md", "# Project\n")
        _write(tmp_path, "docs/index.md", "docs\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["doc_breadth"]["label"] == "pass"
        assert by_check["doc_breadth"]["detail"]["readme_count"] == 1
        assert by_check["doc_breadth"]["detail"]["docs_dir_present"] is True

    def test_readme_only_is_gap_needs_two_signals(self, tmp_path):
        _write(tmp_path, "README.md", "# Project\n")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["doc_breadth"]["label"] == "gap"

    def test_many_md_files_counts_as_second_signal(self, tmp_path):
        _write(tmp_path, "README.md", "# Project\n")
        _write(tmp_path, "a.md", "")
        _write(tmp_path, "b.md", "")
        _write(tmp_path, "c.md", "")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["doc_breadth"]["detail"]["md_txt_count"] >= 3
        assert by_check["doc_breadth"]["label"] == "pass"

    def test_readme_counted_anywhere_in_tree(self, tmp_path):
        _write(tmp_path, "sub/README.rst", "")
        _write(tmp_path, "README.md", "")
        by_check = _findings_by_check(RepoConventionsParser().parse(tmp_path))
        assert by_check["doc_breadth"]["detail"]["readme_count"] == 2
