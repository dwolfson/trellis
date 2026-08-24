"""Ports and wires from deployment artifacts (design §5.5f).

Regression tests for `arch_recovery/interfaces.py`. Hermetic — small synthetic
trees in tmp_path, never the real repos or the pre-registered fixtures.
"""
from __future__ import annotations

import os

import pytest

from resource_explorer.surveyors.arch_recovery import interfaces
from resource_explorer.surveyors.arch_recovery.ir import Component, Identity


def _write(root, rel, content=""):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)
    return rel


def _comp(name, glob, ctype="Software Library"):
    return Component(slug=name, name=name, type=ctype,
                     identity=Identity("module-path", name), files=[glob])


class TestDockerfilePorts:
    def test_expose_becomes_an_inbound_port(self, tmp_path):
        root = str(tmp_path)
        _write(root, "svc/Dockerfile", "FROM x\nEXPOSE 8080/tcp\n")
        ports, _, _, _ = interfaces.propose(root, ["svc/Dockerfile"], [_comp("svc", "svc/**")])
        assert len(ports) == 1
        assert ports[0]["component"] == "svc"
        assert ports[0]["name"] == "8080"
        assert ports[0]["direction"] == interfaces.DIR_INPUT
        assert ports[0]["protocol"] == "tcp"

    def test_protocol_is_never_guessed_from_the_port_number(self, tmp_path):
        """Port 8080 is *conventionally* HTTP. Treating convention as evidence
        is how an unverifiable claim enters the catalog wearing a measured
        claim's confidence — the failure finding 66 turns on."""
        root = str(tmp_path)
        _write(root, "svc/Dockerfile", "FROM x\nEXPOSE 8080\n")
        ports, _, _, _ = interfaces.propose(root, ["svc/Dockerfile"], [_comp("svc", "svc/**")])
        assert ports[0]["protocol"] == ""

    def test_identical_ports_are_deduplicated(self, tmp_path):
        root = str(tmp_path)
        _write(root, "svc/Dockerfile", "FROM x\nEXPOSE 9090\n")
        _write(root, "svc/Dockerfile.debug", "FROM x\nEXPOSE 9090\n")
        files = ["svc/Dockerfile", "svc/Dockerfile.debug"]
        ports, _, _, _ = interfaces.propose(root, files, [_comp("svc", "svc/**")])
        assert len(ports) == 1, "one port declared twice is one fact, not two"


class TestComposeInterfaces:
    def _compose(self, tmp_path):
        root = str(tmp_path)
        _write(root, "docker-compose.yml",
               "services:\n"
               "  web:\n"
               "    ports:\n"
               "      - '8443:443'\n"
               "    depends_on:\n"
               "      - api\n"
               "  api:\n"
               "    expose:\n"
               "      - '5000'\n")
        return root

    def test_published_and_internal_ports_are_both_inbound(self, tmp_path):
        root = self._compose(tmp_path)
        ports, _, _, _ = interfaces.propose(root, ["docker-compose.yml"], [])
        by_name = {p["name"]: p for p in ports}
        assert set(by_name) == {"443", "5000"}
        assert all(p["direction"] == interfaces.DIR_INPUT for p in ports)

    def test_the_container_side_port_is_recorded_not_the_host_side(self, tmp_path):
        """`8443:443` means the component serves on 443; 8443 is where the host
        happens to publish it."""
        root = self._compose(tmp_path)
        ports, _, _, _ = interfaces.propose(root, ["docker-compose.yml"], [])
        assert "443" in {p["name"] for p in ports}
        assert "8443" not in {p["name"] for p in ports}

    def test_depends_on_becomes_a_one_way_wire(self, tmp_path):
        root = self._compose(tmp_path)
        _, wires, _, _ = interfaces.propose(root, ["docker-compose.yml"], [])
        assert len(wires) == 1
        w = wires[0]
        assert (w["source"], w["target"]) == ("web", "api")
        assert w["oneWay"] is True, "depends_on states ordering, not that traffic returns"
        assert w["frequency"] == "" and w["dataExchanged"] == "", "never invented"


class TestOpenApi:
    def test_an_openapi_document_earns_the_strong_direction(self, tmp_path):
        """§3.2: `Input-Output` is request-response *provided*. An OpenAPI
        document is a direct statement that the component serves one — the one
        place the strong value is warranted without inference."""
        root = str(tmp_path)
        _write(root, "api/openapi.yaml", "openapi: 3.0.0\n")
        ports, _, _, _ = interfaces.propose(root, ["api/openapi.yaml"], [_comp("api", "api/**")])
        assert ports[0]["direction"] == interfaces.DIR_INPUT_OUTPUT
        assert ports[0]["protocol"] == "HTTP/REST"


class TestAttribution:
    def test_a_whole_repo_candidate_never_owns_a_port(self, tmp_path):
        """The coupling proposer emits a root `.` candidate on every target.
        Matching every path, it would capture every port."""
        root = str(tmp_path)
        _write(root, "svc/Dockerfile", "FROM x\nEXPOSE 8080\n")
        comps = [_comp(".", "*"), _comp("svc", "svc/**")]
        ports, _, _, _ = interfaces.propose(root, ["svc/Dockerfile"], comps)
        assert ports[0]["component"] == "svc"

    def test_a_root_artifact_goes_to_the_sole_entry_point(self, tmp_path):
        root = str(tmp_path)
        _write(root, "Dockerfile", "FROM x\nEXPOSE 9090\n")
        comps = [_comp("server", "cmd/server/**", ctype="Console Command")]
        ports, _, _, _ = interfaces.propose(root, ["Dockerfile"], comps)
        assert ports[0]["component"] == "server"

    def test_a_root_artifact_with_several_entry_points_is_not_guessed(self, tmp_path):
        """Prometheus's case: several binaries, so a root Dockerfile is
        genuinely ambiguous. Falling back to repo level is honest; picking one
        would be a guess wearing evidence's clothes."""
        root = str(tmp_path)
        _write(root, "Dockerfile", "FROM x\nEXPOSE 9090\n")
        comps = [_comp("a", "cmd/a/**", ctype="Console Command"),
                 _comp("b", "cmd/b/**", ctype="Console Command")]
        ports, _, _, _ = interfaces.propose(root, ["Dockerfile"], comps)
        assert ports[0]["component"] not in ("a", "b")


def test_no_deployment_artifacts_is_a_note_not_an_error(tmp_path):
    root = str(tmp_path)
    _write(root, "src/lib.go", "package lib\n")
    ports, wires, _, notes = interfaces.propose(root, ["src/lib.go"], [])
    assert ports == [] and wires == []
    assert any("no ports or wires" in n for n in notes)
