# Egeria pointer inventory in the RE registry, before the Egeria `egeria` database reset

Date: 2026-10-08

Read-only SELECT snapshot taken before the Egeria `egeria` database reset; RE's registry is database egeria_advisor (unaffected by the reset).

Snapshot timestamp (UTC): 2026-10-08 18:27:49 UTC

Method: SELECT statements only, through a connection wrapper that raises on any non-SELECT statement. Tables and columns were discovered from information_schema (schema resource_explorer). No credentials, connection URLs or secret values are recorded here. No Egeria calls and no HTTP to RE.

Classification: CLEAR = a pointer to an Egeria element that will dangle after the reset. KEEP = RE's own decision or history. Empty strings are treated as "no pointer" throughout; counts below are non-empty values.

## Summary of totals

CLEAR (pointers that will dangle; value counts are non-empty values or rows as stated):

| area | count | clear |
|---|---|---|
| projects.egeria_asset_guid | 7 | column |
| databases.egeria_asset_guid | 6 | column |
| catalogue_commit_proofs rows with a GUID | 175 of 229 | two columns (ledger rows are history) |
| architecture_materialized_blueprints + components | 137 (17 + 120) | whole rows |
| sub_resources.egeria_guid | 46 of 81 | column |
| egeria_outbox | 5230 rows (5203 GUIDs; 10 dead) | rows are spent history |
| native_survey_annotations | 1074 | three GUID columns; rows are a judgement call |
| report pointers (database_surveys 13, project_egeria_surveys 34, project_published_analyses 144, project_published_annotation_types 98) | 289 | column |
| survey_definition_cache | 22 | whole cache |
| investigations, entity_egeria_project_context, working_sets, work_lists, doc_sources, rfa_actions, step_runs, feedback, egeria_linkage_status, one app_settings key | see sections 1, 6, 7, 8 | columns |

KEEP: verdicts (111), scope events (1 + 30 older + 2 baselines), enrichment and curation, journal, curator notes, groups, work lists and members, working-set members, investigation lists, dependency confirmations (4), repo survey outputs, annotation measurements (160,754) and findings (304,163), activity history (2,358), run history, all surveyed-database and project content tables. app_settings repo_node_reclassifications:: has no keys at snapshot time. The registry is not touched by the reset.

## 1. Asset pointers on projects and databases (CLEAR)

### projects.egeria_asset_guid: 7 of 68 projects (CLEAR column; keep the project row)

| project slug | egeria_asset_guid |
|---|---|
| amundsen | 7f496094-1b1f-4146-96ab-d1fb936a20f5 |
| egeria_docs | 3c8977dd-b858-4c0e-9f73-a3a528c9137a |
| egeria_git | 11c64f8d-c85c-4524-a732-65ab83f2806b |
| egeria_python_git | 9a7d4b33-eb3d-4fd3-aca5-7a2a50c98f8b |
| egeria_trellis | fd18ad9b-c3d8-41b2-bdce-1e1a499cff92 |
| egeria_workspaces_git | 8730266e-9e1b-4aa5-927c-2df98838c2e6 |
| sqlglot | 4ab1a63d-975c-4e3c-a368-1aec0c03f88d |

projects has no other guid-named column.

### databases.egeria_asset_guid: 6 of 17 databases (CLEAR column; keep the database row)

| database slug | egeria_asset_guid | status |
|---|---|---|
| egeria_optional_prefect_db | 45a75724-dbd3-45c6-bcd3-203db34265db | active |
| laz_local_adventureworks | fc4e0478-4efe-4a29-bd1a-01b5bcb4a61b | error |
| laz_local_marquez | e94ef5e7-9c41-46b8-bbd3-873ffd7ae320 | active |
| laz_local_treasury | 1ecb045d-e9cb-42f8-950d-8296889288e6 | active |
| laz_local_usda | 34ec7043-b2d5-4224-abe0-e77243d48a6f | active |
| localhost_docker_coco_pharma | 17f0a963-e96f-4726-86a2-e721fd0a38b1 | error |

No `egeria_asset_guid::` or `egeria_server_guid::` keys exist in app_settings (see section 6). file_systems.egeria_asset_guid exists but file_systems has 0 rows.

### egeria_linkage_status: the registry already marks these as stale (CLEAR rows, derived pointer-health cache)

| entity_type | slug | status | stale_guid | detected_at |
|---|---|---|---|---|
| database | egeria_optional_prefect_db | stale | 45a75724-dbd3-45c6-bcd3-203db34265db | 2026-09-26T23:47:29.227334+00:00 |
| database | laz_local_adventureworks | stale | fc4e0478-4efe-4a29-bd1a-01b5bcb4a61b | 2026-10-04T00:39:06.174414+00:00 |
| database | localhost_docker_coco_ods | stale | 8f239316-8773-44da-9e8e-760243226a10 | 2026-09-22T00:13:50.464535+00:00 |

The coco_ods stale GUID has no databases row any more with a pointer (databases.localhost_docker_coco_ods is not in the table); the linkage row alone remains.

## 2. catalogue_commit_proofs (CLEAR pointer columns element_guid and target_guid)

Total rows 229; non-empty element_guid 175 (46 distinct); non-empty target_guid 89 (8 distinct). The rows are RE's record of what each commit did (the proof ledger); the GUID columns are pointers and the rest (proof kind, node, outbox_id, qualified_name, detail_json, recorded_by, read_at) is history. Decision for the owner: clear the two GUID columns and keep the ledger, or clear the whole ledger as stale evidence of a world that no longer exists. Neither the proof rows nor their counts are decisions the user made.

### Counts per resource and proof kind

| database_slug | proof kind | rows | non-empty element_guid | non-empty target_guid |
|---|---|---|---|---|
| egeria_git | report_published | 2 | 2 | 2 |
| egeria_git | sub_resource_read_back | 2 | 2 | 0 |
| egeria_workspaces_git | promotion | 27 | 27 | 0 |
| egeria_workspaces_git | report_published | 1 | 1 | 1 |
| localhost_docker_coco_pharma | archived | 1 | 1 | 0 |
| localhost_docker_coco_pharma | attach_requested | 6 | 6 | 0 |
| localhost_docker_coco_pharma | connector_read | 32 | 0 | 0 |
| localhost_docker_coco_pharma | database_published | 5 | 5 | 0 |
| localhost_docker_coco_pharma | elements_read_back | 91 | 91 | 74 |
| localhost_docker_coco_pharma | owner_result | 5 | 5 | 0 |
| localhost_docker_coco_pharma | read_failed | 18 | 0 | 0 |
| localhost_docker_coco_pharma | report_published | 5 | 1 | 0 |
| localhost_docker_coco_pharma | restored | 1 | 1 | 0 |
| localhost_docker_coco_pharma | survey_result | 1 | 1 | 0 |
| localhost_docker_coco_pharma | survey_started | 5 | 5 | 0 |
| localhost_docker_coco_pharma | target_attached | 12 | 12 | 12 |
| localhost_docker_coco_pharma | target_detached | 1 | 1 | 0 |
| localhost_docker_coco_pharma | zones_read | 14 | 14 | 0 |

### Per resource totals

| database_slug | rows | distinct element_guid | distinct target_guid |
|---|---|---|---|
| egeria_git | 4 | 4 | 1 |
| egeria_workspaces_git | 28 | 28 | 1 |
| localhost_docker_coco_pharma | 197 | 14 | 6 |

