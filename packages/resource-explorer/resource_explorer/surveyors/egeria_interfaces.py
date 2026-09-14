"""Which Egeria view services a repository CONSUMES, and how much it uses
Dr.Egeria — the "interfaces RE (or any repo) consumes from Egeria" layer of
"Cataloguing in layers" (project owner, 2026-09-14). Relationships from a
repository to the Egeria platform's EXISTING view-service capabilities — one
per pyegeria client class it uses — not new elements to create.

**Zero-fetch, and honest about what that costs.** `project_code_symbols`
(repo_symbol_extraction's table) holds only symbol DEFINITIONS the surveyed
repo itself declares — classes, functions, methods — never `import`
statements and never call/instantiation sites (confirmed by reading
`registry.py`'s schema and `ingestion/code_symbol_extractor.py` before
building this: there is no imports table anywhere in this codebase). So this
module cannot see `from pyegeria.omvs import ClassificationExplorer`, which is
how a repo actually consumes a client. What it CAN see, without any new
fetch: a defined symbol whose own SIGNATURE, RETURN TYPE, or base-class list
(inheritance — `project_code_relationships`) names one of pyegeria's client
classes as a type. That is real evidence (nobody writes `client:
ClassificationExplorer` by accident) but it systematically undercounts —
the common `self.client = ClassificationExplorer(...)` pattern inside
`__init__` leaves no trace in either table. Every match this module produces
carries its `basis` (which field matched) so a reader is never handed a bare
number that looks more complete than it is.

Dr.Egeria usage is the same shape again, one level worse: `## Create …`/
`## Link …` command-family headings live in markdown CONTENT, and
`project_file_inventory` stores paths only (confirmed the same way, against
`registry.py`'s schema). Paths under `docs/dr-egeria/**` (or any `dr-egeria`/
`dr_egeria` path segment) ARE a genuine zero-fetch presence signal; a
best-effort per-file FAMILY name, guessed from a command-shaped filename
(`create-term.md` -> family `create_term`), is offered alongside it but
marked with its own `could_not_check` note, because the real family list
lives in headings this module has never been handed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

_DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "configdata" / "egeria_view_services.yaml"
)

NOTHING_FOUND = "nothing_found"
CHECKED = "checked"


class EgeriaViewServiceMappingError(ValueError):
    """The client-class -> view-service mapping is malformed."""


@dataclass(frozen=True)
class ViewServiceClient:
    client_class: str
    module: str
    view_service: str | None
    url_slug: str | None
    shares_path_with: str | None = None


@lru_cache(maxsize=4)
def load_mapping(path: Path | str | None = None) -> tuple[ViewServiceClient, ...]:
    """The curated pyegeria client_class -> view_service table, validated."""
    import yaml

    p = Path(path) if path else _DEFAULT_MAPPING_PATH
    try:
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise EgeriaViewServiceMappingError(f"mapping file not found: {p}") from exc
    entries = raw.get("client_classes")
    if not isinstance(entries, list) or not entries:
        raise EgeriaViewServiceMappingError(f"{p}: 'client_classes' must be a non-empty list")

    allowed = {"client_class", "module", "view_service", "url_slug", "shares_path_with"}
    out: list[ViewServiceClient] = []
    seen: set[str] = set()
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise EgeriaViewServiceMappingError(f"{p}: client_classes[{i}] is not a mapping")
        unknown = set(e) - allowed
        if unknown:
            raise EgeriaViewServiceMappingError(
                f"{p}: client_classes[{i}] has unknown keys {sorted(unknown)}")
        cls = str(e.get("client_class") or "").strip()
        if not cls:
            raise EgeriaViewServiceMappingError(f"{p}: client_classes[{i}] has no client_class")
        if cls in seen:
            raise EgeriaViewServiceMappingError(f"{p}: client_class {cls!r} listed twice")
        seen.add(cls)
        out.append(ViewServiceClient(
            client_class=cls,
            module=str(e.get("module") or "").strip(),
            view_service=(str(e["view_service"]).strip() if e.get("view_service") else None),
            url_slug=(str(e["url_slug"]).strip() if e.get("url_slug") else None),
            shares_path_with=(str(e["shares_path_with"]).strip() if e.get("shares_path_with") else None),
        ))
    return tuple(out)


def clear_cache() -> None:
    load_mapping.cache_clear()


@dataclass
class ClientMatch:
    client: ViewServiceClient
    #: Which symbol-table field(s) produced the match, and the matching
    #: symbol's own qualified_name — so a reader can independently verify
    #: (or dismiss) a hit rather than trust a bare count.
    #: {"qualified_name": ..., "matched_field": "signature"|"return_type"|"base_class", "file_path": ...}
    evidence: list[dict] = field(default_factory=list)

    @property
    def symbol_count(self) -> int:
        return len(self.evidence)


@dataclass
class ViewServiceUsage:
    """One view service, aggregated over every client class that maps to it
    (RegisteredInfo/AssetCatalog both map to "Asset Catalog", for instance)."""
    view_service: str
    client_matches: list[ClientMatch]

    @property
    def client_classes(self) -> list[str]:
        return sorted({m.client.client_class for m in self.client_matches})

    @property
    def symbol_count(self) -> int:
        return sum(m.symbol_count for m in self.client_matches)


@dataclass
class DrEgeriaFamily:
    name: str
    paths: list[str]
    #: Whether `name` is a real command-family name (from a heading — never
    #: true here, since headings are content) or a guess from the filename.
    basis: str = "filename_guess"


@dataclass
class InterfaceAssessment:
    view_services: list[ViewServiceUsage]
    #: Symbols that mentioned a known pyegeria class name but whose match
    #: could not be attributed to a mapped view service (mapping has
    #: view_service=None) — named, not dropped.
    unmapped_client_classes: list[str]
    dr_egeria_doc_paths: list[str]
    dr_egeria_families: list[DrEgeriaFamily]
    #: "checked" | "nothing_found" — nothing_found means pyegeria is not even
    #: a declared dependency, which is a real, provable zero: this repo
    #: cannot be consuming Egeria view services it never imports.
    state: str
    #: Explains what evidence sources were consulted and their limits — see
    #: module docstring. Always populated so a reader never has to guess why
    #: a number looks low.
    basis_note: str = ""

    def as_findings(self) -> list[dict]:
        rows = []
        for vs in self.view_services:
            rows.append({
                "check_name": "view_service",
                "item_key": vs.view_service,
                "label": vs.view_service,
                "summary": (f"{vs.view_service} — via {', '.join(vs.client_classes)} "
                            f"({vs.symbol_count} symbol reference(s))"),
                "confidence": 60,  # never higher: see basis_note — this is a lower bound
                "detail": {
                    "client_classes": vs.client_classes,
                    "symbol_count": vs.symbol_count,
                    "evidence": [m.evidence for m in vs.client_matches],
                },
            })
        for fam in self.dr_egeria_families:
            rows.append({
                "check_name": "dr_egeria_family",
                "item_key": fam.name,
                "label": fam.name,
                "summary": f"{fam.name} — {len(fam.paths)} file(s), name guessed from filename (not headings)",
                "confidence": 30,
                "detail": {"paths": fam.paths, "basis": fam.basis},
            })
        rows.append({
            "check_name": "coverage",
            "label": self.state,
            "summary": self.headline(),
            "confidence": 100 if self.state == NOTHING_FOUND else 40,
            "detail": {
                "view_services": len(self.view_services),
                "client_classes": sum(len(vs.client_classes) for vs in self.view_services),
                "unmapped_client_classes": self.unmapped_client_classes,
                "dr_egeria_doc_count": len(self.dr_egeria_doc_paths),
                "dr_egeria_families": len(self.dr_egeria_families),
                "state": self.state,
                "basis_note": self.basis_note,
            },
        })
        return rows

    def headline(self) -> str:
        if self.state == NOTHING_FOUND:
            return "No pyegeria dependency found — does not consume Egeria view services"
        n_vs = len(self.view_services)
        n_cls = sum(len(vs.client_classes) for vs in self.view_services)
        n_fam = len(self.dr_egeria_families)
        return (f"uses {n_vs} Egeria view service{'s' if n_vs != 1 else ''} via "
                f"{n_cls} pyegeria client{'s' if n_cls != 1 else ''}; "
                f"{n_fam} Dr.Egeria command famil{'y' if n_fam == 1 else 'ies'}")


_DR_EGERIA_PATH_RE = re.compile(r"(^|/)dr[-_]egeria(/|$)", re.IGNORECASE)
_COMMAND_FILENAME_RE = re.compile(
    r"^(create|link|update|delete|remove|attach|detach|classify|declassify|view|list)[-_][a-z0-9_-]+$",
    re.IGNORECASE,
)


def _dr_egeria_evidence(file_inventory_paths: list[str]) -> tuple[list[str], list[DrEgeriaFamily]]:
    doc_paths = [p for p in file_inventory_paths if _DR_EGERIA_PATH_RE.search(p.replace("\\", "/"))]
    by_family: dict[str, list[str]] = {}
    for p in doc_paths:
        stem = Path(p).stem.lower()
        if _COMMAND_FILENAME_RE.match(stem):
            by_family.setdefault(stem.replace("-", "_"), []).append(p)
    families = [DrEgeriaFamily(name=n, paths=sorted(ps)) for n, ps in sorted(by_family.items())]
    return sorted(doc_paths), families


def assess(
    *,
    pyegeria_declared: bool,
    code_symbol_rows: list[dict],
    inherits_from_rows: list[dict],
    file_inventory_paths: list[str],
    mapping: tuple[ViewServiceClient, ...] | None = None,
) -> InterfaceAssessment:
    """Pure: classify which Egeria view services a repo's code symbols
    indicate consumption of, plus Dr.Egeria doc/command-family evidence.

    `pyegeria_declared` — whether `project_dependencies` names pyegeria for
    this repo (from `dependency_support`'s own matcher, or a direct check);
    when False, the result is `nothing_found` and code symbols are not
    scanned at all — a repo that never imports pyegeria cannot consume its
    view services, which is provable from data already collected.

    `code_symbol_rows` — `project_code_symbols` rows: need `qualified_name`,
    `signature`, `return_type`, `file_path` (parent_class is read from
    `inherits_from_rows` instead, since that is where base-class NAMES that
    are not themselves defined in the repo actually live).
    `inherits_from_rows` — `project_code_relationships` rows,
    relationship_type="inherits_from": need `source_name`, `target_name`.
    """
    basis_note = (
        "project_code_symbols records only symbol DEFINITIONS (no import "
        "statements, no call/instantiation sites), so this counts a pyegeria "
        "class name appearing in a symbol's own signature/return-type text or "
        "as a base class — real evidence, but a floor, not a full count: "
        "'self.client = ClassificationExplorer(...)' inside a method body "
        "leaves no trace in either table."
    )
    if not pyegeria_declared:
        return InterfaceAssessment(
            view_services=[], unmapped_client_classes=[], dr_egeria_doc_paths=[],
            dr_egeria_families=[], state=NOTHING_FOUND,
            basis_note="pyegeria is not a declared dependency of this repository",
        )

    techs = mapping or load_mapping()
    by_view_service: dict[str, list[ClientMatch]] = {}
    unmapped: set[str] = set()

    def _match_field(vsc: ViewServiceClient, text: str, field_name: str, qn: str, fp: str,
                      by_class: dict[str, ClientMatch]) -> None:
        if not text or vsc.client_class not in text:
            return
        # Whole-identifier match only — "ClassificationExplorer" must not
        # match inside "MyClassificationExplorerSubclass" being a DIFFERENT
        # identifier that merely contains it as a substring elsewhere in a
        # longer signature; a word-boundary regex is the cheap, correct guard.
        if not re.search(rf"\b{re.escape(vsc.client_class)}\b", text):
            return
        m = by_class.setdefault(vsc.client_class, ClientMatch(client=vsc))
        m.evidence.append({"qualified_name": qn, "matched_field": field_name, "file_path": fp})

    by_class_per_service: dict[str, dict[str, ClientMatch]] = {}
    for row in code_symbol_rows:
        qn = str(row.get("qualified_name") or "")
        fp = str(row.get("file_path") or "")
        for field_name in ("signature", "return_type"):
            text = str(row.get(field_name) or "")
            if not text:
                continue
            for vsc in techs:
                svc_key = vsc.view_service or f"__unmapped__::{vsc.client_class}"
                _match_field(vsc, text, field_name, qn, fp,
                            by_class_per_service.setdefault(svc_key, {}))

    for rel in inherits_from_rows:
        base = str(rel.get("target_name") or "")
        source = str(rel.get("source_name") or "")
        for vsc in techs:
            if base == vsc.client_class or base.endswith("." + vsc.client_class):
                svc_key = vsc.view_service or f"__unmapped__::{vsc.client_class}"
                m = by_class_per_service.setdefault(svc_key, {}).setdefault(
                    vsc.client_class, ClientMatch(client=vsc))
                m.evidence.append({"qualified_name": source, "matched_field": "base_class", "file_path": ""})

    for svc_key, by_class in by_class_per_service.items():
        if not by_class:
            continue
        if svc_key.startswith("__unmapped__::"):
            unmapped.update(by_class.keys())
            continue
        by_view_service[svc_key] = list(by_class.values())

    view_services = [
        ViewServiceUsage(view_service=svc, client_matches=matches)
        for svc, matches in sorted(by_view_service.items())
    ]

    doc_paths, families = _dr_egeria_evidence(file_inventory_paths)

    return InterfaceAssessment(
        view_services=view_services,
        unmapped_client_classes=sorted(unmapped),
        dr_egeria_doc_paths=doc_paths,
        dr_egeria_families=families,
        state=CHECKED,
        basis_note=basis_note,
    )
