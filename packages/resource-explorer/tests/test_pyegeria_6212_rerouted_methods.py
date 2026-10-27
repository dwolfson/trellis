"""pyegeria 6.2.12 (#485, ISSUE-165; #487): methods whose Egeria endpoints were removed now delegate elsewhere.

The behaviour risk of the bump is an RE call that used to reach the old endpoint and now reaches a replacement with
different semantics (a SurveyReport asset instead of an analysis report, collection membership instead of
subject-area membership, a best-effort data-classification mapping). The audit (2026-10-27) found no RE call site
for any of them, nor for get_platform_organization, which now reads /api/public/app/info. This pins:
1. No RE source or script calls a rerouted method by name (adding one is a reviewed decision).
2. The installed pyegeria is at least 6.2.12, so a downgrade cannot slip back in under the lock.
3. delete_annotation's body is optional now; RE does not call it, and the signature RE would bind to is pinned.
"""
from __future__ import annotations

import ast
import inspect
from importlib.metadata import version
from pathlib import Path

from pyegeria import DataDiscovery

import resource_explorer

RE_ROOT = Path(resource_explorer.__file__).parent
SCRIPTS = RE_ROOT.parent / "scripts"

#: Rerouted by #485 (deprecated wrappers) or changed by #487. Calling any of these from RE needs a review first.
REROUTED = {
    "create_analysis_report", "update_analysis_report", "delete_analysis_report", "get_analysis_reports_by_name",
    "find_analysis_reports", "get_analysis_report_by_guid", "link_analysis_report_to_asset",
    "detach_analysis_report_from_asset", "add_element_to_subject_area", "remove_element_from_subject_area",
    "find_governance_action_processes", "get_gov_def_in_context", "create_data_classification",
    "update_data_classification", "link_data_classification_to_data_field",
    "detach_data_classification_from_data_field", "get_platform_organization",
}


def _called_names(root: Path):
    for py in root.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
                if name:
                    yield py, node.lineno, name.removeprefix("_async_")


def test_no_re_source_or_script_calls_a_rerouted_method():
    hits = [f"{py.relative_to(RE_ROOT.parent)}:{line} {name}"
            for root in (RE_ROOT, SCRIPTS) if root.exists()
            for py, line, name in _called_names(root) if name in REROUTED]
    assert hits == [], "review the pyegeria 6.2.12 replacement before calling: " + ", ".join(hits)


def test_the_installed_pyegeria_is_at_least_6_2_12():
    parts = tuple(int(p) for p in version("pyegeria").split(".")[:3])
    assert parts >= (6, 2, 12)


def test_delete_annotation_body_is_optional():
    param = inspect.signature(DataDiscovery.delete_annotation).parameters["body"]
    assert param.default is None
