#!/usr/bin/env python3
"""LLM adjudicator — §5.2 steps 2 (classify) and 3 (name), plus merge.

    python3 adjudicate.py prometheus --root /path/to/checkout   # reads ir/prometheus-distilled.json
                                                                  # writes ir/prometheus-adjudicated.json

§5.2 divides distillation's labour: *"Heuristics own steps 1, 4, 5; the LLM owns
2 and 3 and adjudicates ambiguous partitions. Rule: the LLM never invents a
component with no detector evidence behind it. Its job is naming, classifying,
and merging — not discovery."* `distill.py` (finding 79) is the heuristic half;
this file is the LLM half that consumes its output.

**The hard rule is enforced by post-validation, not by prompting.** A model
will occasionally do something the prompt told it not to — invent a type
outside the 13-value vocabulary, cite a candidate slug that doesn't exist, or
(the subtle one) name a real component but leave the JSON's `candidate_slugs`
empty so nothing grounds it. `_validate()` below is the only thing standing
between "the model said so" and the output file, and it drops rather than
repairs: a dropped component is logged with a reason, never silently patched
into something plausible-looking. Every output component's `files` are
computed here, from the union of its `candidate_slugs`' own globs — the model
is never trusted to state files itself, so "files with no candidate behind
them" is unrepresentable by construction rather than merely checked for.

**CONTAMINATION WARNING — read before adding `--with-architecture-doc`.**
`tests/fixtures/architecture-ground-truth/{prometheus,milvus,kubernetes}.md`
were transcribed FROM those projects' own published architecture documents
(finding 65). §5.2 step 0 says a prose architecture doc outranks inference,
and `resource_explorer.github.doc_locations.find_artifact(repo, "architecture")`
can fetch exactly that document for a live repo — which makes it very tempting
to hand the doc to this adjudicator. Doing that and then scoring the result
against those three fixtures is circular: the fixture IS a transcription of
that same document, so the "score" would only measure whether an LLM can
reproduce a document it was shown, not whether adjudication recovers
architecture from evidence. **This file's default mode never reads an
architecture document and is the only mode whose score against those three
fixtures means anything.** A `--with-architecture-doc` mode is not implemented
here for that reason — §5.2 step 0 is a real, separate feature, but it belongs
behind a flag that refuses to run against prometheus/milvus/kubernetes (or
prints an unmissable contamination warning), and should be measured instead
against `trellis` or `egeria-workspaces`, whose ground truth was written by
the maintainer, not derived from a published doc.

**Caching.** Every LLM call is cached to disk under `llm_cache/`, keyed by a
sha256 of the exact prompt + system text + model id. Re-running this script
after a code change that doesn't alter the prompt costs nothing and is
reproducible — the point of a cache here is not speed, it is not spending the
user's own API key twice on an identical question.

**Chunking.** If the candidate count is large enough that one prompt would be
unreasonably big, candidates are grouped by their shallowest shared path
prefix (§6.0: a component is a scope locator, and locators nest under paths)
so a single component's candidates never split across chunks — the merge step
(3) needs every candidate for a component visible in the same call. Each
chunk is adjudicated independently and the outputs concatenated; nothing is
merged *across* chunks, which is a known limitation stated in the report, not
hidden.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time

SPIKE_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.normpath(os.path.join(SPIKE_DIR, "..", ".."))
sys.path.insert(0, REPO_ROOT)

CACHE_DIR = os.path.join(SPIKE_DIR, "llm_cache")

# §3.1 — the closed 13-value SolutionComponentType vocabulary. Verified against
# frameworks/open-metadata-framework/.../refdata/SolutionComponentType.java.
SOLUTION_COMPONENT_TYPES = [
    "Automated Action", "Long Running Daemon", "Multi-Step Process",
    "Third Party Process", "Manual Process", "Data Storage",
    "Software Service", "Software Library", "User Interface",
    "Console Command", "Data Distribution", "Publishing", "Insight Model",
]

MAX_CANDIDATES_PER_CHUNK = 160  # prometheus (95) fits in one; kubernetes (358) chunks


# ── IR loading ───────────────────────────────────────────────────────────

def load_distilled(target: str) -> dict:
    path = os.path.join(SPIKE_DIR, "ir", f"{target}-distilled.json")
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def evidence_by_slug(ir: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for e in ir.get("evidence", []):
        if e.get("subject_kind") == "component":
            out.setdefault(e["subject_slug"], []).append(e)
    return out


# ── chunking ─────────────────────────────────────────────────────────────

def _prefix(comp: dict, depth: int) -> str:
    roots = [g.rstrip("/*").rstrip("/") for g in (comp.get("files") or []) if g]
    if not roots:
        return ""
    parts = roots[0].split("/")
    return "/".join(parts[:depth]) or roots[0]


def chunk_candidates(components: list[dict], max_per_chunk: int) -> list[list[dict]]:
    """Group by shallowest shared path prefix so a component's candidates
    never split across chunks, then pack groups into chunks under the size
    cap. If a single group already exceeds the cap it stays whole (a
    component is never split; the cap is a target, not a hard limit)."""
    if len(components) <= max_per_chunk:
        return [components]

    groups: dict[str, list[dict]] = {}
    for c in components:
        groups.setdefault(_prefix(c, 1), []).append(c)

    chunks: list[list[dict]] = []
    current: list[dict] = []
    for key in sorted(groups):
        group = groups[key]
        if current and len(current) + len(group) > max_per_chunk:
            chunks.append(current)
            current = []
        current.extend(group)
    if current:
        chunks.append(current)
    return chunks


# ── prompt construction ─────────────────────────────────────────────────

SYSTEM_PROMPT = f"""You are an architecture adjudicator. You are given CANDIDATE components that a
deterministic detector pipeline proposed for a software repository, each with the file globs it
covers and the raw evidence (source excerpts) that justify it. The candidate list is DELIBERATELY
over-proposed — most repositories with dozens or hundreds of candidates have only a HANDFUL (typically
5-25) of real architectural components, because the detectors emit roughly one candidate per source
directory / package / module, and a real system groups many directories under one architectural
component. Your job has exactly three parts:

