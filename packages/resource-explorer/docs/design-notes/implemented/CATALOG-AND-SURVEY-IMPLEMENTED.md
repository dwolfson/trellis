# Register the server with Egeria ("Catalog and Survey") — implemented (2026-10-08)

Source of the work: the project owner's gate on `laz_local_adventureworks` (2026-10-08). Its
Egeria-native survey had failed with "Egeria has no asset with the GUID RE has stored… Publish the
resource to Egeria again" and, before that, `role "surveyor" does not exist`. The owner's rulings,
which shape every part of this:

* "this is not about publishing the details of surveys to Egeria — this is about registering the
  resource with Egeria so that we can run an Egeria based survey on it."
* "It's actually a registration of the database **server** not a database." Surveying a server gives
  its databases; those are then surveyed and cataloged.
* "There may be situations where RE can reach the database but Egeria can't. So registering with
  Egeria should remain optional."
* "Some databases may not distinguish between a database server and a database — but that is a
  subtlety."

The older sentence on the "Catalog and Survey" row, "RE does not collect those template placeholder
properties", was wrong (the Backlog entry "Wire 'Catalog and Survey' for one-click execution" has the
truth): RE has the data; Egeria's processes take it as template **placeholder parameters**, not as the
connection info RE stores. This slice maps one onto the other.

## What the press does (and in what order)

"Register the server with Egeria →" (`POST /api/native-surveys/{type}/{slug}/register`,
`catalog_and_survey.register_with_egeria`). Every write is followed by a read of what it wrote, and a
pointer or proof row is stored only after that read.

| # | Egeria call | Read-back before anything is stored |
|---|---|---|
| 0 | none — checks the `.omsecrets` collection `<slug>::PostgreSQL Secret` exists (existing projection fills it if absent and RE can write the file) | — |
| 1a | `get_metadata_element_by_unique_name(qualifiedName = "PostgreSQL Server::<host:port>")` | — |
| 1b | only if 1a found nothing: `create_elem_from_template` with Egeria's **server template** `542134e6-b9ce-4dce-8aef-22e8daf34fdb` (`isOwnAnchor`, `deepCopy`, the 8 placeholders below) | `get_metadata_element_by_guid(<guid>)`, qualifiedName compared; **then** the server pointer is stored (`app_settings` key `egeria_server_guid::PostgreSQL Server::<host:port>`) |
| 2 | `initiate_gov_action_type("PostgreSQLSurvey::survey-postgres-server", serverToSurvey = <server guid>)` — Egeria's own server survey, through the existing native-survey slice (poll, engine-action read, report read) | engine action read back (`activityStatus`); proof row = the engine-action GUID |
| 3a | `get_metadata_element_by_unique_name(qualifiedName = "PostgreSQL Relational Database::<host:port>::<db>")` | if found: read by GUID, qualifiedName compared, then `databases.egeria_asset_guid` stored (adopted; no process submitted) |
| 3b | only if 3a found nothing: `initiate_gov_action_process("PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess", request_parameters = the 8 database placeholders)` | proof row = the process-instance GUID. The database is read **by qualifiedName and then by GUID** on every refresh; only then is `egeria_asset_guid` stored. The survey engine action the process started is found from the database's own `ActionTarget` relationship (`requestType survey-postgres-database`) and recorded under the ordinary "Survey PostgreSQL Database" row **only when there is exactly one** |

No zone is written (the 2026-10-05 lockout), no `ZoneMembership`, no archive or delete (the ISSUE-117 block
is untouched and ON), nothing in Curate's catalogue commit, and no DDL.

## Phase 1 findings

**How "Survey PostgreSQL Database" is submitted** (the pattern): route `web/routes/native_surveys.py`
(`POST …/run`) → `native_survey_run.submit_native_survey` → `PyegeriaSurveyPort.initiate`
(`AutomatedCuration.initiate_gov_action_type`, action target `serverToSurvey` = the asset GUID) → a
`step_runs` proof row keyed on the engine-action GUID → `refresh_run` reads the action
(`get_metadata_element_by_guid`, `activityStatus`) and, once COMPLETED, the report found by the
`ReportOriginator` relationship. `derive_native_state` is the one place proof becomes words.

