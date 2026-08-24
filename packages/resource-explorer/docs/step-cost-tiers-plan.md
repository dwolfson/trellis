# Step cost tiers — composing surveys by budget instead of enumeration

**Status: implemented 2026-08-20.**

## Why

There are now 21 repo survey steps and the cost spread across them is extreme.
`repo_license_classification` reads a table already in the registry.
`repo_rag_ingestion` embeds an entire repository. `repo_git_statistics` at full
fidelity made hundreds of sequential GitHub calls and took **430 seconds**
against `odpi/egeria` — and still logged a read timeout. "Full Survey (all
steps)" runs all of them indiscriminately.

That is survivable at 21 steps and stops being survivable well before dozens.
The failure is not that a survey is slow; it is that **nothing in the model knows
which steps are cheap**, so no caller — a survey author, the scheduler, or a
future "give me a quick read" action — can make an informed choice. Every
decision about what to bundle is currently made by hand and re-made from memory.

## What exists today, and why neither signal is sufficient

Both were checked against the tree on 2026-08-20. Do not assume either is usable
as-is.

**`analysis_catalog.yaml` has `run_time`** — values `fast` (16), `minutes` (5),
`async` (1). Two problems:

- **Wrong granularity.** It is per *analysis*, but cost is a property of *steps*.
  `repository_health` is tagged `fast` and is genuinely cheap now — but only
  because `repo_git_statistics` took the expensive fetch out of it on 2026-08-20.
  The tag was accurate neither before that change nor during it.
- **Demonstrably stale.** It is hand-maintained prose with nothing checking it.

**`StepInfo.requires_resources`** is a real structural signal — 4 of 21 steps
declare `zipball_root` (`repo_file_inventory`, `repo_homepage`,
`repo_data_profiling`, `repo_symbol_extraction`). It is already load-bearing: the
Discovery tier test asserts every discovery analysis's steps declare `{}`. But it
captures only one cost axis. `repo_git_statistics` requires no zipball and is one
of the most expensive steps in the system.

**So there are two independent axes, and no existing field captures both:**

| axis | what it costs | current signal |
|---|---|---|
| **fetch** | network, GitHub rate limit, wall-clock | `requires_resources` (partial — misses API-heavy steps) |
| **compute** | CPU, embedding, parsing | none |

## Decisions

**D1 — Cost lives on `StepInfo`, not in the analysis catalog.** Steps are the
unit that runs, the unit `SurveyOrchestrator` filters on, and the unit whose cost
we can actually observe. `run_time` in `analysis_catalog.yaml` stays where it is
as human-facing UI prose; it is not the machine-readable signal and should not be
promoted into one. Deriving an analysis's cost from its steps' costs is a natural
follow-up, not part of this.

**D2 — Two declared fields, not one blended score.** A single "cost: high" would
force a step that is slow-because-network and one that is slow-because-CPU into
the same bucket, which the caller then cannot act on differently — rate limits
and CPU are different constraints with different mitigations.

```python
fetch_cost: str = "none"      # "none" | "api" | "api_heavy" | "download"
compute_cost: str = "low"     # "low" | "medium" | "high"
```

Deliberately coarse and ordinal. Resist numeric estimates: they invite precision
nobody has measured and will rot exactly as `run_time` did.

**D3 — `fetch_cost` must be consistent with `requires_resources`, and a test
enforces it.** A step declaring `zipball_root` cannot have `fetch_cost="none"`.
This keeps the new field from drifting away from the structural one that already
exists, which is the failure mode `run_time` demonstrates.

**D4 — Seed values from observation, not estimation.** Where a step's cost has
actually been measured, use that; where it has not, assign conservatively and say
so in a comment. Known measurements from 2026-08-19/20:
- `repo_git_statistics`: 430s against odpi/egeria at `fast=False`; the `fast`
  flag exists precisely because `fetch_diff_stats` is one API call per commit
  over a 90-day window → `fetch_cost="api_heavy"`, `compute_cost="low"`.
- `repo_rag_ingestion`: embeds the repo → `compute_cost="high"`. Its
  `fetch_cost` is conditional (`IncrementalIndexer` downloads only when the SHA
  moved), which is exactly the nuance a coarse field cannot express — record
  `"download"` and note the conditionality in the comment rather than inventing a
  fifth value.
