# Plan: finish `/next` for repositories

**Scope:** the project owner's ten points, 2026-09-17. Repositories only; other
resource types are out of scope until these are done.
**Success:** each item has a done test below. Order is not fixed — the
dependencies are.

---

## Part 1 · Coordination — how sessions stop colliding

Four things went wrong today that were not design problems: branches switched
under a running session four times, one commit swept eight files another session
had staged, `git` could not clean its own lock files, and the design record's
board was edited from two places.

**Worktrees, in a durable location.** Implementer sessions were already using
worktrees — but under `/private/tmp/claude-501/.../scratchpad/`, which gets
cleaned. All six were `prunable` and have been pruned. That is the same failure
that lost the design channel on day one.

`.claude/worktrees/` is gitignored (`.gitignore:245`) and lives inside the repo,
so it survives. Four are created and sitting on `origin/main`:

| worktree | branch | absolute path on this machine |
|---|---|---|
| `wt-honest` | `re/honest-stages` | `/Users/dwolfson/localGit/egeria-v6/trellis/.claude/worktrees/wt-honest` |
| `wt-design` | `re/design-notes` | `…/.claude/worktrees/wt-design` |
| `wt-classic` | `re/classic-honesty` | `…/.claude/worktrees/wt-classic` |
| `wt-admin` | `re/admin-surface` | `…/.claude/worktrees/wt-admin` |

**The protocol, four rules:**

1. **A session works in one worktree and never in the main checkout.** Reach it
   by absolute path — `git -C <path>` and edits under `<path>/…`. Sessions run
   from `/Users/dwolfson`, so nothing else changes about how they operate.
2. **The main checkout stays on `main` and serves the running app** (port 8810).
   Nobody commits there. It is currently on
   `re/restore-unbuilt-stages-defect-doc`; **it should go back to `main` once
   every active session has moved into a worktree** — that switch is the one
   operation I will not do unilaterally, having already caused one.
3. **Finishing means landing it where the app serves from:** push, merge, then
   `git -C <main checkout> fetch origin && merge --ff-only origin/main`. A push
   alone does not move the running app. If `--ff-only` refuses, stop and ask.
4. **New stream, new worktree:**
   `git worktree add .claude/worktrees/wt-<name> -b re/<name> origin/main`.

**Worktrees fix coordination, not contention.** They give each session its own
HEAD and index, which removes every failure listed above. They do **not** stop
two sessions editing `next/app.js` and conflicting on merge — and `app.js` is
6,861 lines that nearly every item below touches. That is what Part 2 is for.

---

## Part 2 · Two changes that unblock everything, in order

Both in `app.js`, both small, **one session, nothing else running in `app.js`.**

### 0 · Make the UI tell the truth — `wt-honest`

- **The `unbuilt` flag.** Read in three places, set in none, so six stages render
  as built. `DEFECT-UNBUILT-STAGES-RENDER-AS-BUILT.md` §3 has the four-line fix:
  invert the tests to read `built`, don't add `unbuilt: true`.
- **The work-list call.** `renderWorkListPane` (`worklist.js:170`) is never
  called and is not among `app.js:26`'s imports. Routes, renderer, nav and state
  all exist.

**Done when:** every unbuilt stage says so on screen, and opening a work list
shows its pane.

**Why first:** until this lands, nobody — including the owner — can read `/next`'s
completeness off the UI, so every other judgement here is being made against a
surface that misrepresents itself. It also turns on a whole feature for
approximately two lines.

### 1 · Split `app.js` so streams can run in parallel — `wt-honest`, straight after

`next/` already has the pattern: `worklist.js`, `feedback.js`, `format.js` are
separate ES modules imported by `app.js`. Extend it — one module per stage, under
`next/stages/`, each exporting its pane renderer. `app.js` keeps routing, shared
state and the chrome; each stage owns its own file.

**Done when:** two sessions can build two different stages without touching the
same file except for one import line each.

**This is the whole parallelism unlock.** Without it, items 1–4 and 6 queue
behind one another in one file no matter how many worktrees exist. With it they
are five independent streams.

---

## Part 3 · The eleven items

Each row: where it lives, what it depends on, and the done test. **No order is
imposed** beyond the dependencies in the last column.

