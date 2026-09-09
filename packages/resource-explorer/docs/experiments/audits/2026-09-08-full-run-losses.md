# Audit: the 16 pairs where RAG beat compiled (run `full-20260908`)

Source: `data/experiments/compiled_vs_rag/results.jsonl`, 312 rows → 156 pairs, all pairs complete.
Confirmed: 16 pairs where `answers_question` is lower under `compiled`, 33 pairs where compiled
scored 0. Working files: `losses.txt`, `zeros.txt`, `win2.txt` in this directory.

## The 16 losing pairs

Cause key: **A** over-eager refusal · **B** evidence displaced the answer · **C** rung too thin/coarse
· **D** genuinely outside stored analyses, RAG's unsupported answer judged useful · **E** judge error
· **F** other.

| repo | question (short) | stage / kind | c | r | cause | reason |
|---|---|---|--:|--:|:--:|---|
| egeria | What kind of thing is this repo? | Discovery/analysis | 1 | 2 | F | compiled emitted the bare token `samples`; rag "This repository is a library." Both unsupported; judge rewarded the sentence, not the content. |
| egeria | Already catalogued in Egeria, when? | Discovery/direct | 1 | 2 | E | compiled "No, there is no evidence of a previous catalogue." vs rag "No, this repository has not been catalogued in Egeria yet." Same answer; the hedged one lost. |
| egeria | Self-described for enterprise catalog? | Assessment/analysis | 1 | 2 | E | compiled "No, there is no catalog-info.yaml found." — *more* specific than rag's "not self-described for an enterprise catalog". |
| kafka | Self-described for enterprise catalog? | Assessment/analysis | 1 | 2 | E | identical shape to the row above, same repo-independent judge behaviour. |
| egeria | What does this repository do? | Scouting/direct | 0 | 1 | B | "serves HTTP/REST (14 operations); 3 runnable unit(s); from 87 candidate component(s)" — architecture_summary fragments in place of a purpose statement. |
| egeria | Who maintains this repository? | Scouting/analysis | 0 | 1 | B | "maintained by a small group of 6 contributors, with one contributor accounting for half of all commits" — answers *how concentrated*, not *who*; `contribution_provenance` was a named gap and the model ignored it. |
| docling | Who maintains this repository? | Scouting/analysis | 0 | 1 | B | "maintained by the project team, as indicated by the 'cla_dco_enforced' status being 'partial'" — a non-sequitur built from a packed flag name. |
| egeria | Telemetry / phone-home present? | Analysis/analysis | 1 | 2 | E | compiled "The evidence does not cover what was asked." was **right**: `telemetry_scan` is a `not_established` gap here. rag asserted "There is no evidence of telemetry…" from nothing and scored 2. |
| kafka | Telemetry / phone-home present? | Analysis/analysis | 1 | 2 | E | compiled cited `AbstractSegments.java:188` and `:201` (`cites_evidence=true`); rag denied telemetry flatly and won. |
| egeria | What dependencies does this require? | Analysis/analysis | 0 | 1 | C | `dependency_analysis` ranked first yet the answer is "9 action references, pinned to a commit SHA" — a `ci_quality`/`repo_conventions` line. The dependency section had nothing usable at the rung it got. |
| egeria | What is the upgrade process? | Analysis/gap | 0 | 1 | D | nothing stored covers it; rag invented `pipx` upgrade instructions (2 unsupported claims) and scored higher. |
| egeria | Does it replace or extend something we have? | Discovery/direct | 0 | 1 | D | outside stored analyses; rag's 3-unsupported-claim answer scored 1. |
| egeria | Is there a Survey Definition for this tech type? | Discovery/direct | 1 | 2 | D | catalog-state question, no analysis covers it; rag asserted "There is no Survey Definition authored…". |
| kafka | Is there a Survey Definition for this tech type? | Discovery/direct | 1 | 2 | D | same; compiled even asked the follow-up the prompt tells it to ask and was marked down for it. |
| docling | Is there a Survey Definition for this tech type? | Discovery/direct | 1 | 2 | D | same; compiled named a needed analysis (`catalog_info`) and was penalised for the unsupported name. |
| docling | Any known feedback? | Discovery/direct | 0 | 1 | B | "65964 stars, 4745 forks, and 65964 watchers" — `chaoss_metrics` displaced a question about `resource_feedback`/curator notes, which no analysis covers. |

Cause totals: **E 5, D 5, B 4, C 1, F 1, A 0.**

Ten of sixteen (E+D) are the judge preferring a fluent unsupported assertion over an honest or
equally-correct one. Only five (B+C) are the compiler doing something wrong.

