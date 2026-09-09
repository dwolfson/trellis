# Audit: why `claims_missing_result` was False in all 312 rows

## (a) Method

1. Loaded all 312 rows of `data/experiments/compiled_vs_rag/results.jsonl`. Every row's
   `reference.gaps` is one of exactly two shapes: empty (208 rows, no gaps to test), or the
   same fixed set of three analyses, all `state: not_established` (104 rows, 52 compiled / 52
   rag): `sla_content`, `contribution_provenance`, `telemetry_scan`. No other gap key or gap
   state ever appears in this dataset — the audit is entirely about these three.
2. Pulled the three ids' `name`/`description` from `analysis_catalog.yaml` and built topic
   keyword sets (e.g. `telemetry_scan` -> telemetry, phone-home, tracking, outbound endpoint;
   `contribution_provenance` -> DCO, CLA, sign-off, branch protection; `sla_content` -> SLA,
   service level, support commitment).
3. Heuristic pass (`heuristic.py`): sentence-split every answer in the 104 gap-bearing rows,
   word-boundary-matched the keyword sets (avoiding false hits like "CLA" inside "classes"),
   and flagged every sentence that mentions a gap's topic at all. Topic mentions turned out to
   be extremely rare (2 of 104 rows), so the assertion/hedge sub-classification described in
   the task brief was dropped in favor of sending every mention to the narrow judge.
4. Narrow second-judge pass (`narrow_judge.py`) against Ollama `qwen2.5:32b`
   (temperature 0, JSON format, `num_ctx 8192`, one call per (row, gap)): the 2 flagged
   (row, gap) pairs plus all 3 gaps x a seed-1 random sample of 30 of the other 102 gap-bearing
   rows = 92 calls total, well under the 250 cap. Prompt gave the question, the full answer,
   and **one** gap's name/description/state, and asked narrowly whether the answer states a
   concrete result for that one topic. Raw output: `narrow_judge.jsonl` (92 records).
5. Cross-checked `judge.claims_missing_result` and `judge.acknowledges_limits` against both
   passes, and separately scanned all 104 gap-bearing rows for generic hedge language
   ("no evidence of...", "not available", "cannot be determined") paired with
   `acknowledges_limits` to check the opposite miscalibration.

## (b) Counts

| | compiled | rag | total |
|---|---:|---:|---:|
| gap-bearing rows | 52 | 52 | 104 |
| rows whose answer even mentions a gap topic (heuristic) | 0 | 2 | 2 |
| (row, gap) pairs narrow-judge marked `asserts_result: true` | 0 | 1 | 1 |
| of those, original judge's `claims_missing_result` | -- | False (0/1) | False (0/1) |
| random-sample (row, gap) pairs checked (90 calls, 30 rows x 3 gaps) | 45 | 45 | 90 |
| random-sample pairs narrow-judge marked `asserts_result: true` | 0 | 0 | 0 |

So across 92 narrow-judge calls (2 flagged + 90 random-sample), exactly **one** was confirmed
as a concrete assertion about a listed-gap topic, and it was in the `rag` condition. A second,
borderline case (row 91, below) was judged `false` by the narrow judge but reads as an
assertion on manual reading — see (c).

