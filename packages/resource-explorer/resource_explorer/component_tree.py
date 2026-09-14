"""Component review at the branch, not in a queue.

The designer's ports round (2026-09-14): at recovery scale a flat
per-component queue fails -- kafka recovers 609 components at a median node
size of 1 and has zero verdicts -- and no human-accepted component is
cohesive under any bar: curators accept named packages. Six hundred
decisions is an abandonment; twenty named branches is a morning. So rows
are branches of the path the components are already keyed by, a branch
verdict inherits and a component's own verdict wins, and none of it needs
a schema change: verdicts are per scope_locator and append-only, so a
branch verdict is one row at the branch's scope and the reader resolves
the longest prefix.

Ports are a column on the component, not a screen: on most repositories
there are almost none (Prometheus, one of the better cases, has one port
and no wires), and an absence that holds for every resource is a bug
report about the reader. Ports get no verdict -- a port is a line in a
Dockerfile, not a proposal about the world. Components are proposals,
ports are readings.

Ports and wires are READ from the repository's deployment artifacts at
survey time; acceptance changes which get drawn. Nothing here claims
otherwise.
"""
from __future__ import annotations

import json
from collections import Counter

from resource_explorer.registry import ProjectRegistry

LOW_CONFIDENCE = 50


#: Recovery keys a few components on non-paths -- the repository root as '',
#: '.', or '*' -- which are not branches anyone can name.
_NOT_A_PATH = {"", ".", "*"}


def _components(registry: ProjectRegistry, slug: str) -> list[dict]:
    from resource_explorer.surveyors.repo_survey_definition_adapter import _architecture_recovery_results
    res = _architecture_recovery_results(registry, slug, max_depth=None) or {}
    return [c for c in (res.get("components") or []) if (c.get("path") or "") not in _NOT_A_PATH]


