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
import logging
from dataclasses import dataclass

from trellis_artifact_tree.model import Rung
from trellis_context import Candidate, ContextSpec, Pointer, Section, pack

log = logging.getLogger(__name__)

#: Kept small on purpose: an instructions section that grows into a system
#: prompt is a prompt template wearing a spec's clothes.
#:
#: The refusal wording is deliberately the ORIGINAL loose one. A one-shape
#: template ("reply in exactly this shape and add nothing else: 'The stored
#: analyses do not cover X. <analysis> would answer it; it <state>.'") was
#: tried in experiment run3-20260909 and over-triggered on the 8B answering
#: model: 107 of 156 compiled answers became pure refusals, including ones
#: where the analysis that answers the question was packed at FULL with no
#: gaps, and the <state> slot was filled by invention ("ran and found
#: nothing" for a packed analysis) in 7 of the run's 8 missing-result
#: claims. docs/experiments/compiled-vs-rag.md, run 3.
_INSTRUCTIONS = (
    "Answer using only the evidence below. Every section states which analysis "
    "produced it. A section marked 'structure only' lists the parts of a result "
    "without their values; it is not a result — do not quote, count or summarise "
    "it as one. If the evidence does not answer the question, say so and name "
    "what is missing — do not infer from absence."
)

#: The same instructions at the packer's SUMMARY rung, for budgets too small
#: to carry the template. Instructions are required, so without a shorter
#: rung a tight budget fails the compile outright instead of degrading — the
#: one section that used to be exempt from the ladder now climbs it too.
_INSTRUCTIONS_SHORT = (
    "Answer using only the evidence below; name the analysis behind each point. "
    "If it does not answer the question, say which analysis would and whether "
    "it has run. Do not infer from absence."
)

#: How many evidence sections a compile packs, counted after ranking. Ranking
#: still orders and never excludes at the DERIVATION level — every catalog
#: question that reaches an analysis stays in `derivation`, and the sections
#: past the cap are reported in the manifest as `deferred`, with their rank
#: and weight, rather than silently absent. What the cap changes is what
#: competes for the budget.
#:
#: Measured 2026-09-09 on the three experiment repos, 6 questions each, at
#: budget 6000 (scripts/experiment_compiled_vs_rag.py's budget):
#:
#:   cap    sections  FULL share  top-3 ranked at FULL  used (median)
#:   none   26.0      22%         43 / 54               5985
#:   12     11.9      88%         52 / 54               5610
#:   8       8.0      90%         53 / 54               4368
#:
#: Uncapped, ~26 sections share 6000 chars, the budget pins at its ceiling in
#: every compile, and four in five sections sit at SUMMARY — which the audit
#: found the model narrating as if it were the answer (cause B/C: "649
#: component(s) exist… documented in the architecture summary"). Twelve is
#: the largest cap at which the ranked sections reach FULL while the budget,
#: not the cap, still decides the last sections in. The value is a knob, not
#: a law: `compile_context(max_sections=...)` overrides it, 0 disables it.
MAX_EVIDENCE_SECTIONS = 12


logger = logging.getLogger(__name__)

#: What a state means for a section with nothing to pack. The distinction the
#: compiler could not previously make -- and did not need to invent, because
#: surveyors/result_status.py already carries it and facts.py already applies
#: it. "A measured zero and a never-run are the same number and opposite
#: answers" (facts.py). Inventing a parallel vocabulary here would have been the
#: mistake that put four retired RE perspectives beside Egeria's twelve.
_GAP_PHRASING = {
    "never_run": "has not run",
    "nothing_found": "ran and found nothing — a real zero, not a missing result",
    "not_established": "ran, but cannot be credited with this result",
    "partial": "ran over only part of what it covers",
}


@dataclass(frozen=True)
class CompiledContext:
    text: str
    manifest: dict
    derivation: list[dict]
    #: Content hash of everything the packer saw: spec id and version, budget,
    #: target model, and every candidate's rungs. Two compiles over the same
    #: materialised state get the same id, which is the replayability contract
    #: (context-compilation-design.md §9) made checkable — and the key that
    #: conversation turns and feedback carry so a rating can be traced back to
    #: the exact context the model was given (§13). Also present as
    #: manifest["compile_id"] so callers holding only the manifest have it.
    compile_id: str = ""


