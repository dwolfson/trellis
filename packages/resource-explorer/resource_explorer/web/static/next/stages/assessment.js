/* Assessment.
 *
 * PLAN-FINISH-REPOS.md Part 2 §1 asks for one module per canonical stage id.
 * Assessment is NOT marked `built` in app.js's `STAGES` array, so
 * `loadPane()`'s dispatch renders it as an honest "not in /next" placeholder
 * and never reaches the generic Questions-checklist engine for it. There is
 * no Assessment-specific rendering code anywhere in app.js today to move here.
 *
 * Building Assessment means adding its renderer(s) to this file, exporting
 * them, marking `{ id: 'assessment', ... built: true }` in app.js's `STAGES`
 * array, and adding one `import { ... } from '/static/next/stages/
 * assessment.js';` line to app.js — see
 * docs/design-notes/APP-JS-SPLIT-IMPLEMENTED.md.
 */
export {};
