/* Automate.
 *
 * PLAN-FINISH-REPOS.md Part 2 §1 asks for one module per canonical stage id.
 * Automate is NOT marked `built` in app.js's `STAGES` array, so
 * `loadPane()`'s dispatch renders it as an honest "not in /next" placeholder
 * and never reaches the generic Questions-checklist engine for it. There is
 * no Automate-specific rendering code anywhere in app.js today to move here.
 *
 * Building Automate means adding its renderer(s) to this file, exporting
 * them, marking `{ id: 'automate', ... built: true }` in app.js's `STAGES`
 * array, and adding one `import { ... } from '/static/next/stages/
 * automate.js';` line to app.js — see
 * docs/design-notes/APP-JS-SPLIT-IMPLEMENTED.md. (Part 3 item 4 notes
 * Automate may instead honestly defer to classic rather than build a pane
 * here at all — either outcome is a change to this file plus that one line.)
 */
export {};
