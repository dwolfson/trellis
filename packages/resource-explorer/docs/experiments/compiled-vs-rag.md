# Experiment: compiled evidence versus RAG-only answers

**Question** (context-compilation-design.md §9): do answers built on compiled evidence beat
answers the agent assembles for itself from retrieval? Everything about the compiler's effect on
answer quality is asserted until this runs.

**Status:** protocol and harness written 2026-09-08 (`scripts/experiment_compiled_vs_rag.py`).
Results are appended to this file's "Runs" section as they land; none yet.

## Design

| | |
|---|---|
| Unit | one (repository, catalog question, condition) |
| Questions | the full repo question catalog (52 entries on 2026-09-08), shuffled with a fixed seed so order does not follow catalog position; `--limit N` takes the first N of that order |
| Repositories | `egeria_python_git`, `kafka`, `docling` by default: the three with the deepest stored analysis results across different languages and communities |
| Conditions | `compiled`: `ConversationAgent(compiled_evidence=True)`, production behaviour. `rag`: the same agent with `compiled_evidence=False`, so it must search collections itself. **Nothing else differs**: same tools, prompt shape, model, tier, fallback |
| Answering model | whatever `LLM__OLLAMA__MODEL` and `EXPLORER_MODEL_TIER` resolve to; record them with each run (default `llama3.1:8b`, tier `dev`) |
| Perspectives | none set, the common case |
| Judge | `qwen2.5:32b` at temperature 0 with JSON output, a different and larger model than the answerer. Override with `EXPERIMENT_JUDGE_MODEL` |
| Ground truth for the judge | a **reference compile** for every row, in both conditions: which analyses had usable stored results and which are gaps, with their fact-layer states. The judge never sees the packed text, only the list |

## Rubric (per row, judged)

| Field | Meaning |
|---|---|
| `answers_question` | 0 not addressed, 1 partial, 2 direct and useful |
| `cites_evidence` | names a specific analysis, finding, file, metric or source |
| `claims_missing_result` | states a concrete result for an analysis the registry has no usable result for; the failure the compiler exists to prevent |
| `acknowledges_limits` | says what could not be determined, where that applies |
| `unsupported_claims` | count of specific claims not attributable to stored evidence or clearly labelled general knowledge |

Plus, unjudged: latency, the agent's `compile_id` (compiled condition) and whether it equals the
reference compile's id, which is the replayability check from §9 running for free.

## What would settle the question

- `claims_missing_result%` materially lower and `acknowledges_limits%` higher under `compiled`,
  across repos, is the compiler doing its main job.
- `answers_question` and `cites_evidence` not worse under `compiled` means the evidence is not
  crowding out the answer.
- If `rag` wins on `answers_question` for `human` or `direct` questions, that is expected and
  informative: those questions are not answered by stored analyses and the compiler should say so.
- Compile ids matching the reference in every compiled row is replayability holding over the run.

## Caveats stated up front

- One judge model, one answering model, one afternoon of state. Treat differences under about
  ten points as noise until a second run reproduces them; a human sample of disagreements is
  part of the protocol, not optional.
- The agent's fallback to plain retrieval on an exception is not distinguished from a normal
  answer in either condition.
- The reference compile persists like any compile (`context_compiles`, session
  `experiment:compiled_vs_rag`), so the run leaves rows behind by design.

## How to run

```bash
cd packages/resource-explorer
uv run python scripts/experiment_compiled_vs_rag.py --repos egeria_python_git --limit 3   # smoke
uv run python scripts/experiment_compiled_vs_rag.py                                      # full, resumable
uv run python scripts/experiment_compiled_vs_rag.py --summarise                          # tables only
```

Results: `data/experiments/compiled_vs_rag/results.jsonl` (one row per unit, resumable) and, when
MLflow is reachable, experiment `compiled_vs_rag` with one run per condition.

## Rubric history

