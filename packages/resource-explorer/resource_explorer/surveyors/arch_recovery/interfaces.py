"""Ports and wires — the external interface a component exposes, and what it calls.

Design reference: §3.2 (`SolutionPortDirection`), §3.3 (`SolutionLinkingWire`
properties), §5.2 steps 4-5, and §5.5f which measured the gap this closes:
`IR.ports` and `IR.wires` were declared, documented "not in this slice", and
**nothing anywhere populated them**.

§5.5f's argument for doing this first is that the biggest gap is also among the
cheapest. Interface evidence is disproportionately **black-box observable** and
mostly sits in artifacts the detectors already parse, so nothing here reads
source code: no ast-grep, no import graph, no clone. That keeps it at Discovery
tier by rule 17's own test.

**Direction is the interesting part of the vocabulary** (§3.2). `Input-Output`
means request-response *provided* — the component serves an interface.
`Output-Input` means request-response *called* — it is the client. Getting these
backwards would invert every dependency, so this module claims the strong values
only on direct evidence and falls back to plain `Input`/`Output` otherwise.

**What is deliberately NOT inferred.** Protocol is never guessed from a port
number. Port 8080 is *conventionally* HTTP, and treating convention as evidence
is how a plausible-but-unverifiable claim enters the catalog wearing the same
confidence as a measured one — the failure §5.5a(b) and finding 66 both turn on.
`protocol` is populated only where an artifact states it: a `/tcp` suffix on
`EXPOSE`, an OpenAPI document, a named Kubernetes service port. Where nothing
says, it stays empty and the direction stays conservative.
"""
from __future__ import annotations

import os
import re

import yaml

from .ir import Component, Evidence, Location

# §3.2 — the five values, spelled as Egeria spells them.
DIR_UNKNOWN = "Unknown"
DIR_OUTPUT = "Output"
DIR_INPUT = "Input"
DIR_INPUT_OUTPUT = "Input-Output"      # request-response PROVIDED (serving)
DIR_OUTPUT_INPUT = "Output-Input"      # request-response CALLED (client)

_EXPOSE_RE = re.compile(r"^\s*EXPOSE\s+(.+?)\s*$", re.I | re.M)
_OPENAPI_NAMES = ("openapi.json", "openapi.yaml", "openapi.yml",
                  "swagger.json", "swagger.yaml", "swagger.yml")

# Interface definition languages, matched by extension rather than filename —
# unlike OpenAPI these are conventionally named after the service, not the
# format. Recognising them closes a blind spot measured on the corpus: Milvus is
# gRPC-first with SDKs in several languages, and we recorded its exposed ports
# while missing its actual interface entirely.
_PROTO_EXT = ".proto"
_GRAPHQL_EXTS = (".graphql", ".graphqls", ".gql")
_THRIFT_EXT = ".thrift"

# HTTP methods an OpenAPI path item may carry. Anything else under a path (like
# `parameters` or `summary`) is not an operation.
_OPENAPI_METHODS = frozenset({
    "get", "put", "post", "delete", "options", "head", "patch", "trace"})

# Word-boundary anchored, NOT line anchored. A line anchor looks safer and
# silently undercounts the compact style — `service S { rpc A (Q) returns (R); }`
# on one line reported 1 service and 0 rpcs, which reads as "an interface with
# no operations" rather than as a parse limitation. Caught by a test before it
# reached real data; Milvus's files happen to be multi-line, so the corpus would
# not have shown it.
_PROTO_SERVICE_RE = re.compile(r"\bservice\s+(\w+)\s*\{")
_PROTO_RPC_RE = re.compile(r"\brpc\s+\w+\s*\(")
_GRAPHQL_ROOT_RE = re.compile(r"\btype\s+(Query|Mutation|Subscription)\b")
_THRIFT_SERVICE_RE = re.compile(r"\bservice\s+(\w+)\s*\{")


