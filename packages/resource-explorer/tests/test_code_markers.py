"""project_code_markers — DESIGN-INTERFACE-SURFACE-IMPLEMENTED-RUNG.md.

Covers the capture layer (CodeSymbolExtractor.extract_markers for Python and
Java), the registry's rewrite-on-rerun semantics, and the backfill-flag
mechanism InterfaceSurfaceSurveyor._capture_coverage reads — kept separate
from tests/test_interface_surface.py, which covers the CONSUMPTION side
(detect()'s three-outcome table) against plain dicts rather than real
extraction output.
"""
from __future__ import annotations

import pytest

from resource_explorer.ingestion.code_symbol_extractor import (
    MARKER_CAPABLE_LANGUAGES,
    CodeMarker,
    CodeSymbolExtractor,
)
from resource_explorer.registry import Project, ProjectRegistry


@pytest.fixture
def extractor():
    return CodeSymbolExtractor()


class TestMarkerCapableLanguages:
    def test_python_and_java_are_capable(self):
        assert MARKER_CAPABLE_LANGUAGES == {"python", "java"}

    def test_an_uncovered_language_returns_nothing_rather_than_guessing(self, extractor):
        """go/js have no decorator equivalent for their common frameworks —
        extract_markers must return [] for them, not attempt a heuristic."""
        assert extractor.extract_markers("main.go", "func main() {}", "p", "go") == []
        assert extractor.extract_markers("x.js", "function f() {}", "p", "javascript") == []


class TestPythonMarkerCapture:
    def test_fastapi_route_decorators(self, extractor):
        src = (
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "@app.get(\"/items/{id}\")\n"
            "def read_item(id: int):\n"
            "    pass\n\n"
            "@app.post(\"/items\")\n"
            "async def create_item():\n"
            "    pass\n"
        )
        markers = extractor.extract_markers("app.py", src, "p", "python")
        by_name = {m.qualified_name: m for m in markers}
        assert by_name["read_item"].interface_kind == "http_api"
        assert by_name["read_item"].framework == "fastapi"
        assert by_name["read_item"].detail == "GET /items/{id}"
        assert by_name["create_item"].detail == "POST /items"

    def test_flask_route_with_explicit_methods(self, extractor):
        src = (
            "@app.route(\"/x\", methods=[\"POST\"])\n"
            "def handler():\n"
            "    pass\n"
        )
        markers = extractor.extract_markers("app.py", src, "p", "python")
        assert len(markers) == 1
        m = markers[0]
        assert m.framework == "flask" and m.interface_kind == "http_api"
        assert m.detail == "POST /x"

    def test_django_rest_framework_api_view(self, extractor):
        src = (
            "@api_view([\"GET\"])\n"
            "def list_things(request):\n"
            "    pass\n"
        )
        markers = extractor.extract_markers("views.py", src, "p", "python")
        assert markers[0].framework == "django-rest-framework"
        assert markers[0].interface_kind == "http_api"

    def test_django_urls_py_path_calls(self, extractor):
        src = (
            "from django.urls import path\n"
            "urlpatterns = [path(\"things/\", views.list_things)]\n"
        )
        markers = extractor.extract_markers("urls.py", src, "p", "python")
        assert len(markers) == 1
        assert markers[0].framework == "django"
        assert markers[0].detail == "things/"

    def test_path_calls_outside_urls_py_are_not_treated_as_routes(self, extractor):
        """The Django detection is deliberately scoped to a urls.py-shaped
        file — a `path(...)` call anywhere else (e.g. pathlib.Path usage) is
        not evidence of a route."""
        src = "from pathlib import Path\nx = path(\"/tmp/foo\")\n"
        markers = extractor.extract_markers("utils.py", src, "p", "python")
        assert markers == []

    def test_celery_task_decorators(self, extractor):
        src = (
            "from celery import shared_task\n\n"
            "@shared_task\n"
            "def do_work():\n"
            "    pass\n\n"
            "@app.task\n"
            "def do_other_work():\n"
            "    pass\n"
        )
        markers = extractor.extract_markers("tasks.py", src, "p", "python")
        assert len(markers) == 2
        assert all(m.interface_kind == "messaging" and m.framework == "celery" for m in markers)

    def test_strawberry_graphql_resolvers(self, extractor):
        src = (
            "@strawberry.field\n"
            "def resolve_thing() -> str:\n"
            "    pass\n\n"
            "@strawberry.mutation\n"
            "def create_thing() -> str:\n"
            "    pass\n"
        )
        markers = extractor.extract_markers("schema.py", src, "p", "python")
        assert len(markers) == 2
        assert all(m.interface_kind == "graphql" and m.framework == "strawberry" for m in markers)

    def test_graphene_object_type_resolve_methods(self, extractor):
        src = (
            "class Query(graphene.ObjectType):\n"
            "    def resolve_things(self, info):\n"
            "        pass\n"
            "    def not_a_resolver(self):\n"
            "        pass\n"
        )
        markers = extractor.extract_markers("schema.py", src, "p", "python")
        assert len(markers) == 1
        assert markers[0].qualified_name == "Query.resolve_things"
        assert markers[0].framework == "graphene"

    def test_grpc_servicer_base_class_yields_one_marker_per_public_method(self, extractor):
        src = (
            "class GreeterServicer(greeter_pb2_grpc.GreeterServicer):\n"
            "    def SayHello(self, request, context):\n"
            "        pass\n"
            "    def _internal(self):\n"
            "        pass\n"
            "    def __init__(self):\n"
            "        pass\n"
        )
        markers = extractor.extract_markers("servicer.py", src, "p", "python")
        assert len(markers) == 1
        assert markers[0].qualified_name == "GreeterServicer.SayHello"
        assert markers[0].interface_kind == "grpc"

    def test_no_registrations_in_plain_code(self, extractor):
        src = "def add(a, b):\n    return a + b\n"
        assert extractor.extract_markers("math.py", src, "p", "python") == []