| Version | What changed | Why |
|---|---|---|
| v1 (run full-20260908) | original five fields | — |
| v2-2026-09-08 | `declines` field with an explicit refusal-scoring rule; `missing_result_claims` as a per-gap list that includes asserted absences and zeros; hedge-shaped statements count as acknowledging limits; consistency between missing-result claims and unsupported claims; grade content not fluency | two audits of the first run (`audits/`): the judge preferred fluent guesses over honest refusals in 10 of the 16 losses and scored the same refusal 0, 1 and 2 across rows; it missed both answers that asserted a result for a missing analysis, having counted them as unsupported claims without routing them to `claims_missing_result` |

| v3-2026-09-09 | the judge receives the packed evidence text; `supported_claims` and `misread_claims` counted separately from `unsupported_claims`, which is now checked claim by claim against the text; a decline scores 0 when a packed section answers the question; `evidence_text_exact` records whether a re-judged row's text was reconstructed with a matching compile id | run-4 audit: 89% of the claims v2 counted as unsupported were in the packed text; v2's flags were uncorrelated with the eleven real defects; run 3 showed a decline that names an analysis scoring 2 even when that analysis was packed |

Rows carry `judge.rubric_version`; a re-judge (`--rejudge`) rescores existing answers under the
current rubric into `results.<version>.jsonl`, keeping the previous verdict as `judge_previous`.
Runs judged under different rubrics are never averaged together.

## Runs

### Runs 2 and 4 re-judged under rubric v3 (judge sees the packed text) — the compiler change is neutral; compiled-versus-RAG is not

`results.v3-2026-09-09.jsonl` in both run directories; run 2 also keeps `results.v3-2026-09-09.blind.jsonl`,
the first v3 pass in which no row had text (see the caveat). Every v3 row carries
`judge.evidence_text_exact`: whether the judge saw the exact text the model saw.

**Caveat first — shared state drifted under the re-judge, twice.** Rows written before v3 carry no
text, so it was reconstructed by recompiling and checking the compile id. Run 4: docling's stored
state had changed since the run, so all 104 docling rows were graded blind. Run 2: the current
compiler cannot reproduce run-2 ids by construction (different section set), so a scratch worktree
at b407dae ran the pre-change compiler — it matched all 104 egeria and kafka questions at the start,
but egeria's state changed after the 7th question while the judge was running (another session's
analysis run on the shared registry), leaving 45 of 52 egeria questions blind. **The comparable set
is the 59 questions (52 kafka, 7 egeria) with exact text in both runs.** From now on the reference
compile keeps its text on the row, so this cannot recur; a re-judge never depends on shared state
again.

On those 59 questions, both conditions, both runs:

| metric (v3) | run 2 compiled | run 2 rag | run 4 compiled | run 4 rag |
|---|---:|---:|---:|---:|
| answers_question (0–2) | 1.10 | 0.32 | 0.88 | 0.25 |
| supported_claims (mean) | 1.54 | 0.20 | 1.61 | 0.36 |
| unsupported_claims (mean) | 0.29 | 0.69 | 0.46 | 0.59 |
| misread_claims (mean) | 0.02 | 0.00 | 0.02 | 0.00 |
| cites_evidence | 68% | 3% | 61% | 3% |
| claims_missing_result | 0% | 2% | 0% | 2% |
| declines | 27% | 69% | 24% | 71% |

**What holds in both runs, on a judge that can check the text:** compiled answers make four to
eight times the supported claims, about half the unsupported claims, answer three times as often,
and cite evidence in about two thirds of answers against 3%. The run-2 v2 finding that compiled
answers "invent more specifics" is reversed, not merely withdrawn: under v2 the judge was counting
density, and density is mostly supported. Misread claims are rare in both conditions (0.02).

**What the compiler change did, paired on the same 59 questions (run 4 minus run 2, compiled):**
answers_question −0.22 (9 up, 19 down, 31 tied); supported_claims +0.07 (14/14/31);
unsupported_claims +0.17 (16 up, 8 down, 35 tied); cites_evidence −7 points. **Neutral to slightly
negative**, on a set that is 88% kafka and small enough that the answers_question move sits at the
edge of the protocol's noise band. The cap, the count-free summary and the relevance fix did not
improve answer quality on a judge that can see; they improved what the manifest reports (86% of
sections at FULL, sane ranking on paraphrases) and nothing the judge measures. The hypothesis that
coarse SUMMARY rungs were breeding invented specifics is not supported: the specifics were real.