**Egeria's source** (read-only, `egeria/open-metadata-resources/.../PostgresPackArchiveWriter.java`,
`ContentPackBaseArchiveWriter.createAndSurveyServerGovernanceActionProcess`):

* Egeria has **two** CreateAndSurvey processes. `PostgreSQLServer:CreateAndSurveyGovernanceActionProcess`
  (step 1 create the server asset from `POSTGRES_SERVER_TEMPLATE`, step 2 `survey-postgres-server`, step 3
  print report) and `PostgreSQLDatabase:CreateAndSurveyGovernanceActionProcess` (step 1 create the database
  from `POSTGRES_DATABASE_TEMPLATE`, step 2 `survey-postgres-database`, step 3 print). Step 1's new asset
  reaches step 2 as the `newAsset` action target. **Neither registers a server alone**: both always survey
  and print afterwards. So the server is registered by Egeria's own server **template** (the same one step 1
  uses) with a read-back, and the server survey is submitted separately; the database is created by the
  database process.
* **The server survey does not create database elements.** `PostgresServerSurveyActionService` lists
  `pg_database`, surveys each (excluding `postgres`) and writes **annotations only**
  (`Capture Database Measurements`, plus schema/table/column ones); its own comment: "the databases are not
  catalogued at this time". So the databases RE shows as *found* come from the report's annotations, as
  Egeria reported them; a found database with no asset is "found, not yet cataloged".
* Server template placeholders (`getPostgresServerPlaceholderPropertyTypes`) and the database template's
  (`getPostgresDatabasePlaceholderPropertyTypes`):

| placeholder | server | database | where RE gets it |
|---|---|---|---|
| `hostIdentifier` | yes | yes | `databases.egeria_host`, else `host` (the host Egeria reaches) |
| `portNumber` | yes | yes | `databases.port` |
| `serverName` | yes | yes | `<egeria host>:<port>` (`catalogue_gateway.server_name_for`) |
| `versionIdentifier` | yes | yes | "not recorded" (RE keeps no version) |
| `description` | yes | — | "PostgreSQL server at <server name>" |
| `resourceName` | yes | — | the server name |
| `databaseName` | — | yes | `databases.database_name` |
| `databaseDescription` | — | yes | `databases.description`, else a sentence naming the database |
| `secretsStorePathName` | yes | yes | `config.egeria.secrets_store_path_name` (the path **inside the engine host**) |
| `secretsCollectionName` | yes | yes | `<slug>::PostgreSQL Secret` |

  There is no user or password placeholder: both templates' connection names the secrets collection and the
  store path, and Egeria's engine host reads `userId` / `clearPassword` from the `.omsecrets` file at survey
  time. A test pins the key sets to Egeria's lists.
* **Where credentials come from and who writes them.** The file is `resource-explorer.omsecrets`
  (`EGERIA_SECRETS_STORE_LOCAL_PATH` host-side, `…_PATH_NAME` container-side), key
  `secretsCollections.<slug>::PostgreSQL Secret.secrets.{userId,clearPassword}`. RE's registry-to-file
  projection writes it (`omsecrets_store.write_credential` at registration / credential change;
  `omsecrets_reproject` at startup, on each resync pass and by CLI). This slice only checks the collection is
  there and, if it is absent and RE can write the file, asks the **existing** projection for that one slug
  (`only_missing`). It never reads a password into a message. The server element's connection uses the same
  collection as the database it was registered from.
* **Where "surveyor" came from.** The user in the collection is `databases.db_user` as stored in RE's registry
  at the time of projection (`omsecrets_reproject._plan`: `user, password = db.db_user, db.db_password`). The
  earlier `FATAL: role "surveyor" does not exist` on the 5432 server therefore means the stored record for
  `laz_local_adventureworks` carried the user `surveyor` while 5432 knows `dwolfson`
  (see the credentials-by-port reference: 5442 accepts `surveyor`). A new registration reads the same record,
  so **it would recreate the same connection** unless the record's user is changed first. This slice changes no
  credential and could not read the shared registry to confirm the stored value; check
  `databases.db_user` for that slug, and Update credentials on it, before pressing.