def _assign_ports(comps: list[dict], ports_by_service: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """{component path: [ports]}. Ports are keyed by the deployment SERVICE
    name the artifact declares (a compose service, a Dockerfile's image);
    the diagram gives each port exactly one owner. Here: the components
    whose name or last path segment is the service name, the most specific
    path winning, so the column agrees with the drawing and 71 ports are
    counted 71 times."""
    by_key: dict[str, list[dict]] = {}
    for c in comps:
        for k in {str(c.get("name") or ""), str(c.get("path") or "").rsplit("/", 1)[-1]}:
            if k:
                by_key.setdefault(k, []).append(c)
    out: dict[str, list[dict]] = {}
    for service, plist in ports_by_service.items():
        owners = by_key.get(service) or []
        if not owners:
            continue
        owner = max(owners, key=lambda c: len(c.get("path") or ""))
        out.setdefault(owner["path"], []).extend(plist)
    return out


def _ports_by_component(registry: ProjectRegistry, slug: str) -> tuple[dict[str, list[dict]], int, int]:
    """{component path: [ports]}, total ports, total wires -- from the
    architecture_interfaces findings, as the deployment reader reads them."""
    ports: dict[str, list[dict]] = {}
    n_ports = n_wires = 0
    for r in registry.query_findings(slug, "architecture_interfaces"):
        try:
            d = json.loads(r.get("detail_json") or "{}") if not isinstance(r.get("detail"), dict) else r["detail"]
        except ValueError:
            d = {}
        if d.get("kind") == "port":
            n_ports += 1
            ports.setdefault(str(d.get("component") or ""), []).append(
                {"name": d.get("port", ""), "direction": d.get("direction", ""), "protocol": d.get("protocol", "")})
        elif d.get("kind") == "wire":
            n_wires += 1
    return ports, n_ports, n_wires


def resolve_verdict(path: str, verdicts: dict[str, dict]) -> dict | None:
    """The verdict that applies to `path`: its own row if there is one, else
    the nearest ancestor branch's, longest prefix first. An inherited verdict
    says so rather than posing as a decision someone made about that file."""
    own = verdicts.get(path)
    if own:
        return {"verdict": own["verdict"], "inherited_from": "", "note": own.get("note", ""),
                "decided_by": own.get("user_id") or own.get("decided_by") or "", "at": own.get("created_at", "")}
    parts = path.split("/")
    for i in range(len(parts) - 1, 0, -1):
        anc = "/".join(parts[:i])
        row = verdicts.get(anc) or verdicts.get(anc + "/")
        if row:
            return {"verdict": row["verdict"], "inherited_from": anc, "note": row.get("note", ""),
                    "decided_by": row.get("user_id") or row.get("decided_by") or "", "at": row.get("created_at", "")}
    return None


def component_tree(registry: ProjectRegistry, slug: str, prefix: str = "") -> dict:
    """The branches directly under `prefix` ('' = the root), each with what a
    curator needs before opening it: how many components, their type mix,
    how many sit at or below 50% confidence, their declared ports, and the
    verdict that applies -- own or inherited. Leaves (components whose path
    IS the branch) come with their branch. A grouping node -- a directory
    that holds components but is not one -- is marked with the classic
    UI's own words."""
    comps = [c for c in _components(registry, slug) if c.get("path")]
    verdicts = {k: v for k, v in registry.get_component_verdicts("repo", slug).items()
                if v.get("verdict_target", "component") == "component"}
    by_service, n_ports, n_wires = _ports_by_component(registry, slug)
    ports = _assign_ports(comps, by_service)
    pre = prefix.rstrip("/")
    under = [c for c in comps if (c["path"] == pre or c["path"].startswith(pre + "/"))] if pre else comps

    branches: dict[str, dict] = {}
    for c in under:
        rel = c["path"][len(pre) + 1:] if pre else c["path"]
        if not rel:
            continue                        # the prefix's own component is the caller's row
        seg = rel.split("/", 1)[0]
        bpath = f"{pre}/{seg}" if pre else seg
        b = branches.setdefault(bpath, {"path": bpath, "name": seg, "components": 0, "low_confidence": 0,
                                        "types": Counter(), "ports": 0, "own": None, "children": 0,
                                        "accepted": 0, "rejected": 0, "undecided": 0, "structural": False})
        if c["path"] == bpath:
            b["own"] = c
            b["structural"] = bool(c.get("structural"))
            if c.get("structural"):
                continue
        if c.get("structural"):
            continue
        b["components"] += 1
        if c["path"] != bpath:
            b["children"] += 1
        if (c.get("confidence") or 0) <= LOW_CONFIDENCE:
            b["low_confidence"] += 1
        if c.get("type"):
            b["types"][c["type"]] += 1
        b["ports"] += len(ports.get(c["path"], []))
        v = resolve_verdict(c["path"], verdicts)
        if not v:
            b["undecided"] += 1
        elif v["verdict"] == "accepted":
            b["accepted"] += 1
        elif v["verdict"] == "rejected":
            b["rejected"] += 1
        else:
            b["undecided"] += 1

    out = []
    for b in sorted(branches.values(), key=lambda x: (-x["components"], x["path"])):
        own = b.pop("own")
        b["types"] = dict(b["types"].most_common(4))
        b["verdict"] = resolve_verdict(b["path"], verdicts)
        b["grouping_only"] = own is None or bool(b["structural"])
        b["type"] = (own or {}).get("type") or ""
        b["confidence"] = (own or {}).get("confidence") if own else None
        b["own_ports"] = ports.get(b["path"], [])
        out.append(b)

    total = sum(1 for c in comps if not c.get("structural"))
    accepted = sum(1 for c in comps if not c.get("structural") and (resolve_verdict(c["path"], verdicts) or {}).get("verdict") == "accepted")
    return {
        "slug": slug, "prefix": pre, "branches": out,
        "total_components": total, "accepted": accepted,
        "reviewed": sum(1 for c in comps if not c.get("structural") and verdicts.get(c["path"])),
        "ports": n_ports, "wires": n_wires,
        "topology": topology_sentence(registry, slug, n_ports, n_wires),
    }


def topology_sentence(registry: ProjectRegistry, slug: str, n_ports: int, n_wires: int) -> str:
    """One sentence at the foot of the tree when a repository declares
    nothing, saying what it looked in -- so a reader can tell nothing
    declared from nobody looked. '' when there is a topology."""
    if n_ports or n_wires:
        return ""
    project = registry.get(slug)
    name = (project.display_name if project else slug) or slug
    return (f"No declared topology — {name} declares no ports and no wires. Ports are read from "
            f"Dockerfiles, compose files and API documents; this repository has none of those with an "
            f"exposed interface.")


def leaves(registry: ProjectRegistry, slug: str, branch: str) -> list[dict]:
    """The components under a branch, each with its resolved verdict and
    its declared ports -- what expands under a row."""
    comps = _components(registry, slug)
    verdicts = {k: v for k, v in registry.get_component_verdicts("repo", slug).items()
                if v.get("verdict_target", "component") == "component"}
    by_service, _, _ = _ports_by_component(registry, slug)
    ports = _assign_ports(comps, by_service)
    b = branch.rstrip("/")
    out = []
    for c in sorted(comps, key=lambda x: x.get("path", "")):
        p = c.get("path", "")
        if not (p == b or p.startswith(b + "/")) or c.get("structural"):
            continue
        out.append({"path": p, "name": c.get("name") or p, "type": c.get("type") or "",
                    "confidence": c.get("confidence"), "low_confidence": (c.get("confidence") or 0) <= LOW_CONFIDENCE,
                    "proposed_by": c.get("proposed_by") or [], "ports": ports.get(p, []),
                    "verdict": resolve_verdict(p, verdicts), "materialized": bool(c.get("materialized"))})
    return out
