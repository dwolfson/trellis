"""Interface definition languages, and counting without listing.

Driving question (Dan, 2026-08-24): to judge whether a repo is usable at
runtime you want the kind of API, maybe language bindings, the number of
commands — NOT every request signature until you actually try to use it. So
these tests pin two things: that the IDL is recognised at all, and that what we
extract is a count rather than a listing.
"""
from __future__ import annotations

import json

import pytest

from resource_explorer.surveyors.arch_recovery import interfaces as I
from resource_explorer.surveyors.arch_recovery.ir import Component, Identity


def _comp(slug, files):
    return Component(slug=slug, name=slug, type="Software Service",
                     identity=Identity(method="path", value=slug), files=list(files))


def _propose(tmp_path, files: dict, components=None, code_marker_operations=None):
    for rel, body in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return I.propose(str(tmp_path), list(files), components or [],
                     code_marker_operations=code_marker_operations)


class TestGrpcIsNoLongerInvisible:
    """Milvus is gRPC-first with SDKs in several languages. Before this, we
    recorded its exposed ports and missed its actual interface entirely."""

    def test_a_proto_with_a_service_is_a_served_interface(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"api/milvus.proto": """
syntax = "proto3";
service MilvusService {
  rpc Insert (InsertRequest) returns (InsertResponse);
  rpc Search (SearchRequest) returns (SearchResponse);
}
"""})
        assert len(ports) == 1
        assert ports[0]["protocol"] == "gRPC"
        assert ports[0]["direction"] == I.DIR_INPUT_OUTPUT
        assert ports[0]["additionalProperties"]["operationCount"] == "2"

    def test_a_proto_with_only_messages_is_a_schema_not_an_interface(self, tmp_path):
        """Skipping it is correct, not a miss — a message-only .proto declares
        data shapes, and calling that a served interface would be inference."""
        ports, _, _, _ = _propose(tmp_path, {"types.proto": """
syntax = "proto3";
message InsertRequest { string collection = 1; }
"""})
        assert ports == []


class TestCountingIsNotListing:
    def test_openapi_operations_are_counted_across_paths_and_methods(self, tmp_path):
        doc = {"openapi": "3.0.0", "paths": {
            "/a": {"get": {}, "post": {}, "parameters": []},
            "/b": {"delete": {}},
        }}
        ports, _, _, _ = _propose(tmp_path, {"openapi.json": json.dumps(doc)})
        assert ports[0]["additionalProperties"]["operationCount"] == "3", \
            "`parameters` is not an operation"

    def test_no_operation_names_or_schemas_are_retained(self, tmp_path):
        """The whole point of the coarse tier. If a signature leaks into the
        port, we have done stage-two work at stage-one cost."""
        doc = {"openapi": "3.0.0", "paths": {"/secret-endpoint": {
            "get": {"operationId": "getSecret",
                    "responses": {"200": {"description": "a schema"}}}}}}
        ports, _, _, _ = _propose(tmp_path, {"openapi.json": json.dumps(doc)})
        blob = json.dumps(ports)
        assert "secret-endpoint" not in blob and "getSecret" not in blob
        assert ports[0]["additionalProperties"]["operationCount"] == "1"

    def test_yaml_openapi_parses_too(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"openapi.yaml":
                                             "openapi: 3.0.0\npaths:\n  /a:\n    get: {}\n"})
        assert ports[0]["additionalProperties"]["operationCount"] == "1"


class TestUnknownIsNotZero:
    """None means 'not counted or unreadable'; 0 means 'counted, and none'.
    Collapsing them is the absence-looks-like-zero shape this codebase keeps
    meeting — here it would report a rich API as having no operations."""

    def test_an_unparseable_document_records_the_interface_and_says_so(self, tmp_path):
        ports, _, _, notes = _propose(tmp_path, {"openapi.json": "{not json at all"})
        assert len(ports) == 1, "the interface exists even if the count failed"
        assert "additionalProperties" not in ports[0]
        assert any("could not be parsed" in n for n in notes)

    def test_a_document_with_no_operations_counts_zero_explicitly(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"openapi.json":
                                             json.dumps({"openapi": "3.0.0", "paths": {}})})
        assert ports[0]["additionalProperties"]["operationCount"] == "0"


