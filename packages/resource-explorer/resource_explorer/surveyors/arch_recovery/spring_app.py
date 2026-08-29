"""Components, ports and wires from a Spring application's own declarations.

**Why this exists.** Egeria is one Spring Boot process — the OMAG Server
Platform — inside which several logical *servers* run on threads and talk to
each other over REST and Kafka. None of that was visible: wire discovery read
only compose files, so egeria yielded **zero** wires, and component discovery
read Java module paths, proposing **235** components where the deployment
architecture has one platform and five servers.

That was never a clustering failure. It is design §4.1 in practice — a detector
working in the *physical* perspective (what is on disk) measured against ground
truth in the *deployment-specification* perspective (what the repo says will
run). Both readings are true; they are not the same reading, and no amount of
regrouping module paths turns one into the other.

**Everything here is declared.** `application.properties` carries the port, the
external endpoints and (for Egeria) the startup server list; the Spring entry
class carries `@SpringBootApplication`; server config documents name the servers
they call. A person wrote each of those, which is what keeps this on the
right side of the line the rest of `arch_recovery` holds: read declarations,
never infer a boundary from similarity.

**The generalisation is the point.** Most of what makes this work is Spring's,
not Egeria's:

| | Egeria | Any Spring Boot app |
|---|---|---|
| the process | `OMAGServerPlatform` | `@SpringBootApplication` |
| its port | `server.port=7443` | `server.port` |
| external deps | `repositoryDatabaseURL`, `kafkaEndpoint` | `spring.datasource.url`, `spring.kafka.bootstrap-servers` |
| sub-components | `startup.server.list` | app-specific |

Only the last row needs app-specific knowledge, and it is isolated in
`_SUBCOMPONENT_KEYS` so adding another framework's convention is a table entry.

**A platform is a component, not a Collection.** Its servers share a process, a
port and a config, and they are reached *through* it — every server-scoped route
is `/servers/{serverName}/...`, so the platform is the entry point and the
servers are addressed by routing. That is affinity, and affinity means
composition (see `clustering.py`): the servers become sub-components rather than
members of a blueprint.
"""
from __future__ import annotations

import json
import logging
import os
import re

log = logging.getLogger(__name__)

#: Properties whose *value* names a sub-component list. App-specific by nature —
#: Spring has no convention for "things running inside me" — so this is a table
#: rather than a heuristic, and an app not in it simply proposes no
#: sub-components rather than having some guessed for it.
_SUBCOMPONENT_KEYS = ("startup.server.list",)

#: Standard Spring keys for external dependencies, plus the Egeria-specific
#: names that mean the same thing. Both are *declared endpoints*; the framework
#: ones simply arrive for free in any Spring app.
_ENDPOINT_KEY_HINTS = ("datasource.url", "bootstrap-servers", "kafkaendpoint",
                       "databaseurl", "repositorydatabaseurl", "topicurlroot")

_PORT_KEY = "server.port"

#: `~{name}~` — Egeria's placeholder syntax. The values are declared in the same
#: file under `platform.placeholder.variables`, so they can be resolved rather
#: than recorded as literals. An unresolved placeholder is not an endpoint.
_PLACEHOLDER_RE = re.compile(r"~\{([A-Za-z0-9_]+)\}~")

#: What a declared endpoint connects to, by scheme or shape.
_KIND_BY_SCHEME = {
    "jdbc:postgresql": ("PostgreSQL", "JDBC"),
    "jdbc:mysql": ("MySQL", "JDBC"),
    "jdbc:mariadb": ("MariaDB", "JDBC"),
    "jdbc:sqlserver": ("SQL Server", "JDBC"),
    "jdbc:oracle": ("Oracle Database", "JDBC"),
    "mongodb": ("MongoDB", "MongoDB"),
    "redis": ("Redis", "Redis"),
    "amqp": ("AMQP Broker", "AMQP"),
}


