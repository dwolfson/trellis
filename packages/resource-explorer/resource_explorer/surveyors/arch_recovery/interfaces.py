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


def _port_dict(component: str, name: str, direction: str, protocol: str,
               path: str, line: int, detail: str) -> dict:
    return {"component": component, "name": name, "direction": direction,
            "protocol": protocol, "evidence": {"path": path, "line": line},
            "detail": detail}


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
    """Component owning a file, longest-prefix first."""
    for prefix, name in by_path:
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
            owner = _owner_of(rel, by_path) or os.path.dirname(rel) or "."
            ports.extend(_dockerfile_ports(root, rel, owner))

        elif base.lower() in _OPENAPI_NAMES:
            owner = _owner_of(rel, by_path) or os.path.dirname(rel) or "."
            # An OpenAPI document is a direct statement that this component
            # SERVES a request-response HTTP interface — the one place a strong
            # `Input-Output` is warranted without inference.
            ports.append(_port_dict(
                owner, base, DIR_INPUT_OUTPUT, "HTTP/REST", rel, 0,
                "OpenAPI document — request-response interface provided",
            ))

        elif detectors._is_compose(root, rel):
            names = {k: n for k, n, _ in detectors.compose_services(root, rel)}
            p, w = _compose_interfaces(root, rel, names)
            ports.extend(p)
            wires.extend(w)

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