1. CLASSIFY each surviving component into one of these 13 values, exactly as spelled — no others
   are valid:
   {", ".join(SOLUTION_COMPONENT_TYPES)}

   These 13 values encode ONE axis: **how and where the thing is run.** They do NOT describe what
   it is about, what domain it serves, or how large it is. Two components doing completely
   different jobs get the same type if they run the same way; a library and the daemon that
   imports it get different types even though they sit side by side.

   Decide by asking, in this order, and stop at the first that fits:

     - Is it a third-party product we run but do not build (a database image, a broker, a proxy)?
       -> Third Party Process
     - Does it have its own entry point (a `main`, a console script, its own binary)?
         - a human invokes it at a terminal and it runs to completion  -> Console Command
         - it runs continuously as a process, serving or watching      -> Long Running Daemon
         - it runs on a schedule or a trigger with no human present    -> Automated Action
     - Does it serve requests over a network interface (HTTP/gRPC/REST endpoints)?
       -> Software Service
     - Does it render something a human looks at or interacts with?    -> User Interface
     - Does it persist data as its purpose (a store, an index, a TSDB)? -> Data Storage
     - Does it move or route data between systems (queues, replication, remote write)?
       -> Data Distribution
     - Does it emit outputs for downstream consumers (alerts, notifications, feeds)? -> Publishing
     - Is it a model or analytic whose output is an inference or a score? -> Insight Model
     - Is it a defined sequence of steps or a workflow?                -> Multi-Step Process
     - Does it require a person to carry out steps?                    -> Manual Process
     - None of the above: it is imported by other components and never runs on its own
       -> Software Library

   `Software Library` is the FALL-THROUGH, not the default. Reaching for it without working down
   the list is the single most common way to get this wrong: a previous run typed 53 of 56
   components `Software Library`, which carries almost no information whatever any individual
   answer's merits. If your output is overwhelmingly one value, you have not used this list.

   Use the evidence you are given. `detector-proposed type: Console Command` means an entry point
   was actually detected (a package declaring `package main` in its own root) — that is strong,
   direct evidence, not a suggestion. An exposed port or an OpenAPI document is direct evidence of
   `Software Service`. Say which evidence decided it in your rationale.
