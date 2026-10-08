"""What admits a node to a blueprint, as RE records and shows it (DESIGN-BLUEPRINT-NODE-ADMISSION.md).

The detectors tag every component with an evidence class (`surveyors/arch_recovery/admission.py`):
built here, shipped here, or referenced only. This module is the registry side:

* `reclassify`: a person may say a node is built here after all, or only referenced, WITH A REASON. The
  trail is append-only in `app_settings` (`repo_node_reclassifications::<slug>` -> `{scope: [{to, reason,
  by, at}]}`, latest entry wins), no schema change, and it is read both at survey time (so the next survey
  honours it) and at read time (so the move shows at once).
* `referenced_rows`: the referenced-only services that are runtime dependencies, with the person's
  reclassifications applied. `dependency_table` lists them as kind `runtime`.
* `summary`: what was admitted by class, what was found and not admitted (the blueprint manifest's
  lines), and the zero-component sentence.
* `environment`: the Environment Deployment Blueprint's nodes: services that are other projects'
  deployment units, each linked to the repository RE knows to build the image.

Nothing here contacts Egeria.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from resource_explorer.surveyors.arch_recovery import admission as adm

log = logging.getLogger(__name__)

ADMISSION_KIND = "architecture_admission"
#: A person can move a node to either side of the line; "shipped here" is evidence, not a decision.
RECLASSIFY_TO = (adm.BUILT, adm.REFERENCED)


def _key(slug: str) -> str:
    return f"repo_node_reclassifications::{slug}"


def read_reclassifications(registry, slug: str) -> dict:
    """{scope: [{to, reason, by, at}, ...]}; unreadable storage is said in the log and reads as none."""
    raw = registry.get_setting(_key(slug))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        log.warning("the stored node reclassifications for %s are unreadable; treating none as made", slug)
        return {}
    return data if isinstance(data, dict) else {}


def latest(reclass: dict, scope: str) -> dict | None:
    trail = reclass.get(scope) or []
    return trail[-1] if trail else None


def _stored(registry, slug: str) -> dict:
    rows = registry.query_findings(slug, ADMISSION_KIND) or []
    for r in rows:
        if r.get("check_name") != "admission":
            continue
        d = r.get("detail")
        if not isinstance(d, dict):
            try:
                d = json.loads(r.get("detail_json") or "{}")
            except ValueError:
                d = {}
        return d or {}
    return {}


def _component_paths(registry, slug: str) -> dict[str, dict]:
    from resource_explorer.surveyors.repo_survey_definition_adapter import _architecture_recovery_results
    res = _architecture_recovery_results(registry, slug, max_depth=None) or {}
    return {c["path"]: c for c in (res.get("components") or []) if c.get("path")}


def reclassify(registry, slug: str, scope: str, to: str, reason: str, by: str) -> dict:
    """Record that a person moved the node at `scope` to `to` ("built_here" or "referenced_only"), with the
    reason. The scope must be a node RE has: an admitted component or a referenced-only service."""
    if to not in RECLASSIFY_TO:
        raise ValueError(f"a node can be reclassified to {' or '.join(RECLASSIFY_TO)}, got {to!r}")
    if not (reason or "").strip():
        raise ValueError("a reclassification needs a reason")
    if not by:
        raise ValueError("a reclassification needs a person who made it")
    stored = _stored(registry, slug)
    known = {i["scope"] for i in stored.get("referenced", [])} | set(_component_paths(registry, slug))
    if scope not in known:
        raise ValueError(f"not a node of this repository: {scope!r}")
    data = read_reclassifications(registry, slug)
    entry = {"to": to, "reason": reason.strip(), "by": by,
             "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    data.setdefault(scope, []).append(entry)
    registry.set_setting(_key(slug), json.dumps(data))
    return entry


def apply_to_components(components: list, reclass: dict) -> None:
    """Survey time: honour the trail on freshly detected Components (mutates them)."""
    for c in components:
        from resource_explorer.surveyors.arch_recovery.persist import scope_locator_for
        entry = latest(reclass, scope_locator_for(c))
        if entry:
            c.admission = entry["to"]
            c.admission_evidence = f"reclassified by {entry['by']} · {entry['reason']}"


def referenced_rows(registry, slug: str) -> list[dict]:
    """The referenced-only services, reclassifications applied: a stored referenced-only service a person
    moved to built-here is gone from this list; an admitted component a person moved to referenced-only
    is on it."""
    reclass = read_reclassifications(registry, slug)
    rows = []
    for i in _stored(registry, slug).get("referenced", []):
        entry = latest(reclass, i["scope"])
        if entry and entry["to"] == adm.BUILT:
            continue
        rows.append({**i, "reclassified": entry})
    have = {r["scope"] for r in rows}
    moved = [s for s, t in reclass.items() if t and t[-1]["to"] == adm.REFERENCED and s not in have]
    if moved:
        comps = _component_paths(registry, slug)
        for scope in moved:
            c = comps.get(scope)
            if c is None:
                continue
            rows.append({"scope": scope, "name": c.get("name") or scope, "slug": scope,
                         "image": c.get("image") or "", "evidence": c.get("admission_evidence") or "",
                         "unit": "", "reclassified": latest(reclass, scope)})
    return rows


def apply_to_tree_components(registry, slug: str, comps: list[dict]) -> list[dict]:
    """Read time (component_tree): a node moved to referenced-only leaves the list; a referenced-only
    service moved to built-here joins it, shown as a node with its class and the reason. Every node
    carries `reclassified` when a person moved it."""
    reclass = read_reclassifications(registry, slug)
    if not reclass:
        return comps
    out = []
    for c in comps:
        entry = latest(reclass, c.get("path", ""))
        if entry and entry["to"] == adm.REFERENCED:
            continue
        if entry:
            c = {**c, "reclassified": entry, "admission": entry["to"],
                 "admission_evidence": f"reclassified by {entry['by']} · {entry['reason']}"}
        out.append(c)
    present = {c.get("path") for c in out}
    for i in _stored(registry, slug).get("referenced", []):
        entry = latest(reclass, i["scope"])
        if entry and entry["to"] == adm.BUILT and i["scope"] not in present:
            out.append({"path": i["scope"], "name": i["name"], "type": "Third Party Process", "confidence": 60,
                        "perspective": "deployment", "proposed_by": [], "proposals": [], "agreement": False,
                        "withdrawn_by": [], "admission": adm.BUILT, "image": i.get("image", ""),
                        "admission_evidence": f"reclassified by {entry['by']} · {entry['reason']}",
                        "reclassified": entry})
    return out


def summary(registry, slug: str) -> dict:
    """What was admitted by class, what was found and not admitted, and the zero-component sentence."""
    stored = _stored(registry, slug)
    comps = apply_to_tree_components(registry, slug, [
        c for c in _component_paths(registry, slug).values()
        if not c.get("structural") and c.get("path") not in ("", ".", "*")])
    counts = {adm.BUILT: 0, adm.SHIPPED: 0}
    for c in comps:
        k = c.get("admission") or adm.BUILT
        if k in counts:
            counts[k] += 1
    refs = referenced_rows(registry, slug)
    admitted = sum(counts.values())
    left_out = list(stored.get("left_out") or [])
    # The referenced-only line is derived from the rows as they stand now (a reclassification moves one),
    # not from the line written at survey time.
    left_out = [l for l in left_out if "referenced only" not in l]
    if refs:
        left_out.insert(0, f"{len(refs)} service{'' if len(refs) == 1 else 's'} referenced only · "
                           f"listed as runtime dependencies")
    return {"admitted": admitted, "counts": counts, "referenced": len(refs), "left_out": left_out,
            "sentence": adm.ZERO_COMPONENT_SENTENCE if (refs and not admitted) else "",
            "surveyed": bool(stored)}


def environment(registry, slug: str) -> dict:
    """The Environment Deployment Blueprint's nodes: each referenced-only service as another project's
    deployment unit, linked to the repository that builds its image when RE knows one (that repository's
    own survey recorded the image among those it builds or publishes). A link is a fact RE read from two
    surveys, carried as an annotation until Egeria has the type; no link is said as "builder not known"."""
    rows = referenced_rows(registry, slug)
    builders: dict[str, str] = {}
    if rows:
        for p in registry.list_all():
            if p.slug == slug:
                continue
            for img in _stored(registry, p.slug).get("published_images", []):
                builders.setdefault(img, p.slug)
    nodes = []
    for r in rows:
        img = r.get("image") or ""
        builder = ""
        for pub, owner in builders.items():
            if img and adm.same_image(img, pub):
                builder = owner
                break
        nodes.append({"name": r["name"], "image": img, "source": r.get("evidence", ""), "scope": r["scope"],
                      "built_by": builder,
                      "words": f"built by {builder}" if builder else "builder not known"})
    return {"nodes": nodes, "linked": sum(1 for n in nodes if n["built_by"])}
