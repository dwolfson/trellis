# Documentation sources — "Declare and probe" (Slice 1) — implemented

**Scope:** Slice 1 of `BRIEF-DATABASE-DOCUMENTATION-SOURCES.md` ("the block, the source table, the
read-only probe with its states, the ExternalReference on publish"). Slices 2 ("Ingest and cite",
`doc_source_ingestion` + chat citations) and 3 ("Freshness", scheduled re-check + staleness) are
**not built here** — out of scope by the brief itself, left for separate future dispatches.

**Branch:** `re/doc-sources-declare-and-probe`, built in an isolated worktree
(`/Users/dwolfson/localGit/egeria-v6/trellis-re-doc-sources-slice1`), never in the shared checkout.

**Brief status at start:** `origin/main` (`a90ce17c`, PR #346 merged) did **not** yet carry
`docs/design-notes/BRIEF-DATABASE-DOCUMENTATION-SOURCES.md` — PRs #344/#345/#347 referenced in the
dispatch either hadn't landed or don't exist under those numbers on this fork. The brief existed
only on an unmerged branch (`re/brief-database-doc-sources`, commit `597e85be`, sitting in
`.claude/worktrees/wt-docsources` in the shared checkout — a design-only commit, no implementation).
Copied from there into this branch (`docs/design-notes/BRIEF-DATABASE-DOCUMENTATION-SOURCES.md`) so
this slice has its own copy of what it's implementing; flagging this gap per the dispatch's own
instruction rather than blocking on it.

## What was built

### Database AND filesystem, both — not scoped to database-only

The brief allowed scoping filesystem out for time. It turned out not to need scoping out:
`FileSystemEntity` carries the exact same `egeria_url`/`egeria_server`/`egeria_user`/
`egeria_password`/`egeria_asset_guid`/`display_name` shape `DatabaseEntity` does, so the entity
resolver in `web/routes/doc_sources.py` (`_resolve_entity`) and the publish hook in
`web/routes/filesystems.py` cost no extra design, only a second `if entity_type ==` branch and a
second publish-route hook. Both entity types are wired end to end.

### New registry table: `doc_sources`

`resource_explorer/registry.py` — one row per declared source, keyed `(entity_type, entity_slug)`
like `resource_tags`/`egeria_linkage_status` (no FK, since it spans two parent tables), added
additively (`CREATE TABLE IF NOT EXISTS` + a fresh index, same migration shape as `step_runs`'
`flow_run_id`/`dispatch_failed` columns). Ingestion columns (`ingested_pages`/`ingested_bytes`/
`ingested_at`) are declared now, unused, so Slice 2 is an ADD-only migration rather than a second
pass over this table.

CRUD: `add_doc_source`, `get_doc_source`, `list_doc_sources`, `record_doc_source_probe`,
`set_doc_source_egeria_ref`, `remove_doc_source`, `upsert_doc_source_from_egeria` (the read-back
upsert — matches on `egeria_external_ref_guid` first, falls back to `url`, so a repeat read-back of
the same reference never duplicates a row).

**One real bug found and fixed by its own test** (`test_upsert_from_egeria_matches_existing_local_
row_by_url`): the first version of `upsert_doc_source_from_egeria` returned `self.get_doc_source(...)`
from *inside* the `with self._conn() as conn:` block that had just written the update — reading the
row back before that write's own commit, so a matched existing row came back with its OLD (usually
empty) `egeria_external_ref_guid` rather than the one just set. Fixed by moving the read to after the
block exits (registry.py's own comment on the fix explains the general shape: `get_doc_source` opens
its own connection, so any early return inside a `with self._conn()` block races that connection's
commit).

### `resource_explorer/doc_source_probe.py` — the read-only reachability probe

Mirrors `credential_capability.py`'s posture and state vocabulary exactly, per the brief's "Reuse,
not rebuild": `reachable` / `needs_sign_in` / `not_found` / `blocked`, each its own predicate over
the response rather than a rung on a ladder. GET-only, a fresh `httpx.Client` per probe (no cookie
jar reuse across sources), body capped at 64 KB, 4s per-probe timeout (gate wants "within 5 seconds"
— set below that so a slow/unreachable host still reports inside the budget). `needs_sign_in` covers
both 401/403 *and* a redirect that landed somewhere that looks like a login page. Never raises —
every failure (timeout, DNS, TLS, connection refused, malformed URL) becomes `blocked` with `error`
set.

### `resource_explorer/doc_source_egeria.py` — the ExternalReference linkage

