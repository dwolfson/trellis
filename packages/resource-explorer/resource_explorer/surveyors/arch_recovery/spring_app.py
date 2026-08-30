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

**Not only Spring, despite the module name.** `application.properties` is also
Quarkus's configuration file, and the shape it describes — a JVM process that
declares its own name, port and external endpoints — is the same. Measured on
`apache/polaris` (Quarkus): two applications, `Apache Polaris Server` and
`Apache Polaris Admin Tool`, in separate `runtime/` modules. What is app-specific
is the *sub-component* concept: Egeria's several-servers-in-one-process has no
Quarkus equivalent, so a Quarkus application is simply a platform with no
servers, which is a legitimate shape rather than a failed read.

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

#: The property a framework uses for "what is this application called". One
#: concept, three spellings — and the third was found by measurement, not by
#: reading a framework's docs: `apache/polaris` is Quarkus, declares
#: `quarkus.application.name=Apache Polaris Server`, and was dropped entirely by
#: the no-servers-and-no-name rule until this table grew a row.
#:
#: Order is precedence. `platform.name` first because it is the most specific —
#: an Egeria platform hosting several servers is a different thing from the
#: framework's name for the process, and where both exist the platform name is
#: the one a curator wants.
_NAME_KEYS = ("platform.name", "spring.application.name", "quarkus.application.name")

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


#: Deployment styles — the axis a platform actually varies along (Dan,
#: 2026-08-29): *"its Native Java vs Containerized vs Choreographed containers
#: (e.g. quickstart and freshstart) which are choreographed with compose or
#: kubernetes"*.
#:
#: This is NOT the same axis as `platform.name`. Egeria declares
#: `platform.name=Development OMAG Server Platform` in `application.properties`
#: and `platform.name=Containerized OMAG Server Platform` in
#: `container.application.properties`, and those are one platform labelled for
#: two runtimes — the release workflow does
#: `cp -f container.application.properties .../assembly/platform/application.properties`
#: before `docker build`, so the container image's `application.properties` IS
#: `container.application.properties`. They are the same file at two points in
#: one build, not two platforms.
STYLE_NATIVE = "native-java"
STYLE_CONTAINERIZED = "containerized"
STYLE_CHOREOGRAPHED = "choreographed"
STYLE_UNKNOWN = ""

#: Filenames whose profile token names a runtime rather than an environment.
#: Weakest of the style signals and used only when nothing references the file.
_CONTAINER_PROFILE_TOKENS = frozenset({"container", "docker", "oci", "image"})
_CHOREO_PROFILE_TOKENS = frozenset({"compose", "k8s", "kubernetes", "helm"})

#: A path segment that makes the REFERRING file a choreography artifact rather
#: than an image build. Substrings, not filenames: measured, egeria-workspaces
#: choreographs from `compose-configs/egeria-freshstart/egeria-freshstart.yaml`,
#: which no `docker-compose.yml` filename test reaches.
_CHOREO_REF_TOKENS = ("compose", "k8s", "kubernetes", "helm", "kustomiz")


def _style_references(root: str) -> dict:
    """`{properties-file basename: style}` from what REFERENCES each file.

    Evidence beats filename. A compose file or Kubernetes manifest naming a
    properties file makes it choreographed; a Dockerfile or an image-building CI
    workflow makes it containerized. Both are Dev/DevOps-perspective artifacts
    (§4.1) — which is worth noticing, because it means the signal that
    disambiguates the *deployment* perspective lives in the perspective §4.1
    rates weakest and gives no good type to.

    Deliberately shallow: it reads CI workflows, compose files and Dockerfiles,
    which is where a substitution is declared, and nothing else.
    """
    styles: dict = {}
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in (".git", "node_modules", ".venv", "build", "target")]
        for fn in filenames:
            low = fn.lower()
            if not (low.endswith((".yml", ".yaml")) or "dockerfile" in low):
                continue
            if seen >= _MAX_STYLE_FILES:
                return styles
            seen += 1
            try:
                with open(os.path.join(dirpath, fn), encoding="utf-8",
                          errors="replace") as fh:
                    text = fh.read(_MAX_STYLE_BYTES)
            except OSError:
                continue
            if "application.properties" not in text:
                continue
            rel = os.path.relpath(os.path.join(dirpath, fn), root)
            choreo = any(t in rel.lower() for t in _CHOREO_REF_TOKENS)
            style = STYLE_CHOREOGRAPHED if choreo else STYLE_CONTAINERIZED
            for match in _PROPS_REF_RE.finditer(text):
                named = os.path.basename(match.group(0))
                if named == "application.properties":
                    # The DESTINATION of a substitution, not a profile. It is
                    # what every build writes, so styling it would style the
                    # platform's own canonical file after whichever workflow
                    # happened to be read first.
                    continue
                # A file copied OVER application.properties is that build's
                # application.properties, which is the substitution this whole
                # rule exists to read.
                styles.setdefault(named, style)
    return styles


