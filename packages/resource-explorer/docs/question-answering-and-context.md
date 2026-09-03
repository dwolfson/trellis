# Question answering and context — retrieval, compilation, and routing

**Status:** consolidated design. Current as of 2026-09-02.
**Scope:** how a free-text question becomes an answer — what is retrieved, how
evidence is compiled into a bounded context, how a question is routed to the
right tool, and what code intelligence supplies. For the fixed question
catalogue and how surveys answer it, see `survey-model.md`.

> **This document consolidates five.** Part I is the ad-hoc question-answering
> review (what exists, the four question classes, coverage, intent recognition).
> Part II merges the context compiler, tool routing, code intelligence, and RAG
> ingestion as an analysis step. Part III is the settled register.

## 0. The headline finding: this isn't greenfield, and half of it is broken

Before scoping "how would we build this," it's worth being clear that an
ad-hoc chat path **already exists and is live** — `ConversationAgent`
(`resource_explorer/agents/conversation_agent.py`), reached from
`POST /api/query` (`resource_explorer/web/routes/query.py:186-187,236-237`),
backed by a BeeAI tool-calling loop over `resource_explorer/agents/tools.py`.
It is not the fixed 49-question catalog `FactLayer` serves — it is exactly
the free-text, no-catalog-entry mechanism this note was asked to design.

Two things are true about it at once:

1. **It already has a working bridge to the honest layer.** As of
   `e729640` (2026-08-30) and `c8f96f0`, `ConversationAgent._compiled_evidence()`
   calls `context_compile.compile_context()` — the same
   `question_catalog_reader` + `FactLayer` machinery this note was pointed
   at — and injects it into the prompt as an "Evidence (compiled from stored
   analysis results)" block, with a same-turn, tested instruction to prefer
   it over `vector_search` and to say so and stop rather than substitute a
   general-corpus answer when it doesn't cover the question
   (`conversation_agent.py:60-77`, `tests/test_conversation_agent_compiled_evidence.py`).
   That is the refusal discipline this note was asked to require — already
   built, for the single-resource case.

