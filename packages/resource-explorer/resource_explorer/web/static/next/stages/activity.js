/* Activity.
 *
 * Named as an example file in the Part 2 §1 task alongside enrichment.js,
 * understanding.js, curate.js and automate.js — but Activity is NOT one of
 * the nine canonical stage ids in app.js's `STAGES` array (investigation,
 * scouting, discovery, assessment, analysis, enrichment, understanding,
 * curate, automate). Per packages/resource-explorer/CLAUDE.md, the 📋
 * Activity log is a persistent surface reachable from the header, decoupled
 * from `#intent-nav`/`currentNavIntent` the same way ⚙ Admin is — not
 * something a user does to a specific resource under one of the eight
 * intents. PLAN-FINISH-REPOS.md Part 3 item 6 lists it as a separate,
 * not-yet-started future item with its own `next/stages/activity.js`, ahead
 * of it actually being designed as a /next pane.
 *
 * There is no Activity-specific rendering code in app.js today (`listActivity`/
 * `pollActivity` are read-only polling helpers imported from re-api.js and used
 * inline in several other panes' progress reporting, not an Activity pane of
 * their own). This file is a placeholder for whichever future stage/nav
 * item design gives Activity its own /next surface — see
 * docs/design-notes/APP-JS-SPLIT-IMPLEMENTED.md.
 */
export {};
