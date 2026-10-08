"""Dependencies as ONE table with a kind column (project owner, 2026-10-07; brief section 3).

"More extensible": a third kind is a new value in `KINDS`, not a new section. Two kinds today:

* `build-time`  what the repository's manifests declare (pyproject, requirements, package.json, pom,
                gradle): measured, read from the dependency surveyor's stored rows.
* `runtime`     what the repository's deployment artifacts say one service depends on (compose
                `depends_on` and environment references): PROPOSED, from the architecture-interfaces
                findings, until a person confirms the row ("how it relates"). A confirmed runtime row
                publishes as an ANNOTATION ONLY: Egeria's planned "deployed by" relationship types are
                not available yet, and nothing here writes a relationship. No word on screen says
                "lineage" (owner, 2026-10-05: a dependency, not lineage).

Everything here reads RE's own records; nothing contacts Egeria. A count RE does not have is not given
as zero: a section with no runtime rows says WHY (`runtime_state`): "runtime not surveyed" when the
architecture step never ran here, "no deployment artifact found" when it ran and found none.

Confirmations are kept in `app_settings` (no schema change) as an append-only trail per repository:
`repo_dependency_confirmations::<slug>` -> `{row key: [{verdict, by, at}, ...]}`, the latest entry wins.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)

KIND_BUILD = "build-time"
KIND_RUNTIME = "runtime"
#: The kinds, in display order. A new kind is added here (and a reader below), never as a new section.
KINDS = (KIND_BUILD, KIND_RUNTIME)
HEADING = "Dependencies · by kind"

VERDICT_CONFIRMED = "confirmed"
VERDICT_WITHDRAWN = "withdrawn"

NO_ARTIFACT_SENTENCE = "no deployment artifact found"
NOT_SURVEYED_SENTENCE = "runtime not surveyed"


def _key(source: str, target: str, path: str) -> str:
    return f"{source}->{target}@{path}"


def _confirmations_key(slug: str) -> str:
    return f"repo_dependency_confirmations::{slug}"


def read_confirmations(registry, slug: str) -> dict:
    raw = registry.get_setting(_confirmations_key(slug))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except ValueError:
        # Said, not hidden: every runtime row would otherwise silently read "proposed" again.
        log.warning("the stored dependency confirmations for %s are unreadable; treating none as confirmed", slug)
        return {}
    return data if isinstance(data, dict) else {}


def record_confirmations(registry, slug: str, keys: list[str], verdict: str, by: str) -> int:
    """Append one confirmation (or withdrawal) per key, by `by`. Only keys that are runtime rows of
    this repository are accepted; returns how many were recorded. Append-only: a change is a new
    entry and the trail keeps both."""
    if verdict not in (VERDICT_CONFIRMED, VERDICT_WITHDRAWN):
        raise ValueError(f"verdict must be '{VERDICT_CONFIRMED}' or '{VERDICT_WITHDRAWN}', got {verdict!r}")
    if not by:
        raise ValueError("a confirmation needs a person who made it")
    known = {r["key"] for r in _runtime_rows(registry, slug, {})}
    unknown = [k for k in keys if k not in known]
    if unknown:
        raise ValueError(f"not runtime dependencies of this repository: {unknown}")
    data = read_confirmations(registry, slug)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    for k in keys:
        data.setdefault(k, []).append({"verdict": verdict, "by": by, "at": at})
    registry.set_setting(_confirmations_key(slug), json.dumps(data))
    return len(keys)


def _latest(trail: list[dict] | None) -> dict | None:
    return trail[-1] if trail else None


def _build_rows(registry, slug: str) -> list[dict]:
    rows = []
    for d in registry.query_dependencies(slug) or []:
        src = d.get("source_file") or ""
        manifest = src.rsplit("/", 1)[-1] or "a manifest"
        rows.append({
            "kind": KIND_BUILD, "name": d.get("dep_name") or "",
            "target": d.get("dep_version") or "", "source": src, "ecosystem": d.get("ecosystem") or "",
            "state": "measured", "state_words": f"measured · from {manifest}",
            "key": f"{d.get('ecosystem') or ''}:{d.get('dep_name') or ''}@{src}",
        })
    return rows


def _artifact_rows(registry, slug: str) -> list[dict]:
    out = []
    for r in registry.query_findings(slug, "architecture_interfaces") or []:
        d = r.get("detail") if isinstance(r.get("detail"), dict) else None
        if d is None:
            try:
                d = json.loads(r.get("detail_json") or "{}")
            except ValueError:
                d = {}
        out.append(d or {})
    return out


def _referenced_rows(registry, slug: str, confirmations: dict) -> list[dict]:
    """The services this repository's deployment artifacts RUN but whose images it neither builds nor
    publishes (DESIGN-BLUEPRINT-NODE-ADMISSION.md): not components of the repository, runtime dependencies
    of the deployment it describes. Reclassifications a person made are already applied."""
    from resource_explorer import node_admission

    rows = []
    for r in node_admission.referenced_rows(registry, slug):
        image = r.get("image") or ""
        target = image or r["name"]
        key = f"referenced:{r['scope']}"
        latest = _latest(confirmations.get(key))
        evidence = r.get("evidence") or ""
        artifact = evidence.split("from ", 1)[-1].split(" ")[0] if "from " in evidence else "a deployment artifact"
        moved = r.get("reclassified")
        tail = f" · reclassified by {moved['by']}: {moved['reason']}" if moved else ""
        if latest and latest["verdict"] == VERDICT_CONFIRMED:
            state, words = "confirmed", f"confirmed · by {latest['by']} · from {artifact}"
        elif latest and latest["verdict"] == VERDICT_WITHDRAWN:
            state, words = "withdrawn", f"withdrawn · by {latest['by']} · from {artifact}"
        else:
            state, words = "proposed", f"proposed · from {artifact} · image {image}" if image else f"proposed · from {artifact}"
        rows.append({
            "kind": KIND_RUNTIME, "name": r["name"], "target": target, "source": artifact,
            "ecosystem": "", "state": state, "state_words": words + tail, "key": key,
            "style": "referenced only", "by": (latest or {}).get("by", ""),
            "scope": r["scope"],
        })
    return rows


def _runtime_rows(registry, slug: str, confirmations: dict) -> list[dict]:
    rows = _referenced_rows(registry, slug, confirmations)
    for d in _artifact_rows(registry, slug):
        if d.get("kind") != "wire":
            continue
        ev = d.get("evidence") or {}
        path = ev.get("path", "")
        source, target = d.get("source", ""), d.get("target", "")
        if not (source and target):
            continue
        key = _key(source, target, path)
        latest = _latest(confirmations.get(key))
        artifact = path.rsplit("/", 1)[-1] or "a deployment artifact"
        style = d.get("integrationStyle") or ""
        proto = d.get("protocol") or ""
        if latest and latest["verdict"] == VERDICT_CONFIRMED:
            state, words = "confirmed", f"confirmed · by {latest['by']} · from {artifact}"
        elif latest and latest["verdict"] == VERDICT_WITHDRAWN:
            state, words = "withdrawn", f"withdrawn · by {latest['by']} · from {artifact}"
        else:
            state, words = "proposed", f"proposed · from {artifact}"
        rows.append({
            "kind": KIND_RUNTIME, "name": source,
            "target": target + (f" ({proto})" if proto else ""),
            "source": f"{path}:{ev.get('line')}" if ev.get("line") else path,
            "ecosystem": "", "state": state, "state_words": words, "key": key,
            "style": style, "by": (latest or {}).get("by", ""),
        })
    return rows


def _runtime_section_state(registry, slug: str) -> str:
    """Why a repository has no runtime rows, or '' when it has some. A section that is empty because
    the step never ran is not the same statement as one that ran and found nothing."""
    from resource_explorer.surveyors import survey_snapshot

    if _artifact_rows(registry, slug):
        return ""
    ran = "repo_arch_detect" in ((survey_snapshot.latest(registry, slug) or survey_snapshot.Snapshot(slug)).steps) or \
        bool(registry.query_findings(slug, "architecture_recovery"))
    return NO_ARTIFACT_SENTENCE if ran else NOT_SURVEYED_SENTENCE


def build_table(registry, slug: str) -> dict:
    """The one table: heading, per-kind counts, every row, and the section sentence when a kind is empty."""
    confirmations = read_confirmations(registry, slug)
    rows = _build_rows(registry, slug) + _runtime_rows(registry, slug, confirmations)
    counts = {k: sum(1 for r in rows if r["kind"] == k) for k in KINDS}
    runtime_state = "" if counts[KIND_RUNTIME] else _runtime_section_state(registry, slug)
    from resource_explorer import node_admission
    deploys_only = node_admission.summary(registry, slug)["sentence"]
    # A repository with deployment artifacts that declare no dependency between services still says why.
    if not counts[KIND_RUNTIME] and not runtime_state:
        runtime_state = "deployment artifacts found · none declares a dependency between services"
    return {"heading": HEADING, "kinds": list(KINDS), "counts": counts, "rows": rows,
            "runtime_state": runtime_state,
            # "this repository deploys other software and builds none of its own", when that is the case.
            "deploys_only": deploys_only,
            "summary": " · ".join(f"{counts[k]} {k}" for k in KINDS)}


def runtime_annotations(registry, slug: str) -> list:
    """The CONFIRMED runtime rows as annotations, and nothing else: publishing a runtime dependency is an
    annotation on the repository's survey report, not a relationship (the types for one are not available
    yet). A proposed or withdrawn row publishes nothing."""
    from resource_explorer.surveyors.survey_report import RelationshipAnnotation

    out = []
    for r in _runtime_rows(registry, slug, read_confirmations(registry, slug)):
        if r["state"] != "confirmed":
            continue
        out.append(RelationshipAnnotation(
            summary=f"runtime dependency: {r['name']} depends on {r['target']}",
            analysis_step="repo_dependency", check_name="runtime_dependency", item_key=r["key"],
            related_entity_name=r["target"], relationship_type_name="runtime dependency",
            expression=f"declared in {r['source']}",
            explanation=f"{r['state_words']}. Read from a deployment artifact; a person confirmed it.",
            confidence=100,
            json_properties={"kind": KIND_RUNTIME, "source": r["name"], "target": r["target"],
                             "artifact": r["source"], "confirmed_by": r["by"]}))
    return out