2. **The tool layer underneath it is reading a stale, empty datastore for
   exactly the questions in Dan's example.** `resource_explorer/agents/tools.py`
   and `stats_agent.py`/`health_agent.py` open `sqlite3.connect(registry.db_path)`
   directly (8 call sites in `tools.py` alone) — bypassing the
   `ProjectRegistry` engine entirely. Since the 2026-08-07 SQLite→Postgres
   migration (`git log`, `c8f96f0`'s ancestor), `data/registry.db` is a
   **0-byte file** (`ls -la data/registry.db` → `-rw-r--r-- ... 0 Aug 23`).
   Verified live:

       $ uv run python -c "from resource_explorer.agents.tools import _query_code_symbols_raw; \
         print(_query_code_symbols_raw('egeria_git', kind='class', limit=3))"
       Error reading symbol table: no such table: project_code_symbols

   `query_code_symbols` is the tool that answers "how many classes" and
   "list the classes/methods" — i.e. two of Dan's four examples, directly.
   It fails today, and the failure is an unrouted Python exception string
   handed back to the LLM to narrate, not a `FactLayer`-shaped refusal.
   Compare `FactLayer().fact('egeria_git', 'code_symbol_extraction')`, which
   reads the same underlying data through the Postgres-backed registry and
   returns the right answer:

       $ uv run python -c "from resource_explorer.facts import FactLayer; \
         f = FactLayer().fact('egeria_git', 'code_symbol_extraction'); print(f.state, f.value)"
       measured {'symbol_count': 42116.0, 'relationship_count': 2513.0, 'by_language': {'java': 42116}, ...}

   The honest number exists one layer over from where the chat tool looks
   for it. `query_dependencies` (`tools.py:620-655`) is the counter-example
   done right: it calls `registry.query_dependencies()` (the SQLAlchemy
   engine, i.e. Postgres) and routes empty results through `_absence()`
   (`tools.py:7-36`), which itself asks `FactLayer` whether "empty" means
   `never_run` or `nothing_found` before saying anything. `CompareAgent`,
   `IntegrationAgent`, `DependencyAgent`, `StatsAgent`, `CodeAgent`
   (`resource_explorer/agents/*.py`) are a second, older, unrelated
   dispatch path (`RAGSystem._route()`, `resource_explorer/rag_system.py`),
   reached only as `ConversationAgent`'s exception fallback — they predate
   `facts.py` (agents present by 2026-08-06; `facts.py` from 2026-08-26) and
   carry none of its discipline: `CompareAgent`/`IntegrationAgent` hand the
   LLM raw tool output and a "be concrete, don't speculate" instruction with
   no structural guarantee behind it, and no coverage statement at all.

This reframes the task. The gap is not "no mechanism for ad-hoc questions" —
it is (a) a live datastore bug in the tool layer for code-inventory
questions specifically, and (b) no cross-resource equivalent of what
`compile_context`/`_compiled_evidence` already does for one resource.

## 1. What exists, read first

- `resource_explorer/facts.py` — `FactLayer`, `Fact`, `Envelope`. States:
  `measured`, `nothing_found`, `never_run`, `not_established`, `partial`
  (`surveyors/result_status.py`). `Envelope.answerable` is `False` unless at
  least one fact `is_known`; a caller cannot turn "unanswerable" into a
  negative answer (`facts.py:109-126`). `FactLayer.answer()` is the 49-entry
  catalog path: it looks up `answering.kind`/`analysis_ids` off a question
  dict and refuses outright for `gap`/`human`/`unknown` kinds
  (`facts.py:682-729`, `UNANSWERABLE_KINDS` at `:155-161`).
- `resource_explorer/surveyors/question_catalog_reader.py` — loads
  `configdata/question_catalog.yaml` (generated from
  `docs/dr-egeria/resource_questions.csv`), each entry carrying
  `answering.analysis_ids`/`checks`. Purpose orders, Perspective filters
  (`get_questions()` docstring, `:108-160`). Fixed catalog only — no path
  for a question not in the CSV.
- `resource_explorer/context_compile.py` — `compile_context()`. Turns
  `get_questions()`'s Purpose/Perspective → analysis_ids chain into a packed
  text block plus a `manifest.gaps` list, each gap phrased from
  `result_status` (`_GAP_PHRASING`, `:44-50`): "has not run" vs "ran and
  found nothing" vs "ran over only part of what it covers" are different
  sentences, never collapsed. This is the piece that already generalizes
  the fact-layer discipline past the fixed catalog, for single resources.
  It works by keyword-overlap ranking against the *catalogued* question
  text (`_question_relevance`, `_STOPWORDS` at `:78-83`) — so it degrades
  gracefully but silently on a phrasing far from any catalog entry; not
  measured here how far.
- `resource_explorer/agents/conversation_agent.py` — the live ad-hoc path.
  `_compiled_evidence()` wires `compile_context()` in; system prompt tells
  the model to prefer it and refuse-and-ask rather than substitute
  `vector_search` (tested, `:60-77`). Single-resource only —
  `resource_slug` is a scalar throughout.
- `resource_explorer/rag_system.py` + `agents/{stats,compare,integration,
  dependency,code,health,examples,doc,survey_meta}_agent.py` — older, still
  routed to as `ConversationAgent`'s exception fallback and directly from
  `query.py:236-237`'s streaming path. `query_processor.py`'s
  `QueryProcessor.classify()` is a **pure regex-priority router** over
  `configdata/routing.yaml` (`intent_patterns`), first match wins, no LLM,
  no confidence, no fallback-to-decline — closest existing analog to "how
  is ad-hoc intent recognized," and it is regex-only today.
- `resource_explorer/surveyors/sub_surveyors/interface_surface.py` — the
  actual "published API" detector. Two-tier evidence, kept apart on
  purpose: `SPECIFIED` (an `openapi.yaml`/`.proto`/`.graphql`/`.wsdl` file
  committed in the repo — `_SPEC_PATTERNS`, confidence 100) vs `IMPLIED` (a
  dependency like `fastapi`/`grpcio` — confidence 60), because "the two
  sources disagree far more often than they overlap" (module docstring,
  measured 2026-08-26: 9 openapi/swagger files across 4 repos, 32 `.proto`
  across 4, 2 GraphQL across 2, vs 17 repos with an HTTP-framework
  dependency and 22 with a CLI-framework one). This is the honest answer to
  "does X have a published API," and it is a different, narrower claim than
  "how many classes does X have."