On the wider egeria+kafka set (run 4 fully exact, run 2 blind for most of egeria) the direction is
the same for compiled-versus-RAG and should not be read for run-4-versus-run-2.

**Rubric v3's own defect, noted for v4:** its rule "a decline scores 0 when a packed section
answers the question" fired on 9 compiled run-4 declines, of which only 2 are real (public
interfaces with `interface_surface` packed; APIs with `api_structure` packed). The other 7 are
catalog-state, cost and organisational-use questions no analysis covers, where declining is right.
The judge reads "a packed section" too loosely; the rule needs "a packed section whose analysis
the question catalog maps to this question".

**Follow-up, 2026-09-10 — the eleven defects fixed** (`context_compile.py`; acceptance script
`scripts/check_compiler_audit_rows.py` recompiles the audit's twenty rows and checks the text,
120 of 120 checks pass against the fixed code, 52 against the old): reader-derived sections lead
with the analysis's own headline (`cve_scan`: "none in 0 of 61 declared dependenc(ies) (warn)"),
FULL renders as flat bullets with dotted nested keys instead of fenced JSON, the middle rung is
abridged with real first entries and marked truncation instead of "structure only", and a
`Coverage:` line plus `manifest.coverage` says when the catalog itself answers a question by human
input, a direct field, a chart or nothing. Found on the way: a verbatim catalog question made only
of stopwords ("What does this repository do?") scored 0.0 against itself; an exact match is now
1.0 before stopwords apply. Unmeasured until the next run; the protocol from here is one variable
per run with text on the row.

**Conclusion for the compiler track.** The engineering target this track started from was an
artefact of a blind judge. The defensible statements are: (1) compiled evidence beats RAG-only on
every content metric once the judge can verify claims; (2) the three packing changes are
neutral on quality and stay because they are cheaper and the manifest is more honest, not because
they helped answers; (3) the real remaining defects are the eleven from the run-4 audit — raw JSON
misread (`cve_scan` zero-versus-unqueryable), structure-only sections narrated, and uncovered
questions arriving with an empty gap list — each small and specific. **Next experiment, if the cap
is to be judged on its own: a within-run A/B (`max_sections` 12 vs 0), same day, text on the row,
rubric v4 with the decline rule tightened.** One variable, no reconstruction.

### run4-20260909 — cap, count-free summary and relevance fix in isolation; the metric, not the compiler, is what moved

Same seed, repos and rubric (v2) as runs 2 and 3; commit d31379a (template reverted, the three
other changes kept). `data/experiments/compiled_vs_rag_run4/results.jsonl`; MLflow
`run4-20260909-{compiled,rag}`. Replayability 156 of 156; 11–12 sections per compile, 86% at FULL.

| metric | compiled | rag | (run 2) |
|---|---:|---:|---:|
| answers_question (0–2) | 1.03 | 0.94 | 1.01 / 0.91 |
| cites_evidence | 24% | 1% | 35% / 1% |
| claims_missing_result | 3% (5 rows) | 4% | 5% / 7% |
| acknowledges_limits | 32% | 59% | 38% / 59% |
| unsupported_claims (mean) | **1.09** | 0.59 | 0.81 / 0.58 |
| declines to answer | 33 | 81 | 46 / 83 |

Under rubric v2 the packing change did not reduce unsupported claims; it raised them. On the 101
questions answered (not declined) in both runs, the mean went 1.10 → 1.22, with 24 rows down, 32
up, 45 tied. Answers are longer and denser now that most sections are FULL, and the count rose
with them.

**But the judge never sees the packed text.** Rubric v2 gives it the list of analysis names, so
"specific claims not attributable to stored evidence" is judged blind. An audit
(`audits/2026-09-09-run4-unsupported-claims-vs-packed-text.md`) took the 36 compiled rows the
judge flagged at ≥2 unsupported claims, sampled 20, recompiled each (all 20 compile ids matched,
so the text audited is byte-identical to what the model saw) and checked every specific claim
against it:

