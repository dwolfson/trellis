# Design notes: an index by status

**Status:** index, hand-maintained. Last checked against `origin/main` on 2026-10-28.

This folder holds Resource Explorer's design record: proposals, the notes written as work was built,
the evidence behind decisions, and the exchange with the designer. This index groups the notes in
the root of the folder by **where the work stands on main**, not by what each note's own status line
says. Several of those lines were written before the work merged. Where a note's status line was
contradicted by main on 2026-10-28, it gained a dated "Status refreshed" line, and the original line
was kept.

For the user-facing guides, see [`../README.md`](../README.md).

## How the folder is laid out

| where | what | count (2026-10-28) |
|---|---|---:|
| [`implemented/`](implemented/) | finished-work records (`*-IMPLEMENTED.md`), plus shipped notes that an `*-IMPLEMENTED` note cites | 174 |
| [`evidence/`](evidence/) | audits, probes, measurements and their data files | 52 |
| [`exchange/`](exchange/) | answered asks, replies, reviews, specs and briefs, moved out of the root 2026-10-15 | 59 |
| [`rulings/`](rulings/) | rulings that later notes build on | 3 |
| [`wireframes/`](wireframes/), [`screenshots/`](screenshots/) | the designer's exports | |
| this folder's root | open design notes, asks and replies still in play, and the records below | |

The conventions come from `DESIGN-NOTES-MOVE-IMPLEMENTED.md`:

- **Cite a note by its bare name** (`see SOME-NOTE-IMPLEMENTED.md`), never by its path, so a later
  move between subfolders cannot break the citation. `tests/test_design_note_references_resolve.py`
  fails on any citation from code, tests, scripts or CI that does not resolve.
- **A note moves to `implemented/`** when it is an `*-IMPLEMENTED.md` record, or when it is a shipped
  note with a citing `*-IMPLEMENTED` twin. A design note whose work merged without such a twin stays
  in the root, and is listed under "Built" below.
- **Asks, replies, reviews and rulings stay in the root** while they are in play. Answered ones go to
  `exchange/`.

## Built: the work is on main

Each of these notes stays in the root because it has no `*-IMPLEMENTED` twin.

