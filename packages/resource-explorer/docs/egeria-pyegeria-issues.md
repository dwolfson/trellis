# Egeria / pyegeria Issues Tracker

**Purpose:** Bugs and rough edges found in Egeria server-side code or the `pyegeria` SDK while building Resource Explorer (RE) — as opposed to RE's own bugs. Dan owns pyegeria/Egeria, so this is the running list to work from when triaging/fixing upstream, or filing issues against the Egeria project. Distinct from `docs/Backlog.md`, which tracks RE's own work.

Each entry: what broke, the exact error, where RE hit it, the workaround (if any) applied in RE, and status.

---

## Open

### E1 — PostgreSQL repository connector 500s on `createMetadataElementFromTemplate` when saving a classification (`metadata_collection_guid` missing)

**Status:** Open, unresolved. No workaround exists in RE — this fails the operation outright; RE catches the exception and reports it, but the Egeria-side catalog action does not complete.

**Where hit:** `AutomatedCuration.create_folder_element_from_template()` (pyegeria), called from `EgeriaFileSystemSurveyor.catalog_and_survey()` (`resource_explorer/surveyors/filesystem/egeria_filesystem_surveyor.py`) while cataloging a new FileSystem root folder as part of a hybrid (local walk + Egeria publish) filesystem survey.

**Reproduction context:** Register a new local filesystem, run a survey with "Publish survey results to Egeria (hybrid mode)" checked, against a filesystem not yet cataloged in Egeria (2026-07-13).

**Full error:**
```
SERVER_ERROR_500
Egeria detected error: `https://localhost:9443/servers/qs-view-server/api/open-metadata/automated-curation/catalog-templates/new-element`.
* class name=`BaseServerClient`
* caller method=`_async_create_element_from_template`
* class= `GUIDResponse`
* relatedHTTPCode= `500`
* exceptionClassName= `org.odpi.openmetadata.frameworks.openmetadata.ffdc.PropertyServerException`
* actionDescription= `createMetadataElementFromTemplate`
* exceptionErrorMessage= `OMAG-REPOSITORY-HANDLER-500-001 An unexpected error
  org.odpi.openmetadata.repositoryservices.ffdc.exception.RepositoryErrorException was
  returned to createEntity by the metadata server during createMetadataElementFromTemplate
  request for open metadata access service Open Metadata Store Services on server
  qs-metadata-store; message was POSTGRES-REPOSITORY-CONNECTOR-500-001 The qs-metadata-store
  postgreSQL repository connector received an unexpected exception
  RepositoryErrorException during method addEntityToStore; the error message was:
  POSTGRES-REPOSITORY-CONNECTOR-500-001 ... during method saveClassification; the error
  message was: JDBC-RESOURCE-CONNECTOR-500-002 The JDBC resource connector detected a
  missing value for column metadata_collection_guid during method setUpStringValueInRow
  in mapper org.odpi.openmetadata.adapters.repositoryservices.postgres.repositoryconnector.
  mappers.ClassificationMapper`