### GUIDs for egeria_git and egeria_workspaces_git

| database_slug | proof | element_guid | target_guid |
|---|---|---|---|
| egeria_git | report_published | 5792872b-5e74-432e-9abf-2eb9485ae00a | 11c64f8d-c85c-4524-a732-65ab83f2806b |
| egeria_git | report_published | 718ac11e-1a4f-4151-8b87-7c9a9aa06df3 | 11c64f8d-c85c-4524-a732-65ab83f2806b |
| egeria_git | sub_resource_read_back | 320e9036-2a78-447e-bd04-a7be64a937a8 |  |
| egeria_git | sub_resource_read_back | 442f2963-c0f6-438a-b99f-9aaa0c151e5b |  |
| egeria_workspaces_git | promotion | 14b8faf0-2232-4c2f-a836-bb23ccf1c319 |  |
| egeria_workspaces_git | promotion | 1703c571-4dbc-4f7a-b64d-3a4456e02e8e |  |
| egeria_workspaces_git | promotion | 191845ae-0932-4c88-a9a8-0ed6d24e20db |  |
| egeria_workspaces_git | promotion | 1c1d8ad3-4153-4d0d-bfae-9f974c245326 |  |
| egeria_workspaces_git | promotion | 1d8cc065-f14b-447a-8380-cece84e3ed4d |  |
| egeria_workspaces_git | promotion | 1e8d4b72-549a-411d-aeb7-2fc15d11cbf0 |  |
| egeria_workspaces_git | promotion | 20b3114f-b3de-4e5e-8ddf-b84c8c896ccc |  |
| egeria_workspaces_git | promotion | 21ea67d6-b1ef-4bad-9c98-2a547c5e017f |  |
| egeria_workspaces_git | promotion | 30877188-3321-4837-8b2d-6fd860635f7e |  |
| egeria_workspaces_git | promotion | 36be306e-6af5-48f0-961e-df78c313516c |  |
| egeria_workspaces_git | promotion | 36dcd941-08e4-49d0-93c2-285363e1d737 |  |
| egeria_workspaces_git | promotion | 3ccd2d2b-eab5-4890-b27a-230f972a5cc1 |  |
| egeria_workspaces_git | promotion | 3f829324-a4a6-48d3-bf8f-d2a7eb3a8334 |  |
| egeria_workspaces_git | promotion | 40db89fe-b19e-43f9-b1ac-a969a03f4edd |  |
| egeria_workspaces_git | promotion | 72d0776b-4e4d-4db5-b136-919fa0fc9045 |  |
| egeria_workspaces_git | promotion | 83cc2513-cb28-430d-9558-8ebc078c51ae |  |
| egeria_workspaces_git | promotion | 971cb322-7c47-4671-a91e-786a10855dbf |  |
| egeria_workspaces_git | promotion | 994b9ff6-b94a-4536-9d26-c4fb7eb51422 |  |
| egeria_workspaces_git | promotion | a1f7c428-6b78-4bb6-8422-8bb17ad52434 |  |
| egeria_workspaces_git | promotion | a2e8efba-1064-475a-8b3c-20850de0e3e7 |  |
| egeria_workspaces_git | promotion | bc18a32e-1bdc-451c-9083-48d0955c9a9d |  |
| egeria_workspaces_git | promotion | dd8f406d-5893-4e95-8fb0-0388cf141a36 |  |
| egeria_workspaces_git | promotion | eada87c1-c1af-4c84-b851-de89a179bab5 |  |
| egeria_workspaces_git | promotion | ee022143-f9c4-47ad-9b22-d75773d98fb1 |  |
| egeria_workspaces_git | promotion | f4b0d1d7-f244-410a-b9e2-3075d487007e |  |
| egeria_workspaces_git | promotion | f7106616-720b-4d47-aadb-3404cf947d27 |  |
| egeria_workspaces_git | promotion | fb926d37-63e3-448d-9852-f0d1872d11d3 |  |
| egeria_workspaces_git | report_published | 0bc76425-d60f-404f-ae3b-ed434fe1cc67 | 8730266e-9e1b-4aa5-927c-2df98838c2e6 |

### Distinct GUIDs for localhost_docker_coco_pharma (counts only; the list is large, 197 rows)

| proof | distinct element_guid | distinct target_guid |
|---|---|---|
| archived | 1 | 0 |
| attach_requested | 5 | 0 |
| connector_read | 0 | 0 |
| database_published | 2 | 0 |
| elements_read_back | 5 | 6 |
| owner_result | 2 | 0 |
| read_failed | 0 | 0 |
| report_published | 1 | 0 |
| restored | 1 | 0 |
| survey_result | 1 | 0 |
| survey_started | 5 | 0 |
| target_attached | 5 | 6 |
| target_detached | 1 | 0 |
| zones_read | 2 | 0 |

Every one of these is re-derivable by reading `select element_guid, target_guid from catalogue_commit_proofs where database_slug = 'localhost_docker_coco_pharma'`.

## 3. architecture_materialized_blueprints and architecture_materialized_components (CLEAR)

Both tables are purely a materialisation ledger: each row is (entity, locator or perspective/cluster, qualified_name, guid, materialized_at) and exists only to remember the Egeria element RE created. The whole row is a pointer, so CLEAR the rows (not just the guid column). architecture_materialized_ports has 0 rows.

### Blueprints per slug

| entity_slug | rows |
|---|---|
| docling | 1 |
| egeria_git | 1 |
| egeria_workspaces_git | 14 |
| sqlglot | 1 |

### Blueprint GUIDs (17 rows)

| entity_slug | perspective | cluster_name | guid |
|---|---|---|---|
| docling | logical | .agents/skills | 538a4378-7809-4d6c-95e3-b6a91d780ff6 |
| egeria_git | deployment | OMAG-Server-Platform | 254dbbe6-1367-40d1-889c-909a1e4489f7 |
| egeria_workspaces_git | deployment | airflow-marquez | ebd4d880-f95a-43d8-841c-599b4e3fd8bb |
| egeria_workspaces_git | deployment | apache-atlas | ada66cb7-bbfb-4058-b7de-460aca5b3889 |
| egeria_workspaces_git | deployment | dagster | 428882e7-f94c-498d-9325-b109a7bba97d |
| egeria_workspaces_git | deployment | deltalake-spark | 442803f6-c65a-4c71-9b67-5f3c893ad107 |
| egeria_workspaces_git | deployment | egeria-freshstart | 814db3ea-abd8-4fcb-82fd-ffb0325a222a |
| egeria_workspaces_git | deployment | egeria-quickstart | b3b6c3fc-cc98-4429-a5bc-adcde2ab8ba7 |
| egeria_workspaces_git | deployment | Freshstart-OMAG-Server-Platform | ad9b2775-f653-47a4-a232-1246cfac32a3 |
| egeria_workspaces_git | deployment | milvus | 95b3343b-ce4c-4a2d-8999-e3c2ca4d1043 |
| egeria_workspaces_git | deployment | mlflow | 51d635d8-fdec-4573-b707-03922e83bd94 |
| egeria_workspaces_git | deployment | prefect | 2fb6b9b4-d83c-4bc7-ba3e-8192065dc7e4 |
| egeria_workspaces_git | deployment | Quickstart-OMAG-Server-Platform | d6450140-2634-4cdb-aab0-0b8143587257 |
| egeria_workspaces_git | deployment | shared-infra | 876226a9-100e-4782-b09c-e160f4657a1b |
| egeria_workspaces_git | deployment | superset-compose | 479fa414-9681-49ea-8363-917f3695be47 |
| egeria_workspaces_git | deployment | unity-catalog | 61fbabef-a39d-48d2-acca-aecb91e1f2d3 |
| sqlglot | logical | .github | 809025b5-cca9-4e9a-a2f7-3a5104138f67 |