def _java_treesitter_available() -> bool:
    try:
        import tree_sitter_java  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _java_treesitter_available(), reason="tree-sitter-java not installed")
class TestJavaMarkerCapture:
    def test_spring_mvc_get_mapping(self, extractor):
        src = (
            "package com.example;\n"
            "public class FooController {\n"
            "    @GetMapping(\"/foo/{id}\")\n"
            "    public String getFoo(String id) {\n"
            "        return null;\n"
            "    }\n"
            "}\n"
        )
        markers = extractor.extract_markers("FooController.java", src, "p", "java")
        assert len(markers) == 1
        m = markers[0]
        assert m.framework == "spring-mvc" and m.interface_kind == "http_api"
        assert m.detail == "GET /foo/{id}"
        assert m.qualified_name == "FooController.getFoo"

    def test_spring_kafka_listener(self, extractor):
        src = (
            "public class Consumer {\n"
            "    @KafkaListener(topics = \"my-topic\")\n"
            "    public void onMessage(String msg) {\n"
            "    }\n"
            "}\n"
        )
        markers = extractor.extract_markers("Consumer.java", src, "p", "java")
        assert len(markers) == 1
        assert markers[0].interface_kind == "messaging"
        assert markers[0].framework == "kafka"
        assert markers[0].detail == "my-topic"

    def test_grpc_impl_base_yields_rpc_method_markers(self, extractor):
        src = (
            "public class GreeterService extends GreeterGrpc.GreeterImplBase {\n"
            "    public void sayHello(HelloRequest req, StreamObserver<HelloReply> resp) {\n"
            "    }\n"
            "}\n"
        )
        markers = extractor.extract_markers("GreeterService.java", src, "p", "java")
        assert len(markers) == 1
        assert markers[0].interface_kind == "grpc"
        assert markers[0].qualified_name == "GreeterService.sayHello"

    def test_no_annotations_yields_no_markers(self, extractor):
        src = "public class Plain {\n    public void doThing() {}\n}\n"
        assert extractor.extract_markers("Plain.java", src, "p", "java") == []


