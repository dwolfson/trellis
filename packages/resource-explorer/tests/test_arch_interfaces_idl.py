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


def _propose(tmp_path, files: dict, components=None):
    for rel, body in files.items():
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return I.propose(str(tmp_path), list(files), components or [])


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
        assert ports[0]["additionalProperties"] == {"operationCount": "1"}
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


class TestProtocolIsStillNeverGuessed:
    def test_a_bare_expose_does_not_acquire_a_protocol(self, tmp_path):
        """§5.5a(b)/finding 66: port 8080 is CONVENTIONALLY HTTP, and treating
        convention as evidence is how an unverifiable claim enters the catalog
        wearing a measured one's confidence. Unchanged by this work."""
        ports, _, _, _ = _propose(tmp_path, {"Dockerfile": "FROM x\nEXPOSE 8080\n"})
        assert ports and not ports[0]["protocol"]