## Where compiled scored 0 (33 pairs)

RAG also scored 0 in 24 of those 33, so they are not losses — but they are where the compiler's own
failure modes are visible, including cause **A**, which does not appear in the loss table at all:

- **A — over-eager refusal with the relevant analysis packed.** "What are the public interfaces?"
  refused for egeria and docling while `interface_surface` *and* `api_structure` were both packed;
  "What components exist, and what kind is each?" refused for egeria with `architecture_recovery`,
  `architecture_summary` and `architecture_diagram` packed; "What kinds of integrations does it
  support?" refused on all three repos.
- **B/C — a count narrated as an answer.** kafka "What APIs and code symbols does it expose?" →
  "Java: 8005 classes, 299 enums, 709 interfaces, 72186 methods"; kafka components → "649
  component(s) exist… The types are documented in the architecture summary"; kafka dependencies →
  "36 dependencies, with 2 key dependencies". The stored analyses hold aggregates and the questions
  want enumerations — for `api_structure` no rung fixes this, the data itself is counts.
- The stock refusal string **"The evidence does not cover what was asked."** appears verbatim in 16
  compiled answers and scored 1 nine times and 0 seven times — **never 2**.

## Patterns

- **By repo:** egeria_python_git 10/52 losses, kafka 3/52, docling 3/52. egeria is also the only
  repo with gaps (`sla_content`, `contribution_provenance`, `telemetry_scan`, all `not_established`;
  kafka and docling have zero gaps in every row). Gaps correlate with losses because a correct
  refusal loses to a confident RAG guess.
- **By stage:** Discovery 7/36, Analysis 4/66, Scouting 3/15, Assessment 2/21, Enrichment 0/15,
  Automate 0/3. Discovery's `direct` questions are catalog-state questions ("has it been catalogued",
  "is there a Survey Definition") that no repo analysis can answer.
- **By kind:** `analysis` 8/69 and `direct` 7/33 carry everything; `human` 0/21, `mixed` 0/18,
  `partial` 0/3, `chart` 0/3 have no losses. The headline claim that compiled wins on `human`
  questions survives this audit intact.
- **By packed set:** the packed list is *ranked* and ranking works — `dependency_analysis` is first
  for the dependency question, `repo_conventions` first for catalog-info, `telemetry_scan` first for
  telemetry. The ranking is not the problem. What every row shares is **breadth**: 24 sections for
  egeria, 27 for kafka/docling, into a 6000-char budget, with `used` at 5974–6000 in every single
  row. `pack()` gives every section its *cheapest* rung first and then upgrades one rung per round
  (`packer.py`), so with ~25 sections most stay at SUMMARY/IDENTIFIERS. Every cause-B answer reads
  like SUMMARY-rung text from a *neighbouring* section.
  **Caveat: this is inference, not measurement.** `reference_compile()` records only `p["key"]` and
  discards `p["rung"]`, so the rung actually chosen is not in the data. See recommendation 2.

## Sanity pass — 5 of the 8 compiled-won-by-2 pairs (`random.seed(7)`)

| pair | verdict |
|---|---|
| docling · AI/ML licensing constraints | **hollow.** compiled "The evidence does not cover the question…" (2) vs rag "Unfortunately, I was unable to find any information…" (0). Both refuse. |
| kafka · What is the upgrade process? | **hollow.** compiled "there is no information in the provided evidence about the upgrade process. The analysis results cover various aspects such as repository health, security scans…" (2, `cites_evidence=true`) vs rag "unable to find any information…" (0). Naming the corpus it *didn't* use scored as citing evidence. |
| kafka · Any existing use in our organization? | **hollow.** "No evidence of existing use within the organization is found in the provided analysis results." (2) vs rag "No information about kafka use within our organization was found." (0). |
| kafka · What languages and file types? | **partly hollow.** "The language_file_classification analysis shows that there are 5 lines of code by language, with the top two being Java and Python." — the `5` is `- lines_of_code_by_language: 5 key(s)` from the structural SUMMARY rung read as a value. Judged 2, `cites_evidence=true`. |
| docling · How adopted/active is the community? | **genuine.** Real numbers from `chaoss_metrics`, and it names the one metric that could not be computed. |

So: 3 of 5 are refusal-vs-refusal where the only difference is that the compiled one says the word
"evidence", 1 cites a section header while misreading a key count as a value, 1 is a real win.
The same construction that scores 2 here scores 0 or 1 in the loss table. **The judge's treatment of
refusals is unstable, and the +0.46 headline is inflated by an unknown amount.**