- The 4 zipball steps → `fetch_cost="download"`.
- The 17 zero-fetch steps → `fetch_cost="none"` unless they call an API.

**D5 — Add a `max_fetch_cost`/`max_compute_cost` filter to
`SurveyOrchestrator.run()`, and nothing else initially.** No new survey types, no
scheduler changes, no UI. One filter, tested, so a caller *can* say "everything
cheap". Composing actual survey types by budget is the next plan, and should be
written only after this filter has been used once in anger.

## The stage-assignment connection

This influences which questions and surveys belong to which stage, and the data
to check it already exists — verified 2026-08-20.

The chain is: `resource_questions.csv` gives each question a funnel stage →
`question_catalog.yaml`'s `answering.analysis_ids` links it to analyses →
`REPO_ANALYSIS_STEP_MAP` links those to steps → steps will carry cost. So
**"is this stage's question answerable within this stage's cost budget?" becomes a
computable question**, where today it is a matter of judgement re-made each time.

That matters because the stage taxonomy settled on 2026-08-20 is defined by a
cost-adjacent property already: Discovery is *the zero-fetch derivation tier* —
"does this collect, or reason over what is already collected" (CLAUDE.md rule
17). Cost tiers make that boundary machine-checkable rather than conventional.

**Add a consistency check** (a test, or a small script under `scripts/`) that
flags a question whose stage is cheaper than the analyses answering it. Run
today against the existing data it finds exactly one case:

> stage `Analysis/Enrichment` — *"Does it fit into our governance frameworks?"*
> answered by `egeria_publish` (`run_time: minutes`)

That near-clean result is the point: the check is cheap to add, will pass now,
and starts failing the moment a Scouting-tier question acquires an expensive
answer. It is far more valuable as a guard against future drift than as a
cleanup of the present.

Note the one hit is arguably not a defect — `egeria_publish` is an action rather
than an analysis. Decide whether to exclude `action != "survey"` entries before
treating the check as authoritative.

## Implementation

1. **`repo_survey_definition_adapter.py`** — add `fetch_cost`/`compute_cost` to
   `StepInfo` with the defaults in D2, then set them on all 21 entries. Comment
   each non-default value with *why*, citing a measurement where one exists.
2. **`survey_orchestrator.py`** — `run(..., max_fetch_cost=None,
   max_compute_cost=None)`, filtering the step list by ordinal position. Both
   `None` means today's behaviour exactly; the existing full-run tests are the
   regression guard.
3. **Tests**:
   - D3's consistency check: no `zipball_root` step has `fetch_cost="none"`.
   - Every step declares both fields (exhaustive, like
     `test_all_step_keys_are_registered` — a new step must make a cost decision,
     not inherit a default silently).
   - Filtering: `max_fetch_cost="none"` excludes the 4 download steps and
     `repo_git_statistics`; both-`None` runs all 21.
   - The stage/cost consistency check described above.
4. **No Egeria authoring, no CSV changes, no regeneration.** This plan touches no
   Survey Definition. If you find yourself running `dr_egeria`, stop — that is
   the next plan, not this one.

## Verification

- `uv run pytest tests/ -q` — baseline is **1351 passed, 9 skipped**.
- Expect `test_all_step_keys_are_registered` to be untouched (no new steps) but
  any exhaustive StepInfo test to need updating.
- Sanity-check the seeded values by eye against the measurements in D4 — a step
  tagged `compute_cost="low"` that embeds a repo is worse than no tag at all.

## Out of scope

- Survey types composed by budget (the point of all this — but write it after
  the filter has been used once).
- Scheduler using cost to decide what to run when.
- Deriving `analysis_catalog.yaml`'s `run_time` from step costs, or removing it.
- Per-repo cost estimates (steps cost different amounts on different repos; this
  plan describes steps, not runs).

## Hazards

- **Do not let the tiers become numbers.** The moment they are seconds, they are
  wrong for every repo but the one they were measured on.
- **`git commit -s`** — DCO sign-off required.
- Do not edit `packages/egeria-advisor/data/repos/egeria-python` — RAG corpus,
  not a working repo.
