"""Render a recovered architecture as Mermaid, at publish time.

**Why this exists at all.** Under *report, then curate*
(`docs/architecture-recovery-report-then-curate.md`), RE publishes what the
analysis *proposes* and a curator decides whether to create real Egeria
artifacts. A curator may decline precisely because the fit is not good enough
to use — and they cannot see that from a list of component names. The shape is
the decision instrument, so the proposal has to be legible before it exists.

**Why RE draws it rather than Egeria.** pyegeria supports `output_format=
"MERMAID"`, and it is tempting to assume that covers this. It cannot: that path
graphs *Egeria elements*, and a proposal's components are not elements yet —
that is the entire point of report-then-curate, so there is nothing to
traverse. The diagram must therefore be produced here, from the IR, and carried
in the annotation as a record of what the analysis said, captured alongside the
evidence it was drawn from. After materialisation pyegeria's renderer becomes
usable, which is what makes "what I approved" versus "what exists" a diff of
two diagrams.

**The shape mirrors materialisation deliberately.** Blueprints are subgraphs
because a `SolutionBlueprint` is a Collection of components; nesting is drawn
because `SolutionComposition` nests components natively (design §3.3a); wire
direction follows `SolutionPortDirection`. Judging this picture is meant to be
judging the thing that would be created.

**Determinism is a requirement, not a nicety.** This text goes into an
annotation that is republished on every re-derivation, so an unchanged analysis
must render byte-identically — otherwise every run looks like a change, and the
outbox/retry work (`docs/outbox-publishing-design.md`) is trying to converge on
a value that never settles. Everything here sorts; nothing samples, hashes by
address, or reads the clock.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .ir import IR, Component
from . import projection, scope_hierarchy

#: Mermaid node ids must be identifier-ish. Slugs carry `/`, `::`, `.` and `-`.
_ID_UNSAFE = re.compile(r"[^0-9A-Za-z_]")

#: Kroki's Mermaid worker refuses a source larger than this
#: (`MaxTextSizeError: Diagram source is too large: N characters (maximum is
#: 50000)`), measured 2026-08-29 against `egeria-shared-kroki` — `genaiexamples`
#: renders to 59,791 characters and is rejected. Recorded as a named limit
#: rather than a truncation: a silently shortened architecture is a *different*
#: architecture, and this is the one diagram in the corpus that hits it.
RENDERER_CHAR_LIMIT = 50_000

#: Confidence at or below this renders as provisional. Not a threshold the
#: analysis uses for anything else — purely a reading aid, so a curator can see
#: which parts of a proposal are weak without opening the evidence table.
LOW_CONFIDENCE = 50


def _nid(slug: str) -> str:
    """A stable Mermaid id for a slug.

    Deliberately *not* a hash: a reader comparing two runs' diagrams should be
    able to see which node is which. Collisions are made impossible by keeping
    the sanitised slug in full rather than truncating it.
    """
    return "n_" + _ID_UNSAFE.sub("_", slug)


def _label(text: str) -> str:
    """Mermaid label text. Quotes and brackets end a label early, and a newline
    ends the statement — all three appear in real component names and port
    details, so none of them can be passed through."""
    return (text.replace("\\", "/")
                .replace('"', "'")
                .replace("[", "(").replace("]", ")")
                .replace("{", "(").replace("}", ")")
                .replace("\n", " ")
                .strip())


def _structural_slugs(components: Iterable[Component]) -> set[str]:
    """Parents that are referenced but are not themselves components.

    Shares `scope_hierarchy.missing_ancestors` with `persist.py`, which
    synthesises exactly these as `structural_node` findings. The two must agree:
    a node drawn as a component here but persisted as structural (or the
    reverse) would show a curator a different architecture from the one the
    findings describe.
    """
    return set(scope_hierarchy.missing_ancestors(components))


class _Structural:
    """A grouping node that is not a Component, and must not be built as one.

    `persist.py` synthesises these as `structural_node` findings with no type
    and confidence 0. Constructing a real `Component` here would require an
    `Identity` — a claim about how the thing was identified — and there is no
    honest value for it: nothing detected this node, its children were
    detected. So it gets the minimum surface the renderer walks, and nothing
    that would let it be mistaken for a component downstream.
    """
    __slots__ = ("slug", "name", "type", "confidence", "parent_slug", "depth", "blueprint")

    def __init__(self, slug: str, parent_slug: str = "") -> None:
        self.slug = slug
        self.name = slug.rsplit("/", 1)[-1] if "/" in slug else slug
        self.type = None
        self.confidence = 0
        self.parent_slug = parent_slug
        self.depth = slug.count("/")
        self.blueprint = ""


def _with_structural(shown: list[Component], structural: set[str]) -> list:
    """`shown` plus a node for every structural parent it references.

    Without this a structural parent is referenced by its children and never
    drawn, so the children render as unrelated roots — the grouping the
    hierarchy work exists to produce would be invisible in the one artefact a
    curator actually reads.
    """
    known = {c.slug for c in shown}
    nodes: list = list(shown)
    for slug in sorted(structural):
        if slug in known:
            continue
        parent = scope_hierarchy.parent_of(slug)
        node = _Structural(slug, parent if parent in structural else "")
        # A grouping node inherits its children's blueprint when they agree.
        # Without this the group renders outside the blueprint subgraph its own
        # members belong to, splitting one solution into two visual groups —
        # which is exactly the wrong answer to "is this one solution?", the
        # question a curator is being asked.  Disagreement leaves it blank
        # rather than picking a winner: children spanning two blueprints is a
        # fact worth seeing, not one to resolve by majority.
        bps = {c.blueprint for c in shown if c.parent_slug == slug}
        node.blueprint = bps.pop() if len(bps) == 1 else ""
        nodes.append(node)
    return nodes


def _children_of(components: list) -> dict[str, list]:
    kids: dict[str, list[Component]] = {}
    for c in components:
        kids.setdefault(c.parent_slug or "", []).append(c)
    for v in kids.values():
        v.sort(key=lambda c: c.slug)
    return kids


def _component_line(c, structural: bool, enclosing_blueprint: str = "") -> str:
    """One node. Structural grouping nodes must be visibly distinct from
    components — `scope_hierarchy` refuses to emit them as components because
    they have no evidence of their own, and a diagram that hides that
    distinction would invent the evidence the analysis declined to invent."""
    if structural:
        # Rounded, no type, explicitly labelled as grouping.
        return f'{_nid(c.slug)}("{_label(c.name)}<br/><i>grouping only</i>")'
    kind = _label(c.type or "unclassified")
    conf = f"{c.confidence}%"
    marker = " ⚠" if c.confidence <= LOW_CONFIDENCE else ""
    # Blueprint membership is Collection membership, which is independent of
    # composition: a nested component may belong to a different blueprint from
    # the one enclosing it. Nesting is drawn structurally, so where the two
    # disagree the membership is stated on the node — otherwise a component
    # inside a grouping node appears to belong to whatever encloses it, which
    # is a claim the analysis never made.
    bp = ""
    if c.blueprint and c.blueprint != enclosing_blueprint:
        bp = f" · blueprint: {_label(c.blueprint)}"
    return f'{_nid(c.slug)}["{_label(c.name)}<br/><small>{kind} · {conf}{marker}{bp}</small>"]'


def _port_lines(ports: list[dict], owner_slugs: set[str]) -> list[str]:
    """Ports as their own nodes attached to their component.

    Drawn rather than summarised because the *direction* is the thing a
    suitability question turns on — "does it serve an API" and "does it call
    one" are different answers, and a count collapses them.
    """
    out: list[str] = []
    for p in sorted(ports, key=lambda p: (str(p.get("component", "")), str(p.get("name", "")))):
        owner = str(p.get("component") or "")
        if owner not in owner_slugs:
            # An unowned port is dropped rather than attached to a guess. It is
            # reported in the caption instead, so the omission is visible.
            continue
        pid = _nid(f"port::{owner}::{p.get('name')}")
        proto = _label(str(p.get("protocol") or ""))
        direction = str(p.get("direction") or "Unknown")
        ops = (p.get("additionalProperties") or {}).get("operationCount")
        detail = f"{proto}" + (f" · {ops} ops" if ops else "")
        out.append(f'{pid}(["{_label(str(p.get("name")))}<br/><small>{detail}</small>"])')
        # Arrow follows SolutionPortDirection: Input flows in, Output flows out,
        # Input-Output is served (arrow in), Output-Input is called (arrow out).
        if direction in ("Input", "Input-Output"):
            out.append(f"{pid} --> {_nid(owner)}")
        elif direction in ("Output", "Output-Input"):
            out.append(f"{_nid(owner)} --> {pid}")
        else:
            out.append(f"{_nid(owner)} --- {pid}")
    return out


def _resolve_endpoint(value: str, by_slug: dict[str, Component],
                      by_name: dict[str, Component]) -> str | None:
    """Wire endpoints are not guaranteed to be component slugs.

    `interfaces.propose` attributes compose wires by *service name*
    (`_wire_dict(name, service_names.get(dep, dep), …)`) while ports are
    attributed by component slug (`_owner_of`). Both are resolved here, and an
    endpoint matching neither returns None so the caller can draw it as
    external rather than silently dropping the wire — a missing edge is a
    different architecture, not a tidier one.
    """
    if value in by_slug:
        return value
    hit = by_name.get(value)
    return hit.slug if hit else None


def render(ir: IR, max_depth: int | None = projection.DEFAULT_PROJECTION_DEPTH) -> str:
    """The proposal as a Mermaid flowchart.

    `max_depth` is the projection level (`projection.project`), not a filter on
    what was found — the full hierarchy is always persisted, and this chooses
    what to *show*. Which depth a curator should see first is genuinely open;
    the default is the same one a results reader gets.
    """
    projected = projection.project(ir.components, max_depth)
    structural = _structural_slugs(ir.components)
    # Only structural parents that some SHOWN component still references: a
    # projection to a shallow depth can drop every child of a group, and a
    # grouping node with nothing left to group is a level a reader steps
    # through for nothing (`scope_hierarchy`: "a parent of one child is not a
    # parent" — the same reasoning, applied to display).
    still_referenced = {c.parent_slug for c in projected if c.parent_slug} & structural
    shown = _with_structural(projected, still_referenced)
    by_slug = {c.slug: c for c in shown}
    by_name = {c.name: c for c in shown}
    shown_slugs = set(by_slug)
    kids = _children_of(shown)

    lines: list[str] = ["flowchart TD"]

    #: Structural slugs actually drawn as a NODE (rather than as a subgraph
    #: title), so the class statement never names an id that does not exist.
    structural_nodes: list[str] = []

    def emit(c, indent: str, enclosing_bp: str = "") -> None:
        children = [k for k in kids.get(c.slug, []) if k.slug in shown_slugs]
        is_structural = c.slug in structural
        # What the node this one sits inside claims about blueprint membership;
        # a grouping node passes its own (possibly inherited) value down.
        inner_bp = c.blueprint or enclosing_bp
        if children:
            # A node with children is a subgraph — SolutionComposition. A
            # structural parent says so in the title: it is the subgraph
            # itself, so there is no node to carry the marker, and a reader
            # must still be able to tell a real component that happens to have
            # children from a grouping node that only ever had children.
            title = _label(c.name) + (" — grouping only" if is_structural else "")
            lines.append(f'{indent}subgraph {_nid(c.slug)}_g["{title}"]')
            lines.append(f"{indent}  direction TB")
            if not is_structural:
                lines.append(f"{indent}  {_component_line(c, False, enclosing_bp)}")
            for k in children:
                emit(k, indent + "  ", inner_bp)
            lines.append(f"{indent}end")
        else:
            lines.append(f"{indent}{_component_line(c, is_structural, enclosing_bp)}")
            if is_structural:
                structural_nodes.append(c.slug)

    # Blueprint grouping. A repo may hold several — a repo is a storage
    # boundary, not a solution boundary (design §3.3a, corrected 2026-08-29) —
    # so this groups by the `blueprint` a component was assigned rather than
    # assuming one per repo. Components with no blueprint are drawn ungrouped
    # rather than swept into a default one they were never assigned to.
    roots = [c for c in shown if (c.parent_slug or "") not in shown_slugs]
    by_blueprint: dict[str, list[Component]] = {}
    for c in roots:
        by_blueprint.setdefault(c.blueprint or "", []).append(c)

    for bp in sorted(k for k in by_blueprint if k):
        lines.append(f'subgraph bp_{_nid(bp)}["Blueprint: {_label(bp)}"]')
        lines.append("  direction TB")
        for c in sorted(by_blueprint[bp], key=lambda c: c.slug):
            emit(c, "  ", bp)
        lines.append("end")
    for c in sorted(by_blueprint.get("", []), key=lambda c: c.slug):
        emit(c, "")

    # Ports attach to components, never to a grouping node — a structural node
    # has no interface of its own, by definition.
    lines.extend(_port_lines(ir.ports, shown_slugs - structural))

    # Wires. `oneWay` decides the arrow: compose `depends_on` states startup
    # ordering, which is directed but says nothing about traffic returning, so
    # the weaker claim is drawn as the plain arrow and a two-way wire is
    # explicit.
    external: set[str] = set()
    edges: list[str] = []
    for w in sorted(ir.wires, key=lambda w: (str(w.get("source", "")), str(w.get("target", "")))):
        src = _resolve_endpoint(str(w.get("source") or ""), by_slug, by_name)
        dst = _resolve_endpoint(str(w.get("target") or ""), by_slug, by_name)
        if src is None and dst is None:
            continue
        if src is None:
            src = str(w.get("source") or "?"); external.add(src)
        if dst is None:
            dst = str(w.get("target") or "?"); external.add(dst)
        label = _label(str(w.get("label") or w.get("integrationStyle") or ""))
        arrow = "-->" if w.get("oneWay", True) else "<-->"
        edges.append(f'{_nid(src)} {arrow}|"{label}"| {_nid(dst)}' if label
                     else f"{_nid(src)} {arrow} {_nid(dst)}")
    for ext in sorted(external):
        lines.append(f'{_nid(ext)}["{_label(ext)}<br/><small>outside this analysis</small>"]')
    lines.extend(edges)

    lines.append("classDef structural stroke-dasharray:4 3,fill:none;")
    if structural_nodes:
        lines.append("class " + ",".join(_nid(s) for s in sorted(structural_nodes))
                     + " structural;")
    return "\n".join(lines)


def exceeds_renderer_limit(diagram: str) -> bool:
    """Whether a rendered diagram is too large for a Mermaid renderer to draw.

    Checked at write time so a consumer knows before it tries. The alternative
    — storing it unlabelled — hands the curator UI a value that fails only when
    someone opens it, which is the worst moment to discover it.
    """
    return len(diagram) > RENDERER_CHAR_LIMIT


def caption(ir: IR, max_depth: int | None = projection.DEFAULT_PROJECTION_DEPTH) -> str:
    """What the diagram does not show, stated rather than left to be noticed.

    Never a bare count: a projection that collapsed nothing and one that
    collapsed everything both report a number (`scope_hierarchy.summarise`
    makes the same point).
    """
    shown = projection.project(ir.components, max_depth)
    hidden = len(ir.components) - len(shown)
    owner_slugs = {c.slug for c in shown}
    unowned = sum(1 for p in ir.ports if str(p.get("component") or "") not in owner_slugs)
    bits = [f"{len(shown)} component(s) shown at depth {max_depth if max_depth is not None else 'full'}"]
    if hidden > 0:
        bits.append(f"{hidden} nested below this level")
    if unowned:
        bits.append(f"{unowned} port(s) not attributable to a shown component, omitted")
    structural = _structural_slugs(ir.components)
    low = sum(1 for c in shown if c.confidence <= LOW_CONFIDENCE and c.slug not in structural)
    if low:
        bits.append(f"{low} marked ⚠ at or below {LOW_CONFIDENCE}% confidence")
    text = "; ".join(bits) + "."
    size = len(render(ir, max_depth))
    if size > RENDERER_CHAR_LIMIT:
        text += (f" NOT RENDERABLE: {size} characters exceeds the "
                 f"{RENDERER_CHAR_LIMIT}-character limit — the proposal is too "
                 f"large to draw at this depth.")
    return text