class TestItRidesInEgeriasExtensionPoint:
    """0735 gives SolutionPort exactly one attribute, `direction`. But
    SolutionPort is a Referenceable (§3.3b), and Referenceable carries
    `additionalProperties` as map<string,string> — which §6.4 already names as
    the documented carrier for anything not yet typed. So the count goes there,
    camelCased and stringified, and promoting it to a real attribute later is an
    upstream type change rather than a migration of ours."""

    def test_the_count_is_a_string_because_the_egeria_map_is_string_valued(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"api/x.proto": """
service S { rpc A (Q) returns (R); }
"""})
        # interfaceName rides alongside operationCount now (design §10
        # signal 3) — a declared service name is the structured, comparable
        # interface identity that signal needs.
        assert ports[0]["additionalProperties"] == {"operationCount": "1", "interfaceName": "S"}
        assert isinstance(ports[0]["additionalProperties"]["operationCount"], str)

    def test_no_invented_top_level_attribute_is_added_to_the_port(self, tmp_path):
        """A bare `operation_count` on the port would be an attribute 0735 does
        not define — publishable only by inventing type-system surface."""
        ports, _, _, _ = _propose(tmp_path, {"openapi.json":
                                             json.dumps({"paths": {"/a": {"get": {}}}})})
        assert set(ports[0]) <= {"component", "name", "direction", "protocol",
                                 "evidence", "detail", "additionalProperties"}


class TestOtherIdls:
    def test_graphql_needs_a_root_type_to_be_a_served_interface(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"schema.graphql":
                                             "type Query { user: User }\ntype User { id: ID }\n"})
        assert ports[0]["protocol"] == "GraphQL"
        assert "Query" in ports[0]["detail"]

    def test_a_graphql_fragment_of_plain_types_is_not_an_interface(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"types.graphql": "type User { id: ID }\n"})
        assert ports == []

    def test_thrift_services_are_recognised(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"svc.thrift":
                                             "service Calc {\n  i32 add(1:i32 a)\n}\n"})
        assert ports[0]["protocol"] == "Thrift"


class TestInterfaceNameIsAStructuredIdentity:
    """Design §10 signal 3 needs a comparable interface identity, not just a
    count — two components each shipping the same declared service/document
    name are jointly presenting one external interface, however they are
    laid out in the repo. Unlike operation counts, this is read from the
    exact same parse already done for counting; no second file read."""

    def test_openapi_title_is_captured(self, tmp_path):
        doc = {"openapi": "3.0.0", "info": {"title": "Payment Gateway API"},
              "paths": {"/a": {"get": {}}}}
        ports, _, _, _ = _propose(tmp_path, {"openapi.json": json.dumps(doc)})
        assert ports[0]["additionalProperties"]["interfaceName"] == "Payment Gateway API"

    def test_no_title_yields_no_interface_name(self, tmp_path):
        """Absent, not empty-string-as-a-value — an identity field with
        nothing stated is the same as not stating it, unlike a count where
        zero is itself informative."""
        doc = {"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}
        ports, _, _, _ = _propose(tmp_path, {"openapi.json": json.dumps(doc)})
        assert "interfaceName" not in ports[0].get("additionalProperties", {})

    def test_proto_service_name_is_captured(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"api/gateway.proto": """
service GatewayAPI { rpc Route (Req) returns (Res); }
"""})
        assert ports[0]["additionalProperties"]["interfaceName"] == "GatewayAPI"

    def test_multiple_proto_services_join_deterministically(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"api/x.proto": """
service Beta { rpc A (Q) returns (R); }
service Alpha { rpc B (Q) returns (R); }
"""})
        assert ports[0]["additionalProperties"]["interfaceName"] == "Alpha, Beta"

    def test_thrift_service_name_is_captured(self, tmp_path):
        ports, _, _, _ = _propose(tmp_path, {"svc.thrift":
                                             "service Calc {\n  i32 add(1:i32 a)\n}\n"})
        assert ports[0]["additionalProperties"]["interfaceName"] == "Calc"

    def test_graphql_never_gets_an_interface_name(self, tmp_path):
        """Root type names (Query/Mutation/Subscription) are near-universal
        across GraphQL schemas — treating them as a shared identity would
        claim two unrelated services present the same interface purely
        because both are GraphQL, which is the opposite of what this signal
        is for."""
        ports, _, _, _ = _propose(tmp_path, {"schema.graphql":
                                             "type Query { user: User }\ntype User { id: ID }\n"})
        assert "additionalProperties" not in ports[0]