| # | item | owns these files | done when | needs |
|---|---|---|---|---|
| 1 | **Enrichment** — partially built | `next/stages/enrichment.js`; Python for the judgement fields | a curator can record and revisit an enrichment judgement on a repo, and a judgement whose evidence moved says so | Part 2 |
| 2 | **Understanding** — not really started | `next/stages/understanding.js` | the stage answers a question a user actually brings to it; the `:145` comment claiming charts is either substantiated or removed | Part 2 |
| 3 | **Curate** — component selection, blueprints | `next/stages/curate.js`; `component_tree.py`, `repo_survey_definition_adapter.py` | a curator can select components and rule on blueprints, and the accept act catalogues what it said it would | Part 2; the `ComponentTree` drawing (canvas p7) |
| 4 | **Automate** — not started | `next/stages/automate.js` | the stage does the automation job, or honestly says it defers to classic | Part 2 |
| 5 | **Admin** — not started | `next/admin/*`, `web/routes/*` | the ten classic admin views are either reachable in `/next` or each recorded as a deliberate deferral | independent — start now in `wt-admin` |
| 6 | **Activity** — not started | `next/stages/activity.js` | the activity log is readable in `/next`, not only a data source | Part 2 |
| 7 | **Work lists** — orphaned | `next/worklist.js` | working a cohort start-to-finish is possible in the early phases; **how much further it carries is an experiment, not a boundary** — the owner's read is that it is strongest early and weakens as work gets detailed, so build it forward and find where it stops paying | Part 2 §0 |
| 8 | **Feedback** — present, not used | `next/feedback.js`; `web/routes/feedback.py`; `gaps.py` | per-answer feedback exists, and a disagreement lands in the gaps collection as destination `ours` | independent |
| 9 | **Chat** — under-utilised | `next/chat.js` (extract) | assessed first, then scoped — the only item here with no agreed shape yet | needs a design round |
| 10 | **RFAs** — not started | `next/rfa.js`; `rfa_egeria_sync.py` | an RFA can be raised and tracked in `/next`; today `app.js:601` honestly links out to classic | independent |
| 11 | **Discovery, Assessment, Analysis** — not started (added by the owner, 2026-09-17) | `next/app.js` (`STAGES`, the generic Questions-checklist pipeline `loadPane()` already reaches every other stage through); `web/routes/discovery.py` for Discovery's own endpoints | each of the three shows its real catalogued questions/analyses in `/next` instead of the "not built" placeholder, and Discovery's classic-only org-import/repo-search/`/from-list`/CSV-export/disposition-write endpoints are reachable there too (or each is explicitly, individually deferred) | Part 2. A prior assessment (2026-09-17) found Assessment and Analysis have **no bespoke UI or backend in classic at all** — both are the same generic catalog-card/dashboard shell classic already reuses for every stage, pointed at `intent: assessment`/`intent: analysis`; likely cheap once the mechanism exists. Discovery shares that same generic shell but does carry real, dedicated backend logic (`discovery.py`, 774 lines) that has no `/next` equivalent yet and would need its own porting work for parity, not just the card grid. |

**Plus, small and already specified:** group collapse with its force-expand rule
(`SPEC-PARITY-INVENTORY-AND-GROUPS.md` §3), the classic honesty clause
(`RULING-CLASSIC-AND-NEXT.md` §3, in `wt-classic`), the sort-direction fix
(`REVIEW-VERDICT-RULING.md` §2), persisted sidebar width, scout source mode.

### What can run at once, today

- `wt-honest` — Part 2, §0 then §1. **Blocks the stage work; start here.**
- `wt-admin` — item 5. Independent, own files, biggest single gap.
- `wt-classic` — the honesty clause, plus anything else in `index.html`.
- `wt-design` — item 9's assessment, and the item-3 drawing. Mine.

After Part 2 §1 lands, items 1, 2, 3, 4, 6 become parallel streams; add a
worktree each.

---

## Part 4 · What I will and won't do

**Will:** assess item 9 and draw item 3, both in `wt-design`; review what lands,
against the code, with citations.

**Won't:** write another ruling unless something is blocked, and won't specify
anything without reading the relevant code first. Four of my errors this week
came from specifying against this design record instead of the source — the
retraction the owner had already ruled out, `MetadataExpert` over
`ClassificationExplorer`, a resolver and a stale-state that both already
existed, and `members.py` named off a file listing I never opened.

**The eleven items are the definition of done.** Nothing gets added to this
plan from the design record; new work comes from the owner or from something
being blocked.