@pytest.fixture
def registry(tmp_path):
    return ProjectRegistry(db_path=str(tmp_path / "t.db"))


@pytest.fixture
def project(registry):
    p = Project(slug="p", display_name="P", github_url="https://github.com/x/p", description="")
    registry.add(p)
    return p


class TestRegistryRewriteSemantics:
    def _marker(self, **overrides):
        base = dict(
            resource_slug="p", file_path="a.py", start_line=1, language="python",
            marker_kind="route", framework="fastapi", interface_kind="http_api",
            detail="GET /x", qualified_name="foo",
        )
        base.update(overrides)
        return CodeMarker(**base)

    def test_upsert_then_read(self, registry, project):
        registry.upsert_code_markers("p", [self._marker()])
        rows = registry.get_code_markers("p")
        assert len(rows) == 1
        assert rows[0]["interface_kind"] == "http_api"

    def test_filter_by_interface_kind(self, registry, project):
        registry.upsert_code_markers("p", [
            self._marker(interface_kind="http_api"),
            self._marker(interface_kind="grpc", qualified_name="bar"),
        ])
        assert len(registry.get_code_markers("p", interface_kind="grpc")) == 1

    def test_rerun_does_not_accumulate_duplicates(self, registry, project):
        """The rewrite semantics repo_symbol_extraction relies on: clear the
        language's rows, then reinsert — a rerun over the SAME source must
        not double the marker count."""
        marker = self._marker()
        registry.clear_code_markers("p", "python")
        registry.upsert_code_markers("p", [marker])
        registry.clear_code_markers("p", "python")
        registry.upsert_code_markers("p", [marker])
        assert len(registry.get_code_markers("p")) == 1

    def test_rerun_drops_a_registration_that_no_longer_exists(self, registry, project):
        registry.clear_code_markers("p", "python")
        registry.upsert_code_markers("p", [self._marker(qualified_name="old_handler")])
        # Simulate the handler being removed/renamed on the next pass.
        registry.clear_code_markers("p", "python")
        registry.upsert_code_markers("p", [self._marker(qualified_name="new_handler")])
        names = {r["qualified_name"] for r in registry.get_code_markers("p")}
        assert names == {"new_handler"}

    def test_a_symbol_may_carry_two_registrations(self, registry, project):
        """No UNIQUE constraint, unlike project_code_symbols — one handler
        legitimately carries several decorators."""
        registry.upsert_code_markers("p", [
            self._marker(detail="GET /x", qualified_name="foo"),
            self._marker(detail="POST /x", qualified_name="foo"),
        ])
        rows = registry.get_code_markers("p")
        assert len(rows) == 2

    def test_removing_a_project_removes_its_markers(self, registry, project):
        registry.upsert_code_markers("p", [self._marker()])
        registry.remove("p")
        registry.add(project)
        assert registry.get_code_markers("p") == []