def _read_properties(path: str) -> dict[str, str]:
    """Flat key=value pairs, with line continuations joined.

    Deliberately not a full properties parser: this reads declarations, and the
    ones that matter here are simple assignments. A JSON block spanning
    continued lines (Egeria's placeholder variables) is joined back together so
    it can be parsed separately.
    """
    try:
        raw = open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return {}
    joined = re.sub(r"\\\s*\n\s*", "", raw)
    out: dict[str, str] = {}
    for line in joined.splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def _placeholders(props: dict[str, str]) -> dict[str, str]:
    blob = props.get("platform.placeholder.variables", "")
    if not blob:
        return {}
    try:
        data = json.loads(blob)
    except ValueError:
        return {}
    return {k: str(v) for k, v in data.items() if isinstance(v, (str, int, float))}


def _resolve(value: str, placeholders: dict[str, str]) -> str:
    """Substitute `~{name}~` from the declared placeholder map.

    Returns "" when a placeholder cannot be resolved: recording the template as
    though it were an endpoint would put a string nobody can connect to into
    the catalog.
    """
    def sub(m):
        return placeholders.get(m.group(1), "\x00")
    out = _PLACEHOLDER_RE.sub(sub, value)
    return "" if "\x00" in out else out


def _endpoint_target(value: str) -> tuple[str, str, str]:
    """`(component name, protocol, detail)` for a declared endpoint, or ("","","")."""
    v = value.strip()
    if not v:
        return "", "", ""
    for prefix, (name, proto) in _KIND_BY_SCHEME.items():
        if v.lower().startswith(prefix):
            return name, proto, v
    if v.lower().startswith(("http://", "https://")):
        return "", "HTTP/REST", v          # an HTTP endpoint names no component on its own
    if re.fullmatch(r"[A-Za-z0-9_.-]+:\d{2,5}", v):
        return "", "TCP", v
    return "", "", ""


def _spring_entry_points(root: str) -> list[str]:
    """Files carrying `@SpringBootApplication` — the processes in this repo."""
    hits: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "build", "target", "out")]
        for fn in filenames:
            if not fn.endswith(".java"):
                continue
            path = os.path.join(dirpath, fn)
            try:
                if "@SpringBootApplication" in open(path, encoding="utf-8", errors="replace").read(20000):
                    hits.append(os.path.relpath(path, root))
            except OSError:
                continue
    return sorted(hits)


def _properties_files(root: str) -> list[str]:
    """Every `*application.properties`.

    Plural deliberately: one repo can declare several platforms — measured on
    egeria-workspaces, which carries `freshstart.application.properties` and
    `quickstart.application.properties`, each with its own name and server list.
    An environment can also span platforms this repo does not contain, which no
    repo-scoped analysis can see and which is stated in `notes` rather than
    guessed at.
    """
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "build", "target")]
        for fn in filenames:
            if fn.endswith("application.properties"):
                found.append(os.path.relpath(os.path.join(dirpath, fn), root))
    return sorted(found)


#: Where a server's configuration was read from, in increasing authority. Egeria
#: has three tiers and they are NOT interchangeable (Dan, 2026-08-29): the repo
#: carries illustrative samples under
#: `open-metadata-resources/open-metadata-deployment/sample-configs`; the docker
#: build bakes a default configuration into the image; and a real deployment —
#: egeria-workspaces' freshstart and quickstart — writes the actual server
#: configs at runtime.
#:
#: Recorded rather than collapsed, because §4.1a's correction is exactly this
#: mistake in another place: a repository contains a *description* of a
#: container, not a container, and treating a sample as the deployment puts
#: fiction in the catalog. A sample tells you what kind of thing a server is; it
#: does not tell you that this deployment runs it that way.
CONFIG_SOURCE_DEPLOYMENT = "deployment"   # the declared config store — what actually runs
CONFIG_SOURCE_SAMPLE = "sample"           # sample-configs in the repo — illustrative only

#: Where sample configs live in an Egeria checkout. A path, because it is one —
#: not a search, so nothing else can be mistaken for a sample.
_SAMPLE_CONFIG_DIR = os.path.join(
    "open-metadata-resources", "open-metadata-deployment", "sample-configs")


