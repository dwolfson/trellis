# DESIGN — Is RE/Egeria a viable migration path for Amundsen users? (2026-10-12)

From the design session at the owner's request. Sources: the Amundsen
repository and its README, databuilder, metadata-service and frontend
docs as of 2026-10-12; RE's own model; Egeria's open types. Nothing in
this note was measured against a live Amundsen instance.

## 1. Amundsen's state

- **Archived.** The repository's archived flag is set; the README says
  "Due to inactivity, this project was archived in September 2026. The
  contents will remain available for historical purposes." The last code
  change was December 2024 (search logging); 2025 and 2026 carry only a
  maintainer move and the archiving notice. Open issues: 0 (closed on
  archive). 4,784 stars, 959 forks, created May 2019 at Lyft.
- **Who used it.** 37 companies listed, among them Lyft, ING, Square,
  Instacart, Brex, Snap, Workday, Asana, Gusto, REA Group, Delivery Hero,
  WeTransfer, Remitly. Many have moved already; the listing is historical.
- **What they have now.** A Neo4j graph (or Atlas, Neptune, MySQL) holding
  tables, columns, descriptions with source attribution, owners, tags,
  badges, dashboards, users, table and column lineage, usage counts,
  column statistics, watermarks, last-updated timestamps, ML features,
  queries and applications; an Elasticsearch index; a Flask/React front
  end for analysts; and databuilder ETL jobs on a scheduler (usually
  Airflow) with 40+ extractors (Snowflake, BigQuery, Redshift, Hive,
  Postgres, MySQL, Oracle, MSSQL, Glue, Delta, Druid, dbt, Tableau, Mode,
  Redash, Superset, Databricks SQL, Kafka schema registry, OpenLineage).

## 2. What an Amundsen user actually relies on

Two different things, and the answer differs for each:

1. **The curated record**: descriptions people typed, owners, tags, badges
   (deprecated, PII, certified), bookmarks, and the ETL-fed facts (schema,
   stats, lineage, usage). This is the asset worth migrating.
2. **The consumer experience**: a search box an analyst opens daily,
   ranked by popularity, with table pages showing columns, stats, lineage,
   previews, "frequently used by", Jira issue creation, notifications,
   announcements, product tours. This is what they will miss.

## 3. Model coverage: Amundsen → Egeria

| Amundsen | Egeria | Fit |
|---|---|---|
| Database / Cluster / Schema / Table / Column (key `db://cluster.schema/table`) | Database, DeployedDatabaseSchema, RelationalTable, RelationalColumn, with qualifiedName derived from the key | full; "cluster" maps to the hosting server or an additionalProperty |
| description, with source (user, dbt, extractor) | `description`; source as RE's signed testimony with author and date | full, and better: RE keeps who said it |
| owner (user email) | `Ownership` classification to a UserIdentity, or Person via ActorProfile | full once the owner-fact ruling lands |
| tags | `InformalTag` (user tags) or `SearchKeyword`; curated tag sets as valid values | full |
| badges (non-editable, admin-set: pii, deprecated, certified) | governance classifications: Confidentiality, retirement notice, `Certification`; custom badges as a valid value set on a classification | full for the common badges; custom badges need a mapping table |
| users / profiles | UserIdentity, Person, Team | full |
| dashboards (Tableau, Mode, Redash, Superset) with charts, queries, owners, usage | `Report` / `DeployedReport` assets, `InformationView`; owner and tags as above | mostly; Egeria's report model is thinner than Amundsen's dashboard model (chart list, execution status, last run) → additionalProperties plus a note |
| table lineage (upstream/downstream, from OpenLineage or dbt) | `DataFlow` relationships between assets; `Process` for the job | full |
| column lineage | `DataMapping` / lineage between SchemaAttributes | full |
| application (Airflow DAG that writes the table) | `Process` + DataFlow; `ImplementedBy` | full |
| table and column statistics (pandas-profiling, ES matrix stats) | survey annotations: `ResourceProfileAnnotation`, `DataProfileAnnotation`, `ResourceMeasureAnnotation` on a SurveyReport | full, and RE already publishes these |
| last updated, watermarks (partition low/high) | `ResourceMeasureAnnotation` (interim) | adequate; no first-class watermark type |
| usage / popularity (reads per user, per table, from query logs) | none native; RE's registry can hold it and publish a measure annotation; Egeria's `Like` is a different thing | gap: popularity ranking in search is Amundsen's signature feature |
| queries (SQL text attached to tables), resource generation code | no obvious Egeria home; keep as annotations or RE rows | gap, minor |
| ML features (feature group, generation code) | unclear in Egeria's types; needs a check | unknown |
| bookmarks, "frequently used by" | `Like` for bookmarks; usage as above | partial |
| notifications, Jira issue creation, announcements, product tours | front-end features, not metadata | out of scope for Egeria; a consumer app concern |