### Components per slug

| entity_slug | rows |
|---|---|
| docling | 2 |
| docling_core | 2 |
| egeria_git | 12 |
| egeria_python_git | 4 |
| egeria_trellis | 53 |
| egeria_workspaces_git | 45 |
| sqlglot | 2 |

### Component GUIDs for egeria_git (12 rows)

| entity_slug | scope_locator | guid |
|---|---|---|
| egeria_git | Apache-Kafka | c5777e87-3e0d-4416-998c-771449bc04b3 |
| egeria_git | OMAG-Server-Platform | 72519a6e-797f-48f5-b7a0-7d4e4b42c4ee |
| egeria_git | OMAG-Server-Platform::active-metadata-store | 5d344599-6eef-465f-9a89-ef104eb2919a |
| egeria_git | OMAG-Server-Platform::engine-host | db776741-9283-4b10-929f-1ae3edd2c6a3 |
| egeria_git | OMAG-Server-Platform::integration-daemon | bbe651f5-221f-4868-a830-40eddfc1120b |
| egeria_git | OMAG-Server-Platform::nanny-daemon | 09d26d60-c283-495c-b1ff-9679b16e41f1 |
| egeria_git | OMAG-Server-Platform::simple-metadata-store | ee75390e-5cc9-4614-97c7-0b2981b9e6a3 |
| egeria_git | OMAG-Server-Platform::view-server | 463678a7-8331-45cb-8f79-1e4368b3b0a1 |
| egeria_git | open-metadata-distribution/omag-server-platform | 588b19b1-4148-4ac3-a54f-d07871ccf43c |
| egeria_git | open-metadata-distribution/omag-server-platform/docs | 9df27aca-6203-4392-bacb-cc6128f484a5 |
| egeria_git | open-metadata-distribution/omag-server-platform/docs/http-client-collections | 88713b6b-87fd-456a-861f-cec9a5b91487 |
| egeria_git | PostgreSQL | 52dc52ef-57c8-4c0f-8900-f9169d6415be |

### Component GUIDs for egeria_workspaces_git (45 rows)

| entity_slug | scope_locator | guid |
|---|---|---|
| egeria_workspaces_git | airflow-marquez::airflow-apiserver | 7107e75b-aed3-4887-bdb4-0a58c160d608 |
| egeria_workspaces_git | airflow-marquez::airflow-init | 9f3e5397-56b6-49e5-9133-9f88127de3da |
| egeria_workspaces_git | airflow-marquez::airflow-scheduler | 9e119e75-21e1-40bd-8460-4eae9098e53d |
| egeria_workspaces_git | airflow-marquez::airflow-triggerer | 59fb9f8e-b919-4637-b81a-76f495c3ceea |
| egeria_workspaces_git | Apache-Kafka | d5b06f06-1bee-440f-ad25-983ce69cb384 |
| egeria_workspaces_git | compose-configs/egeria-freshstart | 1d8cc065-f14b-447a-8380-cece84e3ed4d |
| egeria_workspaces_git | compose-configs/egeria-freshstart/PyegeriaWebHandler | 14b8faf0-2232-4c2f-a836-bb23ccf1c319 |
| egeria_workspaces_git | compose-configs/egeria-freshstart/PyegeriaWebHandler/static | eada87c1-c1af-4c84-b851-de89a179bab5 |
| egeria_workspaces_git | compose-configs/egeria-freshstart/secrets | f7106616-720b-4d47-aadb-3404cf947d27 |
| egeria_workspaces_git | compose-configs/egeria-freshstart/sites-available | 1c1d8ad3-4153-4d0d-bfae-9f974c245326 |
| egeria_workspaces_git | compose-configs/egeria-quickstart | 36dcd941-08e4-49d0-93c2-285363e1d737 |
| egeria_workspaces_git | compose-configs/egeria-quickstart/bin | 3f829324-a4a6-48d3-bf8f-d2a7eb3a8334 |
| egeria_workspaces_git | compose-configs/egeria-quickstart/docker-entrypoint-initdb.d | bc18a32e-1bdc-451c-9083-48d0955c9a9d |
| egeria_workspaces_git | compose-configs/egeria-quickstart/docker-entrypoint-initdb.d/data | 36be306e-6af5-48f0-961e-df78c313516c |
| egeria_workspaces_git | compose-configs/egeria-quickstart/PyegeriaWebHandler | 971cb322-7c47-4671-a91e-786a10855dbf |
| egeria_workspaces_git | compose-configs/egeria-quickstart/PyegeriaWebHandler/static | 191845ae-0932-4c88-a9a8-0ed6d24e20db |
| egeria_workspaces_git | compose-configs/egeria-quickstart/PyegeriaWebHandler/tests/browser | 83cc2513-cb28-430d-9558-8ebc078c51ae |
| egeria_workspaces_git | compose-configs/egeria-quickstart/secrets | 21ea67d6-b1ef-4bad-9c98-2a547c5e017f |
| egeria_workspaces_git | compose-configs/egeria-quickstart/servers | 40db89fe-b19e-43f9-b1ac-a969a03f4edd |
| egeria_workspaces_git | compose-configs/egeria-quickstart/sites-available | dd8f406d-5893-4e95-8fb0-0388cf141a36 |
| egeria_workspaces_git | compose-configs/egeria-quickstart/src/main/java/io/openlineage/proxy | ee022143-f9c4-47ad-9b22-d75773d98fb1 |
| egeria_workspaces_git | compose-configs/egeria-quickstart/watchdog | 30877188-3321-4837-8b2d-6fd860635f7e |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/airflow-marquez | 72d0776b-4e4d-4db5-b136-919fa0fc9045 |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/apache-atlas | f4b0d1d7-f244-410a-b9e2-3075d487007e |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/dagster | 20b3114f-b3de-4e5e-8ddf-b84c8c896ccc |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/duckdb | fb926d37-63e3-448d-9852-f0d1872d11d3 |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/milvus | a1f7c428-6b78-4bb6-8422-8bb17ad52434 |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/mlflow | 1703c571-4dbc-4f7a-b64d-3a4456e02e8e |
| egeria_workspaces_git | compose-configs/optional-associated-runtimes/prefect | a2e8efba-1064-475a-8b3c-20850de0e3e7 |
| egeria_workspaces_git | compose-configs/shared-infra | 3ccd2d2b-eab5-4890-b27a-230f972a5cc1 |
| egeria_workspaces_git | compose-configs/shared-infra/autoheal | 994b9ff6-b94a-4536-9d26-c4fb7eb51422 |
| egeria_workspaces_git | compose-configs/shared-infra/docker-entrypoint-initdb.d | 1e8d4b72-549a-411d-aeb7-2fc15d11cbf0 |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform | 01148ed6-edcf-4665-97c2-f28fcb8b0146 |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform::fs-engine-host | cb66d98b-d7b5-4ca7-8c90-bbb85cbbb750 |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform::fs-integration-daemon | 1fe9f0e4-5433-47dc-83c2-7d5f4b5158f0 |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform::fs-metadata-store | d83a7c0e-1662-49e9-94fe-801cc62c256b |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform::fs-nanny-daemon | 96a56362-c805-4d85-a7ed-ea662da39770 |
| egeria_workspaces_git | Freshstart-OMAG-Server-Platform::fs-view-server | ffc638dc-1956-4b9d-8d8a-259c0f22bc4c |
| egeria_workspaces_git | PostgreSQL | 4b8b4953-7b70-426e-972c-7c325a81388f |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform | 8347a6f3-a53f-4fb3-bb15-8b8abb050f42 |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform::qs-engine-host | 04f0db89-14b4-4aff-aa12-71d6d0dac0bf |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform::qs-integration-daemon | d37d0bc7-55a9-4962-b6fb-4dfd6f1e1b05 |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform::qs-metadata-store | 707e55d4-3926-4a0d-b65f-59afec44f69f |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform::qs-nanny-daemon | 0b6cfeeb-258c-42a9-9073-c6a167e89c10 |
| egeria_workspaces_git | Quickstart-OMAG-Server-Platform::qs-view-server | f66b601f-a508-4daa-92e3-5dc7da45429c |