2. NAME each component in clear human terms (not a raw path or slug).
3. MERGE at the right grain — not too little, not too much. Two failure modes, both wrong:
     a. UNDER-merging: renaming every candidate 1:1 (or only deduping two candidates that describe
        the exact same directory) is NOT merging. If you produce close to as many output components
        as input candidates, you have not done this job.
     b. OVER-merging: dumping every library-like candidate in the whole repository into one or two
        giant buckets ("Libraries", "Utilities") is just as wrong, and loses just as much
        information as not merging at all — a reader gains nothing from being told "everything that
        isn't a CLI is one Library component." Two candidates belong in the same output component
        only if they share an IMMEDIATE common parent directory (siblings, not cousins) AND one of
        them is clearly a small helper/support piece of the other (e.g. a `util/` or `internal/`
        subtree of leaf packages — string helpers, pooling helpers, test helpers — merges into ONE
        component scoped to that subtree, not into a repo-wide "utilities" component alongside
        unrelated top-level packages). Two top-level packages that each have their own distinct
        responsibility (e.g. a query engine vs. a storage engine vs. a notifier) stay SEPARATE
        components even though both are "just a library" by type — the type is not the grouping key,
        the architectural role and directory locality are.
   You may also merge a package with its own CLI entry point, or several near-duplicate candidates
   from different detectors describing the exact same directory.

You do NOT discover components. Every component you output must be built ONLY from the candidate
slugs you were given — you may merge candidates together, drop candidates that are noise (tests,
vendored code, build tooling, duplicates), rename, and reclassify, but you may never assert a
component, a file, or a claim that has no candidate evidence behind it. If you are unsure whether
something is a real architectural component, leave it out rather than guess.

Respond with ONLY a JSON array, no prose before or after, no markdown fences. Each element:

  {{"name": "<human name>", "type": "<one of the 13 values>", "rationale": "<one sentence, cite evidence>",
    "candidate_slugs": ["<slug>", "..."]}}

