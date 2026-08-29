"""Spring application discovery (arch_recovery/spring_app.py).

The case: Egeria is one Spring process hosting several logical servers that
talk over REST and Kafka. Before this, wire discovery read only compose files
(egeria: zero wires) and component discovery read Java module paths (235
components where the deployment architecture has one platform and five
servers). Both readings are true — they are different §4.1 perspectives — but
only one of them clusters into something a curator can read.
"""
from __future__ import annotations

import json
import textwrap

import pytest

from resource_explorer.surveyors.arch_recovery import clustering, spring_app


def _platform(tmp_path, name="Test Platform", servers="a,b", port="7443", extra=""):
    (tmp_path / "application.properties").write_text(textwrap.dedent(f"""\
        server.port={port}
        platform.name={name}
        startup.server.list={servers}
        platform.configstore.endpoint=data/servers/{{0}}/config/{{0}}.config
        {extra}
    """))
    return tmp_path


class TestPlatformDiscovery:
    def test_a_repo_with_no_properties_declares_nothing(self, tmp_path):
        assert spring_app.discover(str(tmp_path)) == {"platforms": [], "wires": [],
                                                      "ports": [], "notes": []}

    def test_the_platform_and_its_port_are_read(self, tmp_path):
        out = spring_app.discover(str(_platform(tmp_path)))
        assert len(out["platforms"]) == 1
        assert out["platforms"][0]["name"] == "Test Platform"
        assert out["platforms"][0]["port"] == "7443"

    def test_servers_come_from_the_startup_list(self, tmp_path):
        out = spring_app.discover(str(_platform(tmp_path, servers="one,two,three")))
        assert [s["name"] for s in out["platforms"][0]["servers"]] == ["one", "two", "three"]

    def test_a_server_with_no_config_is_still_a_declared_server(self, tmp_path):
        """In a checkout the config store is EMPTY — server configs are runtime
        state the platform writes. The startup list is the declaration; an
        earlier version required a config document and would have proposed
        nothing at all for a real repo."""
        out = spring_app.discover(str(_platform(tmp_path)))
        servers = out["platforms"][0]["servers"]
        assert len(servers) == 2
        assert all(s["config_source"] == "" for s in servers)

    def test_several_platforms_in_one_repo_are_all_found(self, tmp_path):
        """egeria-workspaces declares freshstart and quickstart; egeria declares
        development, containerized and test."""
        (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
        _platform(tmp_path / "a", name="Alpha", servers="x")
        _platform(tmp_path / "b", name="Beta", servers="y")
        out = spring_app.discover(str(tmp_path))
        assert {p["name"] for p in out["platforms"]} == {"Alpha", "Beta"}
        assert any("2 platforms declared" in n for n in out["notes"])

    def test_the_notes_say_an_environment_may_span_repos(self, tmp_path):
        """Egeria is distributed and federated — an environment can consist of
        platforms this repo does not contain, which no repo-scoped analysis
        can see."""
        (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
        _platform(tmp_path / "a", name="Alpha"); _platform(tmp_path / "b", name="Beta")
        assert any("declared elsewhere" in n for n in spring_app.discover(str(tmp_path))["notes"])


class TestDeclaredEndpoints:
    def test_a_jdbc_url_names_a_third_party_component(self, tmp_path):
        root = _platform(tmp_path, extra="spring.datasource.url=jdbc:postgresql://db:5432/x")
        eps = spring_app.discover(str(root))["platforms"][0]["endpoints"]
        assert any(e["target"] == "PostgreSQL" and e["protocol"] == "JDBC" for e in eps)

    def test_an_unresolved_placeholder_is_not_recorded_as_an_endpoint(self, tmp_path):
        """Recording `~{egeriaEndpoint}~` would put the template in the catalog."""
        root = _platform(tmp_path, extra="spring.datasource.url=~{missingVar}~")
        out = spring_app.discover(str(root))
        assert out["platforms"][0]["endpoints"] == []
        assert any("unresolved placeholder" in n for n in out["notes"])

    def test_a_placeholder_resolves_from_its_own_declaration_block(self, tmp_path):
        extra = ('platform.placeholder.variables={"dbURL":"jdbc:postgresql://h:5432/e"}\n'
                 'repositoryDatabaseURL=~{dbURL}~')
        eps = spring_app.discover(str(_platform(tmp_path, extra=extra)))["platforms"][0]["endpoints"]
        assert any(e["target"] == "PostgreSQL" for e in eps)

    def test_a_bare_host_port_names_no_component(self, tmp_path):
        """`host:9092` has no scheme. Inferring "that's Kafka" from the property
        NAME would be the similarity guessing this module exists to avoid."""
        root = _platform(tmp_path, extra="spring.kafka.bootstrap-servers=broker:9092")
        eps = spring_app.discover(str(root))["platforms"][0]["endpoints"]
        assert [e["target"] for e in eps] == [""]
        assert eps[0]["protocol"] == "TCP"


class TestServerConfigAndProvenance:
    def _with_config(self, tmp_path, name, block, target=None):
        d = tmp_path / "data" / "servers" / name / "config"
        d.mkdir(parents=True)
        cfg = {"localServerName": name, block: {}}
        if target:
            cfg[block] = {"omagserverName": target}
        (d / f"{name}.config").write_text(json.dumps(cfg))

    def test_a_deployment_config_gives_the_kind_and_is_labelled_as_such(self, tmp_path):
        root = _platform(tmp_path, servers="vs")
        self._with_config(tmp_path, "vs", "viewServicesConfig")
        server = spring_app.discover(str(root))["platforms"][0]["servers"][0]
        assert server["kind"] == "View Server"
        assert server["config_source"] == spring_app.CONFIG_SOURCE_DEPLOYMENT

    def test_a_wire_between_declared_servers_is_proposed(self, tmp_path):
        root = _platform(tmp_path, servers="daemon,store")
        self._with_config(tmp_path, "daemon", "dynamicIntegrationGroupsConfig", target="store")
        self._with_config(tmp_path, "store", "accessServicesConfig")
        wires = spring_app.discover(str(root))["wires"]
        assert any(w["source"] == "daemon" and w["target"] == "store"
                   and w["protocol"] == "REST" for w in wires)

    def test_a_reference_to_an_undeclared_server_is_noted_not_wired(self, tmp_path):
        root = _platform(tmp_path, servers="daemon")
        self._with_config(tmp_path, "daemon", "dynamicIntegrationGroupsConfig", target="elsewhere")
        out = spring_app.discover(str(root))
        assert out["wires"] == []
        assert any("elsewhere" in n for n in out["notes"])

    def test_a_server_naming_itself_is_not_an_edge(self, tmp_path):
        root = _platform(tmp_path, servers="solo")
        self._with_config(tmp_path, "solo", "accessServicesConfig", target="solo")
        assert spring_app.discover(str(root))["wires"] == []

    def test_the_config_store_path_is_the_declared_one_not_a_walk(self, tmp_path):
        """An earlier version walked for `*.config` and picked up eleven
        deliberately-malformed connector test fixtures. The properties file says
        where configs live; nothing else can be mistaken for one."""
        root = _platform(tmp_path, servers="vs")
        stray = tmp_path / "src" / "test" / "resources" / "vs" / "config"
        stray.mkdir(parents=True)
        (stray / "vs.config").write_text("{ this is not json")
        out = spring_app.discover(str(root))
        assert out["platforms"][0]["servers"][0]["config_source"] == ""
        assert not any("could not be read" in n for n in out["notes"])


class TestIRProjection:
    def test_servers_become_sub_components_of_their_platform(self, tmp_path):
        """A platform is a component, not a Collection: its servers share a
        process, a port and a config, and are reached THROUGH it via
        /servers/{serverName}/... — that is affinity, so composition."""
        found = spring_app.discover(str(_platform(tmp_path, name="P", servers="s1,s2")))
        components, _, _, _ = spring_app.to_ir(found)
        platform = [c for c in components if c.parent_slug == ""][0]
        servers = [c for c in components if c.parent_slug]
        assert len(servers) == 2
        assert all(s.parent_slug == platform.slug for s in servers)

    def test_components_are_in_the_deployment_perspective(self, tmp_path):
        found = spring_app.discover(str(_platform(tmp_path)))
        components, _, _, _ = spring_app.to_ir(found)
        assert {c.perspective for c in components} == {"deployment"}

    def test_a_third_party_endpoint_becomes_a_third_party_component(self, tmp_path):
        root = _platform(tmp_path, extra="spring.datasource.url=jdbc:postgresql://db:5432/x")
        components, _, _, _ = spring_app.to_ir(spring_app.discover(str(root)))
        assert any(c.type == "Third Party Process" and c.name == "PostgreSQL" for c in components)

    def test_every_component_carries_evidence(self, tmp_path):
        found = spring_app.discover(str(_platform(tmp_path, servers="a,b")))
        components, _, _, evidence = spring_app.to_ir(found)
        assert {e.subject_slug for e in evidence} == {c.slug for c in components}

    def test_the_slug_is_not_prefixed_with_the_discoverer_name(self, tmp_path):
        """A `spring::` prefix made every platform collapse into one cluster
        named after the tool — the same failure as `docker_compose::`. The first
        slug segment must be the platform's own name."""
        found = spring_app.discover(str(_platform(tmp_path, name="Alpha", servers="s")))
        components, _, _, _ = spring_app.to_ir(found)
        assert all(not c.slug.startswith("spring::") for c in components)
        assert any(c.slug == "Alpha" for c in components)

    def test_platforms_cluster_one_per_platform(self, tmp_path):
        (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
        _platform(tmp_path / "a", name="Alpha", servers="x,y")
        _platform(tmp_path / "b", name="Beta", servers="p,q")
        components, _, _, _ = spring_app.to_ir(spring_app.discover(str(tmp_path)))
        rows = [{"slug": c.slug, "scope_locator": c.slug, "perspective": c.perspective,
                 "identity": c.identity} for c in components]
        clusters = clustering.propose(rows, "deployment")
        assert {c.name for c in clusters} == {"Alpha", "Beta"}


class TestTopicPorts:
    """A Kafka topic a server publishes to or consumes from is an exposed
    surface — a PORT, not a wire to a broker. The broker is infrastructure; the
    topics are what components offer each other, and SolutionPortDirection
    already carries publish/consume."""

    def _server_with(self, tmp_path, connections):
        d = tmp_path / "data" / "servers" / "s" / "config"
        d.mkdir(parents=True)
        (d / "s.config").write_text(json.dumps({"localServerName": "s",
                                                "accessServicesConfig": connections}))
        return _platform(tmp_path, servers="s")

    def _topic(self, address, provider="o.o.KafkaOpenMetadataTopicProvider", key="accessServiceOutTopic"):
        return {key: {"endpoint": {"networkAddress": address},
                      "connectorType": {"connectorProviderClassName": provider}}}

    def test_a_kafka_topic_becomes_a_port(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("egeria.omag.server.s.omas.x.outTopic")])
        ports = spring_app.discover(str(root))["ports"]
        assert len(ports) == 1
        assert ports[0]["protocol"] == "Kafka"
        assert ports[0]["component"] == "s"

    def test_an_out_topic_is_an_output_port(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("t.outTopic")])
        assert spring_app.discover(str(root))["ports"][0]["direction"] == "Output"

    def test_an_in_topic_is_an_input_port(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("t.inTopic", key="accessServiceInTopic")])
        assert spring_app.discover(str(root))["ports"][0]["direction"] == "Input"

    def test_direction_comes_from_the_declaration_not_the_topic_name(self, tmp_path):
        """The enclosing key is the declaration; the address is a name someone
        chose and could say anything."""
        root = self._server_with(tmp_path, [self._topic("nothing-informative", key="accessServiceOutTopic")])
        assert spring_app.discover(str(root))["ports"][0]["direction"] == "Output"

    def test_a_non_topic_endpoint_is_not_a_port(self, tmp_path):
        """`endpoint.networkAddress` carries REST URLs, secrets stores and
        archive files too. Keying on the address swept in 6 non-topics out of
        14 for egeria; the connector provider is what declares the kind."""
        root = self._server_with(tmp_path, [
            self._topic("content-packs/X.omarchive",
                        provider="o.o.FileBasedOpenMetadataArchiveStoreProvider"),
            self._topic("https://host/servers/s",
                        provider="o.o.OMRSRESTRepositoryConnectorProvider"),
        ])
        assert spring_app.discover(str(root))["ports"] == []

    def test_any_topic_provider_qualifies_not_just_kafka(self, tmp_path):
        """Matched on the provider name ending, so a new topic connector is
        caught by convention rather than by an allow-list that goes stale."""
        root = self._server_with(tmp_path, [
            self._topic("mem.topic", provider="o.o.InMemoryOpenMetadataTopicProvider")])
        assert len(spring_app.discover(str(root))["ports"]) == 1

    def test_a_common_service_topic_is_marked_not_dropped(self, tmp_path):
        """FFDC is a common service present in every server by default
        (egeria-project.org/services). Its topic is a true port but an
        identical one everywhere, so a consumer wanting what DISTINGUISHES
        servers must be able to tell it apart."""
        root = self._server_with(tmp_path, [self._topic("egeria.omag.server.default.ffdc.audit-logs")])
        port = spring_app.discover(str(root))["ports"][0]
        assert port["additionalProperties"]["commonService"] == "true"

    def test_a_service_specific_topic_is_not_marked_common(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("egeria.omag.server.s.omas.x.outTopic")])
        port = spring_app.discover(str(root))["ports"][0]
        assert port["additionalProperties"]["commonService"] == "false"

    def test_a_topic_name_is_recorded_exactly_as_declared(self, tmp_path):
        """`egeria.omag.egeria.omag.server.default.ffdc.audit-logs` is not a
        doubled root: it reflects the platform, the generic server component and
        a default service. Reading it as a defect was wrong, and "correcting" a
        name that carries structure would destroy the structure."""
        declared = "egeria.omag.egeria.omag.server.default.ffdc.audit-logs"
        root = self._server_with(tmp_path, [self._topic(declared)])
        assert spring_app.discover(str(root))["ports"][0]["name"] == declared

    def test_the_same_topic_reached_twice_is_one_port(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("t.outTopic"), self._topic("t.outTopic")])
        assert len(spring_app.discover(str(root))["ports"]) == 1

    def test_ports_are_attributed_to_the_server_slug_in_the_ir(self, tmp_path):
        root = self._server_with(tmp_path, [self._topic("t.outTopic")])
        components, ports, _, _ = spring_app.to_ir(spring_app.discover(str(root)))
        server = [c for c in components if c.parent_slug][0]
        assert ports[0]["component"] == server.slug