Other slugs (docling 2, docling_core 2, egeria_python_git 4, sqlglot 2, egeria_trellis 53): counts only above; GUIDs are one `select` away. The architecture_component_verdicts table (111 rows) is KEEP; it has no guid column.

## 4. sub_resources with egeria_guid (CLEAR column; keep the rows)

| resource_type | resource_slug | rows | rows with egeria_guid |
|---|---|---|---|
| repo | amundsen | 2 | 0 |
| repo | egeria_git | 34 | 2 |
| repo | egeria_workspaces_git | 32 | 32 |
| repo | polaris | 10 | 10 |
| repo | sqlglot | 3 | 2 |

Total rows 81, 46 with a non-empty egeria_guid. The rows are RE's own cataloguing of sub-resources (KEEP); egeria_guid is the published pointer.

### sub_resources GUIDs for egeria_git (2)

| locator | kind | egeria_guid |
|---|---|---|
| open-metadata-implementation | folder | 442f2963-c0f6-438a-b99f-9aaa0c151e5b |
| open-metadata-implementation/README.md | file | 320e9036-2a78-447e-bd04-a7be64a937a8 |

### sub_resources GUIDs for egeria_workspaces_git (32)

| locator | kind | egeria_guid |
|---|---|---|
|  | folder | 67bd513d-e34e-4c0e-9770-c03aa49aa870 |
| CHANGELOG.md | file | 923c3c0b-98e2-46c5-b161-cc21a1508f30 |
| .claude | folder | 2d485fab-bf12-424f-8dad-d02b652aa118 |
| coco-data | folder | cfec2cdd-440a-450d-a158-5d129733661a |
| coco-workbooks | folder | 47f43368-91b2-44ad-85e1-239629b53989 |
| coco-workbooks/README.md | file | 61d822b3-8677-47fa-96fe-e61ed4c092b3 |
| CODE_OF_CONDUCT.md | file | c5499461-9418-4120-9ddd-619b7dd46540 |
| compose-configs | folder | f273ccd2-994e-433c-b795-d0498f3a19fb |
| compose-configs/README.md | file | 0bc7d045-e6fe-4f1b-8710-5a7dadf20370 |
| CONTRIBUTING.md | file | d2a79599-1fe7-4bfd-ab89-29bdba1ba3cf |
| design-docs | folder | cd45f4e8-ed5e-4156-ac75-65c2910e85e7 |
| design-patterns | folder | 43db5c89-a189-4c83-a27e-f2dec7493421 |
| design-patterns/README.md | file | 82565624-365c-47d3-bdb4-0be6fa03771a |
| docs | folder | adc04990-d9b6-4370-9d04-c82845efb83e |
| exchange-freshstart | folder | e860f411-fb2f-4ba1-bce6-1cba172872d4 |
| exchange-freshstart/README.md | file | 0a1abcd7-f526-4a63-82eb-d44b20737f43 |
| exchange-quickstart | folder | 26c69c5f-7207-4adc-b3a9-749b16ecf2bc |
| exchange-quickstart/README.md | file | e13581a5-baa1-4433-96ad-de5f63eafe61 |
| .github | folder | 197ac059-d04e-4058-bef9-c96203f8ce51 |
| LICENSE | file | c7400d8e-4b33-470b-babf-92868318d780 |
| portal-docs | folder | c71b3278-4ce5-4f8a-a8b7-129e04d38c1a |
| README.md | file | 60e834b5-91e6-4466-a1bc-9c72f7378106 |
| (root) | folder | df07677d-9d1d-4228-8ca9-c07e266d1396 |
| runtime-volumes | folder | 2330a543-e511-45bc-b3ca-6606eec7f598 |
| runtime-volumes/README.md | file | 47c63cf3-43ae-4a44-b73f-16d9cecfdbad |
| SECURITY.md | file | a144d6a5-a75b-4d52-960a-32100d4cfd8c |
| templates | folder | 2d9d79d8-2206-4533-a9f4-2641885b9b60 |
| templates/README.md | file | b4f3e380-a597-4348-b73f-aa8a52a46801 |
| tests | folder | 1245ed9b-d7cb-44e6-a20e-dc1b566b5be3 |
| work | folder | 9abdd96a-d9a3-43b8-bc7f-8a27dae1afd5 |
| workbooks | folder | 6362e07c-db46-4a38-a265-e1e0a57388f1 |
| work/README.md | file | 65636159-c546-4efc-87dd-80744908eaea |

### sub_resources GUIDs for amundsen (0)

| locator | kind | egeria_guid |
|---|---|---|

### sub_resources GUIDs for polaris (10)

| locator | kind | egeria_guid |
|---|---|---|
|  | folder | 7c516c5f-21dc-4c2a-ba94-8d9fea421224 |
| api | folder | 458155a7-adf1-40d3-8eae-104f0992f102 |
| api/README.md | file | 5068d3e6-fcb7-4256-a825-29a5b113dfb7 |
| client | folder | 0a7fa749-3222-4c1e-8754-381cc479cd56 |
| README.md | file | c6234b0f-be5b-46ba-81a3-7780d87b73ef |
| site | folder | 719b557b-00a6-44ca-ae8a-11b729247bd7 |
| site/README.md | file | a25aad69-d97d-489b-9693-291a613a4eb5 |
| spec | folder | 8cdccdc5-ae86-4ace-8e16-cbf6a555bdb8 |
| spec/README.md | file | b60d5de5-fe55-447f-97c0-70aa997b070f |
| tools | folder | 7eed5b84-757c-46c2-a251-0ed4e6e1bd59 |

### sub_resources GUIDs for sqlglot (2)

| locator | kind | egeria_guid |
|---|---|---|
|  | folder | fbf9b934-e1c3-48e7-af1a-b10355465252 |
| CHANGELOG.md | file | a8c0cfa8-58e1-442b-97a1-2434188c1beb |