`candidate_slugs` must be non-empty and must only contain slugs from the candidate list you were
given. Do not invent slugs. Do not include a "files" field — files are derived from the slugs you
cite, not from you."""


def build_prompt(components: list[dict], ev_by_slug: dict[str, list[dict]]) -> str:
    lines = [
        f"There are {len(components)} candidate components. For each, you are given its slug, "
        "the detector-proposed name/type (may be absent — '?' means the detector didn't classify "
        "it), its file globs, which detector(s) proposed it, its confidence, and the evidence "
        "(assertions with source excerpts) behind it.", "",
    ]
    for c in components:
        slug = c["slug"]
        lines.append(f"### {slug}")
        lines.append(f"  detector-proposed name: {c.get('name', '')}")
        lines.append(f"  detector-proposed type: {c.get('type') or '?'}")
        lines.append(f"  files: {json.dumps(c.get('files', []))}")
        lines.append(f"  proposed_by: {json.dumps(c.get('proposed_by', []))}")
        lines.append(f"  confidence: {c.get('confidence')} ({c.get('confidence_level', '')})")
        for e in ev_by_slug.get(slug, []):
            excerpt = ""
            locs = e.get("locations") or []
            if locs:
                excerpt = f" — {locs[0].get('path', '')}: {locs[0].get('excerpt', '')!r}"
            lines.append(f"  evidence [{e.get('detector', '')}]: {e.get('assertion', '')}{excerpt}")
        lines.append("")
    lines.append(
        "Now name, classify, and merge these into the real architectural component set. "
        "Output the JSON array only."
    )
    return "\n".join(lines)


# ── caching ──────────────────────────────────────────────────────────────

def _cache_key(system: str, prompt: str, model: str) -> str:
    h = hashlib.sha256()
    h.update(model.encode("utf-8"))
    h.update(b"\0")
    h.update(system.encode("utf-8"))
    h.update(b"\0")
    h.update(prompt.encode("utf-8"))
    return h.hexdigest()


def cached_complete(llm, system: str, prompt: str, model: str) -> tuple[str, bool]:
    """Returns (response_text, was_cache_hit)."""
    os.makedirs(CACHE_DIR, exist_ok=True)
    key = _cache_key(system, prompt, model)
    path = os.path.join(CACHE_DIR, f"{key}.json")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)["response"], True
    t0 = time.time()
    response = llm.complete(prompt, system=system)
    elapsed = time.time() - t0
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({
            "model": model, "elapsed_seconds": round(elapsed, 2),
            "prompt_chars": len(prompt), "response": response,
        }, fh, indent=2)
    return response, False


# ── response parsing ─────────────────────────────────────────────────────

def parse_response(text: str) -> list[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
        if text.lstrip().startswith("json"):
            text = text.lstrip()[4:]
    start = text.find("[")
    end = text.rfind("]")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"no JSON array found in response: {text[:200]!r}")
    return json.loads(text[start:end + 1])


# ── falsifying a type with evidence we already hold ─────────────────────
#
# Finding 84. The typing guide moved the vocabulary from 1 effective value to 6,
# but replaced one over-used value with two: `Long Running Daemon` was applied to
# `promql/`, `scrape/`, `rules/`, `notifier/` and `template/` — in-process
# managers, none of which is a separate process. Prometheus's own document says
# of the PromQL engine that it "does not run as its own actor goroutine, but is
# used as a library".
#
# The model cannot tell "runs as its own process" from "runs inside one". We can:
# **a component with no entry point among its constituents is not a daemon and
# not a console command.** That is a falsification, not a preference — those two
# types assert a mode of execution that the absence of an entry point refutes.
#
# The replacement is the detector's own type for the component's largest
# constituent, falling back to `Software Library` only because §3.1's list makes
# it the fall-through. Note this does NOT claim the replacement is right —
# ground truth says `scrape` is an `Automated Action`, and this will say
# `Software Library`. It claims only that the original was demonstrably wrong.
# Removing a false claim is progress even when the replacement is merely weaker.

_EXECUTION_TYPES = frozenset({"Long Running Daemon", "Console Command"})


def falsify_types(kept: list[dict], type_by_slug: dict[str, str],
                  files_by_slug: dict[str, list[str]]) -> tuple[list[dict], list[dict]]:
    """Reject execution-mode types unsupported by any entry-point evidence."""
    notes: list[dict] = []
    for item in kept:
        if item.get("type") not in _EXECUTION_TYPES:
            continue
        # NOT APPLICABLE to the deployment perspective. An entry point is a
        # first-party *code* signal (`package main` in a component root), and a
        # container running a third-party image is a long-running daemon that
        # has no first-party entry point BY DEFINITION. Finding 85 called this
        # rule "a falsification, not a preference" — true in the logical
        # perspective over first-party code, and false outside it, where the
        # premise fails and the rule confidently produces the opposite of the
        # truth. Finding 87 measured exactly that: seven real daemons
        # (Egeria Quickstart, DuckDB Server, Unity Catalog Server, ...) demoted
        # to Software Library.
        if item.get("perspective") == "deployment":
            continue
        slugs = item.get("candidate_slugs") or []
        if any(type_by_slug.get(s) == "Console Command" for s in slugs):
            continue                     # an entry point IS present — claim stands
        biggest = max(slugs, key=lambda s: len(files_by_slug.get(s, [])), default=None)
        replacement = (type_by_slug.get(biggest) if biggest else None) or "Software Library"
        if replacement in _EXECUTION_TYPES:
            replacement = "Software Library"
        notes.append({"name": item.get("name"), "was": item["type"],
                      "now": replacement,
                      "reason": "no entry point among its constituents — cannot be a "
                                "separate process"})
        item["type"] = replacement
    return kept, notes


# ── the partition check: groundedness is not correctness ────────────────
#
# Finding 82. On Kubernetes the model merged 24 independent `cmd/*` binaries —
# kube-apiserver, kubelet, kube-scheduler, kube-proxy, kube-controller-manager
# and nineteen others — into one component called "CLI Commands". Every slug was
# real, every glob grounded, the type valid: it passed `validate_and_ground`
# perfectly and destroyed all six ground-truth components in a single move,
# taking the target from 6/6 to 0/6.
#
# **Groundedness is not architectural correctness, and no amount of grounding
# checking will make it so.** §5.2's rule prevents invention; it says nothing
# about whether a merge is right. So this is a second, different kind of
# check — not "did you invent this?" but "does this grouping contradict
# evidence we already hold?"
#
# The evidence is already extracted. Finding 78 detects entry points properly
# (a package declaring `package main` in its own root, not a file named
# main.go), and `go_subsystems` types those components `Console Command`.
# **Twenty-four binaries are twenty-four independently deployable things**, and
# a merge unioning more than one of them is almost certainly wrong.
#
# On failure the merge is REJECTED rather than the candidates discarded: each
# constituent is passed through unmerged, which is exactly the pre-merge
# (deterministic) state for that group. Losing the model's grouping is a cost;
# losing the candidates would be a regression.

_ENTRY_POINT_TYPES = frozenset({"Console Command"})


def split_multi_perspective(kept: list[dict], perspective_by_slug: dict[str, str],
                            type_by_slug: dict[str, str], name_by_slug: dict[str, str],
                            files_by_slug: dict[str, list[str]],
                            ) -> tuple[list[dict], list[dict]]:
    """Reject a merge spanning perspectives — §4.2's "map, never merge".

    Design §4.1/§4.2: a Dockerfile-directory component (physical) and the
    compose service it builds (deployment) are not the same thing counted
    twice; they are two perspectives on one system, related one-to-many by
    `ImplementedBy`. Merging across them is a category error, not a granularity
    choice.

    Found by finding 87's post-mortem rather than reasoned from the design: on
    `egeria-workspaces` the model merged deployment candidates with logical ones,
    and because a mixed merge fell back to `perspective="logical"`, the
    deployment gate on `falsify_types` never engaged and seven real daemons were
    demoted anyway. Fixing the gate alone would have papered over the merge that
    caused it.

    Rejection passes the constituents through unmerged, as
    `split_multi_entrypoint` does — losing a grouping is a cost, losing the
    candidates would be a regression.
    """
    out: list[dict] = []
    notes: list[dict] = []
    for item in kept:
        slugs = item.get("candidate_slugs") or []
        seen = {perspective_by_slug.get(s) for s in slugs if perspective_by_slug.get(s)}
        if len(seen) < 2:
            out.append(item)
            continue
        notes.append({"name": item.get("name"),
                      "reason": f"merge spans perspectives {sorted(seen)} — §4.2 maps between "
                                f"perspectives, never merges across them"})
        for sl in slugs:
            out.append({
                "slug": sl, "name": name_by_slug.get(sl, sl),
                "type": type_by_slug.get(sl), "files": files_by_slug.get(sl, []),
                "perspective": perspective_by_slug.get(sl, "physical"),
                "confidence": 55, "confidence_level": "Derived",
                "proposed_by": ["llm-adjudicator", "perspective-split"],
                "rationale": "passed through unmerged: parent merge spanned perspectives",
                "candidate_slugs": [sl],
            })
    return out, notes


def split_multi_entrypoint(kept: list[dict], type_by_slug: dict[str, str],
                           name_by_slug: dict[str, str],
                           files_by_slug: dict[str, list[str]],
                           ) -> tuple[list[dict], list[dict]]:
    """Reject any merge spanning more than one entry point; return (out, notes)."""
    out: list[dict] = []
    notes: list[dict] = []
    for item in kept:
        slugs = item.get("candidate_slugs") or []
        entry_slugs = [s for s in slugs if type_by_slug.get(s) in _ENTRY_POINT_TYPES]
        if len(entry_slugs) < 2:
            out.append(item)
            continue
        notes.append({
            "name": item.get("name"),
            "reason": (f"merge spans {len(entry_slugs)} entry points "
                       f"({', '.join(sorted(entry_slugs)[:4])}...) — independently "
                       f"deployable things are not one component"),
            "candidate_slugs": slugs,
        })
        for s in slugs:
            out.append({
                "slug": s, "name": name_by_slug.get(s, s),
                "type": type_by_slug.get(s), "files": files_by_slug.get(s, []),
                "perspective": item.get("perspective", "physical"),
                "confidence": 55, "confidence_level": "Derived",
                "proposed_by": ["llm-adjudicator", "entrypoint-split"],
                "rationale": "passed through unmerged: parent merge spanned multiple entry points",
                "candidate_slugs": [s],
            })
    return out, notes


# ── the hard rule: post-validation, not prompting ───────────────────────

def validate_and_ground(raw_outputs: list[dict], valid_slugs: set[str],
                         files_by_slug: dict[str, list[str]],
                         perspective_by_slug: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """Returns (kept, dropped). `dropped` entries carry a `reason`.

    Every check here is the enforceable version of §5.2's rule: "the LLM never
    invents a component with no detector evidence behind it." Files are never
    taken from the model's output — they are always recomputed as the union of
    the referenced candidates' own globs, so "an output claiming files no
    candidate claimed" is structurally impossible rather than merely checked.
    """
    kept: list[dict] = []
    dropped: list[dict] = []

    for item in raw_outputs:
        name = item.get("name")
        ctype = item.get("type")
        slugs = item.get("candidate_slugs")

        if not isinstance(slugs, list) or not slugs:
            dropped.append({**item, "reason": "no candidate_slugs — ungrounded, no detector evidence"})
            continue

        unknown = [s for s in slugs if s not in valid_slugs]
        if unknown:
            dropped.append({**item, "reason": f"candidate_slugs not in input set: {unknown}"})
            continue

        if ctype not in SOLUTION_COMPONENT_TYPES:
            dropped.append({**item, "reason": f"type {ctype!r} not in the 13-value SolutionComponentType vocabulary"})
            continue

        if not name or not isinstance(name, str):
            dropped.append({**item, "reason": "missing/empty name"})
            continue

        files: list[str] = []
        for s in slugs:
            for g in files_by_slug.get(s, []):
                if g not in files:
                    files.append(g)
        # A DEPLOYMENT component may legitimately own no first-party files.
        # `egeria-workspaces.md` says so in its own text: "deployment components
        # frequently own no first-party files at all — kafka, postgres and kroki
        # are third-party images." Finding 82 called this rule
        # "conservative-but-arguably-too-strict" when it dropped one component
        # on Milvus; finding 87 measured it dropping fifteen on a
        # deployment-perspective target, taking 18/27 to 0/27.
        #
        # Groundedness there is the SLUG, not the file set: the candidate was
        # really proposed by a detector, which is what §5.2's rule asks. Only
        # perspectives whose components are defined by code keep the file
        # requirement.
        deployment_only = bool(slugs) and all(
            perspective_by_slug.get(s) == "deployment" for s in slugs)
        if not files and not deployment_only:
            dropped.append({**item, "reason": "referenced candidates carry no files — nothing to ground on"})
            continue

        perspectives = {perspective_by_slug.get(s, "physical") for s in slugs}
        perspective = perspectives.pop() if len(perspectives) == 1 else "logical"

        slug = "adj::" + "+".join(sorted(slugs))[:120]
        kept.append({
            "slug": slug, "name": name, "type": ctype,
            "files": files, "perspective": perspective,
            "confidence": 70, "confidence_level": "Derived",
            "proposed_by": ["llm-adjudicator"],
            "rationale": item.get("rationale", ""),
            "candidate_slugs": slugs,
        })

    return kept, dropped


# ── orchestration ────────────────────────────────────────────────────────

def adjudicate(target: str, root: str | None, model_override: str | None = None,
                backend: str = "anthropic") -> dict:
    from resource_explorer.config import ExplorerConfig, LLMConfig, AnthropicConfig, OllamaConfig
    from resource_explorer.llm_client import get_llm

    ir = load_distilled(target)
    components = ir["components"]
    ev_by_slug = evidence_by_slug(ir)

    if backend == "ollama":
        cfg = ExplorerConfig(llm=LLMConfig(
            backend="ollama",
            ollama=OllamaConfig(model=model_override or "qwen2.5-coder:32b"),
        ))
        model = cfg.llm.ollama.model
    else:
        cfg = ExplorerConfig(llm=LLMConfig(
            backend="anthropic",
            anthropic=AnthropicConfig(model=model_override or "claude-haiku-4-5-20251001"),
        ))
        model = cfg.llm.anthropic.model
    llm = get_llm(cfg)

    chunks = chunk_candidates(components, MAX_CANDIDATES_PER_CHUNK)

    all_raw: list[dict] = []
    calls: list[dict] = []
    for i, chunk in enumerate(chunks):
        prompt = build_prompt(chunk, ev_by_slug)
        response, hit = cached_complete(llm, SYSTEM_PROMPT, prompt, model)
        calls.append({
            "chunk": i, "candidates": len(chunk), "prompt_chars": len(prompt),
            "cache_hit": hit,
        })
        try:
            parsed = parse_response(response)
        except ValueError as exc:
            calls[-1]["parse_error"] = str(exc)
            parsed = []
        all_raw.extend(parsed)

    valid_slugs = {c["slug"] for c in components}
    files_by_slug = {c["slug"]: c.get("files", []) for c in components}
    perspective_by_slug = {c["slug"]: c.get("perspective", "physical") for c in components}

    kept, dropped = validate_and_ground(all_raw, valid_slugs, files_by_slug, perspective_by_slug)

    type_by_slug = {c["slug"]: c.get("type") for c in components}
    name_by_slug = {c["slug"]: c.get("name", c["slug"]) for c in components}
    kept, persp_notes = split_multi_perspective(kept, perspective_by_slug, type_by_slug,
                                                name_by_slug, files_by_slug)
    kept, split_notes = split_multi_entrypoint(kept, type_by_slug, name_by_slug, files_by_slug)
    split_notes = persp_notes + split_notes
    kept, type_notes = falsify_types(kept, type_by_slug, files_by_slug)

    referenced = {s for item in kept for s in item["candidate_slugs"]}
    for n in split_notes:
        print(f"  REJECTED MERGE: {n['name']!r} — {n['reason']}")
    for n in type_notes:
        print(f"  FALSIFIED TYPE: {n['name']!r} {n['was']} -> {n['now']} — {n['reason']}")

    out_ir = {
        "target": f"{target}-adjudicated",
        "checkout": root or ir.get("checkout", ""),
        "analyzer": {**ir.get("analyzer", {}), "adjudicator": "llm-adjudicator/0.1.0",
                     "adjudicator_model": model},
        "census": ir.get("census", {}),
        "components": kept,
        "ports": [],
        "wires": [],
        "evidence": ir.get("evidence", []),
        "notes": ir.get("notes", []),
    }

    report = {
        "target": target, "model": model,
        "input_candidates": len(components),
        "output_components": len(kept),
        "dropped_count": len(dropped),
        "dropped": dropped,
        "candidates_referenced": len(referenced),
        "candidates_unreferenced": len(components) - len(referenced),
        "chunks": calls,
    }
    return out_ir, report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target")
    ap.add_argument("--root", help="checkout root, recorded into the output IR")
    ap.add_argument("--model", help="override the model id")
    ap.add_argument("--backend", default="anthropic", choices=["anthropic", "ollama"],
                     help="LLM backend (default anthropic; falls back to local ollama "
                          "when there is no API credit)")
    ap.add_argument("--out")
    ap.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = ap.parse_args()

    out_ir, report = adjudicate(args.target, args.root, args.model, args.backend)

    out_path = args.out or os.path.join(SPIKE_DIR, "ir", f"{args.target}-adjudicated.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out_ir, fh, indent=2)

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"wrote {out_path}")
        print(f"  model: {report['model']}")
        print(f"  input candidates: {report['input_candidates']}")
        print(f"  output components: {report['output_components']}")
        print(f"  candidates referenced by output: {report['candidates_referenced']}")
        print(f"  candidates not referenced (left out, not merged into anything): "
              f"{report['candidates_unreferenced']}")
        print(f"  dropped by guardrail: {report['dropped_count']}")
        for d in report["dropped"]:
            print(f"    - {d.get('name')!r}: {d['reason']}")
        for c in report["chunks"]:
            hit = "cache hit" if c["cache_hit"] else "cache miss (called LLM)"
            extra = f" PARSE ERROR: {c['parse_error']}" if "parse_error" in c else ""
            print(f"  chunk {c['chunk']}: {c['candidates']} candidates, "
                  f"{c['prompt_chars']} prompt chars, {hit}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