## 2. What's actually in the registry — measured just now, live

Queried `postgresql://…@localhost:5442/egeria_advisor` (`schema
resource_explorer`) read-only via `ProjectRegistry().engine`, 2026-09-01:

| table | rows | distinct repos | notes |
|---|---:|---:|---|
| `project_code_symbols` | 437,060 | 51 (of 60 registered) | columns: `kind` (not `symbol_kind`), `name`, `qualified_name`, `signature`, `docstring`, `file_path`, `start_line`/`end_line`, `parent_class`, `complexity`. `kind` values: `method` 291,830 · `function` 83,832 · `class` 45,813 · `interface` 14,423 · `enum` 1,162. `language`: java 203,521 · python 114,051 · go 70,955 · javascript 48,533 — **four languages only**. |
| `project_code_relationships` | 23,559 | 46 | `relationship_type` is **`inherits_from` exclusively** — no `calls`, `imports`, or cross-repo edge of any kind exists in this table today. |
| `project_dependencies` | 32,379 | 50 (of 60) | `dep_name`, `dep_version`, `dep_type`, `ecosystem`, `source_file`, `dep_version_source`. |
| `project_analysis_findings`, `kind='interface_surface'` | 216 | (subset) | `check_name` includes `published_spec`: **102 findings** across the whole registry. |
| `project_analysis_findings`, `kind='architecture_interfaces'` | 13,465 | (subset) | ports/wires from the dependency-topology sub-surveyor — a different question ("what talks to what at runtime, within one docker-compose") than "what is the published API," not to be conflated with it. |
| `projects` | 60 | — | the registered-resource denominator. |

Two corrections to the task brief's numbers, both material:

- `project_code_symbols` **does** have a kind column — it's named `kind`,
  not `symbol_kind`. The brief's caveat about not knowing this was right to
  flag; the actual answer is "there is a column, use it."
- `interface_surface` findings are 216, but only 102 of those are
  `published_spec` (the strong, `SPECIFIED`-evidence kind) — the rest are
  `interface_kind` findings (the weaker, dependency-implied ones). "How
  many APIs does X publish" and "does X appear to expose any interface at
  all" are two different counts sitting in the same 216 rows; a query that
  doesn't split on `check_name`/`detail.evidence` will silently answer the
  wrong one.

`project_code_relationships` being `inherits_from`-only is the load-bearing
fact for the "do X and Y integrate?" class below — there is no
cross-repo-call, no cross-repo-import, nothing in this table that could ever
answer that question, at any coverage level. It answers "what inherits from
what," which is an intra-repo design question with no bearing on
integration.

## 3. The four classes

### Counting — "how many APIs / classes?"

**Answerable today, from structured data, with a live bug in the only path
to it.** `code_symbol_extraction`'s results reader
(`repo_survey_definition_adapter.py:1806-1821`, `_api_structure_results`)
does `SELECT language, kind, COUNT(*) FROM project_code_symbols WHERE
project_slug=? GROUP BY language, kind` through the Postgres-backed
registry connection and is correct, verified above. `FactLayer.fact(slug,
"code_symbol_extraction")` already carries the coverage question halfway:
`state` distinguishes `measured` from `never_run`. It does **not** currently
carry "covered 340 of 900 files" — see §4.