## 5. egeria_outbox (CLEAR pointer column egeria_guid; the queue itself is spent history)

Every row records a publish to Egeria (payload, qualified_name, result GUID). After the reset a done row proves nothing is in Egeria; none is a RE decision. The decision to publish lives in the resource rows, not here. Total rows 5230 at snapshot (an earlier look in the same session saw 5239: 9 annotation rows were removed by another writer meanwhile, so the registry is live and counts are as of the timestamp); egeria_guid non-empty on 5203.

### Status by element_kind

| status | element_kind | rows | non-empty egeria_guid |
|---|---|---|---|
| dead | collection_membership | 10 | 0 |
| done | annotation | 4635 | 4635 |
| done | annotation_link | 535 | 535 |
| done | catalogue_schema_attach | 12 | 12 |
| done | catalogue_schema_leave_out | 1 | 1 |
| done | collection_membership | 14 | 0 |
| done | doc_source_publish | 14 | 14 |
| done | doc_source_unpublish | 6 | 6 |
| done | resource_list | 3 | 0 |

### Per slug

| entity_slug | rows | non-empty egeria_guid |
|---|---|---|
| amundsen | 229 | 229 |
| docling | 54 | 54 |
| docling-family | 1 | 0 |
| dts-treasury-data | 1 | 0 |
| egeria_docs | 112 | 112 |
| egeria_git | 3449 | 3435 |
| egeria_python_git | 247 | 247 |
| egeria_trellis | 148 | 148 |
| egeria-understanding | 11 | 0 |
| egeria_workspaces_git | 852 | 852 |
| laz_local_adventureworks | 13 | 13 |
| localhost_docker_coco_pharma | 16 | 16 |
| sqlglot | 97 | 97 |

### Non-terminal rows (status other than done): 10; all are status `dead`, none pending, claimed or failed-retrying

| id | slug | kind | status | attempts | egeria_guid |
|---|---|---|---|---|---|
| 68918 | egeria-understanding | collection_membership | dead | 8 |  |
| 68919 | egeria-understanding | collection_membership | dead | 8 |  |
| 68920 | egeria-understanding | collection_membership | dead | 8 |  |
| 68921 | egeria-understanding | collection_membership | dead | 8 |  |
| 68922 | egeria-understanding | collection_membership | dead | 8 |  |
| 68956 | egeria-understanding | collection_membership | dead | 8 |  |
| 68957 | egeria-understanding | collection_membership | dead | 8 |  |
| 68958 | egeria-understanding | collection_membership | dead | 8 |  |
| 68959 | egeria-understanding | collection_membership | dead | 8 |  |
| 68960 | egeria-understanding | collection_membership | dead | 8 |  |

The dead rows are all collection_membership attaches for investigation egeria-understanding (a working set folio whose collection GUID is in section 7).

## 6. app_settings claim and pointer keys

app_settings has 105 keys. None of the claim/pointer prefixes you listed exist:

| prefix | keys present |
|---|---|
| egeria_register_claim:: | 0 |
| egeria_server_claim:: | 0 |
| egeria_server_unconfirmed:: | 0 |
| egeria_server_guid:: | 0 |
| egeria_server_cred_slug:: | 0 |
| egeria_asset_guid:: | 0 |
| repo_node_reclassifications:: | 0 |

Keys present, by prefix:

| prefix | keys | class |
|---|---|---|
| repo_dependency_confirmations:: | 4 | KEEP |
| repo_survey_index:: | 4 | KEEP |
| repo_survey_step:: | 96 | KEEP |

Keys with no `::` namespace:

| key | value is a bare UUID | class |
|---|---|---|
| egeria.github_source_control_library_guid | yes | CLEAR |

`egeria.github_source_control_library_guid` is a pointer to a SourceControlLibrary-type element in Egeria: CLEAR (it is re-found or re-created by RE on the next publish, so confirm that behaviour before relying on it).

### Values that contain a UUID somewhere inside a larger value (no value printed)

| key | distinct UUIDs inside | of which match a pointer GUID listed in this file |
|---|---|---|
| repo_survey_step::egeria_workspaces_git::repo_data_profiling | 1 | 0 |
| repo_survey_step::egeria_workspaces_git::repo_file_classification | 1 | 0 |
| repo_survey_step::egeria_workspaces_git::repo_secret_scan | 1 | 0 |

These three are survey step outputs (repo_survey_step::egeria_workspaces_git::repo_data_profiling, repo_file_classification, repo_secret_scan): analysis results, KEEP. The UUIDs inside are content of the repository being analysed, not Egeria pointers. The zero in the third column is the evidence for that.

`repo_dependency_confirmations::*` (4 keys) are dependency confirmations: KEEP. `repo_survey_index::*` and `repo_survey_step::*` are survey step outputs: KEEP. There are no `repo_node_reclassifications::` keys in this registry at snapshot time.

## 7. Project, collection and list pointers

### investigations.egeria_project_guid (CLEAR column; keep the investigation)

| slug | egeria_project_guid | egeria_project_qualified_name | egeria_project_status | egeria_binding | classification |
|---|---|---|---|---|---|
| egeria-understanding | 4256e995-98d6-47df-91ab-757920103ac3 | Project::Investigation::egeria-understanding | linked | egeria | PersonalProject |

1 of 8 investigations carries a GUID. Also on that table: egeria_project_qualified_name, egeria_project_status, egeria_free_text_name, egeria_binding (`egeria` or `local`). The qualified name and status are the linked-state mirror and should be cleared with the GUID; egeria_binding is RE's own choice (KEEP). investigations.purposes_json, hypothesis and the rest are KEEP.

### entity_egeria_project_context (8 linked rows; CLEAR the guid and qualified-name columns; the status choice is RE's decision)

| entity_type | entity_slug | status | egeria_project_guid |
|---|---|---|---|
| repo | egeria_docs | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_git | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_git | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_python_git | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_trellis | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_workspaces_git | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| repo | egeria_workspaces_git | linked | 4256e995-98d6-47df-91ab-757920103ac3 |
| database | laz_local_marquez | linked | 4256e995-98d6-47df-91ab-757920103ac3 |

| status (all 106 rows) | rows |
|---|---|
| deferred | 1 |
| linked | 8 |
| personal | 1 |
| unset | 96 |

The decisions `unset`, `personal`, `deferred` and `linked` are the owner's choices (KEEP). After the wipe the 8 `linked` rows point at nothing; RE needs to decide whether they revert to `unset` or stay `linked` and are republished. That is a design decision, not an inventory fact.

### working_sets.egeria_collection_guid (1 of 12; CLEAR column)

| slug | egeria_collection_guid | qualified_name |
|---|---|---|
| egeria-understanding-folio | b3883e29-44e0-4b43-bb17-f8f1d6d40da1 |  |

### work_lists.egeria_guid and published_at (1 of 4; CLEAR both columns; the work list and members are KEEP)

| slug | egeria_guid | published_at |
|---|---|---|
| wl-b37710b3b4 | d8323a5b-ad2a-4775-aadf-acee2df78441 | 2026-09-10T02:51:40.393483+00:00 |

### doc_sources (9 rows; 8 with pointers)