Reuses `egeria_publisher.py`'s `_publish_homepage_reference` pattern (same `ExternalReference::<url>`
qualified-name convention, so a homepage and a declared doc source pointing at the same URL resolve
to one Egeria element, not two) as a standalone module rather than a method on `EgeriaPublisher`,
since this is reached from `web/routes/doc_sources.py` directly, not from a repo survey publish.

- `publish_doc_source(source, asset_guid, ...)` — create-or-reuse + link. Best-effort: returns
  `{"ok": bool, "ref_guid": str, "link_guid": str, "error": str}` rather than raising, so one
  source's Egeria failure doesn't fail the resource's whole publish.
- `unpublish_doc_source(ref_guid, asset_guid, ...)` — detach then delete, **only the one GUID
  passed** (the brief's removal rule: "and only that one"). Tolerates a failed detach (still
  deletes) — a duplicate-link edge case must not lose the reference.
- `read_back_doc_sources(asset_guid, ...)` — every `ExternalReference` currently linked to the asset
  in Egeria, including one declared there by something else. This is the "a source declared in
  Egeria by someone else appears here too" read-back the brief asks for.

**A second real bug, found only by the live gate check, not by the mocked unit tests:**
`get_related_metadata_elements`'s actual response shape is `{"startingElement": ..., "elementList":
[{"element": {"elementGUID": ..., "elementProperties": {"propertiesAsStrings": {...}}}}], ...}` —
not a bare list, and not `{"elements": [...]}`, both of which the first version of
`read_back_doc_sources` guessed (the client's own docstring only sketches the response and doesn't
give this shape). The mocked test for this function had, naturally, mocked the same wrong shape it
was testing against, so it passed while the real call returned **0 references every time** — a
textbook find-absence-as-answer failure (green because the check never actually exercised the real
shape, not because the property held). Caught because the live gate check's own assertion is for
*presence* ("all three declared sources are visible... via Egeria's own API") rather than merely
"did not crash". Fixed in `doc_source_egeria.py` (see its inline comment) and the mocked test
(`test_read_back_extracts_url_and_label`) updated to the real, confirmed shape.

**A third finding, this one about pyegeria rather than this slice's own code:**
`_find_ref_guid`'s call to `AutomatedCuration.get_guid_for_name` — reused verbatim from
`EgeriaPublisher._find_element_guid`'s pattern — **hung indefinitely** during the first live gate
run (the process sat at ~0% CPU for minutes; killed by hand). This is the exact incident
`docs/process-model.md` §1.3 and this project's own memory already document (`resolve_question_guid()`
hanging 15+s inside `get_guid_for_name` → `nest_asyncio` → `run_until_complete`), reproduced fresh in
a brand-new call site. Per `feedback_pyegeria_gaps_tracking` policy this is **not** patched in
pyegeria itself — it's logged as a reproduction of a known gap, not a new one. What *is* fixed here
is RE's own containment: `_find_ref_guid` now runs the lookup through
`resource_explorer/concurrency.py`'s shared bounded pool (`run_sync(..., timeout=15.0)`), the same
containment every other pyegeria call site in this package already uses for exactly this failure
mode. On timeout the lookup is treated as "not found" (falls through to create a new
`ExternalReference` rather than reusing one) — consistent with this codebase's "on our failure to
establish something, run the step" rule (`credential_capability.py`'s module docstring), not a new
policy invented for this slice.

### `web/routes/doc_sources.py` — the API

- `GET /api/doc-sources/{entity_type}/{slug}` — list, with a best-effort Egeria read-back folded in
  first (`_sync_egeria_read_back`) and `published`/`publish_note` from `egeria_linkage.
  describe_publish_status` (the same function the linkage-staleness banner already uses, so a stale
  link reads the identical sentence here as everywhere else in the app, not a second copy of that
  wording).
- `POST /api/doc-sources/{entity_type}/{slug}` — declare + probe immediately (the brief's step 2),
  synchronous, so the response already carries the probe result.
- `POST /api/doc-sources/{entity_type}/{slug}/{source_id}/recheck` — re-probe.
- `DELETE /api/doc-sources/{entity_type}/{slug}/{source_id}` — remove the row and (best-effort)
  detach/delete its ExternalReference, only that one.
- `publish_local_doc_sources(entity_type, slug, asset_guid, registry=...)` — not a route; called
  from `databases.py`'s and `filesystems.py`'s existing `/publish` routes right after a successful
  publish, publishing every locally-declared source with no `egeria_external_ref_guid` yet. Skips
  sources already published (idempotent across repeat publishes). Best-effort per source — one
  source's Egeria failure does not fail the database/filesystem's own publish.

### Frontend: `stages/enrichment.js`

A **Documentation sources** block, rendered inside `#enrichment-form` (below the Observations
section) only when `state.resourceType` is `db` or `filesystem`. Per source: reachability glyph +
label + HTTP status + fetch time + probed-when, re-check and remove actions, and (per source) an
**ingest** button that is present but disabled ("ingest — coming soon") — the brief's third
allowed choice for the Slice-2 affordance, so that slice has a known place to attach rather than
inventing UI from nothing. The block header states "local only" verbatim when the resource isn't
published, or the exact `egeria_linkage` stale-link sentence when it is published-but-stale — never
a generic "not published" that would collide with the per-field copy already used elsewhere on the
page.