#: Caps. Style detection is a Discovery-tier read over build config, and an
#: unbounded walk of a monorepo's CI is not what rule 17 licenses.
_MAX_STYLE_FILES = 400
_MAX_STYLE_BYTES = 200_000
_PROPS_REF_RE = re.compile(r"[\w.\-/]*application\.properties")


def _style_for(rel: str, ref_styles: dict) -> str:
    """The deployment style of one properties file. Reference first, filename
    second, and the bare `application.properties` is native by default."""
    base = os.path.basename(rel)
    if base in ref_styles:
        return ref_styles[base]
    profile = base[: -len("application.properties")].strip(".").lower()
    if not profile:
        return STYLE_NATIVE
    if profile in _CONTAINER_PROFILE_TOKENS:
        return STYLE_CONTAINERIZED
    if profile in _CHOREO_PROFILE_TOKENS:
        return STYLE_CHOREOGRAPHED
    return STYLE_UNKNOWN


def _common_name(names: list) -> str:
    """The longest shared trailing token run across declared platform names.

    `Development OMAG Server Platform` + `Containerized OMAG Server Platform`
    -> `OMAG Server Platform`. A comparison, not a constant: the tokens the
    declarations agree on are the platform, and the ones they do not are the
    style adjective the merge has just made redundant. Returns `""` when they
    share no trailing tokens, and the caller falls back to a declared name
    rather than inventing one.
    """
    if not names:
        return ""
    split = [n.split() for n in names]
    shared: list = []
    for i in range(1, min(len(t) for t in split) + 1):
        token = split[0][-i]
        if all(t[-i] == token for t in split):
            shared.insert(0, token)
        else:
            break
    return " ".join(shared)


def _consolidate(platforms: list, root: str, notes: list) -> list:
    """One platform deployed several ways is ONE component (Dan, 2026-08-29).

    **The rule is a comparison, not a threshold: declarations that declare the
    same server set are the same platform.** Measured, the two cases are not
    close and nothing needs tuning to separate them:

    ```
    egeria              application.properties           5 servers  ]
                        container.application.properties 5 servers  ] identical -> ONE platform
                        test.application.properties      0 servers, no platform.name -> not a platform

    egeria-workspaces   freshstart.application.properties  fs-metadata-store, fs-... ]
                        quickstart.application.properties  qs-metadata-store, qs-... ] disjoint -> TWO
    ```

    egeria's two files are the same file at two points in one build — the
    release workflow copies `container.application.properties` over
    `application.properties` before `docker build`. Workspaces' two are genuine
    peer platforms with disjoint servers, choreographed by compose. Emitting
    four platform components and ten server components for what is one platform
    with five servers was the overcount this fixes: 14 deployment components for
    egeria, of which 12 were duplicates of 6.

    A declaration with no servers AND no explicit `platform.name` declares no
    platform. `test.application.properties` has an empty `startup.server.list`
    and no name, and became a component called `test` off its own filename.
    """
    ref_styles = _style_references(root)
    for p in platforms:
        p["style"] = _style_for(p["path"], ref_styles)

    kept: list = []
    for p in platforms:
        if not p["servers"] and not p.get("declared_name"):
            notes.append(f"{p['path']} declares no servers and no platform.name — "
                         f"not proposed as a platform")
            continue
        kept.append(p)

    # Group key is (directory, server set) — BOTH, and the directory half was
    # added because a test caught the rule being too loose. Two declarations
    # naming different platforms in different directories can still declare the
    # same servers, and merging those deletes a real platform.
    #
    # Directory is the right second half because it is already what
    # `Identity.deployment_context` means: profiles of one build sit beside each
    # other (egeria's `application.properties` and
    # `container.application.properties`, both at the repo root), while separate
    # deployments get their own configuration directory (egeria-workspaces'
    # `runtime-volumes/{freshstart,quickstart}-platform-data/`).
    #
    # An empty server set never merges. Two declarations that agree only in
    # declaring nothing agree about nothing.
    groups: dict = {}
    for p in kept:
        servers = frozenset(s["name"] for s in p["servers"])
        key = (os.path.dirname(p["path"]), servers) if servers else ("", id(p))
        groups.setdefault(key, []).append(p)

    merged: list = []
    for _, group in groups.items():
        if len(group) == 1:
            group[0]["styles"] = [group[0]["style"]] if group[0]["style"] else []
            group[0]["paths"] = [group[0]["path"]]
            merged.append(group[0])
            continue
        names = [g["name"] for g in group]
        # The canonical declaration is the bare `application.properties` where
        # one exists — it is what a plain `java -jar` reads.
        canonical = next((g for g in group
                          if os.path.basename(g["path"]) == "application.properties"), group[0])
        head = dict(canonical)
        head["name"] = _common_name(names) or canonical["name"]
        head["styles"] = sorted({g["style"] for g in group if g["style"]})
        head["paths"] = sorted(g["path"] for g in group)
        head["declared_names"] = sorted(set(names))
        merged.append(head)
        notes.append(
            f"{len(group)} declarations describe one platform "
            f"({', '.join(sorted(names))}) — identical server sets, so they are "
            f"deployment styles ({', '.join(head['styles']) or 'unclassified'}) of "
            f"{head['name']!r}, not separate platforms")

    return sorted(merged, key=lambda p: p["name"])


