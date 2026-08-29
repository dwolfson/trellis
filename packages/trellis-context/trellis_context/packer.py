"""Fit resolved sources into a budget, and say exactly what was done.

Ordinary code, deliberately. Every guarantee below is unavailable if a model
decides what to include, and the guarantees are the reason this exists rather
than a prompt template:

  determinism   same spec + same inputs -> byte-identical output
  monotonicity  more budget never REMOVES content
  symmetry      grouped sections pack at equal budget and the same rung
  hard ceiling  the budget is never exceeded; it fails instead of truncating

The last one is load-bearing for the others. Silent truncation at the window
boundary defeats every promise made above it, which is why an unfittable
required section raises rather than returning a slightly-too-large context.

Budget is counted in CHARACTERS. Callers wanting token precision pass a
`measure` function; the default keeps this package free of a tokenizer heavier
than the thing it packs for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from trellis_artifact_tree.model import Rung

from trellis_context.spec import ContextSpec, Section


class BudgetError(RuntimeError):
    """A required section could not fit even at its coarsest allowed rung.

    Raised rather than returning a context missing something declared essential:
    a caller asked for instructions and evidence, and evidence alone is not a
    smaller answer to that request, it is a different one.
    """


@dataclass(frozen=True)
class Candidate:
    """What a resolver produced for one section, at each rung it can offer.

    `rungs` maps a Rung to rendered text. A section offering only FULL simply
    cannot be compressed, and the packer will drop it rather than pretend.
    """

    key: str
    rungs: dict[Rung, str]
    provenance: tuple[dict, ...] = ()

    def best_within(self, limit: int, floor: Rung, measure: Callable[[str], int]):
        """Richest rung that fits `limit`, or None. Never returns something
        coarser than `floor` -- past that point the section is dropped instead
        of reduced to noise."""
        for rung in sorted(self.rungs):
            if rung > floor:
                break
            text = self.rungs[rung]
            if measure(text) <= limit:
                return rung, text
        return None


@dataclass(frozen=True)
class PackedSection:
    key: str
    role: str
    rung: Rung
    text: str
    size: int
    provenance: tuple[dict, ...] = ()


@dataclass(frozen=True)
class Manifest:
    """What the packer did, and why. Not a debugging extra.

    This is what makes a compile explainable, auditable and negotiable. A packer
    that returns only text has thrown away the part a person can act on.
    """

    spec_id: str
    spec_version: int
    budget: int
    used: int
    packed: tuple[dict, ...] = ()
    dropped: tuple[dict, ...] = ()
    gaps: tuple[dict, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def headroom(self) -> int:
        return self.budget - self.used


@dataclass(frozen=True)
class PackedContext:
    sections: tuple[PackedSection, ...]
    manifest: Manifest

    def text(self, separator: str = "\n\n") -> str:
        return separator.join(s.text for s in self.sections)


def _chars(text: str) -> int:
    return len(text)


def pack(
    spec: ContextSpec,
    candidates: dict[str, Candidate],
    budget: int,
    *,
    measure: Callable[[str], int] = _chars,
) -> PackedContext:
    """Fit `candidates` into `budget` according to `spec`.

    A section with no candidate is a GAP, not a failure: an analysis that has
    not run yet is a normal state, and the manifest says so rather than the
    context silently lacking it (docs/context-compilation-design.md §20).
    """
    order = list(spec.sections)
    gaps = [
        {"key": s.key, "reason": "no candidate — resolver produced nothing yet"}
        for s in order if s.key not in candidates
    ]
    required_gap = [s.key for s in order if s.required and s.key not in candidates]
    if required_gap:
        raise BudgetError(
            f"{spec.spec_id}: required section(s) {required_gap} have no candidate"
        )

    live = [s for s in order if s.key in candidates]
    notes: list[str] = []
    dropped: list[dict] = []

    # BREADTH FIRST, then fidelity. Every section is admitted at its CHEAPEST
    # acceptable rung before any section is upgraded.
    #
    # A proportional per-section allocation was tried first and is not monotone:
    # with a larger budget a heavy section upgrades to FULL, eats the headroom a
    # lighter one had been reclaimed into, and the lighter one disappears. More
    # budget, less content. Monotonicity is a promise this packer makes, and an
    # allocator that breaks it is wrong however reasonable it reads.
    #
    # Weight therefore governs UPGRADE PRIORITY rather than a fixed share, which
    # is also the better reading of "Perspective sets budget weights": a weight
    # says what to spend spare capacity on, not what to exclude.
    group_members: dict[str, list[Section]] = {}
    for s in live:
        if s.group:
            group_members.setdefault(s.group, []).append(s)

    chosen: dict[str, Rung] = {}
    remaining = budget

    def _cheapest(section: Section, limit: int):
        cand = candidates[section.key]
        for rung in sorted(cand.rungs, reverse=True):      # coarsest first
            if rung > section.floor:
                continue
            if measure(cand.rungs[rung]) <= limit:
                return rung
        return None

    def _group_cheapest(members: list[Section], limit: int):
        """One rung all members share, cheapest that the group fits in total."""
        floor = max(m.floor for m in members)
        common = set.intersection(*(set(candidates[m.key].rungs) for m in members))
        for rung in sorted(common, reverse=True):
            if rung > floor:
                continue
            if sum(measure(candidates[m.key].rungs[rung]) for m in members) <= limit:
                return rung
        return None

    handled: set[str] = set()
    for section in live:
        if section.key in handled:
            continue
        if section.group:
            members = group_members[section.group]
            rung = _group_cheapest(members, remaining)
            if rung is None:
                for m in members:
                    handled.add(m.key)
                    if m.required:
                        raise BudgetError(
                            f"{spec.spec_id}: required section {m.key!r} in group "
                            f"{m.group!r} does not fit"
                        )
                    dropped.append({"key": m.key, "reason":
                                    f"symmetric group {section.group!r} has no rung "
                                    f"all members fit in the remaining budget"})
                continue
            for m in members:
                chosen[m.key] = rung
                handled.add(m.key)
                remaining -= measure(candidates[m.key].rungs[rung])
            notes.append(f"group {section.group!r} packed symmetrically at {rung.name}")
            continue

        handled.add(section.key)
        rung = _cheapest(section, remaining)
        if rung is None:
            if section.required:
                raise BudgetError(
                    f"{spec.spec_id}: required section {section.key!r} does not fit "
                    f"in {remaining} (floor {section.floor.name})"
                )
            dropped.append({"key": section.key, "reason":
                            f"no rung at or above {section.floor.name} fits in "
                            f"the remaining {remaining}"})
            continue
        chosen[section.key] = rung
        remaining -= measure(candidates[section.key].rungs[rung])

    # UPGRADE: ONE RUNG PER ROUND, heaviest weight first, key as a deterministic
    # tiebreak. Groups upgrade together or not at all.
    #
    # One rung per round, not straight to the richest, and the difference is a
    # policy choice rather than an implementation detail. Stepping means a heavy
    # section can be overtaken: a weight-3 section moving IDENTIFIERS -> SUMMARY
    # leaves room for a weight-1 section to jump straight to FULL, and the heavy
    # one then cannot afford its second step. Going straight to the richest
    # instead would let the heaviest section consume everything and leave the
    # rest at their floors.
    #
    # Stepping is chosen because Perspective weighting is UNMEASURED -- §3 of
    # the design says so plainly, and says only that nesting makes it safe, not
    # that it helps. A policy that cannot starve a section is the right default
    # under that uncertainty; a greedy one bets on weights that have never been
    # shown to be right. Revisit when the feedback loop can measure them.
    upgradable = sorted(
        {s.group or s.key: s for s in live if s.key in chosen}.values(),
        key=lambda s: (-s.weight, s.key),
    )
    improved = True
    while improved:
        improved = False
        for section in upgradable:
            members = group_members.get(section.group, [section]) if section.group else [section]
            current = chosen[members[0].key]
            better = [r for r in sorted(set.intersection(
                *(set(candidates[m.key].rungs) for m in members))) if r < current]
            if not better:
                continue
            target = better[-1]          # one step up, not straight to the best
            delta = sum(measure(candidates[m.key].rungs[target]) for m in members) - \
                    sum(measure(candidates[m.key].rungs[current]) for m in members)
            if delta <= remaining:
                for m in members:
                    chosen[m.key] = target
                remaining -= delta
                improved = True

    packed = [
        PackedSection(
            key=s.key, role=s.role, rung=chosen[s.key],
            text=candidates[s.key].rungs[chosen[s.key]],
            size=measure(candidates[s.key].rungs[chosen[s.key]]),
            provenance=candidates[s.key].provenance,
        )
        for s in order if s.key in chosen
    ]
    used = sum(p.size for p in packed)
    if used > budget:
        raise BudgetError(
            f"{spec.spec_id}: packed {used} into a budget of {budget} — "
            "the ceiling is hard, and silent truncation would defeat every "
            "other guarantee"
        )

    manifest = Manifest(
        spec_id=spec.spec_id, spec_version=spec.version, budget=budget, used=used,
        packed=tuple({"key": p.key, "role": p.role, "rung": p.rung.name, "size": p.size}
                     for p in packed),
        dropped=tuple(dropped), gaps=tuple(gaps), notes=tuple(notes),
    )
    return PackedContext(sections=tuple(packed), manifest=manifest)


def _allocate(sections: list[Section], budget: int) -> dict[str, int]:
    """Budget per section, proportional to weight.

    Required sections are allocated first and in full proportion; optional ones
    share what is left. Weighting them together would let a heavy optional
    section starve a light required one, which is the wrong failure: required
    means required.
    """
    if not sections:
        return {}
    required = [s for s in sections if s.required]
    optional = [s for s in sections if not s.required]

    req_weight = sum(s.weight for s in required)
    opt_weight = sum(s.weight for s in optional)
    total = req_weight + opt_weight

    shares: dict[str, int] = {}
    for s in required:
        shares[s.key] = int(budget * (s.weight / total)) if total else 0
    spent = sum(shares.values())
    left = budget - spent
    for s in optional:
        shares[s.key] = int(left * (s.weight / opt_weight)) if opt_weight else 0
    return shares


def _symmetric_rungs(spec, live, candidates, shares, measure, notes) -> dict[str, Rung | None]:
    """One rung per group: the richest that EVERY member fits in its own share.

    Without this, a comparison whose budget runs out mid-pack gives subject A
    full evidence and subject B a summary, and the answer favours A for a reason
    nothing in the output reveals. That is a correctness property, not a nicety.
    """
    out: dict[str, Rung | None] = {}
    members: dict[str, list[Section]] = {}
    for s in live:
        if s.group:
            members.setdefault(s.group, []).append(s)

    for group, group_sections in members.items():
        floor = max(s.floor for s in group_sections)
        offered = [set(candidates[s.key].rungs) for s in group_sections]
        common = sorted(set.intersection(*offered)) if offered else []
        chosen = None
        for rung in common:
            if rung > floor:
                break
            if all(measure(candidates[s.key].rungs[rung]) <= shares[s.key]
                   for s in group_sections):
                chosen = rung
                break
        out[group] = chosen
        if chosen is not None:
            notes.append(f"group {group!r} packed symmetrically at {chosen.name}")
    return out