| | claims |
|---|---:|
| judge's unsupported count over the 20 rows | 63 |
| specific claims found by the audit | 101 |
| supported (stated in the packed text) | 85 |
| derived (faithful restatement or aggregation) | 5 |
| invented | 5 |
| misread (in the text, wrong value or wrong analysis) | 6 |

89% of the flagged answers' specific claims are in the evidence. Eleven of the twenty rows have no
defect at all; the two highest-scoring rows (6 and 7 "unsupported") are the longest and are
perfectly faithful — fifteen Scorecard statuses recited exactly, six CSV files with every row and
column count right. The judge's flags are not merely inflated but uncorrelated: its rationales
name verbatim-supported text as unsupported and miss the real defects.

**So the v2 `unsupported_claims` metric penalises exactly what compiled evidence is for**, and
the run-2 baseline's 0.81-versus-0.58 finding — the reason this track started — measured answer
density, not invention. Withdrawn as a compiler defect; it stands as a rubric defect.

**The eleven real defects, which are the compiler's actual next targets:**

- *Structure-only sections narrated as results* (3). Field names of `architecture_recovery` read
  as an architecture; `dependency_analysis` at structure-only rung, so the model answered a
  dependency question from the neighbouring `foss_scorecard` and relabelled Action references as
  dependencies. The instruction forbidding this is in the pack and does not hold on an 8B model.
- *FULL raw-JSON blocks narrated wrongly* (4). `repository_health`'s forks overwritten by its
  stars; a trend invented from two counters; `cve_scan`'s `{checked: 0, unqueryable: 61}` rendered
  as "found no vulnerabilities" while `foss_scorecard` in the same pack says no scan has run. That
  last one is the absence-read-as-zero the compiler exists to prevent, and a raw JSON dump does
  not carry the distinction.
- *No section covers the question and `gaps` is empty* (3 of the 5 inventions). Every catalog
  question maps to some analysis, so "nothing stored addresses this" is invisible to both the
  model and the judge.

Not confirmed: the hypothesised `foss_scorecard` status mix-up occurs nowhere in the sample.
Bullet-with-explanation FULL sections are reproduced exactly, at scale.

**RAG contrast** (8 rows, same threshold): 4 of 8 carry fabricated content of a categorically worse
kind — "123 lines of code" where the stored figure is 107,747, "resale and sublicensing are
forbidden" for an Apache-2.0 repo, and one answer describing a different repository entirely. v2
scores both conditions in the same 2–4 band.

**Rubric v3** follows from this: the judge receives the packed text (kept on the row from now on,
recompiled with an id check for older rows), counts `supported_claims` and `misread_claims`
separately from `unsupported_claims`, and scores a decline as 0 when a packed section answers the
question (the run-3 note). Runs 2 and 4 are re-judged under it below; only v3 numbers are
comparable across them.

### run3-20260909 — four compiler changes at once; a negative result on one of them