```

**Analysis:** The failure is entirely server-side, three layers deep: `createEntity` → `saveClassification` → the JDBC resource connector's `ClassificationMapper.setUpStringValueInRow` fails because `metadata_collection_guid` is null/missing for a classification being attached during template-based entity creation. This is the PostgreSQL repository connector (`qs-metadata-store`), not the view service or pyegeria — RE's request body was accepted (500 came back from a downstream repository call, not a 400 validation error), so this looks like a genuine server-side defect in the Postgres repository connector's classification-mapping path, likely specific to the `FileFolder` template + classification combination `create_folder_element_from_template` uses.

**Full RE-side traceback:** captured in `resource_explorer/surveyors/filesystem/egeria_filesystem_surveyor.py::catalog_and_survey` → `hybrid_filesystem_surveyor.py::run_hybrid_filesystem_survey` (line ~66) → `pyegeria/omvs/automated_curation.py::create_folder_element_from_template` → `_async_create_folder_element_from_template` → `_async_create_elem_from_template` → `_async_create_element_from_template` → `core/_base_server_client.py::_async_make_request` raises `PyegeriaAPIException`.

**Impact on RE:** Blocks hybrid-mode filesystem surveys for any filesystem not already cataloged in Egeria. Local-only surveys are unaffected (the local walk completes and is stored regardless — RE catches this exception and doesn't let it fail the whole request).

---

## Fixed in RE with a documented workaround (root cause is upstream)

### E2 — `AutomatedCuration` survey-initiation methods hardcode a stale single-colon qualifiedName separator (7 methods, only 2 hit by RE so far)

**Status:** Workaround shipped in RE for the 2 methods RE actually calls; the other 5 carry the identical bug, unused by RE today, not yet fixed upstream.

**Where hit:** `EgeriaDatabaseSurveyor._initiate_native_survey` (`resource_explorer/surveyors/database/egeria_database_surveyor.py`), triggering a native PostgreSQL survey.

**Bug:** Egeria changed its qualifiedName separator convention for these built-in survey `GovernanceActionType`s from `:` to `::` at some point, but the corresponding hardcoded strings in `AutomatedCuration`'s survey-initiation methods (pyegeria `omvs/automated_curation.py`) were never updated to match. Confirmed live 2026-07-08 (via `find_governance_definitions`) that the registered names all use `::`. Every one of the following still hardcodes the old single-colon form and will fail with `OMAG-GENERIC-HANDLERS-400-013 "name is not recognized"` against any current, correctly-registered server:
- `initiate_postgres_database_survey` (~line 3034) — `PostgreSQLSurvey:survey-postgres-database`
- `initiate_postgres_server_survey` (~line 3044) — `PostgreSQLSurvey:survey-postgres-server`
- `initiate_file_folder_survey` default arg (~line 3052) — `FileSurveys:survey-folder`
- `initiate_file_survey` (~line 3100) — `FileSurveys:survey-data-file`
- `initiate_kafka_server_survey` (~line 3121) — `ApacheKafkaSurveys:survey-kafka-server`
- `initiate_uc_server_survey` (~line 3143) — `UnityCatalogSurveys:survey-unity-catalog-server`
- `initiate_uc_schema_survey` (~line 3166) — `UnityCatalogSurveys:survey-unity-catalog-schema`

**Workaround in RE:** Only the two Postgres methods are used by RE today. `_initiate_native_survey` bypasses both public SDK methods entirely and calls pyegeria's private `AutomatedCuration._async_initiate_survey(survey_qualified_name, target_guid)` directly with the correct double-colon qualifiedName (sourced from `config/technology_type_processes.yaml`, not hardcoded in RE either). Documented at the top of `egeria_database_surveyor.py` and inline on `_initiate_native_survey` with an explicit "remove this workaround once it's fixed upstream" note. The other five methods are unused by RE and unpatched — they'd need the same workaround if RE ever calls them directly.

**Suggested upstream fix:** `:` → `::` in each of the 7 hardcoded strings above.

---

### E2b — `DataDiscovery._async_delete_annotation` calls a nonexistent method name (typo)

**Status:** Found 2026-07-07; not yet worked around in RE (RE hasn't needed `delete_annotation()` yet) or fixed upstream.

**Where hit:** `pyegeria/omvs/data_discovery.py::_async_delete_annotation`, found during Survey Definition executor debugging.

**Bug:** Calls `self._async_delete_element_body_request(...)` — no such method exists on the client. The real method is `_async_delete_element_request`. This is a plain typo that breaks `delete_annotation()`/`_async_delete_annotation()` for every caller, unconditionally (an `AttributeError`, not a server-side failure).

**Suggested upstream fix:** Rename the call site from `_async_delete_element_body_request` to `_async_delete_element_request`.

---

### E3 — pyegeria sync wrapper methods call `asyncio.get_event_loop()`, which raises in Python 3.12+ worker threads

**Status:** Workaround shipped in RE (three call sites); not fixed upstream.

**Where hit:** Any pyegeria sync-wrapper call (e.g. `AutomatedCuration.create_folder_element_from_template`, `EgeriaPublisher.publish`, `AssetMaker` catalog calls) made from a FastAPI request handled via `asyncio.to_thread` / a plain thread-pool worker — which is exactly how RE runs Egeria publish/catalog operations, since they're blocking calls. Confirmed 2026-06-11 across three separate call sites: `resource_explorer/web/routes/databases.py::publish_database_survey`, `resource_explorer/web/routes/egeria.py::publish_survey` and `::catalog_elements`.

**Bug:** pyegeria's synchronous wrapper methods internally call `asyncio.get_event_loop()` to get a loop to run their async implementation on. In Python 3.12+, calling `get_event_loop()` from a thread that has never had an event loop set (true for any `ThreadPoolExecutor`/`asyncio.to_thread` worker) raises `RuntimeError: There is no current event loop in thread '...'` instead of implicitly creating one (the pre-3.10 behavior pyegeria's design apparently assumes).

**Workaround in RE:** Every thread-worker function that calls into pyegeria's sync wrappers creates and sets a fresh event loop first (`asyncio.new_event_loop()` + `asyncio.set_event_loop(loop)`), then closes it and clears the thread-local loop in a `finally` block.

**Suggested upstream fix:** pyegeria's sync wrappers should manage their own event loop internally (e.g. `asyncio.new_event_loop()` + `run_until_complete()` + close, scoped to the call) rather than relying on `get_event_loop()` finding one already set on the calling thread — the current design only works when called from the main thread or from a context that has already set up a loop, which is a fragile assumption for a library meant to be called from arbitrary application code.

---

### E4 — `AutomatedCuration.get_guid_for_name` returns the literal string `"No elements found"` on a miss, not `None`/`[]`/an exception

**Status:** Workaround shipped in RE; not fixed upstream.

**Where hit:** `_find_element_guid` in both `resource_explorer/surveyors/database/egeria_database_surveyor.py` and `resource_explorer/surveyors/filesystem/egeria_filesystem_surveyor.py`.

**Bug:** When no element matches, `get_guid_for_name` returns the string `"No elements found"` rather than `None`, an empty list, or raising. RE's original code treated any string longer than 10 characters as "looks like a GUID" (`len(s) > 10`) — `"No elements found"` is 16 characters, so it was silently accepted as a valid GUID. The fake GUID then propagated into `_find_element_guid`'s caller and into the activity log, meaning existing Egeria elements were effectively never found (every lookup "succeeded" with a garbage GUID instead of falling through to the not-found path).

**Workaround in RE:** Replaced the length heuristic with a real UUID-format regex (`^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$`, case-insensitive) — `_UUID_RE` in both files.

**Suggested upstream fix:** `get_guid_for_name` should return `None`/`[]` (matching the type signature's other "not found" paths) instead of a human-readable sentinel string indistinguishable from real output without an extra validity check.

---

### E5 — `SurveyReport` creation requires `"class": "AssetProperties"` + `"typeName": "SurveyReport"`, not `"class": "SurveyReportProperties"`

**Status:** Workaround shipped in RE; not fixed upstream (may be a documentation gap rather than a code bug — see below).

**Where hit:** `EgeriaPublisher._create_survey_report` (`resource_explorer/surveyors/egeria_publisher.py`), creating the `SurveyReport` asset a survey's annotations attach to.

**Bug:** The intuitive typed-properties body — `"class": "SurveyReportProperties"` — is not recognized by the asset-maker `/assets` endpoint (fails to create the element). The working shape, confirmed against a live server, is the generic `"class": "AssetProperties"` with `"typeName": "SurveyReport"` set separately, matching pyegeria's own sample body for this call rather than the per-type-class pattern used elsewhere in the same API family (e.g. annotation properties, which *do* use per-type classes — see E6 below, which is the inverse inconsistency).

**Impact before the fix:** Publishing silently used the wrong properties class; the resulting failure mode also masked a second bug — `report_guid` came back `None` and an un-guarded `report_guid[:12]` threw a `TypeError` that silently swallowed the activity log write (fixed in the same pass by guarding with `(report_guid or 'no-guid')[:12]`).

**Suggested upstream fix:** Either accept `SurveyReportProperties` as an alias (matching the per-type-class pattern used for annotations), or document clearly on the asset-maker endpoint which asset types require the generic `AssetProperties` + `typeName` shape vs. a dedicated `<Type>Properties` class — right now this is only discoverable by trial and error against a live server.

---

## Documented API gotchas (not bugs, but easy to get wrong — kept here for reference)

### G1 — Annotation subtype class names are inconsistent: `RequestForActionProperties` breaks the `<X>AnnotationProperties` pattern

Every other Annotation subtype used by `EgeriaPublisher._build_annotation_props` follows `"<X>AnnotationProperties"` — `ResourceMeasureAnnotationProperties`, `ClassificationAnnotationProperties`, `DataClassAnnotationProperties`, `SchemaAnalysisAnnotationProperties`, `RelationshipAdviceAnnotationProperties`. `RequestForAction`'s class is `RequestForActionProperties` — no `"Annotation"` in the middle, breaking the pattern with no obvious reason. `QualityScore`'s class is `QualityAnnotationProperties` (not `QualityScoreAnnotationProperties`), a second, milder break of the same pattern. Documented inline in `egeria_publisher.py::_build_annotation_props`. Not filed upstream as a bug (naming is presumably intentional/legacy), but worth Egeria-side awareness since it's a real trap for anyone guessing the pattern instead of checking each type.

### G2 — `AssetMaker` constructor argument order is `(view_server, platform_url, user_id, user_password)` — `view_server` first, not `platform_url`

Documented in `CLAUDE.md` Key Design Rule #11. Easy to get backwards since most other pyegeria client constructors put the platform URL first.

---

## How to use this doc

When you hit a new Egeria/pyegeria error while working on RE: add an entry above (Open, until a workaround or upstream fix lands), including the full error text/stack trace, the exact pyegeria/Egeria call that triggered it, and the RE code path that hit it. Move to "Fixed in RE with a documented workaround" once a workaround ships, and note the suggested upstream fix so it's ready to file or hand to whoever owns that part of Egeria.