Coverage of the record is high. The two real gaps are usage/popularity and
the dashboard model's depth, and both can be carried as annotations and
additional properties without losing the data.

## 4. How a migration would run

Amundsen's own tooling makes the export easy: databuilder's
`Neo4jExtractor` runs an arbitrary Cypher query and yields model objects,
and the metadata service's proxy API lists every resource kind. An
importer is therefore:

1. **Read the graph** by Cypher (one query per node kind, keyed by
   Amundsen's key), or through the metadata API where a user has Atlas or
   Neptune behind it.
2. **Write to Egeria through pyegeria**, the same channel RE uses, with
   the mapping in §3; descriptions become signed testimony with the
   Amundsen source as author; idempotent by qualifiedName derived from
   the Amundsen key; one proof row per element by GUID, RE's rules.
3. **Re-attach the live sources** through Egeria's connectors (JDBC
   cataloguer for any JDBC database, Unity Catalog, Kafka, files) so the
   schema facts stay fresh without databuilder; where no Egeria connector
   exists (BigQuery, Hive metastore, Glue, the BI tools) the databuilder
   extractor can keep running with its loader pointed at a small pyegeria
   publisher instead of Neo4j CSVs. That is a one-class change in their
   ETL, not a rewrite.
4. **Keep the Elasticsearch index out of it.** Egeria's search and RE's
   pgvector index replace it; nothing in the index is primary data.

For comparison, OpenMetadata's Amundsen connector reads Neo4j and migrates
databases, schemas, tables, tags, descriptions and owners, and states no
dashboards, no usage, no lineage. DataHub's path is similar. An importer
that also carries dashboards, lineage, stats and usage would be more
complete than either incumbent's, and the pieces are small: a Cypher
reader, about twelve mappings, and writes pyegeria already has.

## 5. Where RE fits, and where it does not

- **RE is the steward's tool.** Registration, survey, curation, publish
  with proof. For a migrated estate it is where the curated record is
  checked, where new sources are registered, and where the honesty rules
  (signed testimony, proof rows, "deleted in Egeria") give the record a
  provenance Amundsen never had.
- **RE's listers cover Postgres today.** Amundsen's users are mostly on
  Snowflake, BigQuery, Redshift and Hive. Registration of those goes
  through Egeria's connectors, not RE's survey, until RE grows listers;
  the design already allows a database RE did not survey.
- **RE is not the analyst's search page.** Amundsen's daily user is an
  analyst typing a table name. Egeria has the Portal's catalog apps and
  RE has none of that audience; the planned chat-first non-technical app
  on RE's data is the nearest thing and does not exist yet. This is the
  decisive gap for "migration path": the record migrates cleanly, the
  front door does not.

## 6. Verdict

**As a metadata backend: viable, and more complete than the incumbents'
importers.** The Amundsen record fits Egeria's types with two annotated
gaps, the export is one Cypher reader, and the write path exists.

**As a product an Amundsen shop can switch to this quarter: not yet.**
Missing are (a) a consumer search and table page with popularity
ranking, (b) listers or connectors for Snowflake, BigQuery and Hive on
the RE side, and (c) the importer itself. (b) is partly Egeria's JDBC
cataloguer already; (a) is a new surface and the larger build.

**Recommendation.** If the owner wants to pursue it: build the importer
first (small, provable, and a story on its own: "your Amundsen graph,
governed in Egeria with provenance"), prove it on a public Amundsen
sample graph, then decide on the front door, which is the chat-first
app's question in another form. Do not start with the UI.

## 7. Open questions for the owner

1. Is there an Amundsen user we can talk to about what they would need
   to keep, and what they would give up?
2. Does Egeria have a type for ML features and for stored SQL queries, or
   does the importer carry them as annotations until one exists?
3. Does the chat-first app's first instance want to be "the Amundsen
   front door", which would set its first consumer as the analyst rather
   than the data scientist?
