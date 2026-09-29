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

## Source-kind vocabulary expanded (2026-09-29)

The original five kinds (`data_dictionary`, `design_notes`, `runbook`, `wiki`, `other`) came
straight from `BRIEF-DATABASE-DOCUMENTATION-SOURCES.md` and shipped as-is in this slice. During the
live gate check on database 8813 (2026-09-29) the project owner asked for two more: **Installation
Guide** and **User Manual** — real doc kinds people were declaring that had nowhere to go but
"other". While touching this vocabulary, design's decision was to also add **API Reference** and
**Release Notes**, rather than expand it again for the next obvious gap.

Final nine-kind vocabulary, same `snake_case` value / lowercase display-label convention the
original five already used:

`data_dictionary`, `design_notes`, `runbook`, `wiki`, `installation_guide`, `user_manual`,
`api_reference`, `release_notes`, `other`.

Three places carry this list, kept in sync by hand (no shared source of truth — the frontend
`<select>` needs display labels, the two backend spots need different label strings, so a single
shared constant would still need per-consumer label maps):

- `resource_explorer/registry.py`'s `ProjectRegistry.DOC_SOURCE_TYPES` — validates `add_doc_source`,
  falling back to `"other"` for anything not in the tuple (unchanged behavior, now checked against
  nine values instead of five).
- `resource_explorer/doc_source_egeria.py`'s `_SOURCE_TYPE_LABEL` — the label baked into the
  Egeria `ExternalReference` body on publish.
- `resource_explorer/web/static/next/stages/enrichment.js`'s `DOC_SOURCE_TYPES` — the `<select>`
  options a person picks from when declaring a source, and the label shown on each declared-source
  row.

Pinned by `tests/test_doc_sources_registry.py::test_doc_source_types_vocabulary` (the tuple),
`tests/test_doc_source_egeria.py::test_source_type_label_covers_the_full_vocabulary` (the label
map), and `frontend-build/test-harness/doc-sources-enrichment.test.mjs`'s "source-kind dropdown
offers all nine declared kinds" test (the rendered `<option>` set) — so a future edit to any one of
the three that drops or renames a value fails a test rather than silently drifting from the others.

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

## Egeria publish-state fix (2026-09-29)

Found live by the project owner's gate check on database 8813: adding a documentation
source to an ALREADY-published resource never reached Egeria at all — the row stayed
`origin: local`, `egeria_external_ref_guid: ''`, and the Enrichment header rendered
`"1 declared ·"` with nothing after it, regardless of whether the source had actually
been catalogued. Two separate bugs, both real:

**(a) Semantic gap.** `add_doc_source` (`web/routes/doc_sources.py`) only ever probed
and saved a source LOCALLY. The only path that ever created an `ExternalReference` was
`publish_local_doc_sources`, called exclusively from the database/filesystem `/publish`
routes right after a successful publish — so a source declared AFTER the resource's own
publish had no path to Egeria until the resource's NEXT full re-publish, which may never
happen.

**(b) Silent absence.** `enrichment.js` rendered `publishNote = ''` whenever `data.
published` was true, with no per-row signal at all — a textbook find-absence-as-answer
bug (this project has a standing convention against exactly this shape; see
`credential_capability.py`'s "connected as X — visible N of M schemas" and
`db_resilience`'s explicit "not machine-observable, stays explicitly pending" states,
both cited as the reference examples in the fix brief).

### The fix

**Backend — reuse the existing outbox, not a new retry queue.** Grepped for `outbox`
across `resource_explorer/` per the brief's own instruction; `egeria_outbox.py` (design:
`docs/outbox-publishing-design.md` §5) already implements exactly the local-authoritative-
write / best-effort-remote-sync / periodic-reconcile shape this needed — the same layer
this project's memory notes as the one whose `collection_manager` client went missing in
the 2026-09-04 RE server-stuck incident. Two new `element_kind`s were added to it:

- `doc_source_publish` — resolves the entity and the local `doc_sources` row FRESH at
  apply time (never carries Egeria credentials in the payload, which would go stale if
  the entity's credentials were edited between enqueue and a retry), calls
  `doc_source_egeria.publish_doc_source`, and writes the resulting ref/link GUIDs straight
  back onto the local row. This creator is the ONLY thing that runs for this kind — see
  below for why.
- `doc_source_unpublish` — same shape, calls `unpublish_doc_source` for exactly the one
  GUID a removed row carried, same "and only that one" rule the brief already established.

**A real correctness trap found while wiring this in, before it shipped:** the outbox's
existing `apply_element` has a generic step 2 — search by `qualified_name` before
creating, so a crash-after-Egeria-write-before-recording converges on the existing element
rather than duplicating it. `doc_source_publish`/`doc_source_unpublish` use the exact same
`ExternalReference::<url>` qualifiedName convention `egeria_publisher._publish_homepage_
reference` already uses for a project's homepage — meaning the generic search could find
a homepage reference (or a leftover row from an unrelated retry) with the SAME
qualifiedName and adopt its GUID as `done`, without EVER calling `publish_doc_source`'s own
link step. The row would report catalogued while never actually being linked to THIS
resource's asset — invisible until someone went looking for the link in Egeria itself.
Fixed by adding a `_SELF_RESOLVING_KINDS` set (`{"doc_source_publish",
"doc_source_unpublish"}`) that `apply_element` now skips the generic step-2 search for —
these creators already do their own correct lookup-then-create-then-link (mirroring
`_publish_homepage_reference`'s own local pattern exactly), so the generic shortcut would
only ever be a liability for them. Pinned by
`test_generic_lookup_is_never_consulted_for_doc_source_publish`, which passes a
`find_element_guid` that raises `AssertionError` if it is ever called.

**Routes.** `add_doc_source` and the DELETE handler no longer call `publish_doc_source`/
`unpublish_doc_source` synchronously — the DELETE handler used to (a one-shot best-effort
attempt with no retry if Egeria happened to be unreachable at that exact moment); both now
enqueue through the outbox. `_compute_egeria_state` (new, `web/routes/doc_sources.py`) is
the one place that decides a row's state and self-heals a gap: if the resource is
published, the row has no ref guid, and NO outbox row is tracking it at all — a source
declared before this fix landed, exactly the adventureworks row found live — it queues the
missing publish right there rather than leaving the row unexplained forever. Idempotent:
once queued, the next call finds the row and stops re-queuing.

### Immediate attempt on enqueue, 15 minutes is the retry fallback, not the happy path (round 3, 2026-09-29)

The first version of this fix (above) only ever ENQUEUED a `doc_source_publish`/
`doc_source_unpublish` row and left it for `scheduler.py`'s existing drain loop
(`_CHECK_INTERVAL_SECONDS = 900`) to pick up — so a source declared on an
already-published resource could sit `local — publishing…` for up to 15 minutes even
when Egeria was perfectly reachable at the moment of the add. Design's original spec
was "publish at once (best effort), through the existing outbox so a transient failure
retries" — attempt immediately, fall back to the 15-minute loop only if that immediate
attempt fails. Round 2 shipped only the fallback half.

**The fix.** `registry.claim_due_outbox_elements()` gained an `element_id` parameter that
scopes a claim to exactly one row (in addition to the existing `run_id` scoping, which
isn't precise enough here — doc-source publish/unpublish rows carry no `run_id`, so a
`run_id`-scoped claim could still sweep in unrelated rows). `drain_outbox()` threads
`element_id` straight through to it; `drain_outbox_row(registry, element_id)` is a thin,
named wrapper over `drain_outbox(..., element_id=...)` for callers that want "attempt this
one row now" without spelling out `limit`/`run_id`. **This is the same drain the
scheduler's own unscoped loop calls** — apply, retry bookkeeping, backoff, dead-lettering,
and `record_drain_outcome` are all identical; `element_id` only narrows which row
`claim_due_outbox_elements` is willing to claim, so a scoped call behaves exactly like the
full drain would have behaved on that one row, including leaving a failed attempt for the
normal 15-minute retry with its own backoff — nothing about this path is a separate
mechanism to keep in sync.

`web/routes/doc_sources.py`'s `add_doc_source` (via `_compute_egeria_state`'s self-heal
branch, which is also what `add_doc_source` itself goes through) and the DELETE handler
now call `_attempt_outbox_row_immediately(element_id)` right after enqueueing — a plain
`threading.Thread(daemon=True)` (the same fire-and-forget shape `worker.py`/`rag_system.py`
already use elsewhere in this codebase) that builds its own `ProjectRegistry()` and calls
`drain_outbox_row`, off the request thread so the HTTP response is never blocked on an
Egeria round trip. `drain_outbox`/`drain_outbox_row` never raise (every failure already
routes through `mark_outbox_failed`/dead-lettering), so the background thread cannot crash
the process, and a failure inside it never reaches the add/remove request — the row is
simply left exactly where the normal 15-minute scheduler drain would find and retry it.

**Updated timing language:** on success, a source declared on an already-published
resource reads `catalogued in Egeria` within a few seconds of the add — the time for one
outbox apply against a reachable platform, not a scheduler cycle. The 15-minute interval
is the fallback/retry cadence for when that immediate attempt fails (Egeria unreachable,
timeout, or any other transient error) — not the expected happy-path latency it read as
after round 2.

**Restart safety (design's caution, confirmed 2026-09-29):** the daemon thread that makes
the immediate attempt dies with the process — an add made seconds before a server restart
loses that in-flight attempt and relies on the normal 15-minute scheduler retry to catch it
instead. This is acceptable because the row's state is not held in the thread or in memory
at all: `egeria_outbox` is a real Postgres/SQLite table (`CREATE TABLE IF NOT EXISTS
egeria_outbox`, `registry.py`) with a persisted `status` column (`pending`/`running`/
`failed`/`dead`). A source's row correctly continues to read `local — publishing…` across
a restart, and the scheduler's own drain loop picks the row back up exactly as it would for
any other pending element — no special-casing needed, and nothing is lost or silently
stuck.

### The four states — never empty

`DocSourceOut.egeria_state` (one of `catalogued` / `publishing` / `publish_failed` /
`local_only`) plus `egeria_state_detail` (the ref GUID, or the real failure reason) ride on
every source row from `GET`/`POST add`/`POST recheck`:

1. **`catalogued in Egeria`** — `egeria_external_ref_guid` is set; the GUID is surfaced via
   a `title` attribute on the row rather than cluttering its own text line.
2. **`local — publishing…`** — resource published, no ref guid, an outbox row is
   `pending`/`running`.
3. **`local — publish failed: <reason>, retrying`** — the outbox row is `failed` (still
   retrying) or `dead` (retries exhausted); `<reason>` is the outbox row's own
   `last_error`, never a generic message. A `dead` row gets the same wording rather than a
   fifth state of its own — it is also reported to a human via the outbox's existing
   `record_drain_outcome` → RFA path, which this fix gets for free by reusing the same
   drain.
4. **`local only — resource not published`** — the original design, unchanged: a source
   declared before the resource's first publish stays local until that publish, same as
   before this fix.

`DocSourcesResponse` also carries `in_egeria_count`/`local_count`, computed server-side
(the one place that knows what the four states mean is also the one place that counts
them) — the header now reads `"N declared · X in Egeria · Y local"` instead of the old
blank-when-published `publishNote`. A resource-level stale-linkage warning (from
`egeria_linkage.describe_publish_status`) is kept as a separate second line, since it is a
fact about the resource's own Egeria asset link, not about any one source.

### Tests

**Python (all passing, run via `uv run pytest tests/ -q -rf`):**

- `tests/test_egeria_outbox.py::TestDocSourceOutbox` (6 new) — the publish creator writes
  the ref guid back onto the local row; the generic step-2 lookup is never consulted for
  this kind (poisoned-lookup test); a publish failure raises `OutboxApplyError` so the
  drain retries; a source removed before its queued publish drains is a no-op (never calls
  Egeria); the unpublish creator detaches+deletes exactly the one GUID; an unpublish
  failure raises so the drain retries.
- `tests/test_doc_sources_routes.py::TestEgeriaPublishStateFix` (5 new) — add on an
  ALREADY-published resource queues an outbox publish and returns `egeria_state:
  "publishing"`; add on an UNPUBLISHED resource stays local and queues nothing; `GET`
  reports `catalogued` with the guid once set; `GET` reports `publish_failed` with the
  REAL `last_error` text; `GET` self-heals a row stranded by the pre-fix bug (published,
  no ref guid, no outbox row — exactly the adventureworks shape found live) by queuing the
  missing publish.
- `tests/test_doc_sources_routes.py::TestRemoval` — the one existing test that asserted a
  synchronous `unpublish_doc_source` call was rewritten (`test_remove_of_a_catalogued_
  source_queues_an_outbox_unpublish`) to assert the outbox row instead, since that
  synchronous call no longer exists; a paired `test_remove_of_a_local_only_source_queues_
  nothing` covers the other branch.
- Full suite: **see the run this session reports directly** (ran via `uv run pytest
  tests/ -q -rf` against the shared Postgres registry, same as slice 1's own baseline of
  6822 passed / 102 skipped / 0 failed).

**Round 3 (2026-09-29) — immediate attempt on enqueue:**

- `tests/test_egeria_outbox.py::TestElementScopedDrain` (4 new) — `claim_due_outbox_
  elements(element_id=...)` takes only that row, leaving a sibling row untouched;
  `element_id` still respects the ordinary due-gate (a row whose backoff hasn't elapsed
  stays out of scope even when named explicitly); `drain_outbox(..., element_id=...)`
  applies only the named row and leaves the rest of the outbox alone; `drain_outbox_row`
  is confirmed to be the exact same mechanism as the scheduler's own unscoped drain (a
  failure inside it goes through the identical `mark_outbox_failed` bookkeeping, leaving
  the row for the normal retry rather than a special-cased failure path).
- `tests/test_doc_sources_routes.py::TestImmediateOutboxAttempt` (3 new) — add on an
  already-published resource triggers a scoped drain of EXACTLY the row it just enqueued
  (proven via a `threading.Thread` test double that runs the target synchronously, so the
  assertion isn't racing a real background thread); remove of a catalogued source triggers
  the same for its unpublish row; and — the fallback contract — a failing immediate attempt
  does not fail the add request itself and leaves the row `pending`/`running`, exactly
  where the normal 15-minute scheduler drain will find and retry it.

**JS render harness (`frontend-build/test-harness/doc-sources-enrichment.test.mjs`):**

- `test('each of the four Egeria publish-state rows renders its own required wording
  (2026-09-29 fix)')` — fixture rows in all four states, asserts each one's exact rendered
  text (including the real failure reason interpolated into state 3, not a placeholder),
  the ref-guid `title` attribute on the catalogued row, and the header's three counts.
- The pre-existing `'a published resource shows no "local only" note'` test was updated
  (renamed `'a published, catalogued source shows no "local only" note...'`) to set an
  explicit `egeria_state: 'catalogued'` on its fixture row — under the old code a
  published-but-stateless fixture row rendered nothing either way, so the old assertion
  was accidentally passing for the wrong reason; the new fixture makes the row's own state
  the thing under test.
- Full harness run (`node --test test-harness/*.test.mjs`, Node 20 — the environment's
  default `node` on `PATH` is v14.21.3 via nvm and lacks `--test`, so this needs
  `/usr/local/bin/node` explicitly): **21 passed, 0 failed**, no regressions.

### Live verification

Ran a scratch script (not the shared 8810/8813 web process — calling the same registry/
outbox/egeria functions the routes and the scheduler call, same posture slice 1's own gate
check used) against the REAL shared Postgres registry (`localhost:5442`) and the REAL
Egeria platform (`localhost:9443`, `qs-view-server`), on `laz_local_adventureworks` — the
same resource slice 1's gate check used, confirmed still published
(`fc4e0478-4efe-4a29-bd1a-01b5bcb4a61b`):

1. Declared a source as if the resource were already published (`add_doc_source`, no
   outbox row yet) — `_compute_egeria_state` (the exact function the routes call)
   self-healed by queuing a `doc_source_publish` row; state read `publishing`.
2. Ran `drain_outbox(registry)` for real — hit the live Egeria platform. The outbox row
   completed; the local row's `egeria_external_ref_guid` and `egeria_link_relationship_
   guid` were written back; `_compute_egeria_state` now read `catalogued`.
3. Confirmed via Egeria's OWN API (`read_back_doc_sources` → `get_related_metadata_
   elements`), not RE's cached copy — the declared URL was present.
4. Removed the source (`remove_doc_source`) and queued a `doc_source_unpublish` row
   (`enqueue_doc_source_unpublish`) — the same outbox mechanism, not a synchronous call.
5. Ran `drain_outbox(registry)` again for real — the unpublish completed.
6. Confirmed via Egeria's OWN API again — the URL was gone.

All six steps passed on the first run, no cleanup residue left behind (the local row was
already deleted by step 4; the outbox rows are `done` and will clear on the existing
14-day retention like every other outbox row).

**What was NOT verified live (round 2 claim, corrected round 3, 2026-09-29):** this
section originally said all three shared databases were already published, so
`local_only`'s live equivalent could only be exercised by deliberately unpublishing one —
"a real, and needlessly risky, mutation of shared infrastructure." That premise was wrong.
It came from reading a cached/raw Egeria GUID as "published" rather than routing through
`egeria_linkage.describe_publish_status` (the staleness-aware check `_compute_egeria_state`
above actually uses, and always did — `_compute_egeria_state`'s `is_published` parameter is
supplied by `_publish_status()`, which calls `describe_publish_status` directly; there was
no raw-GUID bug in the row logic itself, only in this doc's own live-verification claim
about the registry's state).

A fresh `describe_publish_status` check (2026-09-29, PR/CI review of this round) against
the real shared registry and the real Egeria platform found:

- `laz_local_adventureworks` — GUID present, `is_published: True`.
- `localhost_docker_coco_pharma` — GUID present, `is_published: **False**` —
  `"published to Egeria · link stale since 2026-09-26 · last checked 2026-09-29 — element
  not found"`.

So `coco_pharma` genuinely IS the live `local_only` case design's gate intended, and has
been since 2026-09-26 — the doc's own claim that "every database is already published" was
stale (or wrong) at the time it was written, not something that changed since. This is a
live-demonstrable case, not harness-only: declaring a documentation source against
`coco_pharma` today exercises the real `local_only` path end to end, no manufactured
unpublish needed. Covered at the unit level regardless by `test_add_on_an_unpublished_
resource_stays_local_and_queues_nothing` and the pre-existing `test_local_only_when_not_
published`, both of which still pass.

**`publish_failed`/`dead`** were verified only via the mocked route test
(`test_list_reports_publish_failed_with_the_real_reason`) and the outbox's own existing
backoff/dead-letter tests (`TestBackoffAndDeadLettering`, unchanged by this fix, still
passing) — reproducing a real Egeria failure live would need either breaking the platform
or forging bad credentials against a shared resource, neither of which seemed like a
reasonable price for this fix's own test to pay.

## Adoption race + dishonest state + missing UI refresh (round 4, 2026-09-29)

Found live by the project owner's re-gate on database 8813, with real registry + Egeria
evidence (timeline, UTC):

- **15:17:34** — publish created `ExternalReference` `b9925119…` for `https://egeria.ai`.
- **15:21:41** — the owner removed that source → an outbox row (`doc_source_unpublish` for
  `b9925119…`) enqueued, `done` at 15:21:44 (reference deleted in Egeria).
- **15:21:42** — WHILE that unpublish was in flight, the owner added a DIFFERENT source
  ("not-adventureworks", `installation_guide`, **same URL** `https://egeria.ai`). Its row
  ended up with `egeria_external_ref_guid = b9925119…` — the SAME reference being
  concurrently deleted — and `egeria_link_relationship_guid` EMPTY, with **no
  `doc_source_publish` outbox row ever created for it**. It stayed stuck reading "local —
  publishing…" for minutes with nothing actually pending or running.
- A clean retry ("pdr", `https://pdr-associates.com`, 15:24:15) proved the SERVER side then
  worked correctly in isolation — ref+link created, outbox row `done` in ~4s — but the PAGE
  still showed "local — publishing…" indefinitely: a third, independent defect (no refresh
  after the background drain completes).

### Root cause 1 — the adoption race: matching key is the URL/qualifiedName

Confirmed against the real registry rows for both sources, not guessed: **the two sources
shared the exact same URL**, `https://egeria.ai` (different label and `source_type`, same
URL). The adoption happens in `web/routes/doc_sources.py`'s `_sync_egeria_read_back` →
`registry.upsert_doc_source_from_egeria`, whose `url` fallback match key is precisely
`ExternalReference::<url>` — the same convention `_qualified_name()`
(`doc_source_egeria.py`) and `_find_ref_guid`'s `AutomatedCuration.get_guid_for_name` lookup
both use. A `GET` (read-back) landing in the ~3-second window between the unpublish being
enqueued and its detach+delete actually completing in Egeria still sees the OLD reference as
a live `ExternalReferenceLink` on the asset — because it genuinely still is one, at that
instant. With no local row for that URL yet (the old row was already deleted, the new one
not yet declared), `upsert_doc_source_from_egeria` created a brand-new local row carrying the
being-deleted ref guid, and because that path never goes through the outbox, no
`doc_source_publish` row was ever queued for it — exactly what was observed live.

**Design's precise adoption rule** (design session, 2026-09-29): a read-back/reuse may adopt
an existing `ExternalReference` only when ALL of — it matches on (asset, URL); its
`ExternalReferenceLink` to THIS asset already exists (structurally true for anything
`read_back_doc_sources` returns, since that call is itself scoped to the asset's own
relationships); and no `doc_source_unpublish` row for it is `pending`/`running`. Anything
else is "not catalogued" and must get a fresh publish of its own.

**Fix — closes the race, not just narrows it:**

- `ProjectRegistry.has_pending_unpublish_for_ref(entity_type, entity_slug, ref_guid)`
  (`registry.py`) — the guard: true when a `doc_source_unpublish` outbox row targeting exactly
  this GUID is still `pending`/`running` for this entity.
- `_sync_egeria_read_back` (`web/routes/doc_sources.py`) — skips adopting any remote
  reference this guard flags, rather than writing a soon-to-be-invalid ref guid onto a local
  row at all. The next read-back (after the unpublish actually lands) sees the reference is
  genuinely gone and adopts nothing; a genuinely new source at the same URL gets its own
  independent, correctly-linked reference via the self-heal below.
- `doc_source_egeria.publish_doc_source` — hardened at the SAME hazard on its own path (not
  the one that fired in this incident, but the identical shape): `_find_ref_guid` matches by
  qualifiedName GLOBALLY, with no check on whether the match is mid-deletion. New
  `is_ref_unpublishing: Callable[[str], bool] | None` parameter — when the found (or a
  caller-supplied `known_ref_guid`) candidate is flagged by it, the candidate is abandoned and
  a fresh, independent `ExternalReference` is created instead of reusing one that may vanish
  out from under the new link. `egeria_outbox.py`'s `_create_doc_source_publish` supplies this
  as `registry.has_pending_unpublish_for_ref` bound to the entity — `doc_source_egeria.py`
  stays standalone (no registry import) per its own design, the caller with the registry
  provides the check.
- **A latent bug found while wiring this in, before it shipped:** `_create_doc_source_publish`
  used to short-circuit ("already done, nothing to write") on `egeria_external_ref_guid`
  ALONE — exactly the field the adoption race can set without ever linking. Re-queuing a
  publish for a ref-but-no-link row (the self-heal below) would have hit that short-circuit
  and returned immediately WITHOUT ever calling `link_external_reference` — defeating the
  self-heal for precisely the shape it exists to fix. Now short-circuits only when BOTH
  `egeria_external_ref_guid` AND `egeria_link_relationship_guid` are set; a ref-only row is
  passed through to `publish_doc_source` via a new `known_ref_guid` parameter, which links
  THAT reference (still subject to the same `is_ref_unpublishing` check) rather than minting a
  second, independent one for the same local row.

### Root cause 2 — dishonest state: a pure four-→-five-state function

`_compute_egeria_state` (round 1) trusted `egeria_external_ref_guid` alone as proof of
"catalogued" — which is also precisely what let an adoption-race row (ref guid set, never
linked) render as fully catalogued. Design asked for the fix to take a specific shape: a
small, PURE function — row facts in, state word out, no side effects, no branching on how the
row got there — so the vocabulary can't drift out of sync with reality again the way a bare
ref guid drifted into meaning "catalogued".

`derive_doc_source_egeria_state(*, ref_guid, link_guid, is_published, outbox_row)` (new,
`web/routes/doc_sources.py`) is exactly that function:

1. `catalogued` — `ref_guid` AND `link_guid` BOTH non-empty.
2. `local_only` — the resource itself isn't published (only reached once rule 1 doesn't hold —
   a genuinely complete ref+link still reads `catalogued` even if the publish-status flag is
   stale, same precedence the pre-fix code already had).
3. `publishing` — the outbox row is `pending`/`running`.
4. `publish_failed` — the outbox row is `failed`/`dead`; detail is the row's own `last_error`.
5. `not_catalogued` (**new**) — everything else, most notably `ref_guid` set, `link_guid`
   EMPTY, nothing pending/running. Rendered honestly ("local — not catalogued (publish
   needed)") instead of the old code's `publishing` with nothing backing that claim — a second,
   distinct find-absence-as-answer bug from the one round 1 already fixed (that one was about
   the header note being empty; this one is about the STATE WORD ITSELF being wrong).

`_compute_egeria_state` is now a thin orchestrator around the pure function, owning the one
side effect: self-healing. A row landing on `not_catalogued` while published with no outbox
row in flight means the add/read-back path missed enqueueing a publish for it — queued right
here, same as round 1's self-heal — and now **logged** (`log.warning`) when it fires, per
design's ask: self-heal firing means something upstream should have queued it already, which
is worth knowing about even though the recovery itself is graceful, not the expected steady
state.

`tests/test_doc_sources_routes.py::TestDeriveEgeriaStateTable` (13 new tests) is the required
table test, covering ref+link present/absent × every outbox status
(pending/running/failed/dead/done/none) plus the `is_published`-vs-`catalogued` precedence
case above.

### Root cause 3 — the page never refreshed after the background drain finished

The add/remove HTTP response necessarily reflects the PRE-drain state —
`_attempt_outbox_row_immediately` fires the real Egeria write on a background daemon thread
specifically so the request isn't held open for it. The gap: nothing EVER re-fetched
afterward. Live-verified with the "pdr" retry: the server-side drain completed in ~4s (ref +
link created, outbox row `done`, visible in Egeria within seconds) while the page kept
showing "local — publishing…" indefinitely, because no code path re-rendered the block once
that thread finished.

**Fix** (`web/static/next/stages/enrichment.js`) — polling, matching this codebase's existing
idiom for "started an operation off the request thread, need to reflect its own completion"
(`pollActivity`, `re-api.js`), rather than the alternative of having the add endpoint block on
the drain (rejected: it would reintroduce exactly the request-blocked-on-an-Egeria-round-trip
problem `_attempt_outbox_row_immediately` was built to avoid). `renderDocSources` was split
into a fetch step and `renderDocSourcesFromData` (render-only, reusable from a poll tick
without the "Loading…" flicker a full re-render would cause every 2s); whenever any row is
`publishing` after a render, `scheduleDocSourcesPoll` re-fetches the same `GET` every 2s,
capped at 30s total, re-rendering from each response until nothing is `publishing` anymore or
the cap is hit — at which point the block simply shows whatever real state the last fetch
returned (never spins forever on a row Egeria genuinely cannot reach). A fresh call to
`renderDocSources` (recheck/remove/add, or navigating to a different slug) cancels any poll in
flight from a prior render.

### Tests (round 4)

**Python** — 166 tests total in the doc-sources area now pass (up from the round-3 baseline),
run via `uv run pytest tests/test_doc_sources_registry.py tests/test_doc_source_egeria.py
tests/test_egeria_outbox.py tests/test_doc_sources_routes.py -q`. New:

- `tests/test_doc_sources_registry.py` (6 new) — `has_pending_unpublish_for_ref`: false with no
  rows, false for an empty guid, true when `pending`, true when `running` (via
  `claim_due_outbox_elements`), false once `done`, and scoped correctly to the right
  guid/entity (a pending unpublish for a different ref or a different entity doesn't count).
- `tests/test_doc_source_egeria.py` (5 new) — `publish_doc_source` does not reuse a found ref
  flagged by `is_ref_unpublishing` (creates fresh instead); reuse is unaffected when nothing
  flags it; a `known_ref_guid` links directly with NO `_find_ref_guid` lookup (poisoned-lookup
  test); a flagged `known_ref_guid` is abandoned, falling through to find-or-create.
- `tests/test_egeria_outbox.py::TestDocSourceOutbox` (3 new) — the publish creator
  short-circuits ONLY when both guids are already set (poisoned-`publish_doc_source` test); a
  ref-only row still calls `publish_doc_source` (with `known_ref_guid` threaded through) and
  the write-back sets both guids; the `is_ref_unpublishing` callback passed through is bound to
  the right entity (a pending unpublish for a different entity/slug does not flag a ref as
  unpublishing here).
- `tests/test_doc_sources_routes.py::TestDeriveEgeriaStateTable` (13 new) — the required pure-
  function table test, see above.
- `tests/test_doc_sources_routes.py::TestAdoptionRaceReadBack` (1 new,
  `test_a_get_landing_mid_unpublish_does_not_adopt_the_reference_being_deleted`) — reproduces
  the exact live timeline at the route/outbox level: a fully-catalogued source is removed
  (`_NeverStartsThread` keeps its `doc_source_unpublish` row deterministically `pending`, i.e.
  "still in flight"), a `GET` lands in that window with `read_back_doc_sources` stubbed to
  report the still-live reference (matching real Egeria behavior before the delete lands), and
  the new same-URL source is then declared. Asserts: the read-back adopts nothing (no local row
  at all right after the `GET`); the newly-declared source gets `egeria_external_ref_guid ==
  ""` and its OWN fresh `doc_source_publish` outbox row (never silently treated as
  already-published); and once the unpublish completes and Egeria's read-back correctly
  reports the reference gone, nothing is resurrected.
  - **Verified this test fails against pre-fix code**: stashed the round-4 source changes
    (keeping the round-4 test files), re-ran `TestAdoptionRaceReadBack` and
    `TestDeriveEgeriaStateTable` — all 14 failed, the race test specifically on
    `registry.list_doc_sources(...) == []` after the read-back (pre-fix code left the
    being-deleted reference adopted onto a ghost local row, exactly the live incident).
    Restored the fix; all 166 tests in the doc-sources area pass again.
- Full suite: **see this session's own report for the run this section doesn't duplicate.**

**JS render harness** (`frontend-build/test-harness/doc-sources-enrichment.test.mjs`, 10 tests
total, all passing via `/usr/local/bin/node --test`) — 2 new:

- `'the not_catalogued state (round 4, 2026-09-29) renders its own honest wording, never
  "publishing"'` — a fixture row with `egeria_state: 'not_catalogued'` renders "local — not
  catalogued (publish needed)" and neither "publishing" nor "catalogued in Egeria".
- `'a "publishing" row polls the GET endpoint and updates to catalogued without any user
  action (round 4, 2026-09-29)'` — a fixture starts `publishing`; `globalThis.fetch` flips to a
  `catalogued` fixture on the second call; `globalThis.setTimeout` is temporarily replaced with
  an immediate-firing version (the real 2s/30s budget would make a unit test slow); asserts the
  row updates to "catalogued in Egeria" with no click, no reload — nothing but the scheduled
  poll firing on its own. Full harness run: 24 tests, 0 failed, no regressions in the other
  three harness files.

### Does the fix close the race, or only narrow the window?

**Closes it.** The PR/CI notes mentioned the owner was separately re-trying the gate with a
manual pause between remove and add, to avoid triggering the race by hand — this fix makes
that pause unnecessary rather than only documenting it as a workaround. The guard
(`has_pending_unpublish_for_ref`) is checked inside the SAME transaction-scoped read that would
otherwise adopt or reuse a reference, not a time-based delay or a retry-until-safe loop — there
is no window during which an unsafe adoption can still slip through between the check and the
read-back's own upsert, because the check happens immediately before that upsert on every
single read-back pass, not once at some earlier point that could go stale. The remaining
theoretical edge (an unpublish enqueued but not yet WRITTEN to the outbox table at the exact
instant a concurrent read-back's guard-check runs) is not a race this fix can leave open by
construction, because `remove_doc_source`'s local delete and `enqueue_doc_source_unpublish`'s
outbox insert happen inside the same request before any response is returned — by the time a
client could possibly issue the racing `GET`, the outbox row already exists for the guard to
see.

### Re-gate scope (2026-09-29, confirmed by design)

Item 5 on `laz_local_adventureworks` only, covering all three of: add → "catalogued in Egeria"
appears BY ITSELF (no manual refresh) within a few seconds; remove → gone in Egeria; and
remove-then-re-add of the SAME URL → catalogued, not stuck. The route-level race test above
and the state/polling harness tests are this session's evidence for the same three outcomes at
the test level; live re-verification against the real shared registry/Egeria is the project
owner's own next gate pass, not repeated here (see this session's own report for what was and
wasn't attempted live in this round).

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
7. **Round 4's live verification is test-level only, not re-run against the real shared
   registry/Egeria in this round.** The route/outbox race test, the pure-function table test,
   and the frontend harness's polling test are this session's evidence that the fix behaves
   correctly; per this session's coordination posture, and because the PR/CI dispatch names the
   project owner's own re-gate on `laz_local_adventureworks` as the next live check (see "Re-gate
   scope" above), a fresh live reproduction against the shared platform was left to that pass
   rather than duplicated here. If that gate finds anything this round's tests didn't anticipate,
   it is a real gap in this fix, not merely an unverified claim about it.
