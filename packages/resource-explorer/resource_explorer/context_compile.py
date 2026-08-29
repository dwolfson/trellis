"""Compile a context for a question about one resource — the adoption gate.

Closes the loop opened in Phase 0. `question_catalog_reader.get_questions()`
already resolves Purpose + Perspective to questions and to the `analysis_ids`
that answer them, and already returns that chain as a `derivation`. Here those
analysis ids become the SECTIONS of a ContextSpec, the registry's materialised
findings become the packer's candidates, and the packer decides what fits.

**Nothing is run here.** Resolvers read stored analysis results only. An analysis
that has not run yet produces no candidate, and the packer reports it as a gap
rather than the context quietly lacking it — which is the whole point of
`availability: inline | queued` (docs/context-compilation-design.md §20). A
compile must never block on a survey.

**The derivation travels with the answer.** It is the explanation with content —
"this section is here because your Purpose is Certify, which ranked Q17, which
dispatches security_scan" — and it is what makes the manifest legible rather
than a list of sizes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from trellis_artifact_tree.model import Rung
from trellis_context import Candidate, ContextSpec, Section, pack

#: Kept small on purpose: an instructions section that grows into a system
#: prompt is a prompt template wearing a spec's clothes.
_INSTRUCTIONS = (
    "Answer using only the evidence below. Every section states which analysis "
    "produced it. If the evidence does not answer the question, say so and name "
    "what is missing — do not infer from absence."
)


@dataclass(frozen=True)
class CompiledContext:
    text: str
    manifest: dict
    derivation: list[dict]


def _findings_to_rungs(findings: list[dict], analysis_id: str) -> dict[Rung, str]:
    """Three rungs from stored findings, all free — no summariser involved.

    FULL is the findings themselves. SUMMARY is one line per check. IDENTIFIERS
    is the check names: enough for a reader to know the analysis ran and what it
    looked at, when the budget cannot afford more.
    """
    if not findings:
        return {}
    full = [f"## {analysis_id}"]
    summary = [f"## {analysis_id}"]
    names = []
    for f in findings:
        check = f.get("check_name") or "?"
        label = f.get("label") or ""
        text = (f.get("summary") or "").strip()
        names.append(check)
        summary.append(f"- {check}: {label}" if label else f"- {check}")
        full.append(f"- {check}: {label}\n  {text}" if text else f"- {check}: {label}")
    return {
        Rung.FULL: "\n".join(full),
        Rung.SUMMARY: "\n".join(summary),
        Rung.IDENTIFIERS: f"## {analysis_id}\nchecks: " + ", ".join(sorted(set(names))),
    }


def _provenance(findings: list[dict], analysis_id: str) -> tuple[dict, ...]:
    """When the fact was true, and where it came from.

    `surveyed_at` is the analysis run's own timestamp, not the compile's — an
    old fact and a stale read are different things, and collapsing them is what
    the envelope exists to prevent (§10)."""
    return tuple(
        {"analysis_id": analysis_id, "check": f.get("check_name"),
         "surveyed_at": f.get("surveyed_at")}
        for f in findings
    )


def compile_context(
    registry,
    slug: str,
    question: str,
    *,
    purposes: list[str] | None = None,
    perspectives: list[str] | None = None,
    budget: int = 8000,
    target_model: str = "",
) -> CompiledContext:
    """Build, resolve and pack a context for `question` about resource `slug`."""
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    entries = get_questions(
        "repo", perspectives=perspectives or None, purposes=purposes or None,
    )

    # Rank matters: Purpose ORDERS, so the analyses reached by the highest-ranked
    # questions become the heaviest sections. Nothing is excluded by ranking --
    # a low-ranked analysis is a light section, not an absent one.
    weights: dict[str, float] = {}
    derivation: list[dict] = []
    for position, entry in enumerate(entries):
        d = entry.get("derivation") or {}
        ids = d.get("analysis_ids") or []
        if not ids:
            continue
        # Weight decays with rank but never reaches zero.
        weight = 1.0 / (1 + position * 0.1)
        for analysis_id in ids:
            weights[analysis_id] = max(weights.get(analysis_id, 0.0), weight)
        derivation.append({
            "question": entry["question"],
            "matched_purposes": d.get("matched_purposes", []),
            "matched_perspectives": d.get("matched_perspectives", []),
            "analysis_ids": ids,
            "rank": position,
        })

    sections = [Section("instructions", role="instructions", required=True, weight=1.0)]
    candidates: dict[str, Candidate] = {
        "instructions": Candidate("instructions", {Rung.FULL: _INSTRUCTIONS}),
    }
    for analysis_id, weight in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])):
        sections.append(Section(analysis_id, role="evidence", weight=weight))
        findings = registry.query_findings(slug, analysis_id)
        rungs = _findings_to_rungs(findings, analysis_id)
        if rungs:
            candidates[analysis_id] = Candidate(
                analysis_id, rungs, provenance=_provenance(findings, analysis_id),
            )
        # No rungs => no candidate => the packer records a gap. Deliberately not
        # skipped here: a section the derivation says should exist, with nothing
        # behind it, is information.

    spec = ContextSpec(
        spec_id=f"adoption-gate:{slug}", version=1,
        sections=tuple(sections), target_model=target_model,
    )
    packed = pack(spec, candidates, budget)
    m = packed.manifest
    return CompiledContext(
        text=packed.text(),
        manifest={
            "spec_id": m.spec_id, "budget": m.budget, "used": m.used,
            "headroom": m.headroom, "packed": list(m.packed),
            "dropped": list(m.dropped), "gaps": list(m.gaps), "notes": list(m.notes),
        },
        derivation=derivation,
    )