* **What the stale GUID is.** `fc4e0478-4efe-4a29-bd1a-01b5bcb4a61b` is `databases.egeria_asset_guid` — the
  **database** element's GUID, set by the older publish path (`set_database_egeria_guid`). RE has two kinds
  of pointer: that column (database) and, new here, the server pointer in `app_settings`. The old publish
  never stored a server pointer (its `server_guid` was a local variable). The database element it pointed at
  no longer exists in Egeria (the repository was reset); the sentence "Publish the resource to Egeria again"
  was generated at `native_survey_run.submit_native_survey` (the `asset_exists` check).

## What changed

* `catalog_and_survey.py` (new): the press, the placeholders, the real port (`PyegeriaRegistrationPort`), pointer
  checks, the "Catalog and Survey" row's derivation, the discovered-databases listing, the reach note.
* `native_survey_run.py`: rows grow `neutral`, `stale`, `target`, `register`, `reach_note`, `discovered`; the catalog
  row and server-survey row; stale wording (`NativeSurveyStale`); registration runs refresh and sweep by their own
  derivation (a COMPLETED process has no report to wait for); Egeria's text is scrubbed of the resource's password.
* `technology_type_processes.py` + `configdata/technology_type_processes.yaml`: `separate_server_element`,
  `server_technology_type`, per-process `target`; **`server_has_separate_element(entity_type, technology_type)`**
  (True PostgreSQL; False coincident kinds; None = "this kind is not wired yet").
* Routes `…/register` and `…/check` (read-only pointer check; called by the pane once, only when a pointer is stored).
* `scheduler._sweep_native_surveys` uses the registration port (same port plus the reads a registration run needs).
* Front end: `native-surveys.js`, `re-api.js`, two neutral cues in `glyphs.js` (`optional`, `gone`).
* No registry DDL; `registry.py` untouched. The server pointer uses the existing `app_settings` key/value table.

## Optional by design

Registering is a press; nothing requires it and nothing nags. A never-registered database shows a **neutral** state
(muted ○ "not registered", "Egeria has not been given this database · register it to run Egeria's own survey ·
optional", no ✕, no warn colour) and RE's own surveys, curation and everything else are unchanged. Only a stored
pointer that **Egeria answers no longer exists** uses the stale wording ("the Egeria asset RE had stored no longer
exists"), and a failed read is "unreadable", never "gone". When an Egeria survey fails and reads as a connection
problem, Egeria's sentence is shown verbatim plus one line: "Egeria connects from its own platform; RE can still
survey this database itself".

## Named follow-ups

1. **Kinds where the server and the database coincide** (a single-file or embedded database, for example).
   `separate_server_element: false` is the config value for them, and `wiring_reason` already answers "the server and
   the database are one thing for this kind, and registering them in one step is not built yet". The single-step
   variant would register **one** element (the database/asset that is also its own server) from that kind's template,
   read it back by GUID, store the one pointer, and run that kind's survey; no server pointer, no server survey, no
   discovered-databases list. Unknown kinds say "this kind is not wired yet". FileDirectory's "Catalog and Survey"
   is in that second group.
2. **An Egeria-side reachability probe** ("can Egeria's platform reach this host:port?") — deliberately not built; the
   reach line only reports after Egeria itself failed.
3. The server's connection reuses the first-registered database's secrets collection; if that database is later
   removed from RE the collection name still resolves in the file but is no longer maintained. A per-server
   collection would fix it.
4. A server survey is stored under the database slug that triggered it, so a second database on the same server shows
   its own server-survey row (it can be run again, a second report).
5. **Unverified live** (no live Egeria was used): the process instance's own `activityStatus` (the code falls back to
   its first engine action found by `ActionRequester`, as Egeria's FVT finds it; no status at all is shown as "last read
   failed", never guessed); and whether `create_elem_from_template` with the server template derives the qualifiedName
   `PostgreSQL Server::<host:port>` on this build (rehearsal 1 evidence says yes; a mismatch makes the read-back refuse and
   store nothing).

## Verified

`tests/test_catalog_and_survey.py`, `tests/test_catalog_and_survey_routes.py` (recording fakes only), and the harness file
`catalog-and-survey-register.test.mjs`. The owner gates by use on adventureworks.