`re-api.js` gained `getDocSources`/`addDocSource`/`recheckDocSource`/`removeDocSource`, following
the file's existing `apiEntityType(state.resourceType)`-generic convention every other
database/filesystem-aware call already uses.

`tailwind-next.css` rebuilt (`npm run build:css:next`) for the new classes — kept to the existing
`state-ok`/`state-warn`/`state-gap` tokens (there is no `state-error` token in
`tailwind-next.config.js`; an earlier draft used one that doesn't exist and was fixed before commit).

## What was deliberately deferred

- **Ingestion** (`doc_source_ingestion`, budgets, `step_runs` cost, pgvector writes) — Slice 2.
  Nothing here reads page content beyond title + byte count, per the brief's own step 2.
- **Chat citations / "documentation says" lines on Answering-Analysis questions** — Slice 2.
- **Scheduled re-check / staleness marking** — Slice 3. `re-check` here is a manual, on-demand
  action only.
- **A dedicated "unpublish" action for databases/filesystems.** None exists in this codebase today —
  publishing is currently one-way from the UI (grep confirms no `unpublish` route for either entity
  type; the only "unpublish"-named code is Survey Definition publish/unpublish and Egeria-linkage
  discard, a different feature). The "local only" state is driven entirely by
  `egeria_linkage.describe_publish_status`'s existing `is_published` rule (no cached GUID, or a GUID
  that's `stale`), which is exactly what the linkage-staleness feature already uses for the same
  question elsewhere in the app — so this slice adds no new "is it published" logic, it reuses the
  one that exists. The live gate check (below) demonstrates "local only" by clearing the cached GUID
  directly via the registry, the nearest existing analog to an unpublish action, and documents this
  as the judgment call it is rather than building a new unpublish surface as a side effect of this
  slice.

## Tests

**Python — 46 new tests, all passing, 0 regressions in the areas touched:**

- `tests/test_doc_source_probe.py` (12) — all four probe states (`reachable`/`needs_sign_in` via
  401/403/login-redirect/`not_found`/`blocked` via 5xx/timeout/connection-error/unexpected
  exception), the body-read cap, and "never raises".
- `tests/test_doc_sources_registry.py` (11) — add/list/scope-by-entity, probe-result write, removal
  returning the deleted row, and the Egeria read-back upsert (new row / matched-by-url / matched-by-
  guid / no duplicate on repeat).
- `tests/test_doc_source_egeria.py` (14) — publish (create new / reuse existing / no-url / Egeria
  unreachable), unpublish (detach+delete / no-op on empty guid / tolerates a failed detach / "only
  this one GUID" pinned by signature inspection), and read-back (unreachable → `[]`, extraction —
  updated to the real confirmed response shape after the live gate check found the bug above).
- `tests/test_doc_sources_routes.py` (16) — full route-level coverage via `FastAPI TestClient` with
  the same registry-sharing fixture pattern `test_databases_egeria_surveys.py` established
  (`ProjectRegistry.__init__` monkeypatched to share one test registry's `__dict__`): add+probe for
  all four states, 400 on a non-http URL, 404 on an unknown database, `published`/`local only`
  transitions, the Egeria read-back folding an Egeria-only source into the list with `origin:
  "egeria"`, re-check, and removal (local-only, and detaching/deleting only its own
  `egeria_external_ref_guid`).

Full suite (`uv run pytest tests/ -q -rf`, against the shared Postgres registry): first full run
was **6820 passed, 102 skipped, 2 failed** — both failures in
`tests/test_no_silent_success.py::TestRatchet`, a codebase-wide AST-based ratchet that flags any
new/grown "broad `except Exception`, log-only body, function still returns a value" site (the
shape behind two real historical bugs — see that file's own docstring). This slice's new code
tripped it at five sites. Two were genuine gaps, fixed for real (option 1 of the test's own three
prescribed fixes — "record something observable in the handler"): `doc_source_egeria.py`'s
`publish_doc_source`/`unpublish_doc_source` each had an inner `try/except` around the
link/detach call whose body only logged — now each assigns the caught exception into an
`error`/`detach_error` field the caller can see, so a link or detach failure is visible on the
returned dict rather than indistinguishable from a clean success. The remaining three
(`doc_sources.py::add_doc_source`'s best-effort activity-log write, and the new best-effort
`publish_local_doc_sources` call wrapped in each of `databases.py::publish_database_survey` and
`filesystems.py::publish_survey_to_egeria`) are the identical, already-accepted "must not fail the
primary operation over a non-critical side write" shape this codebase's own precedent already
baselines twice in `databases.py::publish_database_survey` and once in
`egeria_publisher.py::_publish_homepage_reference` (the very function this slice's Egeria-linkage
code was modeled on) — added to `tests/no_silent_success_baseline.json` as the deliberate,
reviewed decision the test's own option (3) asks for, not silently ignored. Re-run after both
fixes: `test_no_silent_success.py` — 9 passed, 0 failed. A second full-suite run confirmed
**6822 passed, 102 skipped, 0 failed** (13m17s) — clean, no regressions anywhere else in the suite.

**JS render harness (`frontend-build/test-harness/doc-sources-enrichment.test.mjs`, 6 tests, all
passing) — per the 2026-09 harness-regression rule** ("every `/next` fix from here on adds its
regression to the harness, not only a source-text test — also applies to new features"):

1. A declared source renders its reachable state, HTTP status and fetch time, and "local only" when
   unpublished.
2. `needs_sign_in`/`not_found` render their own glyph/label, not "reachable".
3. A published resource shows no "local only" note.
4. A stale-linkage publish note (`egeria_linkage`'s own sentence) is shown verbatim.
5. **The re-check button re-fetches and the row reflects the NEW probe state after a SECOND
   render** — the harness's whole reason for existing (see its own header comment): asserts what
   survives a second render, not just the first, the same class of check that caught the
   engine-note-persistence and Schema-Inventory-filter bugs it was built for.
6. The ingest action is present but disabled.

Building this test found two harness-usage bugs worth recording for the next person who writes one
in this file (both fixed in `dom-harness.mjs`/this test, not pre-existing harness bugs):
`makeDomEnvironment()` installs its own loudly-failing `fetch` stub, so a test's own `stubFetchJson`
call must run *after* `setUpEnrichmentDom()`, never before, or the environment's stub clobbers it;
and a module imported via `loadAppModule()`'s cache-busted specifier is a **different module
instance** than the one `enrichment.js`'s own plain `import ... from '/static/next/app.js'`
resolves to, so mutating `state` on the former is invisible to code driven through the latter — this
test imports the plain specifier directly instead (`dom-harness.mjs` gained an exported
`ensureLoaderRegistered()` so a test can do that without going through `loadAppModule()` first).

## Live gate verification

Run against the **real shared Postgres registry** (`localhost:5442`) and the **real Egeria
platform** (`localhost:9443`, `qs-view-server`), on `laz_local_adventureworks` — not the shared
`8810` web process (a scratch script instead, calling the same registry/probe/egeria functions the
routes call, per this session's coordination posture). No outbound internet is reachable from this
sandbox (confirmed: a direct `probe()` against `httpstat.us` timed out after 4s three times in a
row), so the three probe targets were served by a local fixture HTTP server on an ephemeral
`127.0.0.1` port instead of real external URLs — still a real HTTP round trip and real state
detection through the unmodified `doc_source_probe.probe()`, just not across the internet.

**Step 2 — add + probe three sources, gate: "each shows its state within five seconds with the
status code":**

| label | path | state | HTTP status | elapsed_ms |
|---|---|---|---|---|
| reachable | `/ok` | `reachable` | 200 | well under 5000ms (per-probe timeout is capped at 4000ms) |
| not_found | `/missing` | `not_found` | 404 | ″ |
| needs_sign_in | `/private` | `needs_sign_in` | 401 | ″ |

All three passed the `<5s` assertion; exact per-probe `elapsed_ms`/title were printed live and are
well inside budget (a localhost fixture server, so timings are not representative of a real remote
host, but the state/status-code detection logic is the same code path either way).

**Step 3 — publish `laz_local_adventureworks` for a real `asset_guid`:** published via the same
`EgeriaDatabaseSurveyor.publish_local_survey` the production `/publish` route calls, using the
database's own stored survey (57 local surveys already on file) and credentials. Real asset_guid:
`fc4e0478-4efe-4a29-bd1a-01b5bcb4a61b`.

**Step 4 — publish the three declared sources as ExternalReferences:** all three `ok: True`, each
returning a real `ref_guid` and `link_guid` from the live platform. (First attempt hung inside
`AutomatedCuration.get_guid_for_name` — see the pyegeria finding above; re-run after the
`run_sync(timeout=15.0)` fix completed in ~14s for all three.)

**Step 5 — read back via Egeria's own API (`read_back_doc_sources` against the real asset):** all
three declared sources' URLs confirmed present as `ExternalReferenceLink`-connected
`ExternalReference` elements — this is the "publish the resource and see the ExternalReference
appear in Egeria" gate, verified via Egeria's own `get_related_metadata_elements`, not RE's own
cached copy of what it thinks it published. (First attempt returned 0 references — the response-
shape bug above; re-run after the fix found all three.)

**Step 6 — "unpublish" (simulated by clearing the cached `asset_guid`, per the "what was deferred"
note above):** `describe_publish_status` → `is_published: False`, confirming the Enrichment block
would render "local only". The real Egeria publish was then restored (not left cleared) — a
legitimate outcome for the shared gate database other sessions may want, not test clutter to tear
down, per this session's coordination posture on shared infrastructure.

**Cleanup:** all three gate-check `doc_sources` rows removed locally, and confirmed **0** remaining
`ExternalReference`s for the asset via a fresh Egeria read-back — removal deletes exactly what it
created and nothing else, verified independently rather than trusted from the removal call's own
return value.

## Judgment calls and gaps flagged

1. **Both entity types built, not just database** (see above) — no scoping-out needed.
2. **No dedicated "unpublish" UI action exists or was built** — "local only" is driven by the
   existing `egeria_linkage` publish-status rule; the gate demonstrates it via the nearest existing
   analog (clearing the cached GUID) rather than inventing a new unpublish surface as a side effect
   of this slice. If a real "unpublish a database/filesystem" action is wanted, that's its own
   design question, not something to retrofit here.
3. **Ingest affordance:** built as a visible, disabled "coming soon" button rather than omitted —
   the brief allowed either; this seemed cleaner for Slice 2 to attach to.
4. **Two real bugs found by testing this slice's own new code, not by chance:** the
   commit-ordering bug in `upsert_doc_source_from_egeria` (caught by a unit test) and the
   `get_related_metadata_elements` response-shape bug in `read_back_doc_sources` (caught only by
   the live gate check — the mocked unit test for the same function had mocked the same wrong shape
   it was testing, and passed). Both are fixed; the mocked test is updated to the now-confirmed real
   shape so it can't silently regress back to the wrong assumption.

   **New rule (design session, 2026-09-29), from this exact miss:** mocks of pyegeria response
   shapes must be captured from a real response and stored as fixtures under
   `tests/fixtures/pyegeria/`, never hand-written from memory or documentation — a hand-written
   mock can encode the same wrong assumption the code under test makes, and then agrees with it.
   This slice's own `read_back_doc_sources` test now follows that rule. A sweep of this codebase's
   existing hand-written pyegeria mocks against this rule is logged as a small follow-up slice in
   `docs/Backlog.md`, not done here.
5. **A reproduction, not a new instance, of the documented pyegeria `get_guid_for_name` hang** —
   contained the same way every other call site in this package already contains it
   (`concurrency.run_sync` with a timeout), not patched upstream, per the standing
   `feedback_pyegeria_gaps_tracking` policy. This is at least the **third** live reproduction (the
   two 2026-09-04 RE server-stuck incident dumps, and this one, 2026-09-29) — logged with that count
   against `PYEGERIA_ISSUES.md`'s ISSUE-96, the closest existing entry for this cross-thread/
   event-loop hazard (ISSUE-96 itself describes the exception-raising symptom of the same defect;
   this is the hang-instead-of-raise symptom).
6. **No internet access in this sandbox** — the three-URL live check used a local fixture server
   rather than real external URLs (e.g. real "needs sign-in" wiki pages). The probe logic itself is
   unchanged by that substitution (same HTTP client code path, same state-classification code), and
   the four-state classification is independently pinned by the twelve unit tests in
   `test_doc_source_probe.py` against a broader range of real HTTP status codes/timeouts than three
   URLs would exercise anyway.
