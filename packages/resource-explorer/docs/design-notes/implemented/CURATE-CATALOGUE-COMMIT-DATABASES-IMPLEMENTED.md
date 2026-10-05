# Curate: the catalogue commit for databases, by schema-kind targets (implemented)

2026-10-05, branch `re/curate-catalogue-commit-databases`, built on `origin/main` 27a11316 and merged with
`origin/main` d71be2cf (PR #483, the scope header and collapse). Brief:
`BRIEF-CURATE-CATALOGUE-COMMIT-DATABASES.md`. **Built against a fake Egeria only: nothing here has run against a live
Egeria**, by instruction. Every live question is listed under "Not verified without live Egeria".

Verified import path: `uv run python -c "import resource_explorer; print(resource_explorer.__file__)"` printed
`/Users/dwolfson/localGit/egeria-v6/trellis-re-slice-b/packages/resource-explorer/resource_explorer/__init__.py`,
inside the builder's own worktree. Tests ran with `PGVECTOR_PORT=1` and temp SQLite registries (asserted in the fixtures).

**Decision (project owner, 2026-10-05):** "Go with the schema-kind door." One SCHEMA-kind catalog target per chosen
schema; revisit as Egeria changes.

## What was built

| Piece | Where |
|---|---|
| The commit: preview and manifest, collision check, leave-out forms, re-inclusion rules, proof-row state derivation, read-back, the run's steps | `resource_explorer/catalogue_commit.py` (new) |
| The one door to Egeria (a `CatalogueGateway` protocol and the pyegeria implementation, with the evidence cited per call) | `resource_explorer/catalogue_gateway.py` (new) |
| `catalogue_commit_proofs`, an append-only table, plus `append_/list_catalogue_commit_proofs` and `list_catalogue_outbox_rows` | `registry.py` |
| Outbox kinds `catalogue_schema_attach` and `catalogue_schema_leave_out` (self-resolving, registry and gateway on `OutboxClients`) | `egeria_outbox.py` |
| Run kind `catalogue_commit` and its handler | `registry.py` (`RUN_KINDS`), `run_queue.py` |
| Routes: `GET /{slug}` now carries `commit`; `GET /commit-preview`, `POST /commit`, `GET /commits[/id]`, `POST /read-back` | `web/routes/catalogue_scope.py` |
| The manifest, per-node "In Egeria" states, the Catalogue button, the steps, the state-derived header marker | `static/next/stages/curate-scope.js`, `glyphs.js`, `re-api.js` |
| Classic's database Publish button and modal removed | `static/index.html` |
| Database template gets `databaseDescription` and `versionIdentifier`; `publish_local_survey(survey_after_catalog=False)` | `egeria_database_surveyor.py` |
| Depth is now a tree view (`commit_honours`), its lever wording removed | `catalogue_scope.py` |

## The steps, in the manifest's order

`publish_elements` (server and database, no survey), `zone_membership` (before any target; skipped writes when the zones
already match, because Egeria rejects an equal change), `owner` (added after the database exists; a refused change reads
"owner set by Egeria's source · can't change from RE"), `schema_targets` (outbox rows, drained at once), `leave_outs`,
`survey_report` (RE's own report and annotations, no native survey), `survey` (Egeria's, with `includeSchemaNames`),
`refresh` (optional; `refresh_integration_connectors("JDBCDatabaseCataloguer", daemon, 120)`; RE never restarts a
connector, asserted by a test), `read_back`. A step that fails is a failed step; what depends on it is skipped with the reason
(no zones means no target is attached, because dependents copy the zones at creation).

## Decisions

* **Proof rows.** A schema is `catalogued` only when a read-back found elements under its qualified name;
  `attached, waiting` when the target was read back with none; `queued`/`failed` are the newest outbox row's own
  status and `last_error` (Egeria's word, class prefix stripped); `removed` and `archived` are written only after the
  absence or the Memento is read back; `left out` is the scope record and carries no glyph. A test deletes the rows and
  the words go with them. A schema with zero tables stays "attached, waiting" (it can never be read back as catalogued).
* **Header marker.** `#483`'s constant is now `derive_commit_state(...)["header"]`: the old sentence only while no row
  exists. The JS holds no copy of the words; `#483`'s pinned tests were updated to say so.
* **Per-schema, not per-commit, blocking** for a failed relationships read and for an archived schema chosen again
  ("couldn't check what hangs off it"; the S19 sentence): that schema is left exactly where it is and the commit proceeds for
  the rest. Name collisions disable the whole commit (the brief), and the only way out is leaving the wildcard-bearing schema out.
* **Hang-off is a negative list** (`STRUCTURAL_RELATIONSHIPS`): any relationship type not known as the cataloguer's own
  structure counts, so an unknown type errs towards ARCHIVE (keeps it), never a soft delete. The form is re-derived at press
  time and the safer one wins.
* **Undecided schemas already in Egeria stay targets** and in the survey list (the scope's rule: only an explicit leave out removes).
* **Survey list**: comma-bearing names are left out of it and named; an empty list starts no survey (an empty parameter
  would survey everything).
* **Depth.** A schema-kind target always creates tables and columns and Egeria has no depth option (S2), so depth is
  a tree view; the earlier "include list" wording would now be a false claim and is gone.
* **Version** is "not recorded" (RE keeps no PostgreSQL version): honest beats a made-up "1.0".
* **Classic**: the button and modal are gone. `POST /api/databases/{slug}/publish` stays because the survey-definition
  "catalog in Egeria now, then retry" still calls it; it starts an unscoped survey (documented on the route).
* A queued attach checks the scope again when it runs: if the schema was left out in the meantime it does nothing.

## Migration (for the coordinator's peer check)

One new table, **`catalogue_commit_proofs`** (+ index `idx_catalogue_commit_proofs_node`), `CREATE TABLE IF NOT EXISTS`,
no foreign keys, no colons in comments (the Postgres translator). No column added to any existing table; `runs.kind` has
no constraint, so the new kind needs nothing. Covered by `test_migration_is_additive_and_an_old_shape_database_opens`
(drops the table, reopens, existing rows untouched). `remove_database` deletes its proof rows. New env var
`EGERIA_INTEGRATION_DAEMON` (default `qs-integration-daemon`).

## Evidence of the red runs

* Unchanged `origin/main` (d71be2cf) with the new tests copied in: `test_catalogue_commit.py` cannot import
  (`resource_explorer.catalogue_gateway` missing); `test_classic_database_publish_retired.py` 3 failed;
  `test_catalogue_scope.py` 2 failed (depth); the two harness files 17 failed.
* Sixteen mutations on a copy, each breaking one guard on purpose, all went red: header made a constant; state taken from the
  branch not the rows; collisions ignored; leave-out always soft delete; targets not read before attaching; comma names joined into
  the survey; zones check skipped; archived re-inclusion allowed; orphan schema type not adopted; catalogue kinds not self-resolving;
  parent-first delete order; template placeholders dropped; archive flags dropped in the gateway; targets read with pyegeria's
  default body; and two in the JS (header constant, state-cell constant).
* Full suite (10 shards, `PGVECTOR_PORT=1`): green except `test_architecture_doc_lens ... test_a_site_only_project_reports_every_site_it_found`,
  which fails identically on `origin/main` (a connection-refused message where the test expects a sentence; pre-existing).
  `test_prefect_survey_flow` failed once under 10-way load and passes alone. Two tests of mine-adjacent code were updated, not loosened:
  the dynamic-class tripwire (one interpolation removed from the JS instead of raising the count) and the Classic publish test (the
  code it pinned was retired). Render harness: 455 of 455.

## Owner's gate, on 8810 after merge, coco_pharma, the 29-schema scope

1. Open Curate, expand the scope: the manifest lists the three mechanisms, the target count and the survey's schema list.
   Press Catalogue (leave "refresh now" ticked): the steps land, each schema reads queued, then attached/waiting, then
   catalogued with a read-back time; tables and columns appear under each schema and nothing under the database
   (`PostgreSQL Relational Database::<server>::<db>::` has no children).
2. Leave out a schema with nothing hanging off it: the preview says soft delete; after the press "removed · was catalogued";
   choose it again and press: it is re-created with new GUIDs.
3. Leave out one with a term assignment: the preview names it and says archive; then "archived"; choosing it again is refused with the S19 sentence.
4. Two colliding names (`a_b` and `aXb`, `x_y` and `xZy`) are flagged before the press; coco_pharma may have none, then the fixtures prove it.
5. After an Egeria restart that keeps the store, the scope and states survive; after a reset, pressing again recreates from the scope record
   (tested with a fake reset).
6. Classic shows no database Publish; the header reads from state (change the state, the line changes).

## Not verified without live Egeria (read these first on the first live run)

1. `create_schema_element` sends `anchorGUID`, `parentGUID`, `parentRelationshipTypeName` DataSetContent: the scratch runs created
   the schema with no parent. The brief says "under the database element" so zones copy; if rejected, drop those fields and set the zones another way.
2. The shape of a non-empty `get_catalog_targets` answer (relationship GUID and element keys), of `get_all_related_elements`
   (relationship type names), and of the daemon status (`connectorName`, `lastRefreshTime`): parsed tolerantly, not observed.
3. `elements_under` uses a starts-with name search then filters client-side; whether the server treats the string as a literal or a regex was not established.
4. Adoption of a pre-existing `<dbQN>::<schema>_schemaType` links it with an `AssetSchemaType` relationship; whether the cataloguer's schema-kind scheme even
   produces that name was not observed.
5. The structural relationship list, and that a term assignment on a column is seen by the relationships read of the table and column elements.
6. The Ownership read-before-write shape; the zone read-first (`current_zones`) against a real security connector.
7. Cost: the preview makes one relationships read per element of every schema being left out that was ever catalogued.
8. The lingering-target sentence is the brief's wording; the read-back proves the detach, and S17 (a removed target keeps being refreshed) is the recorded behaviour, not something each read re-observes.
9. The server-template placeholder for its description (S15 was only isolated for the database template).

## Rulings wanted

* Whether a collision should block per schema rather than the whole commit (built as the brief says: whole).
* Whether the survey-definition retry should stop calling the unscoped Classic publish route.
* Whether "refresh now" should default on (UI: on; API: off).
