# Run 4 audit — are "unsupported_claims" really unsupported?

Data: `data/experiments/compiled_vs_rag_run4/results.jsonl` (312 rows).
Selection: `condition == "compiled"`, `judge.unsupported_claims >= 2`, `judge.declines` falsy → **36 rows**
(15×2, 12×3, 6×4, 1×6, 1×7, 1×16; docling 15, egeria_python_git 14, kafka 7).
Sample: sorted by (repo, question), `random.seed(4)`, `random.sample(..., 20)`.

**Compile verification: all 20 recompiled compile_ids matched `reference.compile_id` exactly.**
The evidence text audited below is byte-identical to what the answering model saw.
(All 36 candidates also carry `compile_id_matches_reference: true` from the run itself.)

Classification per specific claim (numbers, names, files, statuses, counts):
- SUPPORTED — stated in the packed text
- DERIVED — reasonable restatement/aggregation of packed text
- INVENTED — not in the text, not labelled general knowledge
- MISREAD — in the text but with a wrong value or attributed to the wrong thing

## Per-row table

| # | repo | question (short) | judge unsup | SUP | DER | INV | MISREAD | worst invented/misread claim |
|---|------|------------------|------------:|----:|----:|----:|--------:|---|
| 00 | egeria_python_git | Any known feedback? | 3 | 3 | 0 | 0 | 0 | — (8 stars / 4 forks / 8 watchers, "open via issues, wiki" all verbatim in `community_support`) |
| 01 | egeria_python_git | OpenSSF Scorecard-style score? | 3 | 6 | 3 | 0 | 0 | — (every status verbatim; "CI/CD / Security / Dependencies" are rollup labels the model coined) |
| 02 | docling | How much has changed since last survey? | 3 | 3 | 0 | 2 | 0 | "The number of commits in the last 30 days (107) and 90 days (314) **has increased**" — no baseline in evidence; 107/30d vs 314/90d is flat, not rising. Also "significant changes since the last survey" — no delta is measured anywhere. |
| 03 | egeria_python_git | What data files does it ship? | 6 | 12 | 0 | 0 | 0 | — all six CSVs, row/col counts and every column name match `data_file_profiling` exactly |
| 04 | kafka | How do components relate? | 4 | 4 | 0 | 0 | 0 | — 649/6/3/31 are the literal `architecture_summary.summary` string |
| 05 | docling | How is it supported? | 4 | 5 | 0 | 0 | 0 | — 65964/4745/65964 verbatim (the stars==watchers oddity is in the evidence itself) |
| 06 | docling | How do components relate? | 3 | 3 | 0 | 0 | 2 | "components are organized into **blueprints, interfaces, and documentation** … some components being **partial or unverified**" — those are field *names* in the structure-only `architecture_recovery` block, and `partial` is literally `False` |
| 07 | kafka | Worth investigating further? | 3 | 5 | 0 | 0 | 1 | "a good level of maturity and **documentation coverage**" — `documentation_coverage` says Partial, 17.4% (12,205/69,991). The three items the judge flagged (no tests in CI, no releases, no SBOM) are verbatim `foss_scorecard`. |
| 08 | docling | Any known feedback? | 2 | 3 | 0 | 0 | 1 | "**The CVE scan found no vulnerabilities**" — `cve_scan` shows `checked: 0, unqueryable: 61`, and `foss_scorecard.vulnerabilities: unknown — No vulnerability scan has run`. Not-measured rendered as a zero. |
| 09 | docling | What does this repository do? | 2 | 2 | 0 | 1 | 0 | "the Docling project, **which is a documentation platform**" — nothing in the pack says what it does; guessed from the name (and wrong: docling is document conversion). |
| 10 | egeria_python_git | Surveyed at any tier? | 2 | 1 | 0 | 1 | 0 | "Yes, the resource has been **surveyed at Tier 1**" — no tier/provenance information appears anywhere in the packed text. |
| 11 | docling | What APIs/symbols does it expose? | 3 | 4 | 0 | 0 | 0 | — 699/2189/2109 verbatim `api_structure`; "not explicitly documented or published" = `published_spec: no` |
| 12 | docling | CII badge? how current? | 2 | 2 | 0 | 0 | 0 | — 'gold', "updated 10 day(s) ago" verbatim `cii_badge` |
| 13 | docling | How widely adopted/active? | 4 | 4 | 0 | 0 | 1 | "high attention (**65964 stars, forks, watchers**)" — forks are 4,745; one number smeared across three fields |
| 14 | egeria_python_git | Worth investigating further? | 3 | 4 | 1 | 0 | 0 | — sast/sbom/vulnerabilities wording is near-verbatim `foss_scorecard` |
| 15 | kafka | How is it supported? | 3 | 4 | 1 | 0 | 0 | — 33665/15474/349 verbatim; "no discussions, issues or wiki" is the literal `community_support.channels: none` gloss the judge called unsupported |
| 16 | docling | What dependencies does it require? | 2 | 1 | 0 | 0 | 1 | "**6 third-party dependencies** are still on a mutable ref" — the evidence says 6 third-party *GitHub Action references*. `dependency_analysis` was structure-only (`total: 62`, unused), so the model answered from the neighbouring section. |
| 17 | docling | Existing use within our organization? | 2 | 2 | 0 | 1 | 0 | "**Yes**, the project has 65964 watchers and 4745 forks" — internal/organizational use is not measured by any packed analysis; global GitHub counts offered as organizational adoption |
| 18 | docling | How much code? how complex? | 2 | 2 | 0 | 0 | 0 | — 107,747 code lines; avg 3.0 / max 93 over 4,298 verbatim |
| 19 | docling | OpenSSF Scorecard-style score? | 7 | 15 | 0 | 0 | 0 | — all 15 recited statuses match `foss_scorecard` exactly (only `branch_protection` omitted) |