class TestBackfillFlag:
    """The mechanism InterfaceSurfaceSurveyor._capture_coverage reads —
    DESIGN-INTERFACE-SURFACE-IMPLEMENTED-RUNG.md Decisions §2's "backfill
    trap": a repo surveyed before project_code_markers shipped must not be
    misread as a measured zero."""

    def test_no_symbol_extraction_metric_means_capture_never_ran(self, registry, project):
        from resource_explorer.surveyors.sub_surveyors.interface_surface import (
            InterfaceSurfaceSurveyor,
        )
        coverage = InterfaceSurfaceSurveyor._capture_coverage(
            registry.query_metrics("p", "symbol_extraction"))
        assert coverage["has_run"] is False

    def test_a_pre_existing_metric_row_without_the_flag_is_not_a_measured_zero(self, registry, project):
        """The exact backfill trap: a symbol_extraction metric row exists
        (extraction genuinely ran, under the OLD code) but carries no
        markers_captured flag because project_code_markers did not exist
        yet. This must read as "never captured", not as a checked zero."""
        from resource_explorer.surveyors.sub_surveyors.interface_surface import (
            InterfaceSurfaceSurveyor,
        )
        registry.upsert_metric(
            "p", "symbol_extraction",
            {"symbol_count": 42, "relationship_count": 3},
            detail={"by_language": {"python": 42}},  # no "markers_captured" key
        )
        coverage = InterfaceSurfaceSurveyor._capture_coverage(
            registry.query_metrics("p", "symbol_extraction"))
        assert coverage["has_run"] is False

    def test_a_run_under_the_new_code_is_recognized(self, registry, project):
        from resource_explorer.surveyors.sub_surveyors.interface_surface import (
            InterfaceSurfaceSurveyor,
        )
        registry.upsert_metric(
            "p", "symbol_extraction",
            {"symbol_count": 10, "relationship_count": 0},
            detail={"by_language": {"python": 10}, "markers_captured": True},
        )
        coverage = InterfaceSurfaceSurveyor._capture_coverage(
            registry.query_metrics("p", "symbol_extraction"))
        assert coverage["has_run"] is True
        assert coverage["marker_capable_languages_present"] == ["python"]

    def test_a_capable_language_run_with_only_uncapable_languages_present(self, registry, project):
        from resource_explorer.surveyors.sub_surveyors.interface_surface import (
            InterfaceSurfaceSurveyor,
        )
        registry.upsert_metric(
            "p", "symbol_extraction",
            {"symbol_count": 10, "relationship_count": 0},
            detail={"by_language": {"go": 10}, "markers_captured": True},
        )
        coverage = InterfaceSurfaceSurveyor._capture_coverage(
            registry.query_metrics("p", "symbol_extraction"))
        assert coverage["has_run"] is True
        assert coverage["marker_capable_languages_present"] == []
        assert coverage["languages_present"] == ["go"]


class TestSymbolExtractionSurveyorWritesMarkers:
    def test_fastapi_route_is_captured_end_to_end(self, tmp_path, registry, project):
        from resource_explorer.surveyors.sub_surveyors.symbol_extraction import (
            SymbolExtractionSurveyor,
        )

        (tmp_path / "app.py").write_text(
            "from fastapi import FastAPI\n"
            "app = FastAPI()\n\n"
            "@app.get(\"/x\")\n"
            "def handler():\n"
            "    pass\n"
        )
        SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

        markers = registry.get_code_markers("p")
        assert len(markers) == 1
        assert markers[0]["interface_kind"] == "http_api"

        metrics = registry.query_metrics("p", "symbol_extraction")
        assert metrics["detail"]["markers_captured"] is True
        assert metrics["detail"]["marker_counts_by_language"] == {"python": 1}

    def test_rerun_clears_stale_markers(self, tmp_path, registry, project):
        from resource_explorer.surveyors.sub_surveyors.symbol_extraction import (
            SymbolExtractionSurveyor,
        )

        (tmp_path / "app.py").write_text(
            "@app.get(\"/old\")\ndef old_handler():\n    pass\n"
        )
        SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

        (tmp_path / "app.py").write_text(
            "@app.get(\"/new\")\ndef new_handler():\n    pass\n"
        )
        SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

        markers = registry.get_code_markers("p")
        assert len(markers) == 1
        assert markers[0]["qualified_name"] == "new_handler"

    def test_a_repo_with_no_marker_capable_language_still_sets_the_flag(self, tmp_path, registry, project):
        """The flag records that CAPTURE ran, independent of whether any
        marker-capable language had matching files — a Go-only repo must
        still be distinguishable from a repo never surveyed at all."""
        from resource_explorer.surveyors.sub_surveyors.symbol_extraction import (
            SymbolExtractionSurveyor,
        )

        (tmp_path / "README.md").write_text("nothing to extract")
        SymbolExtractionSurveyor(project, registry, local_path=str(tmp_path)).run()

        metrics = registry.query_metrics("p", "symbol_extraction")
        assert metrics["detail"]["markers_captured"] is True
        assert registry.get_code_markers("p") == []