def _compile_id(spec, candidates: dict, budget: int) -> str:
    """blake2b over the packer's inputs, in a canonical order.

    Hashes rung TEXT, not provenance timestamps: a re-read of the same stored
    result at a later `fetched_at` is the same compile. Provenance still
    travels in the manifest; it just does not change identity.
    """
    import hashlib
    h = hashlib.blake2b(digest_size=16)
    h.update(f"{spec.spec_id}|{spec.version}|{budget}|{spec.target_model}|".encode())
    for key in sorted(candidates):
        h.update(f"[{key}]".encode())
        for rung, text in sorted(candidates[key].rungs.items(), key=lambda kv: str(kv[0])):
            h.update(f"{rung}:".encode())
            h.update(hashlib.blake2b(str(text).encode(), digest_size=8).digest())
    return h.hexdigest()


#: No single finding may take more than this share of a section's FULL rung.
#: Findings are written for whatever consumer the surveyor had in mind, and some
#: of those are not prose: a rendered diagram, a serialised graph, a file listing.
#: One of them can consume a whole section's budget and crowd out every other
#: check in the same analysis, which is a worse context than omitting it.
#: Truncation is marked, never silent — an elided finding that looked complete
#: would be the failure this module keeps finding in other forms.
MAX_FINDING_CHARS = 1200

#: Below this, a section's findings are too slight to be trusted as the whole
#: story, and the analysis's own results reader is consulted as well. Set at the
#: same order as the near-empty tree threshold and for the same reason: it marks
#: "this says almost nothing", not "this is short".
THIN_FINDINGS_CHARS = 200

#: Words too common to carry relevance on either side of _question_relevance's
#: overlap -- without this, "results"/"survey" (present in nearly every
#: question a Resource Explorer user asks, because that is what this tool
#: does) would inflate every catalog entry's score roughly equally, which is
#: the same as not scoring at all.
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "it", "of", "to", "and", "or", "for",
    "on", "in", "at", "this", "that", "what", "how", "does", "do", "show",
    "me", "all", "with", "about", "results", "result", "survey",
    # Measured 2026-09-09 over the 52 repo catalog questions: "repository"
    # appears in 13 of them and "there" in 9, so a paraphrase like "what
    # languages are in this repository?" overlapped a quarter of the catalog
    # on "repository" alone. Same reason "results"/"survey" are here.
    "repository", "repositories", "repo", "there", "already", "has",
})


def _question_relevance(question: str, catalog_question: str, analysis_ids: list[str]) -> float:
    """How much a catalog entry's own question and analysis ids overlap the
    free-text question actually asked, as a fraction of the asked question's
    own (stopword-stripped) tokens. Deterministic word-overlap, not an
    embedding or model call — the packer must never trigger one (§20).

    Measured 2026-08-31: asking "documentation survey results" packed
    repository_health / architecture_doc_lens / language_file_classification
    ahead of documentation_coverage itself, then dropped documentation_coverage
    as a gap entirely — `question` was accepted by compile_context() and never
    read again; every catalog entry weighed the same regardless of what was
    asked, decaying only by its arbitrary position in the YAML. The model,
    given evidence that did not answer the question, fell back to
    vector_search and answered from Egeria's OWN documentation about its
    Survey Framework feature — a keyword collision on "survey", not an answer
    about the repository's documentation.

    Analysis ids are folded into the candidate token set alongside the
    catalog's own question phrasing: "documentation_coverage" tokenizes to
    "documentation"/"coverage", which is the one thing an asker is most
    likely to have said even when the catalog's own phrasing ("How well
    documented is it?") shares no token with it.

    A score, not a filter: Purpose already establishes that this system
    ranks what it is uncertain of rather than excluding it (see
    question_catalog_reader.get_questions()'s own docstring). This returns
    0.0 for no overlap, not None or an exclusion — the caller decides what a
    zero means for ranking.
    """
    import re
    q_tokens = set(re.findall(r"[a-z0-9]+", question.lower())) - _STOPWORDS
    if not q_tokens:
        return 0.0
    candidate_tokens = set(re.findall(r"[a-z0-9]+", catalog_question.lower()))
    for aid in analysis_ids:
        candidate_tokens |= set(aid.split("_"))
    candidate_tokens -= _STOPWORDS
    return len(q_tokens & candidate_tokens) / len(q_tokens)


