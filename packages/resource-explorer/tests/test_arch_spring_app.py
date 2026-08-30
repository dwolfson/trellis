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


def _profile(tmp_path, profile, name, servers="a,b", port="7443"):
    """A named profile beside the canonical `application.properties` — egeria's
    `container.application.properties` shape."""
    (tmp_path / f"{profile}.application.properties").write_text(textwrap.dedent(f"""\
        server.port={port}
        platform.name={name}
        startup.server.list={servers}
        platform.configstore.endpoint=data/servers/{{0}}/config/{{0}}.config
    """))
    return tmp_path


class TestDeploymentStyleConsolidation:
    """One platform deployed several ways is ONE component (Dan, 2026-08-29:
    *"its Native Java vs Containerized vs Choreographed containers"*).

    Measured on the real repos: egeria went from 14 deployment components to 6
    — one platform, five servers — while egeria-workspaces correctly stayed at
    two platforms, because its freshstart and quickstart declare disjoint
    server sets in separate configuration directories.
    """

    def test_two_profiles_with_the_same_servers_are_one_platform(self, tmp_path):
        _platform(tmp_path, name="Development OMAG Server Platform", servers="x,y")
        _profile(tmp_path, "container", "Containerized OMAG Server Platform", servers="x,y")
        out = spring_app.discover(str(tmp_path))
        assert len(out["platforms"]) == 1
        assert len(out["platforms"][0]["servers"]) == 2

    def test_the_merged_name_drops_the_style_adjective(self, tmp_path):
        """The tokens the declarations AGREE on are the platform; the ones they
        do not are the style adjective the merge just made redundant."""
        _platform(tmp_path, name="Development OMAG Server Platform", servers="x,y")
        _profile(tmp_path, "container", "Containerized OMAG Server Platform", servers="x,y")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["name"] == "OMAG Server Platform"

    def test_both_declarations_survive_as_paths(self, tmp_path):
        """A merge must not lose the file a reader would open."""
        _platform(tmp_path, name="Development OMAG Server Platform", servers="x,y")
        _profile(tmp_path, "container", "Containerized OMAG Server Platform", servers="x,y")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["paths"] == [
            "application.properties", "container.application.properties"]

    def test_different_server_sets_are_different_platforms(self, tmp_path):
        """egeria-workspaces: freshstart declares fs-*, quickstart declares qs-*."""
        (tmp_path / "fs").mkdir(); (tmp_path / "qs").mkdir()
        _profile(tmp_path / "fs", "freshstart", "Freshstart Platform", servers="fs-store,fs-view")
        _profile(tmp_path / "qs", "quickstart", "Quickstart Platform", servers="qs-store,qs-view")
        assert len(spring_app.discover(str(tmp_path))["platforms"]) == 2

    def test_same_servers_in_different_directories_do_not_merge(self, tmp_path):
        """The rule is (directory, server set), not server set alone. Two
        deployments can legitimately run the same server names."""
        (tmp_path / "a").mkdir(); (tmp_path / "b").mkdir()
        _platform(tmp_path / "a", name="Alpha", servers="x,y")
        _platform(tmp_path / "b", name="Beta", servers="x,y")
        assert len(spring_app.discover(str(tmp_path))["platforms"]) == 2

    def test_a_declaration_with_no_servers_and_no_name_is_not_a_platform(self, tmp_path):
        """egeria's `test.application.properties` has an empty
        `startup.server.list` and no `platform.name`, and became a component
        called `test` off its own filename."""
        _platform(tmp_path, name="Real Platform", servers="x")
        (tmp_path / "test.application.properties").write_text("startup.server.list=\n")
        out = spring_app.discover(str(tmp_path))
        assert [p["name"] for p in out["platforms"]] == ["Real Platform"]
        assert any("is a variant of the `application.properties` beside it" in n
                   for n in out["notes"])

    def test_a_named_platform_with_no_servers_is_still_a_platform(self, tmp_path):
        """Only the BOTH case is dropped. Someone who wrote a platform.name
        declared a platform, even if its startup list is empty."""
        (tmp_path / "application.properties").write_text(
            "platform.name=Empty But Named\nstartup.server.list=\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "Empty But Named"]

    def test_the_merge_note_names_what_it_merged(self, tmp_path):
        _platform(tmp_path, name="Development OMAG Server Platform", servers="x,y")
        _profile(tmp_path, "container", "Containerized OMAG Server Platform", servers="x,y")
        note = " ".join(spring_app.discover(str(tmp_path))["notes"])
        assert "Development OMAG Server Platform" in note
        assert "Containerized OMAG Server Platform" in note
        assert "identical server sets" in note


class TestDeploymentStyle:
    def test_the_bare_properties_file_is_native_java(self, tmp_path):
        assert spring_app.discover(str(_platform(tmp_path)))["platforms"][0]["styles"] == [
            spring_app.STYLE_NATIVE]

    def test_a_ci_workflow_substitution_makes_a_profile_containerized(self, tmp_path):
        """egeria's release workflow does `cp -f container.application.properties
        .../assembly/platform/application.properties` before `docker build`, so
        the image's application.properties IS container.application.properties."""
        _platform(tmp_path, name="Development Platform", servers="x")
        _profile(tmp_path, "container", "Containerized Platform", servers="x")
        wf = tmp_path / ".github" / "workflows"; wf.mkdir(parents=True)
        (wf / "release.yml").write_text(
            "run: cp -f container.application.properties ./assembly/platform/application.properties\n")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["styles"] == [
            spring_app.STYLE_CONTAINERIZED, spring_app.STYLE_NATIVE]

    def test_a_compose_reference_makes_a_profile_choreographed(self, tmp_path):
        """Matched on a path SUBSTRING: egeria-workspaces choreographs from
        `compose-configs/egeria-freshstart/egeria-freshstart.yaml`, which no
        `docker-compose.yml` filename test reaches."""
        (tmp_path / "rt").mkdir()
        _profile(tmp_path / "rt", "quickstart", "Quickstart Platform", servers="x")
        cc = tmp_path / "compose-configs"; cc.mkdir()
        (cc / "egeria-quickstart.yaml").write_text(
            "volumes:\n  - ./quickstart.application.properties:/app/application.properties\n")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["styles"] == [
            spring_app.STYLE_CHOREOGRAPHED]

    def test_the_substitution_destination_is_not_styled(self, tmp_path):
        """`application.properties` is what every build WRITES. Styling it would
        style the platform's canonical file after whichever workflow was read
        first, which is order-dependent and wrong."""
        _platform(tmp_path, name="Development Platform", servers="x")
        wf = tmp_path / ".github" / "workflows"; wf.mkdir(parents=True)
        (wf / "release.yml").write_text(
            "run: cp -f container.application.properties ./assembly/application.properties\n")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["styles"] == [
            spring_app.STYLE_NATIVE]

    def test_an_unrecognised_profile_has_no_style_rather_than_a_guessed_one(self, tmp_path):
        _profile(tmp_path, "weird", "Weird Platform", servers="x")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["styles"] == []


class TestMergeDoesNotDuplicateInterfaces:
    """Wires and ports are built per DECLARATION, so a merge leaves one copy per
    profile — measured on egeria, 8 distinct ports arrived as 16 rows, each
    exactly doubled, and `to_ir` lands them all on the same server slug."""

    def test_ports_are_deduplicated_across_merged_profiles(self, tmp_path):
        cfg = {"omagserverConfig": {"repositoryServicesConfig": {"auditLogConnections": [
            {"embeddedConnections": [{"embeddedConnection": {"connection": {
                "connectorType": {"connectorProviderClassName": "x.KafkaOpenMetadataTopicProvider"},
                "endpoint": {"networkAddress": "egeria.audit-logs"}}}}]}]}}}
        for profile, name in ((None, "Development Platform"), ("container", "Containerized Platform")):
            store = tmp_path / "data" / "servers" / "x" / "config"
            store.mkdir(parents=True, exist_ok=True)
            (store / "x.config").write_text(json.dumps(cfg))
            if profile is None:
                _platform(tmp_path, name=name, servers="x")
            else:
                _profile(tmp_path, profile, name, servers="x")
        out = spring_app.discover(str(tmp_path))
        assert len(out["platforms"]) == 1
        keys = [(p["component"], p["name"]) for p in out["ports"]]
        # Guard the guard: an empty list satisfies a uniqueness assertion, so
        # this test passed vacuously until the fixture used `networkAddress`.
        assert keys, "fixture produced no ports — the test would pass vacuously"
        assert len(keys) == len(set(keys)), f"duplicated ports: {keys}"

    def test_wires_point_at_the_surviving_platform(self, tmp_path):
        """`to_ir` attributes a wire by its platform name, so a stale name from
        a merged-away declaration produces an edge attached to nothing."""
        _platform(tmp_path, name="Development OMAG Server Platform", servers="x",
                  extra="platform.databaseURL=jdbc:postgresql://db:5432/egeria")
        _profile(tmp_path, "container", "Containerized OMAG Server Platform", servers="x")
        out = spring_app.discover(str(tmp_path))
        live = {p["name"] for p in out["platforms"]}
        assert live == {"OMAG Server Platform"}
        assert out["wires"], "fixture produced no wires — the test would pass vacuously"
        assert all(w["platform"] in live for w in out["wires"]), out["wires"]


class TestNonEgeriaFrameworks:
    """Validation against JVM projects nobody designed these rules around.

    Pulled 2026-08-29 because every rule here had been measured on exactly two
    repos, both Egeria. `apache/polaris` (Quarkus) found a real defect in the
    day-old no-servers-and-no-name rule; `open-metadata/OpenMetadata`
    (Dropwizard) found a coverage boundary and is correctly silent.
    """

    def test_a_quarkus_application_is_a_platform_with_no_servers(self, tmp_path):
        """`quarkus.application.name` names the process exactly as
        `spring.application.name` does. Polaris declares two applications and
        no `startup.server.list`, and the no-servers-and-no-name rule dropped
        BOTH until `_NAME_KEYS` grew a row — 2 real components read as 0.

        No servers is a legitimate shape, not a failed read: Egeria's
        several-servers-in-one-process has no Quarkus equivalent.
        """
        (tmp_path / "application.properties").write_text(
            "quarkus.application.name=Apache Polaris Server\n"
            "quarkus.container-image.name=polaris\n")
        out = spring_app.discover(str(tmp_path))
        assert [p["name"] for p in out["platforms"]] == ["Apache Polaris Server"]
        assert out["platforms"][0]["servers"] == []

    def test_two_quarkus_modules_stay_two_applications(self, tmp_path):
        """Polaris' server and admin tool are peers in separate `runtime/`
        modules. The directory half of the merge key is what keeps them apart —
        both declare zero servers, so server-set equality alone would have made
        them one."""
        for module, name in (("defaults", "Apache Polaris Server"),
                             ("admin", "Apache Polaris Admin Tool")):
            d = tmp_path / "runtime" / module / "src" / "main" / "resources"
            d.mkdir(parents=True)
            (d / "application.properties").write_text(f"quarkus.application.name={name}\n")
        assert sorted(p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]) == [
            "Apache Polaris Admin Tool", "Apache Polaris Server"]

    def test_platform_name_outranks_the_framework_name(self, tmp_path):
        """Where both exist, an Egeria platform hosting servers is a different
        thing from the framework's name for the process."""
        (tmp_path / "application.properties").write_text(
            "platform.name=OMAG Server Platform\n"
            "spring.application.name=omag-server-platform\n"
            "startup.server.list=x\n")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["name"] == "OMAG Server Platform"

    def test_a_repo_configured_in_yaml_declares_nothing(self, tmp_path):
        """OpenMetadata is Dropwizard: `conf/openmetadata.yaml`, no
        `*application.properties` anywhere. Silence is the correct answer and
        the coverage boundary is worth stating — this reads properties files,
        not every JVM configuration format."""
        (tmp_path / "conf").mkdir()
        (tmp_path / "conf" / "openmetadata.yaml").write_text("server:\n  port: 8585\n")
        assert spring_app.discover(str(tmp_path))["platforms"] == []


