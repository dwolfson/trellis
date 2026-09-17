# Inventory: how far `/next` actually is

**Rebuilt 2026-09-17** from the project owner's assessment, which replaced my
own. Read against `main` at `fa9ac4dc`.

---

## 0 · Why this was rebuilt

My first version screened subsystem vocabulary counts between `index.html` and
`next/`. It found sixteen candidates, missed Automate, missed the Understanding
and Activity stages, missed work lists and RFAs, and credited `/next` with
honestly declaring deferrals it does not actually show. **The project owner
produced a better inventory in one message than the screen produced in an
afternoon** — because the question is "how far is this from doing the job",
which is a judgement about the product, not a diff between two files.

So this document is organised by the owner's ten points. Where I verified
something in the code, it is cited. Where I did not, it says so.

**Decision (project owner, 2026-09-17):** roughly half done on repositories, and
other resource types are not worth looking at until repositories are finished.

---

## 1 · Enrichment — partially built; needs design, analysis and implementation

`STAGES` carries no `built` flag for it. Because of the defect in
`DEFECT-UNBUILT-STAGES-RENDER-AS-BUILT.md`, it **renders as though built**.
Scope not yet assessed by me.

## 2 · Understanding — not really started

Same: no `built` flag, renders as built. The comment at `next/app.js:145` claims
it *"renders charts now"* and that the catalog rows it lacked *"were never what
fed it"* — the owner's read is that this overstates it. **The comment is the only
thing asserting the stage works; treat it as unverified.**

## 3 · Curate — incomplete, especially component selection and blueprints

The verdict-ruling work (`#107`) landed here, so the component row and coverage
sentence are current. Blueprints and selection are not done. This is the stage
with the most design already invested and still not finished.

## 4 · Automate — not started

No `built` flag; renders as built, with four sub-tabs advertising working panes.

## 5 · Admin — **shipped 2026-09-17**, `#124`

Five real ports plus six named deferrals — `next/admin/index.js`, `logs.js`,
`prefect.js`, `question_catalog.js`, `annotation_types.js`, `feedback.js`, with
`test_next_admin_pane.py`. See `ITEM-5-ADMIN-IMPLEMENTED.md`.

*Was: "not started — 338 references in `index.html`, 2 under `next/`."*

## 6 · Activity — **shipped 2026-09-17**, `#122`

`next/stages/activity.js`, with `ITEM-6-ACTIVITY-IMPLEMENTED.md`.

*Was: "not started — the 21 references are to the activity log as a data
source, not a view."*

## 7 · Work lists — orphaned, and I found where

**Verified, and it is one missing call.** Everything exists:

- the backend — `web/routes/work_lists.py`, `work_lists.WorkLists`
- the pane renderer — `next/worklist.js`, 89KB, exporting `renderWorkListPane`
  at `:170`
- the nav — `renderWorkListNav` (`app.js:673`), called at `:609`
- the state — `workListSlug`, `lastWorkListSlug`, `workListIndex` (`:130-133`)
- the import — `app.js:26` pulls `listWorkLists`, `openWorkList`,
  `saveAsWorkList`, `openDialog`, `closeCellDetail`, `CELL`

**`renderWorkListPane` is never called anywhere in `app.js`** — it is not even
among the names imported at `:26`. The feature is complete at both ends and
unwired at exactly one point, which is why it does not work.

The owner's read on the idea: working through a cohort at a time is a real
strength in the early phases, and less useful once the work is detailed
per-resource analysis. That bounds where it should be carried through, and it
suggests the cohort pane belongs to Scouting and Assessment rather than
everywhere.

## 8 · Feedback — present, not effectively used

**Largely shipped.** `ITEM-8-FEEDBACK-IMPLEMENTED.md` built the per-answer
verdict landing as destination `ours` in the gaps collection, and `#124` added
the review side as `next/admin/feedback.js`. What remains is one deferred UI
choice the implementer flagged: the comment uses `window.prompt` rather than an
inline field — *"if the designer wants it inline, that is a UI round, not a
rework of this path."* Agreed, and it is not worth a round on its own.

*Was: "present, not effectively used — missing the per-answer form and the
review side."*

## 9 · Chat — under-utilised power

Owner's assessment; not yet analysed by me. `renderChatLog` exists; classic has
91 references to 34 under `next/`, plus a persisted panel-open state
(`pe_chat_panel_open`) that `/next` does not keep.

## 10 · RFAs — not started, and this one is declared

`app.js:601` links out: *"The RFA drawer is not built in /next — opens the
current UI"*. So unlike items 1–6, this deferral is honest and visible. It is
the model the six unbuilt stages were supposed to follow.

---

## Cross-cutting

- **`DEFECT-UNBUILT-STAGES-RENDER-AS-BUILT.md`** covers items 1, 2, 4 and part of
  3 and 6: `unbuilt` is read in three places and set in none, so six stages
  render as live. Until that lands, no statement about `/next`'s completeness can
  be made from the UI itself.
- **Silently partial is the dangerous tier**, and it is where most of this list
  sits. Item 10 is the only deferral a user can see.
- **Group collapse** (`SPEC-PARITY-INVENTORY-AND-GROUPS.md` §3) and the
  **persisted sidebar width** and **scout source mode** remain, small.

## What I got wrong, kept here deliberately

The screen's premise was that a capability missing from `/next` would also be
missing its vocabulary. Four of the ten items above disprove that: Automate,
Understanding and Activity all appear as labels, and work lists appears 44 times
while being unreachable. **A count of occurrences cannot distinguish wired from
present.** The method that would have worked is the one the owner used: open the
UI and try to do the job.


---

## 11 · Corrected 2026-09-17, and the method failed a third time

The coordinating implementer flagged that §5 and §6 listed Admin and Activity as
absent when both had shipped (`#124`, `#122`). Correct, and §8 was stale too —
`#124` added `next/admin/feedback.js`, the review side I had called missing.

**The same method failure, third instance.** My screen greps `next/app.js`, and
`#124` put Admin in a new directory, `next/admin/*`, touching `app.js` for only
seventeen lines. So a whole shipped subsystem read as zero — exactly as Automate
read as present because its label was there, and as work lists read as present
because the name appeared 44 times unreachable.

**Occurrence counting cannot answer this question, and I should stop reaching for
it.** The durable check is the one the implementers now maintain themselves: an
`ITEM-N-*-IMPLEMENTED.md` per item. Six of those existed when this document was
written and I did not read them. That is the list; this document should be
derived from it plus the owner's judgement, and never again from a grep.