**Totals:** judge flagged **63** unsupported claims across the 20 rows.
My audit of the same answers: **101** specific claims — **85 SUPPORTED, 5 DERIVED, 5 INVENTED, 6 MISREAD**.

## Summary

- 90/101 (89%) of the specific claims in these answers are supported by, or straightforwardly
  derived from, the packed evidence text. 11/101 (11%) are real defects.
- 11 of 20 rows contain **zero** real defects despite the judge flagging ≥2 unsupported claims each.
- Upper bound on the judge's precision: even assuming every one of my 11 real defects was among the
  judge's 63 flags, **≥82%** of the flagged count is judge blindness. Realistically higher: for rows
  07, 15, 16 and 19 the judge's own `rationale` names as "unsupported" items that appear verbatim in
  the packed text (e.g. row 19, 7 flags against 15 statuses copied exactly from `foss_scorecard`).
- The judge is not merely over-counting; it is **uncorrelated** with the real defects. It missed the
  Tier-1 invention (row 10), the "documentation platform" invention (row 09), the CVE-not-measured
  misread (row 08) and the org-use non-sequitur (row 17) — for row 17 it flagged the two numbers that
  *are* supported and let the unsupported "Yes" pass.
- Caveat against the blindness hypothesis: `unsupported_claims` correlates with *answer length*, and
  the longest, most number-dense answers (03, 19) are the ones that scored worst while being perfectly
  faithful. So the metric partly measures verbosity, not fidelity.

### Where the real defects cluster

**Pattern A — structure-only SUMMARY sections narrated as results (rows 06, 16).**
The compile header explicitly warns "A section marked 'structure only' … is not a result — do not
quote, count or summarise it as one", and the model does it anyway. Row 06 reads
`architecture_recovery`'s *field names* (`blueprints`, `interfaces`, `documentation`, `partial`,
`unverified`) as an architecture description and reports "some components partial or unverified"
when `partial: False`. Row 16 shows the mirror failure: the section that would answer the question
(`dependency_analysis`, SUMMARY, `total: 62`) is structure-only, so the model substitutes content
from a neighbouring FULL section (`foss_scorecard` action pinning) and relabels action refs as
dependencies. Both are SUMMARY-rung sections.

