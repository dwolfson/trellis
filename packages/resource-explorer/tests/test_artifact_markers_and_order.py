"""Route markers describe what a product exposes, and api_structure reads the
symbols of the run it is in (inventory 2026-10-15, dataops_testgen).

* 2,438 markers, 54 real routes: the rest were `patch("...")` mock calls and
  invoke `@task` build commands, almost all under `tests/`.
* api_structure stored 5,937 symbols two seconds before extraction wrote 9,713.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from resource_explorer.ingestion.code_symbol_extractor import CodeSymbolExtractor
from resource_explorer.ingestion.test_paths import is_test_path

ROUTES_PY = '''
from fastapi import APIRouter
router = APIRouter()

@router.get("/token")
def get_token():
    return 1
'''

TEST_PY = '''
from unittest.mock import patch
import unittest.mock as mock

@patch("app.routes.x")
def test_a(m):
    pass

@mock.patch("app.routes.y")
def test_b(m):
    pass

@patch("app.routes.z", new=1)
def helper(): ...
'''

TASKS_PY = '''
from invoke import task

@task
def lint(c):
    pass
'''

CELERY_PY = '''
from celery import shared_task

@shared_task
def work():
    pass
'''

JAVA_ROUTE = '''
@RestController
class T {
    @GetMapping("/x")
    public String x() { return ""; }
}
'''


def _write(root, files):
    for rel, text in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)


def _markers(root, files):
    ex = CodeSymbolExtractor()
    out = []
    for rel, text in files.items():
        lang = "java" if rel.endswith(".java") else "python"
        out.extend(ex.extract_markers(rel, text, "p", lang))
    return out


FILES = {
    "app/routes.py": ROUTES_PY,
    "tests/test_routes.py": TEST_PY,
    "tests/test_more_routes.py": ROUTES_PY,      # a sample route in a test is still not product surface
    "invocations/ci.py": TASKS_PY,
    "app/jobs.py": CELERY_PY,
}


class TestPythonMarkers:
    def test_only_the_real_route_and_real_celery_task_are_recorded(self, tmp_path):
        ms = _markers(tmp_path, FILES)
        assert sorted((m.file_path, m.framework, m.detail) for m in ms) == [
            ("app/jobs.py", "celery", ""),
            ("app/routes.py", "fastapi", "GET /token"),
        ]

    def test_mock_patch_forms_are_not_routes_even_outside_tests(self):
        ms = CodeSymbolExtractor().extract_markers("app/helpers.py", TEST_PY, "p", "python")
        assert ms == []

    def test_invoke_task_is_not_celery(self):
        assert CodeSymbolExtractor().extract_markers("invocations/ci.py", TASKS_PY, "p", "python") == []

    def test_real_registration_forms_still_count(self):
        src = '''
@app.post("/a")
def a(): ...
@app.patch("/b")
def b(): ...
@bp.route("/c", methods=["PUT"])
def c(): ...
@router.get("")
def d(): ...
'''
        ms = CodeSymbolExtractor().extract_markers("app/x.py", src, "p", "python")
        assert sorted(m.detail for m in ms) == ["GET", "PATCH /b", "POST /a", "PUT /c"]


class TestTestPathRule:
    @pytest.mark.parametrize("rel", [
        "tests/a.py", "pkg/tests/a.py", "test_a.py", "pkg/a_test.py", "src/test/java/a/B.java",
        "web/__tests__/a.js", "web/a.test.ts", "src/main/java/FooTest.java", "conftest.py", "x/a_test.go",
    ])
    def test_tests(self, rel):
        assert is_test_path(rel)

    @pytest.mark.parametrize("rel", [
        "testgen/api/app.py", "app/routes.py", "src/main/java/a/B.java", "latest/a.py", "contest/x.py",
    ])
    def test_product_code(self, rel):
        assert not is_test_path(rel)


class TestJavaFixture:
    def test_route_annotation_under_src_test_is_excluded(self):
        ex = CodeSymbolExtractor()
        if not ex.extract_markers("src/main/java/a/T.java", JAVA_ROUTE, "p", "java"):
            pytest.skip("java tree-sitter grammar unavailable")
        assert ex.extract_markers("src/test/java/a/T.java", JAVA_ROUTE, "p", "java") == []
        assert len(ex.extract_markers("src/main/java/a/T.java", JAVA_ROUTE, "p", "java")) == 1


class TestInterfaceSurfaceCount:
    def test_the_surveyor_stores_and_reports_one_registration(self, tmp_path):
        from resource_explorer.registry import Project, ProjectRegistry
        from resource_explorer.surveyors.sub_surveyors.symbol_extraction import SymbolExtractionSurveyor
        from resource_explorer.surveyors.sub_surveyors.interface_surface import _registrations

        repo = tmp_path / "repo"
        _write(repo, {k: v for k, v in FILES.items() if k != "app/jobs.py"})
        registry = ProjectRegistry(db_path=str(tmp_path / "r.db"))
        project = Project(slug="fx", display_name="fx", github_url="https://github.com/x/fx")
        registry.add(project)
        SymbolExtractionSurveyor(project, registry, str(repo)).run()
        rows = registry.get_code_markers("fx")
        assert [(r["file_path"], r["detail"]) for r in rows] == [("app/routes.py", "GET /token")]
        regs = _registrations(rows, None)
        assert len(regs["http_api"]) == 1 and "messaging" not in regs

    def test_stale_test_rows_already_stored_are_not_counted(self):
        rows = [{"interface_kind": "http_api", "detail": "PATCH", "file_path": "tests/t.py"},
                {"interface_kind": "http_api", "detail": "GET /a", "file_path": "app/a.py"}]
        from resource_explorer.surveyors.sub_surveyors.interface_surface import _registrations
        assert len(_registrations(rows, None)["http_api"]) == 1


@dataclass
class _Step:
    guid: str
    re_analysis_step: str
    qualified_name: str = ""
    executes_at: str = "resource-explorer"


@dataclass
class _Link:
    previous_guid: str
    next_guid: str
    guard: str = "Any"


@dataclass
class _Def:
    qualified_name: str = "GovActionProcess::T"
    steps: list = field(default_factory=list)
    links: list = field(default_factory=list)


class TestApiStructureOrdering:
    def test_api_structure_depends_on_symbol_extraction(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        assert "repo_symbol_extraction" in STEP_REGISTRY["repo_api_structure"].requires

    def test_a_definition_authored_api_first_still_plans_with_extraction_first(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        from resource_explorer.surveyors.survey_execution_plan import build_plan
        keys = ["repo_dependency", "repo_api_structure", "repo_data_profiling", "repo_symbol_extraction"]
        d = _Def(steps=[_Step(k, k, k) for k in keys],
                 links=[_Link(a, b) for a, b in zip(keys, keys[1:])])
        order = [s.step_key for s in build_plan(d, step_registry=STEP_REGISTRY).steps]
        assert sorted(order) == sorted(keys)
        assert order.index("repo_symbol_extraction") < order.index("repo_api_structure")
        assert order[0] == "repo_dependency"          # the dropped edge did not strand a step

    def test_a_real_data_cycle_still_raises(self, monkeypatch):
        from resource_explorer.surveyors import step_preconditions as sp, step_produces
        from resource_explorer.surveyors.repo_survey_definition_adapter import StepInfo
        from resource_explorer.surveyors.survey_execution_plan import CyclicPlanError, build_plan
        for n, t in (("needs_a", "ta"), ("needs_b", "tb")):
            monkeypatch.setitem(sp.PRECONDITIONS, n, sp.Precondition(sp._needs_rows(t, n), table=t))
        reg = {"a": StepInfo("a", None, "", [], produces=("ta",), requires_context={"needs_b": "x"}),
               "b": StepInfo("b", None, "", [], produces=("tb",), requires_context={"needs_a": "x"})}
        monkeypatch.setattr(step_produces, "_registries", lambda: {"repo": reg})
        with pytest.raises(CyclicPlanError):
            build_plan(_Def(steps=[_Step("a", "a", "a"), _Step("b", "b", "b")]), step_registry=reg)

    def test_extraction_then_api_structure_plans_in_that_order(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        from resource_explorer.surveyors.survey_execution_plan import build_plan
        keys = ["repo_symbol_extraction", "repo_api_structure"]
        plan = build_plan(_Def(steps=[_Step(k, k, k) for k in keys]), step_registry=STEP_REGISTRY)
        assert [s.step_key for s in plan.steps] == keys

    def test_every_live_definition_with_both_steps_orders_them(self):
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        from resource_explorer.surveyors.survey_definition_docs import documented_definitions
        from resource_explorer.surveyors.survey_execution_plan import build_plan
        seen = 0
        for name, doc in documented_definitions().items():
            if "repo_api_structure" not in doc.steps or "repo_symbol_extraction" not in doc.steps:
                continue
            seen += 1
            steps = [_Step(k, k, k) for k in doc.steps]
            links = [_Link(p, n, g) for p, n, g in doc.links]
            plan = build_plan(_Def(qualified_name=name, steps=steps, links=links),
                              step_registry=STEP_REGISTRY)
            order = [s.step_key for s in plan.steps]
            assert order.index("repo_symbol_extraction") < order.index("repo_api_structure"), name
        assert seen, "no live definition has both steps; the guard checked nothing"

    def test_stored_count_equals_the_symbols_written_in_the_same_run(self, tmp_path):
        from resource_explorer.registry import Project, ProjectRegistry
        from resource_explorer.surveyors.sub_surveyors.api_structure import ApiStructureSurveyor
        from resource_explorer.surveyors.sub_surveyors.symbol_extraction import SymbolExtractionSurveyor
        from resource_explorer.surveyors.repo_survey_definition_adapter import STEP_REGISTRY
        from resource_explorer.surveyors.survey_execution_plan import build_plan

        repo = tmp_path / "repo"
        _write(repo, {"app/a.py": "def one(): ...\ndef two(): ...\nclass C:\n    def m(self): ...\n"})
        registry = ProjectRegistry(db_path=str(tmp_path / "r.db"))
        project = Project(slug="fx", display_name="fx", github_url="https://github.com/x/fx")
        registry.add(project)
        # a previous run left a smaller table: the stale value api_structure used to store
        registry.upsert_code_symbols("fx", [])
        runners = {
            "repo_symbol_extraction": lambda: SymbolExtractionSurveyor(project, registry, str(repo)).run(),
            "repo_api_structure": lambda: ApiStructureSurveyor(project, registry).run(),
        }
        d = _Def(steps=[_Step(k, k, k) for k in ("repo_symbol_extraction", "repo_api_structure")])
        for step in build_plan(d, step_registry=STEP_REGISTRY).steps:
            runners[step.step_key]()
        written = len(registry.get_code_symbols("fx")) if hasattr(registry, "get_code_symbols") else None
        stored = registry.query_metrics("fx", "api_structure")["symbol_count"]
        assert stored == 4
        if written is not None:
            assert stored == written
