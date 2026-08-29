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
import logging
from dataclasses import dataclass

from trellis_artifact_tree.model import Rung
from trellis_context import Candidate, ContextSpec, Section, pack

log = logging.getLogger(__name__)

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


def _has_content(results) -> bool:
    """Whether a results dict says anything, as opposed to merely existing.

    Every reader returns a dict, so truthiness is useless here: `cve_scan`
    answers `{"findings": []}` and `dependency_analysis` answers
    `{"by_ecosystem": {}, "total": 0}`. Both are dicts, both are true, and both
    mean nothing was found. Treating them as candidates would replace a wrong
    gap with a wrong section — an empty heading asserting the analysis had
    something to say.

    A measured zero and a never-run are still not distinguished here; the
    readers do not carry that distinction (see result_status.py, which exists
    because it matters elsewhere). What this decides is narrower: is there
    anything to pack.
    """
    if not isinstance(results, dict):
        return bool(results)
    for value in results.values():
        # Each type is decided exactly once. An earlier version put the
        # numeric test in an `elif ... and value` and then had a catch-all
        # `elif value is not None`, so a zero failed the numeric branch and was
        # caught by the fallback: `{"by_ecosystem": {}, "total": 0}` read as
        # content and packed dependency_analysis as an empty section claiming
        # it had something to say. bool is checked first because it is a
        # subclass of int.
        if isinstance(value, bool):
            if value:
                return True
        elif isinstance(value, (int, float)):
            if value:
                return True
        elif isinstance(value, (list, dict, str)):
            if len(value) > 0:
                return True
        elif value is not None:
            return True
    return False


def _results_to_rungs(results: dict, analysis_id: str) -> dict[Rung, str]:
    """Three rungs from an analysis's own results reader.

    The findings table is one of several places results live, and for most
    analyses it is the wrong one. Measured on egeria_git 2026-08-29: eleven
    analyses were reported as gaps and seven of them had real stored data —
    repository_health scoring 85.8, api_structure holding 3,232 Java classes —
    because each keeps its results in its own table (project_stats,
    project_code_symbols, project_file_type_counts) and only
    `project_analysis_findings` was consulted. `docs/granularity-pass.md` §1.2
    had already measured that 12 analyses have no finding `kind` at all.

    The shapes are heterogeneous by design, so the rungs are structural rather
    than field-aware: FULL is the payload, SUMMARY names each top-level part
    with its size, IDENTIFIERS names the parts. A reader that knew each shape
    would be a fourth place to keep that knowledge in sync.
    """
    if not _has_content(results):
        return {}

    def _extent(value) -> str:
        if isinstance(value, list):
            return f"{len(value)} item(s)"
        if isinstance(value, dict):
            return f"{len(value)} key(s)"
        return str(value)

    keys = sorted(results)
    return {
        Rung.FULL: f"## {analysis_id}\n"
                   + json.dumps(results, indent=2, default=str, sort_keys=True),
        Rung.SUMMARY: f"## {analysis_id}\n"
                      + "\n".join(f"- {k}: {_extent(results[k])}" for k in keys),
        Rung.IDENTIFIERS: f"## {analysis_id}\nreports: " + ", ".join(keys),
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
    from resource_explorer.surveyors.analysis_catalog_reader import get_analyses

    # `egeria_publish` is an ACTION, not an analysis — it writes to Egeria and
    # has no results to pack, so it can only ever appear as a permanent gap
    # asserting a missing result that will never exist. The scheduler already
    # excludes action == "publish" for the same reason; this is the same
    # exclusion, one layer up. Question 5 of the catalog references it, which
    # is how it reaches here at all.
    _actions = {a["id"] for a in get_analyses("repo", include_egeria_live=False)
                if a.get("action") == "publish"}

    for position, entry in enumerate(entries):
        d = entry.get("derivation") or {}
        ids = [i for i in (d.get("analysis_ids") or []) if i not in _actions]
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
        provenance = _provenance(findings, analysis_id)

        # The findings table holds results for a MINORITY of analyses. Where it
        # is empty, ask the analysis's own results reader — the same one the UI
        # renders from — before concluding there is nothing stored. Without
        # this, a gap means "not in project_analysis_findings" while claiming
        # to mean "never run", which is the confident-wrong-answer shape this
        # whole spec exists to avoid.
        if not rungs:
            from resource_explorer.surveyors.repo_survey_definition_adapter import (
                REPO_ANALYSIS_RESULTS_MAP,
            )
            entry = REPO_ANALYSIS_RESULTS_MAP.get(analysis_id)
            reader = entry[0] if entry else None
            if reader is not None:
                try:
                    results = reader(registry, slug)
                except Exception as exc:
                    # A reader that raises is not evidence of absence. Say so in
                    # the notes rather than letting it look like a clean gap.
                    log.warning("results reader for %s failed on %s: %s",
                                analysis_id, slug, exc)
                    results = None
                if results is not None:
                    rungs = _results_to_rungs(results, analysis_id)
                    if rungs:
                        provenance = ({"analysis_id": analysis_id,
                                       "check": None, "surveyed_at": None},)

        if rungs:
            candidates[analysis_id] = Candidate(
                analysis_id, rungs, provenance=provenance,
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