**Pattern B — FULL raw-JSON blocks narrated wrongly (rows 02, 08, 13).**
`repository_health` and `cve_scan` are packed as raw JSON with no prose gloss, and that is where
numbers get crossed and non-measurement gets read as a zero:
- row 13: `forks: 4745` overwritten by `stars: 65964` in "65964 stars, forks, watchers";
- row 02: a trend ("has increased") invented from two point-in-time counters;
- row 08: `cve_scan {checked: 0, unqueryable: 61}` → "found no vulnerabilities", contradicting
  `foss_scorecard.vulnerabilities: unknown — No vulnerability scan has run` in the same pack.
This is the *find-absence-as-answer* failure mode reaching the user through the narration layer,
even though the evidence layer labelled it correctly.

**Pattern C — no section covers the question, and the model fills the void (rows 09, 10, 17).**
`What does this repo do?`, `has it been surveyed at what tier?`, `any use inside our organization?`
have no corresponding analysis in the pack (and `gaps` is `[]` for all three — the compile reports
no gap because the question's need was never mapped to a missing analysis). The model answers from
the repo name, from an invented tier, or from global GitHub counts. This, not misquotation, is the
most consequential real defect class: 3 of 5 inventions.

**What does *not* fail:** bullet-with-explanation FULL sections. `foss_scorecard` (15 statuses,
row 19), `cii_badge`, `community_support`, `data_file_profiling` (6 files × rows × cols × column
names, row 03) are reproduced exactly, at scale, with zero errors. Contra the stated hypothesis,
there is no evidence of `foss_scorecard` statuses being mixed up anywhere in this sample.

### Rung breakdown of the 11 real defects

| rung of the implicated section | defects |
|---|---|
| SUMMARY (structure-only) | 3 (row 06 ×2, row 16 ×1) |
| FULL (raw JSON: repository_health, cve_scan) | 4 (rows 02 ×2, 08, 13) |
| FULL (bullet prose) | 1 (row 07, `documentation_coverage` characterised as "good") |
| no section at all | 3 (rows 09, 10, 17) |

## RAG contrast (8 rows, seed 4, unsupported ≥ 2)

All 8 sampled RAG rows happen to be `egeria_python_git`. Classified against plausibility in the
general corpus rather than a packed text.

| # | question | judge | verdict |
|---|----------|------:|---------|
| 0 | community adoption/activity | 2 | Vague, no specifics; nothing checkable either way |
| 1 | how components relate | 3 | "composition, actor roles, solution ports" — real Egeria vocabulary, corpus-plausible |
| 2 | restrictions for use | 3 | **INVENTED and wrong**: "resale and sublicensing are forbidden" — the repo is Apache-2.0, which forbids neither |
| 3 | similar projects | 2 | **Confused identity**: presents `egeria-python` as a *different* project from `egeria_python_git` — they are the same repo |
| 4 | how much code / complexity | 2 | **INVENTED, wildly wrong**: "123 lines of code, complexity score of 0.42" (compiled condition for the same question: 107,747 lines from `language_file_classification`) |
| 5 | integrations supported | 3 | Corpus-plausible pyegeria feature list |
| 6 | replaces/extends? | 3 | Corpus-plausible Dr.Egeria command list |
| 7 | what does the repo do | 4 | **Wrong repo**: describes Egeria Workspaces (Kafka, PostgreSQL, OpenLineage proxy) — a different repository in the same family; classic retrieval cross-contamination |

4 of 8 RAG rows carry genuinely fabricated or misattributed content, vs 9 of 20 compiled rows
carrying any defect at all — but the *kind* differs sharply. Compiled defects are small and adjacent
to correct evidence (a wrong field, an over-read gloss). RAG defects are whole invented facts:
a fabricated LOC count off by three orders of magnitude, licence terms that contradict the actual
licence, and an answer about the wrong repository. The judge's `unsupported_claims` scores the two
conditions in the same 2–4 band and cannot tell these apart.

## Recommendation

`unsupported_claims` at rubric v2 is not a fidelity metric for the compiled condition and should not
be reported as one. The judge needs `c.text` in its prompt (it is ≤6 KB and already reproducible from
`reference.compile_id`), otherwise the metric penalises exactly the behaviour the compiled condition
is meant to produce — dense, verbatim recitation of stored evidence.