"How many APIs" is ambiguous and the note flags rather than resolves it:
does the asker mean *published external contracts* (`interface_surface`,
`published_spec` — 102 registry-wide) or *public methods/classes exposed by
the codebase* (`api_structure`/`code_symbol_extraction` — hundreds of
thousands)? These are different tables, different orders of magnitude, and
an intent router that picks one without surfacing the choice will answer a
question the asker didn't ask. Recommendation in §5: when ambiguous, name
both interpretations rather than silently picking one.

### Listing — "what are the APIs for X?"

**Answerable today** from the same tables, with the same live bug and one
more failure mode: **unmarked truncation**. `_query_code_symbols_raw`
(`tools.py:201-256`) does compute `total` separately from the `LIMIT`-ed
`rows` and does say "showing first N" when `total > limit` — that part is
already done right, once the datastore bug is fixed. `interface_surface`'s
listing path has no equivalent audit; confirm before shipping "list the
APIs" that whatever renders `published_spec` findings states a truncation
the same way, since the doc gave this as the named failure mode.

### Comparison — "difference between repo X and repo Y?"

**Partially answerable, and the hardest of the four to do honestly.**
`CompareAgent` exists (`agents/compare_agent.py`) and runs today, but it is
on the old, undisciplined path: it hands the LLM `query_project_stats` +
`vector_search` output for each side and a structuring instruction, with
**no coverage check that both sides were actually surveyed**, and no
`never_run`/`nothing_found` distinction if one side wasn't. A comparison
built on `code_symbol_extraction` facts for both slugs would inherit
`FactLayer`'s per-side `state`, which is necessary but not sufficient: the
genuinely hard case is not "was analysis X run on repo A" (that's a lookup)
but "was it run at the **same completeness**" — a repo with symbol
extraction covering 4 of 4 languages compared against one covering 1 of 3
is not a fair diff even though both sides are `measured`. Nothing in the
codebase computes that today (§4/§6 below).

### Relationship — "do X and Y integrate?"

**Weak, and the design doc should say so rather than build around it.**
`IntegrationAgent` exists and runs on the old path — no structural
guarantee, LLM told to "say so if not well-documented" as a suggestion,
not a contract. The two structured signals available are: (a) shared
`project_dependencies` rows (`registry.query_shared_dependencies`, used
correctly by `DependencyAgent._fallback`) — a shared package name is weak
evidence of integration (both could depend on `requests` and never touch
each other), and (b) `interface_surface`'s `published_spec` findings — X
publishes an OpenAPI contract, Y depends on an HTTP client, is suggestive
at best. `project_code_relationships` is **not** usable for this at all
(§2 above — `inherits_from` only, and intra-repo). There is no
cross-repo call graph, no traced request path, nothing that could
establish "these two systems actually talk to each other" as opposed to
"these two systems could plausibly talk to each other." This class should
ship with the weakest claim strength of the four and say so in every
answer, not just in this doc.

## 4. Coverage as a first-class part of every answer

The brief's own example — "12 APIs recorded, from an extraction that
covered 340 of 900 files" — is not achievable today for any of the four
classes, and it's worth being precise about why: **the denominator isn't
stored.** `code_symbol_extraction`'s results reader returns
`symbol_count`/`relationship_count`/`by_language`; nothing in that dict or
in `project_code_symbols` says how many files were *candidates* for
extraction versus how many were *actually parsed*. `project_file_type_counts`
(referenced in `stats_agent.py:_indexed_file_count`) carries a total file
count by survey, but nothing joins it against "of those, how many were in a
supported language and successfully parsed" to produce the "340 of 900"
shape. Two things would need to exist before an answer could honestly carry
that number:

1. **A per-run coverage record** — files attempted vs. files that yielded
   at least one symbol, at extraction time, persisted alongside
   `symbol_count`. This is a change to `code_symbol_extraction`'s surveyor
   and results reader (out of scope for this doc's write boundary — flagged
   for whoever owns that step, not touched here).
2. **A language-support disclosure** — "4 languages" (java/python/go/js) is
   knowable today (§2's measured breakdown) but isn't currently stated
   alongside a count. "127 classes" on a Rust repo should read as "0
   classes recorded — this extractor does not cover Rust" rather than a
   silent, indistinguishable-from-real zero. This is exactly the
   `nothing_found`-vs-`never_run` distinction `facts.py` already has
   vocabulary for; it just isn't wired to a language-support check yet.

Until (1) exists, the honest form of a count/list answer is: the number,
`state` (measured/never_run/partial), `last_run_at`, and languages actually
present in `project_code_symbols` for that slug versus the repo's declared
primary language(s) from `project_stats` — a proxy for coverage, not
coverage itself, and should be labeled as a proxy. `Envelope.can_run`
already carries what step would improve a `never_run`/`partial` fact
(`facts.py:126-135`) — that machinery generalizes to ad-hoc answers for
free once they go through `FactLayer` rather than a raw tool call.

For comparison specifically: coverage must travel **per side**, not as one
combined statement — "repo A: measured, 4/4 languages present; repo B:
never_run" is a different answer than a diff table, and the diff must not
be computed at all when one side is `not measured` (see §3's diff-fairness
point — even "measured both sides" isn't sufficient, but "measured one
side" is a hard block, not a caveat).

## 5. Intent recognition — options and recommendation

Three options, weighed on the axis the brief asked for: reliability vs. the
cost of a wrong route, where a misrouted question that answers confidently
from the wrong table is explicitly worse than a decline.

- **Pattern/keyword routing** (what exists: `query_processor.py`,
  regex-priority over `routing.yaml`). Cheap, deterministic, debuggable,
  zero LLM cost. Its failure mode is silent misclassification on phrasing
  the regex didn't anticipate — "how many APIs" plausibly doesn't match
  `intent_patterns.statistical` or `.dependency` and falls through to
  `GENERAL`, which is `ConversationAgent`'s default free-tool-call mode,
  i.e. the least-structured path, not a decline. A near-miss doesn't fail
  loud; it fails into the wrong (or weakest) handler.
- **LLM classifier.** Handles paraphrase and compound questions
  ("list the APIs and say how many") a regex can't. Its failure mode is the
  one the brief calls out explicitly: a wrong-but-confident classification
  is no better than no classification, and now there's an added point of
  non-determinism and latency/cost per question.
- **Hybrid — recommended.** Keep `context_compile.py`'s
  `_question_relevance` keyword-overlap approach (already built, already
  proven at the single-resource single-catalog-question scale) as the
  *first* pass for **counting/listing** questions, because those map
  cleanly onto a small, enumerable set of tables (`project_code_symbols`,
  `project_dependencies`, `interface_surface` findings) and a keyword match
  against "how many / list / count" plus a resource-name match is low-risk
  to get right deterministically. Reserve an LLM step for exactly the two
  classes that need judgment a keyword match can't provide: **which two
  resources** a comparison/relationship question means (see §7) and
  **disambiguating "API"** (§3) when the keyword match is genuinely
  ambiguous. Critically: the LLM step's job is narrowed to *classification*,
  never to *answering* — its output is "route to counting-handler for
  repo=X, api-sense=published" or "insufficient — ask which repo," not
  prose. That keeps the failure mode of a wrong LLM call bounded to a
  misroute (caught by the same "both sides must be measured" / `answerable`
  checks already in `Envelope`) rather than a hallucinated number.

The cost-of-wrong-route asymmetry argues for erring toward decline: a
router that isn't confident in the resource name, the question class, or
the API-sense should return `Envelope(answerable=False, blocked_reason=...)`
rather than guess a plausible-sounding route, exactly as `FactLayer.answer()`
already does for uncatalogued `answering.kind`s.

## 6. The refusal path

`Envelope` and `Fact` already are the refusal contract — `answerable`,
`blocked_reason`, `can_run`. The design decision for ad-hoc is not to invent
a new one; it's to make every new ad-hoc handler *produce* an `Envelope`
instead of a formatted string, so the `ConversationAgent` prompt-injection
pattern already proven in `_compiled_evidence()` (evidence block + "prefer
this, refuse-and-ask rather than substitute") applies unchanged to
counting/listing/comparison/relationship answers, not only to catalogued
ones. Concretely: an ad-hoc counting handler that finds `never_run` should
say so and name the runnable step (`can_run`), the same sentence shape
`_absence()` already produces in `tools.py` for dependencies — that helper
is the pattern to generalize, not to leave as dependency-only.

## 7. Cross-resource naming resolution

Every cross-resource agent (`CompareAgent._infer_all_project_slugs`,
`IntegrationAgent`, `DependencyAgent`) resolves "repo x" the same
brittle way today: `p.slug in q_lower or p.display_name.lower() in q_lower`
— a raw substring match against `ProjectRegistry().list_all()`
(`compare_agent.py` uses `self._infer_all_project_slugs`, defined per-agent
identically in `dependency_agent.py:78-84`). This breaks on any name the
user shortens, aliases, or gets slightly wrong, and fails silently into
"fewer than two slugs found → ask for clarification" — which is at least a
decline, not a wrong guess, but a decline on names a human would resolve
immediately (e.g. "egeria" vs the registered slug `egeria_git`) is a bad
experience for the common case. Not measured here: how often a real slug
fails this substring test against how a person would actually phrase it —
that's worth checking against the 60 registered slugs before building
routing around it.

The half of this problem the brief calls out — "must handle one side being
unanalysed differently from both being analysed and genuinely differing" —
is not a naming problem, it's the coverage problem from §4 applied
per-side: resolve both slugs first (hard-block if either fails to resolve,
same as today), THEN check `FactLayer.fact()` state for both before running
any diff, and report three distinct outcomes rather than two: (1) both
measured → the diff, (2) one side `never_run`/`not_established` → name
which side and what would establish it, never a diff with one column
blank, (3) both unmeasured → decline outright, don't imply there was
anything to compare.

## 8. Honest limits — what this note could not determine

- **How far `_question_relevance`'s keyword overlap degrades** on phrasing
  distant from the 49 catalogued questions — not measured; would need a
  sample of real ad-hoc phrasings run through `compile_context()` and
  human-graded, before trusting it as the counting/listing first pass in
  §5.
- **Whether `_absence()`'s pattern generalizes cleanly** beyond
  dependencies to code-symbol and interface-surface facts — plausible from
  reading it, not verified against a live call the way `query_dependencies`
  was.
- **File-level coverage denominators** (§4, "M of N files") are not
  computed anywhere in this codebase today; how expensive that would be to
  add is a question for whoever owns `code_symbol_extraction`'s surveyor
  (outside this task's write boundary — the agent holding
  `sub_surveyors/data_profiler.py`/`dependency.py` per the task's ground
  rules).
- **Slug-resolution failure rate** against real phrasing (§7) — flagged,
  not measured.
- **Whether the `agents/*.py` fallback path (`RAGSystem`, `CompareAgent`,
  `IntegrationAgent`, etc.) should be repaired in place or retired** once a
  `FactLayer`-backed ad-hoc handler exists for counting/listing — this note
  found the sqlite/Postgres bug but didn't scope a fix; that's a decision
  for whoever owns `tools.py`/`stats_agent.py`, not a design call this note
  makes for them.

## 9. Recommended first slice

Not a complete system. The smallest thing that answers one real question of
Dan's end to end, honestly:

**Fix `query_code_symbols`/`_query_code_symbols_raw` to read through
`ProjectRegistry`'s engine instead of a dead `sqlite3.connect(registry.db_path)`,
and route its empty/error paths through `FactLayer`-shaped refusal (reusing
`_absence()`'s pattern) instead of a bare exception string.**

This is deliberately narrow and deliberately not a new subsystem:

- It answers two of Dan's four literal examples — "how many classes" and
  "list the APIs" (in the code-inventory sense) — with real, already-correct
  data one query away, per §3's measurement.
- It fixes a bug that is live today, not hypothetical — every ad-hoc
  question through the current chat path that touches code symbols fails
  right now.
- It is the smallest unit that proves the "generalize `_absence()`/`Envelope`
  beyond dependencies" pattern from §6 works, before building the harder
  cross-resource comparison/relationship classes on top of it.
- It explicitly does NOT attempt: file-coverage denominators (§4, needs a
  surveyor change out of scope), the hybrid intent router (§5, needed once
  there's more than one handler to route between), or cross-resource
  comparison/relationship (§3/§7, the two hardest and evidentially weakest
  classes — sequence those after the single-resource path is proven
  correct and honest).

Everything past this slice — comparison, integration, the hybrid router,
coverage denominators — should be built once this narrowest case is live
and has actually been asked a few real ad-hoc questions, not designed
further in advance of that.

---

# Part II — Compilation, routing, and the substrate

*Merged 2026-09-02 from four notes. Each section names its source.*

## 8. The context compiler

*(from `context-compiler-across-trellis.md`)*

A compile is **three inputs and one rule**, and the rule is the important part:
**nothing is run.** Resolvers read stored results only, and an analysis that has
not run produces a **gap**, not a silent absence.

| element | what it is |
|---|---|
| `ContextSpec` | the recipe — sections with roles, weights and floors, pinned to a target model and an `as_of` time |
| `Candidate` | one section's content at several **rungs**: `FULL → SUMMARY → IDENTIFIERS` |
| `pack(spec, candidates, budget)` | fits candidates to the budget using weights and floors |
| the manifest | what was included, what was cut, and **why each section is there** |

Three things in that picture are load-bearing and easy to miss:

- **The derivation travels with the answer.** *"This section is here because your
  Purpose is Certify, which ranked Q17, which dispatches security_scan."* It is
  what makes the manifest an explanation rather than a list of sizes.
- **The reader fallback is about evidence, not precedence.** The findings table
  holds results for a *minority* of analyses. An earlier version fell back only
  when findings were empty, so any whole-resource row — however slight —
  suppressed the reader entirely, and a single diagram row replaced an analysis's
  real results with a picture. It now consults both when findings are thin and
  keeps whichever says more.
- **A gap is judged, not merely reported.** The packer knows only that a section
  had no candidate. The fact layer knows whether that is a *measured zero* or a
  *never-run*, and those are opposite answers to the same question.

**Rungs matter because degrading beats dropping.** Under budget pressure a
section loses detail rather than disappearing: losing detail is recoverable,
losing the fact that something exists is not.

## 9. Context as declared facts, not inferences

*(from `repo-context-and-tool-routing.md`)*

The context vocabulary should be small, cheap, and **observable** — properties an
analysis can precondition on without anyone guessing.

| context fact | observable from | available? |
|---|---|---|
| holds first-party code | the exclusion census, `first_party_ratio` | yes |
| is deployable | Dockerfile / compose / k8s manifests | yes |
| has embedded documentation | in-repo doc paths | yes |
| has a documentation site | sibling repo / homepage / ingested site | yes |
| has tests | test-directory conventions | partially |
| declares a package | npm / pypi / gradle / cargo manifests | yes |
| repo role | `repo_classification` | yes |

> **Every row is already produced by something.** What is missing is that they are
> **findings scattered across kinds**, rather than one context record an analysis
> can precondition on. This is an assembly problem, not a detection problem — which
> makes it much cheaper than it looks.

**Interest is a signal to surface, not a threshold to enforce.** Routing should
show the user what it thinks is relevant and let them override, rather than
silently filtering on a score.

**When a question is ambiguous, name both interpretations rather than silently
picking one.** *"How many APIs"* can mean published external contracts (~102
registry-wide) or public methods and classes exposed by the codebase (hundreds of
thousands). Different tables, different orders of magnitude — and a router that
picks one without surfacing the choice answers a question the asker did not ask.

## 10. Code intelligence — the structured substrate

*(from `code-intelligence-approach.md`)*

Symbol extraction populates the tables that make counting and listing questions
answerable from structured data rather than retrieval: symbols by language and
kind, and inheritance relationships. Retrieval answers *"what does this do"*;
these tables answer *"how many"* and *"which"* — and conflating the two is how a
count gets estimated from prose.

The coverage caveat from `repo-analysis-funnel.md` §13 applies directly here: an
extractor that does not read a language's doc comments reports zero for it, and
zero is not a property of the code.

## 11. RAG ingestion as a survey step

*(from `rag-ingestion-as-analysis-step-plan.md`)*

- **D1 — the step wraps the *incremental* indexer, not full ingestion.** The
  incremental path is a **no-op when the commit SHA is unchanged**, which is what
  makes it cheap enough to include in a survey that runs often. Full ingestion
  stays at registration: a survey step must never be the thing that decides to
  embed a repository from scratch for the first time.
- **D2 — it declares no shared zipball resource**, deliberately diverging from the
  other steps. The incremental indexer downloads *conditionally*, only when files
  changed; declaring the resource would force a download on every run including
  the no-op case, making the cheap path expensive.

That second decision is the clearest case in the codebase of a shared-resource
declaration being *wrong* even though it is consistent — consistency would have
cost the property that makes the step usable.

## 12. Cross-resource questions: comparison and integration

*(from `comparison-integration-approach.md`)*

A class of question the routing above cannot serve, because it spans resources:

- **Comparison** — *"Which project has more contributors, A or B?"*, *"How does A
  compare to B on community health?"*
- **Integration** — *"Can I use A with B?"*, *"Which of these work together for an
  MLOps pipeline?"*

Today each query routes to **one** resource's collections and can only answer
within that scope, so cross-resource questions fall through to the general
retrieval path with no multi-resource awareness — and answer confidently about one
of the two things asked about.

Detection is pattern-based on the query text (comparison connectives, integration
verbs), and the important design consequence is that a comparison question needs
**structured** answers from both sides rather than retrieved prose from either:
contributor counts and health scores come from the stats and findings tables, not
from documents that happen to mention them.

Not built.

---

# Part III — Settled — do not reopen without re-measuring

| Question | Settled | On what basis |
|---|---|---|
| Is ad-hoc question answering greenfield? | **No** | A live chat path already exists and is bridged to the evidence layer |
| Should retrieval answer counting questions? | **No** | Counts come from the symbol tables; retrieval estimates them from prose |
| Should an ambiguous question be routed to one interpretation? | **No** — name both | "How many APIs" spans two tables and three orders of magnitude |
| Is interest a threshold to filter on? | **No** — a signal to surface | Filtering silently removes what the user might have wanted |
| Does the compiler run analyses to fill a gap? | **No** | Resolvers read stored results only; a gap is a result |
| Should a section be dropped when over budget? | **No** — degraded | Losing detail is recoverable; losing existence is not |
| Is an empty section an absence? | **No** — it is judged | The fact layer decides measured-zero versus never-run |
| Should the RAG step reuse the shared zipball? | **No** | It downloads conditionally; declaring the resource would force a download on every no-op run |
| Should a survey step perform first-time ingestion? | **No** | Full ingestion belongs at registration |