class TestProfileOverlays:
    """Spring's OWN convention, `application-{profile}.properties`, which the
    original `endswith("application.properties")` test could not see — this
    module read Egeria's non-standard PREFIX form and was blind to the
    framework's documented one. `apache/polaris` carries two we never saw.

    An overlay is a different RELATIONSHIP from a prefix file, not just a
    different spelling: Spring merges it onto the base at runtime, where
    egeria's CI copies `container.application.properties` OVER the base at
    build time. Merged means always the same platform; replaced needs the
    directory + server-set test.
    """

    def test_a_profile_overlay_is_discovered_at_all(self, tmp_path):
        _platform(tmp_path, name="App", servers="x")
        (tmp_path / "application-prod.properties").write_text("server.port=9090\n")
        assert "application-prod.properties" in spring_app._properties_files(str(tmp_path))

    def test_an_overlay_is_not_a_platform(self, tmp_path):
        _platform(tmp_path, name="App", servers="x")
        (tmp_path / "application-prod.properties").write_text("server.port=9090\n")
        out = spring_app.discover(str(tmp_path))
        assert [p["name"] for p in out["platforms"]] == ["App"]

    def test_an_overlay_becomes_an_environment_of_its_base(self, tmp_path):
        _platform(tmp_path, name="App", servers="x")
        for profile in ("dev", "prod"):
            (tmp_path / f"application-{profile}.properties").write_text("server.port=9090\n")
        assert spring_app.discover(str(tmp_path))["platforms"][0]["environments"] == ["dev", "prod"]

    def test_environment_is_not_folded_into_deployment_style(self, tmp_path):
        """`dev`/`prod` name WHERE something runs; Native Java / Containerized /
        Choreographed name HOW it is packaged. Folding one into the other is the
        mistake that made 'Development OMAG Server Platform' look like a
        platform — an environment adjective mistaken for an identity."""
        _platform(tmp_path, name="App", servers="x")
        (tmp_path / "application-prod.properties").write_text("server.port=9090\n")
        plat = spring_app.discover(str(tmp_path))["platforms"][0]
        assert plat["styles"] == [spring_app.STYLE_NATIVE]
        assert "prod" not in plat["styles"]

    def test_an_overlay_never_triggers_the_merge_test(self, tmp_path):
        """Merged means unconditionally the same platform. An overlay declaring
        a DIFFERENT server list must still not become a second platform — it
        would under the directory + server-set rule, which is why overlays are
        set aside before that rule ever sees them."""
        _platform(tmp_path, name="App", servers="x")
        (tmp_path / "application-prod.properties").write_text(
            "startup.server.list=totally,different\n")
        out = spring_app.discover(str(tmp_path))
        assert len(out["platforms"]) == 1
        assert [s["name"] for s in out["platforms"][0]["servers"]] == ["x"]

    def test_an_overlay_overriding_servers_is_reported_not_swallowed(self, tmp_path):
        """Per-environment server lists are a real thing the model has no place
        for. Saying so beats silently keeping the base's reading."""
        _platform(tmp_path, name="App", servers="x")
        (tmp_path / "application-prod.properties").write_text(
            "startup.server.list=totally,different\n")
        assert any("per-environment server lists are not modelled" in n
                   for n in spring_app.discover(str(tmp_path))["notes"])

    def test_an_orphan_overlay_is_reported(self, tmp_path):
        """An overlay with no base beside it has nothing to vary."""
        (tmp_path / "application-prod.properties").write_text("server.port=9090\n")
        out = spring_app.discover(str(tmp_path))
        assert out["platforms"] == []
        assert any("have no base application config beside them" in n for n in out["notes"])

    def test_the_prefix_form_is_still_a_replacement_not_an_overlay(self, tmp_path):
        """`container.application.properties` must keep going through the merge
        test — it is copied OVER the base, not merged onto it."""
        _platform(tmp_path, name="Development Platform", servers="x,y")
        _profile(tmp_path, "container", "Containerized Platform", servers="x,y")
        out = spring_app.discover(str(tmp_path))
        assert len(out["platforms"]) == 1
        assert out["platforms"][0].get("environments") is None
        assert out["platforms"][0]["paths"] == [
            "application.properties", "container.application.properties"]