def _sample_config(root: str, name: str) -> dict:
    """A server's SAMPLE config, used only to learn what kind of server it is."""
    path = os.path.join(root, _SAMPLE_CONFIG_DIR, name, "config", f"{name}.config")
    if not os.path.isfile(path):
        return {}
    try:
        doc = json.load(open(path, encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    inner = doc.get("omagserverConfig") if isinstance(doc, dict) else None
    return inner if isinstance(inner, dict) else (doc if isinstance(doc, dict) else {})


def _server_config(root: str, props: dict[str, str], name: str) -> dict:
    """A server's config document, found via the DECLARED config-store path.

    `platform.configstore.endpoint=data/servers/{0}/config/{0}.config` says
    exactly where these live. Using it rather than walking for `*.config` is
    what keeps connector test fixtures out: an earlier version walked the tree
    and picked up eleven deliberately-malformed `.config` files from
    `configuration-file-store-connector/src/test/resources`, reporting each as
    an unreadable config.

    In a repo checkout the store is usually EMPTY — server configs are runtime
    state the platform writes, so `data/` often holds only a README. That is
    normal and not an error: the startup list still declares the servers.
    """
    endpoint = props.get("platform.configstore.endpoint", "")
    if not endpoint:
        return {}
    rel = endpoint.replace("{0}", name)
    # The config-store path is relative to the platform's working directory,
    # which is the properties file's own directory in every layout seen so far.
    candidates = [os.path.join(root, rel),
                  os.path.join(root, os.path.dirname(props.get("__rel__", "")), rel)]
    path = next((c for c in candidates if os.path.isfile(c)), "")
    if not path:
        return {}
    try:
        doc = json.load(open(path, encoding="utf-8", errors="replace"))
    except (OSError, ValueError):
        return {}
    inner = doc.get("omagserverConfig") if isinstance(doc, dict) else None
    return inner if isinstance(inner, dict) else (doc if isinstance(doc, dict) else {})


_SERVER_KIND_BY_BLOCK = {
    "viewServicesConfig": "View Server",
    "governanceEnginesConfig": "Engine Host",
    "dynamicIntegrationGroupsConfig": "Integration Daemon",
    "accessServicesConfig": "Metadata Access Server",
}


#: An event topic a server publishes to or consumes from is an **interface** —
#: an exposed surface — so it is a PORT, not a wire to a broker. The broker is
#: infrastructure; the topics are what components offer each other.
#: `SolutionPortDirection` already carries the distinction: publishing is
#: Output, consuming is Input.
_TOPIC_DIRECTION_HINTS = (("outtopic", "Output"), ("intopic", "Input"))

#: Egeria's **common services** are present in every server by default
#: (https://egeria-project.org/services/ — the platform is a chassis with
#: pluggable OMAS/OMVS/OMES services plus common services). FFDC —
#: first-failure data capture — is one of them, which is why every server
#: carries an `...default.ffdc.audit-logs` topic. Marked rather than dropped: it
#: is a true port, but an identical one on every server, so a consumer that
#: wants what DISTINGUISHES servers needs to be able to tell it apart from a
#: service-specific topic.
_COMMON_SERVICE_MARKERS = ("ffdc", ".default.")

#: What makes an endpoint a TOPIC is its connector provider, not its address.
#: `endpoint.networkAddress` carries every kind of endpoint a server declares —
#: REST URLs, secrets stores, archive files — so keying on the address string
#: would sweep all of them in (measured: 14 "topics" for egeria, of which 5 were
#: real). The connection declares what it is:
#:
#:     KafkaOpenMetadataTopicProvider          -> an event topic
#:     InMemoryOpenMetadataTopicProvider       -> an event topic, in-process
#:     FileBasedOpenMetadataArchiveStoreProvider -> a file, not a topic
#:     OMRSRESTRepositoryConnectorProvider     -> a REST endpoint, not a topic
#:
#: Matched on the provider class name ending, so a provider in any package
#: qualifies and a new topic connector is caught by naming convention rather
#: than by an allow-list that goes stale.
_TOPIC_PROVIDER_SUFFIX = "topicprovider"


def _topic_ports(cfg: dict, server_name: str, path: str) -> list[dict]:
    """Event-topic ports declared in a server's configuration.

    Topics live at `endpoint.networkAddress` under whichever connection declares
    them — `accessServicesConfig[i].accessServiceOutTopic` for an OMAS out-topic,
    `repositoryServicesConfig.auditLogConnections[i]` for the audit log — so the
    walk keys on that address and reads DIRECTION from the enclosing key rather
    than from the topic string. The enclosing key is the declaration; the string
    is a name someone chose.

    Topic names are recorded exactly as declared. `egeria.omag.egeria.omag.
    server.default.ffdc.audit-logs` is not a doubled root: the naming reflects
    the platform (`egeria.omag`), the generic server component
    (`egeria.omag.server`) and a default service (`default.ffdc.audit-logs`).
    An earlier reading of this as a defect was wrong, and "correcting" a name
    that carries structure would destroy the structure.
    """
    found: list[dict] = []

    def walk(node, enclosing: str) -> None:
        if isinstance(node, dict):
            endpoint = node.get("endpoint")
            address = endpoint.get("networkAddress") if isinstance(endpoint, dict) else None
            connector = node.get("connectorType")
            provider = (connector.get("connectorProviderClassName", "")
                        if isinstance(connector, dict) else "")
            is_topic = provider.lower().endswith(_TOPIC_PROVIDER_SUFFIX)
            if isinstance(address, str) and address.strip() and is_topic:
                lowered = enclosing.lower()
                direction = next((d for hint, d in _TOPIC_DIRECTION_HINTS if hint in lowered),
                                 "Unknown")
                common = any(m in address.lower() for m in _COMMON_SERVICE_MARKERS)
                found.append({
                    "component": server_name,
                    "name": address.strip(),
                    "direction": direction,
                    "protocol": "Kafka",
                    "evidence": {"path": path, "line": 0},
                    "provider": provider.rsplit(".", 1)[-1],
                    "detail": (f"event topic declared in `{enclosing}` "
                               f"({provider.rsplit('.', 1)[-1]})"
                               + (" — a common service present in every server by default"
                                  if common else "")),
                    "additionalProperties": {"commonService": "true" if common else "false"},
                })
            for k, v in node.items():
                walk(v, k if k != "endpoint" else enclosing)
        elif isinstance(node, list):
            for item in node:
                walk(item, enclosing)

    walk(cfg, "")
    # One port per topic name: the same topic reached through several nested
    # connections is one interface, not several.
    unique: dict[str, dict] = {}
    for port in found:
        unique.setdefault(port["name"], port)
    return sorted(unique.values(), key=lambda p: p["name"])


def _referenced_servers(node, out: set) -> None:
    """Every `omagserverName` at any depth.

    Walked rather than read from fixed paths: the references sit at different
    depths per server kind, and a path list would go stale silently. Measured on
    egeria's five sample configs, 69 references collapse to 3 distinct edges —
    most of them are one partner server named once per view service.
    """
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "omagserverName" and isinstance(v, str) and v.strip():
                out.add(v.strip())
            else:
                _referenced_servers(v, out)
    elif isinstance(node, list):
        for item in node:
            _referenced_servers(item, out)


def discover(root: str) -> dict:
    """`{"platforms": [...], "wires": [...], "notes": [...]}`.

    A platform is a component; its servers are sub-components; declared
    endpoints become wires to third-party components. Returns empty lists for a
    repo that declares no Spring application, which is most of them.
    """
    prop_files = _properties_files(root)
    entries = _spring_entry_points(root)
    if not prop_files:
        return {"platforms": [], "wires": [], "ports": [], "notes": []}

    notes: list[str] = []
    platforms: list[dict] = []
    wires: list[dict] = []
    ports: list[dict] = []

    for rel in prop_files:
        props = _read_properties(os.path.join(root, rel))
        props["__rel__"] = rel          # so the config store resolves beside its properties file
        holders = _placeholders(props)
        name = (props.get("platform.name") or props.get("spring.application.name")
                or os.path.basename(rel)[: -len("application.properties")].strip(".") or "platform")

        servers: list[dict] = []
        for key in _SUBCOMPONENT_KEYS:
            for sub in (s.strip() for s in props.get(key, "").split(",")):
                if not sub:
                    continue
                cfg = _server_config(root, props, sub)
                source = CONFIG_SOURCE_DEPLOYMENT if cfg else ""
                if not cfg:
                    # No deployment config — normal in a checkout, where the
                    # config store is runtime state. Fall back to the sample to
                    # learn the server KIND, and label it, so nothing downstream
                    # reads a sample as a deployment fact.
                    cfg = _sample_config(root, sub)
                    source = CONFIG_SOURCE_SAMPLE if cfg else ""
                kind = next((v for k, v in _SERVER_KIND_BY_BLOCK.items() if k in cfg), "")
                refs: set = set()
                _referenced_servers(cfg, refs)
                refs.discard(sub)
                servers.append({"name": sub, "kind": kind, "calls": sorted(refs),
                                "config_source": source,
                                "topics": _topic_ports(cfg, sub, rel) if cfg else []})

        endpoints: list[dict] = []
        for key, value in sorted(props.items()):
            if not any(h in key.lower() for h in _ENDPOINT_KEY_HINTS):
                continue
            resolved = _resolve(value, holders)
            if not resolved:
                notes.append(f"{name}: {key} is an unresolved placeholder — not recorded")
                continue
            target, proto, detail = _endpoint_target(resolved)
            endpoints.append({"key": key, "value": resolved, "target": target,
                              "protocol": proto, "detail": detail})
        # Egeria declares its external endpoints inside the placeholder block
        # rather than as top-level properties, so read those too.
        for key, value in sorted(holders.items()):
            if not any(h in key.lower() for h in _ENDPOINT_KEY_HINTS):
                continue
            target, proto, detail = _endpoint_target(value)
            if target or proto:
                endpoints.append({"key": key, "value": value, "target": target,
                                  "protocol": proto, "detail": detail})

        platforms.append({
            "name": name, "path": rel, "port": props.get(_PORT_KEY, ""),
            "servers": servers, "endpoints": endpoints,
            "spring_entry_points": entries,
        })

        for server in servers:
            ports.extend(server.get("topics") or [])

        known = {s["name"] for s in servers}
        for s in servers:
            for target in s["calls"]:
                if target in known:
                    src = s.get("config_source") or ""
                    wires.append({"source": s["name"], "target": target, "protocol": "REST",
                                  "integrationStyle": f"server config omagserverName ({src})"
                                                      if src else "server config omagserverName",
                                  "oneWay": True, "platform": name,
                                  "config_source": src,
                                  "label": f"{s['name']} is configured to call {target}"
                                           + (" (from a sample configuration, not this "
                                              "deployment)" if src == CONFIG_SOURCE_SAMPLE else "")})
                else:
                    notes.append(f"{s['name']} references {target!r}, which this platform "
                                 f"does not declare — edge not proposed")
        for ep in endpoints:
            if ep["target"]:
                wires.append({"source": name, "target": ep["target"], "protocol": ep["protocol"],
                              "integrationStyle": "declared endpoint", "oneWay": True,
                              "platform": name,
                              "label": f"{name} is configured to reach {ep['target']} "
                                       f"({ep['key']})"})

    if len(platforms) > 1:
        notes.append(f"{len(platforms)} platforms declared in this repo: "
                     + ", ".join(p["name"] for p in platforms)
                     + " — an environment may also span platforms declared elsewhere, "
                       "which a repo-scoped analysis cannot see")
    return {"platforms": platforms, "wires": wires, "ports": ports, "notes": notes}


# ── projection into the IR ───────────────────────────────────────────────────

#: A platform is a `Software Service`: it is the process that holds the port and
#: answers the REST call. Its servers are the same — they serve requests routed
#: to them through it. A declared third-party endpoint is a `Third Party
#: Process`, matching what the compose detector already emits for services it
#: does not own.
_PLATFORM_TYPE = "Software Service"
_SERVER_TYPE = "Software Service"
_THIRD_PARTY_TYPE = "Third Party Process"

#: Confidence. A platform and its servers are read from an explicit declaration
#: a person wrote, which is the strongest evidence this module ever has — the
#: same tier as a compose service. A server whose KIND came from a sample is
#: still a declared server; only the kind is sample-derived, and that is carried
#: in evidence rather than discounted here.
_DECLARED_CONFIDENCE = 85


def _slug(*parts: str) -> str:
    """`platform::server` — an identity locator whose FIRST segment is the
    platform's own name.

    Deliberately not prefixed with `spring::`. `scope_hierarchy` derives a
    parent from the segment before `::`, so a shared prefix makes every platform
    in a repo collapse into one group named after the discoverer: measured on
    egeria, `spring::`-prefixed slugs produced a single 14-member cluster called
    "spring" instead of three platforms. That is the same failure as
    `docker_compose::`, where a locator kept only the last path segment and hid
    the boundary that mattered — a prefix naming the tool that found something
    is not a boundary anyone declared.
    """
    return "::".join(re.sub(r"[^0-9A-Za-z_.-]+", "-", p).strip("-") for p in parts if p)


def to_ir(found: dict):
    """`(components, ports, wires, evidence)` for `persist_ir`.

    The platform is a component and its servers are its **sub-components**, not
    a Collection: they share a process, a port and a configuration, and they are
    reached *through* the platform — every server-scoped route is
    `/servers/{serverName}/...`, so the platform is the entry point and the
    servers are addressed by routing. That is affinity, and affinity means
    composition (`clustering.py` §7).
    """
    from .ir import Component, Evidence, Identity, Location

    components: list = []
    wires: list = list(found.get("wires") or [])
    evidence: list = []
    # Topic ports are attributed to the SERVER that declares them, so their
    # `component` must be the server's slug rather than its bare name.
    ports: list = []
    slug_by_server: dict = {}
    seen_third_party: set = set()

    for platform in found.get("platforms") or []:
        pslug = _slug(platform["name"])
        components.append(Component(
            slug=pslug, name=platform["name"], type=_PLATFORM_TYPE,
            identity=Identity(method="deployment-unit", value=platform["name"],
                              deployment_context=os.path.dirname(platform["path"])),
            confidence=_DECLARED_CONFIDENCE, confidence_level="Derived",
            perspective="deployment", proposed_by=["spring:application-properties"],
        ))
        evidence.append(Evidence(
            subject_kind="component", subject_slug=pslug,
            assertion=f"{platform['name']} is a Spring application declared in {platform['path']}"
                      + (f", serving port {platform['port']}" if platform["port"] else ""),
            detector="spring:application-properties", confidence=_DECLARED_CONFIDENCE,
            locations=[Location(path=platform["path"], line=0)],
        ))

        for server in platform.get("servers") or []:
            sslug = _slug(platform["name"], server["name"])
            components.append(Component(
                slug=sslug, name=server["name"], type=_SERVER_TYPE,
                identity=Identity(method="deployment-unit", value=server["name"],
                                  deployment_context=os.path.dirname(platform["path"])),
                confidence=_DECLARED_CONFIDENCE, confidence_level="Derived",
                perspective="deployment", proposed_by=["spring:startup-server-list"],
                parent_slug=pslug, depth=1,
            ))
            kind_note = ""
            if server.get("kind"):
                kind_note = (f"; a {server['kind']} according to "
                             + ("its deployment configuration"
                                if server.get("config_source") == CONFIG_SOURCE_DEPLOYMENT
                                else "a sample configuration in this repo, not this deployment"))
            slug_by_server[server["name"]] = sslug
            evidence.append(Evidence(
                subject_kind="component", subject_slug=sslug,
                assertion=f"{server['name']} is declared in {platform['path']}'s "
                          f"startup.server.list{kind_note}",
                detector="spring:startup-server-list", confidence=_DECLARED_CONFIDENCE,
                locations=[Location(path=platform["path"], line=0)],
            ))

        for endpoint in platform.get("endpoints") or []:
            target = endpoint.get("target")
            if not target or target in seen_third_party:
                continue
            seen_third_party.add(target)
            tslug = _slug(target)
            components.append(Component(
                slug=tslug, name=target, type=_THIRD_PARTY_TYPE,
                identity=Identity(method="deployment-unit", value=target),
                confidence=_DECLARED_CONFIDENCE, confidence_level="Derived",
                perspective="deployment", proposed_by=["spring:declared-endpoint"],
            ))
            evidence.append(Evidence(
                subject_kind="component", subject_slug=tslug,
                assertion=f"{target} is reached from {platform['name']} via "
                          f"{endpoint['key']} = {endpoint['value']}",
                detector="spring:declared-endpoint", confidence=_DECLARED_CONFIDENCE,
                locations=[Location(path=platform["path"], line=0)],
            ))
    for port in found.get("ports") or []:
        owner = slug_by_server.get(port.get("component"))
        if not owner:
            continue
        ports.append({**port, "component": owner})
    return components, ports, wires, evidence