| id | entity_type | entity_slug | egeria_external_ref_guid | egeria_link_relationship_guid |
|---|---|---|---|---|
| 4711d538faa8ccc3 | database | laz_local_adventureworks | 6eea8076-51d5-41ea-b943-7c5b43dfa89b | 59fd7cb7-1d95-43cb-ad9c-ed18e0c30bf0 |
| 5f6f5c30751c52e0 | repo | amundsen | 2e0da776-86df-4e7f-bb4b-247a2fe67bb6 | 4d7d27c5-8409-4479-b670-ca669904100a |
| 801a72bbd291c52d | database | localhost_docker_coco_pharma | 4e117b71-f3dc-4b82-a641-2779d094e832 | bfa0dfdc-21e8-46c1-af0d-020873d91b69 |
| 8b1469dfc92a89f2 | database | laz_local_adventureworks | 1f39f83b-7ebc-4c9e-b915-b5c8a59035eb | 5e87d236-c239-4a94-bc21-847dfa6922de |
| a84e5467ba0870e3 | database | laz_local_adventureworks | 574ef97f-a6b3-4348-9068-dfb5ec5866af | 8cbae34c-3c66-4ff0-9d10-1ccb644a31b0 |
| a9552e554864b1ac | repo | egeria_workspaces_git | 606922fb-5b55-4a37-bd7d-178c05d74daa | 73ccc3f9-f102-4a87-b7c7-26b2e5b967c1 |
| b5dbf65557c5224c | repo | egeria_docs | 1a1c6ada-3f57-4a43-b164-8ab4f1fa0472 | 1504fd2f-9791-4fbf-bcbf-20176d357cba |
| de142ed2794beb1c | repo | egeria_git | 1a1c6ada-3f57-4a43-b164-8ab4f1fa0472 | 69c3987d-33c8-4e57-a2b6-bc2447405696 |

Class: the two guid columns CLEAR; url, label, probe results and ingestion counts KEEP.

### rfa_actions (3 rows)

| id | egeria_todo_guid | egeria_notelog_guid | rfa_status |
|---|---|---|---|
| 530fe7b6-7b13-4332-a002-94ce13b44a4c::0 | cdadd7ab-578f-4b05-9a98-d33ab10c54aa |  | completed |
| 9f92c4ac-5a77-4faa-9add-edaf816b5066::2 | 77c3308e-9dcd-4d90-8836-209464c79b17 |  | completed |
| b5348831-cdd7-4432-aa93-7f59ddeed7e8::2 | ee4d9f34-8773-491f-bd0f-65a6a85a4036 | 707c53eb-96f4-4eb1-9e0b-0ff2ede3ca97 | deferred |

Class: the two guid columns CLEAR (plus synced_at, sync_error, notes_synced_value as the sync mirror); status, assignee, resolution_note, notes are the owner's actions (KEEP).

### notification_subscriptions (6 rows; egeria_notification_type_guid is empty on all 6)

| id | entity_type | entity_slug | guid | qualified_name |
|---|---|---|---|---|
| 1 | repo | sqlglot |  |  |
| 2 | repo | sqlglot |  |  |
| 6 | repo | egeria_git |  |  |
| 7 | repo | docling |  |  |
| 8 | database | laz_local_adventureworks |  |  |
| 9 | database | laz_local_adventureworks |  |  |

Class: KEEP (nothing to clear on the GUID; qualified_name is a name, not an Egeria identity).

### survey_definition_cache (22 rows; process_guid and process_qualified_name: CLEAR the whole cache)

| entity_type | rows | distinct process_guid |
|---|---|---|
| database | 4 | 3 |
| repo | 18 | 5 |

This is a cache of the survey process looked up in Egeria; RE re-resolves it. The 22 process GUIDs will dangle.

### feedback.element_guid (4 of 22 rows)

| id | page | element_guid |
|---|---|---|
| 147a4865-f988-42f8-a9dd-685fecdb0f20 | /next?type=db&resource=localhost_docker_coco_pharma | answer:localhost_docker_coco_pharma:Is this database alive — writes since the statistics were reset, last vacuum or analyse, and is anything reading it? |
| 5027badb-673d-4bd5-ab17-2b5069921a4b | /next?resource=backstage | answer:backstage:What languages and file types make up this repository? |
| 99f2f0c8-157b-4638-83e4-1ffdc7c2a3e5 |  | answer:localhost_docker_coco_ods:does this matter |
| fe7ade2a-55f4-49ef-979d-e136d2789097 | /next?type=db&resource=localhost_docker_coco_pharma | answer:localhost_docker_coco_pharma:Is this database a primary or a replica, is it clustered, and is WAL archiving or backup configured? |