Same seed, repos and rubric (v2) as run 2; the answering side changed. `data/experiments/
compiled_vs_rag_run3/results.jsonl`; MLflow runs `run3-20260909-{compiled,rag}`. Commit 30989c5
made four changes to `context_compile.py` (and one to the agent's system prompt): a section cap
of 12 applied after ranking; a count-free structural SUMMARY rung; an additive relevance weight;
and a **one-shape refusal template** ("reply in exactly this shape and add nothing else: 'The
stored analyses do not cover X. <analysis> would answer it; it <state>.'").

| metric | compiled | rag | (run 2) |
|---|---:|---:|---:|
| answers_question (0–2) | 1.38 | 0.90 | 1.01 / 0.91 |
| cites_evidence | 58% | 1% | 35% / 1% |
| claims_missing_result | 5% (8 rows) | 4% | 5% / 7% |
| acknowledges_limits | 74% | 62% | 38% / 59% |
| unsupported_claims (mean) | 0.31 | 0.54 | 0.81 / 0.58 |
| declines to answer | 99 | 86 | 46 / 83 |
| sections packed per compile | 11–12, 84% at FULL | | 24–27, 20% at FULL |

Replayability 156 of 156. The packing change did what the sweep predicted: 84% of packed
sections at FULL against 20%, with the budget still filling to a median 5,918.

**Do not quote the top three rows.** An audit of the compiled answers splits them by whether the
refusal template appears:

| subset | n | answers_question | unsupported | declines |
|---|---:|---:|---:|---:|
| pure template refusal (the template is the whole answer) | 107 | 1.43 | 0.05 | 93 |
| template plus content | 7 | 1.57 | 0.29 | 6 |
| no template | 42 | 1.21 | 0.98 | 0 |

- **The template over-triggered.** 107 of 156 compiled answers are refusals, up from 46, and
  they include questions whose answering analysis was packed at FULL with no gap at all: "How does
  the repository handle secrets?" with `secret_scan` packed, "What languages and file types?" with
  `language_file_classification` packed, "Is IP provenance managed via CLA?" with
  `contribution_provenance` packed. Twelve of the pure refusals are questions run 2's compiled
  answer had scored 2 on.
- **The refusals score well because rubric v2 says a decline that names the analysis scores 2.**
  That rule was written for honest refusals of unanswerable questions; the template satisfies its
  letter on answerable ones. The `answers_question` gain is the template meeting the rubric, not
  better answers.
- **The template invented gap states.** Seven of the eight compiled `claims_missing_result` rows
  are the template's `<state>` slot filled with "ran and found nothing" for an analysis that was
  packed (`documentation_coverage`, `repository_health`, `architecture_recovery`,
  `data_file_profiling`) — every one of those compiles had an empty gap list. A template with a
  slot for a state the model does not have is an invitation to invent one.
- **The unsupported-claims drop is mostly refusals making no claims.** Among the 42 answers with
  no template, unsupported claims sit at 0.98 — no better than run 2's 0.81. Whether the cap and
  the count-free summary reduce invented specifics on answers that *answer* is therefore not
  shown by this run; the population that answered shrank to a quarter.

**What was done about it.** The refusal wording went back to the original loose form in the
instructions and the system prompt (commit after this one), keeping the cap, the count-free
summary and the relevance fix. Run 4 isolates those three. Two rubric notes for a future v3, not
applied now so runs 2–4 stay comparable: a decline whose named analysis is in the *packed* list
should score 0, not 2 (the judge already sees both lists); and a state asserted for a packed
analysis should count as a missing-result claim explicitly, which v2 caught only because the
answers used the literal phrase "found nothing".

**Method note, recorded so it is not repeated:** four changes went into one run. The one that
dominated behaviour was the cheapest-looking of the four. One variable per run, or a run per
variable, from here on.

### run2-20260908 — reproducibility on the redeployed platform, rubric v2 from the start

Same seed, same three repos, 312 rows, 0 errors, answered fresh after the 2026-09-08 Egeria
redeploy and judged under v2. `data/experiments/compiled_vs_rag_run2/results.jsonl`.

| metric | compiled | rag | (re-judged run 1) |
|---|---:|---:|---:|
| answers_question (0–2) | 1.01 | 0.91 | 1.02 / 0.90 |
| cites_evidence | 35% | 1% | 36% / 1% |
| claims_missing_result | 5% | 7% | 3% / 7% |
| acknowledges_limits | 38% | 59% | 40% / 60% |
| unsupported_claims (mean) | 0.81 | 0.58 | 0.82 / 0.58 |
| latency, median | 9.4 s | 7.4 s | 11.6 / 10.2 |

Every metric reproduces within two points of the re-judged first run; replayability 156 of 156
again. The protocol's "treat differences under about ten points as noise until a second run
reproduces them" is satisfied for: cites_evidence (+34), declines (compiled declines about half as
often), and unsupported_claims (compiled worse by about 0.23). The answers_question gap (+0.10 to
+0.12) is inside the noise band and should be reported as "no material difference on this
judge". The missing-result claim rate is low and noisy in both conditions (4 to 11 rows); the
direction favours compiled in both runs but the sample is too small to quote as a percentage.


### full-20260908, re-judged under rubric v2-2026-09-08 — the numbers to quote

Same 312 answers as the first run; only the judge changed. `results.v2-2026-09-08.jsonl`; MLflow runs
`full-20260908-rejudge-{compiled,rag}`.

| metric | compiled | rag |
|---|---:|---:|
| answers_question (0–2) | 1.02 | 0.90 |
| cites_evidence | 36% | 1% |
| claims_missing_result | 3% (4 rows) | 7% (11 rows) |
| acknowledges_limits | 40% | 60% |
| unsupported_claims (mean) | 0.82 | 0.58 |
| declines to answer | 46 rows | 84 rows |

Paired per (repo, question): compiled higher in 38, lower in 20, tied in 98; mean difference
**+0.12**, down from +0.46 under v1. Almost all of the v1 gap was the judge scoring RAG's honest
refusals as 0; under v2 every decline that grounds itself scores 1, and RAG declines far more often
(84 to 46). Replayability unchanged: 156 of 156.

**What the corrected numbers say.**

- The compiler's main job is visible now that the rubric can see it: RAG asserted a result for an
  analysis with no usable result in 11 rows, compiled in 4, and of those 4 at least one is a real
  compiled failure ("No, there are no outstanding CVEs" for a repository whose `cve_scan` is a gap)
  while two look like judge over-reach on a general question. The per-kind split is sharper:
  on `analysis` questions RAG claims missing results 16% of the time, compiled 4%.
- Compiled answers cite evidence (36% vs 1%) and answer rather than decline; RAG's higher
  `acknowledges_limits` is mostly that it declines twice as often.
- **Compiled makes MORE unsupported claims** (0.82 vs 0.58; on `analysis` questions 1.12 vs 0.52).
  This is the loss audit's cause B/C measured: summary-rung text from neighbouring sections
  narrated as specifics ("5 lines of code by language"). It is the clearest engineering signal in
  the run and it points at packing 24–27 sections into 6,000 characters, not at the judge.
- The v1 conclusion "compiled roughly doubles answers_question" is withdrawn. The defensible
  claim is: compiled answers are cited, decline less, and assert results for missing analyses less
  often; they also invent more specifics from coarse evidence, which is a compiler defect with a
  known location (`context_compile.py`: section breadth and `_results_to_rungs`' structural SUMMARY).


### full-20260908 — 3 repos × 52 questions × 2 conditions = 312 rows, 0 errors

Answerer `llama3.1:8b`, tier `dev`, no perspectives; judge `qwen2.5:32b`. Results in
`data/experiments/compiled_vs_rag/results.jsonl`; MLflow experiment `compiled_vs_rag`, runs
`full-20260908-compiled` / `full-20260908-rag`.

| metric | compiled | rag |
|---|---:|---:|
| answers_question (0–2) | 1.03 | 0.56 |
| cites_evidence | 26% | 0% |
| claims_missing_result | 0% | 0% |
| acknowledges_limits | 39% | 19% |
| unsupported_claims (mean) | 1.13 | 1.17 |
| latency, median | 11.6 s | 10.2 s |

Paired per (repo, question): compiled scored higher on `answers_question` in 80 pairs, lower in 16,
tied in 60; mean difference +0.46 on a 0–2 scale. The direction held on every repo
(egeria_python_git 0.98 vs 0.81, kafka 1.00 vs 0.40, docling 1.10 vs 0.48) and on every
answering kind, including `human` (1.10 vs 0.48) and `gap` (1.00 vs 0.22), where the compiled
condition's advantage is that it says what is missing. Replayability: the agent's compile id equalled
the reference compile's id in 156 of 156 compiled rows.

**Superseded by the v2 re-judge below once it lands; the audits in `audits/` explain why these v1 numbers overstate the compiled advantage.** Original caveats: **Read with the caveats above.** One answering model, one judge, one afternoon. Two things to
check by hand before believing the numbers: (1) `claims_missing_result` never fired in either
condition, which is either good news or a rubric that cannot detect it — sample the RAG rows for
analyses listed as gaps and see whether the judge missed any; (2) the 16 pairs where RAG scored
higher, to learn what the packed evidence displaced. Unsupported claims did not improve, so the
compiler changes what the model can say, not how disciplined it is about saying more.
