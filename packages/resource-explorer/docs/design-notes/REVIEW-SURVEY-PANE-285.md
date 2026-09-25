# Review: the unified Survey & Analyses pane (#285) — revert, then re-land in three gated slices

**For:** the project owner and the coordinating session.
**From:** the design session, 2026-09-25, at the project owner's request after
a live test of `coco_pharma` found the merged pane unusable ("I can't find
anything I would view as correct or usable").
**Read against:** `main` at `3999c4a1` (#285 merged). Code read, not
live-tested; the screenshots were relayed in words and I did not see them.

## Verdict

**Revert #285 now.** It is a clean revert with nothing built on it, and it
removed a working filter (§1 below) while adding nothing the owner could use.
Then re-land the shape in three slices, each gated by a live, signed-in run
against `coco_pharma` recorded in the slice's `*-IMPLEMENTED.md` with what
the implementer saw on screen. Unit tests passed 1327/1327 on a pane that
did not work; they cannot be the gate for a user surface, and the repo's own
rule already says so (`extending-resource-explorer.md`, "open the thing a
user opens").

But the revert fixes **one** of the five points. Three are older gaps that
#285 made visible by putting everything on one screen, and one is a
design-document defect of mine. Reverting and re-landing the same shape
would reproduce four of the five complaints.

## The five points, sorted by cause

| # | Owner's report | Cause | Introduced by | Fix |
|---|---|---|---|---|
| 1 | Surveys are the same for all stages; they do not correlate to the stage's questions | `renderAnalysesIndexSection` pushes all 21 local analyses with no stage filter; the old `loadSurveyPane` filtered `r.tier === stage` (`git show 41703c55`, lines 616–617 removed). Every database analysis carries an `intent` (stage) in `analysis_catalog.yaml`, so the filter was possible and was dropped | **#285** — and my reply gave it cover: §2 of `REPLY-SURVEY-ANALYSES-PANE-USER-FACING-MODEL.md` says "the scope concept leaves the pane", meaning the *banner about how the list was built*; an implementer read it as "do not scope the list". That ambiguity is mine, corrected in §3 below | revert; re-land with the rule stated as **the stage's pane lists the surveys that answer the stage's questions**, derived from the question catalog's `analysis_ids` (survey-model Part II §4), never from a hand list |
| 2 | Egeria surveys are not runnable | by design, until RE can trigger them from the pane: the row's gate reason is "not runnable from Resource Explorer yet" | pre-existing; my reply §1 kept them as blocked rows | acceptable *only* when the rest of the pane works; on a pane where nothing else runs it reads as one more broken thing. Re-land order matters (§4) |
| 3 | Chat answer to a credential-capability question was garbled ("6 shown to the model", "No list to open — coverage_signals has no member reader yet", repeated) | not a leak of a trace: it is `chat.js:224–257`'s **evidence footer**, built for repositories (dependency lists with a "shown to the model" count and an open-list link). For a database every analysis has no member reader, so the footer degenerates into one "No list to open" line per analysis, and the answer itself was empty because the capability probe's result is not in the evidence compiler | pre-existing, surfaced by #186 (database chat now compiles evidence) | (a) the footer renders only lists that exist, never absence lines, and never more than the answer; (b) `context_compile` includes the stored capability probe as a fact so "what can this credential see" is answerable; (c) when compiled evidence is empty the answer says so in one sentence |
| 4 | No visualisation; Schema Inventory "lists schemas, tables, columns" and shows counts; Row Count Snapshot shows 3,526 rows, 0 bytes, "7 of 10 catalog estimates" | the `/next` UI has **no database report view at all** — no schema/table/column listing (grep of `next/*.js` for `schema_info` returns nothing), while the classic UI renders a full per-schema accordion (`index.html::renderDatabaseSurveyReport`). "By analysis" shows scalar readers only. `0 bytes` is the size-not-measured case rendered as a number (`database_surveyor.py:1482–1503` already distinguishes it; the reader does not). "7 of 10" is the new estimate labelling on a whole-database rollup that the schema-grain work (#266) should have made per schema | pre-existing: DB entered `/next` (#217) before `/next` had any DB result view; the design's §11 deferred visuals to designer round 2 but a *listing* is not a visual, it is the result | port the classic schema listing into `/next` as the Schema Inventory result view (rows from the structured tables, per schema); render "not measured" for bytes; make Row Count Snapshot per schema and per table with the estimate stamp on each row |
| 5 | Questions do not let me run surveys; "How big is this database" looks at one unnamed schema | (a) the question row has no run affordance for databases because runnability comes from hand lists: `DATABASE_ANALYSIS_STEP_MAP` exists **twice** (`database_surveyor.py:50`, `survey_definition_adapter.py:823`) and covers 10 step-backed ids; the five older `db_derived` analyses are covered by a second list; the three newest (`subject_signals`, `coverage_signals`, `preliminary_fit`) are in neither, hence "has no mapped survey step(s)" on exactly those rows. (b) "one unnamed schema" is the rollup rendered without naming what it rolled up | pre-existing; the "one flat dict" failure `extending-resource-explorer.md` §Scaling warns about, now with two copies | derive runnability from the analysis catalog and the step registry (`PRODUCES`, design §17.1) and delete both hand lists; every database answer names its scope ("across 6 of 8 visible schemas: …") |

## §3 · The correction to my reply (#282)

`REPLY-SURVEY-ANALYSES-PANE-USER-FACING-MODEL.md` §2 now states, in these
words: **the list is scoped to the stage.** A stage's pane lists the surveys
and analyses that answer that stage's questions, derived from the question
catalog, plus the stage's own analyses by `intent`. What leaves the pane is
the *banner about how the list was scoped* ("Scope: all tiers — stage filter
unavailable"), not the scoping. When nothing answers the stage's questions,
the empty state says so and names the nearest stage that has something.

## §4 · Re-landing order, three slices, each with a live gate

1. **Runnability from the catalog, and the Questions tab runs surveys.**
   Delete both `DATABASE_ANALYSIS_STEP_MAP` copies; derive analysis → steps
   from the catalog and step registry; a question row shows Run for each
   analysis that answers it. Gate: on `coco_pharma`, signed in, every
   question with an answerable analysis shows Run, and "How big is this
   database" runs Schema Inventory and names the schemas it counted.
2. **The Schema Inventory and Row Count result views in `/next`**, per
   schema, from the structured tables, with "not measured" and the estimate
   stamp rendered. Gate: the owner can see schemas, tables and columns for
   `coco_pharma` in `/next`, with the credential banner above them.
3. **The unified pane, stage-scoped**, per the corrected reply. Gate: the
   Scouting and Discovery tabs list different surveys, each row's second
   line shows the last result, Egeria's native survey is a blocked row with
   its reason, and nothing on the screen is a rollup without a name.

The chat footer (#3) is its own small PR and does not wait.

## §5 · The process change

Add to `COORDINATOR-BRIEF-MULTI-RESOURCE.md`: **a PR that changes a user
surface is not done until the implementer has used it, signed in, on a real
resource, and the `*-IMPLEMENTED.md` says what they saw** — a sentence per
screen, not a screenshot requirement. Unit tests gate regressions in logic;
they cannot gate whether a person can use the screen. Four invisible
extensions in September and this pane were all green in tests.
