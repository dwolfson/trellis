"""Assemble the API reference for a repository: which sources exist, which is best, how they differ.

Preference (committed spec > running instance > derived from code) is one function, `best_interface`, used by
the pane, the chat compile and the drill-down, so the three cannot disagree about which source they quote.
"""
from __future__ import annotations

import logging

from resource_explorer.api_reference import committed, live
from resource_explorer.api_reference.compare import compare_interfaces
from resource_explorer.api_reference.derived import derive_from_code
from resource_explorer.api_reference.model import (
    SOURCE_COMMITTED, SOURCE_DERIVED, SOURCE_LIVE, SOURCE_PREFERENCE, Interface, kind_noun)

log = logging.getLogger(__name__)


def spec_interfaces(registry, slug: str):
    """(committed interfaces, committed problems, running-instance interface | None). Stored data only."""
    try:
        c_ifaces, problems = committed.load_committed(registry, slug)
    except Exception:
        log.warning("committed specs unreadable for %s", slug, exc_info=True)
        c_ifaces, problems = [], []
    try:
        l_iface = live.instance_interface(registry, slug)
    except Exception:
        log.warning("running-instance document unreadable for %s", slug, exc_info=True)
        l_iface = None
    return c_ifaces, problems, l_iface


def best_spec_interface(registry, slug: str) -> Interface | None:
    """The best interface that is an actual description (committed, else running instance); None when only code
    (or nothing) is known."""
    c_ifaces, _problems, l_iface = spec_interfaces(registry, slug)
    return c_ifaces[0] if c_ifaces else l_iface


def best_interface(registry, slug: str) -> Interface | None:
    return best_spec_interface(registry, slug) or derive_from_code(registry, slug)


_MISSING = {
    SOURCE_COMMITTED: "no committed OpenAPI/Swagger file recorded (a repository surveyed before spec capture "
                      "existed shows this until it is re-surveyed)",
    SOURCE_LIVE: "no running-instance URL is registered",
    SOURCE_DERIVED: "not measured: no code markers were captured for this repository, which is not the same as "
                    "having no routes",
}


def build_reference(registry, slug: str) -> dict:
    c_ifaces, problems, l_iface = spec_interfaces(registry, slug)
    d_iface = derive_from_code(registry, slug)
    ordered = list(c_ifaces) + ([l_iface] if l_iface else []) + ([d_iface] if d_iface else [])
    have = {i.source for i in ordered}
    missing = [{"source": s, "reason": _MISSING[s]} for s in SOURCE_PREFERENCE if s not in have]
    best = ordered[0] if ordered else None
    comparisons: list = []
    seen: set = {best.source} if best else set()
    for other in ordered[1:]:
        if other.source in seen:
            continue
        seen.add(other.source)
        comparisons.append(compare_interfaces(best, other))
    return {
        "slug": slug,
        "interfaces": [i.api_payload() for i in ordered],
        "best": best.source if best else "",
        "comparisons": comparisons,
        "missing": missing,
        "problems": problems,
        "instance": live.instance_status(live.load_instance(registry, slug)),
    }


# ── what the chat compile shows ────────────────────────────────────────────

def _first_line(text: str) -> str:
    for line in (text or "").strip().splitlines():
        if line.strip():
            return line.strip()[:120]
    return ""


def operation_line(op, iface: Interface) -> str:
    summary = op.summary or _first_line(op.description)
    bits = [op.name]
    if summary:
        bits.append(f"— {summary}")
    tags = f" [{', '.join(op.tags)}]" if op.tags else ""
    auth = ""
    if op.security:
        auth = f" [auth: {', '.join(op.security)}]"
    elif iface.security_schemes:
        auth = " [auth: none declared]"
    dep = " [deprecated]" if op.deprecated else ""
    return " ".join(bits) + tags + auth + dep


def spec_heading(iface: Interface) -> str:
    ident = " ".join(x for x in (iface.spec_version, f'"{iface.title}"' if iface.title else "", iface.version) if x)
    return f"endpoint list ({iface.source_phrase}; {ident})"


def render_spec_lines(iface: Interface, limit: int, others: list) -> list:
    """The section text for the model from a described interface. `others` are comparison dicts (best vs another
    source). The opening line carries the total and the shown count."""
    n = len(iface.operations)
    noun = kind_noun(iface.kind)
    shown = min(n, limit)
    head = (f"- endpoints: {n} {noun} found, {shown} of {n} shown to the model" if n > limit
            else f"- endpoints: {n} {noun} found, all shown")
    lines = [head]
    if iface.security_schemes:
        lines.append("- security schemes: " + ", ".join(f"{k} ({v})" if v else k for k, v in iface.security_schemes.items()))
    lines += [f"  - {operation_line(o, iface)}" for o in iface.operations[:limit]]
    lines += [f"- {n}" for n in iface.notes]
    for c in others:
        b = c["b"]
        lead = {SOURCE_DERIVED: "also found in code", SOURCE_LIVE: "also from the running instance",
                SOURCE_COMMITTED: "also in a committed spec"}.get(b["source"], "also")
        unit = "route(s)" if b["source"] == SOURCE_DERIVED else "operation(s)"
        extra = f", {len(c['probable'])} more match ignoring a path prefix" if c["probable"] else ""
        lines.append(f"- {lead}: {b['count']} {unit}; {c['both']} match this list{extra}, "
                     f"{len(c['only_b'])} only there, {len(c['only_a'])} only in this list "
                     f"(the API reference pane lists the differences; the reason is not decided)")
    return lines