Countervailing evidence, in the compiler's favour: `claims_missing_result` fired **0 times in 312
rows**, yet RAG asserted "There is no evidence of telemetry" for a repo whose `telemetry_scan` is
`not_established` and the judge scored it 2/`claims_missing_result=false`. The compiler's main job
is real and the rubric cannot see it — the doc's own caveat (1) is confirmed, not refuted.

## Recommendations, ranked

**1. Fix the judge before changing the compiler.** `scripts/experiment_compiled_vs_rag.py`,
`JUDGE_PROMPT`. Three defects, all demonstrated above: (a) `answers_question` has no rule for a
refusal, so identical refusals score 0, 1 and 2 across rows; (b) `claims_missing_result` is defined
as "a number, a finding, a list" and therefore **excludes asserting absence**, which is exactly the
failure — reword to "states any concrete result *or asserts a zero/absence* for an analysis listed
under NO usable result"; (c) pairs with identical content score differently on phrasing. Concretely:
add "if the answer declines to answer, score `answers_question` 2 only when it names which analysis
would answer it, 1 when it declines and grounds the refusal, 0 when it declines with no grounding —
do not reward fluency" and re-judge the existing 312 answers (no re-answering needed, it is cheap).
Expected impact: highest — 10 of the 16 losses and 3 of the 5 sanity-pass wins are judge behaviour,
so the loss list cannot be acted on with confidence until this is done.

**2. Record the chosen rung per section.** `scripts/experiment_compiled_vs_rag.py`,
`reference_compile()` — it already has `c.manifest["packed"]` and throws away `p["rung"]`. One line:
`packed = [{"key": p["key"], "rung": p["rung"]} for p in ... ]`. Without it, cause C is unfalsifiable
and recommendation 3 is a guess. Cheap, and it is the prerequisite for every rung-related change.

**3. Stop packing every analysis in the catalog.** `resource_explorer/context_compile.py`,
`compile_context()` — the loop over `sorted(weights.items())` creates a `Section` for every analysis
reachable from any of the ~50 catalog questions, so 24–27 sections compete for 6000 chars and `used`
pins at the budget in all 156 rows. Two options, in order of preference: (a) drop sections whose
`_question_relevance`-derived weight is below a threshold (they contribute an IDENTIFIERS line —
`checks: a, b, c` — that is noise the model then narrates, per every cause-B row); (b) raise
`Section(..., floor=Rung.SUMMARY)` for evidence sections so a section that cannot afford SUMMARY is
dropped rather than reduced to a check-name list. Do this *after* 2, so the effect on rungs is
measurable rather than asserted.

**4. Do not let the structural SUMMARY rung reach the model.**
`context_compile.py`, `_results_to_rungs()`. Its docstring records this exact bug being fixed for the
`{"findings": [...]}` shape ("5 key(s) with 4 item(s) found… narrated verbatim") — it is still live
for the structural shape: "5 lines of code by language" (kafka, scored 2) and "649 component(s)…
types are documented in the architecture summary" (kafka, scored 0) are both `N key(s)`/`N item(s)`
read as values. Either omit `Rung.SUMMARY` for this shape (letting the packer choose FULL or fall to
IDENTIFIERS) or prefix it "structure only, no values:". Small, local, and it removes a class of
confident wrong numbers.

**5. Make the refusal wording a template, and de-duplicate it.** `context_compile.py`
`_INSTRUCTIONS` says "say so and name what is missing"; `agents/conversation_agent.py`
`system_prompt()` says the weaker "say so plainly and either ask a clarifying question or name what
analysis would need to run". The bare form wins 16 times, and one docling answer echoed the system
prompt's own clause ("do not fall back to a broader search and present its results as though they
answered the question") back to the user as its answer. Give one required shape — "The stored
analyses do not cover X. <analysis> would answer it; it <gap state>." — in `_INSTRUCTIONS` only, and
delete the overlapping sentences from `system_prompt()`. Expected impact is real but modest and
partly cosmetic: it converts cause-D and cause-E refusals into ones a fixed rubric would score 2.

**Not recommended on this data: changing `THIN_FINDINGS_CHARS`.** Nothing in the 16 losses or the 33
zeros shows a thin findings section suppressing a richer reader, or a reader displacing better
findings — the fallback visibly fired (the answers carry reader-shaped content). Leave it at 200
until something measures it.

**Also not supported: cause A as a compiler-instruction problem.** The refusals on "public
interfaces" / "components" happened with the relevant analyses packed, which looks like over-eager
refusal — but every one of those rows is a 0–0 tie, so it may equally be an 8B answering model
failing on a long context. Recommendation 3, measured with 2, will separate the two.