def _dedup_ports(ports: list, platforms: list) -> list:
    """Drop the copies of a port that a merge made redundant.

    Every profile of a merged platform declares the same servers, so it declares
    the same topics: measured on egeria, 8 distinct ports arrived as 16 rows,
    each one exactly doubled. `to_ir` attributes a port to its server's slug and
    the merged platform has one slug per server, so the duplicate rows land on
    top of each other in the catalog.

    Keyed on the OWNING PLATFORM, not on `(component, name)` alone. Two platforms
    that were never merged may legitimately declare a same-named server with the
    same topic, and collapsing those would delete a real distinction to fix a
    bookkeeping one — the §4.1a discipline, applied to ports.
    """
    platform_of: dict = {}
    for plat in platforms:
        for pth in (plat.get("paths") or [plat.get("path", "")]):
            platform_of[pth] = plat["name"]
    out: list = []
    seen: set = set()
    for port in ports:
        path = (port.get("evidence") or {}).get("path", "")
        key = (platform_of.get(path, path), port.get("component"), port.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append(port)
    return out


def _remap_wires(wires: list, platforms: list) -> list:
    """Re-point wires at the surviving platform, and drop what merging made
    duplicate.

    Wires are built per declaration, so a merge leaves two identical copies of
    every server-to-server edge — one per profile — and a `platform` name that
    no longer names a component. `to_ir` attributes a wire by its platform, so
    a stale name silently produces an edge attached to nothing.
    """
    rename: dict = {}
    for p in platforms:
        for declared in p.get("declared_names") or []:
            rename[declared] = p["name"]
    if not rename:
        return wires
    out: list = []
    seen: set = set()
    for w in wires:
        w = dict(w)
        w["platform"] = rename.get(w.get("platform", ""), w.get("platform", ""))
        key = (w.get("source"), w.get("target"), w.get("protocol"), w["platform"])
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    return out


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
        # `declared_name` distinguishes a name a person WROTE from one derived
        # from the filename. A file with neither a name nor any server declares
        # no platform — see `_consolidate`.
        declared_name = next((props[k] for k in _NAME_KEYS if props.get(k)), "")
        name = (declared_name
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
            "name": name, "declared_name": declared_name, "path": rel,
            "port": props.get(_PORT_KEY, ""),
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

    platforms = _consolidate(platforms, root, notes)
    wires = _remap_wires(wires, platforms)
    ports = _dedup_ports(ports, platforms)

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
        paths = platform.get("paths") or [platform["path"]]
        styles = platform.get("styles") or []
        # The styles are the deployment axis (§4.1a stays intact: this asserts
        # what the repo SAYS should run, never that anything runs). Where a
        # merge happened, every declaration that fed it is a location, so the
        # evidence still points at each file a reader would want to open.
        style_note = (f"; deployed {', '.join(styles)}" if styles else "")
        merged_note = ("; one platform declared "
                       f"{len(paths)} ways as {', '.join(platform['declared_names'])}"
                       if platform.get("declared_names") else "")
        evidence.append(Evidence(
            subject_kind="component", subject_slug=pslug,
            assertion=f"{platform['name']} is a Spring application declared in "
                      + ", ".join(paths)
                      + (f", serving port {platform['port']}" if platform["port"] else "")
                      + style_note + merged_note,
            detector="spring:application-properties", confidence=_DECLARED_CONFIDENCE,
            locations=[Location(path=pth, line=0) for pth in paths],
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