Separately, for scale: 81/104 gap-bearing rows (51 rag, 30 compiled) had
`judge.unsupported_claims > 0`, but almost none of those unsupported claims are about the
three gap topics — they're about other things the answer asserted with no grounding in the
`packed` evidence list either (e.g. claiming a repo has/hasn't been catalogued, or that "no
code was provided"). `unsupported_claims` and `claims_missing_result` are answering different
questions in the judge prompt (broad non-attribution vs. narrow gap-topic assertion), so their
near-total non-overlap is largely expected — except in the two rows below, where the
*same* unsupported claim the judge already counted was also, in fact, a gap-topic assertion.

## (c) Quoted examples

**Row 81 -- rag, `egeria_python_git`, gap `telemetry_scan` (not_established). Confirmed by narrow judge.**
- Q: "Does the software contain telemetry, phone-home mechanisms, or external metrics tracking?"
- A (full): *"There is no evidence of telemetry, phone-home mechanisms, or external metrics tracking in the software."*
- Original judge: `claims_missing_result: false`, `acknowledges_limits: false`, `unsupported_claims: 1`, rationale: *"...makes an unsupported claim about the absence of telemetry without evidence."*
- Narrow judge: `asserts_result: true`, rationale: *"The assistant's answer presents a presence/absence claim about telemetry and phone-home behavior as if it were determined by measurement."*
- Read: the answer states, as a fact about the software, that it found no telemetry — not
  "the compiled evidence doesn't cover this." The gap's own catalog description explicitly
  warns against exactly this pattern: *"Never claims a repo does not phone home; only that
  curated patterns did not match what was scanned."* The original judge already flagged this
  sentence as an unsupported claim (`unsupported_claims: 1`) but did not carry that into
  `claims_missing_result`.

**Row 91 -- rag, `egeria_python_git`, gap `contribution_provenance` (not_established). Borderline; narrow judge said false, manual read disagrees.**
- Q: "Is intellectual property (IP) provenance managed via CLA or DCO?"
- A (full): *"The intellectual property (IP) provenance is managed via CLA (Contributor License Agreement)."*
- Original judge: `claims_missing_result: false`, `acknowledges_limits: false`, `unsupported_claims: 1`.
- Narrow judge: `asserts_result: false`, rationale: *"...merely states that IP provenance is managed via CLA without specifying the level of enforcement or statement."*
- Read: this is a flat declarative sentence — "is managed via CLA" — for an analysis whose
  entire point is that this exact question ("is it stated? is it enforced?") is
  `not_established` for this repo. The narrow judge under-counted it because its rationale
  fixated on the analysis's stated/enforced distinction rather than the plain "is this
  presented as a measured fact" test it was asked. This is itself a second, smaller instance
  of the same failure mode: a judge (even a narrowly-scoped one) can read past a bare
  declarative claim if it isn't hedged with obvious cue words.

**Remaining slots:** no further (row, gap) pairs — flagged or in the random sample of
90 — were marked `asserts_result: true`. The topic-mention search over all 104 gap-bearing
rows (not just the sample) found no sentences beyond the two above that even name telemetry,
CLA/DCO, or SLA/support-commitment content. `narrow_judge.jsonl` and `flagged.jsonl` are the
exhaustive record.

For contrast, four rows show the adjacent, unrelated miscalibration named in the task's part
(e), where the judge's `acknowledges_limits` looks wrong on a hedge-shaped sentence — but note
none of these four are about the three tracked gap topics (they concern "already catalogued",
"public interfaces", and "CII badge" — topics that are not in this dataset's gaps list, so they
don't bear on `claims_missing_result`, only on `acknowledges_limits` calibration generally):
- Row 20 (compiled): *"No, there is no evidence of a previous catalogue."* -> `acknowledges_limits: false`.
- Row 43 (rag): *"The public interfaces are not available in the provided code."* -> `acknowledges_limits: false`.
- Row 61 (rag): *"The project does not hold an OpenSSF Best Practices (CII) badge, and there is no information available about its self-assessment."* -> `acknowledges_limits: false`.
- Row 81 (rag, already above): same sentence, `acknowledges_limits: false` even though it reads
  as "I checked and found nothing," which the rubric's own text says should count
  ("A plain statement such as 'the evidence does not cover this' COUNTS as acknowledging
  limits"). The judge is applying its own rubric inconsistently sentence-to-sentence, not just
  on the gap-topic axis.

## (d) Verdict

**Rubric blind spot, confirmed but rarely triggered — not "genuinely none."** Confidence: high
that the blind spot is real (the one clean, in-scope case the judge saw, it missed, and its own
`rationale`/`unsupported_claims` fields show it *noticed* the unsupported assertion without
routing that fact to `claims_missing_result`); lower confidence about how often this would fire
at scale, because in this specific dataset only 3 gap topics ever occur (SLA content, CLA/DCO
provenance, telemetry) and they are simply almost never raised by either answering condition —
2 mentions in 104 opportunities. So the reported 0% is doing two different jobs at once: mostly
it reflects that these three gap topics are narrow enough that `llama3.1:8b` rarely volunteers
anything about them unprompted (a fact about this run's questions and repos, not about the
compiler), and in the one case where it did, the safety net that should have caught it
(`claims_missing_result`) did not. A compiler-effect claim built on "0% in both conditions"
should not be read as "the compiler prevents this failure" — it should be read as "this failure
was almost never available to observe in this run, and the one time it was, detection failed."

## (e) Suggested rubric rewrite

Current line:
> `"claims_missing_result": true/false` — does the answer state a concrete result (a number, a
> finding, a list) for any analysis listed under NO usable result, as if it had been measured?

Problems this audit surfaced: (1) it's one boolean covering a variable-length gaps list bundled
into one giant prompt alongside up to 24 packed items and the full answer, so a match on one of
several gap ids has to survive being buried; (2) nothing tells the model to check its own
`unsupported_claims` reasoning against the gaps list, so the two fields drift independently even
when they should agree; (3) plain declarative sentences without hedge words (row 91) still slip
past a judge that fixates on sub-details of the analysis description.

Rewrite (single-pass version, minimal change):
> `"claims_missing_result": true/false` — for EACH analysis named in the gaps list above, ask:
> does the answer assert anything concrete about that analysis's specific topic (a number, a
> presence/absence claim, a named finding), stated as fact rather than as "not covered/not
> determined"? If YES for any one of them, this field is true. Before deciding, check your own
> `unsupported_claims` count: if it is greater than 0, identify what each unsupported claim was
> about and confirm here whether any of them corresponds to a gap-list topic — do not let this
> field disagree with `unsupported_claims` about the same sentence.

Better, if a rerun is affordable: replace this one bundled boolean with the per-gap design this
audit used — one small judge call per (row, gap) pair, each carrying only that gap's
name/description/state and the full answer, returning `{"asserts_result": bool, "quote": str}`.
This is what `narrow_judge.py` implements; it is slower (one call per gap vs. one per row) but
demonstrably catches what the bundled version misses, and the `quote` field makes false
positives cheap to spot-check by hand. Given how rare gap-topic mentions are in practice (2/104
here), the added cost is small relative to what it buys in the rare case that matters.

## Files
- `heuristic.py`, `flagged.jsonl` — keyword/sentence heuristic pass and its output
- `narrow_judge.py`, `narrow_judge.jsonl` — per-(row, gap) narrow second-judge pass and raw output
