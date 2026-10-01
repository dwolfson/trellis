# REPO-ONLY-ROUTES-DROP-DEFAULT — implemented

## Environment confirmation
`uv sync --all-packages --extra dev` run in worktree `trellis-re-drop-default` (branch
`re/repo-only-routes-drop-default`, off origin/main 99f047cf); resource_explorer resolves to:
`/Users/dwolfson/localGit/egeria-v6/trellis-re-drop-default/packages/resource-explorer/resource_explorer/__init__.py`
Signed test commit verified `G` and dropped before any code change.

## What changed
`resource_explorer/web/routes/projects.py`: `entity_type` is now a REQUIRED query parameter
(`Query(...)`, shared `_REQUIRED_KIND`) on `/analyses/{id}/trend`, `/members/{id}`,
`/members/{id}/children`, `POST /members/{id}/promote` and `/analyses-index` (analyses-index did
carry `= "repo"`, so it was changed). Omitting it is FastAPI's native 422 with
`loc: ["query", "entity_type"]`, "Field required" — the same body shape as every other validation
422 in this app. No client change: every helper in `static/re-api.js` already sends the kind via
`requireKind(...)` (#382); verified by reading each of the five URLs.

Not changed (flagged): `/{slug}/analyses/{id}/measurements` and `answer_question()` in
`routes/analyses.py` still default `entity_type` to "repo"; same bug class, out of this slice's list.

Part 2: `IMPLEMENTED.md` (package root) moved with `git mv` to
`docs/design-notes/REPO-ONLY-ROUTES-ENTITY-TYPE-IMPLEMENTED.md`.

## Tests
`tests/test_repo_only_routes_entity_type.py`: route x kind tables — missing kind -> 422 naming
`entity_type` (5 routes x 3 kinds); with kind, repo still works; database/filesystem still honest 400
on the four repo-built routes; analyses-index resolves for database/filesystem.
`tests/test_analysis_results_routes.py`, `tests/test_promotion.py`: pre-existing calls now pass `?entity_type=repo`.
Subset run (every test file touching /api/projects/): 628 passed, 1 skipped. Frontend untouched, harness not rerun (no JS changed).
Revert proof: with projects.py at HEAD, 15 new tests fail (34 pass); restored: 49 pass, 1 skip.

## Walk-ready: #383's unwalked gate item
"Trend read on a database work list is either real or one honest sentence, never 'not found.'"
Still intact: trend with `entity_type=database` (and filesystem) still returns 400 "Trend history
isn't built for databases yet; today it covers repository analyses." (asserted by
`test_non_repo_kind_gets_honest_400_naming_the_kind[trend-*]`, and 404-for-unknown-slug names the
kind). Only the missing-parameter case changed, to 422.