class TestValidationAgainstThreeSpringProjects:
    """Three defects found by running spring-petclinic, apache/atlas and
    spring-cloud-dataflow on 2026-08-29. Each was invisible on the Egeria
    family, and each is a rule that generalised from too few examples.
    """

    def test_an_app_that_names_itself_nothing_is_still_an_app(self, tmp_path):
        """spring-petclinic is the canonical Spring Boot application and yielded
        ZERO platforms: it never sets `spring.application.name`, because most
        Spring Boot apps have no reason to. The no-name-and-no-servers drop was
        derived from one example (egeria's `test.application.properties`)."""
        d = tmp_path / "src" / "main" / "resources"; d.mkdir(parents=True)
        (d / "application.properties").write_text("spring.jpa.open-in-view=false\n")
        assert len(spring_app.discover(str(tmp_path))["platforms"]) == 1

    def test_a_prefix_file_with_no_sibling_base_is_its_own_app(self, tmp_path):
        """`atlas-application.properties` is Atlas's OWN config, not a variant of
        anything — there is no `application.properties` beside it. Same form as
        egeria's `container.` prefix, opposite meaning, and the sibling is what
        tells them apart without a vocabulary of known prefixes."""
        d = tmp_path / "distro" / "src" / "conf"; d.mkdir(parents=True)
        (d / "atlas-application.properties").write_text("atlas.graph.storage.backend=hbase\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == ["atlas"]

    def test_a_prefix_file_WITH_a_sibling_base_is_still_dropped(self, tmp_path):
        """The drop has to keep working where it was earned — egeria's
        `test.application.properties` sits beside a real base."""
        _platform(tmp_path, name="Real", servers="x")
        (tmp_path / "test.application.properties").write_text("startup.server.list=\n")
        out = spring_app.discover(str(tmp_path))
        assert [p["name"] for p in out["platforms"]] == ["Real"]
        assert any("is a variant of the `application.properties` beside it" in n
                   for n in out["notes"])

    def test_test_resources_are_fixtures_not_deployments(self, tmp_path):
        """apache/atlas carries 11 of its 20 properties files under a test path;
        spring-cloud-dataflow 3 of 8. This module already learned this for
        `.config` files and did not apply it here."""
        d = tmp_path / "src" / "test" / "resources"; d.mkdir(parents=True)
        (d / "atlas-application.properties").write_text("atlas.x=1\n")
        assert spring_app.discover(str(tmp_path))["platforms"] == []

    def test_a_spring_placeholder_resolves_to_its_default(self, tmp_path):
        """spring-cloud-dataflow proposed two platforms literally named
        `${vcap.application.name:spring-cloud-dataflow-tasklauncher-sink}` — a
        raw placeholder with its own default sitting unread inside it."""
        (tmp_path / "application.properties").write_text(
            "spring.application.name=${vcap.application.name:tasklauncher-sink}\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "tasklauncher-sink"]

    def test_a_placeholder_resolves_against_its_own_file_first(self, tmp_path):
        (tmp_path / "application.properties").write_text(
            "app.id=real-name\nspring.application.name=${app.id:fallback}\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "real-name"]

    def test_an_unresolvable_placeholder_is_not_used_as_a_name(self, tmp_path):
        """No default, no local value — so it is not a name, and the module
        fallback is used instead of putting a literal `${...}` in the catalog."""
        (tmp_path / "application.properties").write_text(
            "spring.application.name=${vcap.application.name}\n")
        names = [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]]
        assert names and "${" not in names[0]

    def test_two_platforms_may_not_share_a_name(self, tmp_path):
        """A name becomes a SLUG, so duplicates collapse distinct components onto
        one scope_locator — silently, producing a catalog that is confidently
        wrong. Atlas had six modules all named `atlas`; dataflow had two modules
        whose DECLARED names resolved to the same default."""
        for module in ("couchbase-bridge", "falcon-bridge"):
            d = tmp_path / "addons" / module / "src" / "main" / "resources"
            d.mkdir(parents=True)
            (d / "atlas-application.properties").write_text("atlas.x=1\n")
        names = [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]]
        assert sorted(names) == ["couchbase-bridge", "falcon-bridge"]
        assert len(names) == len(set(names))

    def test_the_disambiguation_is_reported(self, tmp_path):
        for module in ("a-bridge", "b-bridge"):
            d = tmp_path / module / "src" / "main" / "resources"; d.mkdir(parents=True)
            (d / "atlas-application.properties").write_text("atlas.x=1\n")
        assert any("qualified by build module" in n
                   for n in spring_app.discover(str(tmp_path))["notes"])

    def test_a_module_name_comes_from_the_build_module_not_the_resources_dir(self, tmp_path):
        d = tmp_path / "composed-task-runner" / "src" / "main" / "resources"
        d.mkdir(parents=True)
        (d / "application.properties").write_text("server.port=8080\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "composed-task-runner"]


class TestYamlConfig:
    """`application.yml`/`.yaml`, closed 2026-08-29.

    Measured before it existed: `spring-cloud-dataflow` carried **15 YAML config
    files against 5 properties files**, so about a third of its configuration
    was read. Closing it took dataflow from 5 platforms to 9 and found a Spring
    Boot k8s operator inside `open-metadata/OpenMetadata`, which had reported
    zero because its main server is Dropwizard.

    The design is a flattener, not a parallel code path: nested YAML becomes the
    same dotted-key dict `_read_properties` returns, so `_NAME_KEYS`,
    `_ENDPOINT_KEY_HINTS`, `_PORT_KEY` and `_SUBCOMPONENT_KEYS` all work
    unchanged.
    """

    def test_nested_yaml_flattens_to_the_dotted_keys_everything_else_reads(self, tmp_path):
        (tmp_path / "application.yml").write_text(
            "spring:\n  application:\n    name: My Service\nserver:\n  port: 8080\n")
        plat = spring_app.discover(str(tmp_path))["platforms"][0]
        assert plat["name"] == "My Service"
        assert plat["port"] == "8080"

    def test_yaml_and_yml_are_both_read(self, tmp_path):
        (tmp_path / "svc").mkdir()
        (tmp_path / "svc" / "application.yaml").write_text(
            "spring:\n  application:\n    name: Yaml Service\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "Yaml Service"]

    def test_a_scalar_list_joins_the_way_its_consumer_splits_it(self, tmp_path):
        """`startup.server.list` is read with `.split(",")`, so a YAML sequence
        has to arrive comma-joined to reach it."""
        (tmp_path / "application.yml").write_text(
            "platform:\n  name: P\nstartup:\n  server:\n    list:\n      - one\n      - two\n")
        servers = spring_app.discover(str(tmp_path))["platforms"][0]["servers"]
        assert [s["name"] for s in servers] == ["one", "two"]

    def test_a_yaml_endpoint_is_still_an_endpoint(self, tmp_path):
        (tmp_path / "application.yml").write_text(
            "spring:\n  application:\n    name: S\n  datasource:\n"
            "    url: jdbc:postgresql://db:5432/app\n")
        out = spring_app.discover(str(tmp_path))
        assert [w["target"] for w in out["wires"]] == ["PostgreSQL"]

    def test_a_yaml_profile_overlay_is_an_environment(self, tmp_path):
        (tmp_path / "application.yml").write_text("spring:\n  application:\n    name: S\n")
        (tmp_path / "application-prod.yml").write_text("server:\n  port: 9090\n")
        plat = spring_app.discover(str(tmp_path))["platforms"][0]
        assert plat["environments"] == ["prod"]
        assert plat["name"] == "S"

    def test_an_in_file_profile_section_does_not_pollute_the_base(self, tmp_path):
        """A `---` document activating a profile is the in-file equivalent of an
        overlay file. Merging it into the base would apply prod-only config to
        the default reading, silently.

        Precautionary: no file in the corpus uses this, so it is guarded by a
        test rather than by a measurement.
        """
        (tmp_path / "application.yml").write_text(
            "spring:\n  application:\n    name: Base Name\n"
            "---\n"
            "spring:\n  config:\n    activate:\n      on-profile: prod\n"
            "  application:\n    name: Prod Name\n")
        plat = spring_app.discover(str(tmp_path))["platforms"][0]
        assert plat["name"] == "Base Name"
        assert plat["environments"] == ["prod"]

    def test_a_maven_filter_token_is_not_a_name(self, tmp_path):
        """spring-cloud-dataflow's `application.yml` carries
        `name: "@project.artifactId@"` — substituted from the POM at build time,
        so a checkout holds the token verbatim. A token is not a name, for the
        same reason an unresolved `${...}` is not."""
        d = tmp_path / "my-module" / "src" / "main" / "resources"; d.mkdir(parents=True)
        (d / "application.yml").write_text(
            'spring:\n  application:\n    name: "@project.artifactId@"\n')
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == [
            "my-module"]

    def test_malformed_yaml_declares_nothing_and_says_so(self, tmp_path):
        """UNREADABLE is not EMPTY. Returning `{}` for both made a malformed file
        propose a platform named after its own directory — a component invented
        from a parse failure."""
        (tmp_path / "application.yml").write_text("spring: [unclosed\n")
        out = spring_app.discover(str(tmp_path))
        assert out["platforms"] == []
        assert any("could not be parsed" in n for n in out["notes"])

    def test_an_empty_config_still_marks_its_module_as_an_application(self, tmp_path):
        """The other half of the same distinction: a Spring app may legitimately
        ship a near-empty `application.properties`."""
        d = tmp_path / "svc" / "src" / "main" / "resources"; d.mkdir(parents=True)
        (d / "application.properties").write_text("")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == ["svc"]

    def test_a_yaml_base_counts_as_the_sibling_for_a_variant(self, tmp_path):
        """`_is_variant_of_base` has to accept any of the three base names, or a
        prefix variant beside a YAML base reads as its own application."""
        (tmp_path / "application.yml").write_text("spring:\n  application:\n    name: Base\n")
        (tmp_path / "test.application.properties").write_text("startup.server.list=\n")
        assert [p["name"] for p in spring_app.discover(str(tmp_path))["platforms"]] == ["Base"]
