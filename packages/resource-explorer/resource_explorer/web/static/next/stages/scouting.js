/* Scouting.
 *
 * PLAN-FINISH-REPOS.md Part 2 §1 asks for one module per canonical stage id.
 * Scouting is `built: true` in app.js's `STAGES` array and IS live in
 * /next — but its pane is the generic, stage-parameterised Questions
 * checklist that lives in app.js's `loadPane()` (the big shared function
 * that fetches `getQuestions(slug, { phase: state.stage, ... })` and renders
 * `rowShell`/`rowInner`/`bodyLines`/`provenanceLine` per row). That engine
 * is deliberately NOT owned by Scouting alone: it is the same code path
 * Discovery, Assessment and Analysis are meant to render through once they
 * are built (see app.js's own comment above that function — "ONE pane,
 * parameterised by stage — not eight panes"), so it stays in app.js as
 * shared routing/rendering infrastructure rather than moving into this file.
 *
 * Scouting also has its own dedicated experience beyond the questions pane —
 * work lists, batch runs, the comparison grid — but that already has its own
 * module, `next/worklist.js`, from before this split (see the header comment
 * there). This file exists so Scouting has a place for anything that becomes
 * genuinely Scouting-only in the future; today there is nothing to export.
 */
export {};