- [DESIGN-QUALITY-B1A-BASELINE-MATCH.md](DESIGN-QUALITY-B1A-BASELINE-MATCH.md): baseline match on the measures RE profiles, opt-in per table, and the TestGen-only import (PR #887)
- [DESIGN-QUALITY-Q6-RECENCY.md](DESIGN-QUALITY-Q6-RECENCY.md): Recency, the date branch of the functional-type inference, and Future_Date_1Y (PR #880)
- [DESIGN-PUBLISHING-COLUMN-VERDICTS.md](DESIGN-PUBLISHING-COLUMN-VERDICTS.md): Curate's Publish sends the stored per-column verdicts
- [DESIGN-ENGINE-HOST-GOVERNANCE-ENGINE-API.md](DESIGN-ENGINE-HOST-GOVERNANCE-ENGINE-API.md): engine host on the Governance Engine view service (the designer's words, Q4, are still open)
- [DESIGN-COORDINATED-RUN-CREDENTIAL.md](DESIGN-COORDINATED-RUN-CREDENTIAL.md): one-run credential for Egeria-coordinated runs (the designer's words, Q3, are still placeholders)
- [SLICE-ENGINE-HOST-CASE3-RE-DEFINITIONS-DISPATCHED-BY-EGERIA.md](SLICE-ENGINE-HOST-CASE3-RE-DEFINITIONS-DISPATCHED-BY-EGERIA.md): Egeria runs RE's own survey definitions (PR #708)
- [SLICE-ENGINE-HOST-STEP4-MIXED-PROCESS.md](SLICE-ENGINE-HOST-STEP4-MIXED-PROCESS.md): one mixed Egeria process, a native step chained to an RE step (PR #699)
- [EXECUTION-MODES-HYBRID-CLARIFICATION.md](EXECUTION-MODES-HYBRID-CLARIFICATION.md): "hybrid" folded into `executes_at: egeria-adaptive`
- [PLAN-PREFECT-OR-ALTERNATIVE.md](PLAN-PREFECT-OR-ALTERNATIVE.md): the orchestration decision. The per-run engine choice is recorded in `ENGINE-CHOICE-IMPLEMENTED.md`
- [DESIGN-INTERFACE-SURFACE-IMPLEMENTED-RUNG.md](DESIGN-INTERFACE-SURFACE-IMPLEMENTED-RUNG.md): the interface ladder's missing rung. Its status line says "design only", and code cites it. It stays in the root by an owner decision recorded in `DESIGN-NOTES-MOVE-IMPLEMENTED.md`

## In progress: built in part, or on a branch in today's gate

**Do not edit the notes marked ⚑.** Open branches change them on 2026-10-28, so an edit here would
conflict with those branches.

Quality and TestGen (the user guide is [`../testgen-integration-guide.md`](../testgen-integration-guide.md)):

- [DESIGN-QUALITY-AT-SCALE-AND-TESTGEN.md](DESIGN-QUALITY-AT-SCALE-AND-TESTGEN.md): the quality slice plan. Q2 (#816), the accept flow (#822), Q6 (#880) and B1a (#887) are merged
- [DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md](DESIGN-VALUE-PROFILE-AND-QUALITY-CHECKS.md): value profile and quality checks for databases
- ⚑ [DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md](DESIGN-QUALITY-Q4-PORT-PLAN-AND-CALIBRATION.md): the port plan on the TestGen inventory. The profile-1b branch edits it
- ⚑ [DESIGN-QUALITY-Q5-DATA-QUALITY-RULE.md](DESIGN-QUALITY-Q5-DATA-QUALITY-RULE.md): accepted checks as Egeria `DataQualityRule`s. Branch `claude/re-quality-q5-dqrule-publish`
- ⚑ `DESIGN-QUALITY-Q3-BATCH-AND-SCHEDULE.md`: batch and schedule over a work list. Only on branch `claude/re-quality-q3-batch-schedule` so far
- ⚑ `DESIGN-QUALITY-PROFILE-1B.md`: profile 1b. Only on branch `claude/re-quality-profile-1b-on-q5` so far
- [INTEGRATION-TESTGEN-RE-EGERIA.md](INTEGRATION-TESTGEN-RE-EGERIA.md) and [INVENTORY-TESTGEN-TEST-TYPES-MAPPED.md](INVENTORY-TESTGEN-TEST-TYPES-MAPPED.md): reference for the above
- [SPEC-PYEGERIA-DATA-QUALITY-RULE.md](SPEC-PYEGERIA-DATA-QUALITY-RULE.md): the pyegeria convenience API that Q5 would use. Not implemented

Declared extensibility (the user guide is [`../extending-with-analyses.md`](../extending-with-analyses.md)):

- [DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md](DESIGN-DECLARED-EXTENSIBILITY-RENDERING-CHAT-CONFIDENCE.md): one declaration, three consumers. The parent design
- ⚑ [DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md](DECLARED-EXTENSIBILITY-SLICE1-PR1-GAPS.md): slice 1, the declaration (PR #885). Branch `claude/re-ext-slice2-chat-compile` edits it
- ⚑ [DECLARED-EXTENSIBILITY-SLICE1-PR2-PUBLISH-TABLE.md](DECLARED-EXTENSIBILITY-SLICE1-PR2-PUBLISH-TABLE.md): slice 1, the Curate publish table (PR #886). Branch `claude/re-ext-publish-table-answers` edits it
- ⚑ `DECLARED-EXTENSIBILITY-SLICE2-CHAT-COMPILE.md`: slice 2, chat. Only on branch `claude/re-ext-slice2-chat-compile` so far
- [DESIGN-ANALYTIC-EXTENSIBILITY-WORKING-ASSUMPTIONS.md](DESIGN-ANALYTIC-EXTENSIBILITY-WORKING-ASSUMPTIONS.md): the 2026-10-02 brainstorm that started it
- [SLICE-ANALYTIC-LIBRARY-STEPS-NEXT-FIVE.md](SLICE-ANALYTIC-LIBRARY-STEPS-NEXT-FIVE.md): the next Analytic Library steps Egeria can dispatch

Work lists and files:

- ⚑ [DESIGN-WORK-LISTS-WINNOWING-AND-MIXED-KINDS.md](DESIGN-WORK-LISTS-WINNOWING-AND-MIXED-KINDS.md): work lists as a winnowing bench, and lists of mixed kinds
- ⚑ [BRIEF-FILES-QUESTIONS-AND-ANALYSES-TO-RETIRE-CLASSIC.md](BRIEF-FILES-QUESTIONS-AND-ANALYSES-TO-RETIRE-CLASSIC.md): the Files questions and analyses that let Classic retire. Branch `claude/re-files-steps-6-8`
- [DESIGN-FILES-REMOTE-REACH.md](DESIGN-FILES-REMOTE-REACH.md): file systems RE reaches that Egeria cannot

Engine host, Curate and the /next UI:

- [DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md](DESIGN-RE-ENGINE-HOST-BY-EQUIVALENCE.md): RE as an engine host. Steps 3 and 4 and case 3 are built
- [DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md](DESIGN-ARTIFACTS-VIEW-AND-DOC-LINKS.md): the Artifacts view. Slice 1's columns are merged (PR #700)
- [DESIGN-CURATE-BY-ANALYSIS.md](DESIGN-CURATE-BY-ANALYSIS.md): Curate's "By analysis". Curation coverage is built (PR #628)
- [DESIGN-CURATE-NESTING-SELECTION-AND-DEPENDENCY-KINDS.md](DESIGN-CURATE-NESTING-SELECTION-AND-DEPENDENCY-KINDS.md): Curate for repositories. Explicit selection is built (PR #550)
- [DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md](DESIGN-BLUEPRINT-BENCHMARK-EGERIA-WORKSPACES.md): the owner's hand-built blueprints as the bar. Parts 0, 6 and 6a are built (`BLUEPRINT-CONTAINER-SHAPE-IMPLEMENTED.md`)
- [DESIGN-ENRICHMENT-AND-CURATE-PUBLISHING-TO-EGERIA.md](DESIGN-ENRICHMENT-AND-CURATE-PUBLISHING-TO-EGERIA.md): publishing Enrichment and Curate to Egeria
- [DESIGN-ARCHIVE-RESTORE-WRAPPERS-ISSUE-159.md](DESIGN-ARCHIVE-RESTORE-WRAPPERS-ISSUE-159.md): archive and restore (the ISSUE-159 position)
- [PLAN-FINISH-REPOS.md](PLAN-FINISH-REPOS.md): finish `/next` for repositories. Most items have `*-IMPLEMENTED` records
- [PLAN-CARDS-AND-TILES.md](PLAN-CARDS-AND-TILES.md): cards and tiles across /next. C1 is built (PR #782)
- [PLAN-ANALYSIS-GAPS-REPOS-AND-DATABASES.md](PLAN-ANALYSIS-GAPS-REPOS-AND-DATABASES.md): closing the repository and database analysis gaps

## Proposals: designed, not built

- [DESIGN-AMUNDSEN-MIGRATION-ASSESSMENT.md](DESIGN-AMUNDSEN-MIGRATION-ASSESSMENT.md): Amundsen users and RE/Egeria
- [DESIGN-BROADER-QUESTIONS-WITHOUT-CONTENT-INGESTION.md](DESIGN-BROADER-QUESTIONS-WITHOUT-CONTENT-INGESTION.md): broader questions without ingesting content
- [DESIGN-EGERIA-SUGGESTIONS-AND-RE-OWN-CATALOGUING.md](DESIGN-EGERIA-SUGGESTIONS-AND-RE-OWN-CATALOGUING.md): suggestions to Egeria, and RE cataloguing on its own (decision deferred)
- [DESIGN-FIND-AND-INTEGRATE-PURPOSES-AND-THE-DATA-LENS.md](DESIGN-FIND-AND-INTEGRATE-PURPOSES-AND-THE-DATA-LENS.md): the Find and Integrate purposes, and the data lens
- [DESIGN-MCP-SERVER-AND-A2A-GAPS.md](DESIGN-MCP-SERVER-AND-A2A-GAPS.md): an MCP server over RE's engine
- [DESIGN-OPEN-DATA-RESOURCE-KIND-BRAINSTORM.md](DESIGN-OPEN-DATA-RESOURCE-KIND-BRAINSTORM.md): an open-data resource kind (brainstorm)
- [DESIGN-OPTIONAL-ANALYSES-TO-EGERIA-ANNOTATIONS.md](DESIGN-OPTIONAL-ANALYSES-TO-EGERIA-ANNOTATIONS.md): a configurable path from optional results to annotations (options)
- [DESIGN-RAG-CODE-INGESTION-OPTIONAL.md](DESIGN-RAG-CODE-INGESTION-OPTIONAL.md): optional RAG ingestion of code
- [DESIGN-REPO-TO-RUNTIME-COMPONENT-LINKS.md](DESIGN-REPO-TO-RUNTIME-COMPONENT-LINKS.md): linking built components to runtime components (discussion)
- [NOTE-ANNOTATION-ENVELOPE-ATTRIBUTES.md](NOTE-ANNOTATION-ENVELOPE-ATTRIBUTES.md): the annotation envelope RE needs from Egeria
- [REQUIREMENTS-RE-DATA-CHANNELS.md](REQUIREMENTS-RE-DATA-CHANNELS.md): how RE reaches data (draft requirements)
- [SPEC-REPORT-ACTS.md](SPEC-REPORT-ACTS.md): the three acts on a report
- [SPEC-RESOURCE-BROWSER-PORTAL-APP.md](SPEC-RESOURCE-BROWSER-PORTAL-APP.md): a shop-for-data app on Egeria alone

## Rulings, asks and replies in play

Rulings: [DESIGN-BLUEPRINT-NAMING-WHAT-IT-REPRESENTS.md](DESIGN-BLUEPRINT-NAMING-WHAT-IT-REPRESENTS.md),
[DESIGN-FILE-TYPES-AS-ANNOTATIONS.md](DESIGN-FILE-TYPES-AS-ANNOTATIONS.md),
[RULING-OWNER-FACT-VS-OWNERSHIP-CLASSIFICATION.md](RULING-OWNER-FACT-VS-OWNERSHIP-CLASSIFICATION.md),
[RULING-PUBLISH-NOT-CATALOG.md](RULING-PUBLISH-NOT-CATALOG.md),
[RULING-RUNS-REGISTRATION-ARCHITECT.md](RULING-RUNS-REGISTRATION-ARCHITECT.md),
[RULING-THEMES-PORTAL-DARK-LIGHT.md](RULING-THEMES-PORTAL-DARK-LIGHT.md). The two `DESIGN-` names are rulings
despite their prefix. Older rulings are in [`rulings/`](rulings/).

Asks to the designer, with the reply where one exists:

| ask | reply |
|---|---|
| [ASK-DESIGNER-CANCEL-REPORT-KEPT.md](ASK-DESIGNER-CANCEL-REPORT-KEPT.md) | not yet |
| [ASK-DESIGNER-CATALOGUING-AT-SCALE.md](ASK-DESIGNER-CATALOGUING-AT-SCALE.md) | [REPLY-DESIGNER-CATALOGUING-AT-SCALE.md](REPLY-DESIGNER-CATALOGUING-AT-SCALE.md) |
| [ASK-DESIGNER-CURATE-SPLIT-BY-JOB.md](ASK-DESIGNER-CURATE-SPLIT-BY-JOB.md) | [REPLY-DESIGNER-CURATE-SPLIT-BY-JOB.md](REPLY-DESIGNER-CURATE-SPLIT-BY-JOB.md) |
| [ASK-DESIGNER-ENGINE-HOST-CANCEL-WORDS.md](ASK-DESIGNER-ENGINE-HOST-CANCEL-WORDS.md) | [REPLY-DESIGNER-ENGINE-HOST-CANCEL-WORDS.md](REPLY-DESIGNER-ENGINE-HOST-CANCEL-WORDS.md) |
| [ASK-DESIGNER-FIRST-INDEX-CONSENT-CHOICE-2026-10-20.md](ASK-DESIGNER-FIRST-INDEX-CONSENT-CHOICE-2026-10-20.md) | [REPLY-DESIGNER-FIRST-INDEX-CONSENT-CHOICE-2026-10-20.md](REPLY-DESIGNER-FIRST-INDEX-CONSENT-CHOICE-2026-10-20.md) |
| [ASK-DESIGNER-GROUP-SCHEDULING-AND-FIRST-INDEX-2026-10-19.md](ASK-DESIGNER-GROUP-SCHEDULING-AND-FIRST-INDEX-2026-10-19.md) | [REPLY-DESIGNER-GROUP-SCHEDULING-AND-FIRST-INDEX-2026-10-19.md](REPLY-DESIGNER-GROUP-SCHEDULING-AND-FIRST-INDEX-2026-10-19.md) |
| [ASK-DESIGNER-RUNS-REGISTRATION.md](ASK-DESIGNER-RUNS-REGISTRATION.md) | [REPLY-DESIGNER-RUNS-REGISTRATION.md](REPLY-DESIGNER-RUNS-REGISTRATION.md) |
| [ASK-DESIGNER-STATE-CUES-ADDENDUM.md](ASK-DESIGNER-STATE-CUES-ADDENDUM.md) | [REPLY-DESIGNER-STATE-CUES-ADDENDUM.md](REPLY-DESIGNER-STATE-CUES-ADDENDUM.md) |
| [ASK-DESIGNER-TABLE-PREVIEW-2026-10-19.md](ASK-DESIGNER-TABLE-PREVIEW-2026-10-19.md) | [REPLY-DESIGNER-TABLE-PREVIEW-2026-10-19.md](REPLY-DESIGNER-TABLE-PREVIEW-2026-10-19.md) |
| [ASK-DESIGNER-WORDS-ROUND-2026-10-18.md](ASK-DESIGNER-WORDS-ROUND-2026-10-18.md) | not yet |

Other replies and reviews: [REPLY-DESIGNER-CURATE-CATALOGUE-SCOPE-DATABASES.md](REPLY-DESIGNER-CURATE-CATALOGUE-SCOPE-DATABASES.md),
[REPLY-DESIGNER-CURATE-SCOPE-ROUND-2.md](REPLY-DESIGNER-CURATE-SCOPE-ROUND-2.md) (their asks are in `exchange/`),
[REPLY-SURVEY-ANALYSES-PANE-USER-FACING-MODEL.md](REPLY-SURVEY-ANALYSES-PANE-USER-FACING-MODEL.md),
[REVIEW-QUESTIONS-AND-ANALYTICS-2026-10-22.md](REVIEW-QUESTIONS-AND-ANALYTICS-2026-10-22.md).

## Records and reference

- [TIMELINE.md](TIMELINE.md): one dated block per note as it lands
- [INBOX.md](INBOX.md): the designer's inbox: what design said, and whether it was built
- [DEFERRED-REGISTER.md](DEFERRED-REGISTER.md): what was deliberately deferred, and why
- [WORKING-RULES-STANDING-CLEARANCES.md](WORKING-RULES-STANDING-CLEARANCES.md): standing clearances, hard gates, and how sessions report
- [HANDOFF-DESIGN-SESSION-2026-10-16.md](HANDOFF-DESIGN-SESSION-2026-10-16.md): handoff from the design and gate session
- [PLAN-OPEN-FRONTS-2026-10-14.md](PLAN-OPEN-FRONTS-2026-10-14.md): the open fronts after the owner's backlog review
- [BACKLOG-TRIAGE-2026-09-30.md](BACKLOG-TRIAGE-2026-09-30.md): backlog triage
- [CLASSIC-VS-NEXT-PARITY-2026-09-30.md](CLASSIC-VS-NEXT-PARITY-2026-09-30.md) and [INVENTORY-CLASSIC-TO-NEXT.md](INVENTORY-CLASSIC-TO-NEXT.md): Classic versus `/next`
- [AUDIT-PYEGERIA-6.2.2.md](AUDIT-PYEGERIA-6.2.2.md), [AUDIT-PYEGERIA-6.2.3.md](AUDIT-PYEGERIA-6.2.3.md): trellis on each pyegeria release
