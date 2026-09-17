/* Investigation — the frame, not a pane.
 *
 * PLAN-FINISH-REPOS.md Part 2 §1 asks for one module per canonical stage id
 * so a future session touches only its own file plus one import line in
 * app.js. Investigation has nothing to move here today: `STAGES` in app.js
 * marks it `{ frame: true }`, and `loadPane()`'s dispatch renders it as an
 * honest "not in /next" placeholder (`paneMessage(...)`) rather than calling
 * any Investigation-specific renderer — there isn't one. Investigations are
 * live in the current (classic) UI only.
 *
 * If Investigation ever gets its own /next pane, its renderer belongs here,
 * exported, with one new `import { ... } from '/static/next/stages/
 * investigation.js';` line added to app.js — see
 * docs/design-notes/APP-JS-SPLIT-IMPLEMENTED.md for how the other stage
 * modules (enrichment.js, curate.js, understanding.js) do this.
 */
export {};