class TestProtocolIsStillNeverGuessed:
    def test_a_bare_expose_does_not_acquire_a_protocol(self, tmp_path):
        """§5.5a(b)/finding 66: port 8080 is CONVENTIONALLY HTTP, and treating
        convention as evidence is how an unverifiable claim enters the catalog
        wearing a measured one's confidence. Unchanged by this work."""
        ports, _, _, _ = _propose(tmp_path, {"Dockerfile": "FROM x\nEXPOSE 8080\n"})
        assert ports and not ports[0]["protocol"]


class TestFastApiRouteDecoratorsFillTheStaticDocumentGap:
    """Backlog.md "interface extraction" entry, sharpened by Dan 2026-08-30:
    a FastAPI service generates its OpenAPI spec at RUNTIME from its own
    route decorators and ships no static document for `_OPENAPI_NAMES` to
    find — this codebase's own web app is exactly that case. The evidence
    already exists (code_markers.py's `fastapi-route-registration`, counted
    per component for classification); this is that count reused as an
    interface, not a second detection.
    """

    def test_a_route_count_with_no_static_document_becomes_a_port(self, tmp_path):
        comps = [_comp("svc", files=[])]
        ports, _, _, _ = _propose(
            tmp_path, {}, components=comps,
            code_marker_operations={"svc": 12},
        )
        assert len(ports) == 1
        assert ports[0]["component"] == "svc"
        assert ports[0]["protocol"] == "HTTP/REST"
        assert ports[0]["direction"] == I.DIR_INPUT_OUTPUT
        assert ports[0]["additionalProperties"]["operationCount"] == "12"

    def test_a_component_already_covered_by_a_static_document_is_not_double_counted(self, tmp_path):
        """One REST interface must not become two ports — a checked-in
        OpenAPI document is stronger, filename-attributable evidence than a
        decorator count for the same component."""
        comps = [_comp("svc", files=["svc/**"])]
        doc = {"openapi": "3.0.0", "paths": {"/a": {"get": {}}}}
        ports, _, _, _ = _propose(
            tmp_path, {"svc/openapi.json": json.dumps(doc)}, components=comps,
            code_marker_operations={"svc": 40},
        )
        assert len(ports) == 1
        assert ports[0]["additionalProperties"]["operationCount"] == "1", \
            "the static document's count wins; the decorator count is not merged in"

    def test_a_slug_with_no_matching_component_is_skipped_not_swept_in(self, tmp_path):
        """A component filtered out upstream (distillation) or that never
        existed leaves nothing to attach a port to — skipped, same as 'no
        signal, no cluster' elsewhere in this codebase."""
        ports, _, _, _ = _propose(
            tmp_path, {}, components=[],
            code_marker_operations={"code::gone": 5},
        )
        assert ports == []

    def test_a_zero_count_yields_no_port(self, tmp_path):
        comps = [_comp("svc", files=[])]
        ports, _, _, _ = _propose(
            tmp_path, {}, components=comps,
            code_marker_operations={"svc": 0},
        )
        assert ports == []

    def test_without_the_kwarg_behaviour_is_unchanged(self, tmp_path):
        """Backward compatibility: every existing caller of propose() that
        never passes code_marker_operations sees identical behaviour."""
        comps = [_comp("svc", files=[])]
        with_none = _propose(tmp_path, {}, components=comps)
        with_empty = _propose(tmp_path, {}, components=comps, code_marker_operations={})
        assert with_none == with_empty