def _read_text(root: str, rel: str, limit: int = 4_000_000) -> str:
    """Read an interface document, or "" if unreadable. Size-capped: a
    generated OpenAPI document can be very large, and counting operations does
    not justify loading an unbounded file into memory."""
    try:
        full = os.path.join(root, rel)
        if os.path.getsize(full) > limit:
            return ""
        with open(full, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def _count_openapi_operations(root: str, rel: str) -> int | None:
    """Number of operations an OpenAPI document declares, or None if the
    document could not be parsed.

    **A count, not a listing.** The driving question (Dan, 2026-08-24) is
    whether a repo is usable at runtime — "what kind of API it has, maybe
    language bindings, the number of commands ... not the names of every
    request and their payloads until we want to actually try to use it". So
    this opens the document, counts, and discards it. Reading the operation
    names and schemas is stage two and a different cost tier.

    None and 0 are different answers and are kept apart: None means we could
    not read it, 0 means a document that declares no operations.
    """
    text = _read_text(root, rel)
    if not text:
        return None
    try:
        doc = yaml.safe_load(text)     # a superset of JSON, so this covers both
    except Exception:
        return None
    if not isinstance(doc, dict):
        return None
    paths = doc.get("paths")
    if not isinstance(paths, dict):
        return None
    return sum(
        1
        for item in paths.values() if isinstance(item, dict)
        for method in item
        if isinstance(method, str) and method.lower() in _OPENAPI_METHODS
    )


def _count_proto_rpcs(root: str, rel: str) -> tuple[int | None, int | None]:
    """`(services, rpcs)` declared in a `.proto` file, or `(None, None)`.

    Regex rather than a protobuf parser: this runs at Discovery tier and must
    not add a dependency or a compile step. `service X {` and `rpc Y(` are
    unambiguous enough at line starts that a parser would buy very little.
    """
    text = _read_text(root, rel)
    if not text:
        return None, None
    return (len(_PROTO_SERVICE_RE.findall(text)),
            len(_PROTO_RPC_RE.findall(text)))


def _port_dict(component: str, name: str, direction: str, protocol: str,
               path: str, line: int, detail: str,
               operation_count: int | None = None) -> dict:
    """`operation_count` rides in `additionalProperties`, Egeria's documented
    extension point — not a bare local field and not an invented attribute.

    Checked the type first, as §5.5f asks. Per 0735, `SolutionPort` carries
    exactly one attribute of its own — `direction` — so there is no operation
    count to populate. But `SolutionPort` is a `Referenceable` (§3.3b, settled
    by the `Confidence` classification being defined against `Referenceable` and
    applying to `SolutionPort` directly), and `Referenceable` carries
    `additionalProperties` as a `map<string,string>` which §6.4 already names as
    "the documented extension point ... the interim carrier for anything not yet
    typed". So this is the sanctioned place, and promoting `operationCount` to a
    real attribute later is an upstream type change rather than a migration of
    ours.

    **Not `SolutionPortDelegation`.** That relationship maps a parent
    component's port to its decomposed children's ports, and modelling each
    operation as a child port would fit — for **stage two**, when someone wants
    the operations individually. It is wrong here: one entity per operation is
    exactly the listing the coarse suitability question excludes.

    Values are strings because the Egeria map is `map<string,string>`; writing
    an int here would be a shape that cannot be published unchanged.

    None and 0 stay apart: None is "not counted or not readable", 0 is
    "counted, and there are none".
    """
    port = {"component": component, "name": name, "direction": direction,
            "protocol": protocol, "evidence": {"path": path, "line": line},
            "detail": detail}
    if operation_count is not None:
        port["additionalProperties"] = {"operationCount": str(operation_count)}
    return port


def _wire_dict(source: str, target: str, protocol: str, integration_style: str,
               one_way: bool, path: str, line: int, label: str) -> dict:
    """Shaped to §3.3's `SolutionLinkingWire` property names. `frequency` and
    `dataExchanged` are left empty rather than invented — nothing in a compose
    file states either, and an empty property is honest where a guessed one
    would be indistinguishable from a measured one."""
    return {"source": source, "target": target, "label": label,
            "protocol": protocol, "integrationStyle": integration_style,
            "frequency": "", "dataExchanged": "", "oneWay": one_way,
            "evidence": {"path": path, "line": line}}


def _owner_of(rel: str, by_path: list[tuple[str, str]]) -> str:
    """Component owning a file, longest-prefix first.

    Whole-repo candidates are skipped. The coupling proposer emits one on every
    target (root `.`, globbing the entire tree), and because it matches every
    path it would capture every port — measured on Prometheus, where the root
    `Dockerfile`'s `EXPOSE 9090` attached to `.` rather than to anything a
    reader could act on. Same container-not-component rule as `distill.py`'s
    whole-repo guard and `go_subsystems`' module-root skip.
    """
    for prefix, name in by_path:
        if not prefix or prefix == ".":
            continue
        if rel == prefix or rel.startswith(prefix + "/"):
            return name
    return ""


def _component_paths(components: list[Component]) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for c in components:
        for g in c.files or []:
            root = g.rstrip("/*").rstrip("/")
            if root:
                out.append((root, c.name))
    return sorted(out, key=lambda t: len(t[0]), reverse=True)


def _line_of(text: str, needle: str) -> int:
    for n, line in enumerate(text.splitlines(), 1):
        if needle in line:
            return n
    return 0


def _root_artifact_owner(rel: str, components: list[Component]) -> str:
    """Who owns a deployment artifact that sits at the repo root?

    A root `Dockerfile` in a single-binary repo describes *that binary*, not the
    repository. So when exactly one component is an entry point, the artifact is
    attributed to it; with none or several the claim is ambiguous and the
    directory is used instead, which is honest rather than a guess.
    """
    entry_points = [c.name for c in components if c.type == "Console Command"]
    if len(entry_points) == 1:
        return entry_points[0]
    return os.path.dirname(rel) or "."


def _dockerfile_ports(root: str, rel: str, component: str) -> list[dict]:
    """`EXPOSE` declares an inbound port. A `/tcp` or `/udp` suffix is the only
    protocol statement a Dockerfile makes, so it is the only one recorded."""
    try:
        text = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read()
    except OSError:
        return []
    out = []
    for m in _EXPOSE_RE.finditer(text):
        for token in m.group(1).split():
            port, _, proto = token.partition("/")
            if not port.strip().isdigit():
                continue
            out.append(_port_dict(
                component, port.strip(), DIR_INPUT, proto.strip().lower(),
                rel, text[:m.start()].count("\n") + 1,
                f"EXPOSE {token} — inbound port declared by the image",
            ))
    return out


def _compose_interfaces(root: str, rel: str, service_names: dict[str, str],
                        ) -> tuple[list[dict], list[dict]]:
    """Ports from `ports:`/`expose:`, wires from `depends_on`.

    `ports:` publishes to the host, `expose:` makes a port reachable only
    within the compose network — both are inbound, and the distinction is
    recorded in `detail` rather than in `direction`, since §3.2's vocabulary is
    about data flow, not about reachability scope.
    """
    try:
        text = open(os.path.join(root, rel), encoding="utf-8", errors="replace").read()
        data = yaml.safe_load(text)
    except (OSError, yaml.YAMLError):
        return [], []
    if not isinstance(data, dict):
        return [], []
    services = data.get("services")
    if not isinstance(services, dict):
        return [], []

    ports: list[dict] = []
    wires: list[dict] = []
    for key, body in services.items():
        if not isinstance(key, str) or not isinstance(body, dict):
            continue
        name = service_names.get(key, key)

        for field, scope in (("ports", "published to the host"),
                             ("expose", "reachable inside the compose network")):
            entries = body.get(field)
            if not isinstance(entries, list):
                continue
            for entry in entries:
                spec = str(entry)
                # "8080:80" -> the container-side port is what the component serves
                container_side = spec.split(":")[-1]
                port, _, proto = container_side.partition("/")
                if not port.strip().isdigit():
                    continue
                ports.append(_port_dict(
                    name, port.strip(), DIR_INPUT, proto.strip().lower(),
                    rel, _line_of(text, spec), f"compose `{field}: {spec}` — {scope}",
                ))

        deps = body.get("depends_on")
        dep_keys: list[str] = []
        if isinstance(deps, list):
            dep_keys = [d for d in deps if isinstance(d, str)]
        elif isinstance(deps, dict):
            dep_keys = [d for d in deps if isinstance(d, str)]
        for dep in dep_keys:
            wires.append(_wire_dict(
                name, service_names.get(dep, dep), "", "compose depends_on",
                # depends_on states startup ordering, which is a real directed
                # dependency but says nothing about whether traffic returns.
                # `oneWay=False` would be a claim; `True` is the weaker one.
                True, rel, _line_of(text, dep),
                f"{name} depends on {service_names.get(dep, dep)}",
            ))
    return ports, wires


def propose(root: str, first_party: list[str], components: list[Component],
            ) -> tuple[list[dict], list[dict], list[Evidence], list[str]]:
    """`(ports, wires, evidence, notes)` from deployment artifacts only."""
    from . import detectors

    by_path = _component_paths(components)
    ports: list[dict] = []
    wires: list[dict] = []
    evidence: list[Evidence] = []
    notes: list[str] = []

    for rel in first_party:
        base = os.path.basename(rel)

        if base.lower().startswith("dockerfile"):
            owner = _owner_of(rel, by_path) or _root_artifact_owner(rel, components)
            ports.extend(_dockerfile_ports(root, rel, owner))

        elif base.lower() in _OPENAPI_NAMES:
            owner = _owner_of(rel, by_path) or _root_artifact_owner(rel, components)
            # An OpenAPI document is a direct statement that this component
            # SERVES a request-response HTTP interface — the one place a strong
            # `Input-Output` is warranted without inference.
            n_ops = _count_openapi_operations(root, rel)
            detail = "OpenAPI document — request-response interface provided"
            if n_ops is not None:
                detail += f", {n_ops} operation(s)"
            else:
                notes.append(f"{rel}: OpenAPI document could not be parsed — "
                             f"interface recorded, operation count unknown")
            ports.append(_port_dict(
                owner, base, DIR_INPUT_OUTPUT, "HTTP/REST", rel, 0, detail,
                operation_count=n_ops,
            ))

        elif rel.lower().endswith(_PROTO_EXT):
            # gRPC. Milvus is the case that made this a gap: gRPC-first, and we
            # recorded its exposed ports while missing the interface entirely.
            owner = _owner_of(rel, by_path) or _root_artifact_owner(rel, components)
            n_svc, n_rpc = _count_proto_rpcs(root, rel)
            if n_svc:
                detail = f"protobuf service definition — {n_svc} service(s)"
                if n_rpc:
                    detail += f", {n_rpc} rpc(s)"
                ports.append(_port_dict(
                    owner, base, DIR_INPUT_OUTPUT, "gRPC", rel, 0, detail,
                    operation_count=n_rpc,
                ))
            # A .proto declaring only messages and no service is a schema, not
            # an interface. Silently skipping it is correct, not a miss.

        elif rel.lower().endswith(_GRAPHQL_EXTS):
            owner = _owner_of(rel, by_path) or _root_artifact_owner(rel, components)
            text = _read_text(root, rel)
            roots = sorted(set(_GRAPHQL_ROOT_RE.findall(text))) if text else []
            if roots:
                # Only a schema declaring Query/Mutation/Subscription is a
                # served interface; a fragment of type definitions is not.
                ports.append(_port_dict(
                    owner, base, DIR_INPUT_OUTPUT, "GraphQL", rel, 0,
                    f"GraphQL schema — root type(s): {', '.join(roots)}",
                ))

        elif rel.lower().endswith(_THRIFT_EXT):
            owner = _owner_of(rel, by_path) or _root_artifact_owner(rel, components)
            text = _read_text(root, rel)
            svcs = _THRIFT_SERVICE_RE.findall(text) if text else []
            if svcs:
                ports.append(_port_dict(
                    owner, base, DIR_INPUT_OUTPUT, "Thrift", rel, 0,
                    f"Thrift IDL — {len(svcs)} service(s)",
                ))

        elif detectors._is_compose(root, rel):
            names = {k: n for k, n, _ in detectors.compose_services(root, rel)}
            p, w = _compose_interfaces(root, rel, names)
            ports.extend(p)
            wires.extend(w)

    # De-duplicate: two Dockerfiles in one component declaring the same port is
    # one fact about the component, not two.
    seen: set[tuple] = set()
    deduped = []
    for p in ports:
        key = (p["component"], p["name"], p["direction"], p["protocol"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(p)
    ports = deduped

    for p in ports:
        evidence.append(Evidence(
            subject_kind="port", subject_slug=f"{p['component']}::{p['name']}",
            assertion=f"solutionPortDirection = {p['direction']}",
            detector="interfaces",
            locations=[Location(p["evidence"]["path"], p["evidence"]["line"], p["detail"])],
            confidence=70, confidence_level="Derived",
        ))
    if not ports and not wires:
        notes.append("interfaces: no deployment artifacts declared a port or a "
                     "dependency — no ports or wires proposed")
    return ports, wires, evidence, notes