Class: feedback rows KEEP (the user's words); element_guid is the Egeria element the user was looking at, which will dangle (CLEAR the column or leave it as history).

## 8. Publish-state rows: survey and report GUIDs

Mixed class. The row says "RE published or surveyed X at time T" (history, KEEP). The report/annotation GUID points at an Egeria SurveyReport or Annotation that the reset deletes (CLEAR the column). A deleted report is also what makes `published_at` misleading after the wipe, so the right clearing for the publish-state tables below is decided by the owner: clear the whole row (so RE re-publishes) or clear only the GUID.

### egeria_report_guid by table and slug (non-empty)

| table | slug | rows | non-empty egeria_report_guid |
|---|---|---|---|
| database_surveys | egeria_optional_prefect_db | 6 | 0 |
| database_surveys | laz_local_adventureworks | 62 | 0 |
| database_surveys | laz_local_egeria_info | 1 | 0 |
| database_surveys | laz_local_marquez | 1 | 1 |
| database_surveys | laz_local_treasury | 3 | 1 |
| database_surveys | laz_local_usda | 1 | 1 |
| database_surveys | localhost_docker_coco_pharma | 79 | 10 |
| project_egeria_surveys | amundsen | 1 | 1 |
| project_egeria_surveys | egeria_docs | 5 | 5 |
| project_egeria_surveys | egeria_git | 10 | 10 |
| project_egeria_surveys | egeria_python_git | 4 | 4 |
| project_egeria_surveys | egeria_trellis | 5 | 5 |
| project_egeria_surveys | egeria_workspaces_git | 8 | 8 |
| project_egeria_surveys | sqlglot | 1 | 1 |
| project_published_analyses | amundsen | 1 | 1 |
| project_published_analyses | egeria_git | 106 | 106 |
| project_published_analyses | egeria_workspaces_git | 36 | 36 |
| project_published_analyses | sqlglot | 1 | 1 |
| project_published_annotation_types | amundsen | 1 | 1 |
| project_published_annotation_types | egeria_docs | 11 | 11 |
| project_published_annotation_types | egeria_git | 43 | 43 |
| project_published_annotation_types | egeria_python_git | 8 | 8 |
| project_published_annotation_types | egeria_trellis | 11 | 11 |
| project_published_annotation_types | egeria_workspaces_git | 23 | 23 |
| project_published_annotation_types | sqlglot | 1 | 1 |

Whole-table totals: database_surveys 153 rows / 13 non-empty; project_egeria_surveys 34 / 34; project_published_analyses 144 / 144; project_published_annotation_types 98 / 98; filesystem_surveys 0 rows. database_surveys.survey_data (the measured survey, KEEP) is separate from the pointer.

### step_runs engine_action_guid and survey_report_guid (non-empty)

| slug | entity_type | rows | non-empty engine_action_guid | non-empty survey_report_guid |
|---|---|---|---|---|
| laz_local_adventureworks | database | 62 | 1 | 0 |
| laz_local_marquez | database | 2 | 2 | 2 |
| laz_local_usda | database | 2 | 2 | 1 |
| localhost_docker_coco_pharma | database | 29 | 9 | 9 |

step_runs has 2002 rows; 14 carry an engine_action_guid and 12 a survey_report_guid. Rows are run history (KEEP: step_key, executor, metrics, declared, disagreement); the two GUID columns are CLEAR. resource_reachability.engine_action_guid has 0 rows.

### native_survey_annotations (1074 rows, every row carries report_guid, engine_action_guid and annotation_guid)

| slug | entity_type | rows | distinct report_guid | distinct engine_action_guid | distinct annotation_guid |
|---|---|---|---|---|---|
| laz_local_marquez | database | 98 | 2 | 2 | 98 |
| laz_local_usda | database | 79 | 1 | 1 | 79 |
| localhost_docker_coco_pharma | database | 897 | 9 | 9 | 873 |

| slug | report_guid | annotations |
|---|---|---|
| laz_local_marquez | ba7634bb-e6d5-4e3f-b9ff-0d02631ac2e3 | 49 |
| laz_local_marquez | d66412c4-1d24-4ede-9bc6-a8153ff7d507 | 49 |
| laz_local_usda | 6cd4b086-f378-4906-92d8-349ad06b34ff | 79 |
| localhost_docker_coco_pharma | 03b908a5-2605-48fc-b79b-5dbf56b200fe | 318 |
| localhost_docker_coco_pharma | 09b2a5f1-b701-464c-8a3a-a13b6794e06a | 91 |
| localhost_docker_coco_pharma | 231a3d06-177d-4bb4-8d1e-3b69f29180ac | 56 |
| localhost_docker_coco_pharma | 6fa16516-cd73-4d7d-bacb-48e0297a37a6 | 69 |
| localhost_docker_coco_pharma | 85cff103-3ae2-4717-9519-66d7d3dadf3a | 56 |
| localhost_docker_coco_pharma | 969f7727-0b0d-4fcf-855f-cbfae2fc863a | 91 |
| localhost_docker_coco_pharma | b99463ea-614c-4291-a138-1c48a2bdc2eb | 56 |
| localhost_docker_coco_pharma | bf44a57c-469a-48ae-bf91-c6a2d83e2cff | 69 |
| localhost_docker_coco_pharma | f993ac91-c3af-4e88-b742-2669c80c44cf | 91 |

Class: this table is a read-back of annotations that Egeria's native surveyor produced. The three GUID columns are CLEAR; the rows themselves (summary, explanation, confidence, detail_json, read_at) are an RE-side copy of Egeria content, not an RE decision. Judgement call for the owner: clear the rows (they describe reports that no longer exist) or keep them as a record of what the native survey found. Because the Egeria surveyor will need to run again to regenerate them, the rows are the only copy of that output once the reset happens.

### activity_log rows whose detail contains egeria_report_guid: 473 (473 counting items_json and annotations_json too)

| entity_slug | rows |
|---|---|
| amundsen | 7 |
| artwork | 2 |
| backstage | 6 |
| course_material | 2 |
| data_prep_kit | 7 |
| deep_causality | 6 |
| docling | 68 |
| docling_core | 4 |
| egeria_docs | 44 |
| egeria_git | 59 |
| egeria_python_git | 54 |
| egeria_trellis | 46 |
| egeria_workspaces_git | 64 |
| enterprise_inference | 2 |
| kafka | 2 |
| laz_local_adventureworks | 23 |
| laz_local_egeria_info | 2 |
| laz_local_treasury | 2 |
| localhost_docker_coco_pharma | 24 |
| marquez | 1 |
| milvus | 3 |
| monocle | 15 |
| opea_project_github_io | 1 |
| openlineage | 3 |
| openmetadata | 6 |
| polaris | 4 |
| project_explorer | 6 |
| ryoma | 5 |
| sqlglot | 1 |
| unitycatalog | 2 |
| unitycatalog_python | 2 |

Class: KEEP (activity history). The GUID is embedded in text; it records what happened and does not point anywhere RE reads. publish_run_id on every row (2358 of 2358) is RE's own run id.

project_analysis_findings.egeria_annotation_guid is a pointer column with 0 non-empty values across 304,163 rows (all NULL): nothing to clear; the rows are findings, KEEP.

## 9. The cataloguer's target list

Not recorded as a list. A search of every column name for catalog_target, cataloguer and cataloger found nothing. What RE does record:

- catalogue_commit_proofs rows of kind `target_attached` (12) and `target_detached` (1), each with element_guid and target_guid (both CLEAR); these are events, not the current target list.
- egeria_outbox element_kind `catalogue_schema_attach` (12 done) and `catalogue_schema_leave_out` (1 done), with the result GUID.
- The current target list lives only in Egeria (the cataloguer integration connector configuration). After the reset it is gone and must be re-attached.

## 10. Egeria metadataCollectionId as RE last saw it

RE does not store it. Evidence: no column in any table has a name containing metadata_collection or metadatacollection; 0 app_settings keys or values mention it; 0 activity_log detail/items_json rows; 0 egeria_outbox payload_json rows; 0 catalogue_commit_proofs detail_json or qualified_name rows contain the string `metadataCollection`. Nothing to clear. A quick check against the reset: RE's own pointer GUIDs are element GUIDs, not metadata collection ids, so the reset (which creates a new repository) does not need RE to forget a collection id.

## 11. Every column whose name contains "guid" (information_schema scan)

| table.column | rows | non-empty | class |
|---|---|---|---|
| architecture_materialized_blueprints.guid | 17 | 17 | CLEAR (whole row) |
| architecture_materialized_components.guid | 120 | 120 | CLEAR (whole row) |
| architecture_materialized_ports.guid | 0 | 0 | CLEAR (whole row; 0 rows) |
| catalogue_commit_proofs.element_guid | 229 | 175 | CLEAR column; ledger rows are history |
| catalogue_commit_proofs.target_guid | 229 | 89 | CLEAR column; ledger rows are history |
| database_surveys.egeria_report_guid | 153 | 13 | CLEAR column; survey_data and row KEEP |
| databases.egeria_asset_guid | 17 | 6 | CLEAR column; row KEEP |
| doc_sources.egeria_external_ref_guid | 9 | 8 | CLEAR column; row KEEP |
| doc_sources.egeria_link_relationship_guid | 9 | 8 | CLEAR column; row KEEP |
| egeria_linkage_status.stale_guid | 3 | 3 | CLEAR (row is a derived cache) |
| egeria_outbox.egeria_guid | 5230 | 5203 | CLEAR column; queue is spent history |
| entity_egeria_project_context.egeria_project_guid | 106 | 8 | CLEAR column; status choice KEEP |
| feedback.element_guid | 22 | 4 | CLEAR column (or leave as history); feedback KEEP |
| file_systems.egeria_asset_guid | 0 | 0 | CLEAR column; 0 rows |
| filesystem_surveys.egeria_report_guid | 0 | 0 | CLEAR column; 0 rows |
| investigations.egeria_project_guid | 8 | 1 | CLEAR column; investigation KEEP |
| native_survey_annotations.annotation_guid | 1074 | 1074 | CLEAR column; row is a read-back copy (judgement) |
| native_survey_annotations.engine_action_guid | 1074 | 1074 | CLEAR column; row is a read-back copy (judgement) |
| native_survey_annotations.report_guid | 1074 | 1074 | CLEAR column; row is a read-back copy (judgement) |
| notification_subscriptions.egeria_notification_type_guid | 6 | 0 | KEEP (empty on all rows) |
| project_analysis_findings.egeria_annotation_guid | 304163 | 0 | KEEP (all NULL) |
| project_egeria_surveys.egeria_report_guid | 34 | 34 | CLEAR column; publish-state row, owner decides row |
| project_published_analyses.egeria_report_guid | 144 | 144 | CLEAR column; publish-state row, owner decides row |
| project_published_annotation_types.egeria_report_guid | 98 | 98 | CLEAR column; publish-state row, owner decides row |
| projects.egeria_asset_guid | 68 | 7 | CLEAR column; project row KEEP |
| resource_reachability.engine_action_guid | 0 | 0 | CLEAR column; 0 rows |
| rfa_actions.egeria_notelog_guid | 3 | 1 | CLEAR column; row KEEP |
| rfa_actions.egeria_todo_guid | 3 | 3 | CLEAR column; row KEEP |
| step_runs.engine_action_guid | 2002 | 14 | CLEAR column; run history KEEP |
| step_runs.survey_report_guid | 2002 | 12 | CLEAR column; run history KEEP |
| sub_resources.egeria_guid | 81 | 46 | CLEAR column; row KEEP |
| survey_definition_cache.process_guid | 22 | 22 | CLEAR (cache; row can go) |
| work_lists.egeria_guid | 4 | 1 | CLEAR column; work list KEEP |
| working_sets.egeria_collection_guid | 12 | 1 | CLEAR column; working set KEEP |

Pointer-like columns whose name does not contain "guid" (also from information_schema): egeria_outbox.qualified_name and entity_egeria_project_context.egeria_project_qualified_name, investigations.egeria_project_qualified_name, working_sets.egeria_collection_qualified_name, survey_definition_cache.process_qualified_name, notification_subscriptions.egeria_notification_type_qualified_name, project_published_* and architecture_materialized_*.qualified_name. These are names that Egeria uses as identity; after the reset they are stale in the same way as the GUIDs.

## KEEP inventory (row counts, no pointers to clear)

| table | what it is | rows |
|---|---|---|
| architecture_component_verdicts | verdicts on blueprint components | 111 |
| resource_scope_events | scope events (the newer table) | 1 |
| catalogue_scope_events | scope events (older Curate-era table) | 30 |
| catalogue_scope_baselines | scope baselines | 2 |
| resource_curation | curation records | 13 |
| resource_journal | journal | 3 |
| resource_curator_notes | curator notes | 3 |
| resource_feedback | resource feedback | 7 |
| resource_tags | tags | 7 |
| repo_dispositions | repo dispositions | 25 |
| repo_disposition_history | repo disposition history | 54 |
| project_groups | groups | 9 |
| group_changes | group changes | 0 |
| work_list_members | work list members | 23 |
| work_list_runs | work list runs | 147 |
| work_lists | work lists (except the two columns in section 7) | 4 |
| working_set_members | working set members | 131 |
| investigation_resource_lists | investigation resource lists | 12 |
| investigation_members | investigation members | 0 |
| rfa_dismissals | RFA dismissals | 0 |
| analysis_gaps | analysis gaps | 85 |
| project_analysis_metrics | annotation measurements | 160754 |
| project_analysis_findings | annotation findings | 304163 |
| activity_log | activity history | 2358 |
| runs | run queue history | 346 |
| resource_schedules | schedules | 10 |
| resource_context | resource context | 4 |
| annotation_types | annotation type registry | 7 |
| conversation_history | chat history | 114 |
| context_compiles | context compiles | 819 |

Not enumerated one by one (all KEEP, no Egeria pointer): the surveyed-database content tables (database_columns, database_tables, database_schemas, database_column_profiles, database_grants, database_sql_objects, database_table_activity, database_survey_coverage), project_* analysis, code and git content tables, project_stats, the RAG corpus tables (embedding columns), board_summary, egeria_call_timings, query_log, chunk_feedback, discovery_sources, db_servers, project_aliases.

Scope events specifically: resource_scope_events holds 1 row and catalogue_scope_events 30 rows plus 2 baselines in catalogue_scope_baselines; none has a guid column; all KEEP (the owner's Include/Leave-out decisions).

## Pending clean-up the wipe closes

These items are stale or leftover work that the Egeria `egeria` database reset removes on the Egeria side. The registry search below shows how much of each RE still references.

- rehearsal-1 leftovers, the rftrial tree, roll-forward leftovers: searched every text column of every non-RAG table (all slugs, keys, qualified names, locators, schema names, descriptions, payloads, details, summaries, notes) for the strings `rehearsal`, `rftrial`, `rolledforward`, `rolled_forward` and `roll_forward`, case-insensitive. Result: 0 matching rows in the registry. Also 0 in activity_log (detail, summary, entity_slug), 0 in egeria_outbox payload_json, 0 in catalogue_commit_proofs (detail_json, schema_name, qualified_name). These leftovers exist only in Egeria (and in Egeria's own Postgres), not in RE's registry.
- The two `*_rolledforward_*` schemas: information_schema.schemata of the RE registry database (egeria_advisor) contains these schemas: artifact_tree, information_schema, pg_catalog, public, resource_explorer. None contains `rolledforward`. database_schemas (the registry's surveyed-schema table, 1,240 rows) has 0 schema names matching rolledforward, rehearsal, rftrial, rolled or forward. So the two schemas are in a different database, not the registry, and RE has no row about them.
- Blueprint 254dbbe6: present in the registry as architecture_materialized_blueprints row for egeria_git / deployment / OMAG-Server-Platform, guid 254dbbe6-1367-40d1-889c-909a1e4489f7. Its 7 components are all present in architecture_materialized_components (entity egeria_git):

| scope_locator | guid |
|---|---|
| OMAG-Server-Platform | 72519a6e-797f-48f5-b7a0-7d4e4b42c4ee |
| OMAG-Server-Platform::active-metadata-store | 5d344599-6eef-465f-9a89-ef104eb2919a |
| OMAG-Server-Platform::engine-host | db776741-9283-4b10-929f-1ae3edd2c6a3 |
| OMAG-Server-Platform::integration-daemon | bbe651f5-221f-4868-a830-40eddfc1120b |
| OMAG-Server-Platform::nanny-daemon | 09d26d60-c283-495c-b1ff-9679b16e41f1 |
| OMAG-Server-Platform::simple-metadata-store | ee75390e-5cc9-4614-97c7-0b2981b9e6a3 |
| OMAG-Server-Platform::view-server | 463678a7-8331-45cb-8f79-1e4368b3b0a1 |

Matched 7 of the 7 listed component prefixes. The other 5 egeria_git components (Apache-Kafka, PostgreSQL, and three open-metadata-distribution/omag-server-platform paths) are in section 3. CLEAR them all with the rest of section 3.

Everything above is an inventory of what the registry holds. Nothing was changed.

