"""The things a count counted.

Every count on the dashboard names a set — 18 advisories, 68 dependencies,
90 data files, 26,563 symbols, 114 components — and until 2026-09-11 nothing
opened the set. The measurement popup opens the NUMBER's history, so a
reader asking "which 18?" learned that 18 had been 18 for a fortnight. This
module opens the members.

Members are read from the registry, not from the display-shaped results the
dashboard renders: the results readers drop `detail_json`, and that is where
cve_scan keeps its advisory ids. The registry keeps everything.

Members nest, and purpose decides how much of the tree is shown by default.
`scope="public"` is what someone intending to USE the resource wants — the
surface it exposes; `scope="all"` is what someone MAINTAINING it wants — that
plus the internal structure. Maintain is a superset, so this is one tree
with two default expansions, not two screens. Today only symbols carry a
public/internal marker (`is_private`); for every other set the scope is
recorded on the response and changes nothing, so the caller can see that it
was asked for and not honoured rather than assume it was.

`public` is a judgement in a repository, not a fact: `is_private` is inferred
from naming conventions, and the response says so.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from resource_explorer.registry import ProjectRegistry

DEFAULT_LIMIT = 200


@dataclass
class Group:
    name: str
    count: int
    members: list = field(default_factory=list)   # [{name, detail, children?, count?}]
    truncated: bool = False


@dataclass
class MemberSet:
    analysis_id: str
    metric: str
    title: str
    total: int
    scope: str
    scope_honoured: bool
    groups: list = field(default_factory=list)
    note: str = ""
    source: str = ""              # what was read: a table or the findings

    def to_dict(self) -> dict:
        return {
            "analysis_id": self.analysis_id, "metric": self.metric, "title": self.title,
            "total": self.total, "scope": self.scope, "scope_honoured": self.scope_honoured,
            "groups": [{"name": g.name, "count": g.count, "members": g.members, "truncated": g.truncated}
                       for g in self.groups],
            "note": self.note, "source": self.source,
        }


def _row(r):
    return dict(r) if not isinstance(r, dict) else r


def _detail(r) -> dict:
    d = r.get("detail_json")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except ValueError:
            d = {}
    return d if isinstance(d, dict) else {}


# ── readers ───────────────────────────────────────────────────────────────

def _cve_members(registry, slug, scope, limit) -> MemberSet:
    rows = [_row(r) for r in registry.query_findings(slug, "cve_scan")]
    groups: list[Group] = []
    total = 0
    order = {"CRITICAL": 0, "HIGH": 1, "MODERATE": 2, "MEDIUM": 2, "LOW": 3}
    rows.sort(key=lambda r: order.get(str(_detail(r).get("severity", "")).upper(), 9))
    for r in rows:
        d = _detail(r)
        ids = d.get("advisory_ids") or []
        total += len(ids)
        groups.append(Group(
            name=f"{d.get('package') or r['check_name']} {d.get('version') or ''}".strip(),
            count=len(ids),
            members=[{"name": a, "detail": str(d.get("severity") or r.get("label") or "").lower()} for a in ids][:limit],
            truncated=len(ids) > limit,
        ))
    return MemberSet("cve_scan", "advisories", "advisories, by package", total, scope, False, groups,
                     note="Declared dependencies only; severity is OSV's.", source="project_analysis_findings.detail_json")


def _dependency_members(registry, slug, scope, limit) -> MemberSet:
    deps = [_row(d) for d in registry.query_dependencies(slug)]
    by_eco: dict[str, list] = {}
    for d in deps:
        by_eco.setdefault(d.get("ecosystem") or "unknown", []).append(d)
    groups = []
    for eco, items in sorted(by_eco.items(), key=lambda kv: -len(kv[1])):
        items.sort(key=lambda d: (d.get("dep_type") or "", d.get("dep_name") or ""))
        groups.append(Group(eco, len(items), [
            {"name": d.get("dep_name"), "detail": " ".join(x for x in (d.get("dep_version"), d.get("dep_type")) if x)}
            for d in items[:limit]], len(items) > limit))
    return MemberSet("dependency_analysis", "total", "dependencies, by ecosystem", len(deps), scope, False, groups,
                     note="Declared in manifests at the latest indexing; transitive dependencies are not resolved here.",
                     source="project_dependencies")


def _data_file_members(registry, slug, scope, limit) -> MemberSet:
    rows = [_row(r) for r in registry.get_data_profiles(slug)]
    by_fmt: dict[str, list] = {}
    for r in rows:
        by_fmt.setdefault(r.get("format") or "unknown", []).append(r)
    groups = []
    for fmt, items in sorted(by_fmt.items(), key=lambda kv: -len(kv[1])):
        items.sort(key=lambda r: -(r.get("file_size_bytes") or 0))
        groups.append(Group(fmt, len(items), [
            {"name": r.get("file_path"),
             "detail": " × ".join(str(x) for x in (r.get("row_count"), r.get("col_count")) if x is not None) or ""}
            for r in items[:limit]], len(items) > limit))
    return MemberSet("data_file_profiling", "total", "data files, by format", len(rows), scope, False, groups,
                     source="project_data_profiles")


def _symbol_members(registry, slug, scope, limit) -> MemberSet:
    """Symbols nest file -> symbol, and this is the one set where scope is
    real: `public` drops rows marked private. The marker is inferred from
    naming, so the note says so."""
    where = "project_slug = ?" + ("" if scope == "all" else " AND COALESCE(is_private, 0) = 0")
    with registry._conn() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM project_code_symbols WHERE {where}", (slug,)).fetchone()
        total = _row(total).get("count", None) if isinstance(total, dict) else total[0]
        files = [_row(r) for r in conn.execute(
            f"SELECT file_path, language, COUNT(*) AS n FROM project_code_symbols WHERE {where} "
            "GROUP BY file_path, language ORDER BY n DESC LIMIT ?", (slug, limit)).fetchall()]
        nfiles = conn.execute(f"SELECT COUNT(DISTINCT file_path) FROM project_code_symbols WHERE {where}", (slug,)).fetchone()
        nfiles = _row(nfiles).get("count", None) if isinstance(nfiles, dict) else nfiles[0]
    by_lang: dict[str, list] = {}
    for f in files:
        by_lang.setdefault(f.get("language") or "unknown", []).append(f)
    groups = []
    for lang, items in sorted(by_lang.items(), key=lambda kv: -sum(i["n"] for i in kv[1])):
        groups.append(Group(lang, sum(i["n"] for i in items), [
            {"name": f["file_path"], "count": f["n"], "children_key": f"file:{f['file_path']}"} for f in items], False))
    # The honest number beside the misleading one: a project indexed before
    # 2026-09-11 still counts vendored code as its own until re-indexed, and
    # the inventory summary is how the rail says so rather than hiding it.
    inv = registry.file_inventory_summary(slug)
    provenance = (f"{inv['own']:,} of {inv['total']:,} files are this repository's own; "
                  f"{inv['vendored']:,} vendored and not counted." if inv["vendored"]
                  else f"{nfiles} files. Indexed {inv['indexed_at'][:10] or 'unknown'}; an index before "
                       "2026-09-11 counts vendored code as the repository's own until re-indexed.")
    return MemberSet("api_structure", "symbol_count",
                     "symbols, by language and file" + ("" if scope == "all" else " — public only"),
                     int(total or 0), scope, True, groups,
                     note=f"{provenance} `public` is inferred from naming conventions, not declared; a maintainer's marking would be better.",
                     source="project_code_symbols")


def _symbols_in_file(registry, slug, file_path, scope, limit) -> list[dict]:
    where = "project_slug = ? AND file_path = ?" + ("" if scope == "all" else " AND COALESCE(is_private, 0) = 0")
    with registry._conn() as conn:
        rows = [_row(r) for r in conn.execute(
            f"SELECT qualified_name, kind, COALESCE(is_private,0) AS is_private FROM project_code_symbols WHERE {where} "
            "ORDER BY kind, qualified_name LIMIT ?", (slug, file_path, limit)).fetchall()]
    return [{"name": r["qualified_name"], "detail": (r.get("kind") or "") + (" · private" if r.get("is_private") else "")} for r in rows]


def _component_members(registry, slug, scope, limit) -> MemberSet:
    with registry._conn() as conn:
        rows = [_row(r) for r in conn.execute(
            "SELECT qualified_name, scope_locator FROM architecture_materialized_components "
            "WHERE entity_slug = ? ORDER BY scope_locator, qualified_name LIMIT ?", (slug, limit)).fetchall()]
        total = conn.execute("SELECT COUNT(*) FROM architecture_materialized_components WHERE entity_slug = ?", (slug,)).fetchone()
        total = _row(total).get("count", None) if isinstance(total, dict) else total[0]
    by_scope: dict[str, list] = {}
    for r in rows:
        by_scope.setdefault(r.get("scope_locator") or "(whole repository)", []).append(r)
    groups = [Group(k, len(v), [{"name": r["qualified_name"].split("::")[-1], "detail": ""} for r in v], False)
              for k, v in by_scope.items()]
    return MemberSet("architecture_recovery", "component_count", "components, by scope", int(total or 0), scope, False, groups,
                     note="Materialized components only — what was published, not every candidate the recovery found.",
                     source="architecture_materialized_components")


def _findings_members(registry, slug, analysis_id, scope, limit) -> MemberSet:
    """The fallback: a finding row per member, grouped by verdict, with the
    detail the display readers drop."""
    rows = [_row(r) for r in registry.query_findings(slug, analysis_id)]
    by_label: dict[str, list] = {}
    for r in rows:
        by_label.setdefault(str(r.get("label") or ""), []).append(r)
    groups = []
    for label, items in sorted(by_label.items(), key=lambda kv: -len(kv[1])):
        groups.append(Group(label or "(no verdict)", len(items), [
            {"name": r.get("check_name"), "detail": (r.get("summary") or "")[:160], "extra": _detail(r) or None}
            for r in items[:limit]], len(items) > limit))
    return MemberSet(analysis_id, "findings", "findings, by verdict", len(rows), scope, False, groups,
                     source="project_analysis_findings")


_READERS = {
    ("cve_scan", None): _cve_members,
    ("dependency_analysis", None): _dependency_members,
    ("manifest_parse", "dependency_count"): _dependency_members,
    ("data_file_profiling", None): _data_file_members,
    ("api_structure", "symbol_count"): _symbol_members,
    ("code_symbol_extraction", "symbol_count"): _symbol_members,
    ("code_symbol_extraction", None): _symbol_members,
    ("architecture_recovery", None): _component_members,
    ("architecture_summary", "components"): _component_members,
}


def members_for(registry: ProjectRegistry, slug: str, analysis_id: str, metric: str = "",
                scope: str = "public", limit: int = DEFAULT_LIMIT) -> MemberSet:
    scope = "all" if scope == "all" else "public"
    reader = _READERS.get((analysis_id, metric or None)) or _READERS.get((analysis_id, None))
    if reader is not None:
        return reader(registry, slug, scope, limit)
    return _findings_members(registry, slug, analysis_id, scope, limit)


def children_for(registry: ProjectRegistry, slug: str, analysis_id: str, key: str,
                 scope: str = "public", limit: int = DEFAULT_LIMIT) -> list[dict]:
    """One level down. Keys are opaque to the client: `file:<path>` today."""
    scope = "all" if scope == "all" else "public"
    if key.startswith("file:") and analysis_id in ("api_structure", "code_symbol_extraction"):
        return _symbols_in_file(registry, slug, key[5:], scope, limit)
    return []
