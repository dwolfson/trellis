/* Discovery.
 *
 * PLAN-FINISH-REPOS.md item 11: Discovery is now `built: true` in app.js's
 * `STAGES` array. It needed no bespoke renderer -- the generic
 * Questions-checklist engine (`loadPane()` in app.js) already reaches it
 * correctly, the same as Scouting/Enrichment/Curate, because the catalog
 * carries 10 real Discovery-tagged questions (question_catalog.yaml) backed
 * by 10 `intent: discovery` analyses (analysis_catalog.yaml). Its
 * Disposition sub-tab was already calling a real write path before this
 * change -- `setDisposition()` (re-api.js) posts to
 * `/api/discovery/disposition`, i.e. `web/routes/discovery.py`'s
 * `set_repo_disposition` -- since that sub-tab is resource-scoped, not
 * stage-specific code; it only needed `built: true` to be reachable.
 *
 * `discovery.py`'s corpus-level, not-resource-scoped endpoints -- repo
 * search (`/search`), the bulk `/from-list` loader, and `/inventory.csv`
 * export -- are NOT rendered by this file, and never will be: they are not
 * resource-scoped, so they don't belong to Discovery any more than to any
 * other stage (SPEC-ACTIONABLE-AND-HONEST.md point 2). They live at the
 * sidebar's "Find repos" action instead (app.js's `find-repos` action,
 * `next/discovery-import.js`) -- a real port, not a deferral, as of
 * NEXT-DISCOVERY-IMPORT-SEARCH-IMPLEMENTED.md. ("Org import" has no
 * separate endpoint to port: `RepoSearchRequest.org` is a plain search
 * qualifier, and an account URL pasted into from-list expands server-side.)
 * This file has nothing to export because Discovery has no resource-scoped
 * rendering of its own beyond the generic engine.
 */
export {};