def _clip(text: str, analysis_id: str, check: str) -> str:
    if len(text) <= MAX_FINDING_CHARS:
        return text
    return (
        text[:MAX_FINDING_CHARS].rstrip()
        + f"\n  […truncated {len(text) - MAX_FINDING_CHARS} chars — read "
          f"{analysis_id}/{check} directly for the whole thing]"
    )


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
        text = _clip((f.get("summary") or "").strip(), analysis_id, check)
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

    ONE exception, and it is a shape, not an analysis: `{"findings": [...]}`
    with `check_name`/`label`/`summary` per item is the same finding shape
    `_findings_to_rungs` already formats well from the findings table itself
    -- `_documentation_results`, `_license_results`,
    `_repo_classification_results` and others return exactly this ("same
    uniform finding shape" is their own recurring comment). Measured
    2026-08-31: documentation_coverage's SUMMARY read
    "- findings: 4 item(s)\n- _status: 5 key(s)", and the model narrated
    that structural summary verbatim as "5 key(s) with 4 item(s) found" --
    real per-check content, reduced to two counts, then repeated back as if
    it meant something. Recognizing this one recurring shape and reusing
    `_findings_to_rungs`' own formatting is not the field-aware special-
    casing above rules out; it is not re-deriving from `_status` or any
    other field this function still treats structurally.
    """
    if not _has_content(results):
        return {}

    findings = results.get("findings")
    if isinstance(findings, list) and findings and all(
        isinstance(f, dict) and "check_name" in f for f in findings
    ):
        rungs = dict(_findings_to_rungs(findings, analysis_id))
        other = sorted(k for k in results if k != "findings")
        if other:
            rungs[Rung.FULL] += "\n(also: " + ", ".join(other) + ")"
        return rungs

    # SUMMARY carries only what is safe to read as a value. A scalar IS a
    # value and is shown; a list or mapping is named and its kind given, with
    # NO count. The counts were the bug: "- lines_of_code_by_language: 5
    # key(s)" was narrated as "5 lines of code by language" (kafka, run
    # full-20260908, judged 2 and cites_evidence=true) and "649 component(s)"
    # as an inventory. Under `unsupported_claims` compiled answers scored
    # worse than RAG-only (0.82 vs 0.58) and this shape was the named cause.
    # The rung is headed "structure only" so the instructions can refer to it
    # by name; the IDENTIFIERS rung below is the same names with no values.
    def _part(value) -> str:
        if isinstance(value, list):
            return "(list)"
        if isinstance(value, dict):
            return "(mapping)"
        text = str(value)
        return text if len(text) <= 80 else text[:77] + "..."

    keys = sorted(results)
    # Fenced, not bare -- this text reaches two readers: the model, for which a
    # ```json block is exactly as parseable as a bare dump, and now the Chat
    # panel's own "show packed text" toggle, which renders it through
    # marked.parse(). Unfenced, a raw JSON dump reads as a run-on paragraph of
    # braces; fenced, marked.js gives it a monospace block. Same bytes reach
    # the model either way -- this is a display fix, not a content change.
    return {
        Rung.FULL: f"## {analysis_id}\n```json\n"
                   + json.dumps(results, indent=2, default=str, sort_keys=True)
                   + "\n```",
        Rung.SUMMARY: f"## {analysis_id}\n"
                      f"(structure only: part names and scalar values; lists and "
                      f"mappings are named, not counted — read {analysis_id} for "
                      f"their contents)\n"
                      + "\n".join(f"- {k}: {_part(results[k])}" for k in keys),
        Rung.IDENTIFIERS: f"## {analysis_id}\nreports: " + ", ".join(keys),
    }


#: Which analyses have a real, addressable view to point at. Deliberately
#: narrow: Backlog "a compiled answer should be able to POINT at a view" notes
#: deep-linking to a perspective/scope is the *prerequisite* work, and today
#: only the architecture card has perspective tabs (`_archTabsHtml` in
#: index.html) worth linking into. Add an entry here once a view exists to
#: point at — the compiler side needs no other change, since `Pointer` is
#: already resource/analysis-agnostic.
_POINTABLE_VIEWS = {"architecture_recovery": "architecture"}


def _pointer_for(analysis_id: str, slug: str, provenance: tuple[dict, ...]) -> Pointer | None:
    """A link to where this analysis's own view lives, alongside its prose.

    `as_of` comes from the analysis's own `surveyed_at`, not compile time —
    the same fact-vs-read distinction `_provenance` already draws (§10):
    the pointer should say when the view's *data* is from, not when this
    context happened to be compiled.
    """
    view = _POINTABLE_VIEWS.get(analysis_id)
    if view is None:
        return None
    surveyed_at = next((p.get("surveyed_at") for p in provenance if p.get("surveyed_at")), "")
    return Pointer(resource_slug=slug, view=view, as_of=surveyed_at or "")


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


def _judge_gap(fact_layer, slug: str, analysis_id: str) -> dict:
    """Why this section has nothing, in the vocabulary that already exists.

    Fail-soft to a bare name: an unjudged gap is still worth reporting, and a
    fact layer that cannot answer must not cost the whole compile.
    """
    gap = {"key": analysis_id, "reason": "no candidate — resolver produced nothing yet"}
    try:
        fact = fact_layer.fact(slug, analysis_id)
    except Exception:
        logger.debug("no fact for %s/%s", slug, analysis_id, exc_info=True)
        return gap
    phrasing = _GAP_PHRASING.get(fact.state)
    if not phrasing:
        return gap
    gap["state"] = fact.state
    gap["reason"] = phrasing
    if fact.last_run_at:
        gap["last_run_at"] = fact.last_run_at
    if fact.can_run:
        gap["can_run"] = list(fact.can_run)
    return gap


def compile_context(
    registry,
    slug: str,
    question: str,
    *,
    purposes: list[str] | None = None,
    perspectives: list[str] | None = None,
    budget: int = 8000,
    target_model: str = "",
    session_id: str | None = None,
    max_sections: int | None = None,
) -> CompiledContext:
    """Build, resolve and pack a context for `question` about resource `slug`.

    Every successful compile is recorded through `registry.record_compile`
    (fail-soft: a registry without it, or a write that fails, costs the caller
    nothing but the persistence). `session_id` is the chat/CLI session the
    compile served, when there is one; it lands on the row, not in the hash.
    `max_sections` caps how many ranked evidence sections compete for the
    budget (default MAX_EVIDENCE_SECTIONS; 0 means no cap); the rest are
    listed in the manifest as `deferred`.
    """
    from resource_explorer.surveyors.question_catalog_reader import get_questions

    entries = get_questions(
        "repo", perspectives=perspectives or None, purposes=purposes or None,
    )

    # Rank matters: Purpose ORDERS, so the analyses reached by the highest-ranked
    # questions become the heaviest sections. Nothing is excluded by ranking --
    # a low-ranked analysis is a light section, not an absent one.
    #
    # `question` relevance is folded into rank too, not just Purpose/Perspective
    # -- see _question_relevance's docstring for the reported failure this
    # fixes. Without it, a compile with no Perspective chips set (the common
    # case) ranks every one of the ~50 catalog questions by nothing but their
    # position in the YAML, regardless of what was actually asked.
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
        relevance = _question_relevance(question, entry["question"], ids)
        # relevance dominates position by design: a question that names what
        # it wants ("documentation") must outrank an unrelated question that
        # merely sits earlier in the YAML. Position still breaks ties among
        # equally (ir)relevant entries and keeps every entry's weight above
        # zero -- nothing is excluded, same rule Purpose already follows.
        #
        # ADDITIVE, not a ratio. The first form, (1 + 20r) / (1 + 0.1p),
        # divided relevance by position too, so a full match (r = 1) at
        # catalog position 30 weighed 5.25 and a one-word match (r = 0.25)
        # at position 0 weighed 6.0 — measured 2026-09-09 with "What
        # languages and file types are in this repository?", which packed
        # foss_scorecard and repository_health at FULL and the language
        # analysis at SUMMARY. With the positional term bounded by 1.0 and
        # each 0.05 of relevance worth as much, any better match outranks
        # any worse one whatever their positions, and position still orders
        # the equally relevant.
        weight = 1.0 / (1 + position * 0.1) + relevance * 20.0
        for analysis_id in ids:
            weights[analysis_id] = max(weights.get(analysis_id, 0.0), weight)
        derivation.append({
            "question": entry["question"],
            "matched_purposes": d.get("matched_purposes", []),
            "matched_perspectives": d.get("matched_perspectives", []),
            "analysis_ids": ids,
            # `rank` is this entry's position in get_questions()'s own
            # Purpose-ordered catalog list -- NOT its position in this
            # `derivation` list once sorted below. A low catalog rank with
            # high relevance now sorts earlier here while keeping a
            # numerically later `rank`; a reader wanting "why did this pack
            # first" wants list order, and a reader wanting "where does the
            # catalog itself rank this" wants `rank` -- they can diverge on
            # purpose. (S4 review, 2026-08-31: confirmed worth calling out
            # explicitly rather than leaving both readings equally plausible.)
            "rank": position,
            "relevance": round(relevance, 2),
        })

    # Sort by weight, not by catalog rank, before packing -- the manifest and
    # "why these?" panel should read as "this is why these ranked first",
    # which is now relevance-then-position, not the YAML's own order. See the
    # `rank` comment above: this reorders the LIST, not the `rank` field.
    derivation.sort(key=lambda d2: -max((weights.get(a, 0.0) for a in d2["analysis_ids"]), default=0.0))

    sections = [Section("instructions", role="instructions", required=True, weight=1.0)]
    candidates: dict[str, Candidate] = {
        "instructions": Candidate("instructions", {Rung.FULL: _INSTRUCTIONS,
                                                   Rung.SUMMARY: _INSTRUCTIONS_SHORT}),
    }
    ranked = sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))
    cap = MAX_EVIDENCE_SECTIONS if max_sections is None else max_sections
    deferred = [
        {"key": k, "weight": round(w, 3), "rank": i,
         "reason": f"below the section cap of {cap}"}
        for i, (k, w) in enumerate(ranked) if cap > 0 and i >= cap
    ]
    if cap > 0:
        ranked = ranked[:cap]
    for analysis_id, weight in ranked:
        sections.append(Section(analysis_id, role="evidence", weight=weight))
        findings = registry.query_findings(slug, analysis_id)
        rungs = _findings_to_rungs(findings, analysis_id)
        provenance = _provenance(findings, analysis_id)

        # The findings table holds results for a MINORITY of analyses. Where it
        # is empty OR THIN, ask the analysis's own results reader — the same one
        # the UI renders from — before concluding there is nothing stored.
        # Without this, a gap means "not in project_analysis_findings" while
        # claiming to mean "never run", which is the confident-wrong-answer
        # shape this whole spec exists to avoid.
        #
        # "or thin" is the correction. An earlier version fell back only when
        # `rungs` was empty, so ANY whole-resource finding — however slight —
        # suppressed the reader entirely. dwolfson-59 hit it exactly: a single
        # diagram finding written at whole-resource scope replaced an analysis's
        # real results with a picture, and the section got worse than before the
        # finding existed. They fixed the trigger at source; this fixes the
        # fragility, which would otherwise wait for the next analysis to write
        # one thin whole-resource row.
        #
        # The rule is now about evidence, not precedence: consult both when the
        # findings are slight, and keep whichever says more.
        if len(rungs.get(Rung.FULL, "")) < THIN_FINDINGS_CHARS:
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
                    from_reader = _results_to_rungs(results, analysis_id)
                    # Keep whichever says more. Overwriting unconditionally was
                    # safe only while this ran solely on empty findings; now
                    # that a THIN finding also reaches here, a reader with less
                    # to say must not displace the little that was real.
                    if len(from_reader.get(Rung.FULL, "")) > len(rungs.get(Rung.FULL, "")):
                        rungs = from_reader
                        provenance = ({"analysis_id": analysis_id,
                                       "check": None, "surveyed_at": None},)

        if rungs:
            candidates[analysis_id] = Candidate(
                analysis_id, rungs, provenance=provenance,
                pointer=_pointer_for(analysis_id, slug, provenance),
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
    from resource_explorer.facts import FactLayer

    _facts = FactLayer(registry)
    compile_id = _compile_id(spec, candidates, budget)
    compiled = CompiledContext(
        text=packed.text(),
        compile_id=compile_id,
        manifest={
            "compile_id": compile_id,
            "spec_id": m.spec_id, "budget": m.budget, "used": m.used,
            "headroom": m.headroom, "packed": list(m.packed),
            "dropped": list(m.dropped),
            # Ranked below the cap: never offered to the packer, so neither
            # packed, dropped nor a gap. Listed so "why these?" can show what
            # was left out and where it ranked.
            "deferred": deferred,
            # Judged, not merely listed. The packer knows only that a section
            # had no candidate; the fact layer knows whether that is a zero or
            # an absence, and they are opposite answers to the same question.
            "gaps": [_judge_gap(_facts, slug, g["key"]) for g in m.gaps],
            "notes": list(m.notes),
        },
        derivation=derivation,
    )
    record = getattr(registry, "record_compile", None)
    if callable(record):
        try:
            record(compile_id, slug, question, compiled.manifest, compiled.derivation,
                   session_id=session_id)
        except Exception as exc:
            # Persistence is an instrument, not the product: a compile the
            # caller can use must never be lost to a failed bookkeeping write.
            # But the failure must be VISIBLE in what the caller gets, not
            # only in a log nobody reads: the manifest says the compile was
            # not recorded, so feedback that cites this compile_id can be
            # told apart from feedback that cites a persisted one.
            log.warning("could not record compile %s for %s", compile_id, slug, exc_info=True)
            compiled.manifest["notes"].append(
                f"compile not recorded ({type(exc).__name__}); feedback citing "
                f"{compile_id} will not resolve to a stored manifest"
            )
            compiled.manifest["recorded"] = False
        else:
            compiled.manifest["recorded"] = True
    return compiled
